#!/usr/bin/env python3
"""Independently replay and collect the best completed broad-search checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

from challenge.scoring_core import ChallengeScorer, load_decisions


ROOT = Path(__file__).resolve().parent
SCENARIO = ROOT / "scenarios" / "dev-reference"
WORKERS = ("conflict", "diverse", "window", "conflict_alt", "window_alt")


def verify(path: Path) -> dict:
    decisions = load_decisions(path, allow_reports=False)
    if any(decision.reason for decision in decisions):
        raise ValueError("nonempty reason field")
    scorer = ChallengeScorer.from_files(SCENARIO)
    for decision in decisions:
        scorer.apply_decision(decision)
    report = scorer.finalize("trace_complete")
    if len(report["completion"]["completed_tiles"]) != 64:
        raise ValueError("fewer than 64 completed tiles")
    if any(float(action.get("penalty", 0)) for action in report["actions"]):
        raise ValueError("invalid or penalized action")
    return {
        "score": report["score"],
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "decisions": len(decisions),
        "completed_tiles": len(report["completion"]["completed_tiles"]),
        "requests": {row["request_id"]: row["status"] for row in report["requests"]},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    outputs_dir = run_dir / "outputs"
    sources = [("seed", run_dir / "seed.csv")]
    sources.extend((name, outputs_dir / name / "best.csv") for name in WORKERS)
    errors = []
    drop_summary = outputs_dir / "drop_one" / "summary.json"
    if drop_summary.is_file():
        try:
            drop_path = Path(json.loads(drop_summary.read_text(encoding="utf-8"))["best"]["decision_file"])
            if not drop_path.is_absolute():
                drop_path = drop_summary.parent / drop_path
            sources.append(("drop_one", drop_path))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append({"worker": "drop_one", "path": str(drop_summary), "error": str(exc)})
    candidates = []
    for name, path in sources:
        if not path.is_file():
            errors.append({"worker": name, "path": str(path), "error": "missing checkpoint"})
            continue
        try:
            candidates.append({"worker": name, "path": str(path), **verify(path)})
        except (OSError, ValueError, AssertionError, KeyError) as exc:
            errors.append({"worker": name, "path": str(path), "error": str(exc)})
    if not candidates or candidates[0]["worker"] != "seed":
        raise RuntimeError("valid seed checkpoint required")
    candidates.sort(key=lambda row: row["score"]["total"], reverse=True)
    winner = candidates[0]
    destination = run_dir / "best.csv"
    temp = run_dir / "best.csv.tmp"
    shutil.copyfile(winner["path"], temp)
    os.replace(temp, destination)
    summary = {
        "winner": winner,
        "ranked_candidates": candidates,
        "invalid_checkpoints": errors,
        "collected_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }
    temp_summary = run_dir / "summary.json.tmp"
    temp_summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_summary, run_dir / "summary.json")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
