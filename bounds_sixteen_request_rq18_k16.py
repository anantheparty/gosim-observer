#!/usr/bin/env python3
"""Solve the two high exact-16/RQ0018 branches with one new K16 ring DP."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bounds_request_projection_k10 as projection
import bounds_request_projection_ring as ring
import bounds_sixteen_request_grouped_k13 as grouped
import bounds_sixteen_request_k10 as sixteen
import bounds_sixteen_request_reuse_k16 as reuse


ROOT = projection.ROOT
PRIOR_SIXTEEN = ROOT / "results" / "practice_sixteen_request_reuse_k16_round2.json"
PRIOR_FIFTEEN = ROOT / "results" / "practice_fifteen_request_reuse_k13_round2.json"
K16_CERT = ROOT / "results" / "practice_request_projection_k16_ring.json"
DEFAULT_OUT = ROOT / "results" / "practice_sixteen_request_rq18_k16.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certify(prior16_path: Path, prior15_path: Path, k16_path: Path,
            prices_path: Path) -> dict:
    started = time.monotonic()
    old = json.loads(prior16_path.read_text())
    prior15 = json.loads(prior15_path.read_text())
    k16 = json.loads(k16_path.read_text())
    data, audit = projection._load_audited_data(prices_path)
    choices, instants, arc_starts, _, _ = sixteen._certified_inputs(data)
    case = k16["cases"][0]
    keys = tuple(case["keys"])
    theta = int(k16["theta_uniform_cents"])
    if (len(k16["cases"]) != 1 or len(keys) != 16 or theta != 135
            or k16["certificates"]["price_sha256"] != audit["price_sha256"]
            or old["capacity_price_sha256"] != audit["price_sha256"]
            or prior15["capacity_price_sha256"] != audit["price_sha256"]
            or k16["complete_arc_count"] != data["complete_arc_count"]
            or k16["weather_interruption_arc_count"] != data["partial_arc_count"]):
        raise AssertionError("source certificates use different audited data")
    old_rows = old["merged_branch_rows"]
    order = [request.request_id for request, _ in choices]
    expected = {(rid, option) for rid in order
                for option in ((0,) if rid == "RQ0004" else (0, 1))}
    old_by_key = {(r["missed_request"], r["rq0004_branch"]): r
                  for r in old_rows}
    if (len(old_rows) != 33 or set(old_by_key) != expected
            or max(r["merged_upper_cents"] for r in old_rows)
                != old["exactly_sixteen_upper_cents"]):
        raise AssertionError("source exact-16 branch table incomplete")
    threshold = int(prior15["at_most_fifteen_upper_cents"])
    targets = [r for r in old_rows if r["merged_upper_cents"] > threshold]
    if (len(targets) != 2
            or {(r["missed_request"], r["rq0004_branch"]) for r in targets}
                != {("RQ0018", 0), ("RQ0018", 1)}):
        raise AssertionError("unexpected high exact-16 branches")

    specs = []
    signatures = []
    for row in targets:
        spec = grouped._branch_spec(
            data, choices, instants, row["missed_request"], row["rq0004_branch"],
        )
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
        specs.append((row, spec, inputs))
        signatures.append(sig)
    if signatures[0] != signatures[1]:
        raise AssertionError("the two RQ0018 branches need different DPs")
    signature = signatures[0]
    representative_row, representative, representative_inputs = specs[0]
    raw = projection._conditional_bound(
        data, representative_inputs, keys, theta, 0,
        dp_function=ring.conditional_projected_dp_ring,
    )
    if (not raw["feasible_relaxation"]
            or raw["required_key_mask"] != signature["required_key_mask"]
            or raw["mandatory_key_mask"] != signature["mandatory_key_mask"]
            or raw["key_deadline_unit"] != signature["key_deadline_units"]):
        raise AssertionError("full K16 evaluator disagrees with DP signature")
    dp_cents = int(raw["dp_cents"])
    indices_by_tile = [np.flatnonzero(data["complete_tile"] == i)
                       for i in range(len(data["tile_ids"]))]
    theta_constant = theta * (len(data["tile_ids"]) - len(keys))
    refinements = {}
    for row, spec, _ in specs:
        key = (row["missed_request"], row["rq0004_branch"])
        external = reuse._external_cents(
            data, spec["deadlines"], keys, instants, arc_starts,
            indices_by_tile,
        )
        total = (external + spec["reward_cents"] + theta_constant
                 + dp_cents - spec["miss_cents"])
        refinements[key] = {
            "missed_request": key[0],
            "rq0004_branch": key[1],
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "external_cents": external,
            "selected_reward_cents": int(spec["reward_cents"]),
            "unavoidable_miss_cents": int(spec["miss_cents"]),
            "theta_constant_cents": theta_constant,
            "shared_dp_cents": dp_cents,
            "k16_upper_cents": total,
            "merged_upper_cents": min(int(row["merged_upper_cents"]), total),
        }
    rep_key = (representative_row["missed_request"], representative_row["rq0004_branch"])
    rep = refinements[rep_key]
    adjusted_full = (raw["conditional_upper_cents"]
                     - (data["request_cents"] - representative["reward_cents"])
                     - representative["miss_cents"])
    if (raw["external_cents"] != rep["external_cents"]
            or raw["theta_constant_cents"] != theta_constant
            or adjusted_full != rep["k16_upper_cents"]):
        raise AssertionError("representative integer decomposition differs")
    merged_rows = []
    for row in old_rows:
        key = (row["missed_request"], row["rq0004_branch"])
        new = refinements.get(key)
        merged_rows.append({
            "missed_request": key[0],
            "rq0004_branch": key[1],
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "k16_upper_cents": new["k16_upper_cents"] if new else None,
            "merged_upper_cents": new["merged_upper_cents"]
                                  if new else int(row["merged_upper_cents"]),
        })
    exact16 = max(r["merged_upper_cents"] for r in merged_rows)
    if exact16 > old["exactly_sixteen_upper_cents"]:
        raise AssertionError("refinement weakened exact-16 bound")
    return {
        "scope": "dev-reference; all valid traces with at most 16 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "prior_sixteen_certificate_sha256": _sha(prior16_path),
        "prior_fifteen_certificate_sha256": _sha(prior15_path),
        "k16_key_certificate_sha256": _sha(k16_path),
        "shared_dp_signature": signature,
        "shared_dp_signature_sha256": hashlib.sha256(json.dumps(
            signature, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest(),
        "shared_dp_cents": dp_cents,
        "fresh_dp_evaluations": 1,
        "representative_full_dp": raw,
        "representative_full_adjusted_upper_cents": adjusted_full,
        "branch_count": len(merged_rows),
        "refined_branch_count": len(refinements),
        "refinements": list(refinements.values()),
        "merged_branch_rows": merged_rows,
        "at_most_fifteen_upper_cents": threshold,
        "exactly_sixteen_upper_cents": exact16,
        "at_most_sixteen_upper_cents": max(threshold, exact16),
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "The prior signed exact-16 table is checked against all 33 "
            "one-miss witness cases. Only the two RQ0018 branches exceed the "
            "certified <=15 ceiling. Their complete K16 DP signatures agree; "
            "the exact ring DP is solved once. Each branch independently "
            "recomputes its non-key science envelope and request reward/miss "
            "terms. The representative matches the full evaluator to one "
            "integer cent; other 31 branches retain prior valid bounds."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-sixteen", type=Path, default=PRIOR_SIXTEEN)
    parser.add_argument("--prior-fifteen", type=Path, default=PRIOR_FIFTEEN)
    parser.add_argument("--k16-certificate", type=Path, default=K16_CERT)
    parser.add_argument("--prices", type=Path, default=projection.PRICE_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.prior_sixteen, args.prior_fifteen,
                     args.k16_certificate, args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "shared_dp_cents": result["shared_dp_cents"],
        "exactly_sixteen_upper_cents": result["exactly_sixteen_upper_cents"],
        "at_most_sixteen_upper_cents": result["at_most_sixteen_upper_cents"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
