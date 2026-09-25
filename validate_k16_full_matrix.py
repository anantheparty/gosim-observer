#!/usr/bin/env python3
"""Independent full-time-matrix check of the audited K16 ring result."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import bounds_request_projection_k10 as full


KEYS = full.BASE_KEYS + (
    "T00048", "T00032", "T00016", "T00010", "T00047", "T00011",
    "T00027", "T00062",
)
BASE_KEYS = KEYS[:-1]
FIELDS = (
    "conditional_upper_cents", "external_cents", "request_cents",
    "theta_constant_cents", "dp_cents", "required_key_mask",
    "mandatory_key_mask", "key_deadline_unit", "rq0004_tile",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ring-certificate", type=Path,
                        default=full.ROOT / "results" / "practice_request_projection_k16_ring.json")
    parser.add_argument("--base-certificate", type=Path,
                        default=full.ROOT / "results" / "practice_request_projection_k15_ring.json")
    parser.add_argument("--out", type=Path,
                        default=full.ROOT / "results" / "practice_request_projection_k16_full_check.json")
    args = parser.parse_args()
    started = time.monotonic()
    ring = json.loads(args.ring_certificate.read_text())
    base = json.loads(args.base_certificate.read_text())
    if (ring["all_awarded_upper_cents"] != 2133124
            or len(ring["cases"]) != 1
            or tuple(ring["cases"][0]["keys"]) != KEYS):
        raise AssertionError("unexpected K16 ring certificate")
    data, certs = full._load_audited_data(full.PRICE_FILE)
    if certs["price_sha256"] != ring["certificates"]["price_sha256"]:
        raise AssertionError("capacity-price certificate differs")
    if (certs["price_sha256"] != base["certificates"]["price_sha256"]
            or base["all_awarded_upper_cents"] != 2137159):
        raise AssertionError("K15 baseline certificate differs")
    inputs = full._instance_inputs(data)
    base_cases = [row for row in base["cases"] if tuple(row["keys"]) == BASE_KEYS]
    if len(base_cases) != 1:
        raise AssertionError("K15 baseline key set missing")
    base_branches = []
    for i in range(2):
        row = full._conditional_bound(data, inputs, BASE_KEYS, 135, i)
        old = base_cases[0]["branches"][i]
        if {field: row[field] for field in FIELDS} != {field: old[field] for field in FIELDS}:
            raise AssertionError(f"K15 baseline full/ring mismatch in branch {i}")
        base_branches.append(row)
        print(json.dumps({
            "baseline_branch_index": i,
            "upper_cents": row["conditional_upper_cents"],
            "elapsed_seconds": time.monotonic() - started,
            "peak_rss_mib": full._rss_mib(),
        }), flush=True)
    branches = []
    for i in range(2):
        row = full._conditional_bound(data, inputs, KEYS, 135, i)
        old = ring["cases"][0]["branches"][i]
        if {field: row[field] for field in FIELDS} != {field: old[field] for field in FIELDS}:
            raise AssertionError(f"full and ring differ in branch {i}")
        branches.append(row)
        print(json.dumps({
            "branch_index": i,
            "upper_cents": row["conditional_upper_cents"],
            "elapsed_seconds": time.monotonic() - started,
            "peak_rss_mib": full._rss_mib(),
        }), flush=True)
    payload = {
        "scope": ring["scope"],
        "base_certificate_sha256": hashlib.sha256(args.base_certificate.read_bytes()).hexdigest(),
        "ring_certificate_sha256": hashlib.sha256(args.ring_certificate.read_bytes()).hexdigest(),
        "price_sha256": certs["price_sha256"],
        "keys": list(KEYS),
        "base_keys": list(BASE_KEYS),
        "base_branches": base_branches,
        "theta_cents": 135,
        "complete_arc_count": data["complete_arc_count"],
        "weather_interruption_arc_count": data["partial_arc_count"],
        "branches": branches,
        "all_awarded_upper_cents": max(row["conditional_upper_cents"] for row in branches),
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": full._rss_mib(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "all_awarded_upper_cents": payload["all_awarded_upper_cents"],
        "runtime_seconds": payload["runtime_seconds"],
        "peak_rss_mib": payload["peak_rss_mib"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
