#!/usr/bin/env python3
"""Test every second new key paired with the best ninth key T00048."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import bounds_request_projection_k10 as bound


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-extra", default="T00048")
    parser.add_argument("--k9-certificate", type=Path,
                        default=bound.ROOT / "results" / "practice_request_projection_k10_scan.json")
    parser.add_argument("--out", type=Path,
                        default=bound.ROOT / "results" / "practice_request_projection_k10_pairscan.json")
    args = parser.parse_args()
    started = time.monotonic()
    previous = json.loads(args.k9_certificate.read_text())
    data, certificates = bound._load_audited_data(bound.PRICE_FILE)
    inputs = bound._instance_inputs(data)
    if (previous["certificates"]["price_sha256"] != certificates["price_sha256"]
            or previous["theta_uniform_cents"] != 135
            or tuple(previous["baseline_keys"]) != bound.BASE_KEYS):
        raise AssertionError("prior k9 certificate is not the audited baseline")
    k9 = [row for row in previous["tested"] if len(row["keys"]) == 9]
    if len(k9) != 56 or len({row["keys"][-1] for row in k9}) != 56:
        raise AssertionError("prior certificate did not cover all ninth keys")
    first_rows = [row for row in k9 if row["keys"][-1] == args.first_extra]
    if len(first_rows) != 1:
        raise AssertionError("chosen ninth key was not tested")
    already = {tuple(row["keys"]): row for row in previous["tested"] if len(row["keys"]) == 10}
    results = []
    for row in k9:
        extra = row["keys"][-1]
        if extra == args.first_extra:
            continue
        keys = bound.BASE_KEYS + (args.first_extra, extra)
        if keys in already:
            tested = already[keys]
        else:
            branches = [
                bound._conditional_bound(data, inputs, keys, 135, branch_index)
                for branch_index in range(2)
            ]
            if not all(branch["feasible_relaxation"] for branch in branches):
                raise AssertionError("unexpected infeasible all-request branch")
            tested = {
                "keys": list(keys), "theta_uniform_cents": 135,
                "branches": branches,
                "all_awarded_upper_cents": max(
                    branch["conditional_upper_cents"] for branch in branches
                ),
            }
        results.append(tested)
        print(json.dumps({
            "second_extra": extra,
            "all_awarded_upper_cents": tested["all_awarded_upper_cents"],
            "elapsed_seconds": time.monotonic() - started,
        }), flush=True)
    best = min(row["all_awarded_upper_cents"] for row in results)
    global_upper = max(best, certificates["other_award_subsets_upper_cents"])
    payload = {
        "scope": previous["scope"],
        "prior_k9_certificate_sha256": bound.hashlib.sha256(args.k9_certificate.read_bytes()).hexdigest(),
        "certificates": certificates,
        "base_keys": list(bound.BASE_KEYS),
        "first_extra": args.first_extra,
        "theta_uniform_cents": 135,
        "complete_arc_count": data["complete_arc_count"],
        "weather_interruption_arc_count": data["partial_arc_count"],
        "second_key_cases": results,
        "all_awarded_upper_cents": best,
        "unconditional_upper_cents": global_upper,
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": bound._rss_mib(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "unconditional_upper_cents": global_upper,
        "all_awarded_upper_cents": best,
        "runtime_seconds": payload["runtime_seconds"],
        "peak_rss_mib": payload["peak_rss_mib"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
