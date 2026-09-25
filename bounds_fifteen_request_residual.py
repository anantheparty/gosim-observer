#!/usr/bin/env python3
"""Close exact-15 request branches above the improved exact-16 ceiling."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import bounds_fifteen_request_k13_targeted as first
import bounds_request_projection_k10 as projection13
import bounds_sixteen_request_k10 as sixteen10


ROOT = projection13.ROOT
PRIOR_FIFTEEN = ROOT / "results" / "practice_fifteen_request_k13_targeted.json"
PRIOR_SIXTEEN = ROOT / "results" / "practice_sixteen_request_residual.json"
DIAGNOSTIC = ROOT / "results" / "practice_fifteen_request_branch_analysis.json"
DEFAULT_OUT = ROOT / "results" / "practice_fifteen_request_residual.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certify(prior_fifteen_path: Path, prior_sixteen_path: Path,
            diagnostic_path: Path, prices_path: Path) -> dict:
    started = time.monotonic()
    previous = json.loads(prior_fifteen_path.read_text())
    sixteen = json.loads(prior_sixteen_path.read_text())
    diagnostic = json.loads(diagnostic_path.read_text())
    data, audit = projection13._load_audited_data(prices_path)
    choices, instants, arc_starts, _, _ = sixteen10._certified_inputs(data)
    if (previous["capacity_price_sha256"] != audit["price_sha256"]
            or sixteen["capacity_price_sha256"] != audit["price_sha256"]
            or diagnostic["capacity_price_sha256"] != audit["price_sha256"]
            or previous["keys"] != list(first.KEYS)
            or previous["theta_uniform_cents"] != first.THETA_CENTS
            or sixteen["keys"] != list(first.KEYS)
            or sixteen["theta_uniform_cents"] != first.THETA_CENTS
            or previous["exactly_fifteen_diagnostic_sha256"] != _sha(diagnostic_path)):
        raise AssertionError("prior certificates differ from audited data")
    prior_rows = previous["merged_branch_rows"]
    diag_rows = {(row["request_mask"], row["rq0004_branch"]): row
                 for row in diagnostic["rows"]}
    if (len(prior_rows) != 256 or len(diag_rows) != 256
            or len({(row["request_mask"], row["rq0004_branch"])
                    for row in prior_rows}) != 256):
        raise AssertionError("exactly-15 branch partition incomplete")
    threshold = int(sixteen["exactly_sixteen_upper_cents"])
    if threshold != 2130466:
        raise AssertionError("exactly-16 target ceiling changed")
    targets = [row for row in prior_rows if row["merged_upper_cents"] > threshold]
    if len(targets) != 3:
        raise AssertionError("unresolved exactly-15 branch count changed")
    additional = []
    merged = []
    for row in prior_rows:
        key = (row["request_mask"], row["rq0004_branch"])
        diagnostic_row = diag_rows[key]
        if row["old_upper_cents"] != diagnostic_row["upper_cents"]:
            raise AssertionError("old branch identity or upper bound changed")
        adjusted = int(row["merged_upper_cents"])
        new = None
        if adjusted > threshold:
            missing = tuple(diagnostic_row["unawarded_request_ids"])
            new = first._branch_bound(
                data, choices, instants, arc_starts, missing,
                row["rq0004_branch"], first.KEYS, first.THETA_CENTS,
            )
            if (new["selected_request_reward_cents"] != diagnostic_row["request_reward_cents"]
                    or new["unavoidable_miss_cents"] != diagnostic_row["unavoidable_miss_cents"]):
                raise AssertionError("request reward or missing penalty differs")
            check = first._branch_bound(
                data, choices, instants, arc_starts, missing,
                row["rq0004_branch"], projection13.BASE_KEYS, 140,
            )
            if check["upper_cents"] != diagnostic_row["upper_cents"]:
                raise AssertionError("eight-key branch cross-check failed")
            adjusted = min(adjusted, int(new["upper_cents"]))
            additional.append({
                "unawarded_request_ids": list(missing),
                "request_mask": row["request_mask"],
                "rq0004_branch": row["rq0004_branch"],
                "prior_upper_cents": row["merged_upper_cents"],
                "eight_key_conditional_cross_check_cents": check["upper_cents"],
                "thirteen_key_refinement": new,
                "merged_upper_cents": adjusted,
            })
            print(json.dumps({
                "unawarded_request_ids": list(missing),
                "rq0004_branch": row["rq0004_branch"],
                "old_cents": row["merged_upper_cents"],
                "thirteen_key_cents": new["upper_cents"],
                "elapsed_seconds": round(time.monotonic() - started, 1),
                "peak_rss_mib": projection13._rss_mib(),
            }), flush=True)
        merged.append({
            "request_mask": row["request_mask"],
            "rq0004_branch": row["rq0004_branch"],
            "prior_upper_cents": row["merged_upper_cents"],
            "additional_thirteen_key_upper_cents": (
                new["upper_cents"] if new is not None else None
            ),
            "merged_upper_cents": adjusted,
        })
    exactly15 = max(row["merged_upper_cents"] for row in merged)
    at_most14 = int(previous["at_most_fourteen_upper_cents"])
    at_most15 = max(at_most14, exactly15)
    at_most16 = max(at_most15, threshold)
    if at_most15 > previous["at_most_fifteen_upper_cents"]:
        raise AssertionError("new fifteen-request bound weakened")
    best_keys = [(row["request_mask"], row["rq0004_branch"])
                 for row in merged if row["merged_upper_cents"] == exactly15]
    return {
        "scope": "dev-reference; all valid traces with at most 16 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "prior_fifteen_certificate_sha256": _sha(prior_fifteen_path),
        "prior_sixteen_certificate_sha256": _sha(prior_sixteen_path),
        "diagnostic_sha256": _sha(diagnostic_path),
        "keys": list(first.KEYS),
        "theta_uniform_cents": first.THETA_CENTS,
        "branch_count": len(merged),
        "additional_refined_branch_count": len(additional),
        "additional_refinements": additional,
        "merged_branch_rows": merged,
        "at_most_fourteen_upper_cents": at_most14,
        "exactly_fifteen_upper_cents": exactly15,
        "exactly_fifteen_maximizing_branch_keys": best_keys,
        "at_most_fifteen_upper_cents": at_most15,
        "exactly_sixteen_upper_cents": threshold,
        "at_most_sixteen_upper_cents": at_most16,
        "branches_above_exactly_sixteen": [
            row for row in merged if row["merged_upper_cents"] > threshold
        ],
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection13._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "The prior exhaustive exactly-15 table has 256 branches. Only "
            "the three bounds above the certified exactly-16 ceiling are "
            "recomputed with the audited 13-key conditional time DP; all "
            "other branches retain their previous valid upper bounds."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-fifteen", type=Path, default=PRIOR_FIFTEEN)
    parser.add_argument("--prior-sixteen", type=Path, default=PRIOR_SIXTEEN)
    parser.add_argument("--diagnostic", type=Path, default=DIAGNOSTIC)
    parser.add_argument("--prices", type=Path, default=projection13.PRICE_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.prior_fifteen, args.prior_sixteen,
                     args.diagnostic, args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "exactly_fifteen_upper_cents": result["exactly_fifteen_upper_cents"],
        "at_most_fifteen_upper_cents": result["at_most_fifteen_upper_cents"],
        "exactly_sixteen_upper_cents": result["exactly_sixteen_upper_cents"],
        "at_most_sixteen_upper_cents": result["at_most_sixteen_upper_cents"],
        "branches_above_exactly_sixteen": result["branches_above_exactly_sixteen"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
