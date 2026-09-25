#!/usr/bin/env python3
"""Extend an audited projected key set with the exact pruned ring DP.

The prior root is trusted only after its key tuple, integer ledger, arc counts,
price SHA, and explicit expected upper bound have been checked.  Each new
candidate is computed on the complete audited action graph.  Equivalent
RQ0004 branches share one DP only after all 16 DP inputs are compared.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import bounds_request_projection_k10 as full
from bounds_request_projection_ring import transition_horizon
from projection_branch_merge import two_equivalent_branches
from projection_ring_state_pruning import conditional_projected_dp_pruned


def _case_from_prior(prior: dict, base: tuple[str, ...]) -> dict:
    cases = [row for row in prior["cases"] if tuple(row["keys"]) == base]
    if len(cases) != 1:
        raise AssertionError("prior certificate does not contain the exact base key tuple")
    case = cases[0]
    if case["all_awarded_upper_cents"] != max(
        row["conditional_upper_cents"] for row in case["branches"]
    ):
        raise AssertionError("prior branch maximum differs")
    for row in case["branches"]:
        if row["conditional_upper_cents"] != sum(row[field] for field in (
            "external_cents", "request_cents", "theta_constant_cents", "dp_cents",
        )):
            raise AssertionError("prior branch integer ledger differs")
    return case


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-keys", required=True)
    parser.add_argument("--extra", required=True,
                        help="comma-separated distinct candidate tiles")
    parser.add_argument("--prior-certificate", type=Path, required=True)
    parser.add_argument("--expected-base-cents", type=int, required=True)
    parser.add_argument("--theta-cents", type=int, default=135)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    base = tuple(filter(None, args.base_keys.split(",")))
    extra = tuple(filter(None, args.extra.split(",")))
    if (not base or not extra or len(base) + len(extra) != len(set(base + extra))
            or len(base) + 1 > 20):
        raise ValueError("requires unique keys and at most 20 projected keys")
    prior = json.loads(args.prior_certificate.read_text())
    prior_case = _case_from_prior(prior, base)
    if (prior_case["all_awarded_upper_cents"] != args.expected_base_cents
            or prior["theta_uniform_cents"] != args.theta_cents):
        raise AssertionError("base bound or theta differs from prior certificate")
    data, certs = full._load_audited_data(full.PRICE_FILE)
    if (prior["certificates"]["price_sha256"] != certs["price_sha256"]
            or prior["complete_arc_count"] != data["complete_arc_count"]
            or prior["weather_interruption_arc_count"] != data["partial_arc_count"]):
        raise AssertionError("prior certificate uses different graph or capacity prices")
    if any(tile not in data["tile_ids"] for tile in base + extra):
        raise ValueError("unknown tile")
    inputs = full._instance_inputs(data)
    cases = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    partial_path = args.out.with_suffix(".partial.json")
    for tile in extra:
        keys = base + (tile,)
        branch_started = time.monotonic()
        if "T00004" not in keys and "T00012" not in keys:
            branches, sharing = two_equivalent_branches(
                data, inputs, keys, args.theta_cents,
                conditional_projected_dp_pruned,
            )
        else:
            branches = [full._conditional_bound(
                data, inputs, keys, args.theta_cents, branch,
                dp_function=conditional_projected_dp_pruned,
            ) for branch in range(2)]
            sharing = {"second_dp_reused": False,
                       "reason": "RQ0004 choice tile belongs to projected key set"}
        if not all(row["feasible_relaxation"] for row in branches):
            raise AssertionError("all-awarded branch was not evaluated")
        for row in branches:
            if row["conditional_upper_cents"] != sum(row[field] for field in (
                "external_cents", "request_cents", "theta_constant_cents", "dp_cents",
            )):
                raise AssertionError("candidate integer ledger differs")
        case = {"keys": list(keys), "extra_tile": tile,
                "all_awarded_upper_cents": max(
                    row["conditional_upper_cents"] for row in branches),
                "branches": branches, "sharing_audit": sharing,
                "elapsed_seconds": time.monotonic() - branch_started}
        cases.append(case)
        partial_path.write_text(json.dumps({
            "status": "running", "cases": cases,
            "elapsed_seconds": time.monotonic() - started,
            "peak_rss_mib": full._rss_mib(),
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"extra_tile": tile,
                          "all_awarded_upper_cents": case["all_awarded_upper_cents"],
                          "elapsed_seconds": time.monotonic() - started,
                          "peak_rss_mib": full._rss_mib()}), flush=True)
    payload = {
        "scope": "public dev-reference; all 17 feasible request rewards",
        "prior_certificate_sha256": hashlib.sha256(
            args.prior_certificate.read_bytes()).hexdigest(),
        "certificates": certs, "theta_uniform_cents": args.theta_cents,
        "base_keys": list(base), "base_upper_cents": args.expected_base_cents,
        "ring_time_rows": transition_horizon(data),
        "full_time_rows": data["n"] + 1,
        "complete_arc_count": data["complete_arc_count"],
        "weather_interruption_arc_count": data["partial_arc_count"],
        "cases": cases,
        "all_awarded_upper_cents": min(
            row["all_awarded_upper_cents"] for row in cases),
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": full._rss_mib(),
    }
    args.out.write_text(json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    partial_path.unlink(missing_ok=True)
    print(json.dumps({"all_awarded_upper_cents": payload["all_awarded_upper_cents"],
                      "runtime_seconds": payload["runtime_seconds"],
                      "peak_rss_mib": payload["peak_rss_mib"]}, sort_keys=True))


if __name__ == "__main__":
    main()
