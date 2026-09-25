#!/usr/bin/env python3
"""Pilot three eleventh-key candidates on the certified best ten-key set."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import bounds_request_projection_k10 as bound


BASE_K10 = bound.BASE_KEYS + ("T00048", "T00032")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair-certificate", type=Path,
                        default=bound.ROOT / "results" / "practice_request_projection_k10_pairscan.json")
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--extra", default="", help="optional comma-separated eleventh keys")
    parser.add_argument("--out", type=Path,
                        default=bound.ROOT / "results" / "practice_request_projection_k11_pilot.json")
    args = parser.parse_args()
    started = time.monotonic()
    prior = json.loads(args.pair_certificate.read_text())
    data, certs = bound._load_audited_data(bound.PRICE_FILE)
    inputs = bound._instance_inputs(data)
    if (prior["certificates"]["price_sha256"] != certs["price_sha256"]
            or prior["theta_uniform_cents"] != 135
            or prior["all_awarded_upper_cents"] != 2163466):
        raise AssertionError("prior ten-key bound changed")
    base_branches = [
        bound._conditional_bound(data, inputs, BASE_K10, 135, i)
        for i in range(2)
    ]
    if max(b["conditional_upper_cents"] for b in base_branches) != 2163466:
        raise AssertionError("fresh ten-key DP did not reproduce certificate")
    ranked = sorted(prior["second_key_cases"],
                    key=lambda row: row["all_awarded_upper_cents"])
    candidates = [row["keys"][-1] for row in ranked if row["keys"][-1] != "T00032"]
    selected = [s for s in args.extra.split(",") if s] or candidates[:args.top_n]
    if (len(set(selected)) != len(selected)
            or any(tile in BASE_K10 or tile not in data["tile_ids"] for tile in selected)):
        raise ValueError("invalid eleventh-key candidate")
    cases = []
    for extra in selected:
        keys = BASE_K10 + (extra,)
        branches = [
            bound._conditional_bound(data, inputs, keys, 135, i)
            for i in range(2)
        ]
        if not all(b["feasible_relaxation"] for b in branches):
            raise AssertionError("unexpected infeasible all-request branch")
        case = {
            "keys": list(keys),
            "all_awarded_upper_cents": max(b["conditional_upper_cents"] for b in branches),
            "branches": branches,
        }
        cases.append(case)
        print(json.dumps({
            "new_key": extra,
            "all_awarded_upper_cents": case["all_awarded_upper_cents"],
            "elapsed_seconds": time.monotonic() - started,
            "peak_rss_mib": bound._rss_mib(),
        }), flush=True)
    best = min(case["all_awarded_upper_cents"] for case in cases)
    global_upper = max(best, certs["other_award_subsets_upper_cents"])
    payload = {
        "scope": "public dev-reference; all-17 award conditional, with prior <17 certificate",
        "prior_pair_certificate_sha256": bound.hashlib.sha256(args.pair_certificate.read_bytes()).hexdigest(),
        "certificates": certs,
        "base_k10": list(BASE_K10),
        "base_k10_branches": base_branches,
        "theta_uniform_cents": 135,
        "candidate_selection": "best alternative tenth keys from complete 55-case pair scan",
        "tested_extra_keys": selected,
        "cases": cases,
        "all_awarded_upper_cents": best,
        "unconditional_upper_cents": global_upper,
        "complete_arc_count": data["complete_arc_count"],
        "weather_interruption_arc_count": data["partial_arc_count"],
        "capacity_units": data["n"],
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": bound._rss_mib(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "all_awarded_upper_cents": best,
        "unconditional_upper_cents": global_upper,
        "runtime_seconds": payload["runtime_seconds"],
        "peak_rss_mib": payload["peak_rss_mib"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
