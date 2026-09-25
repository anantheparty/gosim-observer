#!/usr/bin/env python3
"""Refine 14 exact-16 branches through one shared K13 projected DP."""

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
import bounds_sixteen_request_k13_targeted as initial
from bounds_request_unconditional import _exact_cents, _request_is_excused_if_missed


ROOT = projection13.ROOT
PRIOR_SIXTEEN = ROOT / "results" / "practice_sixteen_request_residual.json"
PRIOR_FIFTEEN = ROOT / "results" / "practice_fifteen_request_residual.json"
DEFAULT_OUT = ROOT / "results" / "practice_sixteen_request_grouped_k13.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _branch_spec(data: dict, choices: list, instants: np.ndarray,
                 missed_request_id: str, rq0004_branch: int) -> dict:
    scorer = data["scorer"]
    selected = {}
    reward_cents = 0
    latest_release = float("-inf")
    for request, options in choices:
        if request.request_id == missed_request_id:
            continue
        option = rq0004_branch if request.request_id == "RQ0004" else 0
        selected[request.request_id] = tuple(options[option])
        reward_cents += _exact_cents(request.completion_reward)
        latest_release = max(latest_release, request.available_from_utc.timestamp())
    if len(selected) != 16:
        raise AssertionError("branch does not earn exactly sixteen rewards")
    if "RQ0004" not in selected:
        selected["RQ0004"] = ()
    deadlines = {}
    for request_id, tiles in selected.items():
        deadline = scorer.requests[request_id].deadline_utc.timestamp()
        for tile_id in tiles:
            deadlines[tile_id] = min(deadline, deadlines.get(tile_id, deadline))
    missed = scorer.requests[missed_request_id]
    miss_cents = (
        _exact_cents(missed.miss_penalty)
        if missed.deadline_utc.timestamp() <= latest_release
        and not _request_is_excused_if_missed(scorer, missed)
        else 0
    )
    key_deadline_units = tuple(
        int(np.searchsorted(instants, deadlines[key], side="left"))
        if key in deadlines else data["n"]
        for key in initial.KEYS
    )
    mandatory_key_mask = sum(1 << j for j, key in enumerate(initial.KEYS)
                             if key in deadlines)
    required_key_mask = sum(
        1 << j for j, key in enumerate(initial.KEYS)
        if scorer.tiles[key].scheduling_class == "REQUIRED"
    )
    return {
        "missed_request": missed_request_id,
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


def _external_cents(data: dict, spec: dict, instants: np.ndarray,
                    arc_starts: np.ndarray, indices_by_tile: list[np.ndarray]) -> int:
    external = int(data["prices"].sum())
    keys = set(initial.KEYS)
    deadlines = spec["deadlines"]
    for tile_index, tile_id in enumerate(data["tile_ids"]):
        if tile_id in keys:
            continue
        if tile_id not in deadlines:
            external += int(data["tile_residual_max"][tile_index])
            continue
        deadline_unit = int(np.searchsorted(
            instants, deadlines[tile_id], side="left"
        ))
        indices = indices_by_tile[tile_index]
        eligible = indices[arc_starts[indices] < deadline_unit]
        if len(eligible) == 0:
            raise AssertionError(f"mandatory non-key tile has no arc: {tile_id}")
        external += int(np.max(data["complete_reduced"][eligible]))
    return external


def certify(prior_sixteen_path: Path, prior_fifteen_path: Path,
            prices_path: Path) -> dict:
    started = time.monotonic()
    old16 = json.loads(prior_sixteen_path.read_text())
    old15 = json.loads(prior_fifteen_path.read_text())
    data, audit = projection13._load_audited_data(prices_path)
    choices, instants, arc_starts, _, _ = sixteen10._certified_inputs(data)
    if (old16["capacity_price_sha256"] != audit["price_sha256"]
            or old15["capacity_price_sha256"] != audit["price_sha256"]
            or old16["keys"] != list(initial.KEYS)
            or old15["keys"] != list(initial.KEYS)
            or old16["theta_uniform_cents"] != initial.THETA_CENTS
            or old15["theta_uniform_cents"] != initial.THETA_CENTS):
        raise AssertionError("prior upper bounds do not use the audited K13 model")
    rows = old16["merged_branch_rows"]
    if (len(rows) != 33 or len({(row["missed_request"], row["rq0004_branch"])
                                for row in rows}) != 33):
        raise AssertionError("old 33-branch partition changed")
    threshold = int(old15["at_most_fifteen_upper_cents"])
    if threshold != 2128955:
        raise AssertionError("new <=15 bound changed")
    targets = [row for row in rows if row["merged_upper_cents"] > threshold]
    if len(targets) != 14:
        raise AssertionError("targeted exact-16 branch count changed")
    specs = [_branch_spec(data, choices, instants,
                          row["missed_request"], row["rq0004_branch"])
             for row in targets]
    signatures = [(
        spec["earliest_terminal_unit"], spec["key_deadline_units"],
        spec["mandatory_key_mask"], spec["required_key_mask"],
    ) for spec in specs]
    if len(set(signatures)) != 1:
        raise AssertionError("14 target branches cannot share one projected DP")
    signature = signatures[0]
    signature_payload = {
        "keys": list(initial.KEYS),
        "theta_uniform_cents": initial.THETA_CENTS,
        "capacity_price_sha256": audit["price_sha256"],
        "projection_certificate_sha256": audit["projection_certificate_sha256"],
        "earliest_terminal_unit": signature[0],
        "key_deadline_units": list(signature[1]),
        "mandatory_key_mask": signature[2],
        "required_key_mask": signature[3],
    }
    signature_sha = hashlib.sha256(json.dumps(
        signature_payload, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()

    representative = specs[0]
    full = projection13._conditional_bound(
        data,
        {
            "branches": [representative["selected"]],
            "deadlines_by_branch": [representative["deadlines"]],
            "instants": instants,
            "arc_starts": arc_starts,
            "earliest_terminal_unit": representative["earliest_terminal_unit"],
        },
        initial.KEYS, initial.THETA_CENTS, 0,
    )
    if (not full["feasible_relaxation"]
            or tuple(full["key_deadline_unit"]) != signature[1]
            or full["mandatory_key_mask"] != signature[2]
            or full["required_key_mask"] != signature[3]):
        raise AssertionError("representative full DP disagrees with grouped signature")
    theta_constant = initial.THETA_CENTS * (len(data["tile_ids"]) - len(initial.KEYS))
    if full["theta_constant_cents"] != theta_constant:
        raise AssertionError("non-key theta constant changed")
    indices_by_tile = [np.flatnonzero(data["complete_tile"] == tile_index)
                       for tile_index in range(len(data["tile_ids"]))]
    external_by_key = {}
    refinements = []
    for old, spec in zip(targets, specs):
        key = (old["missed_request"], old["rq0004_branch"])
        external = _external_cents(data, spec, instants, arc_starts, indices_by_tile)
        external_by_key[key] = external
        total = (external + spec["reward_cents"] + theta_constant
                 + int(full["dp_cents"]) - spec["miss_cents"])
        adjusted = min(int(old["merged_upper_cents"]), total)
        refinement = {
            "missed_request": old["missed_request"],
            "rq0004_branch": old["rq0004_branch"],
            "prior_upper_cents": old["merged_upper_cents"],
            "shared_dp_signature_sha256": signature_sha,
            "external_cents": external,
            "selected_reward_cents": spec["reward_cents"],
            "unavoidable_miss_cents": spec["miss_cents"],
            "theta_constant_cents": theta_constant,
            "shared_dp_cents": full["dp_cents"],
            "thirteen_key_upper_cents": total,
            "merged_upper_cents": adjusted,
        }
        refinements.append(refinement)
        print(json.dumps({
            "missed_request": key[0], "rq0004_branch": key[1],
            "prior_upper_cents": old["merged_upper_cents"],
            "thirteen_key_upper_cents": total,
        }), flush=True)

    rep_key = (representative["missed_request"], representative["rq0004_branch"])
    rep_refinement = next(row for row in refinements
                          if (row["missed_request"], row["rq0004_branch"]) == rep_key)
    full_adjusted = (int(full["conditional_upper_cents"])
                     - (int(data["request_cents"]) - representative["reward_cents"])
                     - representative["miss_cents"])
    if (full["external_cents"] != external_by_key[rep_key]
            or full_adjusted != rep_refinement["thirteen_key_upper_cents"]):
        raise AssertionError("representative full DP differs by at least one cent")

    refined_by_key = {(r["missed_request"], r["rq0004_branch"]): r
                      for r in refinements}
    merged_rows = []
    for old in rows:
        key = (old["missed_request"], old["rq0004_branch"])
        new = refined_by_key.get(key)
        merged_rows.append({
            "missed_request": key[0],
            "rq0004_branch": key[1],
            "prior_upper_cents": old["merged_upper_cents"],
            "thirteen_key_upper_cents": (
                new["thirteen_key_upper_cents"] if new else None
            ),
            "merged_upper_cents": (
                new["merged_upper_cents"] if new else old["merged_upper_cents"]
            ),
        })
    exactly16 = max(row["merged_upper_cents"] for row in merged_rows)
    at_most16 = max(threshold, exactly16)
    if at_most16 > old16["at_most_sixteen_upper_cents"]:
        raise AssertionError("grouped refinement weakened existing bound")
    return {
        "scope": "dev-reference; all valid traces with at most 16 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "prior_sixteen_certificate_sha256": _sha(prior_sixteen_path),
        "prior_fifteen_certificate_sha256": _sha(prior_fifteen_path),
        "shared_dp_signature": signature_payload,
        "shared_dp_signature_sha256": signature_sha,
        "representative_branch": {"missed_request": rep_key[0],
                                  "rq0004_branch": rep_key[1]},
        "representative_full_dp": full,
        "representative_full_adjusted_upper_cents": full_adjusted,
        "shared_dp_evaluations": 1,
        "branch_count": len(merged_rows),
        "refined_branch_count": len(refinements),
        "refinements": refinements,
        "merged_branch_rows": merged_rows,
        "at_most_fifteen_upper_cents": threshold,
        "exactly_sixteen_upper_cents": exactly16,
        "at_most_sixteen_upper_cents": at_most16,
        "branches_above_at_most_fifteen": [
            row for row in merged_rows if row["merged_upper_cents"] > threshold
        ],
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection13._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "All 14 unresolved exactly-16 branches share the complete K13 DP "
            "input signature (keys, prices, theta, required/mandatory masks, "
            "key deadlines, terminal release). The audited full DP is solved "
            "once. Each branch independently recomputes non-key external "
            "science envelopes and request reward/miss terms in integer cents. "
            "The representative branch agrees with the full evaluator to "
            "the cent. Other 19 branches retain valid prior bounds."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-sixteen", type=Path, default=PRIOR_SIXTEEN)
    parser.add_argument("--prior-fifteen", type=Path, default=PRIOR_FIFTEEN)
    parser.add_argument("--prices", type=Path, default=projection13.PRICE_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.prior_sixteen, args.prior_fifteen, args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "shared_dp_evaluations": result["shared_dp_evaluations"],
        "refined_branch_count": result["refined_branch_count"],
        "exactly_sixteen_upper_cents": result["exactly_sixteen_upper_cents"],
        "at_most_sixteen_upper_cents": result["at_most_sixteen_upper_cents"],
        "branches_above_at_most_fifteen": result["branches_above_at_most_fifteen"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
