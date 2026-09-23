#!/usr/bin/env python3
"""Certify a nightly-capacity upper bound from public geometry and score rules.

Requires NumPy and OR-Tools GLOP (available in `.venv-solver`). Run with
`.venv-solver/bin/python bounds_night_lp.py`. Only static catalogs, slots, and
configuration are read; no generated weather, anomaly, or request truth is used.
"""

from __future__ import annotations

import argparse
import json
import math
from decimal import Decimal, ROUND_CEILING

import numpy as np
from ortools.linear_solver import pywraplp

import bounds_public as public


def _ceil_decimal(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def _night_quality_ceilings(
    tile: dict[str, str],
    candidate_mask: np.ndarray,
    instants: np.ndarray,
    night_of_point: np.ndarray,
    night_count: int,
    latitude: float,
    longitude: float,
    lunar_model: dict,
    atmosphere_numerator: float,
    airmass_exponent: float,
    weather_cap: float,
) -> np.ndarray:
    """For each night, max full-exposure quality over segment-start-legal starts."""
    duration = int(tile["nominal_exptime_seconds"])
    starts_all = np.flatnonzero(candidate_mask)
    ceiling = np.zeros(night_count, dtype=np.float64)
    for offset_units in range(public.POINTS_PER_SLOT):
        starts = starts_all[starts_all % public.POINTS_PER_SLOT == offset_units]
        if len(starts) == 0:
            continue
        quality = np.zeros(len(starts), dtype=np.float64)
        for seconds, midpoint_after_start in public._segments(
            duration, offset_units * public.UNIT_SECONDS
        ):
            quality += seconds / duration * public._segment_quality_upper(
                tile,
                instants[starts] + midpoint_after_start,
                latitude,
                longitude,
                lunar_model,
                atmosphere_numerator,
                airmass_exponent,
                weather_cap,
            )
        np.maximum.at(ceiling, night_of_point[starts], quality)
    return ceiling


def bound_scenario(scenario: str) -> dict[str, int | float | str]:
    root = public.ROOT / "scenarios" / scenario
    config_dir = root / "config"
    catalog_dir = root / "outputs" / "reference"
    calendar = public._read_json(config_dir / "calendar_config.json")
    tile_config = public._read_json(config_dir / "tile_config.json")
    weather = public._read_json(config_dir / "weather_config.json")
    score = public._read_json(config_dir / "score_config.json")
    request = public._read_json(config_dir / "request_config.json")
    tiles = public._read_csv(catalog_dir / "tiles.csv")
    slots = public._read_csv(catalog_dir / "slots.csv")

    latitude = float(calendar["site"]["latitude_deg"])
    longitude = float(calendar["site"]["longitude_deg"])
    minimum_altitude = float(tile_config["geometry"]["minimum_altitude_deg"])
    instants, sidereal, night_end = public._time_grid(slots, longitude)
    nights = list(dict.fromkeys(row["night_id"] for row in slots))
    night_lookup = {night: index for index, night in enumerate(nights)}
    night_of_point = np.repeat(
        [night_lookup[row["night_id"]] for row in slots],
        public.POINTS_PER_SLOT,
    )
    night_capacities = np.bincount(night_of_point, minlength=len(nights)).tolist()

    quality_config = weather["quality"]
    atmosphere_numerator = (
        float(quality_config["instrument_efficiency"]["maximum"])
        * float(quality_config["transparency"]["maximum"])
        * float(quality_config["sky_quality"]["maximum"])
        / float(quality_config["seeing_arcsec"]["minimum"])
    )
    airmass_exponent = float(weather["score_interface"]["airmass_exponent"])
    weather_cap = float(weather["score_interface"]["maximum_weather_quality"])
    science_factor = (
        1.0
        + max(float(value) for value in score["program_bonus"].values())
        + float(score["coverage_bonus_weight"])
    )
    nova_factor = float(score["anomaly_tags"]["nova_factor"])
    if float(score["anomaly_tags"]["reddening_factor"]) > 1.0:
        raise ValueError("this bound assumes reddening cannot increase science")
    nova_limit = int(tile_config["anomaly_tags"]["nova_count"])

    solver = pywraplp.Solver.CreateSolver("GLOP")
    if solver is None:
        raise RuntimeError("OR-Tools GLOP is unavailable")
    tile_rows = [solver.RowConstraint(0.0, 1.0, f"tile_{i}") for i in range(len(tiles))]
    night_rows = [
        solver.RowConstraint(0.0, float(capacity), f"night_{n}")
        for n, capacity in enumerate(night_capacities)
    ]
    nova_row = solver.RowConstraint(0.0, float(nova_limit), "nova_limit")
    objective = solver.Objective()
    objective.SetMaximization()
    # Integer-cent arc rewards make all weak-duality arithmetic auditable.
    arcs: list[tuple[int, int, int, int, int]] = []
    completable = 0
    for i, tile in enumerate(tiles):
        mask = public._geometry_candidate_mask(
            tile, instants, sidereal, night_end, latitude, minimum_altitude
        )
        if not np.any(mask):
            continue
        completable += 1
        p_units = int(tile["nominal_exptime_seconds"]) // public.UNIT_SECONDS
        tile_value = public._tile_value(tile, tile_config["target_models"])
        transit_ceiling = min(
            weather_cap,
            atmosphere_numerator
            / public._airmass(90.0 - abs(latitude - float(tile["dec_deg"])))
            ** airmass_exponent,
        )
        by_night = _night_quality_ceilings(
            tile, mask, instants, night_of_point, len(nights), latitude, longitude,
            tile_config["lunar_model"], atmosphere_numerator,
            airmass_exponent, weather_cap,
        )
        for n, raw_ceiling in enumerate(by_night):
            if raw_ceiling <= 0.0:
                continue
            # The explicit quality cushion and upward cent rounding preserve
            # the upper-bound direction through vectorized floating arithmetic.
            ceiling = min(transit_ceiling, float(raw_ceiling) + 1e-6)
            ordinary_cents = public._ceil_cents(science_factor * tile_value * ceiling)
            nova_cents = public._ceil_cents(
                science_factor * tile_value * ceiling * nova_factor
            )
            for is_nova, reward_cents in ((0, ordinary_cents), (1, nova_cents)):
                variable = solver.NumVar(0.0, 1.0, f"x_{i}_{n}_{is_nova}")
                tile_rows[i].SetCoefficient(variable, 1.0)
                night_rows[n].SetCoefficient(variable, float(p_units))
                if is_nova:
                    nova_row.SetCoefficient(variable, 1.0)
                objective.SetCoefficient(variable, float(reward_cents))
                arcs.append((i, n, p_units, is_nova, reward_cents))

    status = solver.Solve()
    # The solver's reported objective is *not* a certificate. Treat its dual
    # multipliers solely as a guess, project negative values to zero, then
    # rebuild a feasible dual in exact decimal arithmetic from every arc.
    if status == pywraplp.Solver.OPTIMAL:
        night_prices = [
            max(Decimal(0), Decimal(str(row.dual_value()))) for row in night_rows
        ]
        nova_price = max(Decimal(0), Decimal(str(nova_row.dual_value())))
    else:
        night_prices = [Decimal(0)] * len(nights)
        nova_price = Decimal(0)
    tile_prices = [Decimal(0)] * len(tiles)
    for i, n, p_units, is_nova, reward_cents in arcs:
        residual = (
            Decimal(reward_cents)
            - Decimal(p_units) * night_prices[n]
            - Decimal(is_nova) * nova_price
        )
        if residual > tile_prices[i]:
            tile_prices[i] = residual
    science_dual_cents = (
        sum(tile_prices)
        + sum(Decimal(capacity) * price for capacity, price in zip(
            night_capacities, night_prices
        ))
        + Decimal(nova_limit) * nova_price
    )
    science_upper_cents = _ceil_decimal(science_dual_cents) + 1  # extra cent

    attempts = len(range(
        0, int(calendar["survey"]["days"]), int(request["issue_every_n_nights"])
    ))
    request_upper_cents = _ceil_decimal(
        Decimal(100)
        * Decimal(attempts)
        * Decimal(int(request["tiles_per_request"][1]))
        * Decimal(str(request["reward_per_required_tile"]))
    )
    report_upper_cents = _ceil_decimal(
        Decimal(100)
        * Decimal(
            int(tile_config["anomaly_tags"]["nova_count"])
            + int(tile_config["anomaly_tags"]["reddening_count"])
        )
        * Decimal(str(score["reporting"]["reward_correct"]))
    )
    return {
        "scenario": scenario,
        "nights": len(nights),
        "tile_night_arcs": len(arcs) // 2,
        "geometry_completable_tiles": completable,
        "solver_status": "OPTIMAL" if status == pywraplp.Solver.OPTIMAL else str(status),
        "science_dual_upper_bound": science_upper_cents / 100.0,
        "request_upper_bound": request_upper_cents / 100.0,
        "report_upper_bound": report_upper_cents / 100.0,
        "score_upper_bound": (
            science_upper_cents + request_upper_cents + report_upper_cents
        ) / 100.0,
        "dual_numerical_margin_cents": 1,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenarios", nargs="*", default=["eval-a", "eval-b"])
    args = parser.parse_args()
    for scenario in args.scenarios:
        print(json.dumps(bound_scenario(scenario), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
