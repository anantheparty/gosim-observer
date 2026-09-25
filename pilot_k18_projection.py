#!/usr/bin/env python3
"""First K18 T45+T1 test using audited pruned DP and branch signatures."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import bounds_request_projection_k10 as full
from parallel_key_extension_scan import (
    ROOT, atomic_json, calculate_case, certified_base, sha256_file, source_hashes,
)
from projection_ring_state_pruning import mask_count_profile


K17_AGGREGATE = ROOT / "results/practice_parallel_k17_all_candidates.json"
PILOT_TILES = ("T00045", "T00001")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    base, _, base_sha = certified_base()
    aggregate = json.loads(K17_AGGREGATE.read_text())
    if (aggregate["best_extra_tile"] != PILOT_TILES[0]
            or [row["extra_tile"] for row in aggregate["rows"][:3]]
            != ["T00045", "T00001", "T00043"]
            or aggregate["base_certificate_sha256"] != base_sha):
        raise AssertionError("K17 exhaustive aggregate changed")
    data, certs = full._load_audited_data(full.PRICE_FILE)
    if aggregate["price_sha256"] != certs["price_sha256"]:
        raise AssertionError("K17/K18 audited prices differ")
    inputs = full._instance_inputs(data)
    keys = base + PILOT_TILES
    result = calculate_case(data, inputs, keys, 135, certs,
                            sha256_file(K17_AGGREGATE))
    data["arc_starts"] = inputs["arc_starts"]
    profile = mask_count_profile(data, keys, result["branches"][0])
    result.update({
        "status": "completed", "extra_tiles": list(PILOT_TILES),
        "key_count": 18,
        "k17_aggregate_sha256": sha256_file(K17_AGGREGATE),
        "k16_certificate_sha256": base_sha,
        "complete_arc_count": data["complete_arc_count"],
        "partial_arc_count": data["partial_arc_count"],
        "pruned_state_profile": profile,
        "worker_wall_seconds": time.monotonic() - started,
        "source_sha256": {
            **source_hashes(),
            "pilot_k18_projection.py": sha256_file(ROOT / "pilot_k18_projection.py"),
        },
    })
    atomic_json(args.out, result)
    print(json.dumps({
        "key_tiles": list(PILOT_TILES),
        "all_awarded_upper_cents": result["all_awarded_upper_cents"],
        "branches_upper_cents": [branch["conditional_upper_cents"]
                                 for branch in result["branches"]],
        "valid_state_time_cells": profile["valid_state_time_cells"],
        "worker_wall_seconds": result["worker_wall_seconds"],
        "case_input_sha256": result["case_input_sha256"],
    }), flush=True)


if __name__ == "__main__":
    main()
