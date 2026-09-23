#!/usr/bin/env python3
"""Scan all public-practice night cutoffs with an exact max-closure surrogate.

For a fixed incumbent wait timeline and cutoff t, each tile may move its first
completion to its best individually legal start before t. A paid wait after t
is removed in the surrogate iff every tile in its unfinished actionable mask
is moved. The group-choice optimization is an exact maximum-weight closure,
solved by s-t min-cut. Telescope capacity, action displacement, and changed
wait timelines are ignored; these values are search guidance, not global bounds.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from advance_wait_closure import max_closure, timeline
from practice_lns import PracticeModel
from sequence_dp import score_table


ROOT = Path(__file__).resolve().parent


def night_cutoffs(model: PracticeModel) -> list[tuple[str, int]]:
    result = []
    previous = model.slots[0]["night_id"]
    for slot_index, slot in enumerate(model.slots):
        if slot["night_id"] != previous:
            result.append((previous, slot_index * 6))
            previous = slot["night_id"]
    result.append((previous, model.n_units))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incumbent", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    model = PracticeModel(
        ROOT / "scenarios" / "dev-reference",
        ROOT / "results" / "practice_reference.csv",
    )
    first_finish, first_science, waits, report = timeline(model, args.incumbent)
    scores, _ = score_table(model)
    prefix_best = np.maximum.accumulate(scores, axis=1)
    records = []
    for night, cutoff in night_cutoffs(model):
        options = {}
        for i in range(len(model.tiles)):
            end_limit = cutoff - int(model.exposure_units[i])
            if first_finish[i] <= cutoff or end_limit < 0:
                continue
            best = float(prefix_best[i, min(end_limit, model.n_units - 1)])
            if np.isfinite(best):
                options[i] = float(first_science[i] - best)
        eligible_mask = sum(1 << i for i in options)
        rewards: defaultdict[int, float] = defaultdict(float)
        for u, mask, cost in waits:
            if u >= cutoff and mask & ~eligible_mask == 0:
                rewards[mask] += cost
        selected, value, saved, lost = max_closure(options, rewards)
        selected_nights = Counter()
        suggested_starts = []
        for i in sorted(selected):
            limit = cutoff - int(model.exposure_units[i])
            u = int(np.argmax(scores[i, :limit + 1]))
            chosen_night = model.slots[u // 6]["night_id"]
            selected_nights[chosen_night] += 1
            suggested_starts.append({
                "tile": model.tile_ids[i], "start_unit": u,
                "night": chosen_night,
                "science": float(scores[i, u]),
                "science_loss": options[i],
            })
        records.append({
            "cutoff_after_night": night, "cutoff_unit": cutoff,
            "eligible_tiles": len(options), "reward_masks": len(rewards),
            "selected_tiles": [model.tile_ids[i] for i in sorted(selected)],
            "selected_count": len(selected), "surrogate_net": value,
            "surrogate_wait_saved": saved, "surrogate_science_lost": lost,
            "suggested_start_nights": dict(selected_nights),
            "suggested_starts": suggested_starts,
        })
    ranked = sorted(
        (r for r in records if r["selected_count"] >= 2),
        key=lambda r: r["surrogate_net"], reverse=True,
    )
    output = {
        "scope": "fixed-incumbent wait timeline, independent best legal early starts; capacity ignored",
        "incumbent": str(args.incumbent),
        "incumbent_score": report["score"]["total"],
        "night_cutoffs": len(records),
        "charged_wait_edges": len(waits),
        "best_nontrivial": ranked[0] if ranked else None,
        "top_nontrivial": ranked[:args.top],
        "all": records,
        "interpretation": "exact closure optimum for surrogate only, not full-problem bound",
    }
    args.out.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "night_cutoffs": len(records), "best_nontrivial": ranked[0] if ranked else None,
        "output": str(args.out),
    }, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
