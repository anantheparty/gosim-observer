#!/usr/bin/env python3
"""Certify every exactly-16-request branch with the audited ten-key time DP.

There are 17 potentially earnable requests.  If RQ0004 is earned, its two
minimum-tile choices give two branches; otherwise there is one.  Thus exactly
16 rewards give 16*2+1 = 33 branches.  The already audited exhaustive subset
certificate covers <=15 rewards independently, and the ten-key all-reward
certificate covers 17 rewards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bounds_request_projection_k10 as k10
from bounds_request_conditioned import ROOT, request_branches
from bounds_request_unconditional import _exact_cents, _request_is_excused_if_missed


SUBSET_CERT = ROOT / "results" / "practice_global_k8_unconditional.json"
ALL_REWARD_CERT = ROOT / "results" / "practice_request_projection_k10_scan.json"
DEFAULT_OUTPUT = ROOT / "results" / "practice_sixteen_request_k10.json"
KEYS = tuple(k10.BASE_KEYS) + ("T00048", "T00032")
INCUMBENT_SCORE_MICRO = 21119494551


def _certified_inputs(data: dict) -> tuple[list, np.ndarray, np.ndarray, dict, dict]:
    scorer = data["scorer"]
    choices = request_branches(scorer, data["impossible_requests"])
    requests = [request for request, _ in choices]
    request_ids = [request.request_id for request in requests]
    subset = json.loads(SUBSET_CERT.read_text())
    if request_ids != subset["request_ids_in_mask_order"]:
        raise AssertionError("request order differs from exhaustive subset certificate")
    if len(requests) != 17 or request_ids[3] != "RQ0004":
        raise AssertionError("unexpected request structure")
    if len(choices[3][1]) != 2 or any(len(options) != 1 for j, (_, options) in enumerate(choices) if j != 3):
        raise AssertionError("unexpected request option structure")
    for request in requests:
        if not request.issued_at_utc <= request.available_from_utc < request.deadline_utc:
            raise AssertionError("invalid request time order")
        if _exact_cents(request.completion_reward) < 0 or _exact_cents(request.miss_penalty) < 0:
            raise AssertionError("negative request coefficient")
        if _request_is_excused_if_missed(scorer, request) != subset["request_excused_if_missed"][request.request_id]:
            raise AssertionError("request miss excuse differs from exhaustive certificate")
    instants = np.fromiter(
        (slot.timestamp_utc.timestamp() + 150 * offset
         for slot in scorer.slots for offset in range(6)),
        dtype=np.float64, count=data["n"],
    )
    arc_starts = np.repeat(
        np.arange(data["n"], dtype=np.int32), np.diff(data["complete_ptr"]),
    )
    if len(arc_starts) != data["complete_arc_count"]:
        raise AssertionError("complete arc start map differs")
    return choices, instants, arc_starts, subset, {
        (row["missed_request"], row["rq0004_branch"]): row
        for row in subset["exactly_sixteen_awarded_cases"]
    }


def _one_branch(
    data: dict, choices: list, instants: np.ndarray, arc_starts: np.ndarray,
    missed_index: int, rq0004_branch: int, keys: tuple[str, ...], theta_cents: int,
    legacy_lookup: dict,
) -> dict:
    scorer = data["scorer"]
    missed_request = choices[missed_index][0]
    selected = {}
    latest_release = float("-inf")
    reward_cents = 0
    for j, (request, options) in enumerate(choices):
        if j == missed_index:
            continue
        option = rq0004_branch if j == 3 else 0
        selected[request.request_id] = tuple(options[option])
        latest_release = max(latest_release, request.available_from_utc.timestamp())
        reward_cents += _exact_cents(request.completion_reward)
    if missed_index == 3:
        # The imported all-reward evaluator emits this field but an unearned
        # RQ0004 imposes no tile requirements.
        selected["RQ0004"] = ()
    deadlines = {}
    for request_id, tiles in selected.items():
        deadline = scorer.requests[request_id].deadline_utc.timestamp()
        for tile_id in tiles:
            deadlines[tile_id] = min(deadline, deadlines.get(tile_id, deadline))
    earliest_terminal_unit = int(np.searchsorted(instants, latest_release, side="left"))
    miss_cents = (
        _exact_cents(missed_request.miss_penalty)
        if missed_request.deadline_utc.timestamp() <= latest_release
        and not _request_is_excused_if_missed(scorer, missed_request)
        else 0
    )
    raw = k10._conditional_bound(
        data,
        {
            "branches": [selected],
            "deadlines_by_branch": [deadlines],
            "instants": instants,
            "arc_starts": arc_starts,
            "earliest_terminal_unit": earliest_terminal_unit,
        },
        keys, theta_cents, 0,
    )
    if not raw["feasible_relaxation"]:
        return {
            "missed_request": missed_request.request_id,
            "rq0004_branch": rq0004_branch,
            "feasible_relaxation": False,
            "reason": raw,
        }
    # _conditional_bound adds all 17 potential reward cents; remove exactly
    # the unearned request reward, then the unavoidable miss penalty.
    full_reward_cents = int(data["request_cents"])
    if reward_cents != full_reward_cents - _exact_cents(missed_request.completion_reward):
        raise AssertionError("request reward sum changed")
    adjusted = int(raw["conditional_upper_cents"]) - (full_reward_cents - reward_cents) - miss_cents
    old = legacy_lookup[(missed_request.request_id, rq0004_branch)]
    if theta_cents == 140 and keys == tuple(k10.BASE_KEYS):
        # Same prices/theta, with additional exact selected-key deadlines and
        # latest-release terminal rule, so this DP must be no looser.
        if adjusted > old["adjusted_upper_cents"]:
            raise AssertionError("eight-key cross-check exceeds legacy subset bound")
    return {
        "missed_request": missed_request.request_id,
        "rq0004_branch": rq0004_branch,
        "rq0004_tile": None if missed_index == 3 else list(choices[3][1][rq0004_branch]),
        "feasible_relaxation": True,
        "selected_request_reward_cents": reward_cents,
        "unavoidable_miss_cents": miss_cents,
        "earliest_terminal_unit": earliest_terminal_unit,
        "mandatory_tile_count": len(deadlines),
        "mandatory_key_mask": raw["mandatory_key_mask"],
        "required_key_mask": raw["required_key_mask"],
        "key_deadline_unit": raw["key_deadline_unit"],
        "external_cents": raw["external_cents"],
        "projected_dp_cents": raw["dp_cents"],
        "theta_constant_cents": raw["theta_constant_cents"],
        "upper_cents": adjusted,
        "legacy_eight_key_upper_cents": old["adjusted_upper_cents"],
        "dp_wall_seconds": raw["dp_wall_seconds"],
    }


def certify(prices_path: Path, keys: tuple[str, ...], theta_cents: int, cross_check_eight: bool) -> dict:
    started = time.monotonic()
    if len(keys) != 10 or len(set(keys)) != 10 or theta_cents < 0:
        raise ValueError("ten distinct keys and nonnegative theta required")
    data, audit = k10._load_audited_data(prices_path)
    choices, instants, arc_starts, subset, legacy_lookup = _certified_inputs(data)
    all_reward = json.loads(ALL_REWARD_CERT.read_text())
    if all_reward["certificates"]["price_sha256"] != audit["price_sha256"]:
        raise AssertionError("all-reward certificate uses different prices")
    all_reward_rows = [row for row in all_reward["tested"] if tuple(row["keys"]) == keys and row["theta_uniform_cents"] == theta_cents]
    if len(all_reward_rows) != 1:
        raise AssertionError("selected ten-key all-reward result is not certified")
    all_reward_cents = int(all_reward_rows[0]["all_awarded_upper_cents"])
    if len(legacy_lookup) != 33:
        raise AssertionError("legacy exhaustive certificate did not list 33 branches")
    rows = []
    checks = []
    for missed_index in range(17):
        branches = (0,) if missed_index == 3 else (0, 1)
        for branch in branches:
            row = _one_branch(data, choices, instants, arc_starts, missed_index, branch,
                              keys, theta_cents, legacy_lookup)
            rows.append(row)
            print(json.dumps({"missing": row["missed_request"], "branch": branch,
                              "upper_cents": row.get("upper_cents"),
                              "elapsed_seconds": round(time.monotonic() - started, 1)}), flush=True)
            if cross_check_eight and (missed_index, branch) in ((1, 0), (3, 0), (16, 1)):
                check = _one_branch(data, choices, instants, arc_starts, missed_index, branch,
                                    tuple(k10.BASE_KEYS), 140, legacy_lookup)
                checks.append({"missing": check["missed_request"], "branch": branch,
                               "eight_key_upper_cents": check["upper_cents"],
                               "legacy_eight_key_upper_cents": check["legacy_eight_key_upper_cents"]})
    if len(rows) != 33 or len({(r["missed_request"], r["rq0004_branch"]) for r in rows}) != 33:
        raise AssertionError("exactly-16 branch coverage failed")
    feasible = [r for r in rows if r["feasible_relaxation"]]
    exactly_sixteen_max = max(r["upper_cents"] for r in feasible)
    at_most_fifteen_max = max(int(r["upper_cents"]) for r in subset["best_by_awarded_count"] if r["awarded_count"] <= 15)
    overall = max(at_most_fifteen_max, exactly_sixteen_max, all_reward_cents)
    return {
        "scope": "public dev-reference, unconditional over all valid decision traces",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "legacy_subset_certificate_sha256": hashlib.sha256(SUBSET_CERT.read_bytes()).hexdigest(),
        "all_reward_ten_key_certificate_sha256": hashlib.sha256(ALL_REWARD_CERT.read_bytes()).hexdigest(),
        "keys": list(keys), "theta_uniform_cents": theta_cents,
        "exactly_sixteen_branch_count": len(rows),
        "exactly_sixteen_rows": rows,
        "eight_key_cross_checks": checks,
        "at_most_fifteen_upper_cents": at_most_fifteen_max,
        "exactly_sixteen_upper_cents": exactly_sixteen_max,
        "all_seventeen_upper_cents": all_reward_cents,
        "unconditional_upper_cents": overall,
        "incumbent_score_micro": INCUMBENT_SCORE_MICRO,
        "incumbent_gap_micro": overall * 10000 - INCUMBENT_SCORE_MICRO,
        "runtime_seconds": time.monotonic() - started,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": "Exhausts 33 exactly-16 request branches. Each uses the audited nonnegative capacity prices, scorer-complete arcs, 10-key first-visit time DP with mandatory key deadlines and earliest selected request release terminal, and independent non-key reduced first-science envelopes. Missing reward is removed and scorer-unavoidable miss penalty subtracted. <=15 and 17 reward cases are covered by independently cited certificates.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path, default=k10.PRICE_FILE)
    parser.add_argument("--theta-cents", type=int, default=135)
    parser.add_argument("--keys", default=",".join(KEYS))
    parser.add_argument("--no-eight-check", action="store_true")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = certify(args.prices, tuple(args.keys.split(",")), args.theta_cents,
                     not args.no_eight_check)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"upper": result["unconditional_upper_cents"] / 100,
                      "exactly_sixteen": result["exactly_sixteen_upper_cents"] / 100,
                      "runtime_seconds": result["runtime_seconds"]}, sort_keys=True))


if __name__ == "__main__":
    main()
