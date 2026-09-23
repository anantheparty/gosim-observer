#!/usr/bin/env python3
"""Run a reproducible CPU grid over the public interval model's discretization."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from challenge.scoring_core import ChallengeScorer
from optimize_public import enumerate_options, solve, write_decisions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--per-weeks", nargs="+", type=int, default=[2, 4])
    parser.add_argument("--per-nights", nargs="+", type=int, default=[1])
    parser.add_argument("--time-limit", type=float, default=90)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    scorer = ChallengeScorer.from_files(args.scenario)
    options = enumerate_options(scorer)
    summary = []
    for per_week in args.per_weeks:
        for per_night in args.per_nights:
            plan, info = solve(scorer, options, per_week, per_night,
                               args.time_limit, args.workers)
            row = {"per_week": per_week, "per_night": per_night, **info}
            if plan is not None:
                directory = args.out / f"week{per_week}_night{per_night}"
                decisions = directory / "decisions.csv"
                report = directory / "score_report.json"
                write_decisions(decisions, plan)
                subprocess.run([sys.executable, str(Path(__file__).with_name("score_decisions.py")),
                                "--scenario", str(args.scenario), "--decisions", str(decisions),
                                "--out", str(report)], check=True, stdout=subprocess.DEVNULL)
                result = json.loads(report.read_text(encoding="utf-8"))
                row["verified_total"] = result["score"]["total"]
                row["penalties"] = result["score"]["penalties"]
                row["completed_tiles"] = len(result["completion"]["completed_tiles"])
            summary.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
