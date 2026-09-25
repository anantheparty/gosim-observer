#!/usr/bin/env python3
"""Refine only the unresolved exactly-16 request branches with 13 keys.

The older ten-key certificate enumerates all 33 exactly-16 branches.  Its
branches at or below the certified <=15-request ceiling need no further work:
their bounds cannot decide the maximum over <=16 requests.  For every other
branch, recompute the conditional scorer relaxation with the audited 13-key
time DP, then take the smaller of the two valid branch bounds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import bounds_request_projection_k10 as projection13
import bounds_sixteen_request_k10 as sixteen10


ROOT = projection13.ROOT
TEN_CERT = ROOT / "results" / "practice_sixteen_request_k10.json"
THIRTEEN_CERT = ROOT / "results" / "practice_request_projection_k13_pilot.json"
DEFAULT_OUT = ROOT / "results" / "practice_sixteen_request_k13_targeted.json"
KEYS = sixteen10.KEYS + ("T00016", "T00010", "T00047")
THETA_CENTS = 135


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certify(ten_path: Path, thirteen_path: Path, prices_path: Path) -> dict:
    started = time.monotonic()
    ten = json.loads(ten_path.read_text())
    thirteen = json.loads(thirteen_path.read_text())
    data, audit = projection13._load_audited_data(prices_path)
    choices, instants, arc_starts, subset, legacy_lookup = sixteen10._certified_inputs(data)

    if ten["capacity_price_sha256"] != audit["price_sha256"]:
        raise AssertionError("ten-key certificate uses different capacity prices")
    if ten["keys"] != list(KEYS[:10]) or ten["theta_uniform_cents"] != THETA_CENTS:
        raise AssertionError("ten-key branch model differs")
    if ten["legacy_subset_certificate_sha256"] != _sha(sixteen10.SUBSET_CERT):
        raise AssertionError("legacy subset certificate changed")
    if len(ten["exactly_sixteen_rows"]) != 33 or ten["exactly_sixteen_branch_count"] != 33:
        raise AssertionError("ten-key 33-branch certificate is incomplete")
    if len(KEYS) != 13 or len(set(KEYS)) != 13:
        raise AssertionError("13-key projection is malformed")
    if (thirteen["certificates"]["price_sha256"] != audit["price_sha256"]
            or thirteen["theta_uniform_cents"] != THETA_CENTS):
        raise AssertionError("thirteen-key all-request certificate differs")
    thirteen_cases = [case for case in thirteen["cases"] if case["keys"] == list(KEYS)]
    if len(thirteen_cases) != 1:
        raise AssertionError("chosen 13-key branch was not evaluated")
    all_seventeen_cents = int(thirteen_cases[0]["all_awarded_upper_cents"])
    if all_seventeen_cents != max(int(branch["conditional_upper_cents"])
                                   for branch in thirteen_cases[0]["branches"]):
        raise AssertionError("all-request maximum differs from its branches")

    at_most_fifteen = max(int(row["upper_cents"])
                          for row in subset["best_by_awarded_count"]
                          if row["awarded_count"] <= 15)
    if at_most_fifteen != int(ten["at_most_fifteen_upper_cents"]):
        raise AssertionError("<=15 request ceiling changed")

    order = [request.request_id for request, _ in choices]
    lookup = {(row["missed_request"], row["rq0004_branch"]): row
              for row in ten["exactly_sixteen_rows"]}
    expected = {(request_id, branch)
                for request_id in order
                for branch in ((0,) if request_id == "RQ0004" else (0, 1))}
    if set(lookup) != expected:
        raise AssertionError("ten-key certificate does not cover all 33 branches")

    rows = []
    for missed_request, branch in sorted(expected):
        old = lookup[(missed_request, branch)]
        if not old["feasible_relaxation"]:
            raise AssertionError("older certificate unexpectedly infeasible")
        old_cents = int(old["upper_cents"])
        refined = None
        merged = old_cents
        if old_cents > at_most_fifteen:
            refined = sixteen10._one_branch(
                data, choices, instants, arc_starts, order.index(missed_request),
                branch, KEYS, THETA_CENTS, legacy_lookup,
            )
            if not refined["feasible_relaxation"]:
                raise AssertionError("new projected branch unexpectedly infeasible")
            new_cents = int(refined["upper_cents"])
            merged = min(old_cents, new_cents)
            if refined["selected_request_reward_cents"] != old["selected_request_reward_cents"]:
                raise AssertionError("awarded request reward differs")
            if refined["unavoidable_miss_cents"] != old["unavoidable_miss_cents"]:
                raise AssertionError("missing request penalty differs")
            if refined["earliest_terminal_unit"] != old["earliest_terminal_unit"]:
                raise AssertionError("terminal release differs")
            if refined["mandatory_tile_count"] != old["mandatory_tile_count"]:
                raise AssertionError("selected request witness differs")
            print(json.dumps({
                "missed_request": missed_request,
                "rq0004_branch": branch,
                "old_cents": old_cents,
                "thirteen_key_cents": new_cents,
                "merged_cents": merged,
                "elapsed_seconds": round(time.monotonic() - started, 1),
                "peak_rss_mib": projection13._rss_mib(),
            }), flush=True)
        rows.append({
            "missed_request": missed_request,
            "rq0004_branch": branch,
            "ten_key_upper_cents": old_cents,
            "thirteen_key_refinement": refined,
            "merged_upper_cents": merged,
        })

    refined_count = sum(row["thirteen_key_refinement"] is not None for row in rows)
    if refined_count != sum(int(old["upper_cents"]) > at_most_fifteen
                            for old in ten["exactly_sixteen_rows"]):
        raise AssertionError("target branch selection changed")
    exactly_sixteen_cents = max(row["merged_upper_cents"] for row in rows)
    at_most_sixteen_cents = max(at_most_fifteen, exactly_sixteen_cents)
    all_cases_cents = max(at_most_sixteen_cents, all_seventeen_cents)
    if all_cases_cents > int(ten["unconditional_upper_cents"]):
        raise AssertionError("refinement weakened the existing global bound")
    return {
        "scope": "public dev-reference, unconditional over all valid decision traces",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "ten_key_certificate_sha256": _sha(ten_path),
        "thirteen_key_all_request_certificate_sha256": _sha(thirteen_path),
        "legacy_subset_certificate_sha256": _sha(sixteen10.SUBSET_CERT),
        "keys": list(KEYS),
        "theta_uniform_cents": THETA_CENTS,
        "branch_count": len(rows),
        "refined_branch_count": refined_count,
        "branch_rows": rows,
        "at_most_fifteen_upper_cents": at_most_fifteen,
        "exactly_sixteen_upper_cents": exactly_sixteen_cents,
        "at_most_sixteen_upper_cents": at_most_sixteen_cents,
        "all_seventeen_upper_cents": all_seventeen_cents,
        "unconditional_upper_cents": all_cases_cents,
        "incumbent_score_micro": sixteen10.INCUMBENT_SCORE_MICRO,
        "incumbent_gap_micro": all_cases_cents * 10000 - sixteen10.INCUMBENT_SCORE_MICRO,
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection13._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "The exhaustive ten-key certificate covers all 33 exactly-16 "
            "request cases. Only branches above the independently certified "
            "<=15-request ceiling are reevaluated with the 13-key exact "
            "projected time DP. Each branch takes the minimum of two valid "
            "upper bounds. The all-17 case uses the separately audited "
            "13-key conditional certificate."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ten-cert", type=Path, default=TEN_CERT)
    parser.add_argument("--thirteen-cert", type=Path, default=THIRTEEN_CERT)
    parser.add_argument("--prices", type=Path, default=projection13.PRICE_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.ten_cert, args.thirteen_cert, args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "at_most_fifteen_upper_cents": result["at_most_fifteen_upper_cents"],
        "exactly_sixteen_upper_cents": result["exactly_sixteen_upper_cents"],
        "at_most_sixteen_upper_cents": result["at_most_sixteen_upper_cents"],
        "all_seventeen_upper_cents": result["all_seventeen_upper_cents"],
        "unconditional_upper_cents": result["unconditional_upper_cents"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
