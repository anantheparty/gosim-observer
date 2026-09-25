#!/usr/bin/env python3
"""Validate all atomic K17 scan checkpoints and emit a compact certificate."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


BRANCH_FIELDS = (
    "rq0004_tile", "conditional_upper_cents", "external_cents",
    "request_cents", "theta_constant_cents", "dp_cents",
    "required_key_mask", "mandatory_key_mask", "key_deadline_unit",
)


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     ensure_ascii=False, separators=(",", ":")
                                     ).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--best-out", type=Path, required=True)
    args = parser.parse_args()

    status = json.loads(args.status.read_text())
    plan = json.loads(args.plan.read_text())
    verification = json.loads(args.verification.read_text())
    expected_tiles = tuple(plan["candidate_tiles"])
    if (status["status"] != "complete" or status["completed_count"] != len(expected_tiles)
            or status["candidate_count"] != len(expected_tiles) or status["failures"]
            or len(expected_tiles) != 48 or len(set(expected_tiles)) != 48):
        raise AssertionError("the 48-tile scan is incomplete or has failures")
    if status["plan_sha256"] != plan["plan_sha256"]:
        raise AssertionError("status belongs to a different scan plan")
    derived_plan_sha = digest_json({key: plan[key] for key in (
        "base_keys", "candidate_tiles", "base_certificate_sha256", "source_sha256",
    )})
    if derived_plan_sha != plan["plan_sha256"]:
        raise AssertionError("scan plan hash mismatch")
    if (verification["status"] != "passed"
            or verification["source_sha256"] != plan["source_sha256"]
            or verification["base_certificate_sha256"] != plan["base_certificate_sha256"]
            or plan["verification_sha256"] != digest_json(verification)):
        raise AssertionError("scan plan and preflight verification differ")
    if [row["all_awarded_upper_cents"] for row in verification["rows"]] != [
        2141516, 2137159, 2133124,
    ]:
        raise AssertionError("K14/K15/K16 preflight integer values changed")

    rows = []
    for tile in expected_tiles:
        path = args.cases / f"{tile}.json"
        case = json.loads(path.read_text())
        if (case["status"] != "completed" or case["extra_tile"] != tile
                or case["key_tiles"] != plan["base_keys"] + [tile]
                or case["theta_uniform_cents"] != 135
                or case["base_certificate_sha256"] != plan["base_certificate_sha256"]
                or case["price_sha256"] != verification["price_sha256"]
                or case["source_sha256"] != plan["source_sha256"]
                or case["complete_arc_count"] != 918757
                or case["partial_arc_count"] != 850):
            raise AssertionError(f"case metadata changed: {tile}")
        if len(case["branches"]) != 2 or len(case["dp_input_sha256"]) != 2:
            raise AssertionError(f"branch count changed: {tile}")
        compact_branches = []
        for branch_index, branch in enumerate(case["branches"]):
            if not branch["feasible_relaxation"]:
                raise AssertionError(f"infeasible branch: {tile}")
            if branch["conditional_upper_cents"] != sum(branch[field] for field in (
                "external_cents", "request_cents", "theta_constant_cents", "dp_cents",
            )):
                raise AssertionError(f"integer components do not add up: {tile}")
            expected_branch_hash = digest_json({
                "dp_input_sha256": case["dp_input_sha256"][branch_index],
                "external_cents": branch["external_cents"],
                "request_cents": branch["request_cents"],
                "theta_constant_cents": branch["theta_constant_cents"],
                "rq0004_tile": branch["rq0004_tile"],
            })
            if case["branch_input_sha256"][branch_index] != expected_branch_hash:
                raise AssertionError(f"branch input hash changed: {tile}")
            compact_branches.append({field: branch[field] for field in BRANCH_FIELDS})
        expected_case_hash = digest_json({
            "key_tiles": tuple(case["key_tiles"]),
            "theta_uniform_cents": case["theta_uniform_cents"],
            "branch_input_sha256": case["branch_input_sha256"],
            "price_sha256": case["price_sha256"],
            "base_certificate_sha256": case["base_certificate_sha256"],
        })
        if case["case_input_sha256"] != expected_case_hash:
            raise AssertionError(f"case input hash changed: {tile}")
        if case["all_awarded_upper_cents"] != max(
                branch["conditional_upper_cents"] for branch in case["branches"]):
            raise AssertionError(f"branch maximum changed: {tile}")
        if tile in ("T00004", "T00012"):
            if case["branch_sharing_audit"]["second_dp_reused"]:
                raise AssertionError(f"RQ0004 branch illegally shared: {tile}")
        elif (not case["branch_sharing_audit"]["second_dp_reused"]
              or case["dp_input_sha256"][0] != case["dp_input_sha256"][1]):
            raise AssertionError(f"equivalent branches not audited: {tile}")
        rows.append({
            "extra_tile": tile,
            "all_awarded_upper_cents": case["all_awarded_upper_cents"],
            "branches": compact_branches,
            "branch_sharing_audit": case["branch_sharing_audit"],
            "dp_input_sha256": case["dp_input_sha256"],
            "branch_input_sha256": case["branch_input_sha256"],
            "case_input_sha256": case["case_input_sha256"],
            "case_file_sha256": digest_file(path),
            "worker_wall_seconds": case["worker_wall_seconds"],
            "peak_rss_mib": case["peak_rss_mib"],
        })

    rows.sort(key=lambda row: (row["all_awarded_upper_cents"], row["extra_tile"]))
    if (status["best_completed_upper_cents"] != rows[0]["all_awarded_upper_cents"]
            or [(row["tile"], row["all_awarded_upper_cents"], row["case_input_sha256"])
                for row in status["ranking"]]
            != [(row["extra_tile"], row["all_awarded_upper_cents"],
                 row["case_input_sha256"]) for row in rows]):
        raise AssertionError("status ranking differs from case files")

    best_path = args.cases / f"{rows[0]['extra_tile']}.json"
    if digest_file(best_path) != rows[0]["case_file_sha256"]:
        raise AssertionError("best case changed during aggregation")
    args.best_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(best_path, args.best_out)
    payload = {
        "scope": "public dev-reference; all 17 request rewards; 48 K17 one-key extensions",
        "base_keys": plan["base_keys"],
        "candidate_count": len(rows), "failed_count": 0,
        "price_sha256": verification["price_sha256"],
        "base_certificate_sha256": plan["base_certificate_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "plan_file_sha256": digest_file(args.plan),
        "verification_file_sha256": digest_file(args.verification),
        "input_manifest_file_sha256": digest_file(args.input_manifest),
        "source_sha256": plan["source_sha256"],
        "best_extra_tile": rows[0]["extra_tile"],
        "all_awarded_upper_cents": rows[0]["all_awarded_upper_cents"],
        "best_case_file_sha256": rows[0]["case_file_sha256"],
        "best_case_output_file": str(args.best_out),
        "rows": rows,
        "sum_worker_wall_seconds": sum(row["worker_wall_seconds"] for row in rows),
        "scan_elapsed_seconds": status["elapsed_seconds"],
        "proof_note": (
            "All 48 candidates use the audited complete graph, price file and "
            "K16 key set. Each row is a strict all-17 request upper bound. "
            "The minimum of these independent valid bounds is also valid. "
            "Cases with an RQ0004 alternative as a key compute both branches; "
            "the others reuse a DP root only after every DP input is checked. "
            "Request counts below 17 require separate subset certificates."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                   sort_keys=True) + "\n")
    print(json.dumps({
        "cases": len(rows), "best_tile": rows[0]["extra_tile"],
        "all_awarded_upper_cents": rows[0]["all_awarded_upper_cents"],
        "aggregate_sha256": digest_file(args.out),
        "best_case_sha256": digest_file(args.best_out),
    }))


if __name__ == "__main__":
    main()
