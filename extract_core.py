#!/usr/bin/env python3
"""Extract first-completion and request-certificate events from a legal trace.

The original chronological event order is preserved.  For each completed
request, keep a sufficient collection of witnessed tile visits that
satisfies its whole-request threshold.  Other tagged revisits were useful only
as optional time-path edges and can be reconsidered by sequence_path_dp.py.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from challenge.contracts import DECISION_COLUMNS
from challenge.scoring_core import ChallengeScorer, load_decisions


def extract(scenario: Path, source: Path, destination: Path) -> dict:
    scorer = ChallengeScorer.from_files(scenario)
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    decisions = load_decisions(source, allow_reports=False)
    if len(decisions) != len(rows):
        raise ValueError("decision parser and CSV row count disagree")
    # This extractor is for complete-success traces.  A legal start can still
    # be weather-interrupted, in which case first row != first completion and
    # CSV tag counts != scorer visit counts.  Reject that broader input.
    for decision in decisions:
        action = scorer.apply_decision(decision)
        if action["action"] != "observe" or action["outcome"] != "completed":
            raise ValueError(f"{decision.decision_id} is not a completed observation")
    report = scorer.finalize("trace_complete")
    completed_requests = {
        row["request_id"] for row in report["requests"]
        if row["status"] == "completed"
    }
    first: dict[str, int] = {}
    tagged: dict[tuple[str, str], list[int]] = {}
    for index, row in enumerate(rows):
        if row["action"] != "observe":
            raise ValueError("source may contain only observations")
        first.setdefault(row["tile_id"], index)
        if row["request_id"]:
            tagged.setdefault((row["request_id"], row["tile_id"]), []).append(index)
    if len(first) != len(scorer.tiles):
        raise ValueError("source does not complete every practice tile")
    required = set(first.values())
    witnesses = set()
    fulfilled = []
    for request_id, request in scorer.requests.items():
        if request_id not in completed_requests:
            continue
        candidates = []
        for tile_id, visits in scorer.request_tiles[request_id].items():
            occurrences = tagged.get((request_id, tile_id), [])
            if len(occurrences) >= visits:
                selected = occurrences[:visits]
                candidates.append((selected[-1], selected, tile_id))
        if len(candidates) < request.required_tile_count:
            continue
        chosen = sorted(candidates)[:request.required_tile_count]
        for _, indices, _ in chosen:
            witnesses.update(indices)
        fulfilled.append(request_id)
    if set(fulfilled) != completed_requests:
        raise AssertionError("could not extract witnesses for all completed requests")
    required.update(witnesses)
    core = []
    for index in sorted(required):
        row = dict(rows[index])
        if index not in witnesses:
            row["request_id"] = ""
        row["reason"] = ""
        row["decision_id"] = f"D{len(core)+1:06d}"
        core.append(row)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(core)
    return {
        "source_events": len(rows),
        "first_completions": len(first),
        "request_witnesses": len(witnesses),
        "core_events": len(core),
        "fulfilled_requests": fulfilled,
        "output": str(destination),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/dev-reference"))
    parser.add_argument("--input", type=Path, default=Path("results/practice_best.csv"))
    parser.add_argument("--out", type=Path, default=Path("runs/practice_core/decisions.csv"))
    args = parser.parse_args()
    print(json.dumps(extract(args.scenario, args.input, args.out), sort_keys=True))


if __name__ == "__main__":
    main()
