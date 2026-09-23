#!/usr/bin/env python3
"""Compute a weather-independent score upper bound from public scenario rules.

The script reads only tiles, slots, and static configuration. In particular, it
does not read generated weather, events, anomalies, requests, or their metadata.
It is an analysis tool; the result is an upper bound, not a reachable schedule.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
UNIT_SECONDS = 150  # gcd(900, 450, 600, 900, 1200, 1350)
POINTS_PER_SLOT = 900 // UNIT_SECONDS
NEG_INF = -(10**15)


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _epoch(utc: str) -> float:
    return datetime.fromisoformat(utc.replace("Z", "+00:00")).timestamp()


def _airmass(altitude_deg: float) -> float:
    """Same normalized Kasten--Young approximation as the scorer."""
    z = 90.0 - altitude_deg
    raw = 1.0 / (
        math.cos(math.radians(z))
        + 0.50572 * (96.07995 - z) ** (-1.6364)
    )
    zenith_raw = 1.0 / (1.0 + 0.50572 * 96.07995 ** (-1.6364))
    return raw / zenith_raw


def _ceil_cents(score: float) -> int:
    # Upward rounding keeps the reported DP result a bound after discretization.
    # The tiny extra allowance also covers floating-point evaluation noise.
    return math.ceil(100.0 * score + 1e-6)


def _exact_cents(score: Decimal | float) -> int:
    """Round a rule coefficient upward as its JSON decimal literal."""
    return int((100 * Decimal(str(score))).to_integral_value(rounding=ROUND_CEILING))


def _time_grid(slots: list[dict[str, str]], longitude_deg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return each reachable 150-second instant, local sidereal time, night end.

    Waiting jumps to a slot boundary and every exposure is a multiple of 150
    seconds, so an actual run can only begin an exposure at these instants.
    """
    slot_seconds = {int(row["duration_seconds"]) for row in slots}
    if slot_seconds != {900}:
        raise ValueError(f"expected 900-second slots, got {slot_seconds}")
    starts = np.array([_epoch(row["timestamp_utc"]) for row in slots], dtype=np.float64)
    instants = (starts[:, None] + UNIT_SECONDS * np.arange(POINTS_PER_SLOT)).ravel()
    days_j2000 = instants / 86400.0 + 2440587.5 - 2451545.0
    local_sidereal = (
        280.46061837 + 360.98564736629 * days_j2000 + longitude_deg
    ) % 360.0

    night_ids = [row["night_id"] for row in slots]
    night_end = np.empty(len(instants), dtype=np.int32)
    first_slot = 0
    while first_slot < len(slots):
        last_slot = first_slot + 1
        while last_slot < len(slots) and night_ids[last_slot] == night_ids[first_slot]:
            last_slot += 1
        night_end[first_slot * POINTS_PER_SLOT : last_slot * POINTS_PER_SLOT] = (
            last_slot * POINTS_PER_SLOT
        )
        first_slot = last_slot
    return instants, local_sidereal, night_end


def _geometry_candidate_mask(
    tile: dict[str, str],
    instants: np.ndarray,
    local_sidereal: np.ndarray,
    night_end: np.ndarray,
    latitude_deg: float,
    minimum_altitude_deg: float,
) -> np.ndarray:
    """Mark optimistic completed starts using the scorer's segment-start test.

    Weather is assumed open. The scorer does not require midpoint geometry or
    the *end* of the exposure to precede tile.available_until. It checks each
    executed segment's start; copying the stricter published tile-window test
    here would incorrectly exclude legal observations.
    """
    duration = int(tile["nominal_exptime_seconds"])
    if duration % UNIT_SECONDS:
        raise ValueError("exposure duration is not a multiple of 150 seconds")
    units = duration // UNIT_SECONDS
    point = np.arange(len(instants))
    lat = math.radians(latitude_deg)
    dec = math.radians(float(tile["dec_deg"]))
    hour_angle = np.deg2rad((local_sidereal - float(tile["ra_deg"]) + 180.0) % 360.0 - 180.0)
    sin_altitude = (
        math.sin(lat) * math.sin(dec)
        + math.cos(lat) * math.cos(dec) * np.cos(hour_angle)
    )
    segment_start_legal = (
        (instants >= _epoch(tile["available_from_utc"]))
        & (instants < _epoch(tile["available_until_utc"]))
        # The small tolerance errs toward keeping a boundary start. It can
        # weaken this bound, but cannot exclude a scorer-legal observation.
        & (sin_altitude >= math.sin(math.radians(minimum_altitude_deg)) - 1e-12)
    )
    possible = segment_start_legal.copy()
    possible &= point + units <= night_end
    # A segment starts at the action start, then at each crossed slot boundary.
    # No test is made at the final endpoint or at any midpoint.
    for offset in range(1, units):
        crossing = (point % POINTS_PER_SLOT + offset) % POINTS_PER_SLOT == 0
        next_point = point + offset
        safe = next_point < len(instants)
        next_legal = np.zeros(len(instants), dtype=np.bool_)
        next_legal[safe] = segment_start_legal[next_point[safe]]
        possible &= ~crossing | next_legal
    return possible


def _segments(duration_seconds: int, start_offset_seconds: int) -> list[tuple[int, float]]:
    """(segment seconds, midpoint seconds after exposure start)."""
    result = []
    remaining = duration_seconds
    elapsed = 0
    room = 900 - start_offset_seconds
    while remaining:
        seconds = min(remaining, room)
        result.append((seconds, elapsed + seconds / 2.0))
        remaining -= seconds
        elapsed += seconds
        room = 900
    return result


def _cos_separation(ra1: np.ndarray | float, dec1: np.ndarray | float,
                    ra2: np.ndarray | float, dec2: np.ndarray | float) -> np.ndarray:
    """Cosine of an equatorial angular separation; arguments are radians."""
    return np.clip(
        np.sin(dec1) * np.sin(dec2)
        + np.cos(dec1) * np.cos(dec2) * np.cos(ra1 - ra2),
        -1.0, 1.0,
    )


def _segment_quality_upper(
    tile: dict[str, str],
    midpoint_epochs: np.ndarray,
    latitude_deg: float,
    longitude_deg: float,
    lunar_model: dict,
    atmospheric_numerator: float,
    airmass_exponent: float,
    maximum_weather_quality: float,
) -> np.ndarray:
    """Weather ceiling times exact public airmass and lunar geometry.

    This is a NumPy version of `geometry_sample` in tile_geometry_simulator.py.
    It samples each *executed segment midpoint*, exactly where the scorer
    measures science quality. There is no future weather input here.
    """
    days = midpoint_epochs / 86400.0 + 2440587.5 - 2451545.0
    sidereal = (280.46061837 + 360.98564736629 * days + longitude_deg) % 360.0
    lat = math.radians(latitude_deg)
    tile_ra = math.radians(float(tile["ra_deg"]))
    tile_dec = math.radians(float(tile["dec_deg"]))
    hour_angle = np.deg2rad((sidereal - float(tile["ra_deg"]) + 180.0) % 360.0 - 180.0)
    altitude = np.arcsin(np.clip(
        math.sin(lat) * math.sin(tile_dec)
        + math.cos(lat) * math.cos(tile_dec) * np.cos(hour_angle),
        -1.0, 1.0,
    ))
    zenith_deg = 90.0 - np.rad2deg(altitude)
    # The scorer defines infinite airmass at or below the horizon.
    safe_zenith_deg = np.minimum(zenith_deg, 90.0)
    raw_airmass = 1.0 / (
        np.cos(np.deg2rad(safe_zenith_deg))
        + 0.50572 * np.power(96.07995 - safe_zenith_deg, -1.6364)
    )
    zenith_raw = 1.0 / (1.0 + 0.50572 * 96.07995 ** (-1.6364))
    airmass = np.where(zenith_deg < 90.0, raw_airmass / zenith_raw, np.inf)

    sun_longitude = (280.460 + 0.9856474 * days) % 360.0
    sun_anomaly = np.deg2rad((357.528 + 0.9856003 * days) % 360.0)
    sun_ecliptic = np.deg2rad((
        sun_longitude + 1.915 * np.sin(sun_anomaly) + 0.020 * np.sin(2.0 * sun_anomaly)
    ) % 360.0)
    obliquity = np.deg2rad(23.439 - 0.0000004 * days)
    sun_ra = np.arctan2(np.cos(obliquity) * np.sin(sun_ecliptic), np.cos(sun_ecliptic))
    sun_dec = np.arcsin(np.sin(obliquity) * np.sin(sun_ecliptic))

    moon_mean_longitude = np.deg2rad((218.316 + 13.176396 * days) % 360.0)
    moon_mean_anomaly = np.deg2rad((134.963 + 13.064993 * days) % 360.0)
    moon_arg_lat = np.deg2rad((93.272 + 13.229350 * days) % 360.0)
    moon_longitude = moon_mean_longitude + math.radians(6.289) * np.sin(moon_mean_anomaly)
    moon_latitude = math.radians(5.128) * np.sin(moon_arg_lat)
    moon_x = np.cos(moon_longitude) * np.cos(moon_latitude)
    moon_y = (
        np.sin(moon_longitude) * np.cos(moon_latitude) * np.cos(obliquity)
        - np.sin(moon_latitude) * np.sin(obliquity)
    )
    moon_z = (
        np.sin(moon_longitude) * np.cos(moon_latitude) * np.sin(obliquity)
        + np.sin(moon_latitude) * np.cos(obliquity)
    )
    moon_ra = np.arctan2(moon_y, moon_x)
    moon_dec = np.arcsin(moon_z)
    illumination = (1.0 - _cos_separation(sun_ra, sun_dec, moon_ra, moon_dec)) / 2.0
    tile_moon_sep = np.rad2deg(np.arccos(_cos_separation(
        tile_ra, tile_dec, moon_ra, moon_dec
    )))
    moon_hour_angle = np.deg2rad((sidereal - np.rad2deg(moon_ra) + 180.0) % 360.0 - 180.0)
    moon_altitude = np.arcsin(np.clip(
        math.sin(lat) * np.sin(moon_dec)
        + math.cos(lat) * np.cos(moon_dec) * np.cos(moon_hour_angle),
        -1.0, 1.0,
    ))
    moon_altitude_weight = np.power(
        np.sin(np.maximum(0.0, moon_altitude)),
        float(lunar_model["altitude_exponent"]),
    )
    lunar = np.clip(
        1.0
        - float(lunar_model["maximum_penalty"])
        * illumination
        * moon_altitude_weight
        * np.exp(-tile_moon_sep / float(lunar_model["angular_decay_scale_deg"])),
        0.0, 1.0,
    )
    atmospheric = np.minimum(
        maximum_weather_quality,
        atmospheric_numerator / np.power(airmass, airmass_exponent),
    )
    return atmospheric * lunar


def _best_completed_quality_upper(
    tile: dict[str, str],
    candidate_mask: np.ndarray,
    instants: np.ndarray,
    latitude_deg: float,
    longitude_deg: float,
    lunar_model: dict,
    atmospheric_numerator: float,
    airmass_exponent: float,
    maximum_weather_quality: float,
) -> float:
    """Maximum weather-ceiling quality averaged over one legal exposure."""
    duration = int(tile["nominal_exptime_seconds"])
    candidates = np.flatnonzero(candidate_mask)
    best = 0.0
    for offset_units in range(POINTS_PER_SLOT):
        starts = candidates[candidates % POINTS_PER_SLOT == offset_units]
        if len(starts) == 0:
            continue
        score = np.zeros(len(starts), dtype=np.float64)
        for seconds, midpoint_after_start in _segments(duration, offset_units * UNIT_SECONDS):
            score += seconds / duration * _segment_quality_upper(
                tile,
                instants[starts] + midpoint_after_start,
                latitude_deg,
                longitude_deg,
                lunar_model,
                atmospheric_numerator,
                airmass_exponent,
                maximum_weather_quality,
            )
        best = max(best, float(score.max()))
    # Explicit upward cushion for vectorized floating-point geometry.
    return best + 1e-6


def _tile_value(tile: dict[str, str], target_models: dict) -> float:
    classes = {"LRG": "n_lrg", "ELG": "n_elg", "QSO": "n_qso", "BGS": "n_bgs"}
    return sum(
        int(tile[column]) * float(target_models[name]["science_weight"])
        for name, column in classes.items()
    )


def bound_scenario(scenario: str) -> dict[str, int | float | str]:
    root = ROOT / "scenarios" / scenario
    config_dir = root / "config"
    public_dir = root / "outputs" / "reference"
    calendar = _read_json(config_dir / "calendar_config.json")
    tile_config = _read_json(config_dir / "tile_config.json")
    weather = _read_json(config_dir / "weather_config.json")
    score = _read_json(config_dir / "score_config.json")
    request = _read_json(config_dir / "request_config.json")
    tiles = _read_csv(public_dir / "tiles.csv")
    slots = _read_csv(public_dir / "slots.csv")

    latitude = float(calendar["site"]["latitude_deg"])
    longitude = float(calendar["site"]["longitude_deg"])
    minimum_altitude = float(tile_config["geometry"]["minimum_altitude_deg"])
    instants, local_sidereal, night_end = _time_grid(slots, longitude)

    quality = weather["quality"]
    atmospheric_numerator = (
        float(quality["instrument_efficiency"]["maximum"])
        * float(quality["transparency"]["maximum"])
        * float(quality["sky_quality"]["maximum"])
        / float(quality["seeing_arcsec"]["minimum"])
    )
    airmass_exponent = float(weather["score_interface"]["airmass_exponent"])
    maximum_weather_quality = float(weather["score_interface"]["maximum_weather_quality"])
    program_factor = max(float(value) for value in score["program_bonus"].values())
    coverage_factor = float(score["coverage_bonus_weight"])
    science_factor = 1.0 + program_factor + coverage_factor
    nova_factor = float(score["anomaly_tags"]["nova_factor"])
    reddening_factor = float(score["anomaly_tags"]["reddening_factor"])
    if reddening_factor > 1.0:
        raise ValueError("this bound assumes reddening cannot increase science")
    nova_limit = int(tile_config["anomaly_tags"]["nova_count"])

    capacity = len(instants)
    dp = np.full((nova_limit + 1, capacity + 1), NEG_INF, dtype=np.int64)
    dp[0, 0] = 0
    transit_dp = np.full((nova_limit + 1, capacity + 1), NEG_INF, dtype=np.int64)
    transit_dp[0, 0] = 0
    candidate_count = 0
    feasible_tile_count = 0
    for tile in tiles:
        candidate_mask = _geometry_candidate_mask(
            tile, instants, local_sidereal, night_end, latitude, minimum_altitude
        )
        candidates = int(np.count_nonzero(candidate_mask))
        candidate_count += candidates
        if not candidates:
            continue
        feasible_tile_count += 1
        units = int(tile["nominal_exptime_seconds"]) // UNIT_SECONDS
        value = _tile_value(tile, tile_config["target_models"])
        # A tile can never rise above its meridian culmination altitude.
        maximum_altitude = 90.0 - abs(latitude - float(tile["dec_deg"]))
        transit_quality_upper = min(
            maximum_weather_quality,
            atmospheric_numerator / _airmass(maximum_altitude) ** airmass_exponent,
        )
        # The true observation uses per-segment midpoint geometry and lunar
        # quality, both deterministic from public catalog/site/date data.
        quality_upper = min(transit_quality_upper, _best_completed_quality_upper(
            tile, candidate_mask, instants, latitude, longitude,
            tile_config["lunar_model"], atmospheric_numerator,
            airmass_exponent, maximum_weather_quality,
        ))
        regular_cents = _ceil_cents(science_factor * value * quality_upper)
        nova_cents = _ceil_cents(science_factor * value * quality_upper * nova_factor)
        transit_regular_cents = _ceil_cents(science_factor * value * transit_quality_upper)
        transit_nova_cents = _ceil_cents(science_factor * value * transit_quality_upper * nova_factor)

        old = dp.copy()
        np.maximum(dp[:, units:], old[:, :-units] + regular_cents, out=dp[:, units:])
        np.maximum(dp[1:, units:], old[:-1, :-units] + nova_cents, out=dp[1:, units:])
        old_transit = transit_dp.copy()
        np.maximum(
            transit_dp[:, units:],
            old_transit[:, :-units] + transit_regular_cents,
            out=transit_dp[:, units:],
        )
        np.maximum(
            transit_dp[1:, units:],
            old_transit[:-1, :-units] + transit_nova_cents,
            out=transit_dp[1:, units:],
        )

    # At most one request opportunity every `issue_every_n_nights`, each with
    # at most `tiles_per_request[1]` required tiles. Ignore all request misses.
    possible_requests = len(range(0, int(calendar["survey"]["days"]), int(request["issue_every_n_nights"])))
    request_upper = (
        Decimal(possible_requests)
        * Decimal(int(request["tiles_per_request"][1]))
        * Decimal(str(request["reward_per_required_tile"]))
    )
    # Each correct anomaly tag can reward at most once; ignore wrong reports.
    report_upper = Decimal(
        int(tile_config["anomaly_tags"]["nova_count"])
        + int(tile_config["anomaly_tags"]["reddening_count"])
    ) * Decimal(str(score["reporting"]["reward_correct"]))
    request_cents = _exact_cents(request_upper)
    report_cents = _exact_cents(report_upper)
    result_cents = int(dp.max()) + request_cents + report_cents
    return {
        "scenario": scenario,
        "slots": len(slots),
        "tile_count": len(tiles),
        "geometry_complete_starts": candidate_count,
        "geometry_completable_tiles": feasible_tile_count,
        "score_upper_bound": result_cents / 100.0,
        "science_upper_bound": int(dp.max()) / 100.0,
        "transit_score_upper_bound": (
            int(transit_dp.max()) + request_cents + report_cents
        ) / 100.0,
        "request_upper_bound": request_cents / 100.0,
        "report_upper_bound": report_cents / 100.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenarios", nargs="*", default=["eval-a", "eval-b"])
    args = parser.parse_args()
    for scenario in args.scenarios:
        print(json.dumps(bound_scenario(scenario), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
