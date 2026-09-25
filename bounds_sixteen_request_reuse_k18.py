#!/usr/bin/env python3
"""Prove <=16 awarded requests below incumbent via byte-identical K18 DP inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import bounds_request_projection_k10 as projection
import bounds_sixteen_request_grouped_k13 as grouped
import bounds_sixteen_request_k10 as sixteen
from parallel_key_extension_scan import sha256_dp_args, sha256_json


ROOT = projection.ROOT
PRIOR_SIXTEEN = ROOT / "results" / "practice_sixteen_request_reuse_k16_round3.json"
PRIOR_FIFTEEN = ROOT / "results" / "practice_fifteen_request_reuse_k16_round3.json"
K18_PILOT = ROOT / "results" / "practice_k18_t45_t1_pilot.json"
K16_KEYS = ROOT / "results" / "practice_request_projection_k16_ring.json"
K17_AGGREGATE = ROOT / "results" / "practice_parallel_k17_all_candidates.json"
DEFAULT_OUT = ROOT / "results" / "practice_sixteen_request_reuse_k18.json"
REPLAY_FIELDS = (
    "conditional_upper_cents", "external_cents", "request_cents",
    "theta_constant_cents", "dp_cents", "required_key_mask",
    "mandatory_key_mask", "key_deadline_unit", "rq0004_tile",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _replay(data: dict, inputs: dict, keys: tuple[str, ...], theta: int,
            expected_dp_hash: str, dp_cents: int) -> tuple[dict, str]:
    captured = []

    def reuse_exact_input(*args):
        digest = sha256_dp_args(args)
        if digest != expected_dp_hash:
            raise AssertionError("the 16 DP arguments differ byte-for-byte")
        captured.append(digest)
        return dp_cents

    result = projection._conditional_bound(
        data, inputs, keys, theta, 0, dp_function=reuse_exact_input,
    )
    if not result["feasible_relaxation"] or captured != [expected_dp_hash]:
        raise AssertionError("certified K18 DP was not replayed exactly once")
    return result, captured[0]


def certify(prior16_path: Path, prior15_path: Path, pilot_path: Path,
            k16_path: Path, k17_aggregate_path: Path, prices_path: Path) -> dict:
    started = time.monotonic()
    old = json.loads(prior16_path.read_text())
    prior15 = json.loads(prior15_path.read_text())
    pilot = json.loads(pilot_path.read_text())
    k16 = json.loads(k16_path.read_text())
    data, audit = projection._load_audited_data(prices_path)
    choices, instants, arc_starts, _, _ = sixteen._certified_inputs(data)
    all_inputs = projection._instance_inputs(data)
    keys = tuple(pilot["key_tiles"])
    theta = int(pilot["theta_uniform_cents"])
    if (pilot["status"] != "completed"
            or len(keys) != 18 or len(set(keys)) != 18 or theta != 135
            or keys != tuple(k16["cases"][0]["keys"]) + ("T00045", "T00001")
            or pilot["extra_tiles"] != ["T00045", "T00001"]
            or pilot["base_certificate_sha256"] != _sha(k17_aggregate_path)
            or pilot["k16_certificate_sha256"] != _sha(k16_path)
            or pilot["k17_aggregate_sha256"] != _sha(k17_aggregate_path)
            or pilot["price_sha256"] != audit["price_sha256"]
            or old["capacity_price_sha256"] != audit["price_sha256"]
            or prior15["capacity_price_sha256"] != audit["price_sha256"]
            or pilot["complete_arc_count"] != data["complete_arc_count"]
            or pilot["partial_arc_count"] != data["partial_arc_count"]
            or len(pilot["branches"]) != 2
            or len(pilot["dp_input_sha256"]) != 2
            or len(pilot["branch_input_sha256"]) != 2):
        raise AssertionError("K18 pilot or prior certificates use different inputs")
    source_hashes_checked = {}
    for name, expected in pilot["source_sha256"].items():
        actual = _sha(ROOT / name)
        if actual != expected:
            raise AssertionError(f"published K18 source changed: {name}")
        source_hashes_checked[name] = actual

    # Replay all-17 pilot branches without running a DP.  The exact hash of
    # every scalar and every array byte in its 16-argument DP call is checked.
    all17_replay = []
    branch_input_hashes = []
    for branch, published in enumerate(pilot["branches"]):
        inputs = {**all_inputs,
                  "branches": [all_inputs["branches"][branch]],
                  "deadlines_by_branch": [all_inputs["deadlines_by_branch"][branch]]}
        raw, digest = _replay(
            data, inputs, keys, theta,
            pilot["dp_input_sha256"][branch], int(published["dp_cents"]),
        )
        for field in REPLAY_FIELDS:
            if raw[field] != published[field]:
                raise AssertionError(f"pilot all-17 branch {branch} differs in {field}")
        branch_hash = sha256_json({
            "dp_input_sha256": digest,
            "external_cents": raw["external_cents"],
            "request_cents": raw["request_cents"],
            "theta_constant_cents": raw["theta_constant_cents"],
            "rq0004_tile": raw["rq0004_tile"],
        })
        if branch_hash != pilot["branch_input_sha256"][branch]:
            raise AssertionError("published K18 branch-input hash differs")
        all17_replay.append({field: raw[field] for field in REPLAY_FIELDS})
        branch_input_hashes.append(branch_hash)
    case_hash = sha256_json({
        "key_tiles": keys, "theta_uniform_cents": theta,
        "branch_input_sha256": branch_input_hashes,
        "price_sha256": audit["price_sha256"],
        "base_certificate_sha256": _sha(k17_aggregate_path),
    })
    if (case_hash != pilot["case_input_sha256"]
            or pilot["dp_input_sha256"][0] != pilot["dp_input_sha256"][1]
            or pilot["branches"][0]["dp_cents"] != pilot["branches"][1]["dp_cents"]):
        raise AssertionError("all-17 K18 case hash or shared DP differs")

    rows = old["merged_branch_rows"]
    order = [request.request_id for request, _ in choices]
    expected_keys = {(rid, branch) for rid in order
                     for branch in ((0,) if rid == "RQ0004" else (0, 1))}
    old_by_key = {(r["missed_request"], r["rq0004_branch"]): r for r in rows}
    if (len(rows) != 33 or set(old_by_key) != expected_keys
            or max(r["merged_upper_cents"] for r in rows)
                != old["exactly_sixteen_upper_cents"]):
        raise AssertionError("prior exact-16 branch table incomplete")
    incumbent_micro = int(sixteen.INCUMBENT_SCORE_MICRO)
    targets = [r for r in rows if r["merged_upper_cents"] * 10000 > incumbent_micro]
    if (len(targets) != 2
            or {(r["missed_request"], r["rq0004_branch"]) for r in targets}
                != {("RQ0002", 0), ("RQ0002", 1)}):
        raise AssertionError("unexpected exact-16 branches above incumbent")
    refinements = {}
    for row in targets:
        missed, branch = row["missed_request"], row["rq0004_branch"]
        spec = grouped._branch_spec(data, choices, instants, missed, branch)
        inputs = {
            "branches": [spec["selected"]],
            "deadlines_by_branch": [spec["deadlines"]],
            "instants": instants,
            "arc_starts": arc_starts,
            "earliest_terminal_unit": spec["earliest_terminal_unit"],
        }
        raw, dp_hash = _replay(
            data, inputs, keys, theta, pilot["dp_input_sha256"][0],
            int(pilot["branches"][0]["dp_cents"]),
        )
        adjusted = (raw["conditional_upper_cents"]
                    - (int(data["request_cents"]) - spec["reward_cents"])
                    - spec["miss_cents"])
        explicit = (raw["external_cents"] + spec["reward_cents"]
                    + raw["theta_constant_cents"] + raw["dp_cents"]
                    - spec["miss_cents"])
        if adjusted != explicit:
            raise AssertionError("K18 per-branch integer account differs")
        key = (missed, branch)
        refinements[key] = {
            "missed_request": missed,
            "rq0004_branch": branch,
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "exact_dp_input_sha256": dp_hash,
            "external_cents": int(raw["external_cents"]),
            "selected_reward_cents": int(spec["reward_cents"]),
            "unavoidable_miss_cents": int(spec["miss_cents"]),
            "theta_constant_cents": int(raw["theta_constant_cents"]),
            "shared_dp_cents": int(raw["dp_cents"]),
            "k18_upper_cents": explicit,
            "merged_upper_cents": min(int(row["merged_upper_cents"]), explicit),
        }
    merged_rows = []
    for row in rows:
        key = (row["missed_request"], row["rq0004_branch"])
        new = refinements.get(key)
        merged_rows.append({
            "missed_request": key[0],
            "rq0004_branch": key[1],
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "k18_upper_cents": new["k18_upper_cents"] if new else None,
            "merged_upper_cents": new["merged_upper_cents"]
                                  if new else int(row["merged_upper_cents"]),
        })
    exact16 = max(r["merged_upper_cents"] for r in merged_rows)
    at_most15 = int(prior15["at_most_fifteen_upper_cents"])
    at_most16 = max(exact16, at_most15)
    if at_most16 * 10000 >= incumbent_micro:
        raise AssertionError("<=16 was not proved strictly below incumbent")
    return {
        "scope": "dev-reference; all valid traces with at most 16 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "prior_sixteen_certificate_sha256": _sha(prior16_path),
        "prior_fifteen_certificate_sha256": _sha(prior15_path),
        "k18_pilot_certificate_sha256": _sha(pilot_path),
        "k16_base_certificate_sha256": _sha(k16_path),
        "k17_aggregate_sha256": _sha(k17_aggregate_path),
        "source_sha256_checked": source_hashes_checked,
        "all_seventeen_replay": all17_replay,
        "case_input_sha256": case_hash,
        "shared_dp_input_sha256": pilot["dp_input_sha256"][0],
        "shared_dp_cents": int(pilot["branches"][0]["dp_cents"]),
        "fresh_dp_evaluations": 0,
        "incumbent_score_micro": incumbent_micro,
        "branch_count": len(merged_rows),
        "refined_branch_count": len(refinements),
        "refinements": list(refinements.values()),
        "merged_branch_rows": merged_rows,
        "exactly_sixteen_upper_cents": exact16,
        "at_most_fifteen_upper_cents": at_most15,
        "at_most_sixteen_upper_cents": at_most16,
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "All 33 exact-16 one-miss branches are matched against the "
            "signed prior table. Only two exceed the incumbent. For each "
            "one, every scalar, dtype, shape and array byte of the 16-argument "
            "K18 projected DP call hashes identically to the signed all-17 "
            "pilot; its certified DP integer is reused with no new solve. "
            "The full all-17 pilot account and input hashes are replayed. "
            "Per-branch non-key science and request reward/penalty are "
            "recomputed. The other 31 branches and <=15 certificate are "
            "strictly below incumbent."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-sixteen", type=Path, default=PRIOR_SIXTEEN)
    parser.add_argument("--prior-fifteen", type=Path, default=PRIOR_FIFTEEN)
    parser.add_argument("--k18-pilot", type=Path, default=K18_PILOT)
    parser.add_argument("--k16-keys", type=Path, default=K16_KEYS)
    parser.add_argument("--k17-aggregate", type=Path, default=K17_AGGREGATE)
    parser.add_argument("--prices", type=Path, default=projection.PRICE_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.prior_sixteen, args.prior_fifteen,
                     args.k18_pilot, args.k16_keys,
                     args.k17_aggregate, args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "refined_branch_count": result["refined_branch_count"],
        "exactly_sixteen_upper_cents": result["exactly_sixteen_upper_cents"],
        "at_most_sixteen_upper_cents": result["at_most_sixteen_upper_cents"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
