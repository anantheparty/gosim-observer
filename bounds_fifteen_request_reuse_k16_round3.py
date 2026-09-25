#!/usr/bin/env python3
"""Prove all <=15 request cases below the incumbent via signed K16 DP."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bounds_fifteen_request_grouped_k13 as fifteen
import bounds_request_projection_k10 as projection
import bounds_sixteen_request_k10 as sixteen
import bounds_sixteen_request_reuse_k16 as reuse


ROOT = projection.ROOT
PRIOR_FIFTEEN = ROOT / "results" / "practice_fifteen_request_reuse_k13_round2.json"
DIAGNOSTIC = ROOT / "results" / "practice_fifteen_request_branch_analysis.json"
FOURTEEN = ROOT / "results" / "practice_fourteen_request_k16_reuse.json"
K16_SOURCE = ROOT / "results" / "practice_sixteen_request_reuse_k16.json"
K16_KEY_CERT = ROOT / "results" / "practice_request_projection_k16_ring.json"
DEFAULT_OUT = ROOT / "results" / "practice_fifteen_request_reuse_k16_round3.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certify(prior15_path: Path, diagnostic_path: Path, fourteen_path: Path,
            k16_source_path: Path, k16_key_path: Path, prices_path: Path) -> dict:
    started = time.monotonic()
    old = json.loads(prior15_path.read_text())
    diagnostic = json.loads(diagnostic_path.read_text())
    fourteen = json.loads(fourteen_path.read_text())
    source = json.loads(k16_source_path.read_text())
    key_cert = json.loads(k16_key_path.read_text())
    data, audit = projection._load_audited_data(prices_path)
    choices, instants, arc_starts, _, _ = sixteen._certified_inputs(data)
    if any(j["capacity_price_sha256"] != audit["price_sha256"]
           for j in (old, diagnostic, fourteen, source)):
        raise AssertionError("source certificates use different audited prices")
    if (source["reused_k16_certificate_sha256"] != _sha(k16_key_path)
            or key_cert["certificates"]["price_sha256"] != audit["price_sha256"]):
        raise AssertionError("signed K16 DP source differs from key certificate")
    keys = tuple(source["shared_dp_signature"]["keys"])
    theta = int(source["shared_dp_signature"]["theta_uniform_cents"])
    if keys != tuple(key_cert["cases"][0]["keys"]) or len(keys) != 16 or theta != 135:
        raise AssertionError("K16 keys or theta differ")
    all_signature = reuse._signature(
        data, projection._instance_inputs(data), keys, theta,
        audit["price_sha256"], audit["projection_certificate_sha256"], 0,
    )
    if all_signature != source["shared_dp_signature"]:
        raise AssertionError("published all-request DP signature changed")
    dp_cents = int(source["shared_dp_cents"])

    rows = old["merged_branch_rows"]
    original_by_key = {(r["request_mask"], r["rq0004_branch"]): r
                       for r in diagnostic["rows"]}
    old_by_key = {(r["request_mask"], r["rq0004_branch"]): r for r in rows}
    request_ids = [request.request_id for request, _ in choices]
    expected = {
        (pair, option)
        for pair in itertools.combinations(request_ids, 2)
        for option in ((0,) if "RQ0004" in pair else (0, 1))
    }
    actual = {(tuple(r["unawarded_request_ids"]), r["rq0004_branch"])
              for r in diagnostic["rows"]}
    if (len(rows) != 256 or len(old_by_key) != 256
            or len(original_by_key) != 256 or set(old_by_key) != set(original_by_key)
            or expected != actual
            or max(r["merged_upper_cents"] for r in rows)
                != old["exactly_fifteen_upper_cents"]):
        raise AssertionError("prior exact-15 branch coverage differs")
    incumbent_micro = int(sixteen.INCUMBENT_SCORE_MICRO)
    targets = [r for r in rows
               if int(r["merged_upper_cents"]) * 10000 > incumbent_micro]
    indices_by_tile = [np.flatnonzero(data["complete_tile"] == i)
                       for i in range(len(data["tile_ids"]))]
    theta_constant = theta * (len(data["tile_ids"]) - len(keys))
    refinements = {}
    for row in targets:
        key = (row["request_mask"], row["rq0004_branch"])
        original = original_by_key[key]
        spec = fifteen._branch_spec(
            data, choices, instants,
            tuple(original["unawarded_request_ids"]), row["rq0004_branch"],
        )
        if (spec["reward_cents"] != original["request_reward_cents"]
                or spec["miss_cents"] != original["unavoidable_miss_cents"]):
            raise AssertionError("request accounting differs from prior audit")
        inputs = {
            "deadlines_by_branch": [spec["deadlines"]],
            "instants": instants,
            "earliest_terminal_unit": spec["earliest_terminal_unit"],
        }
        signature = reuse._signature(
            data, inputs, keys, theta, audit["price_sha256"],
            audit["projection_certificate_sha256"], 0,
        )
        if signature != all_signature:
            raise AssertionError(f"target branch has different K16 DP state: {key}")
        external = reuse._external_cents(
            data, spec["deadlines"], keys, instants, arc_starts,
            indices_by_tile,
        )
        new_upper = (external + spec["reward_cents"] + theta_constant
                     + dp_cents - spec["miss_cents"])
        refinements[key] = {
            "request_mask": key[0],
            "rq0004_branch": key[1],
            "unawarded_request_ids": spec["missed_ids"],
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "external_cents": external,
            "selected_reward_cents": int(spec["reward_cents"]),
            "unavoidable_miss_cents": int(spec["miss_cents"]),
            "theta_constant_cents": theta_constant,
            "shared_dp_cents": dp_cents,
            "k16_upper_cents": new_upper,
            "merged_upper_cents": min(int(row["merged_upper_cents"]), new_upper),
        }
    if len(targets) != 42:
        raise AssertionError("expected 42 exact-15 branches above incumbent")
    merged_rows = []
    for row in rows:
        key = (row["request_mask"], row["rq0004_branch"])
        new = refinements.get(key)
        merged_rows.append({
            "request_mask": key[0],
            "rq0004_branch": key[1],
            "prior_upper_cents": int(row["merged_upper_cents"]),
            "k16_upper_cents": new["k16_upper_cents"] if new else None,
            "merged_upper_cents": new["merged_upper_cents"]
                                  if new else int(row["merged_upper_cents"]),
        })
    exact15 = max(r["merged_upper_cents"] for r in merged_rows)
    at_most14 = int(fourteen["at_most_fourteen_upper_cents"])
    at_most15 = max(at_most14, exact15)
    if at_most15 * 10000 >= incumbent_micro:
        raise AssertionError("<=15 is not proved strictly below incumbent")
    return {
        "scope": "dev-reference; all valid traces with at most 15 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "prior_fifteen_certificate_sha256": _sha(prior15_path),
        "exact_fifteen_diagnostic_sha256": _sha(diagnostic_path),
        "at_most_fourteen_certificate_sha256": _sha(fourteen_path),
        "k16_source_certificate_sha256": _sha(k16_source_path),
        "k16_key_certificate_sha256": _sha(k16_key_path),
        "shared_dp_signature": all_signature,
        "shared_dp_cents": dp_cents,
        "fresh_dp_evaluations": 0,
        "incumbent_score_micro": incumbent_micro,
        "branch_count": len(merged_rows),
        "refined_branch_count": len(refinements),
        "refinements": list(refinements.values()),
        "merged_branch_rows": merged_rows,
        "at_most_fourteen_upper_cents": at_most14,
        "exactly_fifteen_upper_cents": exact15,
        "at_most_fifteen_upper_cents": at_most15,
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "All 256 exact-15 two-miss witness branches are matched against "
            "the signed prior table. Only 42 prior upper bounds exceed the "
            "incumbent; all have precisely the certified all-request K16 DP "
            "input signature. The already signed exact DP integer is reused "
            "with fresh per-branch science/reward/penalty accounting. "
            "All other branches retain valid prior upper bounds. The new "
            "<=14 certificate covers every lower award count."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-fifteen", type=Path, default=PRIOR_FIFTEEN)
    parser.add_argument("--diagnostic", type=Path, default=DIAGNOSTIC)
    parser.add_argument("--fourteen", type=Path, default=FOURTEEN)
    parser.add_argument("--k16-source", type=Path, default=K16_SOURCE)
    parser.add_argument("--k16-key-cert", type=Path, default=K16_KEY_CERT)
    parser.add_argument("--prices", type=Path, default=projection.PRICE_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.prior_fifteen, args.diagnostic, args.fourteen,
                     args.k16_source, args.k16_key_cert, args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "refined_branch_count": result["refined_branch_count"],
        "exactly_fifteen_upper_cents": result["exactly_fifteen_upper_cents"],
        "at_most_fifteen_upper_cents": result["at_most_fifteen_upper_cents"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
