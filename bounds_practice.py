#!/usr/bin/env python3
"""Independent per-tile oracle upper bound for the public-weather practice case.

Every 150-second reachable start is tested against the scorer's segmented
geometry and actual published practice weather. Telescope conflicts, waiting,
and all nonnegative penalties are relaxed. This script does not plan actions.
"""

from __future__ import annotations

import argparse
import json
import math
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

import numpy as np

import bounds_public as geometry
from challenge.scoring_core import ChallengeScorer


def _upper_cents(value: float) -> int:
    if value <= 0.0:
        return 0
    return math.ceil(100.0 * (value + 1e-6) + 1e-6)


def _rule_cents(value: float) -> int:
    return int((100 * Decimal(str(value))).to_integral_value(rounding=ROUND_CEILING))


def analyze(scenario_root: Path, report_path: Path | None) -> dict:
    scorer = ChallengeScorer.from_files(scenario_root)
    if scorer.mechanics:
        raise ValueError("this script is for the pre-anomaly practice scoring rules")
    tiles = geometry._read_csv(scenario_root / "outputs" / "reference" / "tiles.csv")
    slots = geometry._read_csv(scenario_root / "outputs" / "reference" / "slots.csv")
    calendar = scorer.geometry.calendar_config
    tile_config = scorer.geometry.tile_config
    weather_config = scorer.weather.config
    latitude = float(calendar["site"]["latitude_deg"])
    longitude = float(calendar["site"]["longitude_deg"])
    instants, sidereal, night_end = geometry._time_grid(slots, longitude)
    airmass_exponent = float(weather_config["score_interface"]["airmass_exponent"])
    weather_cap = float(weather_config["score_interface"]["maximum_weather_quality"])
    thresholds = scorer.config["quality_thresholds"]
    program_bonus = scorer.config["program_bonus"]
    complete_starts: dict[str, np.ndarray] = {}
    tile_upper_cents = 0
    tile_max_raw = 0.0
    complete_candidate_count = 0

    for tile in tiles:
        tile_id = tile["tile_id"]
        exposure = int(tile["nominal_exptime_seconds"])
        value = scorer.tile_values[tile_id]
        candidate_mask = geometry._geometry_candidate_mask(
            tile, instants, sidereal, night_end, latitude,
            float(tile_config["geometry"]["minimum_altitude_deg"]),
        )
        candidate_starts = np.flatnonzero(candidate_mask)
        observable = np.zeros(len(slots), dtype=np.bool_)
        weather_numerator = np.zeros(len(slots), dtype=np.float64)
        for slot_index, slot in enumerate(scorer.slots):
            conditions = scorer.weather.get_effective_conditions(slot.slot_id, tile_id)
            if conditions["is_observable"]:
                observable[slot_index] = True
                weather_numerator[slot_index] = (
                    float(conditions["instrument_efficiency"])
                    * float(conditions["transparency"])
                    * float(conditions["sky_quality"])
                    / float(conditions["seeing_arcsec"])
                )
        completed = np.zeros(len(instants), dtype=np.bool_)
        best = 0.0
        for offset_units in range(geometry.POINTS_PER_SLOT):
            starts = candidate_starts[
                candidate_starts % geometry.POINTS_PER_SLOT == offset_units
            ]
            if len(starts) == 0:
                continue
            segments = geometry._segments(
                exposure, offset_units * geometry.UNIT_SECONDS
            )
            valid = np.ones(len(starts), dtype=np.bool_)
            for segment_index in range(len(segments)):
                valid &= observable[starts // geometry.POINTS_PER_SLOT + segment_index]
            starts = starts[valid]
            if len(starts) == 0:
                continue
            completed[starts] = True
            complete_candidate_count += len(starts)
            base = np.zeros(len(starts), dtype=np.float64)
            bonus_dark = np.zeros(len(starts), dtype=np.float64)
            bonus_bright = np.zeros(len(starts), dtype=np.float64)
            bonus_backup = np.zeros(len(starts), dtype=np.float64)
            for segment_index, (seconds, midpoint_after_start) in enumerate(segments):
                slot_indices = starts // geometry.POINTS_PER_SLOT + segment_index
                quality = geometry._segment_quality_upper(
                    tile,
                    instants[starts] + midpoint_after_start,
                    latitude,
                    longitude,
                    tile_config["lunar_model"],
                    weather_numerator[slot_indices],
                    airmass_exponent,
                    weather_cap,
                )
                part = seconds / exposure * quality
                base += part
                bonus_dark += part * (quality >= float(thresholds["dark"]))
                bonus_bright += part * (
                    (quality < float(thresholds["dark"]))
                    & (quality >= float(thresholds["bright"]))
                )
                bonus_backup += part * (quality < float(thresholds["bright"]))
            total = value * (
                base
                + np.maximum.reduce((
                    bonus_dark * float(program_bonus["DARK"]),
                    bonus_bright * float(program_bonus["BRIGHT"]),
                    bonus_backup * float(program_bonus["BACKUP"]),
                ))
            )
            best = max(best, float(total.max()))
        complete_starts[tile_id] = completed
        tile_max_raw += best
        tile_upper_cents += _upper_cents(best)

    request_upper_cents = 0
    impossible_requests = []
    request_opportunities: dict[str, dict[str, int]] = {}
    for request in scorer.requests.values():
        in_window = (
            (instants >= request.available_from_utc.timestamp())
            & (instants < request.deadline_utc.timestamp())
        )
        counts = {}
        enough = 0
        for tile_id, visits in scorer.request_tiles[request.request_id].items():
            count = int(np.count_nonzero(complete_starts[tile_id] & in_window))
            counts[tile_id] = count
            enough += count >= visits
        request_opportunities[request.request_id] = counts
        if enough >= request.required_tile_count:
            request_upper_cents += _rule_cents(float(request.completion_reward))
        else:
            impossible_requests.append(request.request_id)

    result = {
        "scenario": str(scenario_root),
        "tiles": len(tiles),
        "weather_complete_candidate_starts": complete_candidate_count,
        "per_tile_science_oracle_raw": round(tile_max_raw, 9),
        "science_upper_bound": tile_upper_cents / 100.0,
        "request_upper_bound": request_upper_cents / 100.0,
        "impossible_requests": impossible_requests,
        "impossible_request_opportunities": {
            request_id: request_opportunities[request_id]
            for request_id in impossible_requests
        },
        "total_upper_bound": (tile_upper_cents + request_upper_cents) / 100.0,
    }
    if report_path is not None:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        score = report["score"]
        result["feasible_score"] = score["total"]
        result["science_realized"] = score["base_science"] + score["program_bonus"]
        result["avoidable_wait_penalty"] = score["penalties"].get("avoidable_wait", 0.0)
        result["certified_gap_at_most"] = round(
            result["total_upper_bound"] - score["total"], 6
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/dev-reference"))
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(analyze(args.scenario, args.report), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
