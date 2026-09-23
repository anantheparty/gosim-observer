#!/usr/bin/env python3
"""Certified K-tile projected-wait upper bounds for the practice scenario.

The proof, including the role of resource prices and non-K unlabeled
observation tolls, is in PROJECTED_WAIT_BOUND_ZH.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import timedelta
from pathlib import Path

import numpy as np
from numba import njit

import bounds_public as geometry
from bounds_practice_resource import all_arcs, audit_scalar_eligibility, audit_scalar_scores, certify
from challenge.scoring_core import ChallengeScorer


POINTS_PER_SLOT = geometry.POINTS_PER_SLOT
WAIT_UNIT_CENTS = 15  # 150 seconds * 0.001 points/second.
REQUIRED_MISS_CENTS = 100_000


def _partial_weather_arcs(
    scenario: Path,
    scorer: ChallengeScorer,
    instants: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Superset of all legal-start, zero-penalty weather interruptions.

    Segment starts use exactly the scorer's time and altitude rule, with the
    same outward 1e-12 altitude tolerance as bounds_public. A failing geometry
    or night check precedes the weather check and is not included here.
    """
    tiles = geometry._read_csv(scenario / "outputs" / "reference" / "tiles.csv")
    slots = geometry._read_csv(scenario / "outputs" / "reference" / "slots.csv")
    calendar = scorer.geometry.calendar_config
    latitude = float(calendar["site"]["latitude_deg"])
    longitude = float(calendar["site"]["longitude_deg"])
    minimum_altitude = float(
        scorer.geometry.tile_config["geometry"]["minimum_altitude_deg"]
    )
    instants_again, sidereal, night_end = geometry._time_grid(slots, longitude)
    if not np.array_equal(instants, instants_again):
        raise AssertionError("time grid changed during arc enumeration")
    unit = np.arange(len(instants), dtype=np.int32)
    slot_index = unit // POINTS_PER_SLOT
    sin_limit = math.sin(math.radians(minimum_altitude)) - 1e-12
    lat = math.radians(latitude)
    starts_parts: list[np.ndarray] = []
    ends_parts: list[np.ndarray] = []

    for tile in tiles:
        tile_id = tile["tile_id"]
        dec = math.radians(float(tile["dec_deg"]))
        hour_angle = np.deg2rad(
            (sidereal - float(tile["ra_deg"]) + 180.0) % 360.0 - 180.0
        )
        sin_altitude = (
            math.sin(lat) * math.sin(dec)
            + math.cos(lat) * math.cos(dec) * np.cos(hour_angle)
        )
        legal = (
            (instants >= geometry._epoch(tile["available_from_utc"]))
            & (instants < geometry._epoch(tile["available_until_utc"]))
            & (sin_altitude >= sin_limit)
        )
        open_slots = np.fromiter(
            (
                scorer.weather.get_effective_conditions(slot.slot_id, tile_id)[
                    "is_observable"
                ]
                for slot in scorer.slots
            ),
            dtype=np.bool_,
            count=len(scorer.slots),
        )
        open_units = open_slots[slot_index]
        exposure_units = int(tile["nominal_exptime_seconds"]) // geometry.UNIT_SECONDS
        candidates = np.flatnonzero(legal & open_units).astype(np.int32)
        if len(candidates) == 0:
            continue
        target_end = candidates + exposure_units
        next_boundary = ((candidates // POINTS_PER_SLOT) + 1) * POINTS_PER_SLOT
        active = next_boundary < target_end
        while np.any(active):
            rows = np.flatnonzero(active)
            boundary = next_boundary[rows]
            same_night = boundary < night_end[candidates[rows]]
            in_grid = boundary < len(instants)
            possible = same_night & in_grid
            geom_ok = np.zeros(len(rows), dtype=np.bool_)
            geom_ok[possible] = legal[boundary[possible]]
            weather_closed = np.zeros(len(rows), dtype=np.bool_)
            checks = possible & geom_ok
            weather_closed[checks] = ~open_units[boundary[checks]]
            if np.any(weather_closed):
                starts_parts.append(candidates[rows[weather_closed]])
                ends_parts.append(boundary[weather_closed])
            continuing = checks & ~weather_closed
            active[:] = False
            if np.any(continuing):
                next_boundary[rows[continuing]] += POINTS_PER_SLOT
                active[rows[continuing]] = (
                    next_boundary[rows[continuing]] < target_end[rows[continuing]]
                )

    if not starts_parts:
        return np.empty(0, np.int32), np.empty(0, np.int32)
    starts = np.concatenate(starts_parts)
    ends = np.concatenate(ends_parts)
    pairs = np.unique(np.stack((starts, ends), axis=1), axis=0)
    return pairs[:, 0].astype(np.int32), pairs[:, 1].astype(np.int32)


def audit_partial_weather_arcs(
    scorer: ChallengeScorer,
    starts: np.ndarray,
    ends: np.ndarray,
) -> dict[str, int]:
    """Exhaustively audit all scorer-legal grid-start weather interruptions."""
    included = set(zip(map(int, starts), map(int, ends)))
    n = len(scorer.slots) * POINTS_PER_SLOT
    omitted = 0
    encountered = 0
    for tile in scorer.tiles.values():
        for u in range(n):
            slot_index, offset_units = divmod(u, POINTS_PER_SLOT)
            slot = scorer.slots[slot_index]
            moment = slot.timestamp_utc + timedelta(
                seconds=offset_units * geometry.UNIT_SECONDS
            )
            if not scorer._tile_legal(tile, moment):
                continue
            if not scorer.weather.get_effective_conditions(
                slot.slot_id, tile.tile_id
            )["is_observable"]:
                continue
            remaining = tile.nominal_exptime_seconds
            current_slot_index = slot_index
            offset_seconds = offset_units * geometry.UNIT_SECONDS
            while remaining > 0:
                current_slot = scorer.slots[current_slot_index]
                if current_slot.night_id != slot.night_id:
                    break
                segment_start = current_slot.timestamp_utc + timedelta(
                    seconds=offset_seconds
                )
                if not scorer._tile_legal(tile, segment_start):
                    break
                if not scorer.weather.get_effective_conditions(
                    current_slot.slot_id, tile.tile_id
                )["is_observable"]:
                    v = current_slot_index * POINTS_PER_SLOT
                    encountered += 1
                    if (u, v) not in included:
                        omitted += 1
                    break
                used = min(remaining, current_slot.duration_seconds - offset_seconds)
                remaining -= used
                current_slot_index += 1
                offset_seconds = 0
                if current_slot_index >= len(scorer.slots):
                    break
    return {
        "scalar_weather_interruption_cases": encountered,
        "omitted_weather_interruption_arcs": omitted,
    }


def _tag_available(
    scorer: ChallengeScorer,
    instants: np.ndarray,
    tile_ids: list[str],
) -> np.ndarray:
    result = np.zeros((len(instants), len(tile_ids)), dtype=np.bool_)
    tile_index = {tile_id: i for i, tile_id in enumerate(tile_ids)}
    for request in scorer.requests.values():
        mask = (
            (instants >= request.available_from_utc.timestamp())
            & (instants < request.deadline_utc.timestamp())
        )
        for tile_id in scorer.request_tiles[request.request_id]:
            result[mask, tile_index[tile_id]] = True
    return result


def _csr(starts: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(starts, kind="stable")
    count = np.bincount(starts, minlength=n)
    ptr = np.empty(n + 1, dtype=np.int64)
    ptr[0] = 0
    np.cumsum(count, out=ptr[1:])
    return ptr, order


@njit(cache=True)
def _popcount(value: int) -> int:
    result = 0
    while value:
        value &= value - 1
        result += 1
    return result


@njit(cache=True)
def projected_dp(
    n: int,
    complete_ptr: np.ndarray,
    complete_end: np.ndarray,
    complete_tile: np.ndarray,
    complete_reduced_cents: np.ndarray,
    complete_tagged: np.ndarray,
    partial_ptr: np.ndarray,
    partial_end: np.ndarray,
    actionable_mask: np.ndarray,
    key_index: np.ndarray,
    required_mask: int,
    theta_cents: np.ndarray,
    k: int,
) -> int:
    state_count = 1 << k
    dp = np.empty((n + 1, state_count), dtype=np.int64)
    terminal = np.empty(state_count, dtype=np.int64)
    for mask in range(state_count):
        missing = required_mask & (~mask)
        terminal[mask] = -REQUIRED_MISS_CENTS * _popcount(missing)
        dp[n, mask] = terminal[mask]

    for u in range(n - 1, -1, -1):
        boundary = ((u // POINTS_PER_SLOT) + 1) * POINTS_PER_SLOT
        for mask in range(state_count):
            best = terminal[mask]  # The decision file may end at this cursor.
            wait_cost = (
                WAIT_UNIT_CENTS * (boundary - u)
                if actionable_mask[u] & (~mask)
                else 0
            )
            candidate = dp[boundary, mask] - wait_cost
            if candidate > best:
                best = candidate
            for j in range(partial_ptr[u], partial_ptr[u + 1]):
                candidate = dp[partial_end[j], mask]
                if candidate > best:
                    best = candidate
            for j in range(complete_ptr[u], complete_ptr[u + 1]):
                tile = complete_tile[j]
                bit_index = key_index[tile]
                if bit_index >= 0:
                    bit = 1 << bit_index
                    if not (mask & bit):
                        candidate = (
                            dp[complete_end[j], mask | bit]
                            + complete_reduced_cents[j]
                        )
                    elif complete_tagged[j]:
                        candidate = dp[complete_end[j], mask]
                    else:
                        continue
                else:
                    toll = 0 if complete_tagged[j] else theta_cents[tile]
                    candidate = dp[complete_end[j], mask] - toll
                if candidate > best:
                    best = candidate
            dp[u, mask] = best
    return int(dp[0, 0])


def build_data(scenario: Path, price_path: Path, audit: bool) -> dict:
    instants, starts_by_tile, ends_by_tile, rewards_by_tile, request_cents, impossible = all_arcs(
        scenario
    )
    scorer = ChallengeScorer.from_files(scenario)
    tile_ids = list(scorer.tiles)
    n = len(instants)
    penalties = scorer.config["penalties"]
    wait_rate = float(penalties["avoidable_wait_per_second"])
    if abs(wait_rate - 0.001) > 1e-15:
        raise ValueError("wait-cost integer units must be recalibrated")
    if float(penalties["required_miss"]) != REQUIRED_MISS_CENTS / 100.0:
        raise ValueError("REQUIRED terminal penalty changed")
    if float(scorer.config.get("coverage_bonus_weight", 0.0)) != 0.0:
        raise ValueError("positive coverage reward is not included in this bound")
    max_exposure = max(tile.nominal_exptime_seconds for tile in scorer.tiles.values())
    if float(penalties["invalid_action"]) < max_exposure * wait_rate:
        raise ValueError("invalid-action dominance proof no longer applies")
    if float(penalties["unsafe_observation"]) < 900 * wait_rate:
        raise ValueError("unsafe-action dominance proof no longer applies")
    if any(float(value) < 0 for value in penalties.values()):
        raise ValueError("negative penalty invalidates score decomposition")
    with np.load(price_path, allow_pickle=False) as loaded:
        prices = loaded["prices_cents"].astype(np.int64)
    if prices.shape != (n,) or np.any(prices < 0):
        raise ValueError("invalid price certificate")
    certified_science_cents, _ = certify(
        starts_by_tile, ends_by_tile, rewards_by_tile, prices
    )
    price_prefix = np.empty(n + 1, dtype=np.int64)
    price_prefix[0] = 0
    np.cumsum(prices, out=price_prefix[1:])

    starts = np.concatenate(starts_by_tile).astype(np.int32)
    ends = np.concatenate(ends_by_tile).astype(np.int32)
    rewards = np.concatenate(rewards_by_tile).astype(np.int64)
    tile_index = np.concatenate(
        [
            np.full(len(tile_starts), i, dtype=np.int16)
            for i, tile_starts in enumerate(starts_by_tile)
        ]
    )
    tagged_table = _tag_available(scorer, instants, tile_ids)
    tagged = tagged_table[starts, tile_index]
    reduced = rewards - (price_prefix[ends] - price_prefix[starts])
    ptr, order = _csr(starts, n)
    ends = ends[order]
    tile_index = tile_index[order]
    reduced = reduced[order]
    tagged = tagged[order]

    partial_starts, partial_ends = _partial_weather_arcs(
        scenario, scorer, instants
    )
    partial_ptr, partial_order = _csr(partial_starts, n)
    partial_ends = partial_ends[partial_order]

    tile_residual_max = np.zeros(len(tile_ids), dtype=np.int64)
    for i, (a, b, reward) in enumerate(
        zip(starts_by_tile, ends_by_tile, rewards_by_tile)
    ):
        if len(a):
            tile_residual_max[i] = max(
                0, int(np.max(reward - (price_prefix[b] - price_prefix[a])))
            )
    if int(prices.sum()) + int(tile_residual_max.sum()) != certified_science_cents:
        raise AssertionError("resource price sum did not reproduce certificate")

    scalar_audit = {}
    if audit:
        scalar_audit.update(
            audit_scalar_eligibility(scenario, starts_by_tile)
        )
        scalar_audit.update(
            audit_scalar_scores(scenario, starts_by_tile, rewards_by_tile)
        )
        scalar_audit.update(
            audit_partial_weather_arcs(scorer, partial_starts, partial_ends)
        )
        if (
            scalar_audit["omitted_scalar_legal_arcs"]
            or scalar_audit["max_envelope_violation_cents"]
            or scalar_audit["omitted_weather_interruption_arcs"]
        ):
            raise AssertionError("candidate graph is missing a legal scorer arc")

    return {
        "scorer": scorer,
        "tile_ids": tile_ids,
        "n": n,
        "starts_by_tile": starts_by_tile,
        "actionable_cache": {},
        "full_actionability_audit": audit,
        "complete_ptr": ptr,
        "complete_end": ends,
        "complete_tile": tile_index,
        "complete_reduced": reduced,
        "complete_tagged": tagged,
        "partial_ptr": partial_ptr,
        "partial_end": partial_ends,
        "prices": prices,
        "tile_residual_max": tile_residual_max,
        "request_cents": request_cents,
        "impossible_requests": impossible,
        "complete_arc_count": len(starts),
        "partial_arc_count": len(partial_starts),
        "scalar_audit": scalar_audit,
    }


def calculate(
    data: dict,
    keys: list[str],
    theta_uniform_cents: int,
) -> dict:
    tile_ids = data["tile_ids"]
    if len(set(keys)) != len(keys) or any(key not in tile_ids for key in keys):
        raise ValueError("key tiles must be distinct known IDs")
    if len(keys) > 8:
        raise ValueError("prototype is limited to k <= 8")
    if theta_uniform_cents < 0:
        raise ValueError("theta must be nonnegative")
    key_index = np.full(len(tile_ids), -1, dtype=np.int8)
    for b, key in enumerate(keys):
        key_index[tile_ids.index(key)] = b
    required_mask = 0
    for b, key in enumerate(keys):
        if data["scorer"].tiles[key].scheduling_class == "REQUIRED":
            required_mask |= 1 << b
    actionable_mask = np.zeros(data["n"], dtype=np.uint8)
    for b, key in enumerate(keys):
        # The scorer's wait predicate is stricter than successful exposure:
        # _can_complete_from checks segment midpoints against tile geometry.
        # Every true predicate must be among successful starts, because it
        # includes all of their segment-start and weather requirements.
        # Check that inclusion again by the independent complete-arc audit.
        cache = data["actionable_cache"]
        if key not in cache:
            tile = data["scorer"].tiles[key]
            candidate_starts = data["starts_by_tile"][tile_ids.index(key)]
            actionable = np.zeros(data["n"], dtype=np.bool_)
            actionable[candidate_starts] = np.fromiter(
                (
                    data["scorer"]._can_complete_from(
                        tile,
                        int(u) // POINTS_PER_SLOT,
                        (int(u) % POINTS_PER_SLOT) * geometry.UNIT_SECONDS,
                    )
                    for u in candidate_starts
                ),
                dtype=np.bool_,
                count=len(candidate_starts),
            )
            if data["full_actionability_audit"]:
                included = np.zeros(data["n"], dtype=np.bool_)
                included[candidate_starts] = True
                for u in range(data["n"]):
                    if included[u]:
                        continue
                    if data["scorer"]._can_complete_from(
                        tile,
                        u // POINTS_PER_SLOT,
                        (u % POINTS_PER_SLOT) * geometry.UNIT_SECONDS,
                    ):
                        raise AssertionError(
                            f"scorer-actionable start omitted from complete arcs: {key} at {u}"
                        )
            cache[key] = actionable
        actionable_mask[cache[key]] |= 1 << b

    theta = np.full(len(tile_ids), theta_uniform_cents, dtype=np.int64)
    theta[key_index >= 0] = 0
    dp_cents = projected_dp(
        data["n"],
        data["complete_ptr"],
        data["complete_end"],
        data["complete_tile"],
        data["complete_reduced"],
        data["complete_tagged"],
        data["partial_ptr"],
        data["partial_end"],
        actionable_mask,
        key_index,
        required_mask,
        theta,
        len(keys),
    )
    external_science_cents = int(
        data["prices"].sum()
        + data["tile_residual_max"][key_index < 0].sum()
    )
    total_cents = (
        external_science_cents
        + int(data["request_cents"])
        + int(theta.sum())
        + dp_cents
    )
    return {
        "key_tiles": keys,
        "theta_uniform_cents": theta_uniform_cents,
        "required_key_mask": required_mask,
        "external_science_cents": external_science_cents,
        "request_cents": int(data["request_cents"]),
        "theta_constant_cents": int(theta.sum()),
        "projected_dp_cents": dp_cents,
        "total_upper_bound_cents": total_cents,
        "total_upper_bound": total_cents / 100.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario", type=Path, default=Path("scenarios/dev-reference")
    )
    parser.add_argument(
        "--prices", type=Path,
        default=Path("runs/practice_bound/resource_prices.npz"),
    )
    parser.add_argument(
        "--key-set", action="append", default=[],
        help="comma-separated tile IDs; repeat for multiple K sets; empty means K=0",
    )
    parser.add_argument(
        "--theta-cents", action="append", type=int, default=[],
        help="uniform non-K unlabeled-success toll; repeat for parameter scan",
    )
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    data = build_data(args.scenario, args.prices, args.audit)
    sets = args.key_set or [""]
    thetas = args.theta_cents or [0]
    results = [
        calculate(data, [part for part in key_set.split(",") if part], theta)
        for key_set in sets
        for theta in thetas
    ]
    digest = hashlib.sha256(args.prices.read_bytes()).hexdigest()
    payload = {
        "scenario": str(args.scenario),
        "price_certificate": str(args.prices),
        "price_sha256": digest,
        "time_units": data["n"],
        "complete_arc_count": data["complete_arc_count"],
        "weather_interruption_arc_count": data["partial_arc_count"],
        "resource_plus_request_cents": (
            int(data["prices"].sum() + data["tile_residual_max"].sum())
            + int(data["request_cents"])
        ),
        "impossible_requests": data["impossible_requests"],
        "scalar_audit": data["scalar_audit"],
        "results": results,
    }
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
