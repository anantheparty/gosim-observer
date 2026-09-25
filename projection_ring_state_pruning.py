#!/usr/bin/env python3
"""Safe mask pruning for the exact rolling key-projection DP.

The projected state at cursor ``u`` records keys with a completed first
successful visit.  Hence a set bit needs some successful arc ending by ``u``.
For an unset mandatory bit, some successful first-visit arc must still start
at or after ``u`` and strictly before its request deadline.  These are only
necessary conditions; rejecting their violations preserves the root optimum.

Rows are cleared before filling viable masks so the bounded ring never exposes
stale values through a wait, interruption, or successful-visit transition.
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
from bounds_request_projection_ring import conditional_projected_dp_ring


NEG_INF = -(10**15)
K14_KEYS = full.BASE_KEYS + (
    "T00048", "T00032", "T00016", "T00010", "T00047", "T00011",
)
K15_KEYS = K14_KEYS + ("T00027",)


@njit(cache=True)
def _popcount(value: int) -> int:
    count = 0
    while value:
        value &= value - 1
        count += 1
    return count


@njit(cache=True)
def conditional_projected_dp_pruned(
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
    max_span = projection.POINTS_PER_SLOT
    first_end = np.full(k, n + 1, dtype=np.int32)
    last_start = np.full(k, -1, dtype=np.int32)
    for u in range(n):
        for j in range(complete_ptr[u], complete_ptr[u + 1]):
            end = complete_end[j]
            span = end - u
            if span <= 0 or end > n:
                raise AssertionError("invalid complete-arc time ordering")
            if span > max_span:
                max_span = span
            bit_index = key_index[complete_tile[j]]
            if bit_index >= 0 and u < key_deadline_unit[bit_index]:
                if end < first_end[bit_index]:
                    first_end[bit_index] = end
                last_start[bit_index] = u
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
        allowed_mask = 0
        forced_mask = 0
        for bit_index in range(k):
            bit = 1 << bit_index
            if first_end[bit_index] <= u:
                allowed_mask |= bit
            if mandatory_key_mask & bit and u > last_start[bit_index]:
                forced_mask |= bit
        row = u % horizon
        dp[row, :] = NEG_INF
        if forced_mask & (~allowed_mask):
            continue
        free_mask = allowed_mask & (~forced_mask)
        submask = free_mask
        while True:
            mask = forced_mask | submask
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
            dp[row, mask] = best
            if submask == 0:
                break
            submask = (submask - 1) & free_mask
    return int(dp[0, 0])


def mask_count_profile(data: dict, keys: tuple[str, ...], branch: dict) -> dict:
    """Count necessary-condition states without allocating a time × mask table."""
    index = {tile_id: i for i, tile_id in enumerate(data["tile_ids"])}
    first_end = np.full(len(keys), data["n"] + 1, dtype=np.int32)
    last_start = np.full(len(keys), -1, dtype=np.int32)
    for bit, tile_id in enumerate(keys):
        tile = index[tile_id]
        deadline = branch["key_deadline_unit"][bit]
        selected = (data["complete_tile"] == tile) & (data["arc_starts"] < deadline)
        if np.any(selected):
            first_end[bit] = min(data["complete_end"][selected])
            last_start[bit] = max(data["arc_starts"][selected])
    mandatory = branch["mandatory_key_mask"]
    count = 0
    peak = 0
    for u in range(data["n"]):
        allowed = sum(int(first_end[b] <= u) for b in range(len(keys)))
        forced = sum(int(mandatory & (1 << b) and u > last_start[b])
                     for b in range(len(keys)))
        incompatible = any(
            mandatory & (1 << b) and u > last_start[b] and u < first_end[b]
            for b in range(len(keys))
        )
        active = 0 if incompatible else 1 << (allowed - forced)
        count += active
        peak = max(peak, active)
    return {
        "first_end": first_end.tolist(), "last_start": last_start.tolist(),
        "valid_state_time_cells": count,
        "full_state_time_cells": data["n"] * (1 << len(keys)),
        "valid_fraction": count / (data["n"] * (1 << len(keys))),
        "max_valid_masks_per_time": peak,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, choices=(14, 15), action="append")
    parser.add_argument("--out", type=Path,
                        default=Path("results/projection_ring_state_pruning.json"))
    args = parser.parse_args()
    k_list = args.k or [14, 15]
    data, certs = full._load_audited_data(full.PRICE_FILE)
    inputs = full._instance_inputs(data)
    data["arc_starts"] = inputs["arc_starts"]
    rows = []
    for k in k_list:
        keys = K14_KEYS if k == 14 else K15_KEYS
        for branch_index in range(2):
            old = full._conditional_bound(data, inputs, keys, 135, branch_index,
                                          dp_function=conditional_projected_dp_ring)
            new = full._conditional_bound(data, inputs, keys, 135, branch_index,
                                          dp_function=conditional_projected_dp_pruned)
            if old["conditional_upper_cents"] != new["conditional_upper_cents"]:
                raise AssertionError("pruned and original ring differ")
            profile = mask_count_profile(data, keys, new)
            row = {
                "k": k, "branch_index": branch_index,
                "conditional_upper_cents": new["conditional_upper_cents"],
                "old_ring_seconds": old["dp_wall_seconds"],
                "pruned_ring_seconds": new["dp_wall_seconds"],
                "speedup": old["dp_wall_seconds"] / new["dp_wall_seconds"],
                **profile,
            }
            rows.append(row)
            print(json.dumps({key: row[key] for key in (
                "k", "branch_index", "conditional_upper_cents", "old_ring_seconds",
                "pruned_ring_seconds", "speedup", "valid_fraction",
            )}), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"rows": rows, "price_sha256": certs["price_sha256"]},
                                   ensure_ascii=False, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
