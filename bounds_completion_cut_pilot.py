#!/usr/bin/env python3
"""Proof-safe completion-time branch pilot for dev-reference.

Split one non-key tile's *first successful completion* at an integer cursor.
The first action is either complete by the cut, or is later/absent.  Both
children are upper-bounded using the audited eight-key projection and exact
integer-cent reduced science values.  This is a bound experiment, not a
decision-file optimizer.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
from numba import njit

import bounds_practice_projection as projection
from bounds_request_projection import calculate_conditional, conditional_projected_dp
from bounds_request_conditioned import PRACTICE, ROOT, request_branches


KEYS = ("T00018", "T00029", "T00030", "T00031", "T00024", "T00021", "T00040", "T00015")
THETA_CENTS = 140
PRICE_PATH = ROOT / "results" / "practice_global_interval_prices.npz"
PROJECTION_CERT = ROOT / "results" / "projected_wait_global_k8_certificate.json"
CONDITIONAL_CERT = ROOT / "results" / "practice_request_global_k8_conditional.json"
UNCONDITIONAL_CERT = ROOT / "results" / "practice_global_k8_unconditional.json"
NEG_INF = -(10**15)


@njit(cache=True)
def _count_bits(value: int) -> int:
    count = 0
    while value:
        value &= value - 1
        count += 1
    return count


@njit(cache=True)
def cut_projected_dp(
    n: int,
    complete_ptr: np.ndarray,
    complete_end: np.ndarray,
    complete_tile: np.ndarray,
    complete_reduced: np.ndarray,
    complete_tagged: np.ndarray,
    partial_ptr: np.ndarray,
    partial_end: np.ndarray,
    actionable_key_mask: np.ndarray,
    late_tile_actionable: np.ndarray,
    key_index: np.ndarray,
    required_key_mask: int,
    mandatory_key_mask: int,
    key_deadline_unit: np.ndarray,
    earliest_terminal_unit: int,
    theta_cents: np.ndarray,
    k: int,
    target_tile: int,
    cut_unit: int,
    late_child: bool,
) -> int:
    """The prior exact projection, adding one forced OR and an arc cut.

    In the late child, no target-tile successful exposure can end <= cut.
    Any wait at u <= cut for which the target is scorer-actionable is paid,
    unless the key-tile OR already charges the same wait.  Thus no path is
    removed or overcharged from the true late branch.
    """
    states = 1 << k
    dp = np.full((n + 1, states), NEG_INF, dtype=np.int64)
    terminal = np.full(states, NEG_INF, dtype=np.int64)
    for mask in range(states):
        if mandatory_key_mask & (~mask):
            continue
        terminal[mask] = (
            -projection.REQUIRED_MISS_CENTS
            * _count_bits(required_key_mask & (~mask))
        )
        dp[n, mask] = terminal[mask]
    for u in range(n - 1, -1, -1):
        boundary = ((u // projection.POINTS_PER_SLOT) + 1) * projection.POINTS_PER_SLOT
        for mask in range(states):
            best = terminal[mask] if u >= earliest_terminal_unit else NEG_INF
            actionable = (actionable_key_mask[u] & (~mask)) != 0
            if late_child and late_tile_actionable[u]:
                actionable = True
            wait_cost = projection.WAIT_UNIT_CENTS * (boundary - u) if actionable else 0
            future = dp[boundary, mask]
            if future > NEG_INF // 2:
                best = max(best, future - wait_cost)
            for j in range(partial_ptr[u], partial_ptr[u + 1]):
                best = max(best, dp[partial_end[j], mask])
            for j in range(complete_ptr[u], complete_ptr[u + 1]):
                tile = complete_tile[j]
                if late_child and tile == target_tile and complete_end[j] <= cut_unit:
                    continue
                bit_index = key_index[tile]
                if bit_index >= 0:
                    bit = 1 << bit_index
                    if mask & bit:
                        if not complete_tagged[j]:
                            continue
                        future = dp[complete_end[j], mask]
                        if future <= NEG_INF // 2:
                            continue
                        candidate = future
                    else:
                        if u >= key_deadline_unit[bit_index]:
                            continue
                        candidate = dp[complete_end[j], mask | bit]
                        if candidate <= NEG_INF // 2:
                            continue
                        candidate += complete_reduced[j]
                else:
                    future = dp[complete_end[j], mask]
                    if future <= NEG_INF // 2:
                        continue
                    candidate = future - (0 if complete_tagged[j] else theta_cents[tile])
                if candidate > best:
                    best = candidate
            dp[u, mask] = best
    return int(dp[0, 0])


def _instants(data: dict) -> np.ndarray:
    return np.fromiter(
        (slot.timestamp_utc.timestamp() + 150 * offset
         for slot in data["scorer"].slots for offset in range(6)),
        dtype=np.float64, count=data["n"],
    )


def _prepare(data: dict, target: str, cut: int, instants: np.ndarray) -> dict:
    if target in KEYS or target not in data["tile_ids"]:
        raise ValueError("target must be a known non-key tile")
    if not 0 <= cut < data["n"]:
        raise ValueError("cut must be a cursor in the public grid")
    target_index = data["tile_ids"].index(target)
    scorer = data["scorer"]
    tile = scorer.tiles[target]
    # Independent scorer predicate at *every* start, not just catalogued
    # successful arcs.  The Boolean is only used where first completion is
    # certainly still absent, so its fee is exactly unavoidable there.
    target_actionable = np.zeros(data["n"], dtype=np.bool_)
    for u in range(cut + 1):
        target_actionable[u] = scorer._can_complete_from(
            tile, u // projection.POINTS_PER_SLOT,
            (u % projection.POINTS_PER_SLOT) * 150,
        )
    key_index = np.full(len(data["tile_ids"]), -1, dtype=np.int8)
    actionable_key = np.zeros(data["n"], dtype=np.uint8)
    required_mask = 0
    for bit, key in enumerate(KEYS):
        key_index[data["tile_ids"].index(key)] = bit
        actionable_key[data["actionable_cache"][key]] |= 1 << bit
        if scorer.tiles[key].scheduling_class == "REQUIRED":
            required_mask |= 1 << bit
    theta = np.full(len(data["tile_ids"]), THETA_CENTS, dtype=np.int64)
    theta[key_index >= 0] = 0
    arc_starts = np.repeat(
        np.arange(data["n"], dtype=np.int32), np.diff(data["complete_ptr"])
    )
    target_arc_indices = np.flatnonzero(data["complete_tile"] == target_index)
    return {
        "target_index": target_index,
        "target_actionable": target_actionable,
        "actionable_key": actionable_key,
        "key_index": key_index,
        "required_mask": required_mask,
        "theta": theta,
        "arc_starts": arc_starts,
        "target_arc_indices": target_arc_indices,
        "actionable_before_cut_count": int(np.count_nonzero(target_actionable)),
        "cut_utc": str(np.datetime64(int(instants[cut]), "s")),
    }


def _branch_bound(
    data: dict, prepared: dict, instants: np.ndarray, target: str,
    cut: int, late_child: bool, selected_by_request: dict,
    earliest_terminal_unit: int,
) -> dict:
    scorer = data["scorer"]
    key_index = prepared["key_index"]
    deadlines: dict[str, float] = {}
    for request_id, selected in selected_by_request.items():
        deadline = scorer.requests[request_id].deadline_utc.timestamp()
        for tile in selected:
            deadlines[tile] = min(deadline, deadlines.get(tile, deadline))
    key_deadline = np.full(len(KEYS), data["n"], dtype=np.int32)
    mandatory_key_mask = 0
    for bit, key in enumerate(KEYS):
        if key in deadlines:
            mandatory_key_mask |= 1 << bit
            key_deadline[bit] = int(np.searchsorted(instants, deadlines[key], side="left"))

    external_cents = int(data["prices"].sum())
    target_envelope = None
    target_eligible_count = 0
    for i, tile_id in enumerate(data["tile_ids"]):
        if key_index[i] >= 0:
            continue
        if tile_id != target and tile_id not in deadlines:
            external_cents += int(data["tile_residual_max"][i])
            continue
        idx = np.flatnonzero(data["complete_tile"] == i)
        allowed = np.ones(len(idx), dtype=np.bool_)
        if tile_id in deadlines:
            deadline_unit = np.searchsorted(instants, deadlines[tile_id], side="left")
            allowed &= prepared["arc_starts"][idx] < deadline_unit
        if tile_id == target:
            allowed &= (
                data["complete_end"][idx] > cut
                if late_child else data["complete_end"][idx] <= cut
            )
            target_eligible_count = int(np.count_nonzero(allowed))
        if not np.any(allowed):
            if tile_id in deadlines or (tile_id == target and not late_child):
                return {"feasible_relaxation": False, "missing_tile": tile_id}
            best = 0
        else:
            best = int(np.max(data["complete_reduced"][idx[allowed]]))
            if tile_id not in deadlines and (tile_id != target or late_child):
                best = max(0, best)
        external_cents += best
        if tile_id == target:
            target_envelope = best

    dp_cents = cut_projected_dp(
        data["n"], data["complete_ptr"], data["complete_end"],
        data["complete_tile"], data["complete_reduced"],
        data["complete_tagged"], data["partial_ptr"], data["partial_end"],
        prepared["actionable_key"], prepared["target_actionable"],
        key_index, prepared["required_mask"], mandatory_key_mask,
        key_deadline, earliest_terminal_unit, prepared["theta"], len(KEYS),
        prepared["target_index"], cut, late_child,
    )
    if not late_child:
        reference_dp = conditional_projected_dp(
            data["n"], data["complete_ptr"], data["complete_end"],
            data["complete_tile"], data["complete_reduced"],
            data["complete_tagged"], data["partial_ptr"], data["partial_end"],
            prepared["actionable_key"], key_index, prepared["required_mask"],
            mandatory_key_mask, key_deadline, earliest_terminal_unit,
            prepared["theta"], len(KEYS),
        )
        if dp_cents != reference_dp:
            raise AssertionError("new DP did not reproduce original unbranched key projection")
    if dp_cents <= NEG_INF // 2:
        return {"feasible_relaxation": False, "reason": "projected path infeasible"}
    total = external_cents + int(data["request_cents"]) + int(prepared["theta"].sum()) + dp_cents
    return {
        "feasible_relaxation": True,
        "choice_by_request": {r: list(tiles) for r, tiles in selected_by_request.items()
                              if len(scorer.request_tiles[r]) != len(tiles)},
        "target_mandatory_for_request": target in deadlines,
        "target_eligible_first_arc_count": target_eligible_count,
        "target_reduced_envelope_cents": target_envelope,
        "external_science_cents": external_cents,
        "projected_dp_cents": dp_cents,
        "upper_cents_all_awarded": total,
    }


def run_pair(data: dict, target: str, cut: int, subset_ceiling: int) -> dict:
    # This also independently computes all eight key-tile scorer actionability
    # masks, allowing exact reproduction of the published root certificate.
    base = projection.calculate(data, list(KEYS), THETA_CENTS)
    instants = _instants(data)
    prepared = _prepare(data, target, cut, instants)
    choices = request_branches(data["scorer"], data["impossible_requests"])
    latest_release = max(r.available_from_utc.timestamp() for r, _ in choices)
    earliest_terminal = int(np.searchsorted(instants, latest_release, side="left"))
    baseline_rows = []
    for selected in itertools.product(*(options for _, options in choices)):
        selected_by_request = {request.request_id: tiles
                               for (request, _), tiles in zip(choices, selected)}
        baseline_rows.append(calculate_conditional(
            data, list(KEYS), THETA_CENTS, selected_by_request,
            instants, prepared["arc_starts"], earliest_terminal,
        ))
    prior = json.loads(CONDITIONAL_CERT.read_text())
    expected = [row["total_upper_bound_cents"] for row in prior["branches"]]
    observed = [row["total_upper_bound_cents"] for row in baseline_rows]
    if observed != expected:
        raise AssertionError(("published baseline not reproduced", observed, expected))
    outcome = {}
    for name, late in (("early", False), ("late_or_never", True)):
        rows = []
        for selected in itertools.product(*(options for _, options in choices)):
            selected_by_request = {request.request_id: tiles
                                   for (request, _), tiles in zip(choices, selected)}
            rows.append(_branch_bound(data, prepared, instants, target, cut, late,
                                      selected_by_request, earliest_terminal))
        feasible = [row for row in rows if row["feasible_relaxation"]]
        conditional = max((row["upper_cents_all_awarded"] for row in feasible), default=None)
        unconditional = max(subset_ceiling, conditional) if conditional is not None else subset_ceiling
        outcome[name] = {
            "request_choice_branches": rows,
            "conditional_all_awarded_upper_cents": conditional,
            "unconditional_upper_cents": unconditional,
            "prunable_at_21119_494551": unconditional * 10000 <= 21119494551,
        }
    return {
        "target": target, "cut_unit": cut, "cut_utc": prepared["cut_utc"],
        "target_actionable_starts_through_cut": prepared["actionable_before_cut_count"],
        "baseline_projection_upper_cents": base["total_upper_bound_cents"],
        "reproduced_all_awarded_choice_upper_cents": observed,
        "other_request_subsets_upper_cents": subset_ceiling,
        "children": outcome,
        "max_child_unconditional_upper_cents": max(
            outcome["early"]["unconditional_upper_cents"],
            outcome["late_or_never"]["unconditional_upper_cents"],
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", action="append", required=True,
                        help="non-key tile,cursor unit; repeat for a few pairs")
    parser.add_argument("--audit", action="store_true",
                        help="rerun exhaustive scalar arc/weather audit")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "results" / "completion_cut_pilot.json")
    args = parser.parse_args()
    old = json.loads(UNCONDITIONAL_CERT.read_text())
    old_conditional = json.loads(CONDITIONAL_CERT.read_text())
    old_projection = json.loads(PROJECTION_CERT.read_text())
    digest = hashlib.sha256(PRICE_PATH.read_bytes()).hexdigest()
    if (old["capacity_price_sha256"] != digest
            or old_conditional["price_sha256"] != digest
            or old_projection["price_sha256"] != digest):
        raise AssertionError("published certificates use different capacity prices")
    if old["unconditional_upper_bound_cents"] != 2179670:
        raise AssertionError("published unconditional baseline changed")
    subset_ceiling = max(row["upper_cents"] for row in old["best_by_awarded_count"]
                         if row["awarded_count"] < 17)
    data = projection.build_data(PRACTICE, PRICE_PATH, args.audit)
    if data["complete_arc_count"] != 918757 or data["partial_arc_count"] != 850:
        raise AssertionError("audited arc catalog changed")
    if old_projection["complete_arc_count"] != data["complete_arc_count"]:
        raise AssertionError("prior scalar audit arc count differs")
    for key in ("omitted_scalar_legal_arcs", "max_envelope_violation_cents",
                "omitted_weather_interruption_arcs"):
        if old_projection["scalar_audit"][key] != 0:
            raise AssertionError("prior scalar audit failed")
    pairs = []
    for raw in args.pair:
        target, cut_text = raw.split(",", 1)
        pairs.append((target, int(cut_text)))
    rows = [run_pair(data, tile, cut, subset_ceiling) for tile, cut in pairs]
    payload = {
        "scope": "dev-reference fixed public instance; both children cover all first-completion outcomes",
        "key_tiles": list(KEYS), "theta_cents": THETA_CENTS,
        "price_sha256": digest,
        "prior_projection_certificate_sha256": hashlib.sha256(PROJECTION_CERT.read_bytes()).hexdigest(),
        "prior_conditional_certificate_sha256": hashlib.sha256(CONDITIONAL_CERT.read_bytes()).hexdigest(),
        "prior_unconditional_certificate_sha256": hashlib.sha256(UNCONDITIONAL_CERT.read_bytes()).hexdigest(),
        "published_unconditional_upper_cents": old["unconditional_upper_bound_cents"],
        "other_request_subsets_upper_cents": subset_ceiling,
        "fresh_scalar_audit": data["scalar_audit"], "pairs": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"out": str(args.out), "pairs": [
        {"target": row["target"], "cut_unit": row["cut_unit"],
         "early_upper_cents": row["children"]["early"]["unconditional_upper_cents"],
         "late_upper_cents": row["children"]["late_or_never"]["unconditional_upper_cents"],
         "max_child_upper_cents": row["max_child_unconditional_upper_cents"]}
        for row in rows]}, sort_keys=True))


if __name__ == "__main__":
    main()
