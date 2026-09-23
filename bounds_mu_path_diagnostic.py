#!/usr/bin/env python3
"""Small, order-free Lagrangian path-bound diagnostic for public practice.

This is an upper bound, not a submission plan. It uses only dev-reference's
published truth. Paid arcs may score the same tile repeatedly after dualizing
the one-first-credit constraint; tagged full repeats and weather interruptions
are retained as free transit. Wait cost, request occupancy and all penalties
are relaxed. Scores use audited upward cent envelopes.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from numba import njit

from bounds_practice_resource import all_arcs, certify
from bounds_practice_projection import _csr, _partial_weather_arcs, _tag_available
from challenge.scoring_core import ChallengeScorer


SCENARIO = Path("scenarios/dev-reference")
PRICE_FILE = Path("runs/practice_bound/resource_prices.npz")
OUT = Path("results/practice_mu_diagnostic.json")


@njit(cache=True)
def longest_path(
    n: int,
    ptr: np.ndarray,
    ends: np.ndarray,
    tile: np.ndarray,
    reward: np.ndarray,
    tagged: np.ndarray,
    partial_ptr: np.ndarray,
    partial_end: np.ndarray,
    mu: np.ndarray,
    tile_count: int,
) -> tuple[int, np.ndarray, int, int]:
    dp = np.zeros(n + 1, dtype=np.int64)
    choice_kind = np.zeros(n, dtype=np.uint8)  # 0 stop, 1 wait, 2 partial, 3 paid, 4 tagged zero
    choice_arg = np.zeros(n, dtype=np.int32)
    for u in range(n - 1, -1, -1):
        best = 0  # early terminal
        kind = 0
        arg = 0
        boundary = ((u // 6) + 1) * 6
        if dp[boundary] > best:
            best = dp[boundary]
            kind = 1
            arg = boundary
        for j in range(partial_ptr[u], partial_ptr[u + 1]):
            val = dp[partial_end[j]]
            if val > best:
                best = val
                kind = 2
                arg = partial_end[j]
        for j in range(ptr[u], ptr[u + 1]):
            val = dp[ends[j]] + reward[j] - mu[tile[j]]
            if val > best:
                best = val
                kind = 3
                arg = j
            if tagged[j] and dp[ends[j]] > best:
                best = dp[ends[j]]
                kind = 4
                arg = j
        dp[u] = best
        choice_kind[u] = kind
        choice_arg[u] = arg
    counts = np.zeros(tile_count, dtype=np.int32)
    paid = 0
    zero_transit = 0
    u = 0
    while u < n and choice_kind[u]:
        kind = choice_kind[u]
        arg = choice_arg[u]
        if kind == 1 or kind == 2:
            u = arg
        else:
            if kind == 3:
                counts[tile[arg]] += 1
                paid += 1
            else:
                zero_transit += 1
            u = ends[arg]
    return int(dp[0]), counts, paid, zero_transit


def main() -> None:
    instants, starts_by_tile, ends_by_tile, rewards_by_tile, request_cents, impossible = all_arcs(SCENARIO)
    scorer = ChallengeScorer.from_files(SCENARIO)
    tile_ids = list(scorer.tiles)
    if request_cents != 392000 or impossible != ["RQ0015"]:
        raise AssertionError("public practice request assumptions changed")
    n = len(instants)
    starts = np.concatenate(starts_by_tile).astype(np.int32)
    ends = np.concatenate(ends_by_tile).astype(np.int32)
    rewards = np.concatenate(rewards_by_tile).astype(np.int64)
    tiles = np.concatenate([
        np.full(len(a), i, dtype=np.int16) for i, a in enumerate(starts_by_tile)
    ])
    tagged_table = _tag_available(scorer, instants, tile_ids)
    tagged = tagged_table[starts, tiles]
    ptr, order = _csr(starts, n)
    ends = ends[order]
    rewards = rewards[order]
    tiles = tiles[order]
    tagged = tagged[order]
    partial_start, partial_end = _partial_weather_arcs(SCENARIO, scorer, instants)
    partial_ptr, partial_order = _csr(partial_start, n)
    partial_end = partial_end[partial_order]
    with np.load(PRICE_FILE, allow_pickle=False) as loaded:
        lam = loaded["prices_cents"].astype(np.int64)
    if len(lam) != n or np.any(lam < 0):
        raise AssertionError("bad published capacity prices")
    old_science, _ = certify(starts_by_tile, ends_by_tile, rewards_by_tile, lam)
    prefix = np.empty(n + 1, dtype=np.int64)
    prefix[0] = 0
    np.cumsum(lam, out=prefix[1:])
    mu_residual = np.array([
        max(0, int(np.max(q - (prefix[b] - prefix[a])))) if len(a) else 0
        for a, b, q in zip(starts_by_tile, ends_by_tile, rewards_by_tile)
    ], dtype=np.int64)
    if int(mu_residual.sum() + lam.sum()) != old_science:
        raise AssertionError("capacity dual prices did not reconstruct")
    mu_max = np.array([int(np.max(q)) if len(q) else 0 for q in rewards_by_tile], dtype=np.int64)

    results = []
    def evaluate(name: str, mu: np.ndarray) -> tuple[int, np.ndarray]:
        path, counts, paid, zero_transit = longest_path(
            n, ptr, ends, tiles, rewards, tagged,
            partial_ptr, partial_end, mu, len(tile_ids),
        )
        total = int(mu.sum() + request_cents + path)
        results.append({
            "name": name,
            "upper_bound_cents": total,
            "upper_bound": total / 100.0,
            "mu_sum_cents": int(mu.sum()),
            "path_cents": path,
            "paid_arc_count": paid,
            "tagged_zero_transit_count": zero_transit,
            "tiles_paid_more_than_once": int(np.count_nonzero(counts > 1)),
            "max_paid_visits_one_tile": int(counts.max()),
            "counts": counts.tolist(),
        })
        return total, counts

    evaluate("mu_zero", np.zeros(len(tile_ids), dtype=np.int64))
    evaluate("mu_independent_tile_max", mu_max)
    evaluate("mu_from_published_capacity_dual", mu_residual)

    payload = {
        "scope": "published dev-reference only; no hidden evaluation or submission",
        "proof": "For each genuine path, mark each tile's first success as paid q-mu; tagged repeats/weather partial as zero transit; add mu per tile and all feasible request rewards, drop penalties. Integer-cent q envelopes are upward.",
        "nodes": n,
        "complete_base_arcs": len(ends),
        "tagged_zero_transit_eligible_arcs": int(tagged.sum()),
        "partial_weather_arc_pairs": len(partial_end),
        "request_upper_cents": request_cents,
        "published_resource_upper_cents": int(old_science + request_cents),
        "published_request_unconditional_upper_cents": 2_252_473,
        "best_diagnostic_cents": min(r["upper_bound_cents"] for r in results),
        "evaluations": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in (
        "nodes", "complete_base_arcs", "tagged_zero_transit_eligible_arcs",
        "partial_weather_arc_pairs", "best_diagnostic_cents",
    )}))
    for row in results:
        print(row["name"], row["upper_bound"], "paid", row["paid_arc_count"],
              "repeat_science_tiles", row["tiles_paid_more_than_once"])


if __name__ == "__main__":
    main()
