#!/usr/bin/env python3
"""Certify a stronger <=15 request bound by refining four exact-15 branches."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bounds_request_projection_k10 as projection13
import bounds_sixteen_request_k10 as sixteen10
from bounds_request_unconditional import _exact_cents, _request_is_excused_if_missed


ROOT = projection13.ROOT
DIAGNOSTIC = ROOT / "results" / "practice_fifteen_request_branch_analysis.json"
PRIOR_FIFTEEN = ROOT / "results" / "practice_global_k8_unconditional.json"
PRIOR_SIXTEEN = ROOT / "results" / "practice_sixteen_request_k13_targeted.json"
THIRTEEN = ROOT / "results" / "practice_request_projection_k13_pilot.json"
DEFAULT_OUT = ROOT / "results" / "practice_fifteen_request_k13_targeted.json"
KEYS = sixteen10.KEYS + ("T00016", "T00010", "T00047")
THETA_CENTS = 135
TARGET_CENTS = 2135000


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _branch_bound(data: dict, choices: list, instants: np.ndarray,
                  arc_starts: np.ndarray, missed_ids: tuple[str, str],
                  rq0004_branch: int, keys: tuple[str, ...], theta_cents: int) -> dict:
    scorer = data["scorer"]
    selected = {}
    reward_cents = 0
    latest_release = float("-inf")
    for request, options in choices:
        if request.request_id in missed_ids:
            continue
        option = rq0004_branch if request.request_id == "RQ0004" else 0
        selected[request.request_id] = tuple(options[option])
        reward_cents += _exact_cents(request.completion_reward)
        latest_release = max(latest_release, request.available_from_utc.timestamp())
    if len(selected) != 15 or latest_release == float("-inf"):
        raise AssertionError("not an exactly-15 request branch")
    if "RQ0004" not in selected:
        # The projection evaluator records this field; no first-tile witness
        # constraint is imposed when RQ0004 is not awarded.
        selected["RQ0004"] = ()
    deadlines = {}
    for request_id, tiles in selected.items():
        deadline = scorer.requests[request_id].deadline_utc.timestamp()
        for tile_id in tiles:
            deadlines[tile_id] = min(deadline, deadlines.get(tile_id, deadline))
    earliest_terminal_unit = int(np.searchsorted(instants, latest_release, side="left"))
    missed_request_cents = 0
    for request, _ in choices:
        if request.request_id not in missed_ids:
            continue
        if (request.deadline_utc.timestamp() <= latest_release
                and not _request_is_excused_if_missed(scorer, request)):
            missed_request_cents += _exact_cents(request.miss_penalty)
    raw = projection13._conditional_bound(
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
        raise AssertionError("targeted branch has no projected path")
    adjusted = (int(raw["conditional_upper_cents"])
                - (int(data["request_cents"]) - reward_cents)
                - missed_request_cents)
    return {
        "upper_cents": adjusted,
        "selected_request_reward_cents": reward_cents,
        "unavoidable_miss_cents": missed_request_cents,
        "earliest_terminal_unit": earliest_terminal_unit,
        "mandatory_tile_count": len(deadlines),
        "projected_dp": raw,
    }


def certify(diagnostic_path: Path, prior_fifteen_path: Path,
            prior_sixteen_path: Path, thirteen_path: Path,
            prices_path: Path) -> dict:
    started = time.monotonic()
    diagnostic = json.loads(diagnostic_path.read_text())
    prior = json.loads(prior_fifteen_path.read_text())
    prior16 = json.loads(prior_sixteen_path.read_text())
    thirteen = json.loads(thirteen_path.read_text())
    data, audit = projection13._load_audited_data(prices_path)
    choices, instants, arc_starts, subset, _ = sixteen10._certified_inputs(data)
    if (_sha(prior_fifteen_path) != diagnostic["old_exhaustive_subset_certificate_sha256"]
            or prior["capacity_price_sha256"] != audit["price_sha256"]
            or diagnostic["capacity_price_sha256"] != audit["price_sha256"]
            or diagnostic["keys"] != list(projection13.BASE_KEYS)
            or diagnostic["theta_uniform_cents"] != 140):
        raise AssertionError("diagnostic and audited eight-key inputs differ")
    if (prior16["capacity_price_sha256"] != audit["price_sha256"]
            or prior16["keys"] != list(KEYS)
            or prior16["theta_uniform_cents"] != THETA_CENTS
            or thirteen["certificates"]["price_sha256"] != audit["price_sha256"]
            or not any(case["keys"] == list(KEYS) for case in thirteen["cases"])):
        raise AssertionError("thirteen-key or previous sixteen-key certificate differs")
    if (diagnostic["exactly_fifteen_branch_count"] != 256
            or diagnostic["all_exactly_sixteen_cross_checked"] != 33
            or diagnostic["exactly_fifteen_upper_cents"] != 2140232):
        raise AssertionError("old exactly-15 analysis differs")
    rows = diagnostic["rows"]
    if (len(rows) != 256 or len({(r["request_mask"], r["rq0004_branch"])
                                  for r in rows}) != 256):
        raise AssertionError("diagnostic does not cover 256 unique branches")
    expected = sum(row["upper_cents"] > TARGET_CENTS for row in rows)
    if expected != 4:
        raise AssertionError("number of targeted branches changed")

    refined = []
    merged_rows = []
    for old in rows:
        old_cents = int(old["upper_cents"])
        adjusted = old_cents
        new = None
        if old_cents > TARGET_CENTS:
            missing = tuple(old["unawarded_request_ids"])
            new = _branch_bound(data, choices, instants, arc_starts, missing,
                                old["rq0004_branch"], KEYS, THETA_CENTS)
            if (new["selected_request_reward_cents"] != old["request_reward_cents"]
                    or new["unavoidable_miss_cents"] != old["unavoidable_miss_cents"]):
                raise AssertionError("branch request score terms differ")
            adjusted = min(old_cents, new["upper_cents"])
            # Under the old eight keys and theta=140, the new evaluator has
            # only *more* deadline and terminal restrictions than the old
            # unconditional eight-key subset envelope.
            cross = _branch_bound(
                data, choices, instants, arc_starts, missing,
                old["rq0004_branch"], projection13.BASE_KEYS, 140,
            )
            if cross["upper_cents"] > old_cents:
                raise AssertionError("eight-key conditional cross-check weakened old bound")
            refined.append({
                "unawarded_request_ids": list(missing),
                "rq0004_branch": old["rq0004_branch"],
                "old_eight_key_upper_cents": old_cents,
                "eight_key_conditional_cross_check_cents": cross["upper_cents"],
                "thirteen_key_refinement": new,
                "merged_upper_cents": adjusted,
            })
            print(json.dumps({
                "unawarded_request_ids": list(missing),
                "rq0004_branch": old["rq0004_branch"],
                "old_cents": old_cents,
                "thirteen_key_cents": new["upper_cents"],
                "elapsed_seconds": round(time.monotonic() - started, 1),
                "peak_rss_mib": projection13._rss_mib(),
            }), flush=True)
        merged_rows.append({
            "request_mask": old["request_mask"],
            "rq0004_branch": old["rq0004_branch"],
            "old_upper_cents": old_cents,
            "merged_upper_cents": adjusted,
        })
    exactly15 = max(row["merged_upper_cents"] for row in merged_rows)
    at_most14 = max(int(row["upper_cents"])
                    for row in prior["best_by_awarded_count"]
                    if row["awarded_count"] <= 14)
    at_most15 = max(at_most14, exactly15)
    exactly16 = int(prior16["exactly_sixteen_upper_cents"])
    at_most16 = max(at_most15, exactly16)
    if at_most15 > prior16["at_most_fifteen_upper_cents"]:
        raise AssertionError("new <=15 upper bound grew")
    return {
        "scope": "dev-reference; all valid traces with at most 16 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "old_eight_key_subset_certificate_sha256": _sha(prior_fifteen_path),
        "exactly_fifteen_diagnostic_sha256": _sha(diagnostic_path),
        "prior_sixteen_key_refinement_sha256": _sha(prior_sixteen_path),
        "all_seventeen_thirteen_key_certificate_sha256": _sha(thirteen_path),
        "keys": list(KEYS),
        "theta_uniform_cents": THETA_CENTS,
        "selection_threshold_cents": TARGET_CENTS,
        "old_exactly_fifteen_branch_count": len(rows),
        "refined_branch_count": len(refined),
        "refined_branches": refined,
        "merged_branch_rows": merged_rows,
        "at_most_fourteen_upper_cents": at_most14,
        "exactly_fifteen_upper_cents": exactly15,
        "at_most_fifteen_upper_cents": at_most15,
        "exactly_sixteen_upper_cents": exactly16,
        "at_most_sixteen_upper_cents": at_most16,
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection13._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "The published exhaustive K8 certificate covers all <=14 branches "
            "and the diagnostic enumerates all 256 exactly-15 branches. Only "
            "the four K8 bounds above 21,350 are reevaluated with audited K13 "
            "time DP. Every other branch keeps its K8 bound; each targeted "
            "branch takes the minimum of two valid upper bounds. The prior "
            "33-branch K13/K10 certificate covers exactly 16 separately."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostic", type=Path, default=DIAGNOSTIC)
    parser.add_argument("--prior-fifteen", type=Path, default=PRIOR_FIFTEEN)
    parser.add_argument("--prior-sixteen", type=Path, default=PRIOR_SIXTEEN)
    parser.add_argument("--thirteen", type=Path, default=THIRTEEN)
    parser.add_argument("--prices", type=Path, default=projection13.PRICE_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.diagnostic, args.prior_fifteen,
                     args.prior_sixteen, args.thirteen, args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "at_most_fourteen_upper_cents": result["at_most_fourteen_upper_cents"],
        "exactly_fifteen_upper_cents": result["exactly_fifteen_upper_cents"],
        "at_most_fifteen_upper_cents": result["at_most_fifteen_upper_cents"],
        "at_most_sixteen_upper_cents": result["at_most_sixteen_upper_cents"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
