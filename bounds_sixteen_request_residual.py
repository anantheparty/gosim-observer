#!/usr/bin/env python3
"""Close exactly-16 branches left above the strengthened <=15 ceiling."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import bounds_request_projection_k10 as projection13
import bounds_sixteen_request_k10 as sixteen10
import bounds_sixteen_request_k13_targeted as initial


ROOT = projection13.ROOT
PRIOR_SIXTEEN = ROOT / "results" / "practice_sixteen_request_k13_targeted.json"
PRIOR_FIFTEEN = ROOT / "results" / "practice_fifteen_request_k13_targeted.json"
DEFAULT_OUT = ROOT / "results" / "practice_sixteen_request_residual.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certify(prior_sixteen_path: Path, prior_fifteen_path: Path,
            prices_path: Path) -> dict:
    started = time.monotonic()
    prior16 = json.loads(prior_sixteen_path.read_text())
    prior15 = json.loads(prior_fifteen_path.read_text())
    data, audit = projection13._load_audited_data(prices_path)
    choices, instants, arc_starts, _, legacy_lookup = sixteen10._certified_inputs(data)
    request_ids = [request.request_id for request, _ in choices]
    if (prior16["capacity_price_sha256"] != audit["price_sha256"]
            or prior15["capacity_price_sha256"] != audit["price_sha256"]
            or prior16["keys"] != list(initial.KEYS)
            or prior16["theta_uniform_cents"] != initial.THETA_CENTS
            or prior15["keys"] != list(initial.KEYS)
            or prior15["theta_uniform_cents"] != initial.THETA_CENTS):
        raise AssertionError("prior capacity prices or key model differ")
    rows = prior16["branch_rows"]
    if (len(rows) != 33 or prior16["branch_count"] != 33
            or len({(r["missed_request"], r["rq0004_branch"]) for r in rows}) != 33):
        raise AssertionError("prior sixteen-request partition is incomplete")
    threshold = int(prior15["at_most_fifteen_upper_cents"])
    if threshold != 2133431:
        raise AssertionError("the strengthened <=15 ceiling changed")
    targeted = [row for row in rows if row["merged_upper_cents"] > threshold]
    if (len(targeted) != 2 or any(row["missed_request"] != "RQ0018"
                                  or row["thirteen_key_refinement"] is not None
                                  for row in targeted)):
        raise AssertionError("unresolved exactly-16 branch set changed")
    refinements = []
    merged_rows = []
    for old in rows:
        new_cents = None
        merged = int(old["merged_upper_cents"])
        if old in targeted:
            new = sixteen10._one_branch(
                data, choices, instants, arc_starts,
                request_ids.index(old["missed_request"]), old["rq0004_branch"],
                initial.KEYS, initial.THETA_CENTS, legacy_lookup,
            )
            if not new["feasible_relaxation"]:
                raise AssertionError("new projected branch unexpectedly infeasible")
            new_cents = int(new["upper_cents"])
            merged = min(merged, new_cents)
            refinements.append({
                "missed_request": old["missed_request"],
                "rq0004_branch": old["rq0004_branch"],
                "old_upper_cents": old["merged_upper_cents"],
                "thirteen_key_refinement": new,
                "merged_upper_cents": merged,
            })
            print(json.dumps({
                "missed_request": old["missed_request"],
                "rq0004_branch": old["rq0004_branch"],
                "old_upper_cents": old["merged_upper_cents"],
                "thirteen_key_upper_cents": new_cents,
                "elapsed_seconds": round(time.monotonic() - started, 1),
                "peak_rss_mib": projection13._rss_mib(),
            }), flush=True)
        merged_rows.append({
            "missed_request": old["missed_request"],
            "rq0004_branch": old["rq0004_branch"],
            "prior_upper_cents": old["merged_upper_cents"],
            "additional_thirteen_key_upper_cents": new_cents,
            "merged_upper_cents": merged,
        })
    exactly16 = max(row["merged_upper_cents"] for row in merged_rows)
    at_most16 = max(threshold, exactly16)
    if at_most16 > prior16["at_most_sixteen_upper_cents"]:
        raise AssertionError("new sixteen-request bound weakened")
    return {
        "scope": "dev-reference; all valid traces with at most 16 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "prior_sixteen_certificate_sha256": _sha(prior_sixteen_path),
        "prior_fifteen_certificate_sha256": _sha(prior_fifteen_path),
        "keys": list(initial.KEYS),
        "theta_uniform_cents": initial.THETA_CENTS,
        "branch_count": len(merged_rows),
        "additional_refined_branch_count": len(refinements),
        "additional_refinements": refinements,
        "merged_branch_rows": merged_rows,
        "at_most_fifteen_upper_cents": threshold,
        "exactly_sixteen_upper_cents": exactly16,
        "at_most_sixteen_upper_cents": at_most16,
        "branches_above_at_most_fifteen": [
            row for row in merged_rows if row["merged_upper_cents"] > threshold
        ],
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection13._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "The earlier 33-branch exactly-16 certificate is exhaustive. "
            "Only two RQ0018 branches exceed the newly strengthened <=15 "
            "ceiling; they are recomputed by the same audited 13-key time DP. "
            "Every branch takes the minimum of its prior bound and the "
            "additional bound when present."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-sixteen", type=Path, default=PRIOR_SIXTEEN)
    parser.add_argument("--prior-fifteen", type=Path, default=PRIOR_FIFTEEN)
    parser.add_argument("--prices", type=Path, default=projection13.PRICE_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.prior_sixteen, args.prior_fifteen, args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "at_most_fifteen_upper_cents": result["at_most_fifteen_upper_cents"],
        "exactly_sixteen_upper_cents": result["exactly_sixteen_upper_cents"],
        "at_most_sixteen_upper_cents": result["at_most_sixteen_upper_cents"],
        "branches_above_at_most_fifteen": result["branches_above_at_most_fifteen"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
