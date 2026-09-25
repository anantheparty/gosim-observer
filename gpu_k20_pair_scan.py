#!/usr/bin/env python3
"""Resumable exhaustive CUDA K20 pair extension of the certified K18 bound.

The 1,035 unordered pairs of the 46 tiles outside the saved K18 key set are
scanned in one process so the audited graph and CUDA JIT stay resident. Each
completed pair has an atomic checkpoint. Only fully validated cases may enter
the best-bound summary. This proves upper bounds; it does not produce a plan.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from datetime import datetime, timezone
from pathlib import Path

# Importing the GPU module first installs the Windows-only ``resource`` shim.
from gpu_projection_dp import conditional_projected_dp_cuda  # noqa: F401

import bounds_request_projection_k10 as full
import gpu_k19_extension_scan as k19
from parallel_key_extension_scan import COMPARE_FIELDS, ROOT, atomic_json, sha256_file, sha256_json


K19_DIR = ROOT / "results/gpu_k19_scan_20260926"
K19_BEST_TILE = "T00009"
K19_BEST_UPPER_CENTS = 2_127_024
K20_KEY_COUNT = 20
PAIR_COUNT = 1_035
PILOT_PAIRS = (
    ("T00009", "T00052"),
    ("T00009", "T00008"),
    ("T00052", "T00008"),
    ("T00009", "T00004"),
    ("T00009", "T00012"),
)
SOURCE_FILES = (
    "gpu_k20_pair_scan.py", *k19.SOURCE_FILES,
)


def source_hashes() -> dict[str, str]:
    return {name: sha256_file(ROOT / name) for name in SOURCE_FILES}


def pair_key(pair: tuple[str, str]) -> str:
    if len(pair) != 2 or pair[0] >= pair[1]:
        raise ValueError(f"pair must be distinct and sorted: {pair}")
    return "_".join(pair)


def ordered_pairs(remaining: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """First test the promising K19 keys, then exhaust every other pair."""
    universe = {tuple(sorted(pair)) for pair in itertools.combinations(remaining, 2)}
    if len(remaining) != 46 or len(universe) != PAIR_COUNT:
        raise AssertionError("K18 complement is not the expected 46 tiles")
    pilot = tuple(tuple(sorted(pair)) for pair in PILOT_PAIRS)
    if len(set(pilot)) != len(pilot) or not set(pilot) <= universe:
        raise AssertionError("pilot pairs do not belong to the K18 complement")
    ranking = {tile: i for i, tile in enumerate(remaining)}
    priority = {"T00009", "T00052", "T00008"}
    rest = sorted(universe - set(pilot), key=lambda pair: (
        -len(set(pair) & priority),
        min(ranking[pair[0]], ranking[pair[1]]),
        max(ranking[pair[0]], ranking[pair[1]]),
        pair,
    ))
    return pilot + tuple(rest)


def audited_inputs() -> tuple[tuple[str, ...], dict, str, dict, dict, dict,
                              tuple[str, ...], int, str, dict, str]:
    """Check every saved K19 case and the independent <=16-request proof."""
    keys, saved, base_sha = k19.saved_base()
    data, audit = full._load_audited_data(full.PRICE_FILE)
    if (audit["price_sha256"] != saved["price_sha256"]
            or data["complete_arc_count"] != saved["complete_arc_count"]
            or data["partial_arc_count"] != saved["partial_arc_count"]):
        raise AssertionError("K18 price/action graph differs from audited source")
    sixteen_upper, sixteen_sha = k19.checked_sixteen_bound(saved, audit, base_sha)
    remaining = k19.candidate_order(keys, data, saved)
    saved_manifest_path = K19_DIR / "manifest.json"
    saved_status_path = K19_DIR / "status.json"
    saved_best_path = K19_DIR / "cases" / f"{K19_BEST_TILE}.json"
    saved_manifest = json.loads(saved_manifest_path.read_text())
    saved_status = json.loads(saved_status_path.read_text())
    if saved_manifest != k19.manifest_for(saved, base_sha, audit, "auto"):
        raise AssertionError("saved K19 manifest/source hash differs")
    if (saved_status["status"] != "complete"
            or saved_status["candidate_count"] != len(remaining)
            or saved_status["completed_count"] != len(remaining)
            or saved_status["failed_count"] != 0
            or saved_status["best_completed_upper_cents"] != K19_BEST_UPPER_CENTS):
        raise AssertionError("saved K19 scan is incomplete or changed")
    bounds = []
    for tile in remaining:
        case = k19.validate_checkpoint(K19_DIR / "cases" / f"{tile}.json",
                                       "candidate", tile, saved_manifest, keys)
        bounds.append(case["unconditional_upper_cents"])
    if min(bounds) != K19_BEST_UPPER_CENTS:
        raise AssertionError("K19 case minimum differs from saved status")
    best = json.loads(saved_best_path.read_text())
    if (best["extra_tile"] != K19_BEST_TILE
            or best["unconditional_upper_cents"] != K19_BEST_UPPER_CENTS):
        raise AssertionError("saved K19 best-case checkpoint differs")
    inputs = full._instance_inputs(data)
    saved_hashes = {
        "k19_manifest_sha256": sha256_file(saved_manifest_path),
        "k19_status_sha256": sha256_file(saved_status_path),
        "k19_best_case_sha256": sha256_file(saved_best_path),
    }
    return (keys, saved, base_sha, data, audit, inputs, remaining,
            sixteen_upper, sixteen_sha, best, saved_hashes)


def validate_k19_replay(result: dict, saved_best: dict) -> None:
    for field in (
        "key_tiles", "theta_uniform_cents", "all_awarded_upper_cents",
        "dp_input_sha256", "branch_input_sha256", "case_input_sha256",
        "price_sha256", "base_certificate_sha256",
    ):
        if result[field] != saved_best[field]:
            raise AssertionError(f"GPU K19 replay differs from saved case: {field}")
    for i, (actual, expected) in enumerate(zip(result["branches"],
                                               saved_best["branches"], strict=True)):
        differences = {name: (actual[name], expected[name]) for name in COMPARE_FIELDS
                       if actual[name] != expected[name]}
        if differences:
            raise AssertionError(f"GPU K19 branch {i} differs: {differences}")
    if result["branch_sharing_audit"]["second_dp_reused"] != \
            saved_best["branch_sharing_audit"]["second_dp_reused"]:
        raise AssertionError("GPU K19 branch-sharing audit differs")


def manifest_for(base_sha: str, audit: dict, keys: tuple[str, ...],
                 remaining: tuple[str, ...], sixteen_upper: int,
                 sixteen_sha: str, saved_hashes: dict, launch_mode: str) -> dict:
    return {
        "scope": "public dev-reference; K18 plus every unordered pair; all request subsets",
        "base_keys": list(keys), "remaining_tiles": list(remaining),
        "candidate_count": PAIR_COUNT, "k20_key_count": K20_KEY_COUNT,
        "theta_uniform_cents": k19.EXPECTED_THETA_CENTS,
        "k18_pilot_sha256": base_sha,
        "k19_best_upper_cents": K19_BEST_UPPER_CENTS,
        **saved_hashes,
        "price_sha256": audit["price_sha256"],
        "at_most_sixteen_upper_cents": sixteen_upper,
        "sixteen_request_certificate_sha256": sixteen_sha,
        "source_sha256": source_hashes(), "launch_mode": launch_mode,
    }


def validate_baseline(row: dict, kind: str, manifest: dict,
                      saved_k18: dict, saved_k19: dict) -> None:
    if (row["status"] != "completed" or row["kind"] != kind
            or row["source_sha256"] != manifest["source_sha256"]
            or row["launch_mode"] != manifest["launch_mode"]):
        raise AssertionError(f"stale K{kind} GPU baseline")
    if kind == "18":
        k19.validate_k18_result(row, saved_k18)
    else:
        validate_k19_replay(row, saved_k19)


def validate_case(path: Path, pair: tuple[str, str], manifest: dict) -> dict:
    row = json.loads(path.read_text())
    expected_keys = manifest["base_keys"] + list(pair)
    if (row.get("status") != "completed" or row.get("pair") != list(pair)
            or row.get("key_tiles") != expected_keys
            or row.get("key_count") != K20_KEY_COUNT
            or row.get("theta_uniform_cents") != manifest["theta_uniform_cents"]
            or row.get("price_sha256") != manifest["price_sha256"]
            or row.get("base_certificate_sha256") != manifest["k18_pilot_sha256"]
            or row.get("at_most_sixteen_upper_cents")
            != manifest["at_most_sixteen_upper_cents"]
            or row.get("sixteen_request_certificate_sha256")
            != manifest["sixteen_request_certificate_sha256"]
            or row.get("source_sha256") != manifest["source_sha256"]
            or row.get("launch_mode") != manifest["launch_mode"]):
        raise AssertionError(f"stale or invalid K20 checkpoint: {path}")
    branches = row.get("branches")
    if (not isinstance(branches, list) or len(branches) != 2
            or any(not branch.get("feasible_relaxation") for branch in branches)
            or row["all_awarded_upper_cents"]
            != max(branch["conditional_upper_cents"] for branch in branches)
            or row["unconditional_upper_cents"]
            != max(row["all_awarded_upper_cents"],
                   manifest["at_most_sixteen_upper_cents"])):
        raise AssertionError(f"invalid bound in K20 checkpoint: {path}")
    for branch in branches:
        if branch["conditional_upper_cents"] != sum(branch[field] for field in (
            "external_cents", "request_cents", "theta_constant_cents", "dp_cents",
        )):
            raise AssertionError(f"invalid branch decomposition: {path}")
    dp_hashes = row.get("dp_input_sha256")
    branch_hashes = row.get("branch_input_sha256")
    if (not isinstance(dp_hashes, list) or len(dp_hashes) != 2
            or not isinstance(branch_hashes, list) or len(branch_hashes) != 2):
        raise AssertionError(f"missing exact input hashes: {path}")
    for i, branch in enumerate(branches):
        expected = sha256_json({
            "dp_input_sha256": dp_hashes[i],
            "external_cents": branch["external_cents"],
            "request_cents": branch["request_cents"],
            "theta_constant_cents": branch["theta_constant_cents"],
            "rq0004_tile": branch["rq0004_tile"],
        })
        if branch_hashes[i] != expected:
            raise AssertionError(f"branch input hash differs: {path}")
    if row["case_input_sha256"] != sha256_json({
        "key_tiles": expected_keys,
        "theta_uniform_cents": manifest["theta_uniform_cents"],
        "branch_input_sha256": branch_hashes,
        "price_sha256": manifest["price_sha256"],
        "base_certificate_sha256": manifest["k18_pilot_sha256"],
    }):
        raise AssertionError(f"case input hash differs: {path}")
    shared = not bool(set(pair) & {"T00004", "T00012"})
    if (row["branch_sharing_audit"]["second_dp_reused"] != shared
            or (shared and dp_hashes[0] != dp_hashes[1])):
        raise AssertionError(f"request branch-sharing audit differs: {path}")
    return row


def write_status(state_dir: Path, plan: dict, completed: dict[str, dict],
                 failures: dict[str, str], started: float) -> dict:
    ranking = sorted(({
        "pair": list(row["pair"]),
        "upper_cents": row["unconditional_upper_cents"],
        "branch_upper_cents": [b["conditional_upper_cents"] for b in row["branches"]],
        "case_input_sha256": row["case_input_sha256"],
        "gpu_dp_seconds": [b["dp_wall_seconds"] for b in row["branches"]],
    } for row in completed.values()),
        key=lambda row: (row["upper_cents"], row["pair"]))
    status = {
        "status": "complete" if len(completed) == plan["candidate_count"] else "incomplete",
        "plan_sha256": plan["plan_sha256"], "baselines_verified": True,
        "completed_count": len(completed), "candidate_count": plan["candidate_count"],
        "failed_count": len(failures), "failures": failures,
        "best_completed_upper_cents": ranking[0]["upper_cents"] if ranking else None,
        "best_completed_pair": ranking[0]["pair"] if ranking else None,
        "top_20": ranking[:20], "elapsed_seconds": time.monotonic() - started,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(state_dir / "status.json", status)
    return status


def scan(mode: str, state_dir: Path, selected_arg: str | None,
         launch_mode: str, dry_run: bool) -> dict:
    (keys, saved, base_sha, data, audit, inputs, remaining, sixteen_upper,
     sixteen_sha, saved_best, saved_hashes) = audited_inputs()
    ordered = ordered_pairs(remaining)
    if mode == "pilot":
        selected = ordered[:len(PILOT_PAIRS)]
    elif mode == "all":
        selected = ordered
    else:
        tokens = [token.strip() for token in selected_arg.split(",")]
        try:
            selected = tuple(tuple(sorted(token.split("+"))) for token in tokens)
        except AttributeError as error:
            raise ValueError("--pairs syntax: T00009+T00052,T00004+T00009") from error
        universe = set(ordered)
        if (not selected or len(selected) != len(set(selected))
                or any(len(pair) != 2 or pair not in universe for pair in selected)):
            raise ValueError("--pairs must list distinct unordered pairs of remaining tiles")
    manifest = manifest_for(base_sha, audit, keys, remaining, sixteen_upper,
                            sixteen_sha, saved_hashes, launch_mode)
    plan = {
        "mode": mode, "candidate_pairs": [list(pair) for pair in selected],
        "candidate_count": len(selected),
        "plan_sha256": sha256_json({
            "manifest": manifest, "candidate_pairs": selected,
        }),
    }
    if dry_run:
        return {"status": "dry_run", "candidate_count": len(selected),
                "pilot_pairs": [list(pair) for pair in ordered[:len(PILOT_PAIRS)]],
                "plan_sha256": plan["plan_sha256"]}
    state_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = state_dir / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise AssertionError("state directory belongs to different inputs or source code")
    else:
        atomic_json(manifest_path, manifest)
    atomic_json(state_dir / "plan.json", plan)
    started = time.monotonic()
    for kind, baseline_keys, filename in (
        ("18", keys, "k18_gpu_baseline.json"),
        ("19", keys + (K19_BEST_TILE,), "k19_gpu_best_replay.json"),
    ):
        path = state_dir / filename
        if not path.exists():
            result = k19.evaluate_case(data, inputs, baseline_keys,
                                       k19.EXPECTED_THETA_CENTS,
                                       audit["price_sha256"],
                                       saved["base_certificate_sha256"] if kind == "18"
                                       else base_sha, launch_mode)
            result.update({"status": "completed", "kind": kind,
                           "source_sha256": manifest["source_sha256"],
                           "launch_mode": launch_mode})
            validate_baseline(result, kind, manifest, saved, saved_best)
            atomic_json(path, result)
        else:
            validate_baseline(json.loads(path.read_text()), kind, manifest,
                              saved, saved_best)
        print(json.dumps({"gpu_replay_k": int(kind), "verified": True}), flush=True)
    case_dir = state_dir / "cases"
    case_dir.mkdir(exist_ok=True)
    completed: dict[str, dict] = {}
    failures: dict[str, str] = {}
    for pair in selected:
        name = pair_key(pair)
        path = case_dir / f"{name}.json"
        if path.exists():
            completed[name] = validate_case(path, pair, manifest)
            continue
        try:
            row = k19.evaluate_case(data, inputs, keys + pair,
                                    k19.EXPECTED_THETA_CENTS,
                                    audit["price_sha256"], base_sha,
                                    launch_mode)
            row.update({
                "status": "completed", "pair": list(pair),
                "key_count": K20_KEY_COUNT,
                "unconditional_upper_cents": max(row["all_awarded_upper_cents"],
                                                 sixteen_upper),
                "at_most_sixteen_upper_cents": sixteen_upper,
                "sixteen_request_certificate_sha256": sixteen_sha,
                "source_sha256": manifest["source_sha256"],
                "launch_mode": launch_mode,
            })
            atomic_json(path, row)
            completed[name] = validate_case(path, pair, manifest)
        except Exception as error:
            failures[name] = f"{type(error).__name__}: {error}"
            write_status(state_dir, plan, completed, failures, started)
            raise
        status = write_status(state_dir, plan, completed, failures, started)
        print(json.dumps({
            "pair": list(pair), "done": status["completed_count"],
            "total": status["candidate_count"],
            "upper_cents": row["unconditional_upper_cents"],
            "best_upper_cents": status["best_completed_upper_cents"],
            "gpu_dp_seconds": [branch["dp_wall_seconds"] for branch in row["branches"]],
        }), flush=True)
    return write_status(state_dir, plan, completed, failures, started)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("pilot", "select", "all"):
        command = sub.add_parser(name)
        command.add_argument("--state-dir", type=Path, required=True)
        command.add_argument("--launch-mode", choices=("auto", "serial", "wave3"),
                             default="auto")
        command.add_argument("--dry-run", action="store_true")
        if name == "select":
            command.add_argument("--pairs", required=True,
                                 help="comma-separated pairs, e.g. T00009+T00052")
    args = parser.parse_args()
    result = scan(args.command, args.state_dir,
                  getattr(args, "pairs", None), args.launch_mode, args.dry_run)
    print(json.dumps({key: result[key] for key in (
        "status", "candidate_count", "completed_count", "best_completed_upper_cents",
        "best_completed_pair", "plan_sha256", "pilot_pairs",
    ) if key in result}), flush=True)


if __name__ == "__main__":
    main()
