"""RTX PRO 6000 backend: broad CUDA pointing scan, then exact CPU refinement.

Uses the already provisioned Numba-CUDA runtime, not a model or training engine.
All geometry runs in float64.  The coarse stage keeps the CPU planner's frozen-Q
value model and evaluates every program at a modest common duration grid.  Only
its ranking is approximate; final actions use CPU target-derived breakpoints and
quota handling.  Public-input interface matches SpatialPlanner.choose.
"""
from __future__ import annotations

import math
import time

import numpy as np
from numba import cuda

try:
    from .spatial_candidates import SpatialPlanner, DEG, PROGRAMS, SIDEREAL_SPEED, parse_utc, local_sidereal, _shift_altaz
except ImportError:  # task-specific deployment may use flat modules
    from spatial_candidates import SpatialPlanner, DEG, PROGRAMS, SIDEREAL_SPEED, parse_utc, local_sidereal, _shift_altaz


@cuda.jit(cache=True)
def _coarse_geometry_value(vectors, centers, up, k, scores, weights, factors,
                           multipliers, missing, request_reward, request_threshold,
                           request_deadline, uniform_bonus, urgency, durations,
                           side, nfib, glass, pitch, fov, safety,
                           req_threshold, req_penalty, uniform_threshold, cell_values):
    pair = cuda.grid(1)
    nt = vectors.shape[0]
    if pair >= centers.shape[0] * nt:
        return
    c = pair // nt
    i = pair - c * nt
    depth = vectors[i, 0] * centers[c, 0] + vectors[i, 1] * centers[c, 1] + vectors[i, 2] * centers[c, 2]
    if depth <= 0.0:
        return
    dn = (vectors[i, 0] * centers[c, 3] + vectors[i, 1] * centers[c, 4] + vectors[i, 2] * centers[c, 5]) / depth / DEG
    de = (vectors[i, 0] * centers[c, 6] + vectors[i, 1] * centers[c, 7] + vectors[i, 2] * centers[c, 8]) / depth / DEG
    if abs(dn) > fov / 2.0 or abs(de) > fov / 2.0:
        return
    row = min(side - 1, max(0, int(math.floor(dn / pitch + side / 2.0))))
    col = min(side - 1, max(0, int(math.floor(de / pitch + side / 2.0))))
    cn = (row - (side - 1) / 2.0) * pitch
    ce = (col - (side - 1) / 2.0) * pitch
    margin = glass / 2.0 - max(abs(dn - cn), abs(de - ce))
    if margin < .008:
        return
    fiber = row * side + col
    for d in range(durations.shape[0]):
        t = durations[d]
        if t > up[i]:
            continue
        raw = min(1.0, t * k[i])
        robust = min(1.0, t * k[i] / safety)
        terminal = 0.0
        if missing[i] and robust + 1e-10 >= req_threshold:
            terminal += req_penalty
        if factors[i] < uniform_threshold and robust + 1e-10 >= uniform_threshold:
            terminal += uniform_bonus[i]
        if request_reward[i] > 0 and robust + 1e-10 >= request_threshold[i] and t <= request_deadline[i]:
            terminal += request_reward[i]
        for p in range(3):
            science = max(0.0, weights[i] * raw * multipliers[p, i] - scores[i])
            value = (science + terminal) * urgency[i]
            if value > 0.0:
                cell = ((c * durations.shape[0] + d) * 3 + p) * nfib + fiber
                cuda.atomic.max(cell_values, cell, value)


@cuda.jit(cache=True)
def _coarse_reduce(cell_values, durations, nfib, rates):
    c = cuda.grid(1)
    if c >= rates.shape[0]:
        return
    best = 0.0
    for d in range(durations.shape[0]):
        for p in range(3):
            total = 0.0
            base = ((c * durations.shape[0] + d) * 3 + p) * nfib
            for f in range(nfib):
                total += cell_values[base + f]
            value = total / durations[d]
            if value > best:
                best = value
    rates[c] = best


def _center_basis(centers):
    a, z = centers[:, 0] * DEG, centers[:, 1] * DEG
    ca, sa, cz, sz = np.cos(a), np.sin(a), np.cos(z), np.sin(z)
    return np.ascontiguousarray(np.column_stack((ca * cz, ca * sz, sa, -sa * cz, -sa * sz, ca, -sz, cz, np.zeros(len(centers)))))


class GPUSpatialPlanner(SpatialPlanner):
    """Persistent planner suitable for the parent HTTP service.

    env options: gpu_anchor_count=320, gpu_max_candidates=8192,
    gpu_refine_count=48, gpu_refine_budget_seconds=.30,
    gpu_candidate_centers (explicit centers for reproducible benchmarking).
    gpu_fixed_workload=True replaces the normal wallclock cutoff with
    gpu_exact_candidate_count=256 initial evaluations and
    gpu_refinement_steps=32 spatial probes. gpu_emergency_seconds=3 is only
    an emergency cutoff in that mode. Equal coarse rates use index order.
    CUDA context and kernels are initialized at first choose; warm up before
    allowing platform requests.  The best CPU-baseline candidates are always
    included in the refinement pool.
    """
    def __init__(self, initial_payload):
        super().__init__(initial_payload)
        if not cuda.is_available():
            raise RuntimeError("CUDA unavailable in this runtime")
        device_name = cuda.get_current_device().name
        self.device_name = device_name.decode(errors="replace") if isinstance(device_name, bytes) else str(device_name)
        self._collecting = False
        self._frame = None
        self._cpu_centers = []
        self.last_coarse_rates = None
        self.last_candidate_centers = None
        self.gpu_warmed = False

    def _evaluate(self, *args, **kwargs):
        if self._collecting:
            if self._frame is None:
                self._frame = args[2:]
            self._cpu_centers.append(tuple(args[0]))
            return None
        return super()._evaluate(*args, **kwargs)

    def _build_centers(self, frame, env):
        vectors, up, k, scores, factors, multiplier, missing, request_reward, request_threshold, _, _, urgency, seconds_left, safety, _ = frame
        visible = (vectors[:, 2] >= math.sin((self.min_alt + .04) * DEG)) & (up >= self.tmin)
        raw = np.minimum(1., k * np.minimum(up, seconds_left) / safety)
        merit = np.maximum(0., self.weight * raw * multiplier.max(axis=0) - scores) * np.minimum(1., k * 900)
        merit += missing * (raw >= self.req_threshold) * self.req_penalty * np.minimum(1., k * 900 / self.req_threshold)
        merit += (request_reward > 0) * (raw >= request_threshold) * request_reward * np.minimum(1., k * 900 / np.maximum(request_threshold, .01))
        merit *= urgency * visible
        useful = np.flatnonzero(merit > 1e-10)
        if not len(useful):
            return np.empty((0, 2)), useful
        if env.get("gpu_candidate_centers") is not None:
            return np.asarray(env["gpu_candidate_centers"], dtype=float), useful
        count = min(len(useful), max(128, int(env.get("gpu_anchor_count", 320))))
        bins = np.bincount(self.space_bins, weights=merit, minlength=self.bin_count)
        bin_order = np.argsort(bins)[::-1]
        order = useful[np.argsort(merit[useful])[::-1]]
        # Dense regions and individual completion opportunities receive equal
        # seed budgets; the remainder is filled with distinct catalogue anchors.
        dense_anchors = []
        for b in bin_order:
            if bins[b] <= 0 or len(dense_anchors) >= count // 2:
                break
            members = np.flatnonzero((self.space_bins == b) & (merit > 0))
            dense_anchors.append(int(members[np.argmax(merit[members])]))
        anchors = list(dict.fromkeys(dense_anchors + order.tolist()))[:count]
        anchors = np.asarray(anchors, dtype=int)
        v = vectors[anchors]
        az = np.arctan2(v[:, 1], v[:, 0])
        alt = np.arcsin(np.clip(v[:, 2], -1, 1))
        north = np.column_stack((-np.sin(alt) * np.cos(az), -np.sin(alt) * np.sin(az), np.cos(alt)))
        east = np.column_stack((-np.sin(az), np.cos(az), np.zeros(len(anchors))))
        fibers = np.arange(self.nfib)
        if self.nfib > 25:
            axes = np.unique(np.rint(np.linspace(0, self.side - 1, 5)).astype(int))
            fibers = np.asarray([r * self.side + c for r in axes for c in axes])
        rows, cols = np.divmod(fibers, self.side)
        dn = -(rows - (self.side - 1) / 2.) * self.pitch * DEG
        de = -(cols - (self.side - 1) / 2.) * self.pitch * DEG
        pointing = v[:, None, :] + dn[None, :, None] * north[:, None, :] + de[None, :, None] * east[:, None, :]
        pointing = pointing.reshape(-1, 3)
        pointing /= np.linalg.norm(pointing, axis=1)[:, None]
        centers = np.column_stack((np.arcsin(np.clip(pointing[:, 2], -1, 1)) / DEG,
                                   np.arctan2(pointing[:, 1], pointing[:, 0]) / DEG % 360.))
        centers = np.vstack((np.asarray(self._cpu_centers), centers))
        centers = np.unique(np.round(centers, 7), axis=0)
        centers = centers[(centers[:, 0] >= 0) & (centers[:, 0] <= 90)]
        maximum = int(env.get("gpu_max_candidates", 8192))
        if len(centers) > maximum:
            centers = centers[np.unique(np.rint(np.linspace(0, len(centers) - 1, maximum)).astype(int))]
        return centers, useful

    def coarse_gpu(self, centers, useful, frame, env=None):
        """Return frozen-Q coarse rates; exposed for CPU/GPU cross-checks."""
        env = env or {}
        vectors, up, k, scores, factors, multiplier, missing, request_reward, request_threshold, request_deadline, uniform_bonus, urgency, seconds_left, safety, _ = frame
        durations = list((self.tmin, 120, 180, 240, 330, 450, 600, 780, 1020, 1380, 1800, 2400, 3000, self.tmax, seconds_left))
        thresholds = self.req_threshold * safety / np.maximum(k[useful][missing[useful]], 1e-12)
        thresholds = thresholds[(thresholds >= self.tmin) & (thresholds <= seconds_left)]
        if len(thresholds):
            durations += np.ceil(np.quantile(thresholds, (.1, .25, .5, .75, .9))).tolist()
        if env.get("gpu_coarse_durations") is not None:
            durations = env["gpu_coarse_durations"]
        durations = np.unique(np.clip(np.asarray(durations, dtype=np.int32), self.tmin, seconds_left))
        arrays = (vectors[useful], _center_basis(centers), up[useful], k[useful], scores[useful], self.weight[useful], factors[useful],
                  multiplier[:, useful], missing[useful], request_reward[useful], request_threshold[useful], request_deadline[useful],
                  uniform_bonus[useful], urgency[useful], durations)
        device = [cuda.to_device(np.ascontiguousarray(a)) for a in arrays]
        nvalues = len(centers) * len(durations) * 3 * self.nfib
        cell_values = cuda.to_device(np.zeros(nvalues, dtype=np.float64))
        rates = cuda.device_array(len(centers), dtype=np.float64)
        threads = 256
        _coarse_geometry_value[(len(centers) * len(useful) + threads - 1) // threads, threads](
            *device, self.side, self.nfib, self.glass, self.pitch, self.fov, safety,
            self.req_threshold, self.req_penalty, self.uniform_threshold, cell_values)
        _coarse_reduce[(len(centers) + threads - 1) // threads, threads](cell_values, device[-1], self.nfib, rates)
        out = rates.copy_to_host()
        self.gpu_warmed = True
        return out, durations

    def coarse_numpy(self, centers, useful, frame, durations):
        """Independent vectorized CPU calculation of exactly the coarse objective."""
        vectors, up, k, scores, factors, multiplier, missing, request_reward, request_threshold, request_deadline, uniform_bonus, urgency, _, safety, _ = frame
        result = np.zeros(len(centers))
        for c, center in enumerate(centers):
            fibers, valid, _ = self._classify(vectors[useful], *center)
            idx, fibers = useful[valid], fibers[valid]
            if not len(idx):
                continue
            t = durations[:, None]
            raw = np.minimum(1., t * k[idx][None, :])
            robust = np.minimum(1., t * k[idx][None, :] / safety)
            term = missing[idx][None, :] * (robust + 1e-10 >= self.req_threshold) * self.req_penalty
            term += (factors[idx][None, :] < self.uniform_threshold) * (robust + 1e-10 >= self.uniform_threshold) * uniform_bonus[idx][None, :]
            term += (request_reward[idx][None, :] > 0) * (robust + 1e-10 >= request_threshold[idx][None, :]) * (t <= request_deadline[idx][None, :]) * request_reward[idx][None, :]
            value = (np.maximum(0., self.weight[idx][None, None, :] * raw[:, None, :] * multiplier[:, idx][None, :, :] - scores[idx][None, None, :]) + term[:, None, :]) * urgency[idx][None, None, :]
            value = np.where((t <= up[idx][None, :])[:, None, :], value, -np.inf)
            cells = np.zeros((len(durations), 3, self.nfib))
            offsets = np.arange(len(durations) * 3)[:, None] * self.nfib + fibers[None, :]
            np.maximum.at(cells.ravel(), offsets.ravel(), value.reshape(len(durations) * 3, -1).ravel())
            result[c] = float(np.max(cells.sum(axis=2) / durations[:, None]))
        return result

    def choose(self, snapshot, best_scores, best_factors, env_estimate=None, active_requests=None):
        env = dict(env_estimate or {})
        started = time.perf_counter()
        self._frame, self._cpu_centers = None, []
        self._collecting = True
        try:
            # Reuse public geometry, priors, request state and temporal prices.
            # Collection bypasses all CPU objective work and exact assignment.
            super().choose(snapshot, best_scores, best_factors, {**env, "anchor_count": 8}, active_requests)
        finally:
            self._collecting = False
        if self._frame is None:
            return None
        frame = self._frame
        centers, useful = self._build_centers(frame, env)
        if not len(centers) or not len(useful):
            return None
        prepared = time.perf_counter()
        rates, durations = self.coarse_gpu(centers, useful, frame, env)
        fixed_workload = bool(env.get("gpu_fixed_workload", False))

        def ranked_top(values, maximum):
            count = min(len(values), max(1, maximum))
            if fixed_workload:
                return np.lexsort((np.arange(len(values)), -values))[:count]
            return np.argsort(values)[-count:][::-1]
        # Protect the smaller, validated candidate family from coarse-ranking
        # ties when widening the scan.  Its exact optimum and spatial refinement
        # are compared independently, so extra space candidates cannot replace
        # that action with a poorer frozen-Q value.
        protected_centers = []
        protect_count = int(env.get("gpu_protect_baseline_anchor_count", 320))
        if protect_count > 0 and int(env.get("gpu_anchor_count", 320)) > protect_count and env.get("gpu_candidate_centers") is None:
            base_centers, base_useful = self._build_centers(frame, {**env, "gpu_anchor_count": protect_count, "gpu_max_candidates": 8192})
            full_keys = np.rint(centers[:, 0] * 1e7).astype(np.int64) * 3600000001 + np.rint(centers[:, 1] * 1e7).astype(np.int64)
            base_keys = np.rint(base_centers[:, 0] * 1e7).astype(np.int64) * 3600000001 + np.rint(base_centers[:, 1] * 1e7).astype(np.int64)
            positions = np.searchsorted(full_keys, base_keys)
            safe_positions = np.minimum(positions, len(full_keys) - 1)
            if np.all((positions < len(full_keys)) & (full_keys[safe_positions] == base_keys)):
                base_rates = rates[positions]
            else:
                base_rates, _ = self.coarse_gpu(base_centers, base_useful, frame, env)
            base_top = ranked_top(base_rates, int(env.get("gpu_refine_count", 48)))
            protected_centers = list(base_centers[base_top]) + self._cpu_centers
        scanned = time.perf_counter()
        self.last_candidate_centers, self.last_coarse_rates = centers, rates
        top = ranked_top(rates, int(env.get("gpu_refine_count", 48)))
        all_refinement_centers = np.round(np.asarray(protected_centers + list(centers[top]) + self._cpu_centers), 7)
        _, first_indices = np.unique(all_refinement_centers, axis=0, return_index=True)
        refinement_centers = all_refinement_centers[np.sort(first_indices)]
        protected_keys = {tuple(np.round(c, 7)) for c in protected_centers}
        vectors, up, k, scores, factors, multiplier, missing, rr, rt, rd, uniform_bonus, urgency, seconds_left, safety, focus = frame
        best = None
        protected_best = None
        evaluated = 0
        refinement_budget = float(env.get("gpu_refine_budget_seconds", .30))
        exact_limit = max(1, int(env.get("gpu_exact_candidate_count", 256)))
        probe_limit = max(0, int(env.get("gpu_refinement_steps", 32)))
        emergency_seconds = max(.1, float(env.get("gpu_emergency_seconds", 3.0)))
        exact_candidates = 0
        refinement_probes = 0
        emergency_triggered = False
        cache = {}

        def cutoff():
            nonlocal emergency_triggered
            elapsed = time.perf_counter() - scanned
            if fixed_workload:
                if elapsed > emergency_seconds:
                    emergency_triggered = True
                    return True
                return False
            return elapsed > refinement_budget

        def evaluate(center):
            nonlocal evaluated
            key = tuple(np.round(center, 7))
            if key not in cache:
                a, z = center[0] * DEG, center[1] * DEG
                cvec = np.asarray([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])
                pool = useful[np.sum(vectors[useful] * cvec, axis=1) >= math.cos(self.fov * DEG)]
                cache[key] = super(GPUSpatialPlanner, self)._evaluate(tuple(center), pool, *frame)
                evaluated += 1
            return cache[key]

        for center in refinement_centers:
            if fixed_workload and exact_candidates >= exact_limit:
                break
            if (fixed_workload or best is not None) and cutoff():
                break
            candidate = evaluate(center)
            exact_candidates += 1
            if candidate and (best is None or candidate[0] > best[0]):
                best = candidate
            if candidate and tuple(center) in protected_keys and (protected_best is None or candidate[0] > protected_best[0]):
                protected_best = candidate

        def refine(seed):
            nonlocal refinement_probes
            if seed is None:
                return None
            local_best = seed
            for fraction in (.20, .07):
                base = local_best[1]
                for dn, de in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                    if (fixed_workload and refinement_probes >= probe_limit) or cutoff():
                        break
                    center = _shift_altaz(*base, dn * self.pitch * fraction, de * self.pitch * fraction)
                    candidate = evaluate(center)
                    refinement_probes += 1
                    if candidate and candidate[0] > local_best[0]:
                        local_best = candidate
            return local_best

        if protected_best is not None:
            protected_best = refine(protected_best)
            if best is None or protected_best[0] > best[0]:
                best = protected_best
        best = refine(best)
        self.stats = {"backend": "numba-cuda-float64", "device": self.device_name, "gpu_candidates": len(centers),
                      "gpu_durations": len(durations), "cpu_refinements": evaluated, "useful_targets": len(useful),
                      "fixed_workload": fixed_workload, "exact_candidates": exact_candidates,
                      "refinement_probes": refinement_probes, "emergency_triggered": emergency_triggered,
                      "max_coarse_rate": float(rates.max()), "selected_exact_rate": float(best[0]) if best is not None else None,
                      "protected_exact_rate": float(protected_best[0]) if protected_best is not None else None,
                      "prepare_seconds": prepared - started, "gpu_scan_seconds": scanned - prepared,
                      "refine_seconds": time.perf_counter() - scanned, "planning_seconds": time.perf_counter() - started}
        if best is None:
            return None
        _, center, duration, program, chosen, fibers = best
        now = parse_utc(snapshot["now_utc"])
        lst = local_sidereal(now, self.lon)
        alt, az, _, _ = self._altaz(lst)
        public_quality = self._public_quality(now, lst, alt)
        actual_bands = np.where(public_quality * float(env.get("program_band_quality_scale", float(env.get("quality_scale", .55)) / .95)) >= self.dark_threshold, 0,
                               np.where(public_quality * float(env.get("program_band_quality_scale", float(env.get("quality_scale", .55)) / .95)) >= self.bright_threshold, 1, 2))
        quality = k * self.f0t0 / np.maximum(self.flux, 1e-12)
        offset_alt, offset_az = float(env.get("pointing_offset_alt_deg", 0)), float(env.get("pointing_offset_az_deg", 0))
        cmd_alt = center[0] - offset_alt
        if not 0 <= cmd_alt <= 90:
            return None
        self.last_prediction = {self.ids[int(i)]: {"index": int(i), "fiber_id": int(f), "factor": min(1., float(k[i] * duration)),
                                                  "public_quality": float(public_quality[i]), "quality": float(quality[i]),
                                                  "directional_scale": float(quality[i] / max(1e-12, public_quality[i] * float(env.get("quality_scale", .55)))),
                                                  "predicted_band": PROGRAMS[int(actual_bands[i])], "alt_deg": float(alt[i]), "az_deg": float(az[i])}
                                for i, f in zip(chosen, fibers)}
        return {"action": "observe", "pointing": {"alt_deg": round(cmd_alt, 7), "az_deg": round((center[1] - offset_az) % 360, 7)},
                "assignments": {str(int(f)): self.ids[int(i)] for i, f in zip(chosen, fibers)},
                "duration_seconds": int(duration), "program": PROGRAMS[int(program)]}

# Compatibility name used by the service entry point.
GpuSpatialPlanner = GPUSpatialPlanner
