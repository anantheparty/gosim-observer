#!/usr/bin/env python3
"""Combine all-request conditioning with the exact key-tile wait projection.

This is a conditional bound for the public dev-reference practice instance.
The full arc graph and the scalar-audited actionability cache are supplied by
bounds_practice_projection.build_data. No formal-evaluation truth is read.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from numba import njit

import bounds_practice_projection as projection
from bounds_request_conditioned import PRACTICE, ROOT, request_branches


NEG_INF = -(10**15)


@njit(cache=True)
def _popcount(value: int) -> int:
    result = 0
    while value:
        value &= value - 1
        result += 1
    return result


@njit(cache=True)
def conditional_projected_dp(
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


def calculate_conditional(
    data: dict, keys: list[str], theta_cents: int,
    selected_by_request: dict[str, tuple[str, ...]],
    instants: np.ndarray, arc_starts: np.ndarray,
    earliest_terminal_unit: int,
) -> dict:
    if theta_cents < 0:
        raise ValueError("theta must be nonnegative")
    scorer = data["scorer"]
    tile_ids = data["tile_ids"]
    key_index = np.full(len(tile_ids), -1, dtype=np.int8)
    for bit, key in enumerate(keys):
        key_index[tile_ids.index(key)] = bit
    deadlines = {}
    for request_id, selected in selected_by_request.items():
        deadline = scorer.requests[request_id].deadline_utc.timestamp()
        for tile_id in selected:
            deadlines[tile_id] = min(deadline, deadlines.get(tile_id, deadline))
    if not deadlines:
        raise AssertionError("all-request condition requires mandatory tiles")

    mandatory_key_mask = 0
    required_key_mask = 0
    key_deadline_unit = np.full(len(keys), data["n"], dtype=np.int32)
    for bit, key in enumerate(keys):
        if scorer.tiles[key].scheduling_class == "REQUIRED":
            required_key_mask |= 1 << bit
        if key in deadlines:
            mandatory_key_mask |= 1 << bit
            key_deadline_unit[bit] = np.searchsorted(
                instants, deadlines[key], side="left"
            )

    actionable_mask = np.zeros(data["n"], dtype=np.uint8)
    for bit, key in enumerate(keys):
        actionable_mask[data["actionable_cache"][key]] |= 1 << bit

    theta = np.full(len(tile_ids), theta_cents, dtype=np.int64)
    theta[key_index >= 0] = 0

    # Every non-key tile's first successful arc is independent after dualizing
    # the telescope capacity. For a mandatory tile, its first arc is before its
    # earliest request deadline and the zero option is forbidden.
    external_cents = int(data["prices"].sum())
    constrained_tile_count = 0
    for i, tile_id in enumerate(tile_ids):
        if key_index[i] >= 0:
            continue
        if tile_id not in deadlines:
            external_cents += int(data["tile_residual_max"][i])
            continue
        constrained_tile_count += 1
        allowed = (
            (data["complete_tile"] == i)
            & (arc_starts < np.searchsorted(instants, deadlines[tile_id], side="left"))
        )
        if not np.any(allowed):
            return {"feasible_relaxation": False, "missing_tile": tile_id}
        external_cents += int(np.max(data["complete_reduced"][allowed]))

    dp_cents = conditional_projected_dp(
        data["n"], data["complete_ptr"], data["complete_end"],
        data["complete_tile"], data["complete_reduced"],
        data["complete_tagged"], data["partial_ptr"], data["partial_end"],
        actionable_mask, key_index, required_key_mask, mandatory_key_mask,
        key_deadline_unit, earliest_terminal_unit, theta, len(keys),
    )
    if dp_cents <= NEG_INF // 2:
        return {"feasible_relaxation": False, "reason": "key-tile projection has no feasible path"}
    total_cents = (
        external_cents + int(data["request_cents"])
        + int(theta.sum()) + dp_cents
    )
    return {
        "feasible_relaxation": True,
        "mandatory_tile_count": len(deadlines),
        "mandatory_key_mask": mandatory_key_mask,
        "mandatory_external_tile_count": constrained_tile_count,
        "external_science_cents": external_cents,
        "request_cents": int(data["request_cents"]),
        "theta_constant_cents": int(theta.sum()),
        "projected_dp_cents": dp_cents,
        "total_upper_bound_cents": total_cents,
        "total_upper_bound": total_cents / 100,
        "choice_by_request": {
            request_id: list(tiles)
            for request_id, tiles in selected_by_request.items()
            if len(scorer.request_tiles[request_id]) != len(tiles)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path,
                        default=ROOT / "runs" / "practice_bound" / "resource_prices.npz")
    parser.add_argument("--keys", default="T00018,T00029,T00030,T00031")
    parser.add_argument("--theta-cents", type=int, default=134)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    keys = [part for part in args.keys.split(",") if part]
    data = projection.build_data(PRACTICE, args.prices, args.audit)
    if data["impossible_requests"] != ["RQ0015"] or data["request_cents"] != 392000:
        raise AssertionError("practice request opportunity set changed")
    if len(keys) != len(set(keys)) or any(key not in data["tile_ids"] for key in keys):
        raise ValueError("key tiles must be distinct known IDs")
    if len(keys) > 8:
        raise ValueError("key set too large for this DP")
    base = projection.calculate(data, keys, args.theta_cents)
    choices = request_branches(data["scorer"], data["impossible_requests"])
    branch_count = 1
    for _, options in choices:
        branch_count *= len(options)
    if branch_count > 1000:
        raise ValueError("too many explicit request branches")
    instants = np.array([
        slot.timestamp_utc.timestamp() + offset * 150
        for slot in data["scorer"].slots for offset in range(6)
    ], dtype=np.float64)
    if len(instants) != data["n"]:
        raise AssertionError("time-grid length mismatch")
    arc_starts = np.repeat(
        np.arange(data["n"], dtype=np.int32),
        np.diff(data["complete_ptr"]),
    )
    last_available = max(
        request.available_from_utc.timestamp()
        for request, _ in choices
    )
    earliest_terminal_unit = int(np.searchsorted(
        instants, last_available, side="left"
    ))
    results = []
    for selected in itertools.product(*(options for _, options in choices)):
        selected_by_request = {
            request.request_id: tiles
            for (request, _), tiles in zip(choices, selected)
        }
        results.append(calculate_conditional(
            data, keys, args.theta_cents, selected_by_request,
            instants, arc_starts, earliest_terminal_unit,
        ))
    feasible = [r for r in results if r["feasible_relaxation"]]
    if not feasible:
        raise AssertionError("no branch remains after conditional projection")
    overall_cents = max(r["total_upper_bound_cents"] for r in feasible)
    payload = {
        "scope": "dev-reference; conditional on all 17 feasible request rewards",
        "key_tiles": keys,
        "theta_uniform_cents": args.theta_cents,
        "price_sha256": hashlib.sha256(args.prices.read_bytes()).hexdigest(),
        "capacity_units": data["n"],
        "candidate_count": data["complete_arc_count"],
        "partial_weather_arc_count": data["partial_arc_count"],
        "scalar_audit": data["scalar_audit"],
        "baseline_projected_upper_cents": base["total_upper_bound_cents"],
        "earliest_terminal_unit": earliest_terminal_unit,
        "earliest_terminal_utc": datetime.fromtimestamp(
            instants[earliest_terminal_unit], timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "branches": results,
        "conditional_total_upper_cents": overall_cents,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
