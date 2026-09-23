#!/usr/bin/env python3
"""Exact fixed-order practice path DP with zero-science weather interruptions.

Keeps the 89 mandatory observation events and request labels fixed. Between
them, the telescope may wait, revisit a completed tile with a legal request
tag, or attempt an uncompleted tile that will be interrupted by later weather.
Every weather-interrupted edge has an exact scorer-checked tile witness.
"""

from __future__ import annotations

import argparse
import csv
import json
from bisect import bisect_right
from datetime import timedelta
from pathlib import Path

import numpy as np
from numba import njit

import bounds_public as geometry
from bounds_practice_projection import _partial_weather_arcs
from challenge.contracts import DECISION_COLUMNS
from practice_lns import PracticeModel
from sequence_dp import PROGRAMS, ordered_events, score_table
from sequence_path_dp import _optional_revisit_arcs


@njit(cache=True)
def _close_layer(
    dp: np.ndarray,
    actionable: np.ndarray,
    completed: np.uint64,
    ptr: np.ndarray,
    arc_end: np.ndarray,
    arc_tile: np.ndarray,
    arc_kind: np.ndarray,
    pred_node: np.ndarray,
    pred_arc: np.ndarray,
) -> None:
    n = len(actionable)
    full_mask = np.uint64(0xffffffffffffffff)
    uncompleted = full_mask ^ completed
    for u in range(n):
        value = dp[u]
        if not np.isfinite(value):
            continue
        boundary = ((u // geometry.POINTS_PER_SLOT) + 1) * geometry.POINTS_PER_SLOT
        charge = (
            (boundary - u) * geometry.UNIT_SECONDS * 0.001
            if actionable[u] & uncompleted else 0.0
        )
        proposal = value - charge
        if proposal > dp[boundary] + 1e-9:
            dp[boundary] = proposal
            pred_node[boundary] = u
            pred_arc[boundary] = -1
        for a in range(ptr[u], ptr[u + 1]):
            tile_bit = np.uint64(1) << np.uint64(arc_tile[a])
            if arc_kind[a] == 0:
                if not (completed & tile_bit):
                    continue
            else:
                if not (uncompleted & tile_bit):
                    continue
            end = arc_end[a]
            if value > dp[end] + 1e-9:
                dp[end] = value
                pred_node[end] = u
                pred_arc[end] = a


def _scorer_weather_interrupt_end(scorer, tile, start_unit: int) -> int | None:
    """Return the exact no-penalty weather-failure cursor, if it occurs."""
    slot_index, offset_units = divmod(start_unit, geometry.POINTS_PER_SLOT)
    if slot_index >= len(scorer.slots):
        return None
    first_night = scorer.slots[slot_index].night_id
    remaining = tile.nominal_exptime_seconds
    offset_seconds = offset_units * geometry.UNIT_SECONDS
    observed_seconds = 0
    while remaining:
        if slot_index >= len(scorer.slots):
            return None
        slot = scorer.slots[slot_index]
        if slot.night_id != first_night:
            return None
        moment = slot.timestamp_utc + timedelta(seconds=offset_seconds)
        if not scorer._tile_legal(tile, moment):
            return None
        if not scorer.weather.get_effective_conditions(
            slot.slot_id, tile.tile_id
        )["is_observable"]:
            return (
                slot_index * geometry.POINTS_PER_SLOT
                if observed_seconds else None
            )
        seconds = min(remaining, slot.duration_seconds - offset_seconds)
        observed_seconds += seconds
        remaining -= seconds
        slot_index += 1
        offset_seconds = 0
    return None


def _scored_partial_arcs(model: PracticeModel):
    """Expand every audited pair to all exact tile witnesses, retaining IDs."""
    pair_starts, pair_ends = _partial_weather_arcs(
        model.scenario, model.scorer, model.instants
    )
    starts = []
    ends = []
    tiles = []
    pairs_without_witness = 0
    for start, end in zip(pair_starts, pair_ends):
        found = False
        for i, tile_id in enumerate(model.tile_ids):
            observed_end = _scorer_weather_interrupt_end(
                model.scorer, model.scorer.tiles[tile_id], int(start)
            )
            if observed_end == int(end):
                starts.append(int(start))
                ends.append(int(end))
                tiles.append(i)
                found = True
        if not found:
            pairs_without_witness += 1
    if pairs_without_witness:
        raise AssertionError(
            f"{pairs_without_witness} nominal partial arcs have no scorer witness"
        )
    return (
        np.array(starts, dtype=np.int32),
        np.array(ends, dtype=np.int32),
        np.array(tiles, dtype=np.int16),
        len(pair_starts),
    )


def max_partial_interval_units(starts: np.ndarray, ends: np.ndarray) -> int:
    """Maximum total elapsed grid units of nonoverlapping partial arcs."""
    intervals = sorted(
        zip(map(int, starts), map(int, ends)), key=lambda pair: pair[1]
    )
    ending = [v for _, v in intervals]
    best = [0] * (len(intervals) + 1)
    for j, (u, v) in enumerate(intervals, 1):
        predecessor = bisect_right(ending, u, 0, j - 1)
        best[j] = max(best[j - 1], best[predecessor] + v - u)
    return best[-1]


def build_action_arcs(model: PracticeModel, scores: np.ndarray):
    repeat_ptr, repeat_end, repeat_tile, repeat_request = (
        _optional_revisit_arcs(model, scores)
    )
    repeat_start = np.repeat(
        np.arange(model.n_units, dtype=np.int32),
        np.diff(repeat_ptr),
    )
    partial_start, partial_end, partial_tile, pair_count = (
        _scored_partial_arcs(model)
    )
    maximal_partial_units = max_partial_interval_units(
        partial_start, partial_end
    )
    all_start = np.concatenate((repeat_start, partial_start))
    all_end = np.concatenate((repeat_end, partial_end))
    all_tile = np.concatenate((repeat_tile, partial_tile))
    all_kind = np.concatenate((
        np.zeros(len(repeat_start), dtype=np.uint8),
        np.ones(len(partial_start), dtype=np.uint8),
    ))
    all_request = np.concatenate((
        repeat_request,
        np.full(len(partial_start), "", dtype=object),
    ))
    order = np.argsort(all_start, kind="stable")
    all_start = all_start[order]
    all_end = all_end[order]
    all_tile = all_tile[order]
    all_kind = all_kind[order]
    all_request = all_request[order]
    ptr = np.empty(model.n_units + 1, dtype=np.int64)
    ptr[0] = 0
    np.cumsum(
        np.bincount(all_start, minlength=model.n_units),
        out=ptr[1:],
    )
    return (
        ptr, all_end, all_tile, all_kind, all_request,
        len(repeat_start), len(partial_start), pair_count,
        maximal_partial_units,
    )


def solve(
    model: PracticeModel,
    scores: np.ndarray,
    programs: np.ndarray,
    events: list[tuple[int, str, bool]],
):
    n, m = model.n_units, len(events)
    (
        ptr, arc_end, arc_tile, arc_kind, arc_request,
        repeat_count, partial_count, pair_count, maximal_partial_units,
    ) = build_action_arcs(model, scores)
    pred_node = np.full((m + 1, n + 1), -1, dtype=np.int32)
    pred_arc = np.full((m + 1, n + 1), -2, dtype=np.int32)
    event_start = np.full((m, n + 1), -1, dtype=np.int32)
    dp = np.full(n + 1, -np.inf, dtype=np.float64)
    dp[0] = 0.0
    completed = np.uint64(0)
    candidate_starts = [
        np.flatnonzero(np.isfinite(scores[i]))
        for i in range(len(model.tiles))
    ]
    for k, (i, request_id, first) in enumerate(events):
        _close_layer(
            dp, model.actionable, completed, ptr, arc_end,
            arc_tile, arc_kind, pred_node[k], pred_arc[k],
        )
        starts = candidate_starts[i]
        if request_id:
            request = model.scorer.requests[request_id]
            moments = model.instants[starts]
            starts = starts[
                (moments >= max(
                    request.issued_at_utc.timestamp(),
                    request.available_from_utc.timestamp(),
                ))
                & (moments < request.deadline_utc.timestamp())
            ]
        starts = starts[np.isfinite(dp[starts])]
        if len(starts) == 0:
            raise ValueError(
                f"mandatory event {k+1}: {model.tile_ids[i]}/{request_id} unreachable"
            )
        ends = starts + int(model.exposure_units[i])
        values = dp[starts] + (scores[i, starts] if first else 0.0)
        next_dp = np.full(n + 1, -np.inf, dtype=np.float64)
        next_dp[ends] = values
        event_start[k, ends] = starts
        dp = next_dp
        if first:
            completed |= np.uint64(1) << np.uint64(i)

    end = int(np.argmax(dp))
    predicted = float(dp[end])
    path = []
    repeat_used = 0
    partial_used = 0
    for k in range(m - 1, -1, -1):
        start = int(event_start[k, end])
        if start < 0:
            raise RuntimeError("mandatory event backpointer missing")
        i, request_id, _ = events[k]
        path.append((
            start, i, request_id,
            PROGRAMS[int(programs[i, start])], True, "mandatory",
        ))
        cursor = start
        while pred_node[k, cursor] >= 0:
            previous = int(pred_node[k, cursor])
            a = int(pred_arc[k, cursor])
            if a >= 0:
                i = int(arc_tile[a])
                if arc_kind[a] == 0:
                    path.append((
                        previous, i, str(arc_request[a]), "DARK",
                        False, "revisit",
                    ))
                    repeat_used += 1
                else:
                    path.append((
                        previous, i, "", "DARK",
                        False, "weather_interrupted",
                    ))
                    partial_used += 1
            cursor = previous
        end = cursor
    if end != 0:
        raise RuntimeError("time path did not backtrace to the source")
    path.reverse()
    return (
        path, predicted, repeat_used, partial_used,
        repeat_count, partial_count, pair_count, maximal_partial_units,
    )


def write_path(model: PracticeModel, destination: Path, path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=DECISION_COLUMNS, lineterminator="\n"
        )
        writer.writeheader()
        for number, (start, i, request_id, program, _, _) in enumerate(path, 1):
            writer.writerow({
                "decision_id": f"D{number:06d}",
                "slot_id": model.scorer.slots[
                    start // geometry.POINTS_PER_SLOT
                ].slot_id,
                "action": "observe",
                "tile_id": model.tile_ids[i],
                "program": program,
                "request_id": request_id,
                "reason": "",
            })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario", type=Path, default=Path("scenarios/dev-reference")
    )
    parser.add_argument(
        "--input", type=Path,
        default=Path("results/practice_core.csv"),
    )
    parser.add_argument(
        "--out", type=Path, default=Path("runs/practice_weather_path"),
    )
    args = parser.parse_args()
    if args.scenario.name != "dev-reference":
        raise ValueError("only the public-weather practice case is supported")
    model = PracticeModel(args.scenario, Path("results/practice_reference.csv"))
    scores, programs = score_table(model)
    events = ordered_events(model, args.input)
    if len(events) != 89 or sum(first for _, _, first in events) != 64:
        raise ValueError("expected the specified 89-event complete core")
    (
        path, predicted, repeat_used, partial_used,
        repeat_count, partial_count, pair_count, maximal_partial_units,
    ) = solve(model, scores, programs, events)
    args.out.mkdir(parents=True, exist_ok=True)
    decisions = args.out / "decisions.csv"
    core = args.out / "core.csv"
    write_path(model, decisions, path)
    write_path(model, core, [item for item in path if item[4]])
    report = model.authoritative_score(decisions)
    expected_requests = {
        row["request_id"] for row in report["requests"]
        if row["status"] == "completed"
    }
    if len(expected_requests) != 17:
        raise AssertionError("a feasible request was lost")
    if report["score"]["request_reward"] != 3920.0:
        raise AssertionError("request reward changed")
    if report["score"]["penalties"].get("request_miss", 0.0) != 0.0:
        raise AssertionError("a request miss was introduced")
    if len(report["completion"]["completed_tiles"]) != 64:
        raise AssertionError("a first tile completion was lost")
    outcomes = [row["outcome"] for row in report["actions"]]
    if outcomes.count("weather_interrupted") != partial_used:
        raise AssertionError("some selected partial arc did not weather-interrupt")
    if any(
        outcome not in ("completed", "weather_interrupted")
        for outcome in outcomes
    ):
        raise AssertionError("an invalid or unsafe action was selected")
    if abs(
        report["score"]["total"] - predicted - report["score"]["request_reward"]
    ) > 1e-5:
        raise AssertionError("DP objective disagrees with scorer replay")

    original_report = json.loads(
        (args.input.parent / "score_report.json").read_text(encoding="utf-8")
    )
    original_total = float(original_report["score"]["total"])
    summary = {
        "source_core": str(args.input),
        "mandatory_events": len(events),
        "repeat_candidate_arcs": repeat_count,
        "partial_candidate_pairs": pair_count,
        "partial_tile_labeled_arcs": partial_count,
        "max_partial_nonoverlap_units": maximal_partial_units,
        "universal_partial_gain_cap": (
            maximal_partial_units * geometry.UNIT_SECONDS * 0.001
        ),
        "selected_repeats": repeat_used,
        "selected_weather_interruptions": partial_used,
        "selected_interruption_elapsed_seconds": sum(
            int(row["elapsed_seconds"])
            for row in report["actions"]
            if row["outcome"] == "weather_interrupted"
        ),
        "selected_actions": len(path),
        "predicted_without_requests": predicted,
        "source_official_total": original_total,
        "official_total": report["score"]["total"],
        "improvement": report["score"]["total"] - original_total,
        "science": (
            report["score"]["base_science"]
            + report["score"]["program_bonus"]
        ),
        "request_reward": report["score"]["request_reward"],
        "avoidable_wait": report["score"]["penalties"].get(
            "avoidable_wait", 0.0
        ),
        "invalid_action_penalty": report["score"]["penalties"].get(
            "invalid_action", 0.0
        ),
        "unsafe_observation_penalty": report["score"]["penalties"].get(
            "unsafe_observation", 0.0
        ),
        "decisions": str(decisions),
        "core": str(core),
    }
    (args.out / "summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.out / "score_report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
