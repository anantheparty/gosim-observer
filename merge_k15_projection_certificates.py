#!/usr/bin/env python3
"""Bind the Rhodes1 full-matrix and local ten-row K15 certificates."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FIELDS = (
    "conditional_upper_cents", "external_cents", "request_cents",
    "theta_constant_cents", "dp_cents", "required_key_mask",
    "mandatory_key_mask", "key_deadline_unit", "rq0004_tile",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ring", type=Path,
                        default=Path("results/practice_request_projection_k15_ring.json"))
    parser.add_argument("--full-t27", type=Path, default=Path("/tmp/gosim_k15_t27_full.json"))
    parser.add_argument("--full-t62", type=Path, default=Path("/tmp/gosim_k15_t62_full.json"))
    parser.add_argument("--prior", type=Path,
                        default=Path("results/practice_request_projection_k14_pilot.json"))
    parser.add_argument("--out", type=Path,
                        default=Path("results/practice_request_projection_k15_certified.json"))
    args = parser.parse_args()
    ring = json.loads(args.ring.read_text())
    full_files = {"T00027": args.full_t27, "T00062": args.full_t62}
    prior_digest = hashlib.sha256(args.prior.read_bytes()).hexdigest()
    if ring["prior_certificate_sha256"] != prior_digest:
        raise AssertionError("ring used another K14 certificate")
    if ring["ring_time_rows"] != 10 or ring["full_time_rows"] != 47569:
        raise AssertionError("the audited time horizon changed")
    ring_cases = {row["keys"][-1]: row for row in ring["cases"]}
    if set(ring_cases) != set(full_files):
        raise AssertionError("candidate sets differ")
    comparisons = []
    full_payloads = []
    for tile, path in full_files.items():
        full = json.loads(path.read_text())
        if (full["prior_k14_certificate_sha256"] != prior_digest
                or full["certificates"]["price_sha256"]
                != ring["certificates"]["price_sha256"]
                or full["complete_arc_count"] != ring["complete_arc_count"]
                or full["weather_interruption_arc_count"]
                != ring["weather_interruption_arc_count"]
                or len(full["cases"]) != 1):
            raise AssertionError(f"{tile}: input certificate mismatch")
        full_case = full["cases"][0]
        ring_case = ring_cases[tile]
        if full_case["keys"] != ring_case["keys"]:
            raise AssertionError(f"{tile}: key set differs")
        for branch_index in range(2):
            a = full_case["branches"][branch_index]
            b = ring_case["branches"][branch_index]
            if {field: a[field] for field in FIELDS} != {field: b[field] for field in FIELDS}:
                raise AssertionError(f"{tile}: branch {branch_index} differs")
            comparisons.append({
                "extra_key": tile,
                "branch_index": branch_index,
                "upper_cents": a["conditional_upper_cents"],
                "full_dp_seconds": a["dp_wall_seconds"],
                "ring_dp_seconds": b["dp_wall_seconds"],
            })
        full_payloads.append({
            "extra_key": tile,
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "runtime_seconds": full["runtime_seconds"],
            "peak_rss_mib": full["peak_rss_mib"],
            "all_awarded_upper_cents": full["all_awarded_upper_cents"],
            "case": full_case,
        })
    payload = {
        "scope": ring["scope"],
        "price_sha256": ring["certificates"]["price_sha256"],
        "prior_k14_sha256": prior_digest,
        "ring_certificate_sha256": hashlib.sha256(args.ring.read_bytes()).hexdigest(),
        "complete_arc_count": ring["complete_arc_count"],
        "weather_interruption_arc_count": ring["weather_interruption_arc_count"],
        "ring_time_rows": ring["ring_time_rows"],
        "full_time_rows": ring["full_time_rows"],
        "ring_runtime_seconds": ring["runtime_seconds"],
        "ring_peak_rss_mib": ring["peak_rss_mib"],
        "full_remote_trials": full_payloads,
        "exact_branch_comparisons": comparisons,
        "all_awarded_upper_cents": min(
            row["all_awarded_upper_cents"] for row in full_payloads
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"all_awarded_upper_cents": payload["all_awarded_upper_cents"],
                      "compared_branches": len(comparisons)}))


if __name__ == "__main__":
    main()
