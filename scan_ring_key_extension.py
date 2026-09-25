#!/usr/bin/env python3
"""Extend a certified all-request key set using the exact ring-buffer DP."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import bounds_request_projection_k10 as full
from bounds_request_projection_ring import conditional_projected_dp_ring, transition_horizon


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-keys", required=True,
                        help="comma-separated ordered key set from prior certificate")
    parser.add_argument("--extra", required=True,
                        help="comma-separated candidate keys to add one at a time")
    parser.add_argument("--prior-certificate", type=Path, required=True)
    parser.add_argument("--expected-base-cents", type=int, required=True)
    parser.add_argument("--theta-cents", type=int, default=135)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    base = tuple(tile for tile in args.base_keys.split(",") if tile)
    extra = [tile for tile in args.extra.split(",") if tile]
    if not base or not extra or len(set(base + tuple(extra))) != len(base) + len(extra):
        raise ValueError("base and extension keys must be unique")
    prior = json.loads(args.prior_certificate.read_text())
    data, certs = full._load_audited_data(full.PRICE_FILE)
    inputs = full._instance_inputs(data)
    if (prior["certificates"]["price_sha256"] != certs["price_sha256"]
            or prior["all_awarded_upper_cents"] != args.expected_base_cents):
        raise AssertionError("prior certificate does not match this scan")
    if any(tile not in data["tile_ids"] for tile in base + tuple(extra)):
        raise ValueError("unknown tile")
    base_branches = [
        full._conditional_bound(
            data, inputs, base, args.theta_cents, branch,
            dp_function=conditional_projected_dp_ring,
        ) for branch in range(2)
    ]
    if max(row["conditional_upper_cents"] for row in base_branches) != args.expected_base_cents:
        raise AssertionError("ring baseline differs from prior certificate")
    cases = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    partial_path = args.out.with_suffix(".partial.json")
    for tile in extra:
        keys = base + (tile,)
        branches = [
            full._conditional_bound(
                data, inputs, keys, args.theta_cents, branch,
                dp_function=conditional_projected_dp_ring,
            ) for branch in range(2)
        ]
        if not all(branch["feasible_relaxation"] for branch in branches):
            raise AssertionError("unexpected infeasible all-request branch")
        case = {
            "keys": list(keys),
            "all_awarded_upper_cents": max(
                branch["conditional_upper_cents"] for branch in branches
            ),
            "branches": branches,
        }
        cases.append(case)
        partial_path.write_text(json.dumps({
            "status": "running", "cases": cases,
            "elapsed_seconds": time.monotonic() - started,
            "peak_rss_mib": full._rss_mib(),
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        print(json.dumps({
            "new_key": tile,
            "all_awarded_upper_cents": case["all_awarded_upper_cents"],
            "elapsed_seconds": time.monotonic() - started,
            "peak_rss_mib": full._rss_mib(),
        }), flush=True)
    payload = {
        "scope": "public dev-reference; conditional on all 17 feasible request rewards",
        "prior_certificate_sha256": full.hashlib.sha256(args.prior_certificate.read_bytes()).hexdigest(),
        "certificates": certs,
        "theta_uniform_cents": args.theta_cents,
        "base_keys": list(base),
        "base_branches": base_branches,
        "ring_time_rows": transition_horizon(data),
        "full_time_rows": data["n"] + 1,
        "complete_arc_count": data["complete_arc_count"],
        "weather_interruption_arc_count": data["partial_arc_count"],
        "cases": cases,
        "all_awarded_upper_cents": min(row["all_awarded_upper_cents"] for row in cases),
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": full._rss_mib(),
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    partial_path.unlink(missing_ok=True)
    print(json.dumps({
        "all_awarded_upper_cents": payload["all_awarded_upper_cents"],
        "runtime_seconds": payload["runtime_seconds"],
        "peak_rss_mib": payload["peak_rss_mib"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
