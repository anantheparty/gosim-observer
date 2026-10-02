"""Optional planar glass-arrangement candidates evaluated with spherical geometry."""
from __future__ import annotations

import math
import time

import numpy as np

try:
    from .gpu_spatial_candidates import GPUSpatialPlanner
    from .spatial_candidates import DEG, PROGRAMS, parse_utc, local_sidereal
except ImportError:
    from gpu_spatial_candidates import GPUSpatialPlanner
    from spatial_candidates import DEG, PROGRAMS, parse_utc, local_sidereal


def phase_centers(planner, frame, seeds, local_target_limit=24):
    vectors, up, k, scores, factors, multiplier, missing, rr, rt, rd, ub, urgency, seconds_left, safety, _ = frame
    merit = (np.maximum(0, planner.weight * np.minimum(1., 400 * k) * multiplier.max(axis=0) - scores)
             + missing * planner.req_penalty * (k * seconds_left / safety >= planner.req_threshold)
             + rr * (k * seconds_left / safety >= rt)) * urgency
    answer, local_counts = [], []
    for alt, az in seeds:
        a, z = alt * DEG, az * DEG
        basis = np.array([[math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)],
                          [-math.sin(a) * math.cos(z), -math.sin(a) * math.sin(z), math.cos(a)],
                          [-math.sin(z), math.cos(z), 0.]])
        projection = vectors @ basis.T
        north = projection[:, 1] / np.maximum(projection[:, 0], 1e-12) / DEG
        east = projection[:, 2] / np.maximum(projection[:, 0], 1e-12) / DEG
        relevant = np.flatnonzero((projection[:, 0] > 0) & (np.maximum(np.abs(north), np.abs(east)) < (planner.fov + planner.pitch) / 2)
                                 & (up >= planner.tmin) & (merit > 0))
        if local_target_limit:
            relevant = relevant[np.lexsort((relevant, -merit[relevant]))[:local_target_limit]]
        local_counts.append(len(relevant))
        axes = []
        half = planner.glass / 2 - .008
        for offsets in (north[relevant], east[relevant]):
            parity = .5 if planner.side % 2 == 0 else 0.
            nominal_cell = np.rint(offsets / planner.pitch - parity) + parity
            events = np.concatenate((offsets - nominal_cell * planner.pitch - half,
                                     offsets - nominal_cell * planner.pitch + half))
            events = (events + planner.pitch / 2) % planner.pitch - planner.pitch / 2
            events = np.unique(np.round(np.r_[events, -planner.pitch / 2, planner.pitch / 2], 10))
            axes.append(np.r_[0., (events[1:] + events[:-1]) / 2])
        dn, de = np.meshgrid(*axes, indexing="ij")
        shifted = basis[0] + dn.ravel()[:, None] * DEG * basis[1] + de.ravel()[:, None] * DEG * basis[2]
        shifted /= np.linalg.norm(shifted, axis=1)[:, None]
        local = np.column_stack((np.arcsin(np.clip(shifted[:, 2], -1, 1)) / DEG,
                                 np.arctan2(shifted[:, 1], shifted[:, 0]) / DEG % 360))
        answer.append(local[(local[:, 0] >= 0) & (local[:, 0] <= 90)])
    if not answer:
        return np.empty((0, 2)), local_counts
    return np.unique(np.round(np.vstack(answer), 7), axis=0), local_counts


class PhaseGPUSpatialPlanner(GPUSpatialPlanner):
    """Same interface. gpu_phase_mode='bypass' is an exact backend control.

    Expansion work is fixed by gpu_phase_top_count=16,
    gpu_phase_local_target_count=24 and gpu_phase_exact_count=64.
    gpu_phase_emergency_seconds=3 only guards the extra exact stage.
    The base action and prediction are retained unless the spherical exact
    objective strictly improves. No whole-season monotonicity is claimed.
    """

    def choose(self, snapshot, best_scores, best_factors, env_estimate=None, active_requests=None):
        env = dict(env_estimate or {})
        started = time.perf_counter()
        baseline = super().choose(snapshot, best_scores, best_factors, env, active_requests)
        self.stats = {**self.stats, "phase_mode": env.get("gpu_phase_mode", "phase")}
        if baseline is None or env.get("gpu_phase_mode", "phase") == "bypass":
            return baseline
        frame = self._frame
        centers, rates = self.last_candidate_centers, self.last_coarse_rates
        top_count = min(len(centers), max(1, int(env.get("gpu_phase_top_count", 16))))
        seeds = centers[np.lexsort((np.arange(len(rates)), -rates))[:top_count]]
        prepare_start = time.perf_counter()
        phases, local_counts = phase_centers(self, frame, seeds, max(1, int(env.get("gpu_phase_local_target_count", 24))))
        prepared = time.perf_counter()
        if not len(phases):
            return baseline
        _, useful = self._build_centers(frame, env)
        phase_rates, _ = self.coarse_gpu(phases, useful, frame, env)
        scanned = time.perf_counter()
        vectors, up, k, scores, factors, multiplier, missing, rr, rt, rd, ub, urgency, seconds_left, safety, focus = frame
        best, best_rate = None, float(self.stats["selected_exact_rate"])
        baseline_rate = best_rate
        evaluated = 0
        emergency = False
        exact_count = min(len(phases), max(1, int(env.get("gpu_phase_exact_count", 64))))
        order = np.lexsort((np.arange(len(phases)), -phase_rates))[:exact_count]
        for i in order:
            if time.perf_counter() - scanned > float(env.get("gpu_phase_emergency_seconds", 3.0)):
                emergency = True
                break
            center = tuple(phases[i])
            a, z = center[0] * DEG, center[1] * DEG
            cvec = np.array([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])
            pool = useful[np.sum(vectors[useful] * cvec, axis=1) >= math.cos(self.fov * DEG)]
            candidate = self._evaluate(center, pool, *frame)
            evaluated += 1
            if candidate and candidate[0] > best_rate + 1e-12:
                best, best_rate = candidate, float(candidate[0])
        self.stats.update(phase_candidates=len(phases), phase_seeds=top_count, phase_local_counts=local_counts,
                          phase_exact_evaluations=evaluated, phase_emergency_triggered=emergency,
                          phase_build_seconds=prepared-prepare_start, phase_scan_seconds=scanned-prepared,
                          phase_exact_seconds=time.perf_counter()-scanned,
                          base_exact_rate=baseline_rate, selected_exact_rate=best_rate,
                          phase_improved=best is not None, planning_seconds=time.perf_counter()-started)
        if best is None:
            return baseline
        _, center, duration, program, chosen, fibers = best
        offset_alt = float(env.get("pointing_offset_alt_deg", 0))
        offset_az = float(env.get("pointing_offset_az_deg", 0))
        cmd_alt = center[0] - offset_alt
        if not 0 <= cmd_alt <= 90:
            self.stats.update(phase_improved=False, selected_exact_rate=baseline_rate)
            return baseline
        now = parse_utc(snapshot["now_utc"])
        lst = local_sidereal(now, self.lon)
        alt, az, _, _ = self._altaz(lst)
        public_quality = self._public_quality(now, lst, alt)
        band_scale = float(env.get("program_band_quality_scale", float(env.get("quality_scale", .55))/.95))
        actual_bands = np.where(public_quality * band_scale >= self.dark_threshold, 0,
                               np.where(public_quality * band_scale >= self.bright_threshold, 1, 2))
        quality = k * self.f0t0 / np.maximum(self.flux, 1e-12)
        self.last_prediction = {self.ids[int(i)]: {"index": int(i), "fiber_id": int(f), "factor": min(1., float(k[i]*duration)),
                                                  "public_quality": float(public_quality[i]), "quality": float(quality[i]),
                                                  "directional_scale": float(quality[i]/max(1e-12, public_quality[i]*float(env.get("quality_scale", .55)))),
                                                  "predicted_band": PROGRAMS[int(actual_bands[i])], "alt_deg": float(alt[i]), "az_deg": float(az[i])}
                                for i, f in zip(chosen, fibers)}
        return {"action": "observe", "pointing": {"alt_deg": round(cmd_alt, 7), "az_deg": round((center[1]-offset_az)%360, 7)},
                "assignments": {str(int(f)): self.ids[int(i)] for i, f in zip(chosen, fibers)},
                "duration_seconds": int(duration), "program": PROGRAMS[int(program)]}
