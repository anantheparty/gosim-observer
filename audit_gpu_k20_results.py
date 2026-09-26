#!/usr/bin/env python3
"""Read-only audit of the complete, saved K20 GPU pair scan."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import gpu_k20_pair_scan as scan
from parallel_key_extension_scan import ROOT, sha256_file, sha256_json


DEFAULT_STATE_DIR = ROOT / "results/gpu_k20_pairs_20260926"
GPU_REFERENCE = ROOT / "results/gpu_k20_t00009_t00052_gpu_reference.json"
CPU_CROSSCHECK = ROOT / "results/gpu_k20_t00009_t00052_cpu_crosscheck.json"


def audit(state_dir: Path) -> dict:
    (keys, saved, base_sha, data, graph_audit, _inputs, remaining,
     sixteen_upper, sixteen_sha, saved_best, saved_hashes) = scan.audited_inputs()
    manifest = json.loads((state_dir / "manifest.json").read_text())
    expected_manifest = scan.manifest_for(
        base_sha, graph_audit, keys, remaining, sixteen_upper, sixteen_sha,
        saved_hashes, "auto",
    )
    if manifest != expected_manifest:
        raise AssertionError("K20 manifest/source/input hashes differ")

    ordered = scan.ordered_pairs(remaining)
    plan = json.loads((state_dir / "plan.json").read_text())
    if (plan["mode"] != "all" or plan["candidate_count"] != scan.PAIR_COUNT
            or plan["candidate_pairs"] != [list(pair) for pair in ordered]
            or plan["plan_sha256"] != sha256_json({
                "manifest": manifest, "candidate_pairs": ordered,
            })):
        raise AssertionError("K20 exhaustive pair plan differs")

    status = json.loads((state_dir / "status.json").read_text())
    if (status["status"] != "complete"
            or status["plan_sha256"] != plan["plan_sha256"]
            or status["candidate_count"] != scan.PAIR_COUNT
            or status["completed_count"] != scan.PAIR_COUNT
            or status["failed_count"] != 0 or status["failures"]):
        raise AssertionError("K20 scan status is incomplete or failed")

    scan.validate_baseline(
        json.loads((state_dir / "k18_gpu_baseline.json").read_text()),
        "18", manifest, saved, saved_best,
    )
    scan.validate_baseline(
        json.loads((state_dir / "k19_gpu_best_replay.json").read_text()),
        "19", manifest, saved, saved_best,
    )
    case_dir = state_dir / "cases"
    expected_paths = {
        case_dir / f"{scan.pair_key(pair)}.json" for pair in ordered
    }
    if set(case_dir.glob("*.json")) != expected_paths:
        raise AssertionError("K20 checkpoints do not cover exactly 1,035 pairs")
    rows = [
        scan.validate_case(case_dir / f"{scan.pair_key(pair)}.json",
                           pair, manifest)
        for pair in ordered
    ]
    ranking = sorted(rows, key=lambda row: (
        row["unconditional_upper_cents"], row["pair"],
    ))
    best = ranking[0]
    if (status["best_completed_pair"] != best["pair"]
            or status["best_completed_upper_cents"]
            != best["unconditional_upper_cents"]):
        raise AssertionError("saved K20 minimum differs from all checkpoints")
    expected_top_20 = [
        (row["pair"], row["unconditional_upper_cents"],
         row["case_input_sha256"])
        for row in ranking[:20]
    ]
    saved_top_20 = [
        (row["pair"], row["upper_cents"], row["case_input_sha256"])
        for row in status["top_20"]
    ]
    if saved_top_20 != expected_top_20:
        raise AssertionError("saved K20 top 20 differs from all checkpoints")

    gpu_reference = json.loads(GPU_REFERENCE.read_text())
    cpu_crosscheck = json.loads(CPU_CROSSCHECK.read_text())
    if (cpu_crosscheck["status"] != "passed"
            or cpu_crosscheck["gpu_reference_sha256"]
            != sha256_file(GPU_REFERENCE)):
        raise AssertionError("CPU crosscheck provenance differs")
    for field in (
        "all_awarded_upper_cents", "case_input_sha256", "dp_input_sha256",
        "branch_input_sha256", "price_sha256", "unconditional_upper_cents",
    ):
        if (gpu_reference[field] != best[field]
                or cpu_crosscheck[field] != best[field]):
            raise AssertionError(f"CPU/GPU best-case field differs: {field}")
    for i in range(2):
        for field in ("conditional_upper_cents", "dp_cents"):
            if cpu_crosscheck["branches"][i][field] != best["branches"][i][field]:
                raise AssertionError(f"CPU/GPU branch {i} differs: {field}")

    separate_branch_cases = sum(
        not row["branch_sharing_audit"]["second_dp_reused"] for row in rows
    )
    if separate_branch_cases != 89:
        raise AssertionError("unexpected count of separately solved request branches")
    dp_seconds = [
        sum(branch["dp_wall_seconds"] for branch in row["branches"])
        for row in rows
    ]
    return {
        "status": "validated", "candidate_count": len(rows),
        "distinct_unordered_pairs": len({tuple(row["pair"]) for row in rows}),
        "failed_count": status["failed_count"],
        "best_pair": best["pair"],
        "best_unconditional_upper_cents": best["unconditional_upper_cents"],
        "separate_branch_cases": separate_branch_cases,
        "total_dp_calls": len(rows) + separate_branch_cases,
        "scan_elapsed_seconds": status["elapsed_seconds"],
        "gpu_dp_sum_seconds": sum(dp_seconds),
        "gpu_dp_median_seconds": statistics.median(dp_seconds),
        "manifest_sha256": sha256_file(state_dir / "manifest.json"),
        "status_sha256": sha256_file(state_dir / "status.json"),
        "cpu_crosscheck_sha256": sha256_file(CPU_CROSSCHECK),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    args = parser.parse_args()
    print(json.dumps(audit(args.state_dir), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
