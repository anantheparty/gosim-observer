#!/usr/bin/env python3
"""Audited parallel scan of every one-tile extension of the certified K16 set.

Each worker rebuilds the audited public instance and saves one atomic JSON
result.  The coordinator can resume after interruption.  All scores are
integer cents; a failed or timed-out worker never contributes a bound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bounds_request_projection_k10 as full
from projection_branch_merge import two_equivalent_branches
from projection_ring_state_pruning import conditional_projected_dp_pruned


ROOT = Path(__file__).resolve().parent
K14_CERT = ROOT / "results/practice_request_projection_k14_pilot.json"
K15_CERT = ROOT / "results/practice_request_projection_k15_ring.json"
K16_CERT = ROOT / "results/practice_request_projection_k16_ring.json"
CERT_EXPECTED_CENTS = {14: 2141516, 15: 2137159, 16: 2133124}
COMPARE_FIELDS = (
    "conditional_upper_cents", "external_cents", "request_cents",
    "theta_constant_cents", "dp_cents", "required_key_mask",
    "mandatory_key_mask", "key_deadline_unit", "rq0004_tile",
)
SOURCE_FILES = (
    "parallel_key_extension_scan.py", "projection_branch_merge.py",
    "projection_ring_state_pruning.py", "bounds_request_projection_ring.py",
    "bounds_request_projection_k10.py", "bounds_practice_projection.py",
    "bounds_request_conditioned.py", "challenge/scoring_core.py",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_json(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def sha256_dp_args(args: tuple) -> str:
    """Hash every scalar and byte of the exact 16-argument DP invocation."""
    h = hashlib.sha256()
    for index, value in enumerate(args):
        h.update(index.to_bytes(2, "little"))
        if isinstance(value, np.ndarray):
            h.update(b"array\0")
            h.update(value.dtype.str.encode() + b"\0")
            h.update(json.dumps(value.shape).encode() + b"\0")
            h.update(value.tobytes(order="C"))
        else:
            h.update(b"scalar\0")
            h.update(str(int(value)).encode() + b"\0")
    return h.hexdigest()


def certified_base() -> tuple[tuple[str, ...], dict, str]:
    cert = json.loads(K16_CERT.read_text())
    keys = tuple(cert["cases"][0]["keys"])
    if (len(keys) != 16 or len(set(keys)) != 16
            or tuple(cert["base_keys"]) != keys[:-1]
            or cert["all_awarded_upper_cents"] != CERT_EXPECTED_CENTS[16]
            or cert["theta_uniform_cents"] != 135):
        raise AssertionError("published K16 starting certificate changed")
    return keys, cert, sha256_file(K16_CERT)


def source_hashes() -> dict[str, str]:
    return {name: sha256_file(ROOT / name) for name in SOURCE_FILES}


def calculate_case(data: dict, inputs: dict, keys: tuple[str, ...],
                   theta_cents: int, certs: dict, base_cert_sha: str) -> dict:
    seen: list[str] = []

    def hash_and_compute(*args):
        seen.append(sha256_dp_args(args))
        return conditional_projected_dp_pruned(*args)

    started = time.monotonic()
    if "T00004" not in keys and "T00012" not in keys:
        branches, sharing = two_equivalent_branches(
            data, inputs, keys, theta_cents, hash_and_compute,
        )
        if len(seen) != 1 or not sharing["second_dp_reused"]:
            raise AssertionError("equivalent branch DP was not audited once")
        dp_input_hashes = [seen[0], seen[0]]
    else:
        branches = [full._conditional_bound(
            data, inputs, keys, theta_cents, branch_index,
            dp_function=hash_and_compute,
        ) for branch_index in range(2)]
        if len(seen) != 2:
            raise AssertionError("different branch projections were not computed twice")
        sharing = {"second_dp_reused": False,
                   "reason": "one RQ0004 alternative is a projected key"}
        dp_input_hashes = seen
    if not all(row["feasible_relaxation"] for row in branches):
        raise AssertionError("an all-17 request branch became infeasible")
    for row in branches:
        if row["conditional_upper_cents"] != sum(row[field] for field in (
            "external_cents", "request_cents", "theta_constant_cents", "dp_cents",
        )):
            raise AssertionError("integer score components do not add up")
    branch_input_hashes = [sha256_json({
        "dp_input_sha256": dp_input_hashes[i],
        "external_cents": row["external_cents"],
        "request_cents": row["request_cents"],
        "theta_constant_cents": row["theta_constant_cents"],
        "rq0004_tile": row["rq0004_tile"],
    }) for i, row in enumerate(branches)]
    return {
        "key_tiles": list(keys), "theta_uniform_cents": theta_cents,
        "all_awarded_upper_cents": max(row["conditional_upper_cents"] for row in branches),
        "branches": branches, "branch_sharing_audit": sharing,
        "dp_input_sha256": dp_input_hashes,
        "branch_input_sha256": branch_input_hashes,
        "case_input_sha256": sha256_json({
            "key_tiles": keys, "theta_uniform_cents": theta_cents,
            "branch_input_sha256": branch_input_hashes,
            "price_sha256": certs["price_sha256"],
            "base_certificate_sha256": base_cert_sha,
        }),
        "base_certificate_sha256": base_cert_sha,
        "price_sha256": certs["price_sha256"],
        "wall_seconds": time.monotonic() - started,
        "peak_rss_mib": full._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }


def find_certified_case(cert: dict, keys: tuple[str, ...]) -> dict:
    for candidate in cert["cases"]:
        if tuple(candidate["keys"]) == keys:
            return candidate
    raise AssertionError(f"published K{len(keys)} certificate lacks {keys}")


def verify(state_dir: Path | None = None) -> dict:
    base, cert16, base_sha = certified_base()
    data, certs = full._load_audited_data(full.PRICE_FILE)
    inputs = full._instance_inputs(data)
    if cert16["certificates"]["price_sha256"] != certs["price_sha256"]:
        raise AssertionError("K16 price hash differs from current audited graph")
    certificates = {
        14: json.loads(K14_CERT.read_text()),
        15: json.loads(K15_CERT.read_text()),
        16: cert16,
    }
    rows = []
    for k in (14, 15, 16):
        keys = base[:k]
        saved = find_certified_case(certificates[k], keys)
        result = calculate_case(data, inputs, keys, 135, certs, base_sha)
        if result["all_awarded_upper_cents"] != CERT_EXPECTED_CENTS[k]:
            raise AssertionError(f"K{k} total differs from saved integer certificate")
        for index in range(2):
            actual = {field: result["branches"][index][field]
                      for field in COMPARE_FIELDS}
            expected = {field: saved["branches"][index][field]
                        for field in COMPARE_FIELDS}
            if actual != expected:
                raise AssertionError(f"K{k} branch {index} differs from saved certificate")
        rows.append({
            "k": k, "keys": list(keys),
            "branches_upper_cents": [row["conditional_upper_cents"]
                                     for row in result["branches"]],
            "all_awarded_upper_cents": result["all_awarded_upper_cents"],
            "case_input_sha256": result["case_input_sha256"],
            "dp_input_sha256": result["dp_input_sha256"],
            "wall_seconds": result["wall_seconds"],
        })
        print(json.dumps({"verify_k": k,
                          "all_awarded_upper_cents": result["all_awarded_upper_cents"],
                          "wall_seconds": result["wall_seconds"]}), flush=True)
    audit = {
        "status": "passed", "price_sha256": certs["price_sha256"],
        "base_certificate_sha256": base_sha,
        "reference_certificates_sha256": {
            "K14": sha256_file(K14_CERT), "K15": sha256_file(K15_CERT),
            "K16": base_sha,
        },
        "source_sha256": source_hashes(),
        "rows": rows, "completed_utc": datetime.now(timezone.utc).isoformat(),
    }
    if state_dir is not None:
        atomic_json(state_dir / "verification.json", audit)
    return audit


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                    sort_keys=True) + "\n")
    temporary.replace(path)


def tail_text(value: str | bytes | None, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    return value[-limit:]


def worker(tile: str, output: Path) -> dict:
    started = time.monotonic()
    base, cert16, base_sha = certified_base()
    data, certs = full._load_audited_data(full.PRICE_FILE)
    if tile in base or tile not in data["tile_ids"]:
        raise ValueError(f"not a remaining tile: {tile}")
    if certs["price_sha256"] != cert16["certificates"]["price_sha256"]:
        raise AssertionError("audited price hash changed")
    inputs = full._instance_inputs(data)
    result = calculate_case(data, inputs, base + (tile,), 135, certs, base_sha)
    result.update({
        "status": "completed", "extra_tile": tile,
        "complete_arc_count": data["complete_arc_count"],
        "partial_arc_count": data["partial_arc_count"],
        "worker_wall_seconds": time.monotonic() - started,
        "source_sha256": source_hashes(),
    })
    atomic_json(output, result)
    return result


def scan(state_dir: Path, workers: int, timeout_seconds: int,
         deadline_seconds: int, candidates: tuple[str, ...] | None) -> dict:
    if workers < 1 or workers > 40:
        raise ValueError("workers must be in 1..40")
    state_dir.mkdir(parents=True, exist_ok=True)
    audit = verify(state_dir)
    base, _, base_sha = certified_base()
    data, _ = full._load_audited_data(full.PRICE_FILE)
    all_candidates = tuple(tile for tile in data["tile_ids"] if tile not in base)
    selected = candidates or all_candidates
    if len(set(selected)) != len(selected) or any(tile not in all_candidates
                                                  for tile in selected):
        raise ValueError("candidate list contains duplicate or base/unknown tile")
    plan = {
        "scope": "public dev-reference; one-tile K16 extensions; all 17 requests",
        "base_keys": list(base), "candidate_tiles": list(selected),
        "base_certificate_sha256": base_sha,
        "verification_sha256": sha256_json(audit),
        "source_sha256": source_hashes(),
        "workers": workers, "timeout_seconds_per_tile": timeout_seconds,
        "deadline_seconds": deadline_seconds,
    }
    plan_sha = sha256_json({key: plan[key] for key in (
        "base_keys", "candidate_tiles", "base_certificate_sha256", "source_sha256",
    )})
    plan["plan_sha256"] = plan_sha
    atomic_json(state_dir / "plan.json", plan)
    case_dir = state_dir / "cases"
    case_dir.mkdir(exist_ok=True)
    completed = {}
    for tile in selected:
        path = case_dir / f"{tile}.json"
        if path.exists():
            row = json.loads(path.read_text())
            if (row.get("extra_tile") == tile and row.get("status") == "completed"
                    and row.get("base_certificate_sha256") == base_sha
                    and row.get("source_sha256") == plan["source_sha256"]):
                completed[tile] = row
            else:
                raise AssertionError(f"stale or corrupt checkpoint: {path}")
    remaining = [tile for tile in selected if tile not in completed]
    failures: dict[str, dict] = {}
    start = time.monotonic()
    deadline = start + deadline_seconds

    def run_one(tile: str) -> dict:
        left = deadline - time.monotonic()
        if left <= 1:
            return {"status": "not_started", "reason": "scan deadline elapsed"}
        limit = min(timeout_seconds, max(1, int(left)))
        output = case_dir / f"{tile}.json"
        env = dict(os.environ, OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
                   NUMBA_NUM_THREADS="1", OMP_NUM_THREADS="1")
        command = [sys.executable, str(ROOT / "parallel_key_extension_scan.py"),
                   "worker", "--tile", tile, "--out", str(output)]
        invoked = time.monotonic()
        try:
            proc = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                  capture_output=True, timeout=limit)
        except subprocess.TimeoutExpired as error:
            return {"status": "timeout", "limit_seconds": limit,
                    "wall_seconds": time.monotonic() - invoked,
                    "stdout_tail": tail_text(error.stdout, 1500),
                    "stderr_tail": tail_text(error.stderr, 1500)}
        if proc.returncode != 0 or not output.exists():
            return {"status": "failed", "return_code": proc.returncode,
                    "wall_seconds": time.monotonic() - invoked,
                    "stdout_tail": proc.stdout[-1500:], "stderr_tail": proc.stderr[-2500:]}
        result = json.loads(output.read_text())
        if result.get("extra_tile") != tile or result.get("status") != "completed":
            return {"status": "failed", "reason": "worker checkpoint invalid"}
        return result

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run_one, tile): tile for tile in remaining}
        for future in as_completed(futures):
            tile = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = {"status": "failed", "exception": repr(error)}
            if result["status"] == "completed":
                completed[tile] = result
                print(json.dumps({"tile": tile, "upper_cents": result["all_awarded_upper_cents"],
                                  "worker_wall_seconds": result["worker_wall_seconds"],
                                  "done": len(completed), "total": len(selected)}), flush=True)
            else:
                failures[tile] = result
                print(json.dumps({"tile": tile, "failure": result}), flush=True)
            summary = {
                "status": "running", "plan_sha256": plan_sha,
                "completed_count": len(completed), "candidate_count": len(selected),
                "failures": failures,
                "best_completed_upper_cents": min(
                    (row["all_awarded_upper_cents"] for row in completed.values()),
                    default=None),
                "elapsed_seconds": time.monotonic() - start,
            }
            atomic_json(state_dir / "status.json", summary)
    ranking = sorted(({
        "tile": tile, "all_awarded_upper_cents": row["all_awarded_upper_cents"],
        "branch_upper_cents": [branch["conditional_upper_cents"]
                               for branch in row["branches"]],
        "case_input_sha256": row["case_input_sha256"],
        "worker_wall_seconds": row["worker_wall_seconds"],
    } for tile, row in completed.items()),
        key=lambda row: (row["all_awarded_upper_cents"], row["tile"]))
    summary = {
        "status": "complete" if len(completed) == len(selected) else "incomplete",
        "plan_sha256": plan_sha,
        "completed_count": len(completed), "candidate_count": len(selected),
        "failed_count": len(failures), "failures": failures,
        "ranking": ranking, "best_completed_upper_cents": (
            ranking[0]["all_awarded_upper_cents"] if ranking else None),
        "elapsed_seconds": time.monotonic() - start,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(state_dir / "status.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify_p = sub.add_parser("verify", help="compare K14/K15/K16 integer certificates")
    verify_p.add_argument("--state-dir", type=Path)
    worker_p = sub.add_parser("worker", help="compute one candidate with an atomic checkpoint")
    worker_p.add_argument("--tile", required=True)
    worker_p.add_argument("--out", type=Path, required=True)
    scan_p = sub.add_parser("scan", help="verify, run all extensions, and resume checkpoints")
    scan_p.add_argument("--state-dir", type=Path, required=True)
    scan_p.add_argument("--workers", type=int, default=24)
    scan_p.add_argument("--timeout-seconds", type=int, default=7200)
    scan_p.add_argument("--deadline-seconds", type=int, default=28800)
    scan_p.add_argument("--candidates", help="optional comma-separated pilot subset")
    args = parser.parse_args()
    if args.command == "verify":
        result = verify(args.state_dir)
        print(json.dumps({"status": result["status"], "rows": len(result["rows"])}))
    elif args.command == "worker":
        result = worker(args.tile, args.out)
        print(json.dumps({"tile": args.tile,
                          "upper_cents": result["all_awarded_upper_cents"],
                          "case_input_sha256": result["case_input_sha256"]}))
    else:
        candidates = tuple(args.candidates.split(",")) if args.candidates else None
        result = scan(args.state_dir, args.workers, args.timeout_seconds,
                      args.deadline_seconds, candidates)
        print(json.dumps({"status": result["status"],
                          "best_completed_upper_cents": result["best_completed_upper_cents"],
                          "completed_count": result["completed_count"],
                          "failed_count": result["failed_count"]}), flush=True)
        if result["status"] != "complete":
            raise SystemExit(2)


if __name__ == "__main__":
    main()
