#!/usr/bin/env python3
"""Replay and collect the best saved path from a Rhodes1 event-LNS run."""

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


def verified_score(path: Path) -> dict:
    decisions = load_decisions(path, allow_reports=False)
    if any(decision.reason for decision in decisions):
        raise ValueError(f"nonblank reason in {path}")
    scorer = ChallengeScorer.from_files(SCENARIO)
    for decision in decisions:
        scorer.apply_decision(decision)
    report = scorer.finalize("trace_complete")
    if len(report["completion"]["completed_tiles"]) != 64:
        raise ValueError(f"incomplete tile set in {path}")
    if report["score"]["request_reward"] != 3920.0:
        raise ValueError(f"missing request reward in {path}")
    if any(action["penalty"] != 0.0 for action in report["actions"]):
        raise ValueError(f"action penalty in {path}")
    return {
        "score": report["score"]["total"],
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "decisions": len(decisions),
        "completed_tiles": len(report["completion"]["completed_tiles"]),
        "request_reward": report["score"]["request_reward"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    seed = run_dir / "seed.csv"
    candidates = [{"worker": "seed", "path": str(seed), **verified_score(seed)}]
    workers = []
    for worker_dir in sorted(run_dir.iterdir()):
        if not worker_dir.is_dir():
            continue
        # A timeout during a copy can damage best.csv or the newest snapshot.
        paths = []
        for phase_dir in (worker_dir / "phase2", worker_dir / "phase1"):
            paths.append(phase_dir / "best.csv")
            paths.extend(sorted(phase_dir.glob("incumbent_*.csv"), reverse=True))
        workers.append((worker_dir.name, paths))

    errors = []
    for name, paths in workers:
        for path in paths:
            if not path.is_file():
                continue
            try:
                details = verified_score(path)
            except (ValueError, KeyError, AssertionError, OSError) as exc:
                errors.append({"path": str(path), "error": str(exc)})
                continue
            candidates.append({"worker": name, "path": str(path), **details})
            break

    candidates.sort(key=lambda item: item["score"], reverse=True)
    winner = candidates[0]
    destination = run_dir / "best.csv"
    temporary = run_dir / "best.csv.tmp"
    shutil.copyfile(winner["path"], temporary)
    os.replace(temporary, destination)
    summary = {
        "winner": winner,
        "ranked_candidates": candidates,
        "invalid_checkpoints": errors,
        "collected_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }
    temporary_summary = run_dir / "summary.json.tmp"
    temporary_summary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary_summary, run_dir / "summary.json")
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
