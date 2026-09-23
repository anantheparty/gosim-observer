#!/usr/bin/env python3
"""Officially replay and version a strictly better public-practice path.

This tool only reads local dev-reference truth and writes the local best CSV and
manifest. It never contacts the competition platform.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from challenge.scoring_core import ChallengeScorer, load_decisions


ROOT = Path(__file__).resolve().parent
SCENARIO = ROOT / "scenarios" / "dev-reference"
BEST = ROOT / "results" / "practice_best.csv"
MANIFEST = ROOT / "results" / "practice_manifest.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--method", required=True)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    decisions = load_decisions(candidate, allow_reports=False)
    if any(decision.reason for decision in decisions):
        raise ValueError("all reason fields must be blank")
    scorer = ChallengeScorer.from_files(SCENARIO)
    for decision in decisions:
        scorer.apply_decision(decision)
    report = scorer.finalize("trace_complete")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    old = float(manifest["best_offline"]["score"]["total"])
    score = report["score"]
    new = float(score["total"])
    if new <= old:
        print(json.dumps({"promoted": False, "old": old, "candidate": new,
                          "source": str(candidate)}, sort_keys=True))
        return
    if any(action.get("penalty", 0.0) for action in report["actions"]):
        raise ValueError("candidate has a penalized action; inspect the trace")
    shutil.copyfile(candidate, BEST)
    actions = [a for a in report["actions"] if a["action"] == "observe"]
    manifest["best_offline"] = {
        "path": str(BEST.relative_to(ROOT)),
        "sha256": hashlib.sha256(BEST.read_bytes()).hexdigest(),
        "method": args.method,
        "score": {
            "base_science": score["base_science"],
            "program_bonus": score["program_bonus"],
            "science": round(score["base_science"] + score["program_bonus"], 6),
            "request_reward": score["request_reward"],
            "penalties": score["penalties"],
            "total": new,
        },
        "observations": len(actions),
        "completed_observations": sum(a["outcome"] == "completed" for a in actions),
        "weather_interrupted_observations": sum(
            a["outcome"] == "weather_interrupted" for a in actions
        ),
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "promoted": True, "old": old, "score": new,
        "gain": round(new - old, 6),
        "completed_tiles": len(report["completion"]["completed_tiles"]),
        "reason_blank": True,
        "sha256": manifest["best_offline"]["sha256"],
        "source": str(candidate),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
