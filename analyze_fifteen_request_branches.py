#!/usr/bin/env python3
"""Enumerate exactly-15 request branches using the certified eight-key root bound.

This is a cheap diagnostic: the eight-key time DP is already summarized by
the published exhaustive subset certificate, so no projected DP is rerun.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bounds_completion_cut_pilot as cut
import bounds_cut_subsets_benchmark as subsets
import bounds_practice_projection as projection
from bounds_request_conditioned import PRACTICE, ROOT


DEFAULT_OUT = ROOT / "results" / "practice_fifteen_request_branch_analysis.json"
THRESHOLDS_CENTS = (2140000, 2135000)


def _evaluate_count(setup: dict, free: dict, constrained: dict, base: int,
                    n: int, count: int) -> list[dict]:
    request_ids = setup["request_ids"]
    ambiguous = setup["ambiguous_index"]
    rows = []
    for mask in range(1 << len(request_ids)):
        if mask.bit_count() != count:
            continue
        selected = [j for j in range(len(request_ids)) if mask & (1 << j)]
        missed = tuple(request_ids[j] for j in range(len(request_ids))
                       if not mask & (1 << j))
        latest = setup["latest_release_by_mask"][mask]
        unavoidable_miss = sum(
            int(setup["miss"][j]) for j in range(len(request_ids))
            if not mask & (1 << j) and not setup["excuse"][j]
            and setup["deadline_epoch"][j] <= latest
        )
        for branch in ((0, 1) if mask & (1 << ambiguous) else (0,)):
            deadlines = {}
            for j in selected:
                option = setup["request_options"][j][branch if j == ambiguous else 0]
                for tile_id, deadline_unit in option:
                    deadlines[tile_id] = min(
                        deadline_unit, deadlines.get(tile_id, n + 1)
                    )
            regret = 0
            feasible = True
            for tile_id, deadline_unit in deadlines.items():
                restricted = constrained[(tile_id, deadline_unit)]
                if restricted is None:
                    feasible = False
                    break
                regret += free[tile_id] - restricted
            rows.append({
                "request_mask": mask,
                "unawarded_request_ids": list(missed),
                "rq0004_branch": branch,
                "feasible_relaxation": feasible,
                "request_reward_cents": int(setup["rewards_by_mask"][mask]),
                "unavoidable_miss_cents": unavoidable_miss,
                "deadline_regret_cents": regret if feasible else None,
                "upper_cents": (
                    base + int(setup["rewards_by_mask"][mask])
                    - regret - unavoidable_miss if feasible else None
                ),
            })
    return rows


def analyze(out_path: Path) -> dict:
    started = time.monotonic()
    old = json.loads(cut.UNCONDITIONAL_CERT.read_text())
    price_sha = hashlib.sha256(cut.PRICE_PATH.read_bytes()).hexdigest()
    if (old["capacity_price_sha256"] != price_sha
            or tuple(old["request_ids_in_mask_order"]) != tuple(
                f"RQ{i:04d}" for i in range(1, 19) if i != 15
            )
            or old["theta_uniform_cents"] != cut.THETA_CENTS):
        raise AssertionError("certified eight-key root inputs changed")
    data = projection.build_data(PRACTICE, cut.PRICE_PATH, audit=False)
    if (data["complete_arc_count"] != old["candidate_count"]
            or data["partial_arc_count"] != old["weather_interruption_arc_count"]):
        raise AssertionError("scorer arc graph changed")
    instants = cut._instants(data)
    arc_starts = np.repeat(
        np.arange(data["n"], dtype=np.int32), np.diff(data["complete_ptr"])
    )
    setup = subsets._request_setup(data, instants, arc_starts)
    if setup["request_ids"] != old["request_ids_in_mask_order"]:
        raise AssertionError("request bit ordering changed")
    free, constrained = subsets._envelopes(setup, None, 0, "root")
    base = int(old["resource_and_wait_base_cents_without_request_rewards"])
    rows16 = _evaluate_count(setup, free, constrained, base, data["n"], 16)
    old16 = {(row["missed_request"], row["rq0004_branch"]): row
             for row in old["exactly_sixteen_awarded_cases"]}
    if len(rows16) != 33 or len(old16) != 33:
        raise AssertionError("exactly-16 cross-check branch count changed")
    for row in rows16:
        if not row["feasible_relaxation"]:
            raise AssertionError("old exactly-16 branch became infeasible")
        key = (row["unawarded_request_ids"][0], row["rq0004_branch"])
        old_row = old16[key]
        if (row["upper_cents"] != old_row["adjusted_upper_cents"]
                or row["unavoidable_miss_cents"] != old_row["unavoidable_miss_cents"]):
            raise AssertionError("33 known branch bounds were not reproduced")

    rows15 = _evaluate_count(setup, free, constrained, base, data["n"], 15)
    if len(rows15) != 256 or any(not row["feasible_relaxation"] for row in rows15):
        raise AssertionError("exactly-15 branches were not covered")
    rows15.sort(key=lambda row: (-row["upper_cents"],
                                 row["unawarded_request_ids"],
                                 row["rq0004_branch"]))
    published_best = next(row for row in old["best_by_awarded_count"]
                          if row["awarded_count"] == 15)
    if (rows15[0]["upper_cents"] != published_best["upper_cents"]
            or rows15[0]["request_mask"] != published_best["mask"]
            or rows15[0]["rq0004_branch"] != published_best["rq0004_branch"]):
        raise AssertionError("published exactly-15 maximum was not reproduced")
    thresholds = [{
        "threshold_cents": threshold,
        "strictly_above_count": sum(row["upper_cents"] > threshold for row in rows15),
        "at_or_above_count": sum(row["upper_cents"] >= threshold for row in rows15),
    } for threshold in THRESHOLDS_CENTS]
    payload = {
        "scope": "dev-reference exactly-15 awarded request branch diagnostic",
        "old_exhaustive_subset_certificate_sha256": hashlib.sha256(
            cut.UNCONDITIONAL_CERT.read_bytes()).hexdigest(),
        "capacity_price_sha256": price_sha,
        "keys": list(cut.KEYS),
        "theta_uniform_cents": cut.THETA_CENTS,
        "all_exactly_sixteen_cross_checked": len(rows16),
        "exactly_fifteen_branch_count": len(rows15),
        "exactly_fifteen_upper_cents": rows15[0]["upper_cents"],
        "threshold_counts": thresholds,
        "rows": rows15,
        "runtime_seconds": time.monotonic() - started,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Analysis only. Reproduces the known exactly-16 branch table and exactly-15 maximum; no stronger upper bound is claimed.",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = analyze(args.out)
    print(json.dumps({
        "branch_count": result["exactly_fifteen_branch_count"],
        "best_cents": result["exactly_fifteen_upper_cents"],
        "threshold_counts": result["threshold_counts"],
        "runtime_seconds": result["runtime_seconds"],
        "top_ten": [{
            "unawarded_request_ids": row["unawarded_request_ids"],
            "rq0004_branch": row["rq0004_branch"],
            "upper_cents": row["upper_cents"],
        } for row in result["rows"][:10]],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
