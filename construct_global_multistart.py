#!/usr/bin/env python3
"""Global randomized first-order/request-witness construction for practice.

Each seed starts from an empty schedule. It schedules all 64 first completions
and all 28 successful request witnesses, choosing legal starts on the full
150-second grid. The resulting first-visit order is then passed to the exact
fixed-order active-request DP for authoritative scoring. No original request
revisit times or first-visit order are used by the constructor.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import bounds_public as geometry
from practice_lns import PracticeModel
from sequence_active_requests_dp import solve as exact_fixed_order
from sequence_block_dp import _write
from sequence_dp import score_table


ROOT = Path(__file__).resolve().parent
PRACTICE = ROOT / "scenarios" / "dev-reference"
FULL = (1 << 64) - 1
DAY_UNITS = 48 * geometry.POINTS_PER_SLOT


@dataclass(frozen=True)
class Link:
    request_id: str
    tile: int
    starts: np.ndarray
    pool: np.ndarray
    deadline_unit: int


def _candidate_pool(starts: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Keep top-valued starts and both ends of every two-day time bucket."""
    bucket = 2 * DAY_UNITS
    selected: list[int] = []
    if len(starts) == 0:
        return np.empty(0, dtype=np.int32)
    groups = starts // bucket
    split = np.r_[0, np.flatnonzero(groups[1:] != groups[:-1]) + 1, len(starts)]
    for lo, hi in zip(split[:-1], split[1:]):
        part = starts[lo:hi]
        selected.extend((int(part[0]), int(part[-1])))
        top = np.argsort(values[part])[-6:]
        selected.extend(map(int, part[top]))
    return np.array(sorted(set(selected)), dtype=np.int32)


def _request_links(model: PracticeModel, scores: np.ndarray, pools: list[np.ndarray],
                   rq4_tile: str) -> list[Link]:
    links = []
    for request in sorted(model.scorer.requests.values(), key=lambda r: r.request_id):
        if request.request_id == "RQ0015":
            continue
        names = (
            (rq4_tile,) if request.request_id == "RQ0004"
            else tuple(sorted(model.scorer.request_tiles[request.request_id]))
        )
        if len(names) != request.required_tile_count:
            raise AssertionError("request branch cardinality changed")
        lo = max(request.issued_at_utc.timestamp(), request.available_from_utc.timestamp())
        hi = request.deadline_utc.timestamp()
        for tile_id in names:
            i = model.tile_index[tile_id]
            starts = np.flatnonzero(
                np.isfinite(scores[i])
                & (model.instants >= lo)
                & (model.instants < hi)
            ).astype(np.int32)
            if len(starts) == 0:
                raise ValueError(f"no legal request witness: {request.request_id}/{tile_id}")
            pool = pools[i]
            pool = pool[
                (model.instants[pool] >= lo)
                & (model.instants[pool] < hi)
            ]
            deadline_unit = int(np.searchsorted(model.instants, hi, side="left"))
            links.append(Link(request.request_id, i, starts, pool, deadline_unit))
    if len(links) != 28:
        raise AssertionError("expected 28 request witness tasks")
    return links


def _starts_after(starts: np.ndarray, pool: np.ndarray, values: np.ndarray,
                  u: int, cap: int, rng: random.Random) -> tuple[int, ...]:
    pos = int(np.searchsorted(starts, u, side="left"))
    if pos == len(starts) or starts[pos] > cap:
        return ()
    result = {int(starts[pos])}
    p = int(np.searchsorted(pool, u, side="left"))
    stop = int(np.searchsorted(pool, cap, side="right"))
    result.update(map(int, pool[p:min(stop, p + 4)]))
    if p + 4 < stop:
        result.add(int(pool[p + rng.randrange(4, min(16, stop - p))]))
    if p < stop:
        available = pool[p:stop]
        result.add(int(available[np.argmax(values[available])]))
    return tuple(sorted(result))


def _wait_cost(model: PracticeModel, prefix: np.ndarray,
               unfinished: int, u: int, v: int) -> float:
    if v <= u:
        return 0.0
    su, sv = u // 6, v // 6
    if su == sv:
        return 0.15 * (v - u) * bool(int(model.actionable[u]) & unfinished)
    first = 0.15 * (6 - u % 6) * bool(int(model.actionable[u]) & unfinished)
    middle = 0.9 * int(prefix[sv] - prefix[su + 1])
    last = 0.15 * (v % 6) * bool(int(model.actionable[sv * 6]) & unfinished)
    return first + middle + last


def construct_one(model: PracticeModel, scores: np.ndarray,
                  tile_starts: list[np.ndarray], pools: list[np.ndarray],
                  seed: int) -> dict | None:
    rng = random.Random(seed)
    rq4_tile = rng.choice(("T00004", "T00012"))
    links = _request_links(model, scores, pools, rq4_tile)
    by_tile = [[] for _ in model.tiles]
    for j, link in enumerate(links):
        by_tile[link.tile].append(j)
    first_last = np.array([int(v[-1]) for v in tile_starts], dtype=np.int32)
    link_last = np.array([int(link.starts[-1]) for link in links], dtype=np.int32)
    if any(len(v) == 0 for v in tile_starts):
        raise ValueError("a tile has no successful first start")
    first_cap = first_last.copy()
    for link in links:
        first_cap[link.tile] = min(first_cap[link.tile], int(link.starts[-1]))
    target_quality = np.array([
        float(np.max(scores[i, v[v <= first_cap[i]]]))
        for i, v in enumerate(tile_starts)
    ])

    completed = 0
    achieved = 0
    u = 0
    order: list[int] = []
    events: list[tuple[int, int, str, bool]] = []
    scientific = 0.0
    wait_est = 0.0
    params = {
        "wait_weight": rng.uniform(0.3, 1.8),
        "calendar_weight": rng.uniform(0.1, 3.0),
        "quality_weight": rng.uniform(0.7, 1.35),
        "regret_weight": rng.uniform(1.2, 3.8),
        "urgency_weight": rng.uniform(25.0, 180.0),
        "noise_scale": rng.uniform(6.0, 55.0),
        "tile_bias_scale": rng.uniform(5.0, 45.0),
    }
    tile_bias = [rng.gauss(0.0, params["tile_bias_scale"]) for _ in model.tiles]
    all_links = (1 << len(links)) - 1
    for _step in range(len(model.tiles) + len(links)):
        if completed == FULL and achieved == all_links:
            break
        unfinished = FULL ^ completed
        slot_actionable = ((model.actionable[::6] & np.uint64(unfinished)) != 0)
        wait_prefix = np.r_[0, np.cumsum(slot_actionable, dtype=np.int32)]
        options: list[tuple[float, int, int, int, bool, float, float]] = []
        for i in range(len(model.tiles)):
            first = not bool(completed & (1 << i))
            candidate: set[tuple[int, int]] = set()
            if first:
                candidate.update((a, -1) for a in _starts_after(
                    tile_starts[i], pools[i], scores[i], u,
                    int(first_cap[i]), rng,
                ))
            for j in by_tile[i]:
                if achieved & (1 << j):
                    continue
                link = links[j]
                candidate.update((a, j) for a in _starts_after(
                    link.starts, link.pool, scores[i], u,
                    int(link_last[j]), rng,
                ))
            for a, j in candidate:
                if not first and j < 0:
                    continue
                end = a + int(model.exposure_units[i])
                after_completed = completed | ((1 << i) if first else 0)
                after_achieved = achieved | ((1 << j) if j >= 0 else 0)
                if any(
                    end > first_last[z]
                    for z in range(len(model.tiles))
                    if not (after_completed & (1 << z))
                ):
                    continue
                if any(
                    end > link_last[z]
                    for z in range(len(links))
                    if not (after_achieved & (1 << z))
                ):
                    continue
                wait = _wait_cost(model, wait_prefix, unfinished, u, a)
                quality = float(scores[i, a]) if first else 0.0
                gain = params["quality_weight"] * quality
                if first:
                    gain -= params["regret_weight"] * (
                        target_quality[i] - quality
                    )
                gain -= params["wait_weight"] * wait
                gain -= params["calendar_weight"] * ((a - u) / DAY_UNITS)
                if first:
                    gain += tile_bias[i]
                if j >= 0:
                    remaining_days = max(0.0, (links[j].deadline_unit - u) / DAY_UNITS)
                    gain += 140.0 + params["urgency_weight"] / (1.0 + remaining_days)
                noise = -math.log(-math.log(max(1e-12, rng.random())))
                gain += params["noise_scale"] * noise
                options.append((gain, a, i, j, first, quality, wait))
        if not options:
            return None
        _, a, i, j, first, quality, wait = max(options)
        if first:
            completed |= 1 << i
            order.append(i)
            scientific += quality
        if j >= 0:
            achieved |= 1 << j
        wait_est += wait
        events.append((a, i, links[j].request_id if j >= 0 else "", first))
        u = a + int(model.exposure_units[i])
    if completed != FULL or achieved != all_links or len(order) != 64:
        return None
    return {
        "mode": "request_regret_greedy",
        "seed": seed,
        "rq0004_choice": rq4_tile,
        "params": params,
        "first_order": order,
        "events": events,
        "estimated_science": scientific,
        "estimated_wait": wait_est,
        "estimated_total": scientific + 3920.0 - wait_est,
        "event_count": len(events),
        "last_unit": u,
    }


def _wait_shadows(model: PracticeModel) -> np.ndarray:
    """Static OR-wait price split equally across all actionable tiles."""
    actionable = model.actionable[::geometry.POINTS_PER_SLOT]
    count = np.maximum(
        1, np.array([int(mask).bit_count() for mask in actionable],
                    dtype=np.int16)
    )
    slot = np.arange(model.n_units) // geometry.POINTS_PER_SLOT
    offset = np.arange(model.n_units) % geometry.POINTS_PER_SLOT
    result = np.empty((len(model.tiles), model.n_units), dtype=np.float32)
    for i in range(len(model.tiles)):
        active = ((actionable & (np.uint64(1) << np.uint64(i))) != 0)
        rate = active.astype(np.float32) / count
        previous = np.r_[0.0, np.cumsum(0.9 * rate, dtype=np.float64)]
        result[i] = previous[slot] + 0.15 * offset * rate[slot]
    return result


def construct_peak_order(model: PracticeModel, scores: np.ndarray,
                         tile_starts: list[np.ndarray], pools: list[np.ndarray],
                         shadows: np.ndarray, price_prefix: np.ndarray,
                         seed: int, fixed_omega: float | None,
                         fixed_capacity: float | None,
                         fixed_noise: float | None) -> dict:
    """Independent per-tile peak targets with request-deadline caps.

    The targets are a global surrogate and need not form a feasible schedule;
    the exact inner DP determines a valid schedule for their induced order.
    """
    rng = random.Random(seed)
    numerical = np.random.default_rng(seed)
    rq4_tile = rng.choice(("T00004", "T00012"))
    links = _request_links(model, scores, pools, rq4_tile)
    cap = np.array([int(v[-1]) for v in tile_starts], dtype=np.int32)
    for link in links:
        cap[link.tile] = min(cap[link.tile], int(link.starts[-1]))
    omega = (
        rng.choice((0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0))
        if fixed_omega is None else fixed_omega
    )
    capacity_weight = 0.0 if fixed_capacity is None else fixed_capacity
    noise_scale = (
        rng.choice((0.0, 2.0, 5.0, 10.0, 20.0, 35.0))
        if fixed_noise is None else fixed_noise
    )
    targets = []
    total_science = 0.0
    total_shadow = 0.0
    for i in range(len(model.tiles)):
        available = pools[i][pools[i] <= cap[i]]
        if len(available) == 0:
            available = tile_starts[i][tile_starts[i] <= cap[i]]
        if len(available) == 0:
            raise ValueError("request deadline leaves no first arc")
        cost = (
            price_prefix[available + int(model.exposure_units[i])]
            - price_prefix[available]
        ) / 100.0
        utility = (
            scores[i, available] - omega * shadows[i, available]
            - capacity_weight * cost
        )
        if noise_scale:
            utility = utility + numerical.gumbel(0.0, noise_scale, len(available))
        u = int(available[np.argmax(utility)])
        targets.append((u, i))
        total_science += float(scores[i, u])
        total_shadow += float(shadows[i, u])
    targets.sort(key=lambda pair: (pair[0], rng.random()))
    order = [i for _, i in targets]
    return {
        "mode": "independent_peak_shadow",
        "seed": seed,
        "rq0004_choice": rq4_tile,
        "params": {"omega": omega, "capacity_weight": capacity_weight,
                   "gumbel_scale": noise_scale},
        "first_order": order,
        "events": [(u, i, "", True) for u, i in targets],
        "estimated_science": total_science,
        "estimated_wait": total_shadow,
        "estimated_total": total_science + 3920.0 - total_shadow,
        "event_count": 64,
        "last_unit": max(u + int(model.exposure_units[i]) for u, i in targets),
    }


def _distance(a: list[int], b: list[int]) -> int:
    pos = [0] * len(a)
    for k, i in enumerate(a):
        pos[i] = k
    return sum(abs(pos[i] - k) for k, i in enumerate(b))


def _choose_diverse(candidates: list[dict], n: int) -> list[dict]:
    if n <= 0:
        return []
    remaining = sorted(candidates, key=lambda x: x["estimated_total"], reverse=True)
    if not remaining:
        return []
    chosen = [remaining.pop(0)]
    while remaining and len(chosen) < n:
        top = remaining[: min(100, len(remaining))]
        maximum = max(x["estimated_total"] for x in top)
        minimum = min(x["estimated_total"] for x in top)
        spread = max(1.0, maximum - minimum)
        selected = max(
            top,
            key=lambda x: (
                (x["estimated_total"] - minimum) / spread
                + 2.0 * min(_distance(x["first_order"], y["first_order"])
                            for y in chosen) / 2048.0
            ),
        )
        chosen.append(selected)
        remaining.remove(selected)
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=200)
    parser.add_argument("--seed-base", type=int, default=260924)
    parser.add_argument("--oracle-top", type=int, default=5)
    parser.add_argument("--mode", choices=("greedy", "peak", "both"),
                        default="both")
    parser.add_argument("--peak-omega", type=float)
    parser.add_argument("--peak-capacity", type=float)
    parser.add_argument("--peak-noise", type=float)
    parser.add_argument("--out-dir", type=Path,
                        default=ROOT / "runs" / "practice_global_construct")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    model = PracticeModel(PRACTICE, ROOT / "results" / "practice_reference.csv")
    scores, programs = score_table(model)
    tile_starts = [np.flatnonzero(np.isfinite(scores[i])).astype(np.int32)
                   for i in range(len(model.tiles))]
    pools = [_candidate_pool(v, scores[i]) for i, v in enumerate(tile_starts)]
    shadows = _wait_shadows(model) if args.mode != "greedy" else None
    with np.load(ROOT / "runs" / "practice_bound" / "resource_prices.npz",
                 allow_pickle=False) as loaded:
        prices = loaded["prices_cents"].astype(np.int64)
    price_prefix = np.r_[0, np.cumsum(prices, dtype=np.int64)]
    candidates = []
    failures = []
    seen_orders = set()
    for seed in range(args.seed_base, args.seed_base + args.seeds):
        route = args.mode
        if route == "both":
            route = "peak" if seed % 2 else "greedy"
        candidate = (
            construct_peak_order(
                model, scores, tile_starts, pools, shadows, price_prefix,
                seed, args.peak_omega, args.peak_capacity, args.peak_noise,
            )
            if route == "peak" else
            construct_one(model, scores, tile_starts, pools, seed)
        )
        if candidate is None:
            failures.append(seed)
            continue
        signature = tuple(candidate["first_order"])
        if signature not in seen_orders:
            seen_orders.add(signature)
            candidates.append(candidate)
    chosen = _choose_diverse(candidates, max(args.oracle_top, 5))
    results = []
    for candidate in chosen[:args.oracle_top]:
        seed = candidate["seed"]
        output = args.out_dir / f"seed_{seed}" / "decisions.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            path, partial_flags, predicted, optional, partial, data = (
                exact_fixed_order(
                    model, scores, programs, candidate["first_order"]
                )
            )
            _write(model, output, path)
            report = model.authoritative_score(output)
            observed = [a for a in report["actions"] if a["action"] == "observe"]
            if len(observed) != len(partial_flags) or any(
                a["penalty"] != 0.0 or a["outcome"] !=
                ("weather_interrupted" if p else "completed")
                for a, p in zip(observed, partial_flags)
            ):
                raise AssertionError("official action replay differs from exact DP")
            if report["score"]["request_reward"] != 3920.0:
                raise AssertionError("request reward differs from 17 enforced tasks")
            if abs(report["score"]["total"] - (predicted + 3920.0)) > 1e-5:
                raise AssertionError("exact DP value differs from official scorer")
            results.append({
                "seed": seed,
                "score": report["score"]["total"],
                "science": report["score"]["base_science"] + report["score"]["program_bonus"],
                "wait": report["score"]["penalties"].get("avoidable_wait", 0.0),
                "optional": optional,
                "weather_partial": partial,
                "decisions": str(output.resolve().relative_to(ROOT)),
                "first_order_sha256": hashlib.sha256(bytes(candidate["first_order"])).hexdigest(),
            })
        except ValueError as exc:
            results.append({"seed": seed, "error": str(exc)})
    manifest = {
        "scope": "public dev-reference global construction",
        "algorithm": "randomized regret/urgency greedy on 150-second complete arcs; exact fixed-order active-request DP for selected orders",
        "mode": args.mode,
        "seed_base": args.seed_base,
        "attempted_seeds": args.seeds,
        "constructed": len(candidates),
        "failed_construction_seeds": failures,
        "distinct_first_orders": len(seen_orders),
        "oracle_top": args.oracle_top,
        "oracle_results": results,
        "best_official_score": max((r["score"] for r in results if "score" in r), default=None),
        "elapsed_seconds": time.monotonic() - t0,
        "constructed_orders": [
            {"seed": c["seed"], "estimated_total": c["estimated_total"],
             "mode": c["mode"],
             "params": c["params"],
             "rq0004_choice": c["rq0004_choice"],
             "first_order": [model.tile_ids[i] for i in c["first_order"]]}
            for c in sorted(candidates, key=lambda x: x["estimated_total"],
                            reverse=True)
        ],
        "selected_candidates": [
            {**c, "first_order": [model.tile_ids[i] for i in c["first_order"]],
             "events": [[u, model.tile_ids[i], req, first]
                        for u, i, req, first in c["events"]]}
            for c in chosen
        ],
    }
    target = args.out_dir / "manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "attempted": args.seeds, "constructed": len(candidates),
        "distinct": len(seen_orders), "oracle": results,
        "best": manifest["best_official_score"],
        "elapsed_seconds": manifest["elapsed_seconds"],
        "manifest": str(target),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
