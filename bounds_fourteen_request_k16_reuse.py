#!/usr/bin/env python3
"""Exhaustively certify <=14 awarded requests using two signed K16 DP values."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bounds_request_projection_k10 as projection
import bounds_sixteen_request_k10 as sixteen
import bounds_sixteen_request_reuse_k16 as reuse
from bounds_request_unconditional import _exact_cents, _request_is_excused_if_missed


ROOT = projection.ROOT
K8_SUBSETS = ROOT / "results" / "practice_global_k8_unconditional.json"
K16_ALL = ROOT / "results" / "practice_sixteen_request_reuse_k16.json"
K16_RQ18 = ROOT / "results" / "practice_sixteen_request_rq18_k16.json"
K16_KEYS = ROOT / "results" / "practice_request_projection_k16_ring.json"
DEFAULT_OUT = ROOT / "results" / "practice_fourteen_request_k16_reuse.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _selected_spec(data: dict, choices: list, instants: np.ndarray,
                   missed_indices: tuple[int, int, int], branch: int) -> dict:
    scorer = data["scorer"]
    missed_ids = [choices[i][0].request_id for i in missed_indices]
    selected = {}
    latest_release = float("-inf")
    reward_cents = 0
    for i, (request, options) in enumerate(choices):
        if i in missed_indices:
            continue
        option = branch if request.request_id == "RQ0004" else 0
        selected[request.request_id] = tuple(options[option])
        latest_release = max(latest_release, request.available_from_utc.timestamp())
        reward_cents += _exact_cents(request.completion_reward)
    if len(selected) != 14:
        raise AssertionError("branch does not award exactly fourteen requests")
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
    return {
        "missed_request_ids": missed_ids,
        "selected": selected,
        "deadlines": deadlines,
        "reward_cents": reward_cents,
        "miss_cents": miss_cents,
        "earliest_terminal_unit": int(np.searchsorted(
            instants, latest_release, side="left"
        )),
    }


def certify(k8_path: Path, k16_all_path: Path, k16_rq18_path: Path,
            k16_keys_path: Path, prices_path: Path) -> dict:
    started = time.monotonic()
    old = json.loads(k8_path.read_text())
    all_source = json.loads(k16_all_path.read_text())
    rq18_source = json.loads(k16_rq18_path.read_text())
    key_cert = json.loads(k16_keys_path.read_text())
    data, audit = projection._load_audited_data(prices_path)
    choices, instants, arc_starts, _, _ = sixteen._certified_inputs(data)
    request_ids = [request.request_id for request, _ in choices]
    if (old["capacity_price_sha256"] != audit["price_sha256"]
            or all_source["capacity_price_sha256"] != audit["price_sha256"]
            or rq18_source["capacity_price_sha256"] != audit["price_sha256"]
            or key_cert["certificates"]["price_sha256"] != audit["price_sha256"]
            or old["request_ids_in_mask_order"] != request_ids
            or old["key_tiles"] != list(projection.BASE_KEYS)
            or old["theta_uniform_cents"] != 140
            or all_source["reused_k16_certificate_sha256"] != _sha(k16_keys_path)
            or rq18_source["k16_key_certificate_sha256"] != _sha(k16_keys_path)):
        raise AssertionError("signed K8/K16 certificates disagree with audited data")
    keys = tuple(key_cert["cases"][0]["keys"])
    theta = int(key_cert["theta_uniform_cents"])
    if len(keys) != 16 or theta != 135:
        raise AssertionError("unexpected K16 key set or theta")
    dp_sources = [
        {"name": "all_seventeen_K16", "signature": all_source["shared_dp_signature"],
         "dp_cents": int(all_source["shared_dp_cents"]),
         "certificate_sha256": _sha(k16_all_path)},
        {"name": "RQ0018_K16", "signature": rq18_source["shared_dp_signature"],
         "dp_cents": int(rq18_source["shared_dp_cents"]),
         "certificate_sha256": _sha(k16_rq18_path)},
    ]
    if any(src["signature"]["keys"] != list(keys)
           or src["signature"]["theta_uniform_cents"] != theta
           for src in dp_sources):
        raise AssertionError("DP sources have different K16 inputs")

    # Reconstruct the signed K8 subset formula for every three-miss branch.
    # K8 key deadlines are relaxed; all non-key required first arcs have
    # their awarded-request deadlines imposed independently.
    k8_keys = set(old["key_tiles"])
    base = int(old["resource_and_wait_base_cents_without_request_rewards"])
    needed = set()
    for request, options in choices:
        deadline = int(np.searchsorted(
            instants, request.deadline_utc.timestamp(), side="left"
        ))
        for tiles in options:
            for tile in tiles:
                if tile not in k8_keys:
                    needed.add((tile, deadline))
    free_by_tile = {
        tile_id: int(data["tile_residual_max"][i])
        for i, tile_id in enumerate(data["tile_ids"])
    }
    indices_by_tile = [np.flatnonzero(data["complete_tile"] == i)
                       for i in range(len(data["tile_ids"]))]
    best_before = {}
    for tile_id, deadline in needed:
        i = data["tile_ids"].index(tile_id)
        indices = indices_by_tile[i]
        eligible = indices[arc_starts[indices] < deadline]
        value = int(np.max(data["complete_reduced"][eligible])) if len(eligible) else None
        if value is not None and value > free_by_tile[tile_id]:
            raise AssertionError("deadline-restricted science exceeds free envelope")
        best_before[(tile_id, deadline)] = value

    rows = []
    specs_by_key = {}
    for missed in itertools.combinations(range(17), 3):
        options = (0,) if 3 in missed else (0, 1)
        selected_mask = sum(1 << i for i in range(17) if i not in missed)
        for branch in options:
            spec = _selected_spec(data, choices, instants, missed, branch)
            delta = 0
            possible = True
            for tile, deadline in spec["deadlines"].items():
                if tile in k8_keys:
                    continue
                deadline_unit = int(np.searchsorted(
                    instants, deadline, side="left"
                ))
                restricted = best_before[(tile, deadline_unit)]
                if restricted is None:
                    possible = False
                    break
                delta += free_by_tile[tile] - restricted
            if not possible:
                raise AssertionError("unexpected infeasible exact-14 branch")
            old_upper = base + spec["reward_cents"] - delta - spec["miss_cents"]
            key = (selected_mask, branch)
            specs_by_key[key] = spec
            rows.append({
                "request_mask": selected_mask,
                "rq0004_branch": branch,
                "unawarded_request_ids": spec["missed_request_ids"],
                "legacy_k8_upper_cents": old_upper,
            })
    if (len(rows) != 1240 or len(specs_by_key) != 1240
            or max(r["legacy_k8_upper_cents"] for r in rows) != 2117517):
        raise AssertionError("exhaustive exact-14 K8 maximum differs")
    published_best = next(r for r in old["best_by_awarded_count"]
                          if r["awarded_count"] == 14)
    best = max(rows, key=lambda r: r["legacy_k8_upper_cents"])
    if (best["legacy_k8_upper_cents"] != published_best["upper_cents"]
            or best["request_mask"] != published_best["mask"]
            or best["rq0004_branch"] != published_best["rq0004_branch"]):
        raise AssertionError("exact-14 maximizing branch differs from published K8 certificate")

    incumbent_micro = int(sixteen.INCUMBENT_SCORE_MICRO)
    target_rows = [r for r in rows
                   if r["legacy_k8_upper_cents"] * 10000 > incumbent_micro]
    if len(target_rows) != 2:
        raise AssertionError("unexpected number of exact-14 branches above incumbent")
    theta_constant = theta * (len(data["tile_ids"]) - len(keys))
    refinements = {}
    for row in target_rows:
        key = (row["request_mask"], row["rq0004_branch"])
        spec = specs_by_key[key]
        inputs = {
            "deadlines_by_branch": [spec["deadlines"]],
            "instants": instants,
            "earliest_terminal_unit": spec["earliest_terminal_unit"],
        }
        signature = reuse._signature(
            data, inputs, keys, theta, audit["price_sha256"],
            audit["projection_certificate_sha256"], 0,
        )
        matches = [src for src in dp_sources if src["signature"] == signature]
        if len(matches) != 1:
            raise AssertionError("high exact-14 branch lacks a unique signed K16 DP")
        source = matches[0]
        external = reuse._external_cents(
            data, spec["deadlines"], keys, instants, arc_starts,
            indices_by_tile,
        )
        new_upper = (external + spec["reward_cents"] + theta_constant
                     + source["dp_cents"] - spec["miss_cents"])
        refinements[key] = {
            "request_mask": key[0],
            "rq0004_branch": key[1],
            "unawarded_request_ids": spec["missed_request_ids"],
            "legacy_k8_upper_cents": row["legacy_k8_upper_cents"],
            "dp_source": source["name"],
            "dp_source_certificate_sha256": source["certificate_sha256"],
            "external_cents": external,
            "selected_reward_cents": spec["reward_cents"],
            "unavoidable_miss_cents": spec["miss_cents"],
            "theta_constant_cents": theta_constant,
            "shared_dp_cents": source["dp_cents"],
            "k16_upper_cents": new_upper,
            "merged_upper_cents": min(row["legacy_k8_upper_cents"], new_upper),
        }
    merged_rows = []
    for row in rows:
        key = (row["request_mask"], row["rq0004_branch"])
        new = refinements.get(key)
        merged_rows.append({
            **row,
            "k16_upper_cents": new["k16_upper_cents"] if new else None,
            "merged_upper_cents": new["merged_upper_cents"]
                                  if new else row["legacy_k8_upper_cents"],
        })
    exact14 = max(r["merged_upper_cents"] for r in merged_rows)
    at_most13 = max(int(r["upper_cents"])
                    for r in old["best_by_awarded_count"]
                    if r["awarded_count"] <= 13)
    at_most14 = max(exact14, at_most13)
    if at_most14 * 10000 >= incumbent_micro:
        raise AssertionError("the <=14 case is not proved strictly below incumbent")
    return {
        "scope": "dev-reference; all valid traces with at most 14 awarded requests",
        "capacity_price_sha256": audit["price_sha256"],
        "scalar_audit": audit["scalar_audit"],
        "legacy_k8_certificate_sha256": _sha(k8_path),
        "k16_key_certificate_sha256": _sha(k16_keys_path),
        "dp_sources": dp_sources,
        "fresh_dp_evaluations": 0,
        "incumbent_score_micro": incumbent_micro,
        "branch_count": len(merged_rows),
        "refined_branch_count": len(refinements),
        "refinements": list(refinements.values()),
        "merged_branch_rows": merged_rows,
        "at_most_thirteen_upper_cents": at_most13,
        "exactly_fourteen_upper_cents": exact14,
        "at_most_fourteen_upper_cents": at_most14,
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_mib": projection._rss_mib(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "proof_note": (
            "All 1,240 exact-14 three-miss witness cases are independently "
            "enumerated using the signed K8 subset relaxation, whose maximum "
            "and argmax are reproduced. Only two legacy bounds exceed the "
            "incumbent. Each has exactly the complete K16 DP input signature "
            "of one previously signed source; source DP values are reused "
            "without new solves. Non-key science and request terms are "
            "recomputed separately in integer cents. The remaining legacy "
            "bounds and the signed <=13 ceiling are strictly below incumbent."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k8-subsets", type=Path, default=K8_SUBSETS)
    parser.add_argument("--k16-all", type=Path, default=K16_ALL)
    parser.add_argument("--k16-rq18", type=Path, default=K16_RQ18)
    parser.add_argument("--k16-keys", type=Path, default=K16_KEYS)
    parser.add_argument("--prices", type=Path, default=projection.PRICE_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = certify(args.k8_subsets, args.k16_all, args.k16_rq18,
                     args.k16_keys, args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        result, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n")
    print(json.dumps({
        "branch_count": result["branch_count"],
        "refined_branch_count": result["refined_branch_count"],
        "exactly_fourteen_upper_cents": result["exactly_fourteen_upper_cents"],
        "at_most_fourteen_upper_cents": result["at_most_fourteen_upper_cents"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
