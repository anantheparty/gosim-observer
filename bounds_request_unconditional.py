#!/usr/bin/env python3
"""Exhaustive request-subset certificate for the public practice instance.

The telescope/waiting term uses the existing unconditional four-key projection.
For each subset of awarded requests, mandatory non-key first observations are
limited to starts before their earliest awarded-request deadline. An awarded
request's reward is added; an unawarded request's miss penalty is subtracted
only when the scorer proves it unavoidable from the awarded requests' latest
release time. Everything is evaluated in integer score cents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np

import bounds_practice_projection as projection
from bounds_request_conditioned import PRACTICE, ROOT, request_branches


KEY_TILES = ("T00018", "T00029", "T00030", "T00031")
THETA_CENTS = 134
AUDITED_PROJECTION = ROOT / "results" / "projected_wait_certificate.json"
AUDITED_CONDITIONAL = ROOT / "results" / "practice_request_projection.json"


def _exact_cents(value: float) -> int:
    cents = Decimal(100) * Decimal(str(value))
    if cents != cents.to_integral_value():
        raise ValueError(f"practice rule coefficient is not integral cents: {value}")
    return int(cents)


def _request_is_excused_if_missed(scorer, request) -> bool:
    feasible_count = sum(
        scorer._tile_has_request_opportunity(
            scorer.tiles[tile_id],
            request.available_from_utc,
            request.deadline_utc,
        )
        for tile_id in scorer.request_tiles[request.request_id]
    )
    return feasible_count < request.required_tile_count


def _verify_existing_audits(
    price_sha256: str,
    candidate_count: int,
    partial_count: int,
    base_cents: int,
) -> dict:
    projection_cert = json.loads(
        AUDITED_PROJECTION.read_text(encoding="utf-8")
    )
    conditional_cert = json.loads(
        AUDITED_CONDITIONAL.read_text(encoding="utf-8")
    )
    if projection_cert["price_sha256"] != price_sha256:
        raise AssertionError("projection audit used different capacity prices")
    if conditional_cert["price_sha256"] != price_sha256:
        raise AssertionError("conditional audit used different capacity prices")
    if projection_cert["complete_arc_count"] != candidate_count:
        raise AssertionError("complete arc count differs from scalar audit")
    if projection_cert["weather_interruption_arc_count"] != partial_count:
        raise AssertionError("partial arc count differs from scalar audit")
    expected = {
        "max_envelope_violation_cents": 0,
        "omitted_scalar_legal_arcs": 0,
        "omitted_weather_interruption_arcs": 0,
    }
    for key, value in expected.items():
        if projection_cert["scalar_audit"][key] != value:
            raise AssertionError(f"prior scalar audit did not pass: {key}")
    matching = [
        row for row in projection_cert["results"]
        if tuple(row["key_tiles"]) == KEY_TILES
        and row["theta_uniform_cents"] == THETA_CENTS
    ]
    if len(matching) != 1 or matching[0]["total_upper_bound_cents"] != base_cents:
        raise AssertionError("current projection did not reproduce audited bound")
    return {
        "projection_certificate": str(AUDITED_PROJECTION.relative_to(ROOT)),
        "projection_certificate_sha256": hashlib.sha256(
            AUDITED_PROJECTION.read_bytes()
        ).hexdigest(),
        "conditional_certificate": str(AUDITED_CONDITIONAL.relative_to(ROOT)),
        "conditional_certificate_sha256": hashlib.sha256(
            AUDITED_CONDITIONAL.read_bytes()
        ).hexdigest(),
    }


def certify(
    prices: Path,
    audit: bool,
) -> dict:
    data = projection.build_data(PRACTICE, prices, audit)
    scorer = data["scorer"]
    if scorer.mechanics or scorer.tile_anomalies:
        raise ValueError("practice certificate requires the non-anomaly scorer")
    if tuple(data["impossible_requests"]) != ("RQ0015",):
        raise AssertionError("impossible request set changed")
    price_sha256 = hashlib.sha256(prices.read_bytes()).hexdigest()
    base = projection.calculate(data, list(KEY_TILES), THETA_CENTS)
    base_cents = base["total_upper_bound_cents"]
    without_request_cents = base_cents - int(data["request_cents"])
    prior = _verify_existing_audits(
        price_sha256, data["complete_arc_count"],
        data["partial_arc_count"], base_cents,
    )

    requests_with_options = request_branches(scorer, data["impossible_requests"])
    requests = [item[0] for item in requests_with_options]
    if len(requests) != 17:
        raise AssertionError("expected exactly 17 potentially earnable requests")
    request_ids = [r.request_id for r in requests]
    ambiguous_indices = [
        j for j, (_, options) in enumerate(requests_with_options)
        if len(options) > 1
    ]
    if len(ambiguous_indices) != 1 or request_ids[ambiguous_indices[0]] != "RQ0004":
        raise AssertionError("expected only RQ0004 to have two minimum tile choices")
    ambiguous_index = ambiguous_indices[0]

    # Timestamp grid is ordered, including gaps between nights. The index of
    # the first start >= deadline implements the strict start < deadline rule.
    instants = np.fromiter(
        (
            slot.timestamp_utc.timestamp() + 150 * offset
            for slot in scorer.slots for offset in range(6)
        ),
        dtype=np.float64,
        count=data["n"],
    )
    arc_starts = np.repeat(
        np.arange(data["n"], dtype=np.int32),
        np.diff(data["complete_ptr"]),
    )
    key_set = set(KEY_TILES)
    by_tile: dict[str, tuple[np.ndarray, np.ndarray, int]] = {}
    for i, tile_id in enumerate(data["tile_ids"]):
        if tile_id in key_set:
            continue
        selected = data["complete_tile"] == i
        by_tile[tile_id] = (
            arc_starts[selected],
            data["complete_reduced"][selected],
            int(data["tile_residual_max"][i]),
        )

    # At most two options per request; no request visit count exceeds one in
    # this practice instance. A selected option imposes a necessary first-arc
    # deadline for each linked tile. K deadlines are deliberately ignored so
    # that the existing K projection remains unconditional.
    request_options: list[list[tuple[tuple[str, int], ...]]] = []
    reward_cents = np.empty(len(requests), dtype=np.int64)
    miss_cents = np.empty(len(requests), dtype=np.int64)
    release_epochs = np.empty(len(requests), dtype=np.float64)
    deadline_epochs = np.empty(len(requests), dtype=np.float64)
    excuse_if_missed = np.empty(len(requests), dtype=np.bool_)
    needed_values: set[tuple[str, int]] = set()
    for j, (request, options) in enumerate(requests_with_options):
        if not (
            request.issued_at_utc
            <= request.available_from_utc
            < request.deadline_utc
        ):
            raise ValueError("request issue/availability/deadline order changed")
        reward_cents[j] = _exact_cents(request.completion_reward)
        miss_cents[j] = _exact_cents(request.miss_penalty)
        if reward_cents[j] < 0 or miss_cents[j] < 0:
            raise ValueError("negative request coefficient invalidates certificate")
        release_epochs[j] = request.available_from_utc.timestamp()
        deadline_epochs[j] = request.deadline_utc.timestamp()
        excuse_if_missed[j] = _request_is_excused_if_missed(scorer, request)
        deadline_unit = int(
            np.searchsorted(instants, deadline_epochs[j], side="left")
        )
        converted = []
        for selected_tiles in options:
            requirements = tuple(
                (tile_id, deadline_unit)
                for tile_id in selected_tiles if tile_id not in key_set
            )
            needed_values.update(requirements)
            converted.append(requirements)
        request_options.append(converted)

    # Read each non-K tile's complete reduced-value envelope once. The value
    # may be negative: a tile required by an awarded request has no zero
    # option, and its first observation must still pay the capacity price.
    best_before: dict[tuple[str, int], int | None] = {}
    for tile_id, deadline_unit in needed_values:
        a, reduced, unconstrained = by_tile[tile_id]
        valid = reduced[a < deadline_unit]
        best = int(valid.max()) if len(valid) else None
        if best is not None and best > unconstrained:
            raise AssertionError("deadline-constrained envelope exceeds free envelope")
        best_before[(tile_id, deadline_unit)] = best

    total_masks = 1 << len(requests)
    rewards_by_mask = np.zeros(total_masks, dtype=np.int64)
    latest_release_by_mask = np.full(total_masks, float("-inf"))
    for mask in range(1, total_masks):
        least_bit = mask & -mask
        j = least_bit.bit_length() - 1
        parent = mask ^ least_bit
        rewards_by_mask[mask] = rewards_by_mask[parent] + reward_cents[j]
        latest_release_by_mask[mask] = max(
            latest_release_by_mask[parent], release_epochs[j]
        )

    all_mask = total_masks - 1
    subset_count = 0
    branch_count = 0
    infeasible_branch_count = 0
    maximum_raw = (-10**18, -1, -1)
    maximum_adjusted = (-10**18, -1, -1)
    by_awarded_count: dict[int, dict] = {}
    exactly_sixteen: list[dict] = []
    digest = hashlib.sha256()

    for mask in range(total_masks):
        subset_count += 1
        selected_indices = [
            j for j in range(len(requests)) if mask & (1 << j)
        ]
        terminal_lower_epoch = latest_release_by_mask[mask]
        unavoidable_miss_cents = sum(
            int(miss_cents[j])
            for j in range(len(requests))
            if not (mask & (1 << j))
            and not excuse_if_missed[j]
            and request_ids[j] != "RQ0015"
            and deadline_epochs[j] <= terminal_lower_epoch
        )
        choices = (0, 1) if (mask & (1 << ambiguous_index)) else (0,)
        for branch in choices:
            branch_count += 1
            earliest_deadline: dict[str, int] = {}
            for j in selected_indices:
                option = (
                    request_options[j][branch]
                    if j == ambiguous_index else request_options[j][0]
                )
                for tile_id, deadline_unit in option:
                    old = earliest_deadline.get(tile_id, data["n"] + 1)
                    if deadline_unit < old:
                        earliest_deadline[tile_id] = deadline_unit
            delta = 0
            possible = True
            for tile_id, deadline_unit in earliest_deadline.items():
                restricted = best_before[(tile_id, deadline_unit)]
                if restricted is None:
                    possible = False
                    break
                delta += by_tile[tile_id][2] - restricted
            if not possible:
                infeasible_branch_count += 1
                digest.update(f"{mask},{branch},infeasible\n".encode())
                continue
            raw = without_request_cents + int(rewards_by_mask[mask]) - delta
            adjusted = raw - unavoidable_miss_cents
            digest.update(
                f"{mask},{branch},{raw},{unavoidable_miss_cents},{adjusted}\n".encode()
            )
            if raw > maximum_raw[0]:
                maximum_raw = (raw, mask, branch)
            if adjusted > maximum_adjusted[0]:
                maximum_adjusted = (adjusted, mask, branch)
            awarded_count = len(selected_indices)
            incumbent = by_awarded_count.get(awarded_count)
            if incumbent is None or adjusted > incumbent["upper_cents"]:
                by_awarded_count[awarded_count] = {
                    "awarded_count": awarded_count,
                    "upper_cents": adjusted,
                    "mask": mask,
                    "rq0004_branch": branch,
                }
            if awarded_count == 16:
                exactly_sixteen.append({
                    "missed_request": request_ids[
                        next(j for j in range(len(requests)) if not mask & (1 << j))
                    ],
                    "rq0004_branch": branch,
                    "raw_upper_cents": raw,
                    "unavoidable_miss_cents": unavoidable_miss_cents,
                    "adjusted_upper_cents": adjusted,
                })

    all_awarded = by_awarded_count[17]["upper_cents"]
    independent_conditional = json.loads(
        AUDITED_CONDITIONAL.read_text(encoding="utf-8")
    )["conditional_total_upper_cents"]
    if all_awarded != independent_conditional:
        raise AssertionError(
            "all-awarded case does not match independently audited conditional certificate"
        )
    if maximum_adjusted[0] > maximum_raw[0]:
        raise AssertionError("subtracting inevitable penalties raised an upper bound")

    def describe(mask: int, branch: int) -> dict:
        return {
            "request_mask": mask,
            "awarded_request_ids": [
                request_ids[j] for j in range(len(requests))
                if mask & (1 << j)
            ],
            "unawarded_request_ids": [
                request_ids[j] for j in range(len(requests))
                if not (mask & (1 << j))
            ],
            "rq0004_branch": branch,
            "rq0004_tile": (
                list(requests_with_options[ambiguous_index][1][branch])
                if mask & (1 << ambiguous_index) else None
            ),
        }

    result = {
        "scope": "dev-reference practice; unconditional over all valid decision traces",
        "scenario": str(PRACTICE.relative_to(ROOT)),
        "capacity_price_file": (
            str(prices.relative_to(ROOT))
            if prices.is_relative_to(ROOT) else str(prices)
        ),
        "capacity_price_sha256": price_sha256,
        "key_tiles": list(KEY_TILES),
        "theta_uniform_cents": THETA_CENTS,
        "candidate_count": data["complete_arc_count"],
        "weather_interruption_arc_count": data["partial_arc_count"],
        "resource_and_wait_base_cents_without_request_rewards": without_request_cents,
        "request_ids_in_mask_order": request_ids,
        "request_subset_count": subset_count,
        "evaluated_branch_count": branch_count,
        "infeasible_branch_count": infeasible_branch_count,
        "branch_table_sha256": digest.hexdigest(),
        "max_raw_cents": maximum_raw[0],
        "max_raw_case": describe(maximum_raw[1], maximum_raw[2]),
        "max_after_inevitable_miss_cents": maximum_adjusted[0],
        "max_after_inevitable_miss_case": describe(
            maximum_adjusted[1], maximum_adjusted[2]
        ),
        "unconditional_upper_bound_cents": maximum_adjusted[0],
        "unconditional_upper_bound": maximum_adjusted[0] / 100.0,
        "all_awarded_upper_cents": all_awarded,
        "best_by_awarded_count": [
            by_awarded_count[k] for k in range(len(requests) + 1)
        ],
        "exactly_sixteen_awarded_cases": sorted(
            exactly_sixteen,
            key=lambda item: (-item["adjusted_upper_cents"], item["missed_request"]),
        ),
        "unavoidable_miss_rule": (
            "For each unawarded feasible request r, subtract its miss penalty "
            "only when deadline(r) <= max available_from of earned requests. "
            "The scorer's own slot-boundary opportunity predicate establishes "
            "non-excusal."
        ),
        "request_excused_if_missed": {
            request_ids[j]: bool(excuse_if_missed[j])
            for j in range(len(requests))
        },
        "prior_audit": prior,
        "fresh_scalar_audit": data["scalar_audit"],
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prices", type=Path,
        default=ROOT / "runs" / "practice_bound" / "resource_prices.npz",
    )
    parser.add_argument("--audit", action="store_true")
    parser.add_argument(
        "--out", type=Path,
        default=ROOT / "results" / "practice_request_unconditional.json",
    )
    args = parser.parse_args()
    result = certify(args.prices, args.audit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "unconditional_upper_bound": result["unconditional_upper_bound"],
        "subset_count": result["request_subset_count"],
        "branch_count": result["evaluated_branch_count"],
        "max_raw": result["max_raw_cents"] / 100.0,
        "max_after_inevitable_miss": result["max_after_inevitable_miss_cents"] / 100.0,
        "out": str(args.out),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
