#!/usr/bin/env python3
"""Resumable CUDA scan of every one-tile extension of the saved K18 bound.

The first GPU computation reproduces the entire saved K18 integer certificate.
Each subsequent K19 candidate runs in its own process and writes one atomic
checkpoint.  Capacity prices, action graph and request-subset certificate are
loaded from the existing audited files; this script only replaces the exact
16-argument projected DP with the CUDA implementation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Import this first: its Windows entrypoint installs a resource shim solely
# for the existing certificate code's optional peak-RSS reporting.
from gpu_projection_dp import conditional_projected_dp_cuda

import bounds_request_projection_k10 as full
from parallel_key_extension_scan import (
    COMPARE_FIELDS, ROOT, atomic_json, sha256_dp_args, sha256_file, sha256_json,
)
from projection_branch_merge import two_equivalent_branches


K18_PILOT = ROOT / "results/practice_k18_t45_t1_pilot.json"
K17_AGGREGATE = ROOT / "results/practice_parallel_k17_all_candidates.json"
SIXTEEN_CERT = ROOT / "results/practice_sixteen_request_reuse_k18.json"
SOURCE_FILES = (
    "gpu_k19_extension_scan.py", "gpu_projection_dp.py",
    "parallel_key_extension_scan.py", "projection_branch_merge.py",
    "projection_ring_state_pruning.py", "bounds_request_projection_ring.py",
    "bounds_request_projection_k10.py", "bounds_practice_projection.py",
    "bounds_request_conditioned.py", "challenge/scoring_core.py",
)
EXPECTED_K18_UPPER_CENTS = 2_128_284
EXPECTED_KEY_COUNT = 18
EXPECTED_THETA_CENTS = 135
EXPECTED_SIXTEEN_UPPER_CENTS = 2_111_925


def source_hashes() -> dict[str, str]:
    return {name: sha256_file(ROOT / name) for name in SOURCE_FILES}


def saved_base() -> tuple[tuple[str, ...], dict, str]:
    saved = json.loads(K18_PILOT.read_text())
    keys = tuple(saved["key_tiles"])
    if (saved["status"] != "completed" or len(keys) != EXPECTED_KEY_COUNT
            or len(set(keys)) != EXPECTED_KEY_COUNT
            or saved["key_count"] != EXPECTED_KEY_COUNT
            or saved["extra_tiles"] != ["T00045", "T00001"]
            or saved["theta_uniform_cents"] != EXPECTED_THETA_CENTS
            or saved["all_awarded_upper_cents"] != EXPECTED_K18_UPPER_CENTS
            or len(saved["branches"]) != 2):
        raise AssertionError("saved K18 pilot is not the expected base")
    for name, digest in saved["source_sha256"].items():
        if sha256_file(ROOT / name) != digest:
            raise AssertionError(f"saved K18 source changed: {name}")
    if sha256_file(K17_AGGREGATE) != saved["k17_aggregate_sha256"]:
        raise AssertionError("K17 aggregate differs from saved K18 input")
    return keys, saved, sha256_file(K18_PILOT)


def candidate_order(keys: tuple[str, ...], data: dict, saved: dict) -> tuple[str, ...]:
    """Deterministic order from the already audited K17 extension ranking."""
    aggregate = json.loads(K17_AGGREGATE.read_text())
    if (aggregate["price_sha256"] != saved["price_sha256"]
            or aggregate["best_extra_tile"] != "T00045"):
        raise AssertionError("K17 ranking differs from K18 provenance")
    known = set(data["tile_ids"])
    ranking = tuple(row["extra_tile"] for row in aggregate["rows"])
    if len(ranking) != len(set(ranking)) or not set(ranking).issubset(known):
        raise AssertionError("K17 ranking has duplicate or unknown tiles")
    remaining = tuple(tile for tile in ranking if tile not in keys)
    if set(remaining) != known - set(keys) or len(remaining) != 46:
        raise AssertionError("K17 ranking does not cover all 46 K19 additions")
    return remaining


def checked_sixteen_bound(saved: dict, audit: dict, base_sha: str) -> tuple[int, str]:
    """Use the current 16-request proof, not the loose old K8 subset table."""
    certificate = json.loads(SIXTEEN_CERT.read_text())
    if (certificate["at_most_sixteen_upper_cents"] != EXPECTED_SIXTEEN_UPPER_CENTS
            or certificate["capacity_price_sha256"] != audit["price_sha256"]
            or certificate["k18_pilot_certificate_sha256"] != base_sha
            or certificate["case_input_sha256"] != saved["case_input_sha256"]
            or certificate["shared_dp_input_sha256"] != saved["dp_input_sha256"][0]):
        raise AssertionError("current at-most-16-request proof differs from K18 inputs")
    return EXPECTED_SIXTEEN_UPPER_CENTS, sha256_file(SIXTEEN_CERT)


def evaluate_case(data: dict, inputs: dict, keys: tuple[str, ...],
                  theta_cents: int, audited_price_sha: str,
                  base_certificate_sha: str, launch_mode: str) -> dict:
    """Compute both RQ0004 branches, hashing the exact GPU DP arguments."""
    seen: list[str] = []

    def hashed_gpu_dp(*dp_args):
        seen.append(sha256_dp_args(dp_args))
        return conditional_projected_dp_cuda(*dp_args, launch_mode=launch_mode)

    started = time.monotonic()
    if "T00004" not in keys and "T00012" not in keys:
        branches, sharing = two_equivalent_branches(
            data, inputs, keys, theta_cents, hashed_gpu_dp,
        )
        if len(seen) != 1 or not sharing["second_dp_reused"]:
            raise AssertionError("equivalent branch DP was not reused")
        dp_input_hashes = [seen[0], seen[0]]
    else:
        branches = [full._conditional_bound(
            data, inputs, keys, theta_cents, branch_index,
            dp_function=hashed_gpu_dp,
        ) for branch_index in range(2)]
        if len(seen) != 2:
            raise AssertionError("both non-equivalent RQ0004 DPs were not computed")
        sharing = {"second_dp_reused": False,
                   "reason": "one RQ0004 alternative is a projected key"}
        dp_input_hashes = seen
    if len(branches) != 2 or not all(row["feasible_relaxation"] for row in branches):
        raise AssertionError("an all-17 request branch became infeasible")
    for branch in branches:
        if branch["conditional_upper_cents"] != sum(branch[field] for field in (
            "external_cents", "request_cents", "theta_constant_cents", "dp_cents",
        )):
            raise AssertionError("integer score components do not add up")
    branch_input_hashes = [sha256_json({
        "dp_input_sha256": dp_input_hashes[i],
        "external_cents": branch["external_cents"],
        "request_cents": branch["request_cents"],
        "theta_constant_cents": branch["theta_constant_cents"],
        "rq0004_tile": branch["rq0004_tile"],
    }) for i, branch in enumerate(branches)]
    return {
        "key_tiles": list(keys), "theta_uniform_cents": theta_cents,
        "all_awarded_upper_cents": max(
            branch["conditional_upper_cents"] for branch in branches),
        "branches": branches, "branch_sharing_audit": sharing,
        "dp_input_sha256": dp_input_hashes,
        "branch_input_sha256": branch_input_hashes,
        "case_input_sha256": sha256_json({
            "key_tiles": keys, "theta_uniform_cents": theta_cents,
            "branch_input_sha256": branch_input_hashes,
            "price_sha256": audited_price_sha,
            "base_certificate_sha256": base_certificate_sha,
        }),
        "base_certificate_sha256": base_certificate_sha,
        "price_sha256": audited_price_sha,
        "wall_seconds": time.monotonic() - started,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }


def validate_k18_result(result: dict, saved: dict) -> None:
    for field in (
        "key_tiles", "theta_uniform_cents", "all_awarded_upper_cents",
        "dp_input_sha256", "branch_input_sha256", "case_input_sha256",
        "price_sha256", "base_certificate_sha256",
    ):
        if result[field] != saved[field]:
            raise AssertionError(f"GPU K18 disagrees with saved pilot: {field}")
    for index, (actual, expected) in enumerate(zip(result["branches"],
                                                    saved["branches"], strict=True)):
        differences = {field: (actual[field], expected[field])
                       for field in COMPARE_FIELDS if actual[field] != expected[field]}
        if differences:
            raise AssertionError(f"GPU K18 branch {index} differs: {differences}")
    if (not result["branch_sharing_audit"]["second_dp_reused"]
            or result["branch_sharing_audit"]["first_dp_cents"]
            != saved["branch_sharing_audit"]["first_dp_cents"]):
        raise AssertionError("GPU K18 branch equality audit differs")


def compute_and_checkpoint(kind: str, tile: str | None, output: Path,
                           launch_mode: str, data: dict, audit: dict,
                           inputs: dict, keys: tuple[str, ...],
                           saved: dict, base_sha: str,
                           sixteen_upper_cents: int,
                           sixteen_certificate_sha: str) -> dict:
    started = time.monotonic()
    if kind == "baseline":
        case_keys = keys
        provenance = saved["base_certificate_sha256"]
    elif kind == "candidate":
        if tile is None or tile in keys or tile not in data["tile_ids"]:
            raise ValueError("tile must be one of the 46 remaining tiles")
        case_keys = keys + (tile,)
        provenance = base_sha
    else:
        raise ValueError("unknown worker kind")
    result = evaluate_case(data, inputs, case_keys, EXPECTED_THETA_CENTS,
                           audit["price_sha256"], provenance, launch_mode)
    if kind == "baseline":
        validate_k18_result(result, saved)
    result.update({
        "status": "completed", "kind": kind, "extra_tile": tile,
        "key_count": len(case_keys), "k18_pilot_sha256": base_sha,
        "unconditional_upper_cents": max(
            result["all_awarded_upper_cents"],
            sixteen_upper_cents),
        "at_most_sixteen_upper_cents": sixteen_upper_cents,
        "sixteen_request_certificate_sha256": sixteen_certificate_sha,
        "complete_arc_count": data["complete_arc_count"],
        "partial_arc_count": data["partial_arc_count"],
        "worker_wall_seconds": time.monotonic() - started,
        "source_sha256": source_hashes(), "launch_mode": launch_mode,
    })
    atomic_json(output, result)
    return result


def worker(kind: str, tile: str | None, output: Path, launch_mode: str) -> dict:
    keys, saved, base_sha = saved_base()
    data, audit = full._load_audited_data(full.PRICE_FILE)
    if (audit["price_sha256"] != saved["price_sha256"]
            or data["complete_arc_count"] != saved["complete_arc_count"]
            or data["partial_arc_count"] != saved["partial_arc_count"]):
        raise AssertionError("K18 audit price or action graph differs")
    sixteen_upper, sixteen_sha = checked_sixteen_bound(saved, audit, base_sha)
    inputs = full._instance_inputs(data)
    return compute_and_checkpoint(kind, tile, output, launch_mode,
                                  data, audit, inputs, keys, saved, base_sha,
                                  sixteen_upper, sixteen_sha)


def validate_checkpoint(path: Path, kind: str, tile: str | None,
                        manifest: dict, keys: tuple[str, ...]) -> dict:
    result = json.loads(path.read_text())
    expected_keys = list(keys if kind == "baseline" else keys + (tile,))
    if (result.get("status") != "completed" or result.get("kind") != kind
            or result.get("extra_tile") != tile
            or result.get("key_tiles") != expected_keys
            or result.get("key_count") != len(expected_keys)
            or result.get("k18_pilot_sha256") != manifest["k18_pilot_sha256"]
            or result.get("price_sha256") != manifest["price_sha256"]
            or result.get("sixteen_request_certificate_sha256")
            != manifest["sixteen_request_certificate_sha256"]
            or result.get("at_most_sixteen_upper_cents")
            != manifest["at_most_sixteen_upper_cents"]
            or result.get("source_sha256") != manifest["source_sha256"]
            or result.get("launch_mode") != manifest["launch_mode"]
            or result.get("base_certificate_sha256") != (
                manifest["k18_prior_base_sha256"] if kind == "baseline"
                else manifest["k18_pilot_sha256"])):
        raise AssertionError(f"stale or invalid checkpoint: {path}")
    branches = result.get("branches")
    if (not isinstance(branches, list) or len(branches) != 2
            or any(not branch.get("feasible_relaxation") for branch in branches)
            or result["all_awarded_upper_cents"] != max(
                branch["conditional_upper_cents"] for branch in branches)
            or result["unconditional_upper_cents"] != max(
                result["all_awarded_upper_cents"],
                manifest["at_most_sixteen_upper_cents"])):
        raise AssertionError(f"invalid bound in checkpoint: {path}")
    if kind == "baseline":
        _, saved, _ = saved_base()
        validate_k18_result(result, saved)
    return result


def manifest_for(saved: dict, base_sha: str, audit: dict,
                 launch_mode: str) -> dict:
    sixteen_upper, sixteen_sha = checked_sixteen_bound(saved, audit, base_sha)
    return {
        "scope": "public dev-reference; K18 plus one projected key; all request subsets",
        "k18_pilot_sha256": base_sha,
        "k18_prior_base_sha256": saved["base_certificate_sha256"],
        "base_keys": saved["key_tiles"],
        "price_sha256": audit["price_sha256"],
        "at_most_sixteen_upper_cents": sixteen_upper,
        "sixteen_request_certificate_sha256": sixteen_sha,
        "source_sha256": source_hashes(), "launch_mode": launch_mode,
    }


def run_subprocess(kind: str, tile: str | None, output: Path,
                   launch_mode: str, timeout_seconds: float | None) -> dict:
    command = [sys.executable, str(ROOT / "gpu_k19_extension_scan.py"),
               "_worker", "--kind", kind, "--out", str(output),
               "--launch-mode", launch_mode]
    if tile is not None:
        command.extend(("--tile", tile))
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
               NUMBA_NUM_THREADS="1", OMP_NUM_THREADS="1")
    started = time.monotonic()
    try:
        proc = subprocess.run(command, cwd=ROOT, env=env, text=True,
                              capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        return {"status": "timeout", "wall_seconds": time.monotonic() - started,
                "timeout_seconds": timeout_seconds,
                "stdout_tail": str(error.stdout or "")[-1000:],
                "stderr_tail": str(error.stderr or "")[-2000:]}
    if proc.returncode != 0 or not output.exists():
        return {"status": "failed", "return_code": proc.returncode,
                "wall_seconds": time.monotonic() - started,
                "stdout_tail": proc.stdout[-1000:],
                "stderr_tail": proc.stderr[-2500:]}
    return {"status": "completed", "wall_seconds": time.monotonic() - started}


def scan(mode: str, state_dir: Path, selected_arg: str | None,
         launch_mode: str, timeout_seconds: float | None,
         dry_run: bool) -> dict:
    keys, saved, base_sha = saved_base()
    data, audit = full._load_audited_data(full.PRICE_FILE)
    if (audit["price_sha256"] != saved["price_sha256"]
            or data["complete_arc_count"] != saved["complete_arc_count"]
            or data["partial_arc_count"] != saved["partial_arc_count"]):
        raise AssertionError("K18 saved price/action graph differs")
    remaining = candidate_order(keys, data, saved)
    if mode == "pilot":
        selected = remaining[:3]
    elif mode == "all":
        selected = remaining
    else:
        selected = tuple(tile.strip() for tile in selected_arg.split(","))
        if not selected or len(selected) != len(set(selected)) \
                or any(tile not in remaining for tile in selected):
            raise ValueError("--tiles must be distinct members of the 46 remaining tiles")
    manifest = manifest_for(saved, base_sha, audit, launch_mode)
    plan = {**manifest, "mode": mode, "candidate_tiles": list(selected),
            "candidate_count": len(selected), "timeout_seconds": timeout_seconds,
            "plan_sha256": sha256_json({**manifest, "candidate_tiles": selected})}
    if dry_run:
        return {"status": "dry_run", "candidate_tiles": list(selected),
                "candidate_count": len(selected), "k18_pilot_sha256": base_sha,
                "price_sha256": audit["price_sha256"],
                "plan_sha256": plan["plan_sha256"]}
    # Without a timeout, keep the audited graph and JIT-compiled CUDA kernel
    # in one process for the whole scan. An explicit timeout instead isolates
    # each case in a child process so the operating system can stop it.
    inputs = full._instance_inputs(data) if timeout_seconds is None else None
    state_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = state_dir / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise AssertionError("state directory belongs to different inputs or sources")
    else:
        atomic_json(manifest_path, manifest)
    atomic_json(state_dir / "plan.json", plan)
    started = time.monotonic()
    baseline_path = state_dir / "k18_baseline.json"
    if not baseline_path.exists():
        if inputs is None:
            outcome = run_subprocess("baseline", None, baseline_path,
                                     launch_mode, timeout_seconds)
        else:
            compute_and_checkpoint("baseline", None, baseline_path, launch_mode,
                                   data, audit, inputs, keys, saved, base_sha,
                                   manifest["at_most_sixteen_upper_cents"],
                                   manifest["sixteen_request_certificate_sha256"])
            outcome = {"status": "completed"}
        if outcome["status"] != "completed":
            status = {"status": "baseline_failed", "failure": outcome,
                      "completed_count": 0, "candidate_count": len(selected)}
            atomic_json(state_dir / "status.json", status)
            return status
    baseline = validate_checkpoint(baseline_path, "baseline", None, manifest, keys)
    print(json.dumps({"baseline_verified": True,
                      "k18_upper_cents": baseline["all_awarded_upper_cents"],
                      "k18_dp_seconds": baseline["branches"][0]["dp_wall_seconds"]}),
          flush=True)
    case_dir = state_dir / "cases"
    case_dir.mkdir(exist_ok=True)
    completed: dict[str, dict] = {}
    failures: dict[str, dict] = {}
    for tile in selected:
        path = case_dir / f"{tile}.json"
        if path.exists():
            completed[tile] = validate_checkpoint(path, "candidate", tile,
                                                  manifest, keys)
            continue
        if inputs is None:
            outcome = run_subprocess("candidate", tile, path,
                                     launch_mode, timeout_seconds)
        else:
            compute_and_checkpoint("candidate", tile, path, launch_mode,
                                   data, audit, inputs, keys, saved, base_sha,
                                   manifest["at_most_sixteen_upper_cents"],
                                   manifest["sixteen_request_certificate_sha256"])
            outcome = {"status": "completed"}
        if outcome["status"] == "completed":
            completed[tile] = validate_checkpoint(path, "candidate", tile,
                                                  manifest, keys)
            print(json.dumps({"tile": tile,
                              "upper_cents": completed[tile]["unconditional_upper_cents"],
                              "gpu_dp_seconds": [branch["dp_wall_seconds"]
                                                 for branch in completed[tile]["branches"]],
                              "done": len(completed), "total": len(selected)}),
                  flush=True)
        else:
            failures[tile] = outcome
            print(json.dumps({"tile": tile, "failure": outcome}), flush=True)
        write_status(state_dir, plan, completed, failures, started)
    return write_status(state_dir, plan, completed, failures, started)


def write_status(state_dir: Path, plan: dict, completed: dict[str, dict],
                 failures: dict[str, dict], started: float) -> dict:
    ranking = sorted(({
        "tile": tile, "all_awarded_upper_cents": row["all_awarded_upper_cents"],
        "unconditional_upper_cents": row["unconditional_upper_cents"],
        "branch_upper_cents": [branch["conditional_upper_cents"]
                               for branch in row["branches"]],
        "case_input_sha256": row["case_input_sha256"],
        "worker_wall_seconds": row["worker_wall_seconds"],
    } for tile, row in completed.items()),
        key=lambda row: (row["unconditional_upper_cents"], row["tile"]))
    status = {
        "status": "complete" if len(completed) == plan["candidate_count"] else "incomplete",
        "plan_sha256": plan["plan_sha256"],
        "baseline_verified": True, "completed_count": len(completed),
        "candidate_count": plan["candidate_count"],
        "failed_count": len(failures), "failures": failures,
        "best_completed_upper_cents": (
            ranking[0]["unconditional_upper_cents"] if ranking else None),
        "ranking": ranking, "elapsed_seconds": time.monotonic() - started,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(state_dir / "status.json", status)
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("pilot", "select", "all"):
        command = sub.add_parser(name)
        command.add_argument("--state-dir", type=Path, required=True)
        command.add_argument("--launch-mode", choices=("auto", "serial", "wave3"),
                             default="auto")
        command.add_argument("--timeout-seconds", type=float,
                             help="optional limit for each GPU process, including K18 baseline")
        command.add_argument("--dry-run", action="store_true")
        if name == "select":
            command.add_argument("--tiles", required=True,
                                 help="comma-separated distinct K19 candidate tiles")
    hidden = sub.add_parser("_worker", help=argparse.SUPPRESS)
    hidden.add_argument("--kind", choices=("baseline", "candidate"), required=True)
    hidden.add_argument("--tile")
    hidden.add_argument("--out", type=Path, required=True)
    hidden.add_argument("--launch-mode", choices=("auto", "serial", "wave3"),
                        default="auto")
    args = parser.parse_args()
    if args.command == "_worker":
        row = worker(args.kind, args.tile, args.out, args.launch_mode)
        print(json.dumps({"kind": args.kind, "tile": args.tile,
                          "upper_cents": row["unconditional_upper_cents"]}), flush=True)
        return
    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    row = scan(args.command, args.state_dir,
               getattr(args, "tiles", None), args.launch_mode,
               args.timeout_seconds, args.dry_run)
    print(json.dumps({key: row[key] for key in row if key in (
        "status", "candidate_count", "completed_count", "failed_count",
        "best_completed_upper_cents", "candidate_tiles", "plan_sha256",
    )}), flush=True)
    if row["status"] not in ("complete", "dry_run"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
