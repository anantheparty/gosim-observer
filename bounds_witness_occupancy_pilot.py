#!/usr/bin/env python3
"""Small K8 pilot for request-witness occupation Lagrange prices.

For every selected request/tile link (r,i), an all-awarded real trace has at
least one successful observation of i starting inside r's request window.
For arbitrary nonnegative mu[r,i], adding mu times the number of such arcs to
the relaxed path, then subtracting sum(mu), preserves an upper bound. This
pilot prices all 28 links equally; it does not claim to solve the dual.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from numba import njit

import bounds_practice_projection as projection
import bounds_request_projection_k10 as original
import bounds_request_projection_ring as ring


NEG_INF = -(10**15)


@njit(cache=True)
def _popcount(value: int) -> int:
    count = 0
    while value:
        value &= value - 1
        count += 1
    return count


@njit(cache=True)
def _priced_dp(n, complete_ptr, complete_end, complete_tile,
               complete_reduced_cents, complete_tagged, partial_ptr,
               partial_end, actionable_mask, key_index, required_key_mask,
               mandatory_key_mask, key_deadline_unit, earliest_terminal_unit,
               theta_cents, k, arc_bonus):
    """Original reverse time recurrence plus a bonus on each eligible arc."""
    state_count = 1 << k
    horizon = 10  # Audited graph has maximum complete/partial span 9 grid units.
    dp = np.full((horizon, state_count), NEG_INF, dtype=np.int64)
    terminal = np.full(state_count, NEG_INF, dtype=np.int64)
    for mask in range(state_count):
        if mandatory_key_mask & (~mask):
            continue
        terminal[mask] = (-projection.REQUIRED_MISS_CENTS
                          * _popcount(required_key_mask & (~mask)))
        dp[n % horizon, mask] = terminal[mask]
    for u in range(n - 1, -1, -1):
        boundary = ((u // projection.POINTS_PER_SLOT) + 1) * projection.POINTS_PER_SLOT
        for mask in range(state_count):
            best = terminal[mask] if u >= earliest_terminal_unit else NEG_INF
            wait_cost = (projection.WAIT_UNIT_CENTS * (boundary - u)
                         if actionable_mask[u] & (~mask) else 0)
            future = dp[boundary % horizon, mask]
            if future > NEG_INF // 2:
                best = max(best, future - wait_cost)
            for j in range(partial_ptr[u], partial_ptr[u + 1]):
                best = max(best, dp[partial_end[j] % horizon, mask])
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
                        candidate = future + complete_reduced_cents[j] + arc_bonus[j]
                    elif complete_tagged[j]:
                        candidate = dp[complete_end[j] % horizon, mask] + arc_bonus[j]
                    else:
                        continue
                else:
                    future = dp[complete_end[j] % horizon, mask]
                    if future <= NEG_INF // 2:
                        continue
                    toll = 0 if complete_tagged[j] else theta_cents[tile]
                    candidate = future - toll + arc_bonus[j]
                if candidate > best:
                    best = candidate
            dp[u % horizon, mask] = best
    return int(dp[0, 0])


def _links(data, inputs, branch_index):
    selected = inputs["branches"][branch_index]
    tile_index = {tile: i for i, tile in enumerate(data["tile_ids"])}
    links = []
    for request_id, tiles in selected.items():
        request = data["scorer"].requests[request_id]
        start = int(np.searchsorted(inputs["instants"],
                                    request.available_from_utc.timestamp(), side="left"))
        deadline = int(np.searchsorted(inputs["instants"],
                                       request.deadline_utc.timestamp(), side="left"))
        for tile in tiles:
            links.append((request_id, tile, tile_index[tile], start, deadline))
    return links


def _bonus(data, inputs, links, mu_cents):
    if mu_cents < 0:
        raise ValueError("witness price must be nonnegative")
    bonus = np.zeros(data["complete_arc_count"], dtype=np.int64)
    starts = inputs["arc_starts"]
    for _, _, tile_index, lower, upper in links:
        allowed = ((data["complete_tile"] == tile_index) &
                   (starts >= lower) & (starts < upper))
        if not np.any(allowed):
            raise AssertionError("mandatory request witness has no eligible arc")
        if not np.all(data["complete_tagged"][allowed]):
            raise AssertionError("request window arc is not tagged in graph")
        bonus[allowed] += mu_cents
    return bonus


def run(prices, mu_values, keys):
    data, audit = original._load_audited_data(prices)
    if ring.transition_horizon(data) != 10:
        raise AssertionError("pilot kernel's 10-row horizon no longer covers every arc")
    inputs = original._instance_inputs(data)
    if len(keys) != 8:
        raise ValueError("pilot intentionally limited to eight keys")
    rows = []
    for branch in range(2):
        links = _links(data, inputs, branch)
        if len(links) != 28:
            raise AssertionError(f"expected 28 request witness actions, got {len(links)}")
        old = original._conditional_bound(data, inputs, keys, 135, branch)
        for mu in mu_values:
            bonus = _bonus(data, inputs, links, mu)
            def dp_wrapper(*args):
                return _priced_dp(*args, bonus)
            priced = original._conditional_bound(
                data, inputs, keys, 135, branch, dp_function=dp_wrapper)
            upper = int(priced["conditional_upper_cents"]) - len(links) * mu
            if mu == 0 and upper != old["conditional_upper_cents"]:
                raise AssertionError("priced DP at zero price differs from audited baseline")
            rows.append({"branch": branch, "mu_cents": mu,
                         "request_witness_count": len(links),
                         "old_upper_cents": old["conditional_upper_cents"],
                         "priced_upper_cents": upper,
                         "improvement_cents": old["conditional_upper_cents"] - upper,
                         "priced_dp_cents": priced["dp_cents"],
                         "dp_wall_seconds": priced["dp_wall_seconds"]})
            print(json.dumps(rows[-1]), flush=True)
    return {"scope": "dev-reference, all 17 awarded, K8 pilot only",
            "price_sha256": audit["price_sha256"],
            "complete_arc_count": data["complete_arc_count"],
            "partial_arc_count": data["partial_arc_count"],
            "key_tiles": list(keys), "theta_cents": 135,
            "witness_count_per_branch": 28, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mu-cents", type=int, nargs="+", default=[0, 5, 20, 50, 100])
    parser.add_argument("--out", type=Path,
                        default=Path("results/practice_witness_occupancy_k8_pilot.json"))
    args = parser.parse_args()
    payload = run(original.PRICE_FILE, args.mu_cents, original.BASE_KEYS)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
