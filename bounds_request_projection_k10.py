#!/usr/bin/env python3
"""Audited k=8..10 all-request key projection with 16-bit actionability masks.

This is a separate implementation of the same conditional relaxation as
``bounds_request_projection.py``.  The published all-subset certificate bounds
every branch with fewer than 17 awarded requests; this program recomputes the
two all-17/RQ0004 branches only.  It does not change the scorer or source DP.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from numba import njit

import bounds_practice_projection as projection
from bounds_request_conditioned import PRACTICE, ROOT, request_branches
from bounds_request_projection import calculate_conditional


BASE_KEYS = (
    "T00018", "T00029", "T00030", "T00031",
    "T00024", "T00021", "T00040", "T00015",
)
PRICE_FILE = ROOT / "results" / "practice_global_interval_prices.npz"
PROJECTION_CERT = ROOT / "results" / "projected_wait_global_k8_certificate.json"
CONDITIONAL_CERT = ROOT / "results" / "practice_request_global_k8_conditional.json"
SUBSET_CERT = ROOT / "results" / "practice_global_k8_unconditional.json"
OLD_K8_THETA135 = ROOT / "results" / "practice_request_visit_joint_k8_theta135.json"
NEG_INF = -(10**15)


@njit(cache=True)
def _popcount(value: int) -> int:
    count = 0
    while value:
        value &= value - 1
        count += 1
    return count


@njit(cache=True)
def conditional_projected_dp16(
    n: int,
    complete_ptr: np.ndarray,
    complete_end: np.ndarray,
    complete_tile: np.ndarray,
    complete_reduced_cents: np.ndarray,
    complete_tagged: np.ndarray,
    partial_ptr: np.ndarray,
    partial_end: np.ndarray,
    actionable_mask: np.ndarray,
    key_index: np.ndarray,
    required_key_mask: int,
    mandatory_key_mask: int,
    key_deadline_unit: np.ndarray,
    earliest_terminal_unit: int,
    theta_cents: np.ndarray,
    k: int,
) -> int:
    """Exact reverse-topological DP on the complete relaxed time graph."""
    state_count = 1 << k
    dp = np.full((n + 1, state_count), NEG_INF, dtype=np.int64)
    terminal = np.full(state_count, NEG_INF, dtype=np.int64)
    for mask in range(state_count):
        if mandatory_key_mask & (~mask):
            continue
        terminal[mask] = (
            -projection.REQUIRED_MISS_CENTS
            * _popcount(required_key_mask & (~mask))
        )
        dp[n, mask] = terminal[mask]

    for u in range(n - 1, -1, -1):
        boundary = ((u // projection.POINTS_PER_SLOT) + 1) * projection.POINTS_PER_SLOT
        for mask in range(state_count):
            best = terminal[mask] if u >= earliest_terminal_unit else NEG_INF
            wait_cost = (
                projection.WAIT_UNIT_CENTS * (boundary - u)
                if actionable_mask[u] & (~mask)
                else 0
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
                        candidate = future + complete_reduced_cents[j]
                    elif complete_tagged[j]:
                        candidate = dp[complete_end[j], mask]
                    else:
                        continue
                else:
                    future = dp[complete_end[j], mask]
                    if future <= NEG_INF // 2:
                        continue
                    toll = 0 if complete_tagged[j] else theta_cents[tile]
                    candidate = future - toll
                if candidate > best:
                    best = candidate
            dp[u, mask] = best
    return int(dp[0, 0])


def _rss_mib() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024) if sys.platform == "darwin" else value / 1024


def _load_audited_data(prices_path: Path) -> tuple[dict, dict]:
    projected = json.loads(PROJECTION_CERT.read_text())
    conditional = json.loads(CONDITIONAL_CERT.read_text())
    subsets = json.loads(SUBSET_CERT.read_text())
    digest = hashlib.sha256(prices_path.read_bytes()).hexdigest()
    if digest != projected["price_sha256"]:
        raise AssertionError("capacity prices differ from the full scalar audit")
    if conditional["price_sha256"] != digest or subsets["capacity_price_sha256"] != digest:
        raise AssertionError("conditional/subset certificates use different prices")
    if tuple(conditional["key_tiles"]) != BASE_KEYS:
        raise AssertionError("published key set changed")
    audit = projected["scalar_audit"]
    if any(audit[field] != 0 for field in (
        "omitted_scalar_legal_arcs", "omitted_weather_interruption_arcs",
        "max_envelope_violation_cents",
    )):
        raise AssertionError("the prior full scalar audit failed")
    data = projection.build_data(PRACTICE, prices_path, audit=False)
    if data["complete_arc_count"] != 918757 or data["partial_arc_count"] != 850:
        raise AssertionError("the full action graph changed")
    if data["impossible_requests"] != ["RQ0015"] or data["request_cents"] != 392000:
        raise AssertionError("request opportunities changed")
    return data, {
        "price_sha256": digest,
        "projection_certificate_sha256": hashlib.sha256(PROJECTION_CERT.read_bytes()).hexdigest(),
        "conditional_certificate_sha256": hashlib.sha256(CONDITIONAL_CERT.read_bytes()).hexdigest(),
        "all_subsets_certificate_sha256": hashlib.sha256(SUBSET_CERT.read_bytes()).hexdigest(),
        "scalar_audit": audit,
        "other_award_subsets_upper_cents": max(
            int(row["upper_cents"]) for row in subsets["best_by_awarded_count"]
            if row["awarded_count"] < 17
        ),
    }


def _populate_actionability(data: dict, key: str) -> None:
    cache = data["actionable_cache"]
    if key in cache:
        return
    tile_ids = data["tile_ids"]
    tile = data["scorer"].tiles[key]
    starts = data["starts_by_tile"][tile_ids.index(key)]
    candidate = np.zeros(data["n"], dtype=np.bool_)
    candidate[starts] = True
    actionable = np.zeros(data["n"], dtype=np.bool_)
    for u in range(data["n"]):
        valid = data["scorer"]._can_complete_from(
            tile, u // projection.POINTS_PER_SLOT,
            (u % projection.POINTS_PER_SLOT) * 150,
        )
        if valid and not candidate[u]:
            raise AssertionError(f"actionable start omitted from audited arcs: {key}, {u}")
        actionable[u] = valid
    cache[key] = actionable


def _instance_inputs(data: dict) -> dict:
    scorer = data["scorer"]
    choices = request_branches(scorer, data["impossible_requests"])
    if len(choices) != 17 or any(
        len(options) != 1 for request, options in choices
        if request.request_id != "RQ0004"
    ):
        raise AssertionError("unexpected all-request branches")
    branches = [
        {request.request_id: tuple(tiles)
         for (request, _), tiles in zip(choices, selected)}
        for selected in itertools.product(*(options for _, options in choices))
    ]
    if len(branches) != 2:
        raise AssertionError("expected the two RQ0004 branches")
    instants = np.fromiter(
        (slot.timestamp_utc.timestamp() + 150 * offset
         for slot in scorer.slots for offset in range(6)),
        dtype=np.float64, count=data["n"],
    )
    arc_starts = np.repeat(
        np.arange(data["n"], dtype=np.int32), np.diff(data["complete_ptr"]),
    )
    earliest_terminal_unit = int(np.searchsorted(
        instants, max(request.available_from_utc.timestamp() for request, _ in choices),
        side="left",
    ))
    deadlines_by_branch = []
    for selected in branches:
        deadlines: dict[str, float] = {}
        for request_id, tiles in selected.items():
            deadline = scorer.requests[request_id].deadline_utc.timestamp()
            for tile in tiles:
                deadlines[tile] = min(deadline, deadlines.get(tile, deadline))
        deadlines_by_branch.append(deadlines)
    return {
        "branches": branches,
        "instants": instants,
        "arc_starts": arc_starts,
        "earliest_terminal_unit": earliest_terminal_unit,
        "deadlines_by_branch": deadlines_by_branch,
    }


def _conditional_bound(
    data: dict, inputs: dict, keys: tuple[str, ...], theta_cents: int,
    branch_index: int,
) -> dict:
    if len(keys) > 12 or len(keys) < 8 or theta_cents < 0:
        raise ValueError("requires 8 <= k <= 12 and nonnegative theta")
    tile_ids = data["tile_ids"]
    key_index = np.full(len(tile_ids), -1, dtype=np.int8)
    for bit, key in enumerate(keys):
        key_index[tile_ids.index(key)] = bit
        _populate_actionability(data, key)
    scorer = data["scorer"]
    deadlines = inputs["deadlines_by_branch"][branch_index]
    required_key_mask = 0
    mandatory_key_mask = 0
    key_deadline_unit = np.full(len(keys), data["n"], dtype=np.int32)
    for bit, key in enumerate(keys):
        if scorer.tiles[key].scheduling_class == "REQUIRED":
            required_key_mask |= 1 << bit
        if key in deadlines:
            mandatory_key_mask |= 1 << bit
            key_deadline_unit[bit] = np.searchsorted(
                inputs["instants"], deadlines[key], side="left",
            )
    actionable_mask = np.zeros(data["n"], dtype=np.uint16)
    for bit, key in enumerate(keys):
        actionable_mask[data["actionable_cache"][key]] |= np.uint16(1 << bit)
    theta = np.full(len(tile_ids), theta_cents, dtype=np.int64)
    theta[key_index >= 0] = 0

    external_cents = int(data["prices"].sum())
    for tile_index, tile_id in enumerate(tile_ids):
        if key_index[tile_index] >= 0:
            continue
        if tile_id not in deadlines:
            external_cents += int(data["tile_residual_max"][tile_index])
            continue
        deadline_unit = np.searchsorted(
            inputs["instants"], deadlines[tile_id], side="left",
        )
        allowed = (
            (data["complete_tile"] == tile_index)
            & (inputs["arc_starts"] < deadline_unit)
        )
        if not np.any(allowed):
            return {"feasible_relaxation": False, "missing_tile": tile_id}
        external_cents += int(np.max(data["complete_reduced"][allowed]))

    started = time.monotonic()
    dp_cents = conditional_projected_dp16(
        data["n"], data["complete_ptr"], data["complete_end"],
        data["complete_tile"], data["complete_reduced"],
        data["complete_tagged"], data["partial_ptr"], data["partial_end"],
        actionable_mask, key_index, required_key_mask, mandatory_key_mask,
        key_deadline_unit, inputs["earliest_terminal_unit"], theta, len(keys),
    )
    if dp_cents <= NEG_INF // 2:
        return {"feasible_relaxation": False, "reason": "no projected path"}
    total_cents = (
        external_cents + int(data["request_cents"])
        + int(theta.sum()) + dp_cents
    )
    return {
        "feasible_relaxation": True,
        "rq0004_tile": list(inputs["branches"][branch_index]["RQ0004"]),
        "conditional_upper_cents": total_cents,
        "external_cents": external_cents,
        "request_cents": int(data["request_cents"]),
        "theta_constant_cents": int(theta.sum()),
        "dp_cents": dp_cents,
        "required_key_mask": required_key_mask,
        "mandatory_key_mask": mandatory_key_mask,
        "key_deadline_unit": key_deadline_unit.tolist(),
        "dp_wall_seconds": time.monotonic() - started,
        "peak_rss_mib": _rss_mib(),
    }


def _rank_candidates(data: dict, inputs: dict) -> list[dict]:
    """Rank non-keys by conflict among high reduced-value first-visit arcs.

    A score is the number of overlapping pairs among each tile's top 64
    deadline-feasible arcs and the eight key tiles' top 64 such arcs, summing
    both all-request branches.  It is only a deterministic search heuristic.
    """
    top: list[list[tuple[np.ndarray, np.ndarray]]] = []
    tile_ids = data["tile_ids"]
    for deadlines in inputs["deadlines_by_branch"]:
        one_branch = []
        for i, tile in enumerate(tile_ids):
            mask = data["complete_tile"] == i
            if tile in deadlines:
                deadline = np.searchsorted(inputs["instants"], deadlines[tile], side="left")
                mask &= inputs["arc_starts"] < deadline
            indices = np.flatnonzero(mask)
            if len(indices) > 64:
                order = np.argpartition(data["complete_reduced"][indices], -64)[-64:]
                indices = indices[order]
            one_branch.append((inputs["arc_starts"][indices], data["complete_end"][indices]))
        top.append(one_branch)
    rows = []
    for tile in tile_ids:
        if tile in BASE_KEYS:
            continue
        score = 0
        for branch in top:
            start, end = branch[tile_ids.index(tile)]
            for key in BASE_KEYS:
                ks, ke = branch[tile_ids.index(key)]
                if len(start) and len(ks):
                    score += int(np.count_nonzero(
                        (start[:, None] < ke[None, :])
                        & (ks[None, :] < end[:, None])
                    ))
        rows.append({"tile_id": tile, "top64_conflict_pair_count": score})
    rows.sort(key=lambda row: (-row["top64_conflict_pair_count"], row["tile_id"]))
    return rows


def run(prices_path: Path, theta_cents: int, extra: list[str], top_n: int,
        k10_candidates: int) -> dict:
    started = time.monotonic()
    data, certificates = _load_audited_data(prices_path)
    inputs = _instance_inputs(data)
    old_baseline = projection.calculate(data, list(BASE_KEYS), theta_cents)
    old_branches = [
        calculate_conditional(
            data, list(BASE_KEYS), theta_cents, branch,
            inputs["instants"], inputs["arc_starts"], inputs["earliest_terminal_unit"],
        )
        for branch in inputs["branches"]
    ]
    fresh_branches = [
        _conditional_bound(data, inputs, BASE_KEYS, theta_cents, index)
        for index in range(2)
    ]
    if [row["conditional_upper_cents"] for row in fresh_branches] != [
        row["total_upper_bound_cents"] for row in old_branches
    ]:
        raise AssertionError("16-bit k8 reproduction differs from audited old DP")
    if theta_cents == 135:
        old = json.loads(OLD_K8_THETA135.read_text())
        if max(row["conditional_upper_cents"] for row in fresh_branches) != old["all_awarded_joint_upper_cents"]:
            raise AssertionError("theta=135 k8 does not reproduce 21,794.30")
    ranked = _rank_candidates(data, inputs)
    selected = extra or [row["tile_id"] for row in ranked[:top_n]]
    if len(set(selected)) != len(selected) or any(
        key in BASE_KEYS or key not in data["tile_ids"] for key in selected
    ):
        raise ValueError("invalid additional key tile")
    rows = []
    for key in selected:
        keys = BASE_KEYS + (key,)
        branches = [_conditional_bound(data, inputs, keys, theta_cents, i) for i in range(2)]
        row = {
            "keys": list(keys), "theta_uniform_cents": theta_cents,
            "branches": branches,
            "all_awarded_upper_cents": max(
                branch["conditional_upper_cents"] for branch in branches
                if branch["feasible_relaxation"]
            ),
        }
        rows.append(row)
        print(json.dumps({"k": 9, "new_key": key,
                          "all_awarded_upper_cents": row["all_awarded_upper_cents"],
                          "elapsed_seconds": time.monotonic() - started}), flush=True)
    if rows:
        best9 = min(rows, key=lambda row: row["all_awarded_upper_cents"])
        second_candidates = [row["keys"][-1] for row in sorted(
            rows, key=lambda row: row["all_awarded_upper_cents"]
        )[1:1 + k10_candidates]]
        for key2 in second_candidates:
            keys = tuple(best9["keys"]) + (key2,)
            branches = [_conditional_bound(data, inputs, keys, theta_cents, i) for i in range(2)]
            row = {
                "keys": list(keys), "theta_uniform_cents": theta_cents,
                "branches": branches,
                "all_awarded_upper_cents": max(
                    branch["conditional_upper_cents"] for branch in branches
                    if branch["feasible_relaxation"]
                ),
            }
            rows.append(row)
            print(json.dumps({"k": 10, "new_key": key2,
                              "all_awarded_upper_cents": row["all_awarded_upper_cents"],
                              "elapsed_seconds": time.monotonic() - started}), flush=True)
    best = min([max(row["conditional_upper_cents"] for row in fresh_branches)]
               + [row["all_awarded_upper_cents"] for row in rows])
    global_upper = max(best, certificates["other_award_subsets_upper_cents"])
    return {
        "scope": "public dev-reference; unconditional over all valid decisions",
        "certificates": certificates,
        "complete_arc_count": data["complete_arc_count"],
        "weather_interruption_arc_count": data["partial_arc_count"],
        "capacity_units": data["n"],
        "theta_uniform_cents": theta_cents,
        "baseline_keys": list(BASE_KEYS),
        "old_projected_unconditional_cents": old_baseline["total_upper_bound_cents"],
        "baseline_branches": fresh_branches,
        "ranked_candidate_heuristic": ranked,
        "tested": rows,
        "all_awarded_upper_cents": best,
        "unconditional_upper_cents": global_upper,
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": _rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "The 16-bit projected DP is an exact evaluation of the audited "
            "k-tile relaxed time DAG, with scorer-actionable wait masks and "
            "key first-success request deadlines. Every complete successful "
            "and partial weather-interrupted arc remains present. Non-key "
            "science and capacity use the same audited nonnegative lambda. "
            "The published exhaustive request-subset certificate bounds all "
            "branches awarding fewer than 17 requests independently."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path, default=PRICE_FILE)
    parser.add_argument("--theta-cents", type=int, default=135)
    parser.add_argument("--extra", default="", help="comma-separated k9 candidates")
    parser.add_argument("--top-n", type=int, default=4)
    parser.add_argument("--k10-candidates", type=int, default=2,
                        help="number of other tested k9 keys paired with best k9 key")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "results" / "practice_request_projection_k10.json")
    args = parser.parse_args()
    extra = [key for key in args.extra.split(",") if key]
    result = run(args.prices, args.theta_cents, extra, args.top_n,
                 args.k10_candidates)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "all_awarded_upper": result["all_awarded_upper_cents"] / 100,
        "unconditional_upper": result["unconditional_upper_cents"] / 100,
        "runtime_seconds": result["runtime_seconds"],
        "peak_rss_mib": result["peak_rss_mib"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
