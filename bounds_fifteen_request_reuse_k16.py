#!/usr/bin/env python3
"""Tighten exact-15 request branches using the certified all-17 K16 DP."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bounds_fifteen_request_grouped_k13 as fifteen
import bounds_request_projection_k10 as projection
import bounds_sixteen_request_k10 as sixteen
import bounds_sixteen_request_reuse_k16 as reused16


ROOT = projection.ROOT
PRIOR_FIFTEEN = ROOT / "results" / "practice_fifteen_request_grouped_k13.json"
DIAGNOSTIC = ROOT / "results" / "practice_fifteen_request_branch_analysis.json"
EXACT_SIXTEEN = ROOT / "results" / "practice_sixteen_request_reuse_k16.json"
K16_CERT = ROOT / "results" / "practice_request_projection_k16_ring.json"
DEFAULT_OUT = ROOT / "results" / "practice_fifteen_request_reuse_k16.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certify(prior15_path: Path, diagnostic_path: Path, exact16_path: Path,
            k16_path: Path, prices_path: Path) -> dict:
    started = time.monotonic()
    prior15 = json.loads(prior15_path.read_text())
    diagnostic = json.loads(diagnostic_path.read_text())
    exact16 = json.loads(exact16_path.read_text())
    k16 = json.loads(k16_path.read_text())
    data, audit = projection._load_audited_data(prices_path)
    choices, instants, arc_starts, _, _ = sixteen._certified_inputs(data)
    all_inputs = projection._instance_inputs(data)
    k16_case = k16["cases"][0]
    keys = tuple(k16_case["keys"])
    theta = int(k16["theta_uniform_cents"])
    if (len(k16["cases"]) != 1 or len(keys) != 16 or theta != 135
            or k16["certificates"]["price_sha256"] != audit["price_sha256"]
            or k16["certificates"]["projection_certificate_sha256"]
                != audit["projection_certificate_sha256"]
            or prior15["capacity_price_sha256"] != audit["price_sha256"]
            or diagnostic["capacity_price_sha256"] != audit["price_sha256"]
            or exact16["capacity_price_sha256"] != audit["price_sha256"]
            or exact16["reused_k16_certificate_sha256"] != _sha(k16_path)
            or int(exact16["exactly_sixteen_upper_cents"]) != 2123847):
        raise AssertionError("source certificates or audited model differ")
    shared_sig = reused16._signature(
        data, all_inputs, keys, theta, audit["price_sha256"],
        audit["projection_certificate_sha256"], 0,
    )
    if (shared_sig != exact16["shared_dp_signature"]
            or k16_case["branches"][0]["dp_cents"] != exact16["shared_dp_cents"]
            or k16_case["branches"][1]["dp_cents"] != exact16["shared_dp_cents"]):
        raise AssertionError("K16 DP source differs from the exact-16 reuse audit")

    rows = prior15["merged_branch_rows"]
    original_by_key = {
        (row["request_mask"], row["rq0004_branch"]): row
        for row in diagnostic["rows"]
    }
    row_by_key = {(row["request_mask"], row["rq0004_branch"]): row
                  for row in rows}
    if (len(rows) != 256 or len(row_by_key) != 256
            or len(original_by_key) != 256
            or set(row_by_key) != set(original_by_key)
            or max(int(row["merged_upper_cents"]) for row in rows)
                != int(prior15["exactly_fifteen_upper_cents"])):
        raise AssertionError("source exact-15 branch table differs")
    # A two-request miss set has two RQ0004 witnesses except when RQ0004
    # itself is unawarded.  This exhausts 16 + 2*C(16,2) = 256 cases.
    request_ids = [request.request_id for request, _ in choices]
    expected = {
        (pair, option)
        for pair in itertools.combinations(request_ids, 2)
        for option in ((0,) if "RQ0004" in pair else (0, 1))
    }
    actual = {
        (tuple(row["unawarded_request_ids"]), row["rq0004_branch"])
        for row in original_by_key.values()
    }
    if len(expected) != 256 or actual != expected:
        raise AssertionError("the 256 exact-15 branches are not exhaustive")

    threshold = int(exact16["exactly_sixteen_upper_cents"])
    targets = [row for row in rows if int(row["merged_upper_cents"]) > threshold]
    indices_by_tile = [np.flatnonzero(data["complete_tile"] == i)
                       for i in range(len(data["tile_ids"]))]
    theta_constant = theta * (len(data["tile_ids"]) - len(keys))
    refinements = {}
    for row in targets:
        key = (row["request_mask"], row["rq0004_branch"])
        original = original_by_key[key]
        missed = tuple(original["unawarded_request_ids"])
        spec = fifteen._branch_spec(
            data, choices, instants, missed, row["rq0004_branch"],
        )
        if (spec["reward_cents"] != original["request_reward_cents"]
                or spec["miss_cents"] != original["unavoidable_miss_cents"]):
            raise AssertionError("request reward or penalty differs from prior audit")
        branch_inputs = {
            "deadlines_by_branch": [spec["deadlines"]],
            "instants": instants,
            "earliest_terminal_unit": spec["earliest_terminal_unit"],
        }
        sig = reused16._signature(
            data, branch_inputs, keys, theta, audit["price_sha256"],
            audit["projection_certificate_sha256"], 0,
        )
        if sig != shared_sig:
            raise AssertionError(f"target branch changes K16 DP inputs: {missed}/{key[1]}")
        external = reused16._external_cents(
            data, spec["deadlines"], keys, instants, arc_starts, indices_by_tile,
        )
        new_upper = (external + spec["reward_cents"] + theta_constant
                     + exact16["shared_dp_cents"] - spec["miss_cents"])
        refinements[key] = {
            "request_mask": key[0],
            "rq0004_branch": key[1],
            "unawarded_request_ids": list(missed),
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "external_cents": external,
            "selected_reward_cents": int(spec["reward_cents"]),
            "unavoidable_miss_cents": int(spec["miss_cents"]),
            "theta_constant_cents": theta_constant,
            "shared_dp_cents": int(exact16["shared_dp_cents"]),
            "k16_upper_cents": new_upper,
            "merged_upper_cents": min(int(row["merged_upper_cents"]), new_upper),
        }
    merged_rows = []
    for row in rows:
        key = (row["request_mask"], row["rq0004_branch"])
        new = refinements.get(key)
        merged_rows.append({
            "request_mask": key[0],
            "rq0004_branch": key[1],
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "k16_upper_cents": new["k16_upper_cents"] if new else None,
            "merged_upper_cents": new["merged_upper_cents"]
                                  if new else int(row["merged_upper_cents"]),
        })
    exact15 = max(row["merged_upper_cents"] for row in merged_rows)
    at_most14 = int(prior15["at_most_fourteen_upper_cents"])
    at_most15 = max(at_most14, exact15)
    at_most16 = max(at_most15, threshold)
    if at_most15 > prior15["at_most_fifteen_upper_cents"]:
        raise AssertionError("refinement weakened the prior <=15 bound")
    return {
        "scope": "dev-reference; all valid traces with at most 16 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "prior_fifteen_certificate_sha256": _sha(prior15_path),
        "exact_fifteen_diagnostic_sha256": _sha(diagnostic_path),
        "exact_sixteen_reuse_certificate_sha256": _sha(exact16_path),
        "reused_k16_certificate_sha256": _sha(k16_path),
        "shared_dp_signature": shared_sig,
        "shared_dp_signature_sha256": hashlib.sha256(json.dumps(
            shared_sig, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest(),
        "shared_dp_cents": int(exact16["shared_dp_cents"]),
        "shared_dp_evaluations": 0,
        "branch_count": len(merged_rows),
        "refined_branch_count": len(refinements),
        "refinements": list(refinements.values()),
        "merged_branch_rows": merged_rows,
        "at_most_fourteen_upper_cents": at_most14,
        "exactly_fifteen_upper_cents": exact15,
        "at_most_fifteen_upper_cents": at_most15,
        "exactly_sixteen_upper_cents": threshold,
        "at_most_sixteen_upper_cents": at_most16,
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "The previous signed exact-15 branch table is checked against "
            "all 256 two-miss witness cases. Every branch above the new "
            "exact-16 ceiling has precisely the same complete K16 projected "
            "DP input signature as the certified all-17 case; its existing "
            "DP integer is reused without another DP run. Each target's "
            "non-key science envelope and request reward/penalty terms are "
            "recomputed independently; all other branches retain valid "
            "prior bounds."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-fifteen", type=Path, default=PRIOR_FIFTEEN)
    parser.add_argument("--diagnostic", type=Path, default=DIAGNOSTIC)
    parser.add_argument("--exact-sixteen", type=Path, default=EXACT_SIXTEEN)
    parser.add_argument("--k16-certificate", type=Path, default=K16_CERT)
    parser.add_argument("--prices", type=Path, default=projection.PRICE_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.prior_fifteen, args.diagnostic,
                     args.exact_sixteen, args.k16_certificate, args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        result, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n")
    print(json.dumps({
        "refined_branch_count": result["refined_branch_count"],
        "exactly_fifteen_upper_cents": result["exactly_fifteen_upper_cents"],
        "at_most_fifteen_upper_cents": result["at_most_fifteen_upper_cents"],
        "at_most_sixteen_upper_cents": result["at_most_sixteen_upper_cents"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
