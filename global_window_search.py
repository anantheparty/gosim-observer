#!/usr/bin/env python3
"""Long, scored search over deliberately varied open-night CP neighborhoods.

This is a feasible-solution search on the public dev-reference instance.  The
restricted-column CP is allowed to rearrange every seed action and all legal
completed observations on the selected nights.  Every retained candidate is
replayed by the authoritative scorer inside relink_restricted_cp.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from practice_lns import PracticeModel
from sequence_dp import score_table


ROOT = Path(__file__).resolve().parent
SCENARIO = ROOT / "scenarios" / "dev-reference"
REFERENCE = ROOT / "results" / "practice_reference.csv"
CRITICAL_NIGHTS = (
    "N20260909", "N20260914", "N20270122", "N20270225", "N20270226",
)


def plan_groups(model: PracticeModel, seed: Path) -> list[dict]:
    scores, _ = score_table(model)
    report = model.authoritative_score(seed)
    first = {}
    for action in report["actions"]:
        if action["action"] != "observe" or action["outcome"] != "completed":
            continue
        tile = action["tile_id"]
        if tile not in first:
            first[tile] = (
                action["slot_id"].split("-")[0],
                action["base_science_score"] + action["program_bonus_score"],
            )
    if len(first) != len(model.tiles):
        raise ValueError("seed does not first-complete every tile")
    night_names = sorted({slot["night_id"] for slot in model.slots})
    night_index = {name: idx for idx, name in enumerate(night_names)}
    by_unit = np.asarray(
        [night_index[model.slots[u // 6]["night_id"]] for u in range(model.n_units)],
        dtype=np.int16,
    )
    opportunities = []
    for i, tile in enumerate(model.tile_ids):
        origin, achieved = first[tile]
        valid = np.flatnonzero(np.isfinite(scores[i]))
        for idx in np.unique(by_unit[valid]):
            target = night_names[int(idx)]
            if target == origin:
                continue
            local = valid[by_unit[valid] == idx]
            gain = float(np.max(scores[i, local])) - achieved
            if gain > 0.5:
                opportunities.append((gain, origin, target, tile))
    opportunities.sort(reverse=True)
    groups: list[dict] = []
    seen = set()

    def add(label: str, nights: set[str], merit: float = 0.0) -> None:
        key = tuple(sorted(nights))
        if 2 <= len(key) <= 4 and all(n in night_index for n in key) and key not in seen:
            seen.add(key)
            groups.append({"name": label, "nights": list(key), "merit": round(merit, 4)})

    add("critical_three", {"N20260909", "N20270225", "N20270226"})
    add("early_late_four", {"N20260909", "N20260914", "N20270122", "N20270225"})
    add("early_end_four", {"N20260909", "N20260914", "N20270225", "N20270226"})
    add("mid_end_four", {"N20260909", "N20270122", "N20270225", "N20270226"})
    top_pairs = []
    for gain, origin, target, tile in opportunities[:180]:
        pair = {origin, target}
        add(f"science_{tile}", pair, gain)
        top_pairs.append((gain, pair, tile))
        for anchor in ("N20260909", "N20270225", "N20270226"):
            if anchor not in pair:
                add(f"science_{tile}_anchor_{anchor}", pair | {anchor}, gain)
    for j, (gain_a, pair_a, tile_a) in enumerate(top_pairs[:60]):
        for gain_b, pair_b, tile_b in top_pairs[j + 1 : j + 25]:
            if tile_a == tile_b:
                continue
            union = pair_a | pair_b
            if 3 <= len(union) <= 4:
                add(f"coupled_{tile_a}_{tile_b}", union, gain_a + gain_b)
    # Preserve curated cases first, then rank the global opportunity groups.
    return groups[:4] + sorted(groups[4:], key=lambda row: row["merit"], reverse=True)


def verify(path: Path, model: PracticeModel) -> tuple[float, str]:
    report = model.authoritative_score(path)
    if len(report["completion"]["completed_tiles"]) != len(model.tiles):
        raise ValueError("candidate is incomplete")
    if report["score"]["request_reward"] != 3920.0:
        raise ValueError("candidate lost a reward")
    if any(action["penalty"] for action in report["actions"]):
        raise ValueError("candidate has an action penalty")
    return float(report["score"]["total"]), hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=ROOT / "results/practice_best.csv")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--hours", type=float, default=9.0)
    parser.add_argument("--time-limit", type=int, default=240)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--max-trials", type=int, default=160)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if not 0 < args.hours <= 24 or args.time_limit < 30 or args.workers < 1:
        parser.error("invalid time or worker budget")
    model = PracticeModel(SCENARIO, REFERENCE)
    groups = plan_groups(model, args.seed)
    if args.plan_only:
        print(json.dumps({"groups": len(groups), "first": groups[:12]}, ensure_ascii=False))
        return
    args.out.mkdir(parents=True, exist_ok=False)
    best_path = args.out / "best.csv"
    shutil.copyfile(args.seed, best_path)
    best, original_sha = verify(best_path, model)
    start = time.monotonic()
    deadline = start + args.hours * 3600
    (args.out / "plan.json").write_text(
        json.dumps({"seed": str(args.seed), "seed_sha256": original_sha,
                    "hours": args.hours, "time_limit": args.time_limit,
                    "workers": args.workers, "groups": groups}, indent=2) + "\n",
        encoding="utf-8",
    )
    completed = 0
    with (args.out / "trace.jsonl").open("w", encoding="utf-8") as trace:
        for index, group in enumerate(groups[: args.max_trials], 1):
            remaining = deadline - time.monotonic()
            if remaining < 180:
                break
            limit = min(args.time_limit, max(30, int(remaining - 120)))
            candidate_dir = args.out / f"trial_{index:03d}"
            candidate_dir.mkdir()
            candidate = candidate_dir / "decisions.csv"
            command = [
                sys.executable, str(ROOT / "relink_restricted_cp.py"),
                "--seeds", str(best_path),
                "--shift-units", "1",
                "--wait-neighbor-shift-units", "1",
                "--wait-neighbor-limit", "256",
                "--global-first-tiles", "8",
                "--global-first-per-night", "1",
                "--open-nights", *group["nights"],
                "--time-limit", str(limit),
                "--workers", str(args.workers),
                "--seed", str(96000 + index),
                "--out", str(candidate),
            ]
            if index % 2 == 0:
                command.append("--all-weather-partials")
            t0 = time.monotonic()
            record = {"index": index, "group": group, "time_limit": limit,
                      "all_weather_partials": index % 2 == 0}
            try:
                result = subprocess.run(
                    command, cwd=ROOT, capture_output=True, text=True,
                    timeout=max(1, int(remaining - 30)), check=False,
                )
                (candidate_dir / "solver.log").write_text(
                    result.stdout + result.stderr, encoding="utf-8"
                )
                record["returncode"] = result.returncode
                if result.returncode == 0 and candidate.is_file():
                    record["score"], record["sha256"] = verify(candidate, model)
                    record["solver"] = json.loads(result.stdout.strip().splitlines()[-1])
                    if record["score"] > best + 1e-6:
                        best = record["score"]
                        shutil.copyfile(candidate, best_path)
                        record["accepted"] = True
                        print(json.dumps({"accepted": best, "group": group,
                                          "index": index}), flush=True)
            except (subprocess.TimeoutExpired, ValueError, IndexError, json.JSONDecodeError) as exc:
                record["error"] = str(exc)
            record["seconds"] = round(time.monotonic() - t0, 3)
            trace.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            trace.flush()
            completed += 1
            print(json.dumps({"index": index, "score": record.get("score"),
                              "best": best, "seconds": record["seconds"]}), flush=True)
            if not record.get("accepted"):
                # Detailed logs remain; unsuccessful multi-megabyte replay files
                # are reproducible and add no new schedule information.
                candidate.unlink(missing_ok=True)
                (candidate_dir / "score_report.json").unlink(missing_ok=True)
    summary = {"seed_sha256": original_sha, "best": best,
               "best_path": str(best_path), "trials": completed,
               "groups_available": len(groups), "elapsed_seconds": round(time.monotonic() - start, 3)}
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
