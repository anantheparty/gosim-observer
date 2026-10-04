"""Bounded local glass-phase expansion of the existing CPU spatial planner.

Only NumPy and the CPU SpatialPlanner are imported.  The inherited action is
retained unless an additional executable pointing has a strictly better exact
frozen-state rate.  Candidate ranking is local and uses fixed exposure times;
it does not establish global spatial or whole-season optimality.
"""
from __future__ import annotations

import math
import os
import time

import numpy as np

try:
    from .spatial_candidates import SpatialPlanner, DEG, PROGRAMS, parse_utc, local_sidereal
except ImportError:
    from spatial_candidates import SpatialPlanner, DEG, PROGRAMS, parse_utc, local_sidereal


def _basis(centers):
    centers = np.asarray(centers, dtype=float).reshape(-1, 2)
    a, z = centers[:, 0] * DEG, centers[:, 1] * DEG
    ca, sa, cz, sz = np.cos(a), np.sin(a), np.cos(z), np.sin(z)
    return (np.column_stack((ca * cz, ca * sz, sa)),
            np.column_stack((-sa * cz, -sa * sz, ca)),
            np.column_stack((-sz, cz, np.zeros(len(centers)))))


def local_phase_centers(planner, seed, pool, vectors, merit, boundary_target_count=8):
    """Represent planar glass-boundary cells around one seed.

    The event construction is planar; returned pointings are spherical unit
    vectors.  Later scoring always uses spherical gnomonic geometry.  Finite
    field edges are included as well as periodic glass edges.  ``pool`` is a
    small ranking pool, not the full catalogue.
    """
    center, north, east = (x[0] for x in _basis([seed]))
    depth = vectors[pool] @ center
    dn = (vectors[pool] @ north) / np.maximum(depth, 1e-12) / DEG
    de = (vectors[pool] @ east) / np.maximum(depth, 1e-12) / DEG
    relevant = np.flatnonzero((depth > 0) &
                             (np.maximum(np.abs(dn), np.abs(de)) <= (planner.fov + planner.pitch) / 2))
    relevant = relevant[np.lexsort((pool[relevant], -merit[pool[relevant]]))[:boundary_target_count]]
    axes = []
    half = planner.glass / 2 - .008
    for offsets in (dn[relevant], de[relevant]):
        parity = .5 if planner.side % 2 == 0 else 0.
        nominal_cell = np.rint(offsets / planner.pitch - parity) + parity
        glass_events = np.r_[offsets - nominal_cell * planner.pitch - half,
                             offsets - nominal_cell * planner.pitch + half]
        glass_events = (glass_events + planner.pitch / 2) % planner.pitch - planner.pitch / 2
        field_events = np.r_[offsets - planner.fov / 2, offsets + planner.fov / 2]
        field_events = field_events[np.abs(field_events) <= planner.pitch / 2]
        events = np.unique(np.round(np.r_[glass_events, field_events,
                                          -planner.pitch / 2, planner.pitch / 2], 10))
        axes.append(np.r_[0., (events[1:] + events[:-1]) / 2])
    dn_grid, de_grid = np.meshgrid(*axes, indexing="ij")
    shifted = (center + dn_grid.ravel()[:, None] * DEG * north
               + de_grid.ravel()[:, None] * DEG * east)
    shifted /= np.linalg.norm(shifted, axis=1)[:, None]
    phases = np.column_stack((np.arcsin(np.clip(shifted[:, 2], -1, 1)) / DEG,
                              np.arctan2(shifted[:, 1], shifted[:, 0]) / DEG % 360))
    return phases[(phases[:, 0] >= 0) & (phases[:, 0] <= 90)], len(relevant)


def coarse_numpy_local(planner, centers, pool, frame, durations, batch_size=256):
    """Exact fixed-duration/three-program rates on the supplied local pool.

    Fibre collisions use per-fibre maxima.  The focus request uses the same
    quota-regret calculation as SpatialPlanner._evaluate.  Approximation is
    confined to the restricted pool, duration grid, and spatial candidates.
    Working storage is bounded by ``batch_size * 3 * (len(pool) + n_fibres)``.
    """
    vectors, up, k, scores, factors, multiplier, missing, rr, rt, rd, ub, urgency, _, safety, focus = frame
    rates = np.zeros(len(centers))
    if not len(pool):
        return rates
    weights, kp = planner.weight[pool], k[pool]
    for start in range(0, len(centers), batch_size):
        stop = min(start + batch_size, len(centers))
        center, north, east = _basis(centers[start:stop])
        pv = vectors[pool]
        depth = np.einsum("ij,kj->ki", pv, center)
        dn = np.einsum("ij,kj->ki", pv, north) / np.maximum(depth, 1e-12) / DEG
        de = np.einsum("ij,kj->ki", pv, east) / np.maximum(depth, 1e-12) / DEG
        row = np.clip(np.floor(dn / planner.pitch + planner.side / 2).astype(np.int32), 0, planner.side - 1)
        col = np.clip(np.floor(de / planner.pitch + planner.side / 2).astype(np.int32), 0, planner.side - 1)
        cn, ce = (row - (planner.side - 1) / 2) * planner.pitch, (col - (planner.side - 1) / 2) * planner.pitch
        margin = planner.glass / 2 - np.maximum(np.abs(dn - cn), np.abs(de - ce))
        valid = ((depth > 0) & (np.abs(dn) <= planner.fov / 2) &
                 (np.abs(de) <= planner.fov / 2) & (margin >= .008))
        fibers = row * planner.side + col
        count = stop - start
        offsets = (np.arange(count)[:, None, None] * 3 * planner.nfib
                   + np.arange(3)[None, :, None] * planner.nfib + fibers[:, None, :])
        offsets = offsets.ravel()
        batch_rates = np.zeros(count)
        for duration in durations:
            raw = np.minimum(1., duration * kp)
            robust = np.minimum(1., duration * kp / safety)
            terminal = missing[pool] * (robust + 1e-10 >= planner.req_threshold) * planner.req_penalty
            terminal += ((factors[pool] < planner.uniform_threshold)
                         * (robust + 1e-10 >= planner.uniform_threshold) * ub[pool])
            terminal += ((rr[pool] > 0) * (robust + 1e-10 >= rt[pool])
                         * (duration <= rd[pool]) * rr[pool])
            focus_eligible = None
            if focus is not None:
                membership, reward, left, threshold, deadline = focus
                focus_eligible = membership[pool] & (robust + 1e-10 >= threshold) & (duration <= deadline)
                terminal -= focus_eligible * (reward / left)
            science = np.maximum(0., weights[None, :] * raw[None, :] * multiplier[:, pool] - scores[pool][None, :])
            value = (science + terminal[None, :]) * urgency[pool][None, :]
            allowed = valid & (duration <= up[pool][None, :])
            values = np.where(allowed[:, None, :], value[None, :, :], -np.inf)
            cells = np.zeros((count, 3, planner.nfib))
            np.maximum.at(cells.ravel(), offsets, values.ravel())
            total = cells.sum(axis=2)
            if focus_eligible is not None:
                eligible_cells = np.full_like(cells, -np.inf)
                eligible_values = np.where(focus_eligible[None, None, :], values, -np.inf)
                np.maximum.at(eligible_cells.ravel(), offsets, eligible_values.ravel())
                regrets = cells - eligible_cells
                ordered = np.sort(regrets, axis=2)[:, :, :min(left, planner.nfib)]
                possible = (left <= planner.nfib) & (np.sum(np.isfinite(regrets), axis=2) >= left)
                full = np.where(possible, total + reward - ordered.sum(axis=2), -np.inf)
                partial = total + np.maximum(0., reward / left - ordered).sum(axis=2)
                total = np.where(possible, np.maximum(total, full), partial)
            batch_rates = np.maximum(batch_rates, total.max(axis=1) / duration)
        rates[start:stop] = batch_rates
    return rates


class CPUPhaseSpatialPlanner(SpatialPlanner):
    """SpatialPlanner interface with a bounded, optional CPU-only expansion.

    Added work has hard limits: four seeds, 64 ranking targets per seed, 24
    boundary targets, 16 duration values, 16 exact evaluations.  Defaults are
    four seeds, 50 ranking targets, 24 boundary targets and 16 exact probes.
    The default cpu_phase_fixed_workload=True completes inherited choose's
    bounded loops (eight anchors by default, at most 24) as well as the phase work.  Set False
    to retain its ordinary planning budget.  ``cpu_phase_mode='bypass'`` or environment
    ``GOSIM_CPU_PHASE_MODE=bypass`` returns the inherited action and prediction.
    """

    def __init__(self, initial_payload):
        super().__init__(initial_payload)
        self.cpu_phase_summary = {
            "choose_calls": 0, "phase_calls": 0, "phase_candidates": 0,
            "phase_exact_evaluations": 0, "phase_emergency_count": 0,
            "phase_improvements": 0,
        }

    def _publish_summary(self):
        self.stats.update({f"{name}_total": value for name, value in self.cpu_phase_summary.items()})

    def _evaluate(self, center, pool, *frame):
        candidate = super()._evaluate(center, pool, *frame)
        if getattr(self, "_cpu_phase_capture", False):
            if self._cpu_phase_frame is None:
                self._cpu_phase_frame = frame
            if candidate is not None:
                self._cpu_phase_baseline_candidates.append(candidate)
        return candidate

    def _merit(self, frame):
        vectors, up, k, scores, _, multiplier, missing, rr, rt, _, _, urgency, seconds_left, safety, _ = frame
        visible = (vectors[:, 2] >= math.sin((self.min_alt + .04) * DEG)) & (up >= self.tmin)
        raw = np.minimum(1., k * np.minimum(up, seconds_left) / safety)
        merit = np.maximum(0., self.weight * raw * multiplier.max(axis=0) - scores) * np.minimum(1., k * 900)
        merit += missing * (raw >= self.req_threshold) * self.req_penalty * np.minimum(1., k * 900 / self.req_threshold)
        merit += ((rr > 0) * (raw >= rt) * rr * np.minimum(1., k * 900 / np.maximum(rt, .01)))
        return merit * urgency * visible

    def choose(self, snapshot, best_scores, best_factors, env_estimate=None, active_requests=None):
        started = time.perf_counter()
        env = dict(env_estimate or {})
        mode = env.get("cpu_phase_mode", os.environ.get("GOSIM_CPU_PHASE_MODE", "phase"))
        fixed_workload = bool(env.get("cpu_phase_fixed_workload", True))
        if fixed_workload:
            env["planning_budget_seconds"] = 1e9
            env["anchor_count"] = min(24, max(1, int(env.get("anchor_count", 8))))
        self.cpu_phase_summary["choose_calls"] += 1
        self._cpu_phase_frame = None
        self._cpu_phase_baseline_candidates = []
        self._cpu_phase_capture = mode != "bypass"
        self.stats = {}
        try:
            baseline = super().choose(snapshot, best_scores, best_factors, env, active_requests)
        finally:
            self._cpu_phase_capture = False
        self.cpu_phase_baseline_action = baseline
        self.stats.update(cpu_phase_mode=mode, phase_fixed_workload=fixed_workload,
                          phase_improved=False, phase_exact_evaluations=0, phase_emergency_triggered=False)
        if baseline is None or mode == "bypass" or self._cpu_phase_frame is None:
            self._publish_summary()
            return baseline

        self.cpu_phase_summary["phase_calls"] += 1
        frame = self._cpu_phase_frame
        ordered = sorted(self._cpu_phase_baseline_candidates, key=lambda candidate: -candidate[0])
        baseline_rate = float(ordered[0][0])
        self.stats.update(base_exact_rate=baseline_rate, selected_exact_rate=baseline_rate)
        top_count = min(4, max(1, int(env.get("cpu_phase_top_count", 4))))
        target_count = min(64, max(1, int(env.get("cpu_phase_local_target_count", 50))))
        boundary_count = min(24, max(1, int(env.get("cpu_phase_boundary_target_count", 24))))
        exact_count = min(16, max(1, int(env.get("cpu_phase_exact_count", 16))))
        batch_size = min(512, max(16, int(env.get("cpu_phase_batch_size", 256))))
        seeds = []
        separation = math.cos(.35 * self.pitch * DEG)
        for candidate in ordered:
            seed = tuple(candidate[1])
            vector = _basis([seed])[0][0]
            if all(float(vector @ prior[1]) < separation for prior in seeds):
                seeds.append((seed, vector, candidate[4]))
            if len(seeds) == top_count:
                break

        build_start = time.perf_counter()
        vectors = frame[0]
        merit = self._merit(frame)
        useful = np.flatnonzero(merit > 1e-10)
        # Spherical triangle inequality: all targets of every shifted field
        # lie in this seed cap.  Exact refinement uses the entire cap pool.
        radius = math.atan(self.fov / math.sqrt(2) * DEG) + math.atan(self.pitch / math.sqrt(2) * DEG) + 1e-8
        cap_cosine = math.cos(radius)
        groups, local_counts, full_counts, boundary_counts = [], [], [], []
        offset_alt = float(env.get("pointing_offset_alt_deg", 0.))
        offset_az = float(env.get("pointing_offset_az_deg", 0.))
        for seed, seed_vector, seed_assignments in seeds:
            dot = np.einsum("ij,j->i", vectors[useful], seed_vector)
            full_pool = useful[dot >= cap_cosine]
            ranked = full_pool[np.lexsort((full_pool, -merit[full_pool]))]
            # Keep the seed's own assigned targets in the bounded ranking
            # pool, so pruning does not erase its known good fibre choices.
            protected = seed_assignments[np.isin(seed_assignments, full_pool)]
            pool = np.asarray(list(dict.fromkeys(np.r_[protected, ranked].tolist()))[:target_count], dtype=int)
            if not len(pool):
                continue
            phases, used_boundaries = local_phase_centers(self, seed, pool, vectors, merit, boundary_count)
            # Score the center that the rounded command will actually execute.
            command_alt = np.round(phases[:, 0] - offset_alt, 7)
            command_az = np.round((phases[:, 1] - offset_az) % 360, 7)
            valid = (command_alt >= 0) & (command_alt <= 90)
            phases = np.column_stack((command_alt[valid] + offset_alt,
                                       (command_az[valid] + offset_az) % 360))
            phases = np.unique(phases, axis=0)
            groups.append((phases, pool, full_pool))
            local_counts.append(len(pool))
            full_counts.append(len(full_pool))
            boundary_counts.append(used_boundaries)
        built = time.perf_counter()
        if not groups:
            self._publish_summary()
            return baseline
        seconds_left = frame[12]
        durations = env.get("cpu_phase_durations", (self.tmin, 120, 240, 400, 900, 1800,
                                                     seconds_left, baseline["duration_seconds"]))
        durations = np.unique(np.clip(np.asarray(durations, dtype=np.int32).ravel(), self.tmin, seconds_left))
        if not len(durations):
            durations = np.asarray([self.tmin], dtype=np.int32)
        if len(durations) > 16:
            durations = durations[np.unique(np.rint(np.linspace(0, len(durations) - 1, 16)).astype(int))]
        centers, rates, group_ids = [], [], []
        for group_index, (phases, pool, _) in enumerate(groups):
            centers.append(phases)
            rates.append(coarse_numpy_local(self, phases, pool, frame, durations, batch_size))
            group_ids.append(np.full(len(phases), group_index, dtype=np.int32))
        centers, rates, group_ids = np.vstack(centers), np.concatenate(rates), np.concatenate(group_ids)
        scanned = time.perf_counter()
        order = np.lexsort((np.arange(len(rates)), -rates))
        seen = set()
        best, best_rate, evaluated = None, baseline_rate, 0
        exact_seed_counts = [0] * len(groups)
        for i in order:
            center = tuple(centers[i])
            if center in seen:
                continue
            seen.add(center)
            candidate = super()._evaluate(center, groups[int(group_ids[i])][2], *frame)
            evaluated += 1
            exact_seed_counts[int(group_ids[i])] += 1
            if candidate is not None and candidate[0] > best_rate + 1e-12:
                best, best_rate = candidate, float(candidate[0])
            if evaluated == exact_count:
                break
        self.stats.update(
            phase_candidates=len(centers), phase_seeds=len(groups), phase_local_counts=local_counts,
            phase_full_local_counts=full_counts, phase_boundary_counts=boundary_counts,
            phase_duration_count=len(durations), phase_durations=durations.tolist(),
            phase_exact_evaluations=evaluated, phase_build_seconds=built - build_start,
            phase_exact_seed_counts=exact_seed_counts,
            phase_scan_seconds=scanned - built, phase_exact_seconds=time.perf_counter() - scanned,
            phase_improved=best is not None, selected_exact_rate=best_rate,
            phase_geometry_target_pairs=sum(len(phases) * len(pool) for phases, pool, _ in groups),
            planning_seconds=time.perf_counter() - started,
        )
        self.cpu_phase_summary["phase_candidates"] += len(centers)
        self.cpu_phase_summary["phase_exact_evaluations"] += evaluated
        self.cpu_phase_summary["phase_improvements"] += best is not None
        self._publish_summary()
        if best is None:
            return baseline

        _, center, duration, program, chosen, fibers = best
        now = parse_utc(snapshot["now_utc"])
        lst = local_sidereal(now, self.lon)
        alt = np.arcsin(np.clip(vectors[:, 2], -1, 1)) / DEG
        az = np.arctan2(vectors[:, 1], vectors[:, 0]) / DEG % 360
        public_quality = self._public_quality(now, lst, alt)
        quality_scale = max(.005, float(env.get("quality_scale", .55)))
        band_scale = max(.005, float(env.get("program_band_quality_scale", quality_scale / .95)))
        actual_bands = np.where(public_quality * band_scale >= self.dark_threshold, 0,
                               np.where(public_quality * band_scale >= self.bright_threshold, 1, 2))
        k = frame[2]
        quality = k * self.f0t0 / np.maximum(self.flux, 1e-12)
        target_scale = np.ones(self.n) if env.get("target_quality_scale") is None else np.asarray(env["target_quality_scale"], dtype=float)
        directional = quality / np.maximum(1e-12, public_quality * quality_scale * target_scale)
        self.last_prediction = {
            self.ids[int(i)]: {"index": int(i), "fiber_id": int(f), "factor": min(1., float(k[i] * duration)),
                              "public_quality": float(public_quality[i]), "quality": float(quality[i]),
                              "directional_scale": float(directional[i]), "predicted_band": PROGRAMS[int(actual_bands[i])],
                              "alt_deg": float(alt[i]), "az_deg": float(az[i])}
            for i, f in zip(chosen, fibers)
        }
        self.stats["planning_seconds"] = time.perf_counter() - started
        return {"action": "observe", "pointing": {"alt_deg": round(center[0] - offset_alt, 7),
                                                   "az_deg": round((center[1] - offset_az) % 360, 7)},
                "assignments": {str(int(f)): self.ids[int(i)] for i, f in zip(chosen, fibers)},
                "duration_seconds": int(duration), "program": PROGRAMS[int(program)]}
