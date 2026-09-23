#!/usr/bin/env python3
"""Certified interval-capacity upper bound for the public-weather practice case.

For every tile, enumerate all 150-second-grid starts which can complete in
published practice weather. A first visit earns at most one science credit.
Non-overlap is dualized with nonnegative integer-cent prices on 150-second
capacity cells. Request rewards are separately bounded by individual
opportunity. Waiting and all negative terms are relaxed. No plan is submitted.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

import numpy as np

import bounds_public as geometry
from challenge.scoring_core import ChallengeScorer
from challenge.weather_simulator import weather_quality


def upward_cents(value: float) -> int:
    return math.ceil(100.0 * (value + 1e-6) + 1e-6)


def all_arcs(scenario: Path):
    scorer = ChallengeScorer.from_files(scenario)
    if scorer.mechanics:
        raise ValueError("only the public-weather pre-anomaly practice rules")
    tiles = geometry._read_csv(scenario / "outputs" / "reference" / "tiles.csv")
    slots = geometry._read_csv(scenario / "outputs" / "reference" / "slots.csv")
    calendar = scorer.geometry.calendar_config
    tile_config = scorer.geometry.tile_config
    weather_config = scorer.weather.config
    lat = float(calendar["site"]["latitude_deg"])
    lon = float(calendar["site"]["longitude_deg"])
    min_alt = float(tile_config["geometry"]["minimum_altitude_deg"])
    instants, sidereal, night_end = geometry._time_grid(slots, lon)
    exponent = float(weather_config["score_interface"]["airmass_exponent"])
    cap = float(weather_config["score_interface"]["maximum_weather_quality"])
    dark = float(scorer.config["quality_thresholds"]["dark"])
    bright = float(scorer.config["quality_thresholds"]["bright"])
    bonus = scorer.config["program_bonus"]
    all_starts = []
    all_ends = []
    all_rewards = []
    complete_starts = {}

    for tile in tiles:
        tile_id = tile["tile_id"]
        exposure = int(tile["nominal_exptime_seconds"])
        p_units = exposure // geometry.UNIT_SECONDS
        mask = geometry._geometry_candidate_mask(
            tile, instants, sidereal, night_end, lat, min_alt,
        )
        candidates = np.flatnonzero(mask)
        observable = np.zeros(len(slots), dtype=np.bool_)
        numerator = np.zeros(len(slots), dtype=np.float64)
        for k, slot in enumerate(scorer.slots):
            conditions = scorer.weather.get_effective_conditions(slot.slot_id, tile_id)
            if conditions["is_observable"]:
                observable[k] = True
                numerator[k] = (
                    float(conditions["instrument_efficiency"])
                    * float(conditions["transparency"])
                    * float(conditions["sky_quality"])
                    / float(conditions["seeing_arcsec"])
                )
        tile_starts = []
        tile_rewards = []
        completion_mask = np.zeros(len(instants), dtype=np.bool_)
        for offset in range(geometry.POINTS_PER_SLOT):
            starts = candidates[candidates % geometry.POINTS_PER_SLOT == offset]
            if len(starts) == 0:
                continue
            segments = geometry._segments(exposure, offset * geometry.UNIT_SECONDS)
            valid = np.ones(len(starts), dtype=np.bool_)
            for segment_index in range(len(segments)):
                valid &= observable[starts // geometry.POINTS_PER_SLOT + segment_index]
            starts = starts[valid]
            if len(starts) == 0:
                continue
            completion_mask[starts] = True
            base = np.zeros(len(starts), dtype=np.float64)
            program_parts = np.zeros((3, len(starts)), dtype=np.float64)
            for segment_index, (seconds, midpoint_after_start) in enumerate(segments):
                slot_indices = starts // geometry.POINTS_PER_SLOT + segment_index
                quality = geometry._segment_quality_upper(
                    tile, instants[starts] + midpoint_after_start,
                    lat, lon, tile_config["lunar_model"], numerator[slot_indices],
                    exponent, cap,
                )
                # Widen the vectorized geometry values before classifying a
                # threshold band. This errs upward around all band edges;
                # scalar scorer comparisons on 11,726 sampled midpoints
                # differed by at most 9.5e-16 in quality.
                quality_low = quality - 1e-6
                quality_high = quality + 1e-6
                part = seconds / exposure * quality_high
                base += part
                program_parts[0] += part * (quality_high >= dark)
                program_parts[1] += part * ((quality_low < dark) & (quality_high >= bright))
                program_parts[2] += part * (quality_low < bright)
            bonuses = np.vstack((
                program_parts[0] * float(bonus["DARK"]),
                program_parts[1] * float(bonus["BRIGHT"]),
                program_parts[2] * float(bonus["BACKUP"]),
            ))
            score = scorer.tile_values[tile_id] * (base + bonuses.max(axis=0))
            reward = np.ceil(100.0 * (score + 1e-6) + 1e-6).astype(np.int64)
            tile_starts.append(starts.astype(np.int32))
            tile_rewards.append(reward)
        if tile_starts:
            starts = np.concatenate(tile_starts)
            rewards = np.concatenate(tile_rewards)
            all_starts.append(starts)
            all_ends.append(starts + p_units)
            all_rewards.append(rewards)
        else:
            all_starts.append(np.empty(0, dtype=np.int32))
            all_ends.append(np.empty(0, dtype=np.int32))
            all_rewards.append(np.empty(0, dtype=np.int64))
        complete_starts[tile_id] = completion_mask

    request_upper_cents = 0
    impossible_requests = []
    for request in scorer.requests.values():
        in_window = (
            (instants >= request.available_from_utc.timestamp())
            & (instants < request.deadline_utc.timestamp())
        )
        possible_tiles = sum(
            np.count_nonzero(complete_starts[tile_id] & in_window) >= visit_count
            for tile_id, visit_count in scorer.request_tiles[request.request_id].items()
        )
        if possible_tiles >= request.required_tile_count:
            request_upper_cents += int((
                Decimal(100) * Decimal(str(request.completion_reward))
            ).to_integral_value(rounding=ROUND_CEILING))
        else:
            impossible_requests.append(request.request_id)
    return (instants, all_starts, all_ends, all_rewards,
            request_upper_cents, impossible_requests)


def certify(
    starts: list[np.ndarray], ends: list[np.ndarray],
    rewards: list[np.ndarray], prices: np.ndarray,
) -> tuple[int, np.ndarray]:
    """Recompute the weak-duality bound entirely in integer cents."""
    prefix = np.empty(len(prices) + 1, dtype=np.int64)
    prefix[0] = 0
    np.cumsum(prices, out=prefix[1:])
    total = int(np.sum(prices, dtype=np.int64))
    chosen = np.full(len(starts), -1, dtype=np.int32)
    for i, (a, b, reward) in enumerate(zip(starts, ends, rewards)):
        if len(a) == 0:
            continue
        reduced = reward - (prefix[b] - prefix[a])
        j = int(np.argmax(reduced))
        if reduced[j] > 0:
            total += int(reduced[j])
            chosen[i] = j
    return total, chosen


def optimize_prices(
    starts: list[np.ndarray], ends: list[np.ndarray],
    rewards: list[np.ndarray], n_units: int, rounds: int,
) -> tuple[int, np.ndarray, dict]:
    prices = np.zeros(n_units, dtype=np.int64)
    best, chosen = certify(starts, ends, rewards, prices)
    independent = best
    best_prices = prices.copy()
    update_sizes = (512, 256, 128, 64, 32, 16, 8, 4, 2, 1)
    for iteration in range(rounds):
        occupancy_delta = np.zeros(n_units + 1, dtype=np.int32)
        for i, j in enumerate(chosen):
            if j >= 0:
                occupancy_delta[starts[i][j]] += 1
                occupancy_delta[ends[i][j]] -= 1
        occupancy = np.cumsum(occupancy_delta[:-1])
        step = update_sizes[min(len(update_sizes) - 1,
                                iteration * len(update_sizes) // rounds)]
        prices = np.maximum(0, prices + step * (occupancy - 1))
        value, chosen = certify(starts, ends, rewards, prices)
        if value < best:
            best = value
            best_prices = prices.copy()
    check, _ = certify(starts, ends, rewards, best_prices)
    if check != best:
        raise AssertionError("dual certificate changed")
    return best, best_prices, {"independent_cents": independent,
                               "dual_improvement_cents": independent - best,
                               "positive_price_cells": int(np.count_nonzero(best_prices)),
                               "max_cell_price_cents": int(best_prices.max())}


def audit_scalar_scores(
    scenario: Path, starts: list[np.ndarray], rewards: list[np.ndarray],
) -> dict:
    """Exhaustively compare every arc envelope with scalar scoring routines."""
    scorer = ChallengeScorer.from_files(scenario)
    catalog_ids = [row["tile_id"] for row in geometry._read_csv(
        scenario / "outputs" / "reference" / "tiles.csv"
    )]
    if list(scorer.tiles) != catalog_ids:
        raise AssertionError("scorer and arc tile order differ")
    checked = 0
    max_overage = 0
    min_slack = None
    for tile_id, tile_starts, upper_rewards in zip(scorer.tiles, starts, rewards):
        tile = scorer.tiles[tile_id]
        value = scorer.tile_values[tile_id]
        for start_unit, reward_cents in zip(tile_starts, upper_rewards):
            slot_index = int(start_unit) // geometry.POINTS_PER_SLOT
            offset_seconds = int(start_unit) % geometry.POINTS_PER_SLOT * geometry.UNIT_SECONDS
            remaining = tile.nominal_exptime_seconds
            base_total = 0.0
            bonus_by_program = {"DARK": 0.0, "BRIGHT": 0.0, "BACKUP": 0.0}
            while remaining:
                slot = scorer.slots[slot_index]
                seconds = min(remaining, slot.duration_seconds - offset_seconds)
                midpoint = slot.timestamp_utc + timedelta(
                    seconds=offset_seconds + seconds / 2,
                )
                sample = scorer.geometry.get_tile_geometry(tile_id, midpoint)
                conditions = scorer.weather.get_effective_conditions(slot.slot_id, tile_id)
                quality = weather_quality(
                    conditions, float(sample["airmass"]), scorer.weather.config,
                ) * float(sample["lunar_quality_factor"])
                part = value * seconds / tile.nominal_exptime_seconds * quality
                base_total += part
                band = scorer._quality_band(quality)
                bonus_by_program[band] += part * float(scorer.config["program_bonus"][band])
                remaining -= seconds
                slot_index += 1
                offset_seconds = 0
            actual_cents = math.ceil(100.0 * (
                base_total + max(bonus_by_program.values())
            ))
            slack = int(reward_cents) - actual_cents
            max_overage = max(max_overage, -slack)
            min_slack = slack if min_slack is None else min(min_slack, slack)
            checked += 1
    return {"scalar_checked_arcs": checked, "max_envelope_violation_cents": max_overage,
            "minimum_envelope_slack_cents": min_slack}


def audit_scalar_eligibility(
    scenario: Path, starts: list[np.ndarray],
) -> dict:
    """Check all source-scorer legal 150-second starts occur among our arcs."""
    scorer = ChallengeScorer.from_files(scenario)
    catalog_ids = [row["tile_id"] for row in geometry._read_csv(
        scenario / "outputs" / "reference" / "tiles.csv"
    )]
    if list(scorer.tiles) != catalog_ids:
        raise AssertionError("scorer and arc tile order differ")
    n_units = len(scorer.slots) * geometry.POINTS_PER_SLOT
    checked_points = 0
    omitted = 0
    for tile_id, tile_starts in zip(scorer.tiles, starts):
        tile = scorer.tiles[tile_id]
        legal = np.zeros(n_units, dtype=np.bool_)
        observable = np.zeros(len(scorer.slots), dtype=np.bool_)
        for k, slot in enumerate(scorer.slots):
            observable[k] = scorer.weather.get_effective_conditions(
                slot.slot_id, tile_id
            )["is_observable"]
            for offset in range(geometry.POINTS_PER_SLOT):
                moment = slot.timestamp_utc + timedelta(
                    seconds=offset * geometry.UNIT_SECONDS,
                )
                if tile.available_from_utc <= moment < tile.available_until_utc:
                    legal[k * geometry.POINTS_PER_SLOT + offset] = scorer._tile_legal(
                        tile, moment,
                    )
        p_units = tile.nominal_exptime_seconds // geometry.UNIT_SECONDS
        possible = legal.copy()
        for k, slot in enumerate(scorer.slots):
            if not observable[k]:
                possible[k * geometry.POINTS_PER_SLOT:(k + 1) * geometry.POINTS_PER_SLOT] = False
        for u in range(n_units):
            if not possible[u]:
                continue
            end = u + p_units
            if end > n_units:
                possible[u] = False
                continue
            first_night = scorer.slots[u // geometry.POINTS_PER_SLOT].night_id
            if scorer.slots[(end - 1) // geometry.POINTS_PER_SLOT].night_id != first_night:
                possible[u] = False
                continue
            for boundary in range(
                ((u // geometry.POINTS_PER_SLOT) + 1) * geometry.POINTS_PER_SLOT,
                end, geometry.POINTS_PER_SLOT,
            ):
                if not legal[boundary] or not observable[boundary // geometry.POINTS_PER_SLOT]:
                    possible[u] = False
                    break
        included = np.zeros(n_units, dtype=np.bool_)
        included[tile_starts] = True
        omitted += int(np.count_nonzero(possible & ~included))
        checked_points += n_units
    return {"scalar_checked_start_points": checked_points,
            "omitted_scalar_legal_arcs": omitted}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/dev-reference"))
    parser.add_argument("--rounds", type=int, default=200)
    parser.add_argument("--certificate", type=Path,
                        default=Path("runs/practice_bound/resource_prices.npz"))
    parser.add_argument("--verify-certificate", type=Path, default=None,
                        help="recompute the exact integer dual from saved prices")
    parser.add_argument("--audit-scalar-scores", action="store_true",
                        help="exhaustively compare arc envelopes to scorer arithmetic")
    parser.add_argument("--audit-scalar-eligibility", action="store_true",
                        help="check every scorer-legal grid start is enumerated")
    args = parser.parse_args()
    instants, starts, ends, rewards, request_cents, impossible = all_arcs(args.scenario)
    if args.verify_certificate is None:
        science_cents, prices, diagnostics = optimize_prices(
            starts, ends, rewards, len(instants), args.rounds,
        )
        args.certificate.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(args.certificate, prices_cents=prices)
        certificate = args.certificate
    else:
        with np.load(args.verify_certificate, allow_pickle=False) as loaded:
            prices = loaded["prices_cents"]
        if prices.shape != (len(instants),) or np.any(prices < 0):
            raise ValueError("certificate prices must be nonnegative capacity-cell cents")
        science_cents, _ = certify(starts, ends, rewards, prices)
        independent_cents, _ = certify(
            starts, ends, rewards, np.zeros(len(instants), dtype=np.int64)
        )
        diagnostics = {
            "independent_cents": independent_cents,
            "dual_improvement_cents": independent_cents - science_cents,
            "positive_price_cells": int(np.count_nonzero(prices)),
            "max_cell_price_cents": int(prices.max()),
        }
        certificate = args.verify_certificate
    scalar_audit = (
        audit_scalar_scores(args.scenario, starts, rewards)
        if args.audit_scalar_scores else {}
    )
    eligibility_audit = (
        audit_scalar_eligibility(args.scenario, starts)
        if args.audit_scalar_eligibility else {}
    )
    if scalar_audit.get("max_envelope_violation_cents", 0):
        raise AssertionError("an arc score exceeded its conservative envelope")
    if eligibility_audit.get("omitted_scalar_legal_arcs", 0):
        raise AssertionError("a scorer-legal grid start was omitted")
    print(json.dumps({
        "scenario": str(args.scenario), "tile_count": len(starts),
        "candidate_count": sum(len(a) for a in starts),
        "capacity_units": len(instants),
        "rounds": args.rounds if args.verify_certificate is None else 0,
        "science_dual_upper_bound": science_cents / 100.0,
        "request_upper_bound": request_cents / 100.0,
        "total_upper_bound": (science_cents + request_cents) / 100.0,
        "impossible_requests": impossible,
        "certificate": str(certificate), **diagnostics,
        **scalar_audit, **eligibility_audit,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
