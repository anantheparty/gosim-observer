#!/usr/bin/env python3
"""Exact conditional key-projection DP with a bounded time-horizon ring.

Every edge advances by at most one exposure duration, so reverse-topological
DP only needs the next H cursor rows.  This changes storage, not the relaxed
graph or recurrence.  The full-matrix DP remains available for independent
cross-checks at feasible K.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from numba import njit

import bounds_practice_projection as projection
import bounds_request_projection_k10 as full


NEG_INF = -(10**15)


@njit(cache=True)
def _popcount(value: int) -> int:
    count = 0
    while value:
        value &= value - 1
        count += 1
    return count


@njit(cache=True)
def conditional_projected_dp_ring(
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
    # Wait to the next 900-second slot boundary advances 1..6 grid cells.
    max_span = projection.POINTS_PER_SLOT
    for u in range(n):
        for j in range(complete_ptr[u], complete_ptr[u + 1]):
            span = complete_end[j] - u
            if span <= 0 or complete_end[j] > n:
                raise AssertionError("invalid complete-arc time ordering")
            if span > max_span:
                max_span = span
        for j in range(partial_ptr[u], partial_ptr[u + 1]):
            span = partial_end[j] - u
            if span <= 0 or partial_end[j] > n:
                raise AssertionError("invalid partial-arc time ordering")
            if span > max_span:
                max_span = span
    horizon = max_span + 1
    state_count = 1 << k
    dp = np.full((horizon, state_count), NEG_INF, dtype=np.int64)
    terminal = np.full(state_count, NEG_INF, dtype=np.int64)
    for mask in range(state_count):
        if mandatory_key_mask & (~mask):
            continue
        terminal[mask] = (
            -projection.REQUIRED_MISS_CENTS
            * _popcount(required_key_mask & (~mask))
        )
        dp[n % horizon, mask] = terminal[mask]

    for u in range(n - 1, -1, -1):
        boundary = ((u // projection.POINTS_PER_SLOT) + 1) * projection.POINTS_PER_SLOT
        if boundary > n or boundary - u >= horizon:
            raise AssertionError("wait edge exceeds ring horizon")
        for mask in range(state_count):
            best = terminal[mask] if u >= earliest_terminal_unit else NEG_INF
            wait_cost = (
                projection.WAIT_UNIT_CENTS * (boundary - u)
                if actionable_mask[u] & (~mask)
                else 0
            )
            future = dp[boundary % horizon, mask]
            if future > NEG_INF // 2:
                candidate = future - wait_cost
                if candidate > best:
                    best = candidate
            for j in range(partial_ptr[u], partial_ptr[u + 1]):
                candidate = dp[partial_end[j] % horizon, mask]
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
                        future = dp[complete_end[j] % horizon, mask | bit]
                        if future <= NEG_INF // 2:
                            continue
                        candidate = future + complete_reduced_cents[j]
                    elif complete_tagged[j]:
                        candidate = dp[complete_end[j] % horizon, mask]
                    else:
                        continue
                else:
                    future = dp[complete_end[j] % horizon, mask]
                    if future <= NEG_INF // 2:
                        continue
                    toll = 0 if complete_tagged[j] else theta_cents[tile]
                    candidate = future - toll
                if candidate > best:
                    best = candidate
            dp[u % horizon, mask] = best
    return int(dp[0, 0])


def transition_horizon(data: dict) -> int:
    starts = np.repeat(np.arange(data["n"], dtype=np.int32),
                       np.diff(data["complete_ptr"]))
    partial_starts = np.repeat(np.arange(data["n"], dtype=np.int32),
                               np.diff(data["partial_ptr"]))
    return 1 + max(
        projection.POINTS_PER_SLOT,
        int(np.max(data["complete_end"] - starts)),
        int(np.max(data["partial_end"] - partial_starts))
        if len(partial_starts) else 0,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keys", default=",".join(full.BASE_KEYS))
    parser.add_argument("--theta-cents", type=int, default=135)
    parser.add_argument("--out", type=Path, default=Path("results/practice_projection_ring_reproduction.json"))
    args = parser.parse_args()
    keys = tuple(key for key in args.keys.split(",") if key)
    started = time.monotonic()
    data, certs = full._load_audited_data(full.PRICE_FILE)
    inputs = full._instance_inputs(data)
    results = []
    for branch_index in range(2):
        full_row = full._conditional_bound(
            data, inputs, keys, args.theta_cents, branch_index,
        )
        ring_row = full._conditional_bound(
            data, inputs, keys, args.theta_cents, branch_index,
            dp_function=conditional_projected_dp_ring,
        )
        if full_row["conditional_upper_cents"] != ring_row["conditional_upper_cents"]:
            raise AssertionError("ring and full-matrix DP differ")
        results.append({"branch_index": branch_index,
                        "full": full_row, "ring": ring_row})
        print(json.dumps({"branch_index": branch_index,
                          "bound_cents": ring_row["conditional_upper_cents"],
                          "full_dp_seconds": full_row["dp_wall_seconds"],
                          "ring_dp_seconds": ring_row["dp_wall_seconds"]}), flush=True)
    payload = {
        "key_tiles": keys,
        "theta_cents": args.theta_cents,
        "price_sha256": certs["price_sha256"],
        "capacity_units": data["n"],
        "complete_arc_count": data["complete_arc_count"],
        "partial_arc_count": data["partial_arc_count"],
        "ring_time_rows": transition_horizon(data),
        "full_time_rows": data["n"] + 1,
        "results": results,
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": full._rss_mib(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
