#!/usr/bin/env python3
"""Refine the four remaining high exact-15 branches with two K13 ring DPs."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bounds_fifteen_request_grouped_k13 as prior_group
import bounds_request_projection_k10 as projection
import bounds_request_projection_ring as ring
import bounds_sixteen_request_k10 as sixteen
import bounds_sixteen_request_reuse_k16 as reuse


ROOT = projection.ROOT
PRIOR_FIFTEEN = ROOT / "results" / "practice_fifteen_request_reuse_k16.json"
DIAGNOSTIC = ROOT / "results" / "practice_fifteen_request_branch_analysis.json"
EXACT_SIXTEEN = ROOT / "results" / "practice_sixteen_request_reuse_k16_round2.json"
DEFAULT_OUT = ROOT / "results" / "practice_fifteen_request_two_k13.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certify(prior15_path: Path, diagnostic_path: Path, exact16_path: Path,
            prices_path: Path, target_upper_cents: int) -> dict:
    started = time.monotonic()
    old = json.loads(prior15_path.read_text())
    diagnostic = json.loads(diagnostic_path.read_text())
    exact16 = json.loads(exact16_path.read_text())
    data, audit = projection._load_audited_data(prices_path)
    choices, instants, arc_starts, _, _ = sixteen._certified_inputs(data)
    if (old["capacity_price_sha256"] != audit["price_sha256"]
            or diagnostic["capacity_price_sha256"] != audit["price_sha256"]
            or exact16["capacity_price_sha256"] != audit["price_sha256"]):
        raise AssertionError("certificate and audited instance differ")
    rows = old["merged_branch_rows"]
    old_by_key = {(r["request_mask"], r["rq0004_branch"]): r for r in rows}
    original_by_key = {(r["request_mask"], r["rq0004_branch"]): r
                       for r in diagnostic["rows"]}
    request_ids = [request.request_id for request, _ in choices]
    expected = {
        (pair, option)
        for pair in itertools.combinations(request_ids, 2)
        for option in ((0,) if "RQ0004" in pair else (0, 1))
    }
    actual = {(tuple(r["unawarded_request_ids"]), r["rq0004_branch"])
              for r in diagnostic["rows"]}
    if (len(rows) != 256 or len(old_by_key) != 256 or len(original_by_key) != 256
            or set(old_by_key) != set(original_by_key) or expected != actual
            or max(r["merged_upper_cents"] for r in rows)
                != old["exactly_fifteen_upper_cents"]):
        raise AssertionError("exact-15 exhaustive branch table differs")

    keys = tuple(prior_group.first.KEYS)
    theta = prior_group.first.THETA_CENTS
    targets = [r for r in rows if r["merged_upper_cents"] > target_upper_cents]
    groups: dict[str, dict] = {}
    for row in targets:
        key = (row["request_mask"], row["rq0004_branch"])
        original = original_by_key[key]
        spec = prior_group._branch_spec(
            data, choices, instants,
            tuple(original["unawarded_request_ids"]), row["rq0004_branch"],
        )
        if (spec["reward_cents"] != original["request_reward_cents"]
                or spec["miss_cents"] != original["unavoidable_miss_cents"]):
            raise AssertionError("request accounting differs from prior audit")
        inputs = {
            "branches": [spec["selected"]],
            "deadlines_by_branch": [spec["deadlines"]],
            "instants": instants,
            "arc_starts": arc_starts,
            "earliest_terminal_unit": spec["earliest_terminal_unit"],
        }
        sig = reuse._signature(
            data, inputs, keys, theta, audit["price_sha256"],
            audit["projection_certificate_sha256"], 0,
        )
        sig_sha = hashlib.sha256(json.dumps(
            sig, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        group = groups.setdefault(sig_sha, {"signature": sig, "members": []})
        if group["signature"] != sig:
            raise AssertionError("DP signature SHA collision")
        group["members"].append((row, spec, inputs))
    if len(targets) != 4 or len(groups) != 2 or sorted(len(g["members"]) for g in groups.values()) != [2, 2]:
        raise AssertionError("expected two unresolved two-branch DP groups")

    indices_by_tile = [np.flatnonzero(data["complete_tile"] == i)
                       for i in range(len(data["tile_ids"]))]
    theta_constant = theta * (len(data["tile_ids"]) - len(keys))
    refinements = {}
    dp_groups = []
    for sig_sha, group in sorted(groups.items()):
        representative_row, representative_spec, representative_inputs = group["members"][0]
        raw = projection._conditional_bound(
            data, representative_inputs, keys, theta, 0,
            dp_function=ring.conditional_projected_dp_ring,
        )
        sig = group["signature"]
        if (not raw["feasible_relaxation"]
                or raw["key_deadline_unit"] != sig["key_deadline_units"]
                or raw["mandatory_key_mask"] != sig["mandatory_key_mask"]
                or raw["required_key_mask"] != sig["required_key_mask"]
                or raw["theta_constant_cents"] != theta_constant):
            raise AssertionError("representative DP output differs from its signature")
        dp_cents = int(raw["dp_cents"])
        group_records = []
        for row, spec, _ in group["members"]:
            key = (row["request_mask"], row["rq0004_branch"])
            external = reuse._external_cents(
                data, spec["deadlines"], keys,
                instants, arc_starts, indices_by_tile,
            )
            total = (external + spec["reward_cents"] + theta_constant
                     + dp_cents - spec["miss_cents"])
            record = {
                "request_mask": key[0],
                "rq0004_branch": key[1],
                "unawarded_request_ids": spec["missed_ids"],
                "prior_upper_cents": int(row["merged_upper_cents"]),
                "shared_dp_signature_sha256": sig_sha,
                "external_cents": external,
                "selected_reward_cents": spec["reward_cents"],
                "unavoidable_miss_cents": spec["miss_cents"],
                "theta_constant_cents": theta_constant,
                "shared_dp_cents": dp_cents,
                "k13_upper_cents": total,
                "merged_upper_cents": min(int(row["merged_upper_cents"]), total),
            }
            refinements[key] = record
            group_records.append(record)
        rep_key = (representative_row["request_mask"], representative_row["rq0004_branch"])
        rep = refinements[rep_key]
        raw_adjusted = (raw["conditional_upper_cents"]
                        - (data["request_cents"] - representative_spec["reward_cents"])
                        - representative_spec["miss_cents"])
        if raw["external_cents"] != rep["external_cents"] or raw_adjusted != rep["k13_upper_cents"]:
            raise AssertionError("representative integer reconstruction differs from evaluator")
        dp_groups.append({
            "signature_sha256": sig_sha,
            "signature": sig,
            "branch_count": len(group_records),
            "representative_request_mask": rep_key[0],
            "representative_rq0004_branch": rep_key[1],
            "representative_full_dp": raw,
            "representative_full_adjusted_upper_cents": raw_adjusted,
            "refined_rows": group_records,
        })
        print(json.dumps({
            "signature_sha256": sig_sha,
            "missed_requests": representative_spec["missed_ids"],
            "dp_cents": dp_cents,
            "group_upper_cents": max(r["merged_upper_cents"] for r in group_records),
            "elapsed_seconds": round(time.monotonic() - started, 1),
        }), flush=True)

    merged_rows = []
    for row in rows:
        key = (row["request_mask"], row["rq0004_branch"])
        new = refinements.get(key)
        merged_rows.append({
            "request_mask": key[0],
            "rq0004_branch": key[1],
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "k13_upper_cents": new["k13_upper_cents"] if new else None,
            "merged_upper_cents": new["merged_upper_cents"]
                                  if new else int(row["merged_upper_cents"]),
        })
    exact15 = max(r["merged_upper_cents"] for r in merged_rows)
    at_most14 = int(old["at_most_fourteen_upper_cents"])
    at_most15 = max(exact15, at_most14)
    exact16_upper = int(exact16["exactly_sixteen_upper_cents"])
    if at_most15 > old["at_most_fifteen_upper_cents"]:
        raise AssertionError("refinement weakened <=15 bound")
    return {
        "scope": "dev-reference; all valid traces with at most 16 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "prior_fifteen_certificate_sha256": _sha(prior15_path),
        "exact_fifteen_diagnostic_sha256": _sha(diagnostic_path),
        "exact_sixteen_certificate_sha256": _sha(exact16_path),
        "keys": list(keys),
        "theta_uniform_cents": theta,
        "target_upper_cents": target_upper_cents,
        "branch_count": len(merged_rows),
        "refined_branch_count": len(refinements),
        "fresh_dp_evaluations": len(dp_groups),
        "dp_groups": dp_groups,
        "refinements": list(refinements.values()),
        "merged_branch_rows": merged_rows,
        "at_most_fourteen_upper_cents": at_most14,
        "exactly_fifteen_upper_cents": exact15,
        "at_most_fifteen_upper_cents": at_most15,
        "exactly_sixteen_upper_cents": exact16_upper,
        "at_most_sixteen_upper_cents": max(at_most15, exact16_upper),
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "All 256 exact-15 witness branches are checked against the "
            "exhaustive prior table. Only its four cases above the stated "
            "threshold are recomputed. They form two complete K13 DP input "
            "signatures, each solved once by the proven ring recurrence. "
            "Non-key first-science envelopes and request terms are recomputed "
            "per branch in integer cents; representative full evaluator output "
            "matches the decomposed account to the cent. All other branches "
            "retain their valid prior bounds."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-fifteen", type=Path, default=PRIOR_FIFTEEN)
    parser.add_argument("--diagnostic", type=Path, default=DIAGNOSTIC)
    parser.add_argument("--exact-sixteen", type=Path, default=EXACT_SIXTEEN)
    parser.add_argument("--prices", type=Path, default=projection.PRICE_FILE)
    parser.add_argument("--target-upper-cents", type=int, default=2120000)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.prior_fifteen, args.diagnostic, args.exact_sixteen,
                     args.prices, args.target_upper_cents)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "fresh_dp_evaluations": result["fresh_dp_evaluations"],
        "exactly_fifteen_upper_cents": result["exactly_fifteen_upper_cents"],
        "at_most_sixteen_upper_cents": result["at_most_sixteen_upper_cents"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
