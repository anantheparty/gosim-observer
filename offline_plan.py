#!/usr/bin/env python3
"""Plan a public-weather Playground trace.

For each tile, enumerate safe slot-boundary exposures and calculate the exact
science value using the frozen scorer's geometry and weather interfaces. Place
high-value exposures greedily, then fit request visits into open intervals.
The result is a feasible weighted-interval packing heuristic, not a proof of
global optimality. Competition weather is hidden, so this tool is for public
practice scenarios only; the online entry is agent/my_strategy.py.
"""

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

from challenge.contracts import DECISION_COLUMNS
from challenge.scoring_core import ChallengeScorer
from challenge.weather_simulator import weather_quality


PROGRAMS = ("DARK", "BRIGHT", "BACKUP")


@dataclass(frozen=True)
class Option:
    tile_id: str
    slot_id: str
    start: object
    end: object
    score: float
    program: str
    request_id: str = ""


def exact_option(scorer, tile, index):
    slot = scorer.slots[index]
    start = slot.timestamp_utc
    if not tile.available_from_utc <= start < tile.available_until_utc:
        return None
    remaining = tile.nominal_exptime_seconds
    segments = []
    first_night = slot.night_id
    while remaining > 0:
        if index >= len(scorer.slots):
            return None
        slot = scorer.slots[index]
        if slot.night_id != first_night:
            return None
        seconds = min(remaining, slot.duration_seconds)
        midpoint = slot.timestamp_utc + timedelta(seconds=seconds / 2)
        if not scorer._tile_legal(tile, slot.timestamp_utc) or not scorer._tile_legal(tile, midpoint):
            return None
        conditions = scorer.weather.get_effective_conditions(slot.slot_id, tile.tile_id)
        if not conditions["is_observable"]:
            return None
        geometry = scorer.geometry.get_tile_geometry(tile.tile_id, midpoint)
        atmospheric = weather_quality(conditions, float(geometry["airmass"]), scorer.weather.config)
        if scorer.mechanics:
            band_atmospheric = weather_quality(
                conditions, float(geometry["airmass"]), scorer.weather.config,
                include_efficiency=False,
            )
        else:
            band_atmospheric = atmospheric
        lunar = float(geometry["lunar_quality_factor"])
        base = scorer.tile_values[tile.tile_id] * seconds / tile.nominal_exptime_seconds * atmospheric * lunar
        band = scorer._quality_band(band_atmospheric * lunar)
        segments.append((base, band))
        remaining -= seconds
        index += 1
    scores = {
        program: sum(
            base * (1 + float(scorer.config["program_bonus"][program]) if band == program else 1)
            for base, band in segments
        )
        for program in PROGRAMS
    }
    program = max(PROGRAMS, key=lambda name: scores[name])
    return Option(tile.tile_id, scorer.slots[index - len(segments)].slot_id, start,
                  start + timedelta(seconds=tile.nominal_exptime_seconds), scores[program], program)


def free(option, occupied, ignore=None):
    return all(
        other is ignore or option.end <= other.start or other.end <= option.start
        for other in occupied
    )


def valid_for_request(option, request):
    return request.available_from_utc <= option.start and option.end <= request.deadline_utc


def make_plan(scorer):
    options = defaultdict(list)
    for tile in scorer.tiles.values():
        for index, slot in enumerate(scorer.slots):
            if slot.timestamp_utc < tile.available_from_utc or slot.timestamp_utc >= tile.available_until_utc:
                continue
            option = exact_option(scorer, tile, index)
            if option is not None:
                options[tile.tile_id].append(option)
        options[tile.tile_id].sort(key=lambda row: row.score, reverse=True)

    occupied = []
    science = {}

    # Fix scarce request windows before placing observations that can move
    # anywhere in the season. A later request for the same tile needs a
    # separate tagged visit after the first observation.
    for request in sorted(scorer.requests.values(), key=lambda row: row.deadline_utc):
        candidates = []
        for tile_id, count in scorer.request_tiles[request.request_id].items():
            if count != 1:
                continue
            primary = science.get(tile_id)
            if primary is not None and valid_for_request(primary, request) and not primary.request_id:
                candidates.append((0, 0.0, tile_id, "tag", [primary]))
                continue
            viable = [
                option for option in options[tile_id]
                if valid_for_request(option, request)
                and (primary is None or option.start >= primary.end)
                and free(option, occupied)
            ]
            if viable:
                best = max(viable, key=lambda row: row.score)
                candidates.append((len(viable), -best.score if primary is None else 0.0,
                                   tile_id, "primary" if primary is None else "revisit", viable))
        candidates.sort(key=lambda row: row[:3])
        selected = 0
        for _, _, tile_id, kind, viable in candidates:
            if selected >= request.required_tile_count:
                break
            option = viable[0] if kind == "tag" else max(
                (row for row in viable if free(row, occupied)),
                key=lambda row: row.score, default=None,
            )
            if option is None:
                continue
            tagged = replace(option, request_id=request.request_id)
            if kind == "tag":
                occupied.remove(science[tile_id])
                science[tile_id] = tagged
            elif kind == "primary":
                science[tile_id] = tagged
            occupied.append(tagged)
            selected += 1

    def priority(tile_id):
        tile = scorer.tiles[tile_id]
        choices = len(options[tile_id])
        if tile.scheduling_class == "REQUIRED" and choices:
            return (0, choices, -options[tile_id][0].score)
        return (1, -options[tile_id][0].score if choices else 0, tile_id)

    for tile_id in sorted(options, key=priority):
        if tile_id in science:
            continue
        for option in options[tile_id]:
            if free(option, occupied):
                science[tile_id] = option
                occupied.append(option)
                break

    return sorted(occupied, key=lambda row: row.start)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    scorer = ChallengeScorer.from_files(args.scenario)
    plan = make_plan(scorer)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS)
        writer.writeheader()
        for index, option in enumerate(plan, start=1):
            writer.writerow({"decision_id": f"D{index:06d}", "slot_id": option.slot_id,
                             "action": "observe", "tile_id": option.tile_id,
                             "program": option.program, "request_id": option.request_id,
                             "reason": ""})
    print(f"wrote {len(plan)} observations to {args.out}")


if __name__ == "__main__":
    main()
