#!/usr/bin/env python3
"""Refine 16 exact-15 branches with one new and one reused K13 DP value."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bounds_fifteen_request_k13_targeted as first
import bounds_request_projection_k10 as projection13
import bounds_sixteen_request_grouped_k13 as grouped16
import bounds_sixteen_request_k10 as sixteen10
from bounds_request_unconditional import _exact_cents, _request_is_excused_if_missed


ROOT = projection13.ROOT
PRIOR_FIFTEEN = ROOT / "results" / "practice_fifteen_request_residual.json"
PRIOR_SIXTEEN = ROOT / "results" / "practice_sixteen_request_grouped_k13.json"
DIAGNOSTIC = ROOT / "results" / "practice_fifteen_request_branch_analysis.json"
DEFAULT_OUT = ROOT / "results" / "practice_fifteen_request_grouped_k13.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _branch_spec(data: dict, choices: list, instants: np.ndarray,
                 missed_ids: tuple[str, str], rq0004_branch: int) -> dict:
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
    if len(selected) != 15:
        raise AssertionError("branch does not earn exactly fifteen rewards")
    if "RQ0004" not in selected:
        selected["RQ0004"] = ()
    deadlines = {}
    for request_id, tiles in selected.items():
        deadline = scorer.requests[request_id].deadline_utc.timestamp()
        for tile_id in tiles:
            deadlines[tile_id] = min(deadline, deadlines.get(tile_id, deadline))
    miss_cents = 0
    for request_id in missed_ids:
        request = scorer.requests[request_id]
        if (request.deadline_utc.timestamp() <= latest_release
                and not _request_is_excused_if_missed(scorer, request)):
            miss_cents += _exact_cents(request.miss_penalty)
    key_deadline_units = tuple(
        int(np.searchsorted(instants, deadlines[key], side="left"))
        if key in deadlines else data["n"]
        for key in first.KEYS
    )
    mandatory_key_mask = sum(1 << j for j, key in enumerate(first.KEYS)
                             if key in deadlines)
    required_key_mask = sum(
        1 << j for j, key in enumerate(first.KEYS)
        if scorer.tiles[key].scheduling_class == "REQUIRED"
    )
    return {
        "missed_ids": list(missed_ids),
        "rq0004_branch": rq0004_branch,
        "selected": selected,
        "deadlines": deadlines,
        "reward_cents": reward_cents,
        "miss_cents": miss_cents,
        "earliest_terminal_unit": int(np.searchsorted(
            instants, latest_release, side="left"
        )),
        "key_deadline_units": key_deadline_units,
        "mandatory_key_mask": mandatory_key_mask,
        "required_key_mask": required_key_mask,
    }


def _signature_payload(spec: dict, audit: dict) -> dict:
    return {
        "keys": list(first.KEYS),
        "theta_uniform_cents": first.THETA_CENTS,
        "capacity_price_sha256": audit["price_sha256"],
        "projection_certificate_sha256": audit["projection_certificate_sha256"],
        "earliest_terminal_unit": spec["earliest_terminal_unit"],
        "key_deadline_units": list(spec["key_deadline_units"]),
        "mandatory_key_mask": spec["mandatory_key_mask"],
        "required_key_mask": spec["required_key_mask"],
    }


def _signature_sha(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def certify(prior_fifteen_path: Path, prior_sixteen_path: Path,
            diagnostic_path: Path, prices_path: Path) -> dict:
    started = time.monotonic()
    old15 = json.loads(prior_fifteen_path.read_text())
    old16 = json.loads(prior_sixteen_path.read_text())
    diagnostic = json.loads(diagnostic_path.read_text())
    data, audit = projection13._load_audited_data(prices_path)
    choices, instants, arc_starts, _, _ = sixteen10._certified_inputs(data)
    if (old15["capacity_price_sha256"] != audit["price_sha256"]
            or old16["capacity_price_sha256"] != audit["price_sha256"]
            or diagnostic["capacity_price_sha256"] != audit["price_sha256"]
            or old15["keys"] != list(first.KEYS)
            or old16["shared_dp_signature"]["keys"] != list(first.KEYS)
            or old15["theta_uniform_cents"] != first.THETA_CENTS
            or old16["shared_dp_signature"]["theta_uniform_cents"] != first.THETA_CENTS):
        raise AssertionError("prior certificates use different audited inputs")
    old_rows = old15["merged_branch_rows"]
    original_by_key = {(row["request_mask"], row["rq0004_branch"]): row
                       for row in diagnostic["rows"]}
    if (len(old_rows) != 256 or len(original_by_key) != 256
            or len({(row["request_mask"], row["rq0004_branch"])
                    for row in old_rows}) != 256):
        raise AssertionError("prior exact-15 partition incomplete")
    threshold = int(old16["exactly_sixteen_upper_cents"])
    if threshold != 2128323:
        raise AssertionError("exactly-16 ceiling changed")
    targets = [row for row in old_rows if row["merged_upper_cents"] > threshold]
    if len(targets) != 16:
        raise AssertionError("unresolved exact-15 branch count changed")

    groups: dict[str, dict] = {}
    target_specs = []
    for row in targets:
        original = original_by_key[(row["request_mask"], row["rq0004_branch"])]
        spec = _branch_spec(
            data, choices, instants,
            tuple(original["unawarded_request_ids"]), row["rq0004_branch"],
        )
        if (spec["reward_cents"] != original["request_reward_cents"]
                or spec["miss_cents"] != original["unavoidable_miss_cents"]):
            raise AssertionError("branch request reward or miss terms differ")
        payload = _signature_payload(spec, audit)
        sig_sha = _signature_sha(payload)
        item = groups.setdefault(sig_sha, {"payload": payload, "members": []})
        if item["payload"] != payload:
            raise AssertionError("DP signature SHA collision")
        item["members"].append((row, spec))
        target_specs.append((row, spec, sig_sha))
    if len(groups) != 2 or sorted(len(g["members"]) for g in groups.values()) != [2, 14]:
        raise AssertionError("expected exactly two shared DP states")
    reused_sha = old16["shared_dp_signature_sha256"]
    if (reused_sha not in groups or len(groups[reused_sha]["members"]) != 14
            or groups[reused_sha]["payload"] != old16["shared_dp_signature"]):
        raise AssertionError("14-branch DP state does not match certified 16-request DP")
    new_sha = next(sha for sha in groups if sha != reused_sha)
    if (len(groups[new_sha]["members"]) != 2
            or groups[new_sha]["payload"]["earliest_terminal_unit"] != 40896):
        raise AssertionError("two-branch newly solved DP state changed")

    representative_row, representative = groups[new_sha]["members"][0]
    full = projection13._conditional_bound(
        data,
        {
            "branches": [representative["selected"]],
            "deadlines_by_branch": [representative["deadlines"]],
            "instants": instants,
            "arc_starts": arc_starts,
            "earliest_terminal_unit": representative["earliest_terminal_unit"],
        },
        first.KEYS, first.THETA_CENTS, 0,
    )
    if (not full["feasible_relaxation"]
            or full["key_deadline_unit"] != list(representative["key_deadline_units"])
            or full["mandatory_key_mask"] != representative["mandatory_key_mask"]
            or full["required_key_mask"] != representative["required_key_mask"]):
        raise AssertionError("new representative full DP disagrees with signature")
    groups[new_sha]["dp_cents"] = int(full["dp_cents"])
    groups[new_sha]["source"] = "fresh_full_conditional_dp"
    groups[reused_sha]["dp_cents"] = int(old16["representative_full_dp"]["dp_cents"])
    groups[reused_sha]["source"] = "prior_sixteen_certificate"
    theta_constant = first.THETA_CENTS * (len(data["tile_ids"]) - len(first.KEYS))
    if (full["theta_constant_cents"] != theta_constant
            or old16["representative_full_dp"]["theta_constant_cents"] != theta_constant):
        raise AssertionError("non-key theta constant differs")

    indices_by_tile = [np.flatnonzero(data["complete_tile"] == tile_index)
                       for tile_index in range(len(data["tile_ids"]))]
    refined = {}
    for row, spec, sig_sha in target_specs:
        external = grouped16._external_cents(
            data, spec, instants, arc_starts, indices_by_tile,
        )
        dp_cents = groups[sig_sha]["dp_cents"]
        new_upper = (external + spec["reward_cents"] + theta_constant
                     + dp_cents - spec["miss_cents"])
        merged = min(int(row["merged_upper_cents"]), new_upper)
        key = (row["request_mask"], row["rq0004_branch"])
        refined[key] = {
            "request_mask": key[0],
            "rq0004_branch": key[1],
            "unawarded_request_ids": spec["missed_ids"],
            "prior_upper_cents": row["merged_upper_cents"],
            "shared_dp_signature_sha256": sig_sha,
            "external_cents": external,
            "selected_reward_cents": spec["reward_cents"],
            "unavoidable_miss_cents": spec["miss_cents"],
            "theta_constant_cents": theta_constant,
            "shared_dp_cents": dp_cents,
            "thirteen_key_upper_cents": new_upper,
            "merged_upper_cents": merged,
        }
        print(json.dumps({
            "unawarded_request_ids": spec["missed_ids"],
            "rq0004_branch": key[1],
            "prior_upper_cents": row["merged_upper_cents"],
            "thirteen_key_upper_cents": new_upper,
            "dp_source": groups[sig_sha]["source"],
        }), flush=True)

    rep_key = (representative_row["request_mask"], representative_row["rq0004_branch"])
    rep = refined[rep_key]
    adjusted_full = (int(full["conditional_upper_cents"])
                     - (int(data["request_cents"]) - representative["reward_cents"])
                     - representative["miss_cents"])
    if full["external_cents"] != rep["external_cents"] or adjusted_full != rep["thirteen_key_upper_cents"]:
        raise AssertionError("new group representative differs from full DP by at least one cent")

    merged_rows = []
    for old in old_rows:
        key = (old["request_mask"], old["rq0004_branch"])
        new = refined.get(key)
        merged_rows.append({
            "request_mask": key[0],
            "rq0004_branch": key[1],
            "prior_upper_cents": old["merged_upper_cents"],
            "thirteen_key_upper_cents": new["thirteen_key_upper_cents"] if new else None,
            "merged_upper_cents": new["merged_upper_cents"] if new else old["merged_upper_cents"],
        })
    exactly15 = max(row["merged_upper_cents"] for row in merged_rows)
    at_most14 = int(old15["at_most_fourteen_upper_cents"])
    at_most15 = max(at_most14, exactly15)
    at_most16 = max(at_most15, threshold)
    if at_most15 > old15["at_most_fifteen_upper_cents"]:
        raise AssertionError("grouped refinement weakened previous <=15 bound")
    return {
        "scope": "dev-reference; all valid traces with at most 16 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "prior_fifteen_certificate_sha256": _sha(prior_fifteen_path),
        "prior_sixteen_certificate_sha256": _sha(prior_sixteen_path),
        "diagnostic_sha256": _sha(diagnostic_path),
        "keys": list(first.KEYS),
        "theta_uniform_cents": first.THETA_CENTS,
        "dp_groups": [{
            "signature_sha256": sha,
            "signature": group["payload"],
            "branch_count": len(group["members"]),
            "dp_cents": group["dp_cents"],
            "source": group["source"],
        } for sha, group in sorted(groups.items())],
        "fresh_dp_evaluations": 1,
        "reused_dp_evaluations": 1,
        "new_representative_full_dp": full,
        "new_representative_full_adjusted_upper_cents": adjusted_full,
        "branch_count": len(merged_rows),
        "refined_branch_count": len(refined),
        "refinements": list(refined.values()),
        "merged_branch_rows": merged_rows,
        "at_most_fourteen_upper_cents": at_most14,
        "exactly_fifteen_upper_cents": exactly15,
        "at_most_fifteen_upper_cents": at_most15,
        "exactly_sixteen_upper_cents": threshold,
        "at_most_sixteen_upper_cents": at_most16,
        "branches_above_exactly_sixteen": [
            row for row in merged_rows if row["merged_upper_cents"] > threshold
        ],
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection13._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "The exhaustive 256-branch exact-15 table has 16 branches above "
            "the certified exact-16 ceiling. They form two exact projected-DP "
            "input signatures: 14 reuse the signed prior exact-16 K13 DP value; "
            "two use one fresh full K13 DP. Every branch independently "
            "recomputes non-key science envelopes and request reward/miss "
            "terms in integer cents. The fresh representative agrees with "
            "the full conditional evaluator to the cent."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-fifteen", type=Path, default=PRIOR_FIFTEEN)
    parser.add_argument("--prior-sixteen", type=Path, default=PRIOR_SIXTEEN)
    parser.add_argument("--diagnostic", type=Path, default=DIAGNOSTIC)
    parser.add_argument("--prices", type=Path, default=projection13.PRICE_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.prior_fifteen, args.prior_sixteen,
                     args.diagnostic, args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "fresh_dp_evaluations": result["fresh_dp_evaluations"],
        "refined_branch_count": result["refined_branch_count"],
        "exactly_fifteen_upper_cents": result["exactly_fifteen_upper_cents"],
        "at_most_fifteen_upper_cents": result["at_most_fifteen_upper_cents"],
        "at_most_sixteen_upper_cents": result["at_most_sixteen_upper_cents"],
        "branches_above_exactly_sixteen": result["branches_above_exactly_sixteen"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
