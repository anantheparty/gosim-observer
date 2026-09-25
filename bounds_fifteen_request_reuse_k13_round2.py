#!/usr/bin/env python3
"""Refine 14 exact-15 branches using an already certified K13 DP signature."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bounds_fifteen_request_grouped_k13 as grouped
import bounds_request_projection_k10 as projection
import bounds_sixteen_request_k10 as sixteen
import bounds_sixteen_request_reuse_k16 as reused


ROOT = projection.ROOT
PRIOR_FIFTEEN = ROOT / "results" / "practice_fifteen_request_two_k13.json"
SOURCE_K13 = ROOT / "results" / "practice_fifteen_request_grouped_k13.json"
DIAGNOSTIC = ROOT / "results" / "practice_fifteen_request_branch_analysis.json"
EXACT_SIXTEEN = ROOT / "results" / "practice_sixteen_request_reuse_k16_round2.json"
DEFAULT_OUT = ROOT / "results" / "practice_fifteen_request_reuse_k13_round2.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certify(prior15_path: Path, source_path: Path, diagnostic_path: Path,
            exact16_path: Path, prices_path: Path) -> dict:
    started = time.monotonic()
    old = json.loads(prior15_path.read_text())
    source = json.loads(source_path.read_text())
    diagnostic = json.loads(diagnostic_path.read_text())
    exact16 = json.loads(exact16_path.read_text())
    data, audit = projection._load_audited_data(prices_path)
    choices, instants, arc_starts, _, _ = sixteen._certified_inputs(data)
    if any(cert["capacity_price_sha256"] != audit["price_sha256"]
           for cert in (old, source, diagnostic, exact16)):
        raise AssertionError("source certificates have different audited prices")
    rows = old["merged_branch_rows"]
    original_by_key = {(r["request_mask"], r["rq0004_branch"]): r
                       for r in diagnostic["rows"]}
    row_by_key = {(r["request_mask"], r["rq0004_branch"]): r for r in rows}
    request_ids = [request.request_id for request, _ in choices]
    expected = {
        (pair, option)
        for pair in itertools.combinations(request_ids, 2)
        for option in ((0,) if "RQ0004" in pair else (0, 1))
    }
    actual = {(tuple(r["unawarded_request_ids"]), r["rq0004_branch"])
              for r in diagnostic["rows"]}
    if (len(rows) != 256 or len(row_by_key) != 256
            or len(original_by_key) != 256 or set(row_by_key) != set(original_by_key)
            or expected != actual
            or max(r["merged_upper_cents"] for r in rows)
                != old["exactly_fifteen_upper_cents"]):
        raise AssertionError("prior exact-15 branch coverage differs")

    keys = tuple(source["keys"])
    theta = int(source["theta_uniform_cents"])
    if keys != tuple(grouped.first.KEYS) or theta != 135:
        raise AssertionError("source K13 projection differs")
    candidate_groups = [g for g in source["dp_groups"]
                        if g["source"] == "fresh_full_conditional_dp"
                        and g["signature"]["earliest_terminal_unit"] == 40896]
    if len(candidate_groups) != 1:
        raise AssertionError("expected one fresh K13 DP group")
    certified_group = candidate_groups[0]
    certified_signature = certified_group["signature"]
    full = source["new_representative_full_dp"]
    dp_cents = int(certified_group["dp_cents"])
    if (full["dp_cents"] != dp_cents
            or full["key_deadline_unit"] != certified_signature["key_deadline_units"]
            or full["mandatory_key_mask"] != certified_signature["mandatory_key_mask"]
            or full["required_key_mask"] != certified_signature["required_key_mask"]):
        raise AssertionError("fresh K13 source DP does not match signed group")

    threshold = int(exact16["exactly_sixteen_upper_cents"])
    targets = [r for r in rows if int(r["merged_upper_cents"]) > threshold]
    indices_by_tile = [np.flatnonzero(data["complete_tile"] == i)
                       for i in range(len(data["tile_ids"]))]
    theta_constant = theta * (len(data["tile_ids"]) - len(keys))
    refinements = {}
    for row in targets:
        key = (row["request_mask"], row["rq0004_branch"])
        original = original_by_key[key]
        spec = grouped._branch_spec(
            data, choices, instants,
            tuple(original["unawarded_request_ids"]), row["rq0004_branch"],
        )
        if (spec["reward_cents"] != original["request_reward_cents"]
                or spec["miss_cents"] != original["unavoidable_miss_cents"]):
            raise AssertionError("request reward/penalty differs from prior audit")
        branch_inputs = {
            "deadlines_by_branch": [spec["deadlines"]],
            "instants": instants,
            "earliest_terminal_unit": spec["earliest_terminal_unit"],
        }
        sig = reused._signature(
            data, branch_inputs, keys, theta, audit["price_sha256"],
            audit["projection_certificate_sha256"], 0,
        )
        if any(sig[field] != value for field, value in certified_signature.items()):
            raise AssertionError(f"target has a different K13 DP input: {key}")
        external = reused._external_cents(
            data, spec["deadlines"], keys, instants, arc_starts,
            indices_by_tile,
        )
        total = (external + spec["reward_cents"] + theta_constant
                 + dp_cents - spec["miss_cents"])
        refinements[key] = {
            "request_mask": key[0],
            "rq0004_branch": key[1],
            "unawarded_request_ids": spec["missed_ids"],
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "external_cents": external,
            "selected_reward_cents": int(spec["reward_cents"]),
            "unavoidable_miss_cents": int(spec["miss_cents"]),
            "theta_constant_cents": theta_constant,
            "shared_dp_cents": dp_cents,
            "k13_upper_cents": total,
            "merged_upper_cents": min(int(row["merged_upper_cents"]), total),
        }
    if len(targets) != 14:
        raise AssertionError("expected fourteen unresolved branches")

    merged_rows = []
    for row in rows:
        key = (row["request_mask"], row["rq0004_branch"])
        new = refinements.get(key)
        merged_rows.append({
            "request_mask": key[0],
            "rq0004_branch": key[1],
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "k13_upper_cents": new["k13_upper_cents"] if new else None,
            "merged_upper_cents": new["merged_upper_cents"]
                                  if new else int(row["merged_upper_cents"]),
        })
    exact15 = max(r["merged_upper_cents"] for r in merged_rows)
    at_most14 = int(old["at_most_fourteen_upper_cents"])
    at_most15 = max(at_most14, exact15)
    if at_most15 > old["at_most_fifteen_upper_cents"]:
        raise AssertionError("refinement weakened <=15 bound")
    return {
        "scope": "dev-reference; all valid traces with at most 16 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "prior_fifteen_certificate_sha256": _sha(prior15_path),
        "source_k13_certificate_sha256": _sha(source_path),
        "exact_fifteen_diagnostic_sha256": _sha(diagnostic_path),
        "exact_sixteen_certificate_sha256": _sha(exact16_path),
        "source_dp_signature": certified_signature,
        "source_dp_signature_sha256": certified_group["signature_sha256"],
        "source_dp_cents": dp_cents,
        "fresh_dp_evaluations": 0,
        "target_threshold_cents": threshold,
        "branch_count": len(merged_rows),
        "refined_branch_count": len(refinements),
        "refinements": list(refinements.values()),
        "merged_branch_rows": merged_rows,
        "at_most_fourteen_upper_cents": at_most14,
        "exactly_fifteen_upper_cents": exact15,
        "at_most_fifteen_upper_cents": at_most15,
        "exactly_sixteen_upper_cents": threshold,
        "at_most_sixteen_upper_cents": max(at_most15, threshold),
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "The prior signed table is checked against all 256 exact-15 "
            "request witness cases. Its fourteen branches above the exact-16 "
            "ceiling all have the identical complete K13 DP signature of a "
            "previously certified fresh full DP group. That DP integer is "
            "reused without a new solve. Non-key science envelopes and request "
            "terms are independently recomputed in integer cents for each "
            "target; all other branches keep valid prior bounds."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-fifteen", type=Path, default=PRIOR_FIFTEEN)
    parser.add_argument("--source-k13", type=Path, default=SOURCE_K13)
    parser.add_argument("--diagnostic", type=Path, default=DIAGNOSTIC)
    parser.add_argument("--exact-sixteen", type=Path, default=EXACT_SIXTEEN)
    parser.add_argument("--prices", type=Path, default=projection.PRICE_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.prior_fifteen, args.source_k13,
                     args.diagnostic, args.exact_sixteen, args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "refined_branch_count": result["refined_branch_count"],
        "exactly_fifteen_upper_cents": result["exactly_fifteen_upper_cents"],
        "at_most_fifteen_upper_cents": result["at_most_fifteen_upper_cents"],
        "at_most_sixteen_upper_cents": result["at_most_sixteen_upper_cents"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
