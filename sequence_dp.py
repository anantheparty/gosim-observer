#!/usr/bin/env python3
"""Exact timing DP for a fixed ordered list of public-practice observations.

The sequence of tiles and request labels is fixed, but every observation may
move to any scorer-completable 150-second start reachable through legal waits
and preceding observations. This is a restricted, mathematically exact
subproblem; the authoritative scorer validates the reconstructed path.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

import bounds_public as geometry
from challenge.contracts import DECISION_COLUMNS
from challenge.scoring_core import load_decisions
from practice_lns import PracticeModel


PROGRAMS = ("DARK", "BRIGHT", "BACKUP")
FULL_MASK = (1 << 64) - 1


def score_table(model: PracticeModel) -> tuple[np.ndarray, np.ndarray]:
    """Complete success/score catalog on the entire 150-second grid."""
    scorer = model.scorer
    n_tiles = len(model.tiles)
    table = np.full((n_tiles, model.n_units), -np.inf, dtype=np.float64)
    program = np.zeros((n_tiles, model.n_units), dtype=np.uint8)
    wc = model.weather_config
    exponent = float(wc["score_interface"]["airmass_exponent"])
    cap = float(wc["score_interface"]["maximum_weather_quality"])
    dark = float(scorer.config["quality_thresholds"]["dark"])
    bright = float(scorer.config["quality_thresholds"]["bright"])
    bonuses = scorer.config["program_bonus"]
    for i, tile in enumerate(model.tiles):
        tile_id = tile["tile_id"]
        exposure = int(tile["nominal_exptime_seconds"])
        candidate = np.flatnonzero(geometry._geometry_candidate_mask(
            tile, model.instants, model.sidereal, model.night_end,
            model.latitude, model.minimum_altitude,
        ))
        observable = np.zeros(len(model.slots), dtype=np.bool_)
        weather_numerator = np.zeros(len(model.slots), dtype=np.float64)
        for index, slot in enumerate(scorer.slots):
            conditions = scorer.weather.get_effective_conditions(slot.slot_id, tile_id)
            if conditions["is_observable"]:
                observable[index] = True
                weather_numerator[index] = (
                    float(conditions["instrument_efficiency"])
                    * float(conditions["transparency"])
                    * float(conditions["sky_quality"])
                    / float(conditions["seeing_arcsec"])
                )
        for offset in range(geometry.POINTS_PER_SLOT):
            starts = candidate[candidate % geometry.POINTS_PER_SLOT == offset]
            segments = geometry._segments(
                exposure, offset * geometry.UNIT_SECONDS
            )
            for segment_index in range(len(segments)):
                starts = starts[observable[
                    starts // geometry.POINTS_PER_SLOT + segment_index
                ]]
            if len(starts) == 0:
                continue
            base = np.zeros(len(starts), dtype=np.float64)
            matched = np.zeros((3, len(starts)), dtype=np.float64)
            for segment_index, (seconds, midpoint_after_start) in enumerate(segments):
                slot_indices = starts // geometry.POINTS_PER_SLOT + segment_index
                quality = geometry._segment_quality_upper(
                    tile, model.instants[starts] + midpoint_after_start,
                    model.latitude, model.longitude,
                    model.tile_config["lunar_model"],
                    weather_numerator[slot_indices], exponent, cap,
                )
                part = seconds / exposure * quality
                base += part
                matched[0] += part * (quality >= dark)
                matched[1] += part * ((quality < dark) & (quality >= bright))
                matched[2] += part * (quality < bright)
            matched[0] *= float(bonuses["DARK"])
            matched[1] *= float(bonuses["BRIGHT"])
            matched[2] *= float(bonuses["BACKUP"])
            chosen = np.argmax(matched, axis=0)
            table[i, starts] = scorer.tile_values[tile_id] * (
                base + matched[chosen, np.arange(len(starts))]
            )
            program[i, starts] = chosen.astype(np.uint8)
    return table, program


def ordered_events(model: PracticeModel, seed: Path):
    rows = [item for item in load_decisions(seed, allow_reports=False)
            if item.action == "observe"]
    result = []
    seen = set()
    for row in rows:
        i = model.tile_index[row.tile_id]
        first = i not in seen
        seen.add(i)
        result.append((i, row.request_id, first))
    if len(seen) != len(model.tile_ids):
        raise ValueError("seed order does not complete all 64 tiles")
    return result


def solve_order(
    model: PracticeModel, scores: np.ndarray, programs: np.ndarray,
    events: list[tuple[int, str, bool]],
):
    n = model.n_units
    points = geometry.POINTS_PER_SLOT
    durations = model.exposure_units
    request_window = {}
    for request_id, request in model.scorer.requests.items():
        request_window[request_id] = (
            request.issued_at_utc.timestamp(),
            request.available_from_utc.timestamp(),
            request.deadline_utc.timestamp(),
        )
    candidate_starts = [np.flatnonzero(np.isfinite(scores[i]))
                        for i in range(len(model.tiles))]
    dp = np.full(n + 1, -np.inf, dtype=np.float64)
    dp[0] = 0.0
    back_start = np.full((len(events), n + 1), -1, dtype=np.int32)
    back_end = np.full((len(events), n + 1), -1, dtype=np.int32)
    completed = 0
    for k, (i, request_id, first) in enumerate(events):
        wait_cost = (
            ((model.actionable & np.uint64(FULL_MASK ^ completed)) != 0)
            * ((points - model.unit_index % points)
               * geometry.UNIT_SECONDS * 0.001)
        )
        origin = np.full(n + 1, -1, dtype=np.int32)
        origin[np.isfinite(dp)] = np.flatnonzero(np.isfinite(dp))
        # One wait edge from every six grid nodes to the next slot boundary.
        # Processing slots in order propagates arbitrarily long legal waits.
        for slot_index in range(len(model.slots)):
            lo = slot_index * points
            hi = lo + points
            candidates = dp[lo:hi] - wait_cost[lo:hi]
            best_offset = int(np.argmax(candidates))
            best = candidates[best_offset]
            if best > dp[hi]:
                dp[hi] = best
                origin[hi] = origin[lo + best_offset]
        starts = candidate_starts[i]
        if request_id:
            issued, available, deadline = request_window[request_id]
            moments = model.instants[starts]
            starts = starts[
                (moments >= issued)
                & (moments >= available)
                & (moments < deadline)
            ]
        finite = np.isfinite(dp[starts])
        starts = starts[finite]
        if len(starts) == 0:
            raise ValueError(f"ordered event {k+1} has no reachable start")
        ends = starts + int(durations[i])
        values = dp[starts] + (scores[i, starts] if first else 0.0)
        next_dp = np.full(n + 1, -np.inf, dtype=np.float64)
        next_dp[ends] = values
        back_start[k, ends] = starts
        back_end[k, ends] = origin[starts]
        dp = next_dp
        if first:
            completed |= 1 << i
    final = int(np.argmax(dp))
    predicted = float(dp[final])
    path = []
    end = final
    for k in range(len(events) - 1, -1, -1):
        start = int(back_start[k, end])
        preceding = int(back_end[k, end])
        if start < 0 or preceding < 0:
            raise RuntimeError("broken timing DP backtrace")
        i, request_id, first = events[k]
        path.append((start, i, request_id, PROGRAMS[int(programs[i, start])]))
        end = preceding
    if end != 0:
        raise RuntimeError("timing DP did not trace to source")
    path.reverse()
    return path, predicted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/dev-reference"))
    parser.add_argument("--input", type=Path, default=Path("results/practice_reference.csv"))
    parser.add_argument("--model-seed", type=Path,
                        help="observation-only seed for shared precomputation")
    parser.add_argument("--out", type=Path, default=Path("runs/practice_timing/decisions.csv"))
    args = parser.parse_args()
    model = PracticeModel(args.scenario, args.model_seed or args.input)
    scores, programs = score_table(model)
    events = ordered_events(model, args.input)
    path, predicted_without_requests = solve_order(model, scores, programs, events)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS)
        writer.writeheader()
        for number, (start, i, request_id, program) in enumerate(path, 1):
            writer.writerow({
                "decision_id": f"D{number:06d}",
                "slot_id": model.scorer.slots[start // geometry.POINTS_PER_SLOT].slot_id,
                "action": "observe",
                "tile_id": model.tile_ids[i],
                "program": program,
                "request_id": request_id,
                "reason": "",
            })
    report = model.authoritative_score(args.out)
    (args.out.parent / "score_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "ordered_observations": len(events),
        "full_grid_complete_candidates": int(np.isfinite(scores).sum()),
        "predicted_without_requests": predicted_without_requests,
        "official_score": report["score"]["total"],
        "science": report["score"]["base_science"] + report["score"]["program_bonus"],
        "request_reward": report["score"]["request_reward"],
        "avoidable_wait": report["score"]["penalties"].get("avoidable_wait", 0.0),
        "output": str(args.out),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
