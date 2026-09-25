#!/usr/bin/env python3
"""Pilot three thirteenth-key candidates after the best twelve-key relaxation."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import bounds_request_projection_k10 as bound


BASE_K12 = bound.BASE_KEYS + ("T00048", "T00032", "T00016", "T00010")
DEFAULT_EXTRA = ("T00047", "T00011", "T00027")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k12-certificate", type=Path,
                        default=bound.ROOT / "results" / "practice_request_projection_k12_pilot.json")
    parser.add_argument("--extra", default=",".join(DEFAULT_EXTRA))
    parser.add_argument("--out", type=Path,
                        default=bound.ROOT / "results" / "practice_request_projection_k13_pilot.json")
    args = parser.parse_args()
    started = time.monotonic()
    prior = json.loads(args.k12_certificate.read_text())
    data, certs = bound._load_audited_data(bound.PRICE_FILE)
    inputs = bound._instance_inputs(data)
    if (prior["certificates"]["price_sha256"] != certs["price_sha256"]
            or prior["theta_uniform_cents"] != 135
            or prior["all_awarded_upper_cents"] != 2151744):
        raise AssertionError("prior twelve-key bound changed")
    base_branches = [bound._conditional_bound(data, inputs, BASE_K12, 135, i)
                     for i in range(2)]
    if max(b["conditional_upper_cents"] for b in base_branches) != 2151744:
        raise AssertionError("fresh twelve-key DP did not reproduce certificate")
    selected = [s for s in args.extra.split(",") if s]
    if (not selected or len(set(selected)) != len(selected)
            or any(tile in BASE_K12 or tile not in data["tile_ids"] for tile in selected)):
        raise ValueError("invalid thirteenth-key candidate")
    cases = []
    for extra in selected:
        keys = BASE_K12 + (extra,)
        branches = [bound._conditional_bound(data, inputs, keys, 135, i)
                    for i in range(2)]
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
    payload = {
        "scope": "public dev-reference; all-17 request conditional bound",
        "prior_k12_certificate_sha256": bound.hashlib.sha256(args.k12_certificate.read_bytes()).hexdigest(),
        "certificates": certs,
        "base_k12": list(BASE_K12),
        "base_k12_branches": base_branches,
        "theta_uniform_cents": 135,
        "candidate_selection": (
            "T00047 and T00011 are the next-best twelfth keys; T00027 is "
            "the next-best alternative tenth key after those"
        ),
        "cases": cases,
        "all_awarded_upper_cents": best,
        "old_less_than_17_upper_cents": certs["other_award_subsets_upper_cents"],
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
        "runtime_seconds": payload["runtime_seconds"],
        "peak_rss_mib": payload["peak_rss_mib"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
