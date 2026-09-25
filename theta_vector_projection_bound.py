#!/usr/bin/env python3
"""Search nonuniform nonnegative tile tolls for audited K=8..12 bounds.

All arithmetic in the bound is integer cents.  The LP bundle master merely
proposes toll vectors; every reported upper bound is recomputed by exact DP.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import time
from pathlib import Path

import numpy as np
from numba import njit
from scipy.optimize import linprog

import bounds_practice_projection as projection
from bounds_request_conditioned import PRACTICE, ROOT, request_branches
from bounds_request_projection import conditional_projected_dp
from bounds_request_projection_k10 import (
    _populate_actionability, conditional_projected_dp16,
)


BASE_KEYS = (
    "T00018", "T00029", "T00030", "T00031",
    "T00024", "T00021", "T00040", "T00015",
)
DEFAULT_PRICE_PATH = ROOT / "results" / "practice_global_interval_prices.npz"
BASELINE_PATH = ROOT / "results" / "practice_request_visit_joint_k8_theta135.json"
OLD_SUBSETS_PATH = ROOT / "results" / "practice_global_k8_unconditional.json"
AUDIT_PATH = ROOT / "results" / "projected_wait_global_k8_certificate.json"
NEG_INF = -(10**15)


@njit(cache=True)
def _popcount(value: int) -> int:
    n = 0
    while value:
        value &= value - 1
        n += 1
    return n


@njit(cache=True)
def dp_with_untagged_counts(
    n, complete_ptr, complete_end, complete_tile, reduced,
    complete_tagged, partial_ptr, partial_end, actionable_mask,
    key_index, required_key_mask, mandatory_key_mask,
    key_deadline_unit, earliest_terminal_unit, theta, k,
):
    """Exact conditional DP, then reconstruct one maximizing path and its n_i."""
    states = 1 << k
    dp = np.full((n + 1, states), NEG_INF, np.int64)
    terminal = np.full(states, NEG_INF, np.int64)
    for mask in range(states):
        if mandatory_key_mask & (~mask):
            continue
        terminal[mask] = -projection.REQUIRED_MISS_CENTS * _popcount(
            required_key_mask & (~mask)
        )
        dp[n, mask] = terminal[mask]

    for u in range(n - 1, -1, -1):
        boundary = ((u // projection.POINTS_PER_SLOT) + 1) * projection.POINTS_PER_SLOT
        for mask in range(states):
            best = terminal[mask] if u >= earliest_terminal_unit else NEG_INF
            wait_cost = (
                projection.WAIT_UNIT_CENTS * (boundary - u)
                if actionable_mask[u] & (~mask) else 0
            )
            future = dp[boundary, mask]
            if future > NEG_INF // 2:
                candidate = future - wait_cost
                if candidate > best:
                    best = candidate
            for j in range(partial_ptr[u], partial_ptr[u + 1]):
                candidate = dp[partial_end[j], mask]
                if candidate > best:
                    best = candidate
            for j in range(complete_ptr[u], complete_ptr[u + 1]):
                tile = complete_tile[j]
                bit_index = key_index[tile]
                if bit_index >= 0:
                    bit = 1 << bit_index
                    if not (mask & bit):
                        if u >= key_deadline_unit[bit_index]:
                            continue
                        future = dp[complete_end[j], mask | bit]
                        if future <= NEG_INF // 2:
                            continue
                        candidate = future + reduced[j]
                    elif complete_tagged[j]:
                        candidate = dp[complete_end[j], mask]
                    else:
                        continue
                else:
                    future = dp[complete_end[j], mask]
                    if future <= NEG_INF // 2:
                        continue
                    candidate = future - (0 if complete_tagged[j] else theta[tile])
                if candidate > best:
                    best = candidate
            dp[u, mask] = best

    counts = np.zeros(len(theta), np.int32)
    u = 0
    mask = 0
    while u < n:
        value = dp[u, mask]
        if u >= earliest_terminal_unit and value == terminal[mask]:
            break
        boundary = ((u // projection.POINTS_PER_SLOT) + 1) * projection.POINTS_PER_SLOT
        wait_cost = (
            projection.WAIT_UNIT_CENTS * (boundary - u)
            if actionable_mask[u] & (~mask) else 0
        )
        if dp[boundary, mask] > NEG_INF // 2 and dp[boundary, mask] - wait_cost == value:
            u = boundary
            continue
        moved = False
        for j in range(partial_ptr[u], partial_ptr[u + 1]):
            if dp[partial_end[j], mask] == value:
                u = partial_end[j]
                moved = True
                break
        if moved:
            continue
        for j in range(complete_ptr[u], complete_ptr[u + 1]):
            tile = complete_tile[j]
            bit_index = key_index[tile]
            if bit_index >= 0:
                bit = 1 << bit_index
                if not (mask & bit):
                    if u >= key_deadline_unit[bit_index]:
                        continue
                    future = dp[complete_end[j], mask | bit]
                    if future <= NEG_INF // 2:
                        continue
                    candidate = future + reduced[j]
                    next_mask = mask | bit
                elif complete_tagged[j]:
                    candidate = dp[complete_end[j], mask]
                    next_mask = mask
                else:
                    continue
            else:
                future = dp[complete_end[j], mask]
                if future <= NEG_INF // 2:
                    continue
                candidate = future - (0 if complete_tagged[j] else theta[tile])
                next_mask = mask
            if candidate == value:
                if bit_index < 0 and not complete_tagged[j]:
                    counts[tile] += 1
                mask = next_mask
                u = complete_end[j]
                moved = True
                break
        if not moved:
            raise AssertionError("could not reconstruct a maximizing DP path")
    return int(dp[0, 0]), counts


class ThetaProblem:
    def __init__(self, price_path: Path, subset_path: Path,
                 keys: tuple[str, ...] = BASE_KEYS) -> None:
        self.price_path = price_path
        self.subset_path = subset_path
        self.keys = keys
        if len(keys) > 12 or len(keys) < 8 or len(set(keys)) != len(keys):
            raise ValueError("key set must contain 8 to 12 distinct tiles")
        if keys[:8] != BASE_KEYS:
            raise ValueError("current subset certificate is anchored to the original 8 keys")
        self.price_sha = hashlib.sha256(price_path.read_bytes()).hexdigest()
        self.old_subsets_sha = hashlib.sha256(subset_path.read_bytes()).hexdigest()
        self.baseline_sha = hashlib.sha256(BASELINE_PATH.read_bytes()).hexdigest()
        self.old_subsets = json.loads(subset_path.read_text())
        self.baseline = json.loads(BASELINE_PATH.read_text())
        audit_ref = self.old_subsets["prior_audit"]
        audit_path = Path(audit_ref["projection_certificate"])
        if not audit_path.is_absolute():
            audit_path = ROOT / audit_path
        self.audit_sha = hashlib.sha256(audit_path.read_bytes()).hexdigest()
        assert self.audit_sha == audit_ref["projection_certificate_sha256"]
        self.audit = json.loads(audit_path.read_text())
        assert self.audit["price_sha256"] == self.price_sha
        assert self.old_subsets["capacity_price_sha256"] == self.price_sha
        assert self.old_subsets["request_subset_count"] == 131072
        assert self.old_subsets["evaluated_branch_count"] == 196608
        assert tuple(self.old_subsets["key_tiles"]) == BASE_KEYS
        old_price = self.baseline["price_sha256"] == self.price_sha
        if old_price:
            assert self.baseline["price_sha256"] == self.price_sha
            assert self.baseline["combined_unconditional_upper_cents"] == 2179430
            assert self.baseline["other_award_subsets_upper_cents"] == 2161431
        other_subsets = max(int(row["upper_cents"])
                            for row in self.old_subsets["best_by_awarded_count"]
                            if row["awarded_count"] < 17)
        if old_price:
            assert other_subsets == 2161431
        for name in ("omitted_scalar_legal_arcs", "omitted_weather_interruption_arcs",
                     "max_envelope_violation_cents"):
            assert self.audit["scalar_audit"][name] == 0
        self.data = projection.build_data(PRACTICE, price_path, audit=False)
        assert self.data["complete_arc_count"] == self.audit["complete_arc_count"]
        assert self.data["partial_arc_count"] == self.audit["weather_interruption_arc_count"]
        self.n = self.data["n"]
        self.tile_ids = self.data["tile_ids"]
        self.key_index = np.full(len(self.tile_ids), -1, np.int8)
        for bit, tile in enumerate(self.keys):
            self.key_index[self.tile_ids.index(tile)] = bit
        # Builds the scorer-exact actionability cache, with an independent
        # all-start inclusion check for newly promoted keys at k=9..10.
        if len(self.keys) <= 8:
            projection.calculate(self.data, list(self.keys), 135)
        else:
            for tile in self.keys:
                _populate_actionability(self.data, tile)
        self.actionable_mask = np.zeros(
            self.n, np.uint8 if len(self.keys) <= 8 else np.uint16
        )
        for bit, tile in enumerate(self.keys):
            self.actionable_mask[self.data["actionable_cache"][tile]] |= 1 << bit
        self.required_key_mask = sum(
            1 << bit for bit, tile in enumerate(self.keys)
            if self.data["scorer"].tiles[tile].scheduling_class == "REQUIRED"
        )
        requests = request_branches(self.data["scorer"], self.data["impossible_requests"])
        assert len(requests) == 17 and self.data["request_cents"] == 392000
        instants = np.array([
            slot.timestamp_utc.timestamp() + offset * 150
            for slot in self.data["scorer"].slots for offset in range(6)
        ], np.float64)
        self.earliest_terminal = int(np.searchsorted(
            instants, max(r.available_from_utc.timestamp() for r, _ in requests),
            side="left",
        ))
        starts = np.repeat(np.arange(self.n, dtype=np.int32),
                           np.diff(self.data["complete_ptr"]))
        self.branch_external = []
        self.branch_choices = []
        self.branch_masks = []
        self.branch_key_deadlines = []
        for selected in itertools.product(*(options for _, options in requests)):
            self.branch_choices.append({request.request_id: list(tiles)
                 for (request, _), tiles in zip(requests, selected)
                 if len(self.data["scorer"].request_tiles[request.request_id]) != len(tiles)})
            deadlines = np.full(len(self.tile_ids), self.n, np.int32)
            for (request, _), required_tiles in zip(requests, selected):
                d = int(np.searchsorted(instants, request.deadline_utc.timestamp(), side="left"))
                for tile_id in required_tiles:
                    i = self.tile_ids.index(tile_id)
                    deadlines[i] = min(int(deadlines[i]), d)
            key_deadlines = np.full(len(self.keys), self.n, np.int32)
            key_mask = 0
            external = int(self.data["prices"].sum())
            for i, tile_id in enumerate(self.tile_ids):
                if self.key_index[i] >= 0:
                    bit = int(self.key_index[i])
                    if deadlines[i] < self.n:
                        key_mask |= 1 << bit
                        key_deadlines[bit] = deadlines[i]
                    continue
                eligible = self.data["complete_tile"] == i
                if deadlines[i] < self.n:
                    eligible &= starts < deadlines[i]
                values = self.data["complete_reduced"][eligible]
                if deadlines[i] < self.n:
                    assert len(values)
                    external += int(values.max())
                elif len(values):
                    external += max(0, int(values.max()))
            self.branch_external.append(external)
            self.branch_masks.append(key_mask)
            self.branch_key_deadlines.append(key_deadlines)
        assert len(self.branch_external) == 2
        assert self.branch_masks[0] == self.branch_masks[1]
        assert np.array_equal(self.branch_key_deadlines[0], self.branch_key_deadlines[1])
        if old_price and self.keys == BASE_KEYS:
            assert sorted(self.branch_external) == [1639160, 1639260]
        self.nonkeys = np.flatnonzero(self.key_index < 0)
        self.fixed = max(self.branch_external) + int(self.data["request_cents"])
        self.other_subsets = other_subsets

    def evaluate(self, values: np.ndarray, trace: bool = True) -> dict:
        if values.shape != (len(self.nonkeys),) or np.any(values < 0):
            raise ValueError("one nonnegative integer-cent toll per non-key tile is required")
        theta = np.zeros(len(self.tile_ids), np.int64)
        theta[self.nonkeys] = values.astype(np.int64)
        args = (
            self.n, self.data["complete_ptr"], self.data["complete_end"],
            self.data["complete_tile"], self.data["complete_reduced"],
            self.data["complete_tagged"], self.data["partial_ptr"],
            self.data["partial_end"], self.actionable_mask, self.key_index,
            self.required_key_mask, self.branch_masks[0],
            self.branch_key_deadlines[0], self.earliest_terminal, theta, len(self.keys),
        )
        if trace:
            dp, counts = dp_with_untagged_counts(*args)
        else:
            dp = (conditional_projected_dp(*args) if len(self.keys) <= 8
                  else conditional_projected_dp16(*args))
            counts = None
        assert dp > NEG_INF // 2
        total = int(self.fixed + theta.sum() + dp)
        result = {"all_awarded_cents": total, "dp_cents": int(dp),
                  "theta_constant_cents": int(theta.sum()),
                  "global_cents": max(total, self.other_subsets)}
        if counts is not None:
            result["nonkey_untagged_counts"] = counts[self.nonkeys].tolist()
            result["support_slope"] = (1 - counts[self.nonkeys]).tolist()
        return result


def optimize(problem: ThetaProblem, iterations: int, seconds: float,
             initial_vector: np.ndarray | None = None) -> tuple[np.ndarray, dict, list[dict]]:
    start = time.monotonic()
    incumbent = np.full(len(problem.nonkeys), 135, np.int64)
    initial = problem.evaluate(incumbent)
    if (problem.keys == BASE_KEYS
            and problem.price_sha == problem.baseline["price_sha256"]):
        assert initial["all_awarded_cents"] == 2179430, initial
    problem.uniform_baseline = int(initial["all_awarded_cents"])
    problem.warm_start_cents = None
    if initial_vector is not None:
        warmed = problem.evaluate(initial_vector)
        problem.warm_start_cents = int(warmed["all_awarded_cents"])
        if warmed["all_awarded_cents"] < initial["all_awarded_cents"]:
            incumbent, initial = initial_vector.copy(), warmed
    best = initial
    cuts: list[tuple[np.ndarray, int]] = []
    seen = {incumbent.tobytes()}
    history = [{"iteration": 0, "objective_cents": best["all_awarded_cents"],
                "radius_cents": 0, "theta_sum_cents": int(incumbent.sum()),
                "max_path_untagged_visits": max(best["nonkey_untagged_counts"])}]

    def add_cut(x: np.ndarray, evaluation: dict) -> None:
        visits = np.asarray(evaluation["nonkey_untagged_counts"], np.int64)
        intercept = int(evaluation["dp_cents"] + visits @ x)
        if not any(np.array_equal(visits, old) and intercept == a for old, a in cuts):
            cuts.append((visits, intercept))

    add_cut(incumbent, initial)
    radii = (20, 40, 80, 160, 320, 640)
    for it in range(1, iterations + 1):
        if seconds and time.monotonic() - start >= seconds:
            break
        radius = radii[(it - 1) // max(1, iterations // len(radii)) % len(radii)]
        center = incumbent.copy()
        bounds = [(int(max(0, center[i] - radius)), int(center[i] + radius))
                  for i in range(len(center))] + [(None, None)]
        # t >= intercept - visits @ theta, so -visits @ theta - t <= -intercept.
        a_ub = np.array([np.r_[-v.astype(np.float64), -1.0]
                         for v, _ in cuts])
        b_ub = -np.array([a for _, a in cuts], np.float64)
        c = np.r_[np.ones(len(center), np.float64), 1.0]
        master = linprog(c, A_ub=a_ub, b_ub=b_ub, bounds=bounds, method="highs")
        if not master.success:
            raise RuntimeError(master.message)
        proposed = np.rint(master.x[:-1]).astype(np.int64)
        # Break ties in the fractional master and avoid exact repeats.
        if proposed.tobytes() in seen:
            proposed = np.floor(master.x[:-1]).astype(np.int64)
        if proposed.tobytes() in seen:
            active = np.where(np.asarray(best["support_slope"]) != 0)[0]
            if len(active) == 0:
                active = np.arange(len(center))
            j = int(active[(it - 1) % len(active)])
            proposed = center.copy()
            proposed[j] = max(0, int(proposed[j] - radius // 2))
        if proposed.tobytes() in seen:
            continue
        seen.add(proposed.tobytes())
        current = problem.evaluate(proposed)
        add_cut(proposed, current)
        if current["all_awarded_cents"] < best["all_awarded_cents"]:
            incumbent, best = proposed, current
        history.append({
            "iteration": it,
            "objective_cents": current["all_awarded_cents"],
            "best_cents": best["all_awarded_cents"],
            "radius_cents": radius,
            "theta_sum_cents": int(proposed.sum()),
            "max_path_untagged_visits": max(current["nonkey_untagged_counts"]),
            "cut_count": len(cuts),
            "elapsed_seconds": round(time.monotonic() - start, 1),
        })
        print(json.dumps(history[-1]), flush=True)
    return incumbent, best, history


def coordinate_refine(problem: ThetaProblem, values: np.ndarray, current: dict,
                      passes: int, seconds: float) -> tuple[np.ndarray, dict, list[dict]]:
    """Exact one-dimensional convex minimization in each theta_i coordinate."""
    start = time.monotonic()
    history = []
    values = values.copy()
    for pass_number in range(1, passes + 1):
        improved = False
        for i in range(len(values)):
            if seconds and time.monotonic() - start >= seconds:
                return values, current, history
            present = int(values[i])
            slope = int(current["support_slope"][i])
            if slope == 0:
                continue
            evaluated: dict[int, dict] = {present: current}

            def oracle(x: int) -> dict:
                if x not in evaluated:
                    trial = values.copy()
                    trial[i] = x
                    evaluated[x] = problem.evaluate(trial)
                return evaluated[x]

            if slope > 0:
                lo, hi = 0, present
                oracle(lo)
            else:
                lo = present
                hi = max(present + 1, 2 * present, 16)
                while hi < 8192 and int(oracle(hi)["support_slope"][i]) < 0:
                    lo, hi = hi, 2 * hi
                oracle(hi)
            while hi - lo > 1:
                mid = (lo + hi) // 2
                g = int(oracle(mid)["support_slope"][i])
                if g < 0:
                    lo = mid
                elif g > 0:
                    hi = mid
                else:
                    lo = hi = mid
            options = (lo, hi, present)
            candidate_x = min(options,
                              key=lambda x: (oracle(x)["all_awarded_cents"],
                                             abs(x - present)))
            candidate = oracle(candidate_x)
            if candidate["all_awarded_cents"] < current["all_awarded_cents"]:
                values[i] = candidate_x
                current = candidate
                improved = True
                history.append({
                    "pass": pass_number, "tile_id": problem.tile_ids[int(problem.nonkeys[i])],
                    "old_theta_cents": present, "new_theta_cents": candidate_x,
                    "all_awarded_upper_cents": current["all_awarded_cents"],
                    "evaluations": len(evaluated) - 1,
                    "elapsed_seconds": round(time.monotonic() - start, 1),
                })
                print(json.dumps(history[-1]), flush=True)
        if not improved:
            break
    return values, current, history


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--seconds", type=float, default=1800)
    parser.add_argument("--prices", type=Path, default=DEFAULT_PRICE_PATH)
    parser.add_argument("--keys", default=",".join(BASE_KEYS))
    parser.add_argument("--subset-certificate", type=Path, default=OLD_SUBSETS_PATH)
    parser.add_argument("--init-json", type=Path, default=None)
    parser.add_argument("--coordinate-passes", type=int, default=0)
    parser.add_argument("--coordinate-seconds", type=float, default=600)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "results" / "theta_vector_k8_bound.json")
    args = parser.parse_args()
    keys = tuple(part.strip() for part in args.keys.split(",") if part.strip())
    problem = ThetaProblem(args.prices, args.subset_certificate, keys)
    initial_vector = None
    if args.init_json is not None:
        old = json.loads(args.init_json.read_text())
        initial_vector = np.array([old["theta_by_tile_cents"][problem.tile_ids[int(i)]]
                                   for i in problem.nonkeys], np.int64)
    best_theta, best, history = optimize(problem, args.iterations, args.seconds,
                                         initial_vector)
    best_theta, best, coordinate_history = coordinate_refine(
        problem, best_theta, best, args.coordinate_passes, args.coordinate_seconds
    )
    # Independent production-DP equality is the final arithmetic check.
    checked = problem.evaluate(best_theta, trace=False)
    assert checked["all_awarded_cents"] == best["all_awarded_cents"]
    result = {
        "scope": "public dev-reference, all valid decision traces",
        "algorithm": "nonuniform nonnegative per-non-key-tile theta bundle proposals; exact integer-cent conditional DP",
        "key_tiles": list(problem.keys),
        "request_subset_certificate_key_tiles": list(BASE_KEYS),
        "price_sha256": problem.price_sha,
        "audited_projection_sha256": problem.audit_sha,
        "audited_projection_price_sha256": problem.audit["price_sha256"],
        "request_subset_certificate_sha256": problem.old_subsets_sha,
        "old_price_uniform_theta135_certificate_sha256": problem.baseline_sha,
        "successful_exposure_arcs": int(problem.data["complete_arc_count"]),
        "partial_weather_arcs": int(problem.data["partial_arc_count"]),
        "capacity_units": int(problem.n),
        "other_award_subsets_upper_cents": problem.other_subsets,
        "theta_by_tile_cents": {problem.tile_ids[int(i)]: int(v)
                                for i, v in zip(problem.nonkeys, best_theta)},
        "first_rq0004_branch_upper_cents": int(problem.branch_external[0]
             + problem.data["request_cents"] + best["theta_constant_cents"] + best["dp_cents"]),
        "first_rq0004_branch_choice": problem.branch_choices[0],
        "second_rq0004_branch_upper_cents": int(problem.branch_external[1]
             + problem.data["request_cents"] + best["theta_constant_cents"] + best["dp_cents"]),
        "second_rq0004_branch_choice": problem.branch_choices[1],
        "all_awarded_upper_cents": best["all_awarded_cents"],
        "unconditional_upper_cents": best["global_cents"],
        "uniform_theta135_all_awarded_upper_cents": problem.uniform_baseline,
        "warm_start_all_awarded_upper_cents": problem.warm_start_cents,
        "baseline_unconditional_upper_cents": max(problem.uniform_baseline, problem.other_subsets),
        "improvement_cents": max(problem.uniform_baseline, problem.other_subsets) - best["global_cents"],
        "projected_dp_cents": best["dp_cents"],
        "theta_constant_cents": best["theta_constant_cents"],
        "independent_production_dp_cents": checked["dp_cents"],
        "history": history,
        "coordinate_history": coordinate_history,
        "proof_note": (
            "Each actual non-key tile has at most one successful untagged exposure. "
            "Its theta_i toll is applied to every untagged complete edge in the "
            "relaxed projected path, with constant sum_i theta_i. Thus for "
            "theta_i >= 0 the pathwise Lagrangian inequality holds. The two "
            "all-17-awarded RQ0004 branches differ only in their exact external "
            "first-exposure residuals. The independently enumerated <17-award "
            "certificate bounds all other request subsets, and the maximum of "
            "these disjoint cases is an unconditional upper bound."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                   sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"all_awarded_upper": best["all_awarded_cents"] / 100,
                      "unconditional_upper": best["global_cents"] / 100,
                      "improvement_cents": result["improvement_cents"],
                      "out": str(args.out)}), flush=True)


if __name__ == "__main__":
    main()
