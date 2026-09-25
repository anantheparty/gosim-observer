#!/usr/bin/env python3
"""Independently audit the CUDA K20 T00009+T00052 certificate with CPU DP.

The preflight rebuilds and hashes every scalar and byte of the existing
16-argument integer DP invocation, plus each RQ0004 branch's external terms.
The subsequent CPU calculation calls the unchanged pruned integer DP.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import bounds_request_projection_k10 as full
from parallel_key_extension_scan import (
    COMPARE_FIELDS, ROOT, atomic_json, calculate_case, sha256_dp_args,
    sha256_file, sha256_json, source_hashes,
)
from projection_branch_merge import two_equivalent_branches


K18_PILOT = ROOT / "results/practice_k18_t45_t1_pilot.json"
PAIR = ("T00009", "T00052")
THETA_CENTS = 135
SIXTEEN_UPPER_CENTS = 2_111_925


def run(reference_path: Path, output_path: Path) -> dict:
    started = time.monotonic()
    reference = json.loads(reference_path.read_text())
    saved = json.loads(K18_PILOT.read_text())
    keys = tuple(saved["key_tiles"]) + PAIR
    base_sha = sha256_file(K18_PILOT)
    if (reference["status"] != "completed"
            or reference["pair"] != list(PAIR)
            or reference["key_tiles"] != list(keys)
            or reference["key_count"] != 20
            or reference["base_certificate_sha256"] != base_sha
            or reference["theta_uniform_cents"] != THETA_CENTS
            or reference["at_most_sixteen_upper_cents"]
            != SIXTEEN_UPPER_CENTS):
        raise AssertionError("reference is not the expected K18+T00009+T00052 case")
    for name, digest in reference["source_sha256"].items():
        path = ROOT / name
        if path.is_file() and sha256_file(path) != digest:
            raise AssertionError(f"common CPU/GPU source differs: {name}")

    data, audit = full._load_audited_data(full.PRICE_FILE)
    if audit["price_sha256"] != reference["price_sha256"]:
        raise AssertionError("audited prices differ")
    inputs = full._instance_inputs(data)
    seen: list[str] = []

    def hash_only(*dp_args):
        if len(dp_args) != 16:
            raise AssertionError("expected exactly 16 integer DP arguments")
        seen.append(sha256_dp_args(dp_args))
        return 0

    branches, sharing = two_equivalent_branches(
        data, inputs, keys, THETA_CENTS, hash_only,
    )
    if len(seen) != 1 or not sharing["second_dp_reused"]:
        raise AssertionError("expected equivalent branch projection inputs")
    dp_hashes = [seen[0], seen[0]]
    branch_hashes = [sha256_json({
        "dp_input_sha256": dp_hashes[i],
        "external_cents": branch["external_cents"],
        "request_cents": branch["request_cents"],
        "theta_constant_cents": branch["theta_constant_cents"],
        "rq0004_tile": branch["rq0004_tile"],
    }) for i, branch in enumerate(branches)]
    case_hash = sha256_json({
        "key_tiles": keys,
        "theta_uniform_cents": THETA_CENTS,
        "branch_input_sha256": branch_hashes,
        "price_sha256": audit["price_sha256"],
        "base_certificate_sha256": base_sha,
    })
    for field, actual in (
        ("dp_input_sha256", dp_hashes),
        ("branch_input_sha256", branch_hashes),
        ("case_input_sha256", case_hash),
    ):
        if actual != reference[field]:
            raise AssertionError(f"preflight input mismatch: {field}")
    print(json.dumps({
        "preflight": "passed", "dp_argument_count": 16,
        "dp_input_sha256": dp_hashes,
        "branch_input_sha256": branch_hashes,
        "case_input_sha256": case_hash,
        "elapsed_seconds": time.monotonic() - started,
    }), flush=True)

    cpu = calculate_case(data, inputs, keys, THETA_CENTS, audit, base_sha)
    for field in (
        "key_tiles", "theta_uniform_cents", "all_awarded_upper_cents",
        "dp_input_sha256", "branch_input_sha256", "case_input_sha256",
        "price_sha256", "base_certificate_sha256",
    ):
        if cpu[field] != reference[field]:
            raise AssertionError(f"CPU/GPU case mismatch: {field}")
    for i in range(2):
        for field in (*COMPARE_FIELDS, "feasible_relaxation"):
            if cpu["branches"][i][field] != reference["branches"][i][field]:
                raise AssertionError(f"CPU/GPU branch {i} mismatch: {field}")
    if max(cpu["all_awarded_upper_cents"], SIXTEEN_UPPER_CENTS) != \
            reference["unconditional_upper_cents"]:
        raise AssertionError("unconditional bound combination differs")

    result = {
        "status": "passed",
        "scope": "K18 T00045+T00001 plus T00009+T00052; CPU pruned integer DP",
        "gpu_reference_sha256": sha256_file(reference_path),
        "k18_pilot_sha256": base_sha,
        "cpu_source_sha256": source_hashes(),
        "price_sha256": audit["price_sha256"],
        "complete_arc_count": data["complete_arc_count"],
        "partial_arc_count": data["partial_arc_count"],
        "dp_argument_count": 16,
        "dp_input_sha256": cpu["dp_input_sha256"],
        "branch_input_sha256": cpu["branch_input_sha256"],
        "case_input_sha256": cpu["case_input_sha256"],
        "branches": cpu["branches"],
        "all_awarded_upper_cents": cpu["all_awarded_upper_cents"],
        "unconditional_upper_cents": reference["unconditional_upper_cents"],
        "cpu_wall_seconds": cpu["wall_seconds"],
        "total_wall_seconds": time.monotonic() - started,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(output_path, result)
    print(json.dumps({
        "status": result["status"],
        "unconditional_upper_cents": result["unconditional_upper_cents"],
        "branch_upper_cents": [
            b["conditional_upper_cents"] for b in cpu["branches"]
        ],
        "cpu_wall_seconds": result["cpu_wall_seconds"],
        "total_wall_seconds": result["total_wall_seconds"],
    }), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.reference, args.out)


if __name__ == "__main__":
    main()
