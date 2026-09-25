#!/usr/bin/env python3
"""Resumable K18 beam: extend three certified K17 seeds by every remaining tile."""

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
from parallel_key_extension_scan import (
    ROOT, atomic_json, calculate_case, certified_base, sha256_file,
    sha256_json, source_hashes, tail_text,
)


K17_AGG = ROOT / "results/practice_parallel_k17_all_candidates.json"
SEEDS = ("T00045", "T00001", "T00043")
EXPECTED_SEED_CENTS = (2130192, 2130226, 2130417)


def scan_sources() -> dict[str, str]:
    return {**source_hashes(),
            "parallel_k18_beam_scan.py": sha256_file(ROOT / "parallel_k18_beam_scan.py")}


def load_setup() -> tuple[tuple[str, ...], dict, str, dict, dict, dict]:
    base, _, base_sha = certified_base()
    agg = json.loads(K17_AGG.read_text())
    if (agg["base_keys"] != list(base)
            or agg["base_certificate_sha256"] != base_sha
            or agg["candidate_count"] != 48
            or agg["failed_count"] != 0
            or tuple(row["extra_tile"] for row in agg["rows"][:3]) != SEEDS
            or tuple(row["all_awarded_upper_cents"] for row in agg["rows"][:3])
            != EXPECTED_SEED_CENTS):
        raise AssertionError("certified K17 top-three seed aggregate changed")
    data, certs = full._load_audited_data(full.PRICE_FILE)
    if certs["price_sha256"] != agg["price_sha256"]:
        raise AssertionError("K17/K18 audited prices differ")
    inputs = full._instance_inputs(data)
    return base, agg, sha256_file(K17_AGG), data, inputs, certs


def all_jobs(base: tuple[str, ...], data: dict) -> list[dict]:
    remaining = tuple(tile for tile in data["tile_ids"] if tile not in base)
    if len(remaining) != 48 or any(seed not in remaining for seed in SEEDS):
        raise AssertionError("K16 complement changed")
    seen: set[frozenset[str]] = set()
    jobs: list[dict] = []
    for seed in SEEDS:
        for extra in remaining:
            if extra == seed:
                continue
            pair = frozenset((seed, extra))
            if pair in seen:
                continue
            seen.add(pair)
            name = "_".join(sorted(pair))
            jobs.append({"name": name, "seed": seed, "extra": extra,
                         "key_tiles": list(base + (seed, extra))})
    if len(jobs) != 138 or len(seen) != 138:
        raise AssertionError("K18 beam does not cover 138 unique unordered pairs")
    return jobs


def _profile_estimator(data: dict, inputs: dict):
    """Exact count of necessary-condition mask cells, for scheduling only."""
    n = data["n"]
    tile_to_index = {tile: i for i, tile in enumerate(data["tile_ids"])}
    arc_starts = inputs["arc_starts"]
    time_grid = np.arange(n, dtype=np.int32)
    cached_limits: dict[tuple[str, int], tuple[int, int]] = {}

    def limits(tile: str, deadline_unit: int) -> tuple[int, int]:
        cache_key = (tile, deadline_unit)
        if cache_key not in cached_limits:
            selected = ((data["complete_tile"] == tile_to_index[tile])
                        & (arc_starts < deadline_unit))
            if np.any(selected):
                cached_limits[cache_key] = (
                    int(np.min(data["complete_end"][selected])),
                    int(np.max(arc_starts[selected])),
                )
            else:
                cached_limits[cache_key] = (n + 1, -1)
        return cached_limits[cache_key]

    def one_branch(keys: tuple[str, ...], branch: int) -> int:
        deadlines = inputs["deadlines_by_branch"][branch]
        allowed = np.zeros(n, dtype=np.int8)
        forced = np.zeros(n, dtype=np.int8)
        incompatible = np.zeros(n, dtype=np.bool_)
        for tile in keys:
            deadline_unit = (int(np.searchsorted(inputs["instants"],
                                                 deadlines[tile], side="left"))
                             if tile in deadlines else n)
            first_end, last_start = limits(tile, deadline_unit)
            allowed += time_grid >= first_end
            if tile in deadlines:
                forced_here = time_grid > last_start
                forced += forced_here
                incompatible |= forced_here & (time_grid < first_end)
        valid_bits = allowed.astype(np.int16) - forced.astype(np.int16)
        valid_bits[incompatible] = 0
        cells = np.left_shift(np.int64(1), valid_bits.astype(np.int64))
        cells[incompatible] = 0
        return int(cells.sum())

    def estimate(keys: tuple[str, ...]) -> dict:
        branch0 = one_branch(keys, 0)
        if "T00004" in keys or "T00012" in keys:
            branch1 = one_branch(keys, 1)
            charged = branch0 + branch1
        else:
            branch1 = branch0
            charged = branch0
        return {"branch0_valid_cells": branch0,
                "branch1_valid_cells": branch1,
                "charged_valid_cells": charged,
                "full_cells_per_branch": n * (1 << len(keys))}

    return estimate


def worker(seed: str, extra: str, out: Path) -> dict:
    started = time.monotonic()
    base, agg, agg_sha, data, inputs, certs = load_setup()
    jobs = all_jobs(base, data)
    chosen = next((job for job in jobs if job["seed"] == seed
                   and job["extra"] == extra), None)
    if chosen is None:
        raise ValueError("pair is not in the deduplicated K18 beam")
    keys = tuple(chosen["key_tiles"])
    result = calculate_case(data, inputs, keys, 135, certs, agg_sha)
    estimate = _profile_estimator(data, inputs)(keys)
    result.update({
        "status": "completed", "name": chosen["name"],
        "seed": seed, "extra_tile": extra, "unordered_extra_tiles": sorted((seed, extra)),
        "key_count": 18, "k17_aggregate_sha256": agg_sha,
        "k16_certificate_sha256": agg["base_certificate_sha256"],
        "complete_arc_count": data["complete_arc_count"],
        "partial_arc_count": data["partial_arc_count"],
        "state_cell_estimate": estimate,
        "worker_wall_seconds": time.monotonic() - started,
        "source_sha256": scan_sources(),
    })
    atomic_json(out, result)
    return result


def scan(state_dir: Path, workers: int, per_job_timeout: int,
         deadline_seconds: int) -> dict:
    if not 1 <= workers <= 24:
        raise ValueError("workers must be 1..24")
    start = time.monotonic()
    base, agg, agg_sha, data, inputs, certs = load_setup()
    pilot_path = state_dir / "pilot_t45_t1.json"
    if not pilot_path.exists():
        raise AssertionError("K18 pilot must finish before beam scan")
    pilot = json.loads(pilot_path.read_text())
    if (pilot["status"] != "completed" or pilot["key_tiles"] != list(base + SEEDS[:2])
            or pilot["price_sha256"] != certs["price_sha256"]
            or pilot["k17_aggregate_sha256"] != agg_sha
            or not pilot["branch_sharing_audit"]["second_dp_reused"]):
        raise AssertionError("K18 pilot has not certified the new projection")
    jobs = all_jobs(base, data)
    estimate = _profile_estimator(data, inputs)
    for job in jobs:
        job["state_cell_estimate"] = estimate(tuple(job["key_tiles"]))
    jobs.sort(key=lambda job: (
        job["state_cell_estimate"]["charged_valid_cells"], job["name"],
    ))
    source_sha = scan_sources()
    plan = {
        "scope": "public dev-reference; K18 top-three K17 beam; all 17 requests",
        "base_keys": list(base), "seeds": list(SEEDS),
        "k17_aggregate_sha256": agg_sha,
        "k16_certificate_sha256": agg["base_certificate_sha256"],
        "price_sha256": certs["price_sha256"],
        "source_sha256": source_sha,
        "pilot_file_sha256": sha256_file(pilot_path),
        "workers": workers, "timeout_seconds_per_pair": per_job_timeout,
        "deadline_seconds": deadline_seconds,
        "jobs": jobs,
    }
    plan["plan_sha256"] = sha256_json({key: plan[key] for key in (
        "base_keys", "seeds", "k17_aggregate_sha256", "source_sha256", "jobs",
    )})
    atomic_json(state_dir / "plan.json", plan)
    case_dir = state_dir / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    completed: dict[str, dict] = {}
    for job in jobs:
        path = case_dir / f"{job['name']}.json"
        if not path.exists():
            continue
        row = json.loads(path.read_text())
        if (row.get("status") != "completed" or row.get("name") != job["name"]
                or row.get("key_tiles") != job["key_tiles"]
                or row.get("source_sha256") != source_sha
                or row.get("k17_aggregate_sha256") != agg_sha):
            raise AssertionError(f"stale or corrupt K18 checkpoint: {path}")
        completed[job["name"]] = row
    remaining = [job for job in jobs if job["name"] not in completed]
    deadline = time.monotonic() + deadline_seconds
    failures: dict[str, dict] = {}

    def run_one(job: dict) -> dict:
        left = deadline - time.monotonic()
        if left <= 1:
            return {"status": "not_started", "reason": "beam deadline elapsed"}
        limit = min(per_job_timeout, max(1, int(left)))
        path = case_dir / f"{job['name']}.json"
        command = [sys.executable, str(ROOT / "parallel_k18_beam_scan.py"),
                   "worker", "--seed", job["seed"], "--extra", job["extra"],
                   "--out", str(path)]
        env = dict(os.environ, OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
                   NUMBA_NUM_THREADS="1", OMP_NUM_THREADS="1")
        invoked = time.monotonic()
        try:
            proc = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                  capture_output=True, timeout=limit)
        except subprocess.TimeoutExpired as error:
            return {"status": "timeout", "limit_seconds": limit,
                    "wall_seconds": time.monotonic() - invoked,
                    "stdout_tail": tail_text(error.stdout, 1500),
                    "stderr_tail": tail_text(error.stderr, 2500)}
        if proc.returncode or not path.exists():
            return {"status": "failed", "return_code": proc.returncode,
                    "wall_seconds": time.monotonic() - invoked,
                    "stdout_tail": proc.stdout[-1500:], "stderr_tail": proc.stderr[-2500:]}
        result = json.loads(path.read_text())
        if result.get("name") != job["name"] or result.get("status") != "completed":
            return {"status": "failed", "reason": "invalid worker checkpoint"}
        return result

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run_one, job): job for job in remaining}
        for future in as_completed(futures):
            job = futures[future]
            try:
                row = future.result()
            except Exception as error:
                row = {"status": "failed", "exception": repr(error)}
            if row["status"] == "completed":
                completed[job["name"]] = row
                print(json.dumps({"pair": job["name"],
                                  "upper_cents": row["all_awarded_upper_cents"],
                                  "worker_wall_seconds": row["worker_wall_seconds"],
                                  "done": len(completed), "total": len(jobs)}), flush=True)
            else:
                failures[job["name"]] = row
                print(json.dumps({"pair": job["name"], "failure": row}), flush=True)
            atomic_json(state_dir / "status.json", {
                "status": "running", "plan_sha256": plan["plan_sha256"],
                "completed_count": len(completed), "candidate_count": len(jobs),
                "best_completed_upper_cents": min(
                    (case["all_awarded_upper_cents"] for case in completed.values()),
                    default=None),
                "failures": failures,
                "elapsed_seconds": time.monotonic() - start,
            })
    ranking = sorted(({
        "name": name, "all_awarded_upper_cents": row["all_awarded_upper_cents"],
        "branch_upper_cents": [branch["conditional_upper_cents"]
                               for branch in row["branches"]],
        "case_input_sha256": row["case_input_sha256"],
        "worker_wall_seconds": row["worker_wall_seconds"],
    } for name, row in completed.items()),
        key=lambda row: (row["all_awarded_upper_cents"], row["name"]))
    result = {
        "status": "complete" if len(completed) == len(jobs) else "incomplete",
        "plan_sha256": plan["plan_sha256"],
        "completed_count": len(completed), "candidate_count": len(jobs),
        "failed_count": len(failures), "failures": failures,
        "ranking": ranking,
        "best_completed_upper_cents": (
            ranking[0]["all_awarded_upper_cents"] if ranking else None),
        "elapsed_seconds": time.monotonic() - start,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(state_dir / "status.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    worker_p = sub.add_parser("worker")
    worker_p.add_argument("--seed", required=True)
    worker_p.add_argument("--extra", required=True)
    worker_p.add_argument("--out", type=Path, required=True)
    scan_p = sub.add_parser("scan")
    scan_p.add_argument("--state-dir", type=Path, required=True)
    scan_p.add_argument("--workers", type=int, default=24)
    scan_p.add_argument("--timeout-seconds", type=int, default=7200)
    scan_p.add_argument("--deadline-seconds", type=int, default=32400)
    args = parser.parse_args()
    if args.command == "worker":
        row = worker(args.seed, args.extra, args.out)
        print(json.dumps({"pair": row["name"],
                          "upper_cents": row["all_awarded_upper_cents"],
                          "case_input_sha256": row["case_input_sha256"]}), flush=True)
    else:
        row = scan(args.state_dir, args.workers, args.timeout_seconds,
                   args.deadline_seconds)
        print(json.dumps({"status": row["status"],
                          "completed_count": row["completed_count"],
                          "failed_count": row["failed_count"],
                          "best_completed_upper_cents": row["best_completed_upper_cents"]}),
              flush=True)
        if row["status"] != "complete":
            raise SystemExit(2)


if __name__ == "__main__":
    main()
