#!/usr/bin/env python3
"""Exact all-cursor path DP for a fixed sequence of required observations.

Between required events the path may wait, or make any scorer-completable
request-tagged revisit of a tile already completed by an earlier required
event.  These optional zero-science arcs are chosen by the DP, not fixed in a
seed plan.  This is a precise restricted subproblem of the practice scorer;
the request labels on the required events remain fixed.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from numba import njit

import bounds_public as geometry
from challenge.contracts import DECISION_COLUMNS
from practice_lns import PracticeModel
from sequence_dp import PROGRAMS, ordered_events, score_table


@njit(cache=True)
def _close_layer(
    dp: np.ndarray,
    actionable: np.ndarray,
    uncompleted: np.uint64,
    ptr: np.ndarray,
    arc_end: np.ndarray,
    arc_tile: np.ndarray,
    completed: np.uint64,
    pred_node: np.ndarray,
    pred_arc: np.ndarray,
) -> None:
    """Longest paths in one time-DAG layer, including optional repeat arcs."""
    n = len(actionable)
    for u in range(n):
        value = dp[u]
        if not np.isfinite(value):
            continue
        boundary = (u // geometry.POINTS_PER_SLOT + 1) * geometry.POINTS_PER_SLOT
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
            if not (completed & (np.uint64(1) << np.uint64(arc_tile[a]))):
                continue
            end = arc_end[a]
            if value > dp[end] + 1e-9:
                dp[end] = value
                pred_node[end] = u
                pred_arc[end] = a


def _optional_revisit_arcs(model: PracticeModel, scores: np.ndarray):
    """All complete arcs that can carry an active request label at start."""
    scorer = model.scorer
    starts_parts = []
    ends_parts = []
    tiles_parts = []
    requests_parts = []
    for i, tile_id in enumerate(model.tile_ids):
        starts = np.flatnonzero(np.isfinite(scores[i])).astype(np.int32)
        if len(starts) == 0:
            continue
        selected = np.zeros(len(starts), dtype=np.bool_)
        labels = np.full(len(starts), -1, dtype=np.int16)
        possible_requests = [
            request_id for request_id in scorer.requests
            if tile_id in scorer.request_tiles[request_id]
        ]
        for request_number, request_id in enumerate(possible_requests):
            request = scorer.requests[request_id]
            moment = model.instants[starts]
            mask = (
                (moment >= max(request.issued_at_utc.timestamp(), request.available_from_utc.timestamp()))
                & (moment < request.deadline_utc.timestamp())
                & ~selected
            )
            selected[mask] = True
            labels[mask] = request_number
        if not np.any(selected):
            continue
        these_starts = starts[selected]
        starts_parts.append(these_starts)
        ends_parts.append(these_starts + model.exposure_units[i])
        tiles_parts.append(np.full(len(these_starts), i, dtype=np.int16))
        requests_parts.extend(possible_requests[int(x)] for x in labels[selected])
    if not starts_parts:
        raise ValueError("no legal request-tagged revisits")
    starts = np.concatenate(starts_parts)
    ends = np.concatenate(ends_parts).astype(np.int32)
    tiles = np.concatenate(tiles_parts)
    requests = np.array(requests_parts, dtype=object)
    order = np.argsort(starts, kind="stable")
    starts, ends, tiles, requests = starts[order], ends[order], tiles[order], requests[order]
    ptr = np.empty(model.n_units + 1, dtype=np.int64)
    ptr[0] = 0
    np.cumsum(np.bincount(starts, minlength=model.n_units), out=ptr[1:])
    return ptr, ends, tiles, requests


def solve_path(
    model: PracticeModel,
    scores: np.ndarray,
    programs: np.ndarray,
    events: list[tuple[int, str, bool]],
):
    """Optimize exact timing and optional legal revisit path for fixed events."""
    n = model.n_units
    m = len(events)
    ptr, arc_end, arc_tile, arc_request = _optional_revisit_arcs(model, scores)
    pred_node = np.full((m + 1, n + 1), -1, dtype=np.int32)
    pred_arc = np.full((m + 1, n + 1), -2, dtype=np.int32)
    event_start = np.full((m, n + 1), -1, dtype=np.int32)
    dp = np.full(n + 1, -np.inf, dtype=np.float64)
    dp[0] = 0.0
    completed = np.uint64(0)
    all_mask = np.uint64((1 << len(model.tiles)) - 1)
    candidate_starts = [np.flatnonzero(np.isfinite(scores[i]))
                        for i in range(len(model.tiles))]
    for k, (i, request_id, first) in enumerate(events):
        _close_layer(
            dp, model.actionable, all_mask ^ completed, ptr, arc_end,
            arc_tile, completed, pred_node[k], pred_arc[k],
        )
        starts = candidate_starts[i]
        if request_id:
            request = model.scorer.requests[request_id]
            moments = model.instants[starts]
            starts = starts[
                (moments >= max(request.issued_at_utc.timestamp(), request.available_from_utc.timestamp()))
                & (moments < request.deadline_utc.timestamp())
            ]
        starts = starts[np.isfinite(dp[starts])]
        if len(starts) == 0:
            raise ValueError(f"event {k+1} ({model.tile_ids[i]} {request_id}) is unreachable")
        ends = starts + int(model.exposure_units[i])
        values = dp[starts] + (scores[i, starts] if first else 0.0)
        next_dp = np.full(n + 1, -np.inf, dtype=np.float64)
        next_dp[ends] = values
        event_start[k, ends] = starts
        dp = next_dp
        if first:
            completed |= np.uint64(1) << np.uint64(i)

    # The result table terminates at its last decision; further actions only
    # add waiting expense and have no required future event.
    end = int(np.argmax(dp))
    predicted = float(dp[end])
    path = []
    optional_count = 0
    for k in range(m - 1, -1, -1):
        start = int(event_start[k, end])
        if start < 0:
            raise RuntimeError("mandatory backpointer missing")
        i, request_id, _ = events[k]
        path.append((start, i, request_id, PROGRAMS[int(programs[i, start])]))
        cursor = start
        while pred_node[k, cursor] >= 0:
            previous = int(pred_node[k, cursor])
            a = int(pred_arc[k, cursor])
            if a >= 0:
                tile = int(arc_tile[a])
                path.append((previous, tile, str(arc_request[a]), "DARK"))
                optional_count += 1
            cursor = previous
        end = cursor
    if end != 0:
        raise RuntimeError("path did not backtrace to initial cursor")
    path.reverse()
    return path, predicted, optional_count, len(arc_end)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/dev-reference"))
    parser.add_argument("--input", type=Path, default=Path("results/practice_reference.csv"))
    parser.add_argument("--out", type=Path, default=Path("runs/practice_path_dp/decisions.csv"))
    args = parser.parse_args()
    model = PracticeModel(args.scenario, Path("results/practice_reference.csv"))
    scores, programs = score_table(model)
    events = ordered_events(model, args.input)
    path, predicted, optional_count, arc_count = solve_path(model, scores, programs, events)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for number, (start, i, request_id, program) in enumerate(path, 1):
            writer.writerow({
                "decision_id": f"D{number:06d}",
                "slot_id": model.scorer.slots[start // geometry.POINTS_PER_SLOT].slot_id,
                "action": "observe", "tile_id": model.tile_ids[i],
                "program": program, "request_id": request_id, "reason": "",
            })
    report = model.authoritative_score(args.out)
    (args.out.parent / "score_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "required_events": len(events), "optional_events": optional_count,
        "optional_arcs": arc_count, "predicted_without_requests": predicted,
        "official_total": report["score"]["total"],
        "science": report["score"]["base_science"] + report["score"]["program_bonus"],
        "request_reward": report["score"]["request_reward"],
        "avoidable_wait": report["score"]["penalties"].get("avoidable_wait", 0.0),
        "output": str(args.out),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
