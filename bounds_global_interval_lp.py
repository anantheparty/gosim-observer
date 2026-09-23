#!/usr/bin/env python3
"""Order-free, request-aware interval LP certificate for dev-reference.

The primal includes *every* previously audited successful exposure start.
First observations consume the tile's one science credit; tagged repeats use
the same telescope capacity and can support request completion. A request's
reward variable is bounded by each mandatory tagged-visit group. Waiting,
request miss, quotas, and precedence are relaxed. The LP dual is recertified
in integer micro-cents, so the reported bound is not GLOP's floating result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from ortools.linear_solver import pywraplp

from bounds_practice_resource import all_arcs
from challenge.scoring_core import ChallengeScorer


ROOT = Path(__file__).resolve().parent
PRACTICE = ROOT / "scenarios" / "dev-reference"
SCALE = 1_000_000  # integer units per cent


def request_groups(scorer: ChallengeScorer, instants: np.ndarray,
                   starts: list[np.ndarray]):
    """Map each legal (successful arc, request label) to one award constraint."""
    tile_ids = list(scorer.tiles)
    tile_index = {tile_id: i for i, tile_id in enumerate(tile_ids)}
    offsets = np.cumsum([0] + [len(a) for a in starts], dtype=np.int64)
    group_members: dict[int, list[int]] = defaultdict(list)
    group_names: list[str] = []
    groups_by_request: list[list[int]] = []
    first_by_tile: list[list[tuple[int, float]]] = [[] for _ in tile_ids]
    requests = sorted(scorer.requests.values(), key=lambda r: r.request_id)
    for request in requests:
        links = scorer.request_tiles[request.request_id]
        if not all(m == 1 for m in links.values()):
            raise ValueError("this practice LP assumes one visit per request/tile")
        if request.required_tile_count == len(links):
            tilesets = [[tile_id] for tile_id in sorted(links)]
        elif request.required_tile_count == 1:
            tilesets = [sorted(links)]
        else:
            raise ValueError("unsupported request choice cardinality")
        g_for_r: list[int] = []
        for tileset in tilesets:
            g = len(group_names)
            g_for_r.append(g)
            group_names.append(request.request_id + ":" + "+".join(tileset))
            for tile_id in tileset:
                i = tile_index[tile_id]
                first_by_tile[i].append((g, request.deadline_utc.timestamp()))
                mask = (
                    (instants[starts[i]] >= request.available_from_utc.timestamp())
                    & (instants[starts[i]] < request.deadline_utc.timestamp())
                )
                for j in np.flatnonzero(mask):
                    group_members[int(offsets[i] + j)].append(g)
        groups_by_request.append(g_for_r)
    return requests, group_names, groups_by_request, group_members, first_by_tile


def prices_to_int(duals, name: str, *, tol: float = 1e-5) -> np.ndarray:
    values = np.array([c.dual_value() for c in duals], dtype=np.float64)
    if np.any(values < -tol):
        raise AssertionError(f"{name} has negative dual beyond tolerance: {values.min()}")
    # These are arbitrary nonnegative integer prices, not a fragile rounding
    # of an LP objective. The full Lagrangian expression is then exact.
    return np.rint(np.maximum(values, 0.0) * SCALE).astype(np.int64)


def free_prices_to_int(duals) -> np.ndarray:
    return np.rint(np.array([c.dual_value() for c in duals], dtype=np.float64) * SCALE).astype(np.int64)


def certify(starts: list[np.ndarray], ends: list[np.ndarray],
            rewards: list[np.ndarray], requests, groups_by_request,
            group_members: dict[int, list[int]], first_by_tile,
            instants: np.ndarray, capacity_prices: np.ndarray,
            tile_prices: np.ndarray, link_prices: dict[int, int],
            access_prices: np.ndarray, early_prices: np.ndarray,
            miss_rows, miss_prices: np.ndarray, prefix_by_tile) -> tuple[int, dict]:
    """Exact integer weak-duality certificate for all columns and bounds."""
    price_prefix = np.empty(len(capacity_prices) + 1, np.int64)
    price_prefix[0] = 0
    np.cumsum(capacity_prices, out=price_prefix[1:])
    value = int(price_prefix[-1]) + int(np.sum(tile_prices, dtype=np.int64))
    baseline = value
    first_positive = tagged_positive = repeat_positive = 0
    offset = 0
    for i, (a, b, q) in enumerate(zip(starts, ends, rewards)):
        cell = price_prefix[b] - price_prefix[a]
        gamma = np.zeros(len(a), np.int64)
        for j in range(len(a)):
            gamma[j] = link_prices.get(offset + j, 0)
        early = np.zeros(len(a), np.int64)
        for g, deadline in first_by_tile[i]:
            early[instants[a] < deadline] += early_prices[g]
        reduced = q.astype(np.int64) * SCALE - cell - tile_prices[i] + gamma + early
        tile_prefix = prefix_by_tile.get(i)
        if tile_prefix:
            times, theta, delta = tile_prefix
            buckets = np.searchsorted(times, b, side="left")
            has_bucket = buckets < len(times)
            reduced[has_bucket] += theta[buckets[has_bucket]]
            next_theta = np.empty(len(theta), np.int64)
            next_theta[:-1] = theta[1:]
            next_theta[-1] = 0
            value += int(np.maximum(next_theta - theta + delta, 0).sum(dtype=np.int64))
        pos = np.maximum(reduced, 0)
        value += int(np.sum(pos, dtype=np.int64))
        first_positive += int(np.count_nonzero(pos))
        for j in range(len(a)):
            for g in group_members.get(offset + j, ()):
                tagged = max(0, int(access_prices[g] - gamma[j]))
                prefix_cost = 0
                if tile_prefix:
                    index = np.searchsorted(times, a[j], side="left")
                    if index >= len(times) or times[index] != a[j]:
                        raise AssertionError("tag start omitted from prefix checkpoints")
                    prefix_cost = delta[index]
                revisit = max(0, int(access_prices[g] - cell[j] - prefix_cost))
                value += tagged + revisit
                tagged_positive += tagged > 0
                repeat_positive += revisit > 0
        offset += len(a)
    sigma_out = np.zeros(len(requests), np.int64)
    sigma_in = np.zeros(len(requests), np.int64)
    for (r, s, _), sigma in zip(miss_rows, miss_prices):
        sigma_out[r] += sigma
        sigma_in[s] += sigma
    request_residual = 0
    for i, (r, gs) in enumerate(zip(requests, groups_by_request)):
        reward = round(100 * r.completion_reward) * SCALE
        excess = max(0, reward - int(np.sum(access_prices[gs] + early_prices[gs], dtype=np.int64))
                     + int(sigma_out[i] - sigma_in[i]))
        request_residual += excess
    value += request_residual
    miss_residual = 0
    for i, r in enumerate(requests):
        if sigma_out[i]:
            miss_residual += max(0, int(sigma_out[i]) - round(100 * r.miss_penalty) * SCALE)
    value += miss_residual
    return value, {
        "base_price_microcents": baseline,
        "request_residual_microcents": request_residual,
        "miss_penalty_residual_microcents": miss_residual,
        "positive_first_reduced_columns": first_positive,
        "positive_first_tag_reduced_columns": tagged_positive,
        "positive_repeat_reduced_columns": repeat_positive,
        "all_columns_checked": offset + 2 * sum(len(v) for v in group_members.values()),
    }


def solve(args):
    started = time.monotonic()
    instants, starts, ends, rewards, request_cents, impossible = all_arcs(args.scenario)
    scorer = ChallengeScorer.from_files(args.scenario)
    if scorer.mechanics or scorer.tile_anomalies or scorer.config.get("coverage_bonus_weight", 0):
        raise ValueError("only the public practice semantics are supported")
    if len(starts) != len(scorer.tiles) or len(instants) != len(scorer.slots) * 6:
        raise AssertionError("candidate/scorer dimension mismatch")
    requests, group_names, groups_by_request, group_members, first_by_tile = request_groups(
        scorer, instants, starts,
    )
    n_success = sum(len(a) for a in starts)
    n_tags = sum(map(len, group_members.values()))
    if n_success != 918_757 or n_tags != 46_382 or request_cents != 392_000:
        raise AssertionError((n_success, n_tags, request_cents))
    print(json.dumps({"phase": "enumerated", "seconds": time.monotonic() - started,
                      "successful_arcs": n_success, "tag_copies": n_tags,
                      "request_groups": len(group_names)}), flush=True)

    solver = pywraplp.Solver.CreateSolver("GLOP")
    if solver is None:
        raise RuntimeError("GLOP unavailable")
    solver.SetTimeLimit(args.time_limit_seconds * 1000)
    infinity = solver.infinity()
    capacity = [solver.RowConstraint(-infinity, 1.0, "") for _ in range(len(instants))]
    tile_once = [solver.RowConstraint(-infinity, 1.0, "") for _ in starts]
    access = [solver.RowConstraint(-infinity, 0.0, "") for _ in group_names]
    early_first = [solver.RowConstraint(-infinity, 0.0, "") for _ in group_names]
    objective = solver.Objective()
    objective.SetMaximization()
    link_rows: dict[int, object] = {}
    first_records = []
    repeat_records = []
    first_vars_by_tile: dict[int, list[tuple[int, object]]] = defaultdict(list)
    repeat_by_tile: dict[int, dict[int, list[object]]] = defaultdict(lambda: defaultdict(list))
    event = 0
    for i, (a, b, q) in enumerate(zip(starts, ends, rewards)):
        for j in range(len(a)):
            u, v = int(a[j]), int(b[j])
            x = solver.NumVar(0.0, 1.0, "")
            first_records.append((i, u, v, int(q[j]), x))
            if first_by_tile[i]:
                first_vars_by_tile[i].append((v, x))
            objective.SetCoefficient(x, float(q[j]))
            tile_once[i].SetCoefficient(x, 1.0)
            for g, deadline in first_by_tile[i]:
                if instants[u] < deadline:
                    early_first[g].SetCoefficient(x, -1.0)
            for t in range(u, v):
                capacity[t].SetCoefficient(x, 1.0)
            gs = group_members.get(event)
            if gs:
                row = solver.RowConstraint(-infinity, 0.0, "")
                row.SetCoefficient(x, -1.0)
                link_rows[event] = row
                for g in gs:
                    tagged = solver.NumVar(0.0, 1.0, "")
                    row.SetCoefficient(tagged, 1.0)
                    access[g].SetCoefficient(tagged, -1.0)
                    repeat = solver.NumVar(0.0, 1.0, "")
                    repeat_records.append((i, u, v, g, repeat))
                    repeat_by_tile[i][u].append(repeat)
                    access[g].SetCoefficient(repeat, -1.0)
                    for t in range(u, v):
                        capacity[t].SetCoefficient(repeat, 1.0)
            event += 1
        if (i + 1) % 16 == 0:
            print(json.dumps({"phase": "building", "tiles": i + 1,
                              "variables": solver.NumVariables(),
                              "seconds": time.monotonic() - started}), flush=True)
    awards = []
    # Prefix completion state only at timestamps where a tagged revisit could
    # start. Each first column enters exactly one recurrence equation.
    prefix_rows: dict[int, tuple[np.ndarray, list, list]] = {}
    for i, revisits in repeat_by_tile.items():
        times = np.array(sorted(revisits), dtype=np.int32)
        completed = sorted(first_vars_by_tile[i], key=lambda item: item[0])
        before = None
        k = 0
        equalities = []
        revisit_rows = []
        for u in times:
            F = solver.NumVar(0.0, 1.0, "")
            eq = solver.RowConstraint(0.0, 0.0, "")
            eq.SetCoefficient(F, 1.0)
            if before is not None:
                eq.SetCoefficient(before, -1.0)
            while k < len(completed) and completed[k][0] <= u:
                eq.SetCoefficient(completed[k][1], -1.0)
                k += 1
            row = solver.RowConstraint(-infinity, 0.0, "")
            row.SetCoefficient(F, -1.0)
            for repeat in revisits[int(u)]:
                row.SetCoefficient(repeat, 1.0)
            equalities.append(eq)
            revisit_rows.append(row)
            before = F
        prefix_rows[i] = (times, equalities, revisit_rows)
    for request, gs in zip(requests, groups_by_request):
        award = solver.NumVar(0.0, 1.0, "")
        awards.append(award)
        objective.SetCoefficient(award, round(100 * request.completion_reward))
        for g in gs:
            access[g].SetCoefficient(award, 1.0)
            early_first[g].SetCoefficient(award, 1.0)
    miss_rows = []
    for i, request in enumerate(requests):
        feasible_count = sum(
            scorer._tile_has_request_opportunity(
                scorer.tiles[tile_id], request.available_from_utc,
                request.deadline_utc,
            ) for tile_id in scorer.request_tiles[request.request_id]
        )
        if feasible_count < request.required_tile_count:
            continue  # The scorer excuses an unawarded expired request.
        later = [j for j, other in enumerate(requests)
                 if other.available_from_utc >= request.deadline_utc]
        if not later:
            continue
        miss = solver.NumVar(0.0, 1.0, "")
        objective.SetCoefficient(miss, -round(100 * request.miss_penalty))
        for j in later:
            row = solver.RowConstraint(-infinity, 0.0, "")
            row.SetCoefficient(awards[j], 1.0)
            row.SetCoefficient(awards[i], -1.0)
            row.SetCoefficient(miss, -1.0)
            miss_rows.append((i, j, row))
    built_seconds = time.monotonic() - started
    print(json.dumps({"phase": "solving", "variables": solver.NumVariables(),
                      "constraints": solver.NumConstraints(),
                      "seconds": built_seconds}), flush=True)
    status = solver.Solve()
    solved_seconds = time.monotonic() - started
    print(json.dumps({"phase": "solved", "status": status,
                      "lp_objective_cents": objective.Value(),
                      "seconds": solved_seconds}), flush=True)
    if status != pywraplp.Solver.OPTIMAL:
        # Feasible but nonoptimal restricted objective is not a global bound.
        # GLOP duals are only used after its optimal status is established.
        raise RuntimeError(f"GLOP did not certify optimal LP status: {status}")
    selected_first = [
        [i, u, v, q, round(x.solution_value(), 9)]
        for i, u, v, q, x in first_records if x.solution_value() > 1e-8
    ]
    selected_repeats = [
        [i, u, v, group_names[g], round(z.solution_value(), 9)]
        for i, u, v, g, z in repeat_records if z.solution_value() > 1e-8
    ]
    p = prices_to_int(capacity, "capacity")
    mu = prices_to_int(tile_once, "tile")
    alpha = prices_to_int(access, "request access")
    beta = prices_to_int(early_first, "early first")
    sigma = prices_to_int([row for _, _, row in miss_rows], "inevitable miss")
    prefix_prices = {
        i: (times, free_prices_to_int(eqs), prices_to_int(rows, "prefix repeat"))
        for i, (times, eqs, rows) in prefix_rows.items()
    }
    # A capacity price vector is valid for the independent integer-cent
    # request/wait projection certificate, even if it came from this LP.
    projected_capacity_cents = np.rint(p.astype(np.float64) / SCALE).astype(np.int64)
    args.price_out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.price_out, prices_cents=projected_capacity_cents)
    gamma = {event: max(0, round(row.dual_value() * SCALE))
             for event, row in link_rows.items()}
    bound_microcents, check = certify(
        starts, ends, rewards, requests, groups_by_request, group_members,
        first_by_tile, instants, p, mu, gamma, alpha, beta,
        miss_rows, sigma, prefix_prices,
    )
    total_cents_ceiling = (bound_microcents + SCALE - 1) // SCALE
    output = {
        "scope": "all valid decision traces for the public dev-reference practice instance",
        "model": "complete order-free interval LP; first science plus tagged revisits; request access constraints; nonnegative penalties relaxed",
        "candidate_count": n_success,
        "tag_copy_count": n_tags,
        "full_action_column_count": n_success + 2 * n_tags,
        "request_group_count": len(group_names),
        "inevitable_miss_implication_count": len(miss_rows),
        "prefix_checkpoint_count": sum(len(item[0]) for item in prefix_rows.values()),
        "request_count": len(requests),
        "request_award_lp_values": {
            r.request_id: round(y.solution_value(), 9)
            for r, y in zip(requests, awards)
        },
        "lp_positive_first_columns": selected_first,
        "lp_positive_repeat_columns": selected_repeats,
        "impossible_requests": impossible,
        "capacity_cells": len(instants),
        "model_variables": solver.NumVariables(),
        "model_constraints": solver.NumConstraints(),
        "glop_status": "OPTIMAL",
        "glop_objective_cents": objective.Value(),
        "integer_microcents_per_cent": SCALE,
        "certified_upper_microcents": bound_microcents,
        "certified_upper_cents_ceiling": total_cents_ceiling,
        "certified_upper_points": total_cents_ceiling / 100,
        "certification": check,
        "price_nonzero": {
            "capacity": int(np.count_nonzero(p)), "tile": int(np.count_nonzero(mu)),
            "access": int(np.count_nonzero(alpha)),
            "early_first": int(np.count_nonzero(beta)),
            "inevitable_miss": int(np.count_nonzero(sigma)),
            "prefix_repeat": sum(int(np.count_nonzero(item[2])) for item in prefix_prices.values()),
            "first_tag_link": sum(v > 0 for v in gamma.values()),
        },
        "runtime_seconds": {
            "build": built_seconds,
            "solve_and_certify": time.monotonic() - started - built_seconds,
        },
        "price_digest_sha256": hashlib.sha256(
            p.tobytes() + mu.tobytes() + alpha.tobytes() + beta.tobytes()
            + sigma.tobytes()
            + np.array(sorted(gamma.items()), dtype=np.int64).tobytes()
            + b"".join(
                prefix_prices[i][0].tobytes() + prefix_prices[i][1].tobytes()
                + prefix_prices[i][2].tobytes()
                for i in sorted(prefix_prices)
            )
        ).hexdigest(),
        "projection_capacity_price_file": str(args.price_out),
        "projection_capacity_price_sha256": hashlib.sha256(args.price_out.read_bytes()).hexdigest(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=PRACTICE)
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "practice_global_interval_lp.json")
    parser.add_argument("--time-limit-seconds", type=int, default=300)
    parser.add_argument("--price-out", type=Path,
                        default=ROOT / "results" / "practice_global_interval_prices.npz")
    solve(parser.parse_args())


if __name__ == "__main__":
    main()
