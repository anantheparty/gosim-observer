#!/usr/bin/env python3
"""Certified one-tile completion-time split of the eleven-key projection.

For a non-key tile t and integer cursor c, every real schedule belongs to
exactly one child: its first successful t observation ends by c, or it does
not.  The early child restricts t's independent first-visit envelope.  The
late child also removes t's successful arcs ending by c and charges waits
through c where the still-uncompleted t is scorer-actionable.  The latter is
an exact extra OR in the existing key-state time DP.  This program bounds the
two possible RQ0004 choices when all 17 earnable requests are awarded; the
separately certified <=16 case is combined at the end.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from numba import njit

import bounds_request_projection_k10 as projection
from pilot_k11_projection import BASE_K10


ROOT = projection.ROOT
KEYS = BASE_K10 + ("T00016",)
THETA_CENTS = 135
K11_CERT = ROOT / "results" / "practice_request_projection_k11_pilot.json"
SIXTEEN_CERT = ROOT / "results" / "practice_sixteen_request_k10.json"
NEG_INF = -(10**15)


@njit(cache=True)
def _popcount(value: int) -> int:
    count = 0
    while value:
        value &= value - 1
        count += 1
    return count


@njit(cache=True)
def cut_dp16(
    n: int,
    complete_ptr: np.ndarray,
    complete_end: np.ndarray,
    complete_tile: np.ndarray,
    complete_reduced: np.ndarray,
    complete_tagged: np.ndarray,
    partial_ptr: np.ndarray,
    partial_end: np.ndarray,
    actionable_key_mask: np.ndarray,
    target_actionable: np.ndarray,
    key_index: np.ndarray,
    required_key_mask: int,
    mandatory_key_mask: int,
    key_deadline_unit: np.ndarray,
    earliest_terminal_unit: int,
    theta_cents: np.ndarray,
    k: int,
    target_tile_index: int,
    cut_unit: int,
) -> int:
    """Relaxed late-child path DP with exact OR wait and forbidden early arcs."""
    states = 1 << k
    dp = np.full((n + 1, states), NEG_INF, dtype=np.int64)
    terminal = np.full(states, NEG_INF, dtype=np.int64)
    for mask in range(states):
        if mandatory_key_mask & (~mask):
            continue
        terminal[mask] = -projection.projection.REQUIRED_MISS_CENTS * _popcount(
            required_key_mask & (~mask)
        )
        dp[n, mask] = terminal[mask]
    for u in range(n - 1, -1, -1):
        boundary = ((u // projection.projection.POINTS_PER_SLOT) + 1) * projection.projection.POINTS_PER_SLOT
        for mask in range(states):
            best = terminal[mask] if u >= earliest_terminal_unit else NEG_INF
            actionable = (actionable_key_mask[u] & (~mask)) != 0
            if u <= cut_unit and target_actionable[u]:
                actionable = True
            wait_cost = projection.projection.WAIT_UNIT_CENTS * (boundary - u) if actionable else 0
            future = dp[boundary, mask]
            if future > NEG_INF // 2:
                best = max(best, future - wait_cost)
            for j in range(partial_ptr[u], partial_ptr[u + 1]):
                best = max(best, dp[partial_end[j], mask])
            for j in range(complete_ptr[u], complete_ptr[u + 1]):
                tile = complete_tile[j]
                if tile == target_tile_index and complete_end[j] <= cut_unit:
                    continue
                bit_index = key_index[tile]
                if bit_index >= 0:
                    bit = 1 << bit_index
                    if mask & bit:
                        if not complete_tagged[j]:
                            continue
                        candidate = dp[complete_end[j], mask]
                    else:
                        if u >= key_deadline_unit[bit_index]:
                            continue
                        candidate = dp[complete_end[j], mask | bit]
                        if candidate <= NEG_INF // 2:
                            continue
                        candidate += complete_reduced[j]
                else:
                    candidate = dp[complete_end[j], mask]
                    if candidate <= NEG_INF // 2:
                        continue
                    candidate -= 0 if complete_tagged[j] else theta_cents[tile]
                if candidate > best:
                    best = candidate
            dp[u, mask] = best
    return int(dp[0, 0])


def _setup(data: dict, inputs: dict, keys: tuple[str, ...]) -> dict:
    tile_ids = data["tile_ids"]
    key_index = np.full(len(tile_ids), -1, dtype=np.int8)
    actionable_mask = np.zeros(data["n"], dtype=np.uint16)
    required_key_mask = 0
    mandatory_key_mask_by_branch = []
    key_deadline_by_branch = []
    for bit, key in enumerate(keys):
        key_index[tile_ids.index(key)] = bit
        projection._populate_actionability(data, key)
        actionable_mask[data["actionable_cache"][key]] |= np.uint16(1 << bit)
        if data["scorer"].tiles[key].scheduling_class == "REQUIRED":
            required_key_mask |= 1 << bit
    for deadlines in inputs["deadlines_by_branch"]:
        mandatory_mask = 0
        deadline_unit = np.full(len(keys), data["n"], dtype=np.int32)
        for bit, key in enumerate(keys):
            if key in deadlines:
                mandatory_mask |= 1 << bit
                deadline_unit[bit] = int(np.searchsorted(
                    inputs["instants"], deadlines[key], side="left"
                ))
        mandatory_key_mask_by_branch.append(mandatory_mask)
        key_deadline_by_branch.append(deadline_unit)
    theta = np.full(len(tile_ids), THETA_CENTS, dtype=np.int64)
    theta[key_index >= 0] = 0
    return {
        "key_index": key_index,
        "actionable_mask": actionable_mask,
        "required_key_mask": required_key_mask,
        "mandatory_key_mask_by_branch": mandatory_key_mask_by_branch,
        "key_deadline_by_branch": key_deadline_by_branch,
        "theta": theta,
    }


def _envelope(data: dict, inputs: dict, tile: str, branch: int,
              cut_unit: int | None, early: bool) -> tuple[int | None, int]:
    arcs = inputs["tile_arc_indices"][tile]
    starts = inputs["arc_starts"][arcs]
    ends = data["complete_end"][arcs]
    values = data["complete_reduced"][arcs]
    deadline = inputs["deadlines_by_branch"][branch].get(tile)
    mandatory = deadline is not None
    if mandatory:
        deadline_unit = np.searchsorted(inputs["instants"], deadline, side="left")
        allowed = starts < deadline_unit
    else:
        allowed = np.ones(len(arcs), dtype=np.bool_)
    if cut_unit is not None:
        allowed &= ends <= cut_unit if early else ends > cut_unit
    if not np.any(allowed):
        return (None if mandatory or early else 0), 0
    envelope = int(np.max(values[allowed]))
    if not mandatory and not early:
        envelope = max(0, envelope)
    return envelope, int(np.count_nonzero(allowed))


def _static_pair(data: dict, inputs: dict, baseline: list[dict],
                 target: str, cut_unit: int) -> dict:
    early_rows = []
    late_rows = []
    base_rows = []
    eligible = []
    for branch, row in enumerate(baseline):
        old, _ = _envelope(data, inputs, target, branch, None, False)
        early, early_n = _envelope(data, inputs, target, branch, cut_unit, True)
        late, late_n = _envelope(data, inputs, target, branch, cut_unit, False)
        assert old is not None
        base_rows.append(int(row["conditional_upper_cents"]))
        early_rows.append(None if early is None else base_rows[-1] - old + early)
        late_rows.append(None if late is None else base_rows[-1] - old + late)
        eligible.append({"branch": branch, "root_envelope_cents": old,
                         "early_envelope_cents": early, "late_envelope_cents": late,
                         "early_arc_count": early_n, "late_arc_count": late_n})
    root = max(base_rows)
    early_bound = max((x for x in early_rows if x is not None), default=None)
    late_bound = max((x for x in late_rows if x is not None), default=None)
    return {
        "target": target, "cut_unit": cut_unit,
        "early_external_only_upper_cents": early_bound,
        "late_external_only_upper_cents": late_bound,
        "early_external_tightening_cents": root - early_bound if early_bound is not None else None,
        "late_external_tightening_cents": root - late_bound if late_bound is not None else None,
        "branch_envelopes": eligible,
    }


def _rank_pairs(data: dict, inputs: dict, baseline: list[dict]) -> list[dict]:
    grid = range(2500, data["n"], 2500)
    rows = []
    for tile in data["tile_ids"]:
        if tile in KEYS:
            continue
        tile_index = data["tile_ids"].index(tile)
        starts = data["starts_by_tile"][tile_index]
        for cut in grid:
            row = _static_pair(data, inputs, baseline, tile, cut)
            if row["early_external_only_upper_cents"] is None:
                continue
            actionable_before = int(np.count_nonzero(starts <= cut))
            row["actionable_start_count_through_cut"] = actionable_before
            # The late DP decides actual wait/path loss; this merely ranks
            # promising cuts.  Prefer a sizeable forced-early envelope loss.
            row["ranking_score"] = min(
                row["early_external_tightening_cents"],
                15 * actionable_before,
            )
            rows.append(row)
    rows.sort(key=lambda r: (-r["ranking_score"],
                             -r["early_external_tightening_cents"],
                             r["target"], r["cut_unit"]))
    return rows


def _late_dp(data: dict, inputs: dict, state: dict,
             target: str, cut_unit: int, branch: int) -> int:
    projection._populate_actionability(data, target)
    return cut_dp16(
        data["n"], data["complete_ptr"], data["complete_end"],
        data["complete_tile"], data["complete_reduced"],
        data["complete_tagged"], data["partial_ptr"], data["partial_end"],
        state["actionable_mask"], data["actionable_cache"][target],
        state["key_index"], state["required_key_mask"],
        state["mandatory_key_mask_by_branch"][branch],
        state["key_deadline_by_branch"][branch],
        inputs["earliest_terminal_unit"], state["theta"], len(KEYS),
        data["tile_ids"].index(target), cut_unit,
    )


def run(pairs: list[tuple[str, int]], top_n: int) -> dict:
    started = time.monotonic()
    data, certs = projection._load_audited_data(projection.PRICE_FILE)
    inputs = projection._instance_inputs(data)
    inputs["tile_arc_indices"] = {
        tile: np.flatnonzero(data["complete_tile"] == index)
        for index, tile in enumerate(data["tile_ids"])
    }
    prior = json.loads(K11_CERT.read_text())
    sixteen = json.loads(SIXTEEN_CERT.read_text())
    if (prior["certificates"]["price_sha256"] != certs["price_sha256"]
            or sixteen["capacity_price_sha256"] != certs["price_sha256"]
            or prior["all_awarded_upper_cents"] != 2157473):
        raise AssertionError("certificate chain changed")
    exactly_sixteen = max(row["upper_cents"] for row in sixteen["exactly_sixteen_rows"]
                          if row["feasible_relaxation"])
    fewer_upper = max(int(sixteen["at_most_fifteen_upper_cents"]), exactly_sixteen)
    if fewer_upper != 2145227:
        raise AssertionError("<=16 certificate changed")
    baseline = [projection._conditional_bound(data, inputs, KEYS, THETA_CENTS, j)
                for j in range(2)]
    prior_rows = prior["cases"][0]["branches"]
    if [row["conditional_upper_cents"] for row in baseline] != [
        row["conditional_upper_cents"] for row in prior_rows
    ]:
        raise AssertionError("fresh eleven-key DP failed to reproduce certificate")
    state = _setup(data, inputs, KEYS)
    ranking = _rank_pairs(data, inputs, baseline)
    if not pairs:
        distinct = set()
        for row in ranking:
            if row["target"] in distinct:
                continue
            pairs.append((row["target"], row["cut_unit"]))
            distinct.add(row["target"])
            if len(pairs) >= top_n:
                break
    for target, cut in pairs:
        if target in KEYS or target not in data["tile_ids"] or not 0 <= cut < data["n"]:
            raise ValueError("pair must be non-key tile and a valid cursor")
    cases = []
    for target, cut in pairs:
        static = _static_pair(data, inputs, baseline, target, cut)
        if static["early_external_only_upper_cents"] is None:
            # This child contains no valid first success; safely empty.
            early_cents = None
        else:
            early_cents = static["early_external_only_upper_cents"]
        late_rows = []
        for j in range(2):
            if static["branch_envelopes"][j]["late_envelope_cents"] is None:
                late_rows.append({"branch": j, "feasible_relaxation": False})
                continue
            dp = _late_dp(data, inputs, state, target, cut, j)
            if dp <= NEG_INF // 2:
                late_rows.append({"branch": j, "feasible_relaxation": False})
                continue
            dp_delta = dp - int(baseline[j]["dp_cents"])
            if dp_delta > 0:
                raise AssertionError("late child relaxed path improved over root")
            old = static["branch_envelopes"][j]["root_envelope_cents"]
            new = static["branch_envelopes"][j]["late_envelope_cents"]
            total = int(baseline[j]["conditional_upper_cents"]) - old + new + dp_delta
            late_rows.append({"branch": j, "feasible_relaxation": True,
                              "dp_cents": dp, "dp_loss_cents": -dp_delta,
                              "upper_cents": total})
        late_cents = max((r["upper_cents"] for r in late_rows
                          if r["feasible_relaxation"]), default=None)
        children = [x for x in (early_cents, late_cents) if x is not None]
        combined = max(children) if children else None
        if combined is None:
            raise AssertionError("both children unexpectedly empty")
        cases.append({**static, "late_branch_rows": late_rows,
                      "early_upper_cents": early_cents,
                      "late_or_never_upper_cents": late_cents,
                      "all_seventeen_upper_cents": combined,
                      "unconditional_upper_cents": max(combined, fewer_upper),
                      "tightening_cents": prior["all_awarded_upper_cents"] - combined})
        print(json.dumps({"target": target, "cut": cut, "early": early_cents,
                          "late": late_cents, "all17": combined,
                          "elapsed_seconds": time.monotonic() - started}), flush=True)
    best = min(cases, key=lambda row: row["all_seventeen_upper_cents"])
    return {
        "scope": "public dev-reference; exhaustive two-child first-success split",
        "price_sha256": certs["price_sha256"],
        "eleven_key_certificate_sha256": hashlib.sha256(K11_CERT.read_bytes()).hexdigest(),
        "sixteen_certificate_sha256": hashlib.sha256(SIXTEEN_CERT.read_bytes()).hexdigest(),
        "audited_arc_count": data["complete_arc_count"],
        "audited_partial_arc_count": data["partial_arc_count"],
        "scalar_audit": certs["scalar_audit"],
        "key_tiles": list(KEYS), "theta_cents": THETA_CENTS,
        "all_seventeen_root_upper_cents": prior["all_awarded_upper_cents"],
        "at_most_sixteen_upper_cents": fewer_upper,
        "baseline_branches": baseline,
        "ranked_static_candidates": ranking[:20],
        "tested_pairs": cases,
        "best_pair": [best["target"], best["cut_unit"]],
        "best_all_seventeen_upper_cents": best["all_seventeen_upper_cents"],
        "best_unconditional_upper_cents": max(fewer_upper, best["all_seventeen_upper_cents"]),
        "elapsed_seconds": time.monotonic() - started,
        "peak_rss_mib": projection._rss_mib(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", action="append", default=[],
                        help="non-key tile,cursor; repeat for a short pilot")
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "results" / "practice_k11_completion_cut.json")
    args = parser.parse_args()
    pairs = []
    for raw in args.pair:
        tile, cut = raw.split(",", 1)
        pairs.append((tile, int(cut)))
    if not pairs and args.top_n < 1:
        raise ValueError("top-n must be positive")
    payload = run(pairs, args.top_n)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"out": str(args.out),
                      "best_pair": payload["best_pair"],
                      "best_all_seventeen_upper_cents": payload["best_all_seventeen_upper_cents"],
                      "best_unconditional_upper_cents": payload["best_unconditional_upper_cents"],
                      "elapsed_seconds": payload["elapsed_seconds"]}, sort_keys=True))


if __name__ == "__main__":
    main()
