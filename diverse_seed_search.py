#!/usr/bin/env python3
"""Diverse first-completion order search on the public dev-reference instance.

This is a feasibility search, not an optimality proof.  Every candidate order
is scored by the exact fixed-order active-request DP.  Each new global best
and each exported population seed is independently replayed by the official
local scorer.  It reads only versioned repository inputs, writes only to OUT,
and never contacts the competition website.

Unlike a CSV's first *attempt* at a tile, the state here is the order of first
*successful completions*.  Interrupted observations can make these orders very
different.  The source order is extracted from official replay actions.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from multistart_large_neighborhood import Oracle
from practice_lns import PracticeModel


ROOT = Path(__file__).resolve().parent
SCENARIO = ROOT / "scenarios" / "dev-reference"
REFERENCE = ROOT / "results" / "practice_reference.csv"
INCUMBENT = ROOT / "results" / "practice_best.csv"
TRAINING = ROOT / "results" / "practice_order_training.npz"
FROZEN = ROOT / "results" / "practice_order_frozen_proposals.json"
FROZEN_SCORES = ROOT / "results" / "practice_order_frozen_scores.json"


@dataclass
class Member:
    order: tuple[int, ...]
    score: float
    source: str


@dataclass
class Chain:
    order: tuple[int, ...]
    score: float
    temperature: float


def distance(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    rank = [0] * 64
    for k, tile in enumerate(a):
        rank[tile] = k
    return sum(abs(rank[tile] - k) for k, tile in enumerate(b))


def completion_order(model: PracticeModel, path: Path) -> tuple[tuple[int, ...], float]:
    report = model.authoritative_score(path)
    seen = set()
    order = []
    for action in report["actions"]:
        if action["action"] != "observe" or action["outcome"] != "completed":
            continue
        i = model.tile_index[action["tile_id"]]
        if i not in seen:
            seen.add(i)
            order.append(i)
    if len(order) != 64:
        raise ValueError(f"{path} does not successfully complete all 64 tiles")
    return tuple(order), float(report["score"]["total"])


def proposed_orders(model: PracticeModel, incumbent: tuple[int, ...],
                    *, limit: int) -> list[tuple[tuple[int, ...], str]]:
    """Use only tracked scored-order data; take high scores and far seeds."""
    candidates: list[tuple[tuple[int, ...], float, str]] = [(incumbent, 1e9, "incumbent")]
    if TRAINING.exists():
        with np.load(TRAINING, allow_pickle=False) as data:
            indices = np.asarray(data["order_indices"], dtype=np.uint8)
            scores = np.asarray(data["scores"], dtype=np.float64)
        for j in np.argsort(-scores)[:min(300, len(scores))]:
            candidates.append((tuple(map(int, indices[j])), float(scores[j]), f"training_{j}"))
    if FROZEN.exists():
        payload = json.loads(FROZEN.read_text(encoding="utf-8"))
        exact_scores = {}
        if FROZEN_SCORES.exists():
            frozen_results = json.loads(FROZEN_SCORES.read_text(encoding="utf-8"))
            exact_scores = {int(row["seed"]): float(row["score"])
                            for row in frozen_results["results"] if "score" in row}
        for item in payload["constructed_orders"]:
            names = item["first_order"]
            order = tuple(model.tile_index[tile_id] for tile_id in names)
            candidates.append((order, exact_scores.get(int(item["seed"]),
                                                float(item.get("base_exact_score", 0))),
                               f"frozen_{item['seed']}"))
    distinct: dict[tuple[int, ...], tuple[float, str]] = {}
    for order, score, source in candidates:
        if len(order) != 64 or len(set(order)) != 64:
            raise ValueError(f"bad order from {source}")
        if order not in distinct or distinct[order][0] < score:
            distinct[order] = (score, source)
    ranked = sorted(distinct.items(), key=lambda item: item[1][0], reverse=True)
    selected = [(incumbent, "incumbent")]
    chosen = {incumbent}
    for order, (_score, source) in ranked:
        if len(selected) >= min(limit, 10):
            break
        if order not in chosen:
            selected.append((order, source))
            chosen.add(order)
    # Mix score rank and diversity: a high-scoring seed from another basin is
    # more useful than dozens of tiny perturbations of the incumbent.
    while len(selected) < limit and len(chosen) < len(ranked):
        pool = [(order, estimate, source) for order, (estimate, source) in ranked[:180]
                if order not in chosen]
        if not pool:
            break
        highest = max(item[1] for item in pool)
        order, _estimate, source = max(
            pool, key=lambda item: (item[1] - highest) / 250.0
            + min(distance(item[0], old) for old, _ in selected) / 70.0,
        )
        selected.append((order, source))
        chosen.add(order)
    return selected


def add_archive(archive: list[Member], member: Member,
                *, capacity: int = 40, radius: int = 12) -> bool:
    """Retain strong orders with enough rank diversity for recombination."""
    if not math.isfinite(member.score):
        return False
    for j, old in enumerate(archive):
        if old.order == member.order:
            if member.score > old.score + 1e-8:
                archive[j] = member
                archive.sort(key=lambda x: x.score, reverse=True)
                return True
            return False
        if distance(old.order, member.order) < radius:
            if member.score > old.score + 1e-8:
                archive[j] = member
                archive.sort(key=lambda x: x.score, reverse=True)
                return True
            return False
    if len(archive) < capacity or member.score > archive[-1].score + 1e-8:
        archive.append(member)
        archive.sort(key=lambda x: x.score, reverse=True)
        del archive[capacity:]
        return True
    return False


KINDS = (
    "near_swap", "relocate", "window_shuffle", "two_windows",
    "block_move", "donor_segment", "donor_scatter", "global_cycle",
)


def mutate(order: tuple[int, ...], donor: tuple[int, ...],
           rng: random.Random, kind: str) -> tuple[int, ...]:
    result = list(order)
    n = len(result)
    if kind == "near_swap":
        i = rng.randrange(n)
        j = max(0, min(n - 1, i + rng.choice((-4, -3, -2, -1, 1, 2, 3, 4))))
        result[i], result[j] = result[j], result[i]
    elif kind == "relocate":
        i = rng.randrange(n)
        width = rng.choice((3, 6, 12, 24, 48))
        j = max(0, min(n - 1, i + rng.randint(-width, width)))
        result.insert(j, result.pop(i))
    elif kind == "window_shuffle":
        width = rng.randint(3, 14)
        i = rng.randrange(n - width + 1)
        chunk = result[i:i + width]
        rng.shuffle(chunk)
        result[i:i + width] = chunk
    elif kind == "two_windows":
        width = rng.randint(2, 7)
        a = rng.randrange(n - width + 1)
        b = rng.randrange(n - width + 1)
        if abs(a - b) < width:
            b = (a + width + rng.randrange(n - width)) % (n - width + 1)
        positions = sorted(set(range(a, a + width)) | set(range(b, b + width)))
        values = [result[k] for k in positions]
        rng.shuffle(values)
        for k, tile in zip(positions, values):
            result[k] = tile
    elif kind == "block_move":
        width = rng.randint(2, 9)
        i = rng.randrange(n - width + 1)
        chunk = result[i:i + width]
        del result[i:i + width]
        j = rng.randrange(len(result) + 1)
        result[j:j] = chunk
    elif kind == "donor_segment":
        # Order crossover transfers a whole donor segment, while the remainder
        # retains the parent's relative order.  This can jump between basins.
        width = rng.randint(4, 22)
        i = rng.randrange(n - width + 1)
        chunk = donor[i:i + width]
        rest = [tile for tile in result if tile not in chunk]
        result = rest[:i] + list(chunk) + rest[i:]
    elif kind == "donor_scatter":
        width = rng.randint(6, 22)
        positions = sorted(rng.sample(range(n), width))
        selected = {result[k] for k in positions}
        values = [tile for tile in donor if tile in selected]
        for k, tile in zip(positions, values):
            result[k] = tile
    elif kind == "global_cycle":
        width = rng.randint(3, 12)
        positions = sorted(rng.sample(range(n), width))
        values = [result[k] for k in positions]
        shift = rng.randrange(1, width)
        values = values[shift:] + values[:shift]
        for k, tile in zip(positions, values):
            result[k] = tile
    else:
        raise ValueError(kind)
    candidate = tuple(result)
    if len(candidate) != 64 or len(set(candidate)) != 64:
        raise AssertionError("mutation is not a permutation")
    return candidate


def export_seed(model: PracticeModel, oracle: Oracle, member: Member,
                destination: Path, incumbent_order: tuple[int, ...],
                incumbent_path: Path) -> dict:
    if member.order == incumbent_order:
        shutil.copyfile(incumbent_path, destination)
        report = model.authoritative_score(destination)
        checked = float(report["score"]["total"])
    else:
        checked = float(oracle.write_and_verify(list(member.order), destination)["score"]["total"])
    if abs(checked - member.score) > 1e-5:
        raise AssertionError("seed official replay differs from fixed-order oracle")
    return {"path": str(destination), "source": member.source,
            "score": checked, "footrule_from_incumbent": distance(incumbent_order, member.order),
            "first_order": [model.tile_ids[i] for i in member.order]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=9 * 3600)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--population", type=int, default=20)
    parser.add_argument("--export-seeds", type=int, default=4)
    parser.add_argument("--max-iterations", type=int, default=0,
                        help="0 means run to time limit")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"refusing to overwrite {args.out}")
    if args.seconds <= 0 or args.population < 2 or args.export_seeds < 1:
        raise SystemExit("invalid time, population, or seed count")
    args.out.mkdir(parents=True)
    started = time.monotonic()
    deadline = started + args.seconds
    rng = random.Random(args.seed)
    model = PracticeModel(SCENARIO, REFERENCE)
    oracle = Oracle(model)
    initial_order, initial_score = completion_order(model, INCUMBENT)
    recovered = oracle.value(list(initial_order))
    if abs(recovered - initial_score) > 1e-5:
        raise AssertionError("first-completion order failed to reconstruct incumbent")
    proposed = proposed_orders(model, initial_order, limit=max(args.population * 3, 50))
    members = []
    cache = {}
    for order, source in proposed:
        if time.monotonic() >= deadline and not args.prepare_only:
            break
        score = recovered if order == initial_order else oracle.value(list(order))
        cache[order] = score
        if math.isfinite(score):
            members.append(Member(order, score, source))
    members.sort(key=lambda x: x.score, reverse=True)
    archive: list[Member] = []
    for member in members:
        add_archive(archive, member)
    if not archive or archive[0].score + 1e-5 < initial_score:
        raise AssertionError("population lost the verified incumbent")
    seed_dir = args.out / "seeds"
    seed_dir.mkdir()
    exported = []
    for j, member in enumerate(archive[:args.export_seeds]):
        exported.append(export_seed(model, oracle, member, seed_dir / f"seed_{j:02d}.csv",
                                    initial_order, INCUMBENT))
    (args.out / "seeds.json").write_text(json.dumps(exported, indent=2) + "\n")
    shutil.copyfile(INCUMBENT, args.out / "best.csv")
    best = initial_score
    best_order = initial_order
    for member in archive:
        if member.score > best + 1e-6:
            result = oracle.write_and_verify(list(member.order), args.out / "candidate.csv")
            verified = float(result["score"]["total"])
            if abs(verified - member.score) > 1e-5:
                raise AssertionError("initial order oracle/scorer mismatch")
            os.replace(args.out / "candidate.csv", args.out / "best.csv")
            best, best_order = verified, member.order
    header = {"phase": "prepared", "score": best, "source_score": initial_score,
              "population": len(members), "archive": len(archive),
              "elapsed_seconds": time.monotonic() - started}
    print(json.dumps(header, sort_keys=True), flush=True)
    if args.prepare_only:
        return

    temperatures = (2.0, 8.0, 25.0, 70.0, 180.0, 400.0, 800.0, 1400.0)
    chains = []
    for j, temp in enumerate(temperatures):
        member = archive[min(j, len(archive) - 1)]
        chains.append(Chain(member.order, member.score, temp))
    counts = Counter()
    accepted = Counter()
    iteration = 0
    log_path = args.out / "trace.jsonl"
    with log_path.open("w", encoding="utf-8") as log:
        log.write(json.dumps(header) + "\n")
        while time.monotonic() < deadline:
            if args.max_iterations and iteration >= args.max_iterations:
                break
            iteration += 1
            j = iteration % len(chains)
            chain = chains[j]
            kind = KINDS[(iteration // len(chains) + j) % len(KINDS)]
            mate = rng.choice(archive[:min(20, len(archive))]).order
            candidate = mutate(chain.order, mate, rng, kind)
            if candidate == chain.order:
                continue
            if candidate in cache:
                value = cache[candidate]
                reused = True
            else:
                value = oracle.value(list(candidate))
                cache[candidate] = value
                reused = False
            counts[kind] += 1
            if math.isfinite(value):
                probability = min(1.0, math.exp(max(-700.0,
                    (value - chain.score) / chain.temperature)))
                if rng.random() < probability:
                    chain.order, chain.score = candidate, value
                    accepted[kind] += 1
                if value >= best - 450:
                    add_archive(archive, Member(candidate, value, kind))
                if value > best + 1e-6:
                    result = oracle.write_and_verify(list(candidate), args.out / "candidate.csv")
                    verified = float(result["score"]["total"])
                    if abs(verified - value) > 1e-5:
                        raise AssertionError("improvement oracle/scorer mismatch")
                    os.replace(args.out / "candidate.csv", args.out / "best.csv")
                    best, best_order = verified, candidate
                    (args.out / "best.json").write_text(json.dumps({
                        "score": best, "iteration": iteration, "kind": kind,
                        "first_order": [model.tile_ids[i] for i in best_order],
                        "official": result,
                    }, indent=2, sort_keys=True) + "\n")
                    print(json.dumps({"phase": "improved", "score": best,
                                      "iteration": iteration, "kind": kind,
                                      "elapsed_seconds": time.monotonic() - started}), flush=True)
            log.write(json.dumps({
                "iteration": iteration, "chain": j, "kind": kind,
                "score": value if math.isfinite(value) else None,
                "best": best, "accepted": chain.order == candidate,
                "reused": reused,
                "footrule_from_incumbent": distance(initial_order, candidate),
                "order": list(candidate),
            }, separators=(",", ":")) + "\n")
            if iteration % 64 == 0:
                # Swap adjacent temperature chains, letting strong solutions
                # travel between small and large perturbation regimes.
                for k in range(len(chains) - 1):
                    left, right = chains[k], chains[k + 1]
                    exponent = (1 / left.temperature - 1 / right.temperature) * (
                        right.score - left.score)
                    if rng.random() < min(1.0, math.exp(max(-700.0, exponent))):
                        left.order, right.order = right.order, left.order
                        left.score, right.score = right.score, left.score
            if iteration % 1024 == 0:
                log.flush()
                print(json.dumps({"phase": "progress", "iteration": iteration,
                                  "best": best, "archive": len(archive),
                                  "elapsed_seconds": time.monotonic() - started,
                                  "finite_fraction": sum(accepted.values()) / max(1, sum(counts.values()))}),
                      flush=True)
            if iteration % 4096 == 0 and len(cache) > 150000:
                cache = {member.order: member.score for member in archive}
                cache[initial_order] = recovered
    log_score = float(model.authoritative_score(args.out / "best.csv")["score"]["total"])
    if abs(log_score - best) > 1e-5:
        raise AssertionError("final best CSV/scorer mismatch")
    summary = {"best": best, "initial": initial_score, "iterations": iteration,
               "elapsed_seconds": time.monotonic() - started,
               "operators": dict(counts), "accepted": dict(accepted),
               "archive_size": len(archive), "best_path": str(args.out / "best.csv"),
               "best_first_order": [model.tile_ids[i] for i in best_order],
               "seed_paths": [item["path"] for item in exported]}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2,
                                                        sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
