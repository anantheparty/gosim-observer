#!/usr/bin/env python3
"""Iterated exact event-level large-neighborhood search on public practice.

The inner oracle is event_subset_exact_dp.py.  This driver tests structured
6--8-tile groups: neighboring first visits, request-hyperedge unions, science
regret groups, and nonlocal closure/blocker groups.  It accepts only official
scorer-verified improvements, retaining every accepted incumbent.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import time
from pathlib import Path

import numpy as np

import sequence_active_requests_dp as active
from event_subset_exact_dp import _core_events, solve
from multistart_large_neighborhood import Oracle, REFERENCE, SCENARIO
from practice_lns import PracticeModel


def candidate_groups(model: PracticeModel, oracle: Oracle, incumbent: Path, seed: int):
    rng = random.Random(seed)
    events, report = _core_events(model, incumbent)
    first_order = [e["tile"] for e in events if e["first"]]
    if len(first_order) != 64:
        raise AssertionError("first order length")
    achieved = np.zeros(64, dtype=np.float64)
    seen = set()
    for a in report["actions"]:
        if a["action"] == "observe" and a["outcome"] == "completed":
            i = model.tile_index[a["tile_id"]]
            if i not in seen:
                seen.add(i)
                achieved[i] = a["base_science_score"] + a["program_bonus_score"]
    regret = np.nanmax(oracle.scores, axis=1) - achieved
    req_sets = [
        {model.tile_index[t] for t in model.scorer.request_tiles[rid]}
        for rid in sorted(model.scorer.requests) if rid != "RQ0015"
    ]
    group_specs = []
    for length in (6, 8):
        for start in range(0, 65 - length, 2):
            group_specs.append((f"rank_window_{length}_{start}", set(first_order[start:start + length])))
    for a in range(len(req_sets)):
        for b in range(a + 1, min(a + 4, len(req_sets))):
            group = req_sets[a] | req_sets[b]
            if len(group) > 8:
                continue
            # Fill to 6 with tiles near the group's median first-visit rank.
            ranks = [first_order.index(i) for i in group]
            pivot = int(np.median(ranks))
            nearby = sorted(
                (i for i in first_order if i not in group),
                key=lambda i: (abs(first_order.index(i) - pivot), -regret[i]),
            )
            group.update(nearby[:max(0, 6 - len(group))])
            group_specs.append((f"request_union_{a}_{b}", group))
    high_regret = list(np.argsort(-regret))[:24]
    for start in range(0, 19, 2):
        group_specs.append((f"regret_{start}", set(map(int, high_regret[start:start + 6]))))
    closure = [
        "T00002", "T00003", "T00005", "T00006", "T00013", "T00014",
        "T00027", "T00031", "T00032", "T00039", "T00042", "T00044",
        "T00047", "T00048", "T00056", "T00062",
    ]
    closure_ids = [model.tile_index[t] for t in closure]
    for j in range(32):
        group_specs.append((f"closure_sample_{j}", set(rng.sample(closure_ids, 6 if j % 2 else 8))))
    for j in range(40):
        group = set(rng.sample(first_order, 6 if j % 2 else 8))
        group_specs.append((f"nonlocal_{j}", group))
    unique = []
    seen_groups = set()
    for name, group in group_specs:
        key = tuple(sorted(group))
        if len(group) >= 4 and key not in seen_groups:
            seen_groups.add(key)
            unique.append((name, sorted(group)))
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incumbent", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=85001)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--max-groups", type=int, default=300)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    best_path = args.out / "best.csv"
    shutil.copyfile(args.incumbent, best_path)
    model = PracticeModel(SCENARIO, REFERENCE)
    oracle = Oracle(model)
    best = float(model.authoritative_score(best_path)["score"]["total"])
    begin = time.monotonic()
    trace = args.out / "trace.jsonl"
    with trace.open("w", encoding="utf-8") as log:
        count = 0
        for round_no in range(args.rounds):
            groups = candidate_groups(model, oracle, best_path, args.seed + round_no)
            for name, selected in groups:
                if count >= args.max_groups:
                    break
                count += 1
                temporary = args.out / "candidate.csv"
                t0 = time.monotonic()
                result = solve(model, oracle, best_path, selected, temporary)
                score = float(result.get("candidate_total", -np.inf))
                record = {
                    "index": count, "round": round_no, "group": name,
                    "tiles": [model.tile_ids[i] for i in selected],
                    "score": score if np.isfinite(score) else None,
                    "best_before": best,
                    "seconds": time.monotonic() - t0,
                    "status": result["status"],
                }
                if score > best + 1e-6:
                    best = score
                    shutil.copyfile(temporary, best_path)
                    record["accepted"] = True
                    record["score_breakdown"] = result["score"]
                    shutil.copyfile(temporary, args.out / f"incumbent_{count:04d}.csv")
                    print(json.dumps({"accepted": best, "group": name,
                                      "index": count, "round": round_no,
                                      "elapsed": time.monotonic() - begin}), flush=True)
                log.write(json.dumps(record, sort_keys=True) + "\n")
                log.flush()
            if count >= args.max_groups:
                break
    summary = {
        "initial": str(args.incumbent), "best": best,
        "evaluated_groups": count, "elapsed_seconds": time.monotonic() - begin,
        "best_path": str(best_path),
    }
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
