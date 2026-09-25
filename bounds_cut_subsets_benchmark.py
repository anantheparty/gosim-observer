#!/usr/bin/env python3
"""Audited all-request-subset bounds for one non-key completion-time cut.

The 8-key time-path DP is evaluated once for each child.  Given a request
reward subset, all non-key first-visit science terms separate after pricing
capacity.  The target tile's first-visit envelope is restricted by its child;
the remaining request deadlines are handled exactly as in
bounds_request_unconditional.py.  No request subset is assumed in advance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import bounds_completion_cut_pilot as cut
import bounds_practice_projection as projection
from bounds_request_conditioned import PRACTICE, ROOT, request_branches
from bounds_request_unconditional import _exact_cents, _request_is_excused_if_missed


INCUMBENT_SCORE_MICRO = 21119494551


def _request_setup(data: dict, instants: np.ndarray, arc_starts: np.ndarray) -> dict:
    scorer = data["scorer"]
    choices = request_branches(scorer, data["impossible_requests"])
    requests = [request for request, _ in choices]
    request_ids = [request.request_id for request in requests]
    if len(requests) != 17 or request_ids[3] != "RQ0004":
        raise AssertionError("the published request-branch structure changed")
    ambiguous_index = request_ids.index("RQ0004")
    if len(choices[ambiguous_index][1]) != 2 or any(
        len(options) != 1 for j, (_, options) in enumerate(choices) if j != ambiguous_index
    ):
        raise AssertionError("the published request-choice structure changed")

    key_set = set(cut.KEYS)
    tile_arrays = {}
    for i, tile_id in enumerate(data["tile_ids"]):
        if tile_id in key_set:
            continue
        selected = data["complete_tile"] == i
        tile_arrays[tile_id] = (
            arc_starts[selected],
            data["complete_end"][selected],
            data["complete_reduced"][selected],
            int(data["tile_residual_max"][i]),
        )

    request_options = []
    reward = np.empty(len(requests), dtype=np.int64)
    miss = np.empty(len(requests), dtype=np.int64)
    release = np.empty(len(requests), dtype=np.float64)
    deadline_epoch = np.empty(len(requests), dtype=np.float64)
    excuse = np.empty(len(requests), dtype=np.bool_)
    needed = set()
    for j, (request, options) in enumerate(choices):
        reward[j] = _exact_cents(request.completion_reward)
        miss[j] = _exact_cents(request.miss_penalty)
        release[j] = request.available_from_utc.timestamp()
        deadline_epoch[j] = request.deadline_utc.timestamp()
        excuse[j] = _request_is_excused_if_missed(scorer, request)
        deadline_unit = int(np.searchsorted(instants, deadline_epoch[j], side="left"))
        converted = []
        for selected_tiles in options:
            requirement = tuple(
                (tile_id, deadline_unit)
                for tile_id in selected_tiles if tile_id not in key_set
            )
            converted.append(requirement)
            needed.update(requirement)
        request_options.append(converted)

    rewards_by_mask = np.zeros(1 << len(requests), dtype=np.int64)
    latest_release_by_mask = np.full(1 << len(requests), float("-inf"))
    for mask in range(1, len(rewards_by_mask)):
        low = mask & -mask
        j = low.bit_length() - 1
        previous = mask ^ low
        rewards_by_mask[mask] = rewards_by_mask[previous] + reward[j]
        latest_release_by_mask[mask] = max(latest_release_by_mask[previous], release[j])

    return {
        "requests": requests, "request_ids": request_ids,
        "ambiguous_index": ambiguous_index, "request_options": request_options,
        "reward": reward, "miss": miss, "deadline_epoch": deadline_epoch,
        "excuse": excuse, "rewards_by_mask": rewards_by_mask,
        "latest_release_by_mask": latest_release_by_mask,
        "tile_arrays": tile_arrays, "needed": needed,
    }


def _envelopes(setup: dict, target: str | None, cut_unit: int, side: str) -> tuple[dict, dict]:
    free = {}
    for tile_id, (_, ends, values, root_free) in setup["tile_arrays"].items():
        if tile_id != target:
            free[tile_id] = root_free
        else:
            allowed = ends <= cut_unit if side == "early" else ends > cut_unit
            eligible = values[allowed]
            free[tile_id] = (
                int(eligible.max()) if len(eligible) else None
            ) if side == "early" else (
                max(0, int(eligible.max())) if len(eligible) else 0
            )
    constrained = {}
    for tile_id, deadline_unit in setup["needed"]:
        starts, ends, values, _ = setup["tile_arrays"][tile_id]
        allowed = starts < deadline_unit
        if tile_id == target:
            allowed &= ends <= cut_unit if side == "early" else ends > cut_unit
        eligible = values[allowed]
        constrained[(tile_id, deadline_unit)] = (
            int(eligible.max()) if len(eligible) else None
        )
    return free, constrained


def _enumerate_subsets(
    setup: dict, target: str | None, cut_unit: int, side: str, dp_cents: int,
    data: dict, make_digest: bool = False,
) -> dict:
    free, constrained = _envelopes(setup, target, cut_unit, side)
    if any(value is None for value in free.values()):
        return {"feasible_relaxation": False, "reason": "forced early target has no successful arc"}
    base_without_request = (
        int(data["prices"].sum()) + sum(free.values())
        + cut.THETA_CENTS * (len(data["tile_ids"]) - len(cut.KEYS)) + dp_cents
    )
    n_requests = len(setup["requests"])
    ambiguous_index = setup["ambiguous_index"]
    request_options = setup["request_options"]
    miss = setup["miss"]
    deadline_epoch = setup["deadline_epoch"]
    excuse = setup["excuse"]
    request_ids = setup["request_ids"]
    rewards_by_mask = setup["rewards_by_mask"]
    latest_release_by_mask = setup["latest_release_by_mask"]
    by_count = [None] * (n_requests + 1)
    live_by_count = [0] * (n_requests + 1)
    counts = {"total": 0, "feasible": 0, "infeasible": 0,
              "above_incumbent": 0, "prunable": 0}
    survivors = []
    digest = hashlib.sha256()
    best = (-10**18, -1, -1)
    for mask in range(1 << n_requests):
        selected_indices = [j for j in range(n_requests) if mask & (1 << j)]
        latest = latest_release_by_mask[mask]
        missed = sum(
            int(miss[j]) for j in range(n_requests)
            if not (mask & (1 << j)) and not excuse[j]
            and deadline_epoch[j] <= latest
        )
        branches = (0, 1) if mask & (1 << ambiguous_index) else (0,)
        for branch in branches:
            counts["total"] += 1
            earliest_deadline = {}
            for j in selected_indices:
                option = request_options[j][branch if j == ambiguous_index else 0]
                for tile_id, deadline_unit in option:
                    earliest_deadline[tile_id] = min(
                        deadline_unit, earliest_deadline.get(tile_id, data["n"] + 1)
                    )
            regret = 0
            feasible = True
            for tile_id, deadline_unit in earliest_deadline.items():
                best_restricted = constrained[(tile_id, deadline_unit)]
                if best_restricted is None:
                    feasible = False
                    break
                regret += free[tile_id] - best_restricted
            if not feasible:
                counts["infeasible"] += 1
                if make_digest:
                    digest.update(f"{mask},{branch},infeasible\n".encode())
                continue
            counts["feasible"] += 1
            raw = base_without_request + int(rewards_by_mask[mask]) - regret
            adjusted = raw - missed
            if make_digest:
                digest.update(f"{mask},{branch},{raw},{missed},{adjusted}\n".encode())
            counts["above_incumbent" if adjusted * 10000 > INCUMBENT_SCORE_MICRO
                   else "prunable"] += 1
            if adjusted * 10000 > INCUMBENT_SCORE_MICRO:
                live_by_count[len(selected_indices)] += 1
                survivors.append({
                    "mask": mask, "rq0004_branch": branch,
                    "rq0004_tile": ("T00004" if branch == 0 else "T00012")
                    if mask & (1 << ambiguous_index) else None,
                    "upper_cents": adjusted,
                    "unawarded_request_ids": [
                        request_ids[j] for j in range(n_requests) if not mask & (1 << j)
                    ],
                })
            awarded_count = len(selected_indices)
            if by_count[awarded_count] is None or adjusted > by_count[awarded_count][0]:
                by_count[awarded_count] = (adjusted, mask, branch)
            if adjusted > best[0]:
                best = (adjusted, mask, branch)

    def describe(row):
        value, mask, branch = row
        return {
            "upper_cents": value, "mask": mask, "rq0004_branch": branch,
            "unawarded_request_ids": [
                request_ids[j] for j in range(n_requests) if not mask & (1 << j)
            ],
        }

    return {
        "feasible_relaxation": True, "side": side,
        "base_without_request_cents": base_without_request,
        "dp_cents": dp_cents, "target_free_envelope_cents": free.get(target),
        "best": describe(best),
        "best_by_awarded_count": [describe(row) for row in by_count],
        "above_incumbent_by_awarded_count": live_by_count,
        "counts": counts, "survivors": survivors,
        "branch_table_sha256": digest.hexdigest() if make_digest else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="T00004")
    parser.add_argument("--cut", type=int, default=20000)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "results" / "completion_cut_subsets_benchmark.json")
    args = parser.parse_args()
    if args.target in cut.KEYS:
        raise ValueError("target must be a non-key tile")
    old = json.loads(cut.UNCONDITIONAL_CERT.read_text())
    price_sha = hashlib.sha256(cut.PRICE_PATH.read_bytes()).hexdigest()
    if old["capacity_price_sha256"] != price_sha:
        raise AssertionError("saved request-subset certificate uses other prices")
    data = projection.build_data(PRACTICE, cut.PRICE_PATH, args.audit)
    if data["complete_arc_count"] != 918757 or data["partial_arc_count"] != 850:
        raise AssertionError("published arc catalog changed")
    base = projection.calculate(data, list(cut.KEYS), cut.THETA_CENTS)
    if base["total_upper_bound_cents"] != old["resource_and_wait_base_cents_without_request_rewards"] + data["request_cents"]:
        raise AssertionError("root projection differs from published subset certificate")
    instants = cut._instants(data)
    arc_starts = np.repeat(np.arange(data["n"], dtype=np.int32),
                           np.diff(data["complete_ptr"]))
    setup = _request_setup(data, instants, arc_starts)
    root = _enumerate_subsets(setup, None, args.cut, "root",
                              base["projected_dp_cents"], data, True)
    if (root["best"]["upper_cents"] != old["unconditional_upper_bound_cents"]
            or root["branch_table_sha256"] != old["branch_table_sha256"]):
        raise AssertionError("all request subsets did not reproduce root certificate")
    prepared = cut._prepare(data, args.target, args.cut, instants)
    no_mandatory = np.full(len(cut.KEYS), data["n"], dtype=np.int32)
    children = {}
    for side in ("early", "late_or_never"):
        late = side == "late_or_never"
        dp = cut.cut_projected_dp(
            data["n"], data["complete_ptr"], data["complete_end"],
            data["complete_tile"], data["complete_reduced"],
            data["complete_tagged"], data["partial_ptr"], data["partial_end"],
            prepared["actionable_key"], prepared["target_actionable"],
            prepared["key_index"], prepared["required_mask"], 0,
            no_mandatory, 0, prepared["theta"], len(cut.KEYS),
            prepared["target_index"], args.cut, late,
        )
        if not late and dp != base["projected_dp_cents"]:
            raise AssertionError("unbranched DP was not reproduced")
        children[side] = _enumerate_subsets(
            setup, args.target, args.cut, side, dp, data
        )
    payload = {
        "scope": "dev-reference; complete partition by first successful target completion",
        "target": args.target, "cut_unit": args.cut,
        "price_sha256": price_sha,
        "prior_certificate_sha256": hashlib.sha256(cut.UNCONDITIONAL_CERT.read_bytes()).hexdigest(),
        "root": root, "children": children,
        "scalar_audit": data["scalar_audit"],
        "candidate_count": data["complete_arc_count"],
        "weather_interruption_arc_count": data["partial_arc_count"],
        "incumbent_score_micro": INCUMBENT_SCORE_MICRO,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"out": str(args.out), "root_cents": root["best"]["upper_cents"],
                      "children": {side: {"upper_cents": value["best"]["upper_cents"],
                                          "counts": value["counts"]}
                                   for side, value in children.items()}}, sort_keys=True))


if __name__ == "__main__":
    main()
