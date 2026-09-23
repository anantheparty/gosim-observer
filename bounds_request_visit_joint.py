#!/usr/bin/env python3
"""Audit a request-visit-aware capacity bound on the public practice instance.

For each non-key tile, the local dynamic program selects its first successful
science arc and one distinct tagged witness arc per earned request. A first arc
may itself be one of those witnesses. Every selected arc pays its saved
nonnegative time-capacity price once. Cross-tile conflicts are then relaxed.

This script evaluates the all-request branches. The existing exhaustive
request-subset certificate bounds every branch; the new per-branch value can
only decrease, so equality at the old maximizer proves that this fixed price
certificate cannot improve the existing unconditional upper bound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

import bounds_practice_projection as projection
from bounds_request_conditioned import PRACTICE, ROOT, request_branches


KEY_TILES = ("T00018", "T00029", "T00030", "T00031")
NEG = -(10**15)


def tile_value(
    starts: np.ndarray,
    ends: np.ndarray,
    reduced: np.ndarray,
    price_prefix: np.ndarray,
    instants: np.ndarray,
    requests: list,
) -> int | None:
    """Exact local maximum for zero, one or two requested tagged visits.

    All complete arcs of one tile have one fixed nominal duration. Candidate
    starts are sorted. The first successful arc may precede all tagged visits
    or be the earliest tagged visit. Each tagged visit has its own request id.
    """
    if len(requests) > 2:
        raise ValueError("this practice-specific DP supports at most two tags per tile")
    if len(starts) == 0:
        return None if requests else 0
    if np.any(starts[1:] < starts[:-1]):
        raise ValueError("tile arcs must be sorted by start")
    durations = ends - starts
    duration = int(durations[0])
    if np.any(durations != duration):
        raise ValueError("tile exposure duration is not constant")
    cost = price_prefix[ends] - price_prefix[starts]
    quality = reduced + cost
    if not requests:
        return max(0, int(reduced.max()))

    # Last earlier arc with end <= the current arc's start.
    last_prior = np.searchsorted(starts, starts - duration, side="right") - 1
    prefix_first = np.maximum.accumulate(reduced)
    best_prior = np.full(len(starts), NEG, dtype=np.int64)
    valid_prior = last_prior >= 0
    best_prior[valid_prior] = prefix_first[last_prior[valid_prior]]

    one_tag: dict[str, np.ndarray] = {}
    for request in requests:
        valid = (
            (instants[starts] >= request.available_from_utc.timestamp())
            & (instants[starts] < request.deadline_utc.timestamp())
        )
        values = np.full(len(starts), NEG, dtype=np.int64)
        values[valid] = np.maximum(
            quality[valid], best_prior[valid]
        ) - cost[valid]
        one_tag[request.request_id] = values
    if len(requests) == 1:
        best = int(one_tag[requests[0].request_id].max())
        return None if best == NEG else best

    order_best: list[int] = []
    for first, second in (requests, requests[::-1]):
        prefix = np.maximum.accumulate(one_tag[first.request_id])
        prior = np.full(len(starts), NEG, dtype=np.int64)
        prior[valid_prior] = prefix[last_prior[valid_prior]]
        valid_second = one_tag[second.request_id] != NEG
        values = np.full(len(starts), NEG, dtype=np.int64)
        values[valid_second] = prior[valid_second] - cost[valid_second]
        # Negative infinity must remain exact for impossible predecessors.
        values[prior == NEG] = NEG
        order_best.append(int(values.max()))
    best = max(order_best)
    return None if best == NEG else best


def certify(prices_path: Path) -> dict:
    old = json.loads(
        (ROOT / "results" / "practice_request_unconditional.json").read_text()
    )
    previous = json.loads(
        (ROOT / "results" / "practice_request_projection.json").read_text()
    )
    digest = hashlib.sha256(prices_path.read_bytes()).hexdigest()
    if (old["capacity_price_sha256"] != digest
            or previous["price_sha256"] != digest):
        raise AssertionError("capacity price file differs from audited certificates")
    if old["unconditional_upper_bound_cents"] != 2_252_473:
        raise AssertionError("previous unconditional maximum changed")
    data = projection.build_data(PRACTICE, prices_path, audit=False)
    if data["impossible_requests"] != ["RQ0015"]:
        raise AssertionError("impossible-request set changed")
    scorer = data["scorer"]
    requests_with_options = request_branches(scorer, data["impossible_requests"])
    if len(requests_with_options) != 17:
        raise AssertionError("expected seventeen earnable requests")
    base = projection.calculate(data, list(KEY_TILES), 134)
    if base["total_upper_bound_cents"] != old["resource_and_wait_base_cents_without_request_rewards"] + data["request_cents"]:
        raise AssertionError("projected-wait base changed")

    instants = np.fromiter(
        (slot.timestamp_utc.timestamp() + 150 * k
         for slot in scorer.slots for k in range(6)),
        dtype=np.float64,
        count=data["n"],
    )
    starts_all = np.repeat(
        np.arange(data["n"], dtype=np.int32),
        np.diff(data["complete_ptr"]),
    )
    prefix = np.empty(data["n"] + 1, dtype=np.int64)
    prefix[0] = 0
    np.cumsum(data["prices"], out=prefix[1:])
    by_tile = {}
    for i, tile_id in enumerate(data["tile_ids"]):
        if tile_id in KEY_TILES:
            continue
        sel = data["complete_tile"] == i
        by_tile[tile_id] = (
            starts_all[sel],
            data["complete_end"][sel],
            data["complete_reduced"][sel],
            int(data["tile_residual_max"][i]),
        )

    branches = []
    for choice_t4 in ("T00004", "T00012"):
        needed = defaultdict(list)
        for request, options in requests_with_options:
            selected = (
                (choice_t4,) if request.request_id == "RQ0004"
                else options[0]
            )
            for tile_id in selected:
                if tile_id not in KEY_TILES:
                    needed[tile_id].append(request)
        rows = []
        total_old_loss = 0
        total_joint_loss = 0
        for tile_id, requests in sorted(needed.items()):
            starts, ends, reduced, free = by_tile[tile_id]
            earliest_deadline = min(r.deadline_utc.timestamp() for r in requests)
            before = reduced[instants[starts] < earliest_deadline]
            old_value = int(before.max()) if len(before) else None
            joint_value = tile_value(
                starts, ends, reduced, prefix, instants, requests
            )
            if old_value is None or joint_value is None:
                raise AssertionError("all-earned branch unexpectedly infeasible")
            if joint_value > old_value:
                raise AssertionError("joint local value exceeded old deadline envelope")
            total_old_loss += free - old_value
            total_joint_loss += free - joint_value
            rows.append({
                "tile_id": tile_id,
                "request_ids": [r.request_id for r in requests],
                "free_reduced_cents": free,
                "old_deadline_reduced_cents": old_value,
                "joint_reduced_cents": joint_value,
                "extra_joint_loss_cents": old_value - joint_value,
            })
        constant = old["resource_and_wait_base_cents_without_request_rewards"]
        reward = int(data["request_cents"])
        old_branch_cents = constant + reward - total_old_loss
        joint_branch_cents = constant + reward - total_joint_loss
        matching = [
            item for item in previous["branches"]
            if item["choice_by_request"] == {"RQ0004": [choice_t4]}
        ]
        if len(matching) != 1 or matching[0]["total_upper_bound_cents"] != old_branch_cents:
            raise AssertionError("old per-branch result did not reproduce")
        branches.append({
            "rq0004_choice": choice_t4,
            "old_branch_upper_cents": old_branch_cents,
            "joint_branch_upper_cents": joint_branch_cents,
            "old_loss_cents": total_old_loss,
            "joint_loss_cents": total_joint_loss,
            "tiles": rows,
        })
    best = max(branches, key=lambda row: row["joint_branch_upper_cents"])
    if best["joint_branch_upper_cents"] != old["unconditional_upper_bound_cents"]:
        raise AssertionError(
            "all-earned branch no longer witnesses the old maximum; "
            "enumerate every awarded subset before claiming a new global bound"
        )
    return {
        "scope": "public dev-reference, all seventeen earnable requests",
        "price_sha256": digest,
        "positive_price_units": int(np.count_nonzero(data["prices"])),
        "time_units": int(data["n"]),
        "complete_arcs": int(data["complete_arc_count"]),
        "previous_unconditional_upper_cents": int(old["unconditional_upper_bound_cents"]),
        "best_all_earned_joint_branch_cents": int(best["joint_branch_upper_cents"]),
        "certified_new_unconditional_upper_cents": int(old["unconditional_upper_bound_cents"]),
        "strict_improvement_cents": 0,
        "branches": branches,
        "proof_note": (
            "Every awarded subset and RQ0004 branch has a joint per-tile "
            "maximum at most its old deadline-only maximum, since capacity "
            "prices are nonnegative and the first arc precedes every selected "
            "tagged witness. The prior exhaustive subset certificate bounds "
            "all branches by its saved unconditional maximum. If an all-earned "
            "branch attains that maximum, the refined bound is equal to it."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prices", type=Path,
        default=ROOT / "runs" / "practice_bound" / "resource_prices.npz",
    )
    parser.add_argument(
        "--out", type=Path,
        default=ROOT / "results" / "practice_request_visit_joint.json",
    )
    args = parser.parse_args()
    result = certify(args.prices)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "previous_upper": result["previous_unconditional_upper_cents"] / 100,
        "joint_upper": result["certified_new_unconditional_upper_cents"] / 100,
        "strict_improvement_cents": result["strict_improvement_cents"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
