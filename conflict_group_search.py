#!/usr/bin/env python3
"""Conflict-guided exact event LNS on the fixed public dev-reference instance.

For a candidate legal first-visit arc, its *support* consists of its tile and
all incumbent first visits occupying that arc.  Every one of these tiles must
be released if that particular arc is to occur while other first visits stay
fixed.  Separately, each charged wait has an OR mask of unfinished actionable
tiles.  These supports, wait masks, and request-witness sets seed diversified
groups of at most 11 tiles.  They rank neighborhoods; they are not bounds or
claims of feasible improvement.  The event DP and authoritative scorer decide
every result.  No website or private data is accessed.

``generate`` writes JSON accepted by event_subset_batch.py --groups-json.
``search`` repeatedly solves those groups with --release-witnesses semantics,
keeping an append-only trace and atomic best.csv checkpoint under --out.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from event_subset_exact_dp import _core_events, solve
from multistart_large_neighborhood import Oracle, REFERENCE, SCENARIO
from practice_lns import PracticeModel


@dataclass(frozen=True)
class Edge:
    mask: int
    weight: float
    kind: str
    evidence: str
    tile: int = -1


def _bits(mask: int) -> list[int]:
    return [i for i in range(64) if mask & (1 << i)]


def _unit(model: PracticeModel, instant: str) -> int:
    epoch = datetime.fromisoformat(instant.replace("Z", "+00:00")).timestamp()
    result = int(np.searchsorted(model.instants, epoch))
    if result >= model.n_units or abs(model.instants[result] - epoch) > 1e-6:
        raise AssertionError("scored observation not on public 150-second grid")
    return result


def _wait_edges(model: PracticeModel, report: dict) -> dict[int, float]:
    """Reproduce the incumbent's charged-wait OR masks in score points."""
    paid: dict[int, float] = defaultdict(float)
    cursor = 0
    completed = 0
    for action in report["actions"]:
        if action["action"] != "observe":
            continue
        start = _unit(model, action["start_utc"])
        while cursor < start:
            boundary = (cursor // 6 + 1) * 6
            if boundary > start:
                raise AssertionError("implicit wait does not end on an action")
            missing = int(model.actionable[cursor]) & ~completed
            if missing:
                paid[missing] += (boundary - cursor) * 0.15
            cursor = boundary
        if cursor != start:
            raise AssertionError("action starts before prior action ends")
        cursor = start + int(action["elapsed_seconds"]) // 150
        if action["outcome"] == "completed":
            completed |= 1 << model.tile_index[action["tile_id"]]
    score_wait = float(report["score"]["penalties"]["avoidable_wait"])
    if abs(sum(paid.values()) - score_wait) > 1e-6:
        raise AssertionError("wait masks do not reproduce authoritative penalty")
    return dict(paid)


def _read_excluded(paths: list[Path], model: PracticeModel) -> set[int]:
    """Accept prior group JSON or batch trace JSONL for exact-set deduplication."""
    excluded: set[int] = set()
    for path in paths:
        raw = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            records = [json.loads(line) for line in raw.splitlines() if line.strip()]
        else:
            records = json.loads(raw)
            if isinstance(records, dict):
                records = records["groups"]
        for item in records:
            if isinstance(item, dict):
                members = item.get("tiles", item.get("tile_ids", []))
            else:
                members = item
            if not members:
                continue
            mask = 0
            for member in members:
                idx = model.tile_index[member] if isinstance(member, str) else int(member)
                mask |= 1 << idx
            excluded.add(mask)
    return excluded


def _evidence(
    model: PracticeModel, oracle: Oracle, incumbent: Path,
    min_arc_gain: float,
) -> tuple[list[Edge], list[dict], dict, dict]:
    events, report = _core_events(model, incumbent)
    first = sorted((event for event in events if event["first"]), key=lambda e: e["start"])
    if len(first) != 64:
        raise AssertionError("expected one first completion for each of 64 tiles")
    first_starts = np.array([e["start"] for e in first], dtype=np.int32)
    first_ends = np.array([e["end"] for e in first], dtype=np.int32)
    first_tiles = [e["tile"] for e in first]
    original_gain = np.zeros(64)
    original_start = np.zeros(64, dtype=np.int32)
    for event in first:
        i = event["tile"]
        original_start[i] = event["start"]
        original_gain[i] = oracle.scores[i, event["start"]]

    # At most one best legal arc per (tile, night, exact blocker support).  A
    # night is a real calendar night from slots.csv, not an approximate bin.
    best_arc: dict[tuple[int, str, int], tuple[float, int]] = {}
    legal_profitable = 0
    conflict_profitable = 0
    night_of_slot = [slot["night_id"] for slot in model.slots]
    # All rewards are retained by the event DP.  When a request requires every
    # eligible tile, its tagged completion forces that tile's first successful
    # start before the request deadline.  This necessary filter removes the
    # attractive but impossible late-season science peaks for such tiles.
    mandatory_deadline = np.full(64, math.inf, dtype=np.float64)
    for rid, request in model.scorer.requests.items():
        if rid == "RQ0015":
            continue  # officially excused request; the DP omits it as well
        eligible = model.scorer.request_tiles[rid]
        if request.required_tile_count == len(eligible):
            for tile_id in eligible:
                i = model.tile_index[tile_id]
                mandatory_deadline[i] = min(
                    mandatory_deadline[i], request.deadline_utc.timestamp()
                )
    for i in range(64):
        candidates = np.flatnonzero(oracle.scores[i] >= original_gain[i] + min_arc_gain)
        for u0 in candidates:
            u = int(u0)
            if model.instants[u] >= mandatory_deadline[i]:
                continue
            v = u + int(model.exposure_units[i])
            left = int(np.searchsorted(first_ends, u, side="right"))
            right = int(np.searchsorted(first_starts, v, side="left"))
            support = 1 << i
            for j in range(left, right):
                support |= 1 << first_tiles[j]
            gain = float(oracle.scores[i, u] - original_gain[i])
            night = night_of_slot[u // 6]
            key = (i, night, support)
            old = best_arc.get(key)
            if old is None or gain > old[0]:
                best_arc[key] = (gain, u)
            legal_profitable += 1
            conflict_profitable += support.bit_count() > 1

    arcs = []
    arc_weight_by_mask: dict[int, tuple[float, str, int]] = {}
    context_weight_by_mask: dict[int, tuple[float, str, int]] = {}
    for (i, night, support), (gain, u) in best_arc.items():
        v = u + int(model.exposure_units[i])
        arcs.append({
            "tile": i, "night": night, "start": u, "end": v,
            "gain": gain, "support": support,
        })
        # Single-tile optimism is strongly discounted because each such move
        # was already available within earlier 6/8/10-tile neighborhoods.
        weight = gain * (0.15 if support.bit_count() == 1 else 1.0)
        evidence = f"arc:{model.tile_ids[i]}@{night}:{u}"
        old = arc_weight_by_mask.get(support)
        if old is None or weight > old[0]:
            arc_weight_by_mask[support] = (weight, evidence, i)

        # Rank-neighbor context at both original and proposed locations can
        # expose a reordering chain even when the arc overlaps no fixed event.
        origin_rank = int(np.searchsorted(first_starts, original_start[i]))
        target_rank = int(np.searchsorted(first_starts, u))
        for rank in (origin_rank - 1, origin_rank + 1, target_rank - 1, target_rank):
            if 0 <= rank < len(first):
                context = support | (1 << first_tiles[rank])
                if context != support and context.bit_count() <= 11:
                    w = gain * 0.18
                    old = context_weight_by_mask.get(context)
                    if old is None or w > old[0]:
                        context_weight_by_mask[context] = (w, evidence, i)

    waits = _wait_edges(model, report)
    edges = [
        Edge(mask, weight, "arc", evidence, i)
        for mask, (weight, evidence, i) in arc_weight_by_mask.items()
        if mask.bit_count() <= 11 and weight > 0
    ]
    edges.extend(
        Edge(mask, weight, "arc_context", evidence, i)
        for mask, (weight, evidence, i) in context_weight_by_mask.items()
        if mask.bit_count() <= 11 and weight > 0
    )
    edges.extend(
        Edge(mask, cost, "paid_wait", f"paid_wait:{mask.bit_count()}")
        for mask, cost in waits.items() if mask.bit_count() <= 11
    )
    request_masks = {}
    for event in events:
        if event["request"] and event["request"] != "RQ0015":
            request_masks[event["request"]] = (
                request_masks.get(event["request"], 0) | (1 << event["tile"])
            )
    edges.extend(
        Edge(mask, 12.0, "request", f"request:{rid}")
        for rid, mask in request_masks.items() if 2 <= mask.bit_count() <= 11
    )
    arcs.sort(key=lambda a: (-a["gain"], a["tile"], a["start"]))
    metrics = {
        "incumbent_sha256": hashlib.sha256(incumbent.read_bytes()).hexdigest(),
        "incumbent_score": report["score"]["total"],
        "legal_profitable_arc_count": legal_profitable,
        "direct_conflict_profitable_arc_count": conflict_profitable,
        "night_support_arc_count": len(arcs),
        "distinct_arc_supports": len(arc_weight_by_mask),
        "distinct_paid_wait_masks": len(waits),
        "paid_wait_points": sum(waits.values()),
        "largest_wait_mask_points": max(waits.values(), default=0.0),
        "largest_wait_mask_size": max(waits, key=waits.get).bit_count() if waits else 0,
        "request_witness_sets": len(request_masks),
        "mandatory_first_deadline_tiles": int(np.isfinite(mandatory_deadline).sum()),
    }
    return edges, arcs, metrics, {"waits": waits, "first": first, "original_gain": original_gain}


def _edge_score(mask: int, edges: list[Edge]) -> float:
    # Many legal arcs for the same tile are mutually exclusive.  Count only
    # its best covered science arc, while wait masks correspond to disjoint
    # paid intervals and legitimately add.  This remains a ranking heuristic.
    best_by_tile = [0.0] * 64
    other = 0.0
    for edge in edges:
        if edge.mask & mask != edge.mask:
            continue
        if edge.tile >= 0:
            best_by_tile[edge.tile] = max(best_by_tile[edge.tile], edge.weight)
        else:
            other += edge.weight
    return other + sum(best_by_tile)


def _expand(
    seed: int, size: int, edges: list[Edge], tile_potential: list[float],
    rng: random.Random,
) -> int:
    mask = seed
    while mask.bit_count() < size:
        remaining = size - mask.bit_count()
        best = -math.inf
        chosen = 0
        # Whole-edge additions preserve a real conflict/wait/request motif.
        for edge in edges:
            new = edge.mask & ~mask
            n = new.bit_count()
            if not 1 <= n <= remaining:
                continue
            overlap = (edge.mask & mask).bit_count()
            merit = edge.weight * (1.0 + 0.6 * overlap) / (n ** 1.3)
            merit *= rng.uniform(0.65, 1.35)
            if merit > best:
                best, chosen = merit, edge.mask
        if chosen:
            mask |= chosen
            continue
        available = [i for i in range(64) if not mask & (1 << i)]
        i = max(available, key=lambda j: tile_potential[j] * rng.uniform(0.65, 1.35))
        mask |= 1 << i
    return mask


def generate_groups(
    model: PracticeModel, oracle: Oracle, incumbent: Path,
    sizes: list[int], count: int, seed: int, excluded: set[int] | None = None,
    min_arc_gain: float = 0.5,
) -> tuple[list[dict], dict]:
    """Build diversified fixed-size neighborhoods from factual local evidence."""
    if not sizes or any(size < 1 or size > 11 for size in sizes):
        raise ValueError("all group sizes must be in 1..11")
    rng = random.Random(seed)
    excluded = set() if excluded is None else set(excluded)
    edges, arcs, metrics, aux = _evidence(model, oracle, incumbent, min_arc_gain)
    useful_edges = [edge for edge in edges if edge.mask.bit_count() <= max(sizes)]
    useful_edges.sort(key=lambda e: (-e.weight, e.mask, e.kind))
    tile_potential = [0.1] * 64
    for i in range(64):
        tile_potential[i] += max(0.0, float(np.nanmax(oracle.scores[i]) - aux["original_gain"][i])) * 0.08
    for edge in useful_edges:
        if edge.kind == "paid_wait":
            for i in _bits(edge.mask):
                tile_potential[i] += edge.weight / max(1, edge.mask.bit_count()) * 0.1

    pool: dict[int, dict] = {}
    # Separate seed families prevent a large cluster of correlated high-score
    # arcs from burying the wait masks that require all 11 tiles to be freed.
    wait_seeds = [edge for edge in useful_edges if edge.kind == "paid_wait"]
    conflict_seeds = [edge for edge in useful_edges
                      if edge.kind in ("arc", "arc_context") and edge.mask.bit_count() >= 2]
    conflict_seeds = conflict_seeds[:450]
    request_seeds = [edge for edge in useful_edges if edge.kind == "request"]
    seed_edges = wait_seeds + conflict_seeds + request_seeds
    # Include the strongest arc of every tile, even if the global top list is
    # dominated by a few high-value tiles.
    per_tile = set()
    for arc in arcs:
        if arc["tile"] not in per_tile:
            per_tile.add(arc["tile"])
            seed_edges.append(Edge(
                arc["support"], max(1.0, arc["gain"]), "per_tile_arc",
                f"arc:{model.tile_ids[arc['tile']]}@{arc['night']}:{arc['start']}",
                arc["tile"],
            ))

    for size in sizes:
        for j, anchor in enumerate(seed_edges):
            if anchor.mask.bit_count() > size:
                continue
            # Multiple continuations of the same mathematical seed give the
            # oracle different cross-night displacement opportunities.
            repetitions = 1 if anchor.mask.bit_count() == size else 3
            for repetition in range(repetitions):
                group = _expand(anchor.mask, size, useful_edges, tile_potential, rng)
                if group in excluded:
                    continue
                obj = _edge_score(group, useful_edges)
                prior = pool.get(group)
                family = (
                    "paid_wait" if anchor.kind == "paid_wait" else
                    "request" if anchor.kind == "request" else "conflict_arc"
                )
                covered_wait = sum(
                    cost for wait_mask, cost in aux["waits"].items()
                    if wait_mask & group == wait_mask
                )
                priority = (
                    covered_wait + 0.05 * obj if family == "paid_wait" else
                    anchor.weight + 0.10 * covered_wait + 0.04 * obj
                )
                row = {
                    "name": f"conflict_k{size}_{anchor.kind}_{j}_{repetition}",
                    "tiles": [model.tile_ids[i] for i in _bits(group)],
                    "surrogate_coverage": round(obj, 6),
                    "anchor": anchor.evidence,
                    "family": family, "anchor_tile": anchor.tile,
                    "priority": round(priority, 6),
                    "covered_wait_points": round(covered_wait, 6),
                }
                if prior is None or row["priority"] > prior["priority"]:
                    pool[group] = row

        # Nonlocal paired-arc seeds have up to 11 tiles; this connects two
        # separate science opportunities without imposing rank proximity.
        top_arcs = []
        arc_count_by_tile: dict[int, int] = defaultdict(int)
        for arc in arcs:
            if arc_count_by_tile[arc["tile"]] < 4:
                top_arcs.append(arc)
                arc_count_by_tile[arc["tile"]] += 1
        for j in range(min(count * 8, 3000)):
            if len(top_arcs) < 2:
                break
            a = top_arcs[rng.randrange(len(top_arcs))]
            b = top_arcs[rng.randrange(len(top_arcs))]
            if a["tile"] == b["tile"]:
                continue
            group = a["support"] | b["support"]
            if group.bit_count() > size:
                continue
            group = _expand(group, size, useful_edges, tile_potential, rng)
            if group in excluded or group in pool:
                continue
            covered_wait = sum(
                cost for wait_mask, cost in aux["waits"].items()
                if wait_mask & group == wait_mask
            )
            pool[group] = {
                "name": f"conflict_k{size}_arc_pair_{j}",
                "tiles": [model.tile_ids[i] for i in _bits(group)],
                "surrogate_coverage": round(_edge_score(group, useful_edges), 6),
                "anchor": f"{model.tile_ids[a['tile']]}@{a['night']}+{model.tile_ids[b['tile']]}@{b['night']}",
                "family": "arc_pair", "anchor_tile": a["tile"],
                "priority": round(a["gain"] + b["gain"] + 0.1 * covered_wait, 6),
                "covered_wait_points": round(covered_wait, 6),
            }

    # Round-robin families enforce breadth.  Within a family, favor evidence
    # value while discounting both repeated tile anchors and near-copy sets.
    chosen: list[dict] = []
    candidates: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for mask, row in pool.items():
        candidates[row["family"]].append((mask, row))
    selected_masks: list[int] = []
    anchor_counts: dict[int, int] = defaultdict(int)
    cycle = ["paid_wait", "conflict_arc", "arc_pair", "conflict_arc",
             "paid_wait", "request", "arc_pair"]
    cycle_index = 0
    while any(candidates.values()) and len(chosen) < count:
        family = cycle[cycle_index % len(cycle)]
        cycle_index += 1
        if not candidates[family]:
            continue
        best_index = -1
        best_merit = -math.inf
        for j, (mask, row) in enumerate(candidates[family]):
            nearest = max(
                ((mask & old).bit_count() / (mask | old).bit_count() for old in selected_masks),
                default=0.0,
            )
            tile = row["anchor_tile"]
            repeat = anchor_counts[tile] if tile >= 0 else 0
            merit = row["priority"] * (1.0 - 0.70 * nearest) / (1.0 + 0.40 * repeat)
            if merit > best_merit:
                best_merit, best_index = merit, j
        mask, row = candidates[family].pop(best_index)
        chosen.append(row)
        selected_masks.append(mask)
        if row["anchor_tile"] >= 0:
            anchor_counts[row["anchor_tile"]] += 1

    metrics.update({
        "seed": seed, "sizes": sizes, "requested_count": count,
        "candidate_pool_count": len(pool), "excluded_count": len(excluded),
        "generated_count": len(chosen),
        "generated_by_family": dict((family, sum(r["family"] == family for r in chosen))
                                    for family in cycle),
        "best_covered_wait_points": max((r["covered_wait_points"] for r in chosen), default=0.0),
        "max_surrogate_coverage": max((r["surrogate_coverage"] for r in chosen), default=0.0),
    })
    return chosen, metrics


def _atomic_copy(source: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def _search(args: argparse.Namespace) -> None:
    if args.max_stagnant_groups < 1:
        raise ValueError("max_stagnant_groups must be positive")
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    best_path = out / "best.csv"
    if not best_path.exists():
        _atomic_copy(args.incumbent, best_path)
    model = PracticeModel(SCENARIO, REFERENCE)
    oracle = Oracle(model)
    best = float(model.authoritative_score(best_path)["score"]["total"])
    excluded = _read_excluded(args.exclude_groups, model)
    trace = out / "trace.jsonl"
    if trace.exists():
        excluded |= _read_excluded([trace], model)
    stagnant = 0
    if trace.exists():
        for line in trace.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            stagnant = 0 if json.loads(line).get("accepted") else stagnant + 1
    start = time.monotonic()
    deadline = start + args.hours * 3600.0
    index = sum(1 for line in trace.open(encoding="utf-8")) if trace.exists() else 0
    round_no = 0
    with trace.open("a", encoding="utf-8") as log:
        while time.monotonic() < deadline and stagnant < args.max_stagnant_groups:
            round_no += 1
            groups, diagnostics = generate_groups(
                model, oracle, best_path, args.sizes,
                args.groups_per_round, args.seed + round_no - 1,
                excluded, args.min_arc_gain,
            )
            if not groups:
                break
            (out / "latest_generator_report.json").write_text(
                json.dumps(diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            for group in groups:
                if time.monotonic() >= deadline:
                    break
                index += 1
                ids = group["tiles"]
                mask = sum(1 << model.tile_index[t] for t in ids)
                excluded.add(mask)
                candidate = out / "candidate.csv"
                t0 = time.monotonic()
                result = solve(
                    model, oracle, best_path,
                    [model.tile_index[t] for t in ids], candidate,
                    release_witnesses=True,
                )
                score = result.get("candidate_total")
                row = {
                    "index": index, "round": round_no, "name": group["name"],
                    "tiles": ids, "anchor": group["anchor"],
                    "covered_wait_points": group["covered_wait_points"],
                    "surrogate_coverage": group["surrogate_coverage"],
                    "status": result["status"], "score": score,
                    "best_before": best, "seconds": time.monotonic() - t0,
                    "release_witnesses": True,
                }
                if score is not None and score > best + 1e-6:
                    best = float(score)
                    _atomic_copy(candidate, best_path)
                    row["accepted"] = True
                    row["score_breakdown"] = result["score"]
                    stagnant = 0
                    print(json.dumps({"accepted": best, "index": index,
                                      "name": group["name"]}), flush=True)
                else:
                    stagnant += 1
                log.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                log.flush()
                if stagnant >= args.max_stagnant_groups:
                    break
            print(json.dumps({"round": round_no, "groups_solved": index,
                              "best": best, "elapsed_seconds": time.monotonic() - start}),
                  flush=True)
    summary = {
        "best": best, "best_path": str(best_path), "groups_solved": index,
        "elapsed_seconds": time.monotonic() - start,
        "deadline_hours": args.hours, "release_witnesses": True,
        "sizes": args.sizes, "seed": args.seed,
        "best_sha256": hashlib.sha256(best_path.read_bytes()).hexdigest(),
        "max_stagnant_groups": args.max_stagnant_groups,
        "stagnant_groups": stagnant,
        "stopped_reason": ("stagnation" if stagnant >= args.max_stagnant_groups
                           else "deadline_or_no_groups"),
    }
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    search = sub.add_parser("search")
    for p in (generate, search):
        p.add_argument("--incumbent", type=Path, default=Path("results/practice_best.csv"))
        p.add_argument("--seed", type=int, default=20260924)
        p.add_argument("--sizes", nargs="+", type=int, default=[11])
        p.add_argument("--exclude-groups", nargs="*", type=Path, default=[])
        p.add_argument("--min-arc-gain", type=float, default=0.5)
    generate.add_argument("--count", type=int, default=300)
    generate.add_argument("--groups-out", type=Path, required=True)
    generate.add_argument("--report-out", type=Path, required=True)
    search.add_argument("--out", type=Path, required=True)
    search.add_argument("--hours", type=float, default=9.0)
    search.add_argument("--groups-per-round", type=int, default=500)
    search.add_argument("--max-stagnant-groups", type=int, default=100)
    args = parser.parse_args()
    if args.command == "search":
        _search(args)
    else:
        model = PracticeModel(SCENARIO, REFERENCE)
        oracle = Oracle(model)
        excluded = _read_excluded(args.exclude_groups, model)
        groups, report = generate_groups(
            model, oracle, args.incumbent, args.sizes,
            args.count, args.seed, excluded, args.min_arc_gain,
        )
        args.groups_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.groups_out.write_text(
            json.dumps(groups, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.report_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
