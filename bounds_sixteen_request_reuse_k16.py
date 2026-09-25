#!/usr/bin/env python3
"""Tighten exact-16 request branches by reusing an audited K16 time DP.

The older exact-16 certificate partitions every valid trace into 33 cases.
Only cases above a chosen threshold need refinement.  A case may reuse the
all-17 K16 DP value only when *all* projected-DP inputs match exactly.  The
non-key science envelope and request accounting are recomputed per case.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bounds_request_projection_k10 as projection
import bounds_sixteen_request_grouped_k13 as grouped
import bounds_sixteen_request_k10 as sixteen


ROOT = projection.ROOT
PRIOR_SIXTEEN = ROOT / "results" / "practice_sixteen_request_grouped_k13.json"
PRIOR_FIFTEEN = ROOT / "results" / "practice_fifteen_request_grouped_k13.json"
K16_CERT = ROOT / "results" / "practice_request_projection_k16_ring.json"
DEFAULT_OUT = ROOT / "results" / "practice_sixteen_request_reuse_k16.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _signature(data: dict, inputs: dict, keys: tuple[str, ...],
               theta_cents: int, price_sha: str, projection_sha: str,
               branch_index: int) -> dict:
    deadlines = inputs["deadlines_by_branch"][branch_index]
    scorer = data["scorer"]
    return {
        "keys": list(keys),
        "theta_uniform_cents": theta_cents,
        "capacity_price_sha256": price_sha,
        "projection_certificate_sha256": projection_sha,
        "time_units": data["n"],
        "complete_arc_count": data["complete_arc_count"],
        "weather_interruption_arc_count": data["partial_arc_count"],
        "earliest_terminal_unit": int(inputs["earliest_terminal_unit"]),
        "required_key_mask": sum(
            1 << j for j, key in enumerate(keys)
            if scorer.tiles[key].scheduling_class == "REQUIRED"
        ),
        "mandatory_key_mask": sum(
            1 << j for j, key in enumerate(keys) if key in deadlines
        ),
        "key_deadline_units": [
            int(np.searchsorted(inputs["instants"], deadlines[key], side="left"))
            if key in deadlines else int(data["n"])
            for key in keys
        ],
    }


def _external_cents(data: dict, deadlines: dict, keys: tuple[str, ...],
                    instants: np.ndarray, arc_starts: np.ndarray,
                    indices_by_tile: list[np.ndarray]) -> int:
    external = int(data["prices"].sum())
    key_set = set(keys)
    for tile_index, tile_id in enumerate(data["tile_ids"]):
        if tile_id in key_set:
            continue
        if tile_id not in deadlines:
            external += int(data["tile_residual_max"][tile_index])
            continue
        deadline = int(np.searchsorted(instants, deadlines[tile_id], side="left"))
        indices = indices_by_tile[tile_index]
        eligible = indices[arc_starts[indices] < deadline]
        if not len(eligible):
            raise AssertionError(f"mandatory non-key tile lacks an eligible arc: {tile_id}")
        external += int(np.max(data["complete_reduced"][eligible]))
    return external


def certify(prior16_path: Path, prior15_path: Path, k16_path: Path,
            prices_path: Path, target_upper_cents: int) -> dict:
    started = time.monotonic()
    prior16 = json.loads(prior16_path.read_text())
    prior15 = json.loads(prior15_path.read_text())
    cert16 = json.loads(k16_path.read_text())
    data, audit = projection._load_audited_data(prices_path)
    choices, instants, arc_starts, _, _ = sixteen._certified_inputs(data)
    all_inputs = projection._instance_inputs(data)
    case = cert16["cases"][0]
    keys = tuple(case["keys"])
    theta = int(cert16["theta_uniform_cents"])
    if (len(cert16["cases"]) != 1 or len(keys) != 16
            or len(case["branches"]) != 2 or theta != 135
            or cert16["certificates"]["price_sha256"] != audit["price_sha256"]
            or cert16["certificates"]["projection_certificate_sha256"]
                != audit["projection_certificate_sha256"]
            or prior16["capacity_price_sha256"] != audit["price_sha256"]
            or prior15["capacity_price_sha256"] != audit["price_sha256"]
            or cert16["complete_arc_count"] != data["complete_arc_count"]
            or cert16["weather_interruption_arc_count"] != data["partial_arc_count"]
            or cert16["full_time_rows"] != data["n"] + 1):
        raise AssertionError("source certificates or audited model differ")
    if tuple(keys[:13]) != grouped.initial.KEYS:
        raise AssertionError("K16 key prefix differs from K13 branch certificate")
    rows = prior16["merged_branch_rows"]
    order = [request.request_id for request, _ in choices]
    expected = {(request_id, option)
                for request_id in order
                for option in ((0,) if request_id == "RQ0004" else (0, 1))}
    old_by_id = {(row["missed_request"], row["rq0004_branch"]): row
                 for row in rows}
    if len(rows) != 33 or set(old_by_id) != expected:
        raise AssertionError("source exact-16 certificate lacks a branch")
    if max(int(row["merged_upper_cents"]) for row in rows) != int(prior16["exactly_sixteen_upper_cents"]):
        raise AssertionError("source exact-16 maximum differs from branch table")

    # The published all-17 K16 result is the source DP calculation.  First
    # reconstruct and check both of its branches to the cent.
    indices_by_tile = [np.flatnonzero(data["complete_tile"] == tile_index)
                       for tile_index in range(len(data["tile_ids"]))]
    theta_constant = theta * (len(data["tile_ids"]) - len(keys))
    all_signatures = []
    for branch_index, published in enumerate(case["branches"]):
        sig = _signature(data, all_inputs, keys, theta, audit["price_sha256"],
                         audit["projection_certificate_sha256"], branch_index)
        external = _external_cents(
            data, all_inputs["deadlines_by_branch"][branch_index], keys,
            instants, arc_starts, indices_by_tile,
        )
        if (not published["feasible_relaxation"]
                or published["key_deadline_unit"] != sig["key_deadline_units"]
                or published["mandatory_key_mask"] != sig["mandatory_key_mask"]
                or published["required_key_mask"] != sig["required_key_mask"]
                or published["external_cents"] != external
                or published["theta_constant_cents"] != theta_constant
                or published["request_cents"] != data["request_cents"]
                or published["conditional_upper_cents"]
                    != external + int(data["request_cents"])
                       + theta_constant + published["dp_cents"]):
            raise AssertionError("published K16 branch fails integer reconstruction")
        all_signatures.append(sig)
    if all_signatures[0] != all_signatures[1]:
        raise AssertionError("the all-17 K16 branches have different DP states")
    if case["branches"][0]["dp_cents"] != case["branches"][1]["dp_cents"]:
        raise AssertionError("identical K16 DP inputs have different outputs")
    shared_signature = all_signatures[0]
    shared_dp = int(case["branches"][0]["dp_cents"])

    target_rows = [row for row in rows
                   if int(row["merged_upper_cents"]) > target_upper_cents]
    refinements = {}
    for row in target_rows:
        missed, option = row["missed_request"], row["rq0004_branch"]
        spec = grouped._branch_spec(data, choices, instants, missed, option)
        branch_inputs = {
            "deadlines_by_branch": [spec["deadlines"]],
            "instants": instants,
            "earliest_terminal_unit": spec["earliest_terminal_unit"],
        }
        sig = _signature(data, branch_inputs, keys, theta,
                         audit["price_sha256"],
                         audit["projection_certificate_sha256"], 0)
        if sig != shared_signature:
            raise AssertionError(f"target branch has a different K16 DP input: {missed}/{option}")
        external = _external_cents(
            data, spec["deadlines"], keys, instants, arc_starts, indices_by_tile,
        )
        new_upper = (external + spec["reward_cents"] + theta_constant
                     + shared_dp - spec["miss_cents"])
        key = (missed, option)
        refinements[key] = {
            "missed_request": missed,
            "rq0004_branch": option,
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "external_cents": external,
            "selected_reward_cents": int(spec["reward_cents"]),
            "unavoidable_miss_cents": int(spec["miss_cents"]),
            "theta_constant_cents": theta_constant,
            "shared_dp_cents": shared_dp,
            "k16_upper_cents": new_upper,
            "merged_upper_cents": min(int(row["merged_upper_cents"]), new_upper),
        }
    merged_rows = []
    for row in rows:
        key = (row["missed_request"], row["rq0004_branch"])
        new = refinements.get(key)
        merged_rows.append({
            "missed_request": key[0],
            "rq0004_branch": key[1],
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "k16_upper_cents": new["k16_upper_cents"] if new else None,
            "merged_upper_cents": new["merged_upper_cents"] if new else int(row["merged_upper_cents"]),
        })
    exact16 = max(row["merged_upper_cents"] for row in merged_rows)
    at_most15 = int(prior15["at_most_fifteen_upper_cents"])
    if exact16 > int(prior16["exactly_sixteen_upper_cents"]):
        raise AssertionError("refinement weakened exact-16 bound")
    return {
        "scope": "dev-reference; all valid traces with exactly 16 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "prior_sixteen_certificate_sha256": _sha(prior16_path),
        "prior_fifteen_certificate_sha256": _sha(prior15_path),
        "reused_k16_certificate_sha256": _sha(k16_path),
        "shared_dp_signature": shared_signature,
        "shared_dp_signature_sha256": hashlib.sha256(json.dumps(
            shared_signature, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest(),
        "shared_dp_cents": shared_dp,
        "shared_dp_evaluations": 0,
        "all_seventeen_branch_reconstructions": [
            {"rq0004_branch": i,
             "external_cents": case["branches"][i]["external_cents"],
             "conditional_upper_cents": case["branches"][i]["conditional_upper_cents"]}
            for i in range(2)
        ],
        "target_upper_cents": target_upper_cents,
        "branch_count": len(merged_rows),
        "refined_branch_count": len(refinements),
        "refinements": list(refinements.values()),
        "merged_branch_rows": merged_rows,
        "exactly_sixteen_upper_cents": exact16,
        "at_most_fifteen_upper_cents": at_most15,
        "at_most_sixteen_upper_cents": max(exact16, at_most15),
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "The previous signed 33-branch exact-16 partition remains exhaustive. "
            "Every branch above the stated threshold has the same complete K16 "
            "time-DP input signature as the independently certified all-17 K16 "
            "case. Its exact projected DP integer is reused without a new DP "
            "evaluation. For each target, the non-key first-science envelopes "
            "and reward/miss terms are independently recomputed in integer "
            "cents; other branches retain their valid prior upper bounds."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-sixteen", type=Path, default=PRIOR_SIXTEEN)
    parser.add_argument("--prior-fifteen", type=Path, default=PRIOR_FIFTEEN)
    parser.add_argument("--k16-certificate", type=Path, default=K16_CERT)
    parser.add_argument("--prices", type=Path, default=projection.PRICE_FILE)
    parser.add_argument("--target-upper-cents", type=int, default=2125000)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.prior_sixteen, args.prior_fifteen,
                     args.k16_certificate, args.prices, args.target_upper_cents)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        result, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n")
    print(json.dumps({
        "refined_branch_count": result["refined_branch_count"],
        "exactly_sixteen_upper_cents": result["exactly_sixteen_upper_cents"],
        "at_most_sixteen_upper_cents": result["at_most_sixteen_upper_cents"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
