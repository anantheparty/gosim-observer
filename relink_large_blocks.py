#!/usr/bin/env python3
"""Systematic order-based crossover of 8--16 first-visit blocks.

For each donor interval, transfer its full order and absolute rank into the
recipient order while retaining recipient order for the remaining tiles.  The
active-request oracle exactly reschedules all starts, tags, revisits, waits,
and weather interruptions for each hybrid.  The best candidate is replayed
through the authoritative practice scorer.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import sequence_active_requests_dp as active
from multistart_large_neighborhood import Oracle, REFERENCE, SCENARIO, _movement
from practice_lns import PracticeModel


def crossover(recipient: list[int], donor: list[int], lo: int, length: int) -> list[int]:
    block = donor[lo:lo + length]
    blocked = set(block)
    result = [tile for tile in recipient if tile not in blocked]
    result[lo:lo] = block
    if len(result) != len(recipient) or len(set(result)) != len(recipient):
        raise AssertionError("crossover lost a tile")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipient", type=Path, required=True)
    parser.add_argument("--donor", type=Path, required=True)
    parser.add_argument("--lengths", type=int, nargs="+", default=[8, 12, 16])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    model = PracticeModel(SCENARIO, REFERENCE)
    oracle = Oracle(model)
    recipient = active._first_order(model, args.recipient)
    donor = active._first_order(model, args.donor)
    baseline = oracle.value(recipient)
    best = baseline
    best_order = recipient
    counts = {"tested": 0, "feasible": 0, "strict_improvements": 0}
    trace = args.out / "trace.jsonl"
    seen = set()
    with trace.open("w", encoding="utf-8") as log:
        for length in args.lengths:
            if not 1 <= length <= len(recipient):
                raise ValueError("invalid block length")
            for lo in range(len(recipient) - length + 1):
                candidate = crossover(recipient, donor, lo, length)
                key = tuple(candidate)
                if key in seen:
                    continue
                seen.add(key)
                t0 = time.monotonic()
                value = oracle.value(candidate)
                counts["tested"] += 1
                counts["feasible"] += math.isfinite(value)
                shift, total = _movement(recipient, candidate)
                record = {
                    "length": length, "donor_start": lo,
                    "max_rank_shift": shift, "total_rank_shift": total,
                    "score": value if math.isfinite(value) else None,
                    "first_infeasible_event": oracle.last_failure,
                    "seconds": time.monotonic() - t0,
                }
                if value > best + 1e-7:
                    verified = oracle.write_and_verify(candidate, args.out / "best.csv")
                    if abs(verified["score"]["total"] - value) > 1e-5:
                        raise AssertionError("oracle and scorer disagree")
                    best = value
                    best_order = candidate
                    counts["strict_improvements"] += 1
                    record["improved"] = True
                    record["verified"] = verified
                    print(json.dumps({"improved": best, "length": length,
                                      "lo": lo, "elapsed": time.monotonic() - start}),
                          flush=True)
                log.write(json.dumps(record, sort_keys=True) + "\n")
                log.flush()
    summary = {
        "recipient": str(args.recipient), "donor": str(args.donor),
        "baseline": baseline, "best": best, "counts": counts,
        "elapsed_seconds": time.monotonic() - start,
        "best_order": [model.tile_ids[i] for i in best_order],
    }
    (args.out / "summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
