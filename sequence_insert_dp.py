#!/usr/bin/env python3
"""Exact arbitrary insertion of one required event into a fixed event chain.

The other required events keep their relative order.  A binary state records
whether the selected event has happened; all 150-second starts, exact wait
edges, and currently legal completed-tile tagged revisits remain available.
This optimizes a global single-event relocation neighborhood of the same
restricted practice graph used by sequence_path_dp.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from practice_lns import PracticeModel
from sequence_block_dp import _write
from sequence_dp import PROGRAMS, ordered_events, score_table
from sequence_path_dp import _close_layer, _optional_revisit_arcs


INSERT = -3


def _event_starts(model: PracticeModel, scores: np.ndarray, event: tuple[int, str, bool]) -> np.ndarray:
    i, request_id, _ = event
    starts = np.flatnonzero(np.isfinite(scores[i]))
    if request_id:
        request = model.scorer.requests[request_id]
        moments = model.instants[starts]
        starts = starts[
            (moments >= max(request.issued_at_utc.timestamp(), request.available_from_utc.timestamp()))
            & (moments < request.deadline_utc.timestamp())
        ]
    return starts


def solve_insertion(
    model: PracticeModel,
    scores: np.ndarray,
    programs: np.ndarray,
    events: list[tuple[int, str, bool]],
    moved_index: int,
):
    if not 0 <= moved_index < len(events):
        raise ValueError("event index outside input")
    moved = events[moved_index]
    anchors = [event for j, event in enumerate(events) if j != moved_index]
    n = model.n_units
    m = len(anchors)
    ptr, arc_end, arc_tile, arc_request = _optional_revisit_arcs(model, scores)
    candidate = [_event_starts(model, scores, event) for event in anchors]
    moved_starts = _event_starts(model, scores, moved)
    if len(moved_starts) == 0:
        raise ValueError("moved event has no complete start")
    all_mask = np.uint64((1 << len(model.tiles)) - 1)
    moved_bit = (np.uint64(1) << np.uint64(moved[0])) if moved[2] else np.uint64(0)
    pred_node = np.full((m + 1, 2, n + 1), -1, dtype=np.int32)
    pred_arc = np.full((m + 1, 2, n + 1), -2, dtype=np.int32)
    anchor_start = np.full((m, 2, n + 1), -1, dtype=np.int32)
    dp = np.full((2, n + 1), -np.inf, dtype=np.float64)
    dp[0, 0] = 0.0
    completed = np.uint64(0)

    for k in range(m + 1):
        _close_layer(
            dp[0], model.actionable, all_mask ^ completed,
            ptr, arc_end, arc_tile, completed,
            pred_node[k, 0], pred_arc[k, 0],
        )
        starts = moved_starts[np.isfinite(dp[0, moved_starts])]
        if not moved[2] and not (completed & (np.uint64(1) << np.uint64(moved[0]))):
            starts = starts[:0]
        if len(starts):
            ends = starts + int(model.exposure_units[moved[0]])
            values = dp[0, starts] + (scores[moved[0], starts] if moved[2] else 0.0)
            improve = values > dp[1, ends] + 1e-9
            chosen_ends = ends[improve]
            dp[1, chosen_ends] = values[improve]
            pred_node[k, 1, chosen_ends] = starts[improve]
            pred_arc[k, 1, chosen_ends] = INSERT
        done_after_move = completed | moved_bit
        _close_layer(
            dp[1], model.actionable, all_mask ^ done_after_move,
            ptr, arc_end, arc_tile, done_after_move,
            pred_node[k, 1], pred_arc[k, 1],
        )
        if k == m:
            break
        i, _, first = anchors[k]
        next_dp = np.full((2, n + 1), -np.inf, dtype=np.float64)
        for z in range(2):
            state_completed = completed if z == 0 else done_after_move
            if not first and not (state_completed & (np.uint64(1) << np.uint64(i))):
                continue
            starts = candidate[k]
            starts = starts[np.isfinite(dp[z, starts])]
            if len(starts) == 0:
                continue
            ends = starts + int(model.exposure_units[i])
            values = dp[z, starts] + (scores[i, starts] if first else 0.0)
            next_dp[z, ends] = values
            anchor_start[k, z, ends] = starts
        dp = next_dp
        if first:
            completed |= np.uint64(1) << np.uint64(i)

    end = int(np.argmax(dp[1]))
    if not np.isfinite(dp[1, end]):
        raise ValueError("no feasible insertion")
    predicted = float(dp[1, end])
    path = []
    k = m
    z = 1
    cursor = end
    optional_count = 0
    insertion_position = -1
    while True:
        previous = int(pred_node[k, z, cursor])
        action = int(pred_arc[k, z, cursor])
        if previous >= 0:
            if action >= 0:
                tile = int(arc_tile[action])
                path.append((previous, tile, str(arc_request[action]), "DARK", False))
                optional_count += 1
                cursor = previous
                continue
            if action == -1:
                cursor = previous
                continue
            if action == INSERT and z == 1:
                i, request_id, _ = moved
                path.append((previous, i, request_id, PROGRAMS[int(programs[i, previous])], True))
                insertion_position = k
                cursor = previous
                z = 0
                continue
            raise RuntimeError("broken insertion pointer")
        if k == 0:
            if z != 0 or cursor != 0 or insertion_position < 0:
                raise RuntimeError("insertion path did not reach initial state")
            break
        start = int(anchor_start[k - 1, z, cursor])
        if start < 0:
            raise RuntimeError("broken anchor pointer")
        i, request_id, _ = anchors[k - 1]
        path.append((start, i, request_id, PROGRAMS[int(programs[i, start])], True))
        cursor = start
        k -= 1
    path.reverse()
    return path, predicted, optional_count, insertion_position


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/dev-reference"))
    parser.add_argument("--input", type=Path, default=Path("results/practice_core.csv"))
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--tile", help="tile ID of the first-completion event to relocate")
    target.add_argument("--scan-tiles", help="comma-separated tile IDs for deterministic insertion descent")
    target.add_argument("--scan-all", action="store_true",
                        help="scan every tile's first-completion event in catalog order")
    target.add_argument("--scan-request-events", action="store_true",
                        help="scan all required tagged revisits, moving each anywhere legal")
    target.add_argument("--scan-all-events", action="store_true",
                        help="scan every required event, first completions and tagged revisits")
    parser.add_argument("--passes", type=int, default=1,
                        help="number of complete insertion scans; only strict improvements are accepted")
    parser.add_argument("--out", type=Path, default=Path("runs/practice_insertion/decisions.csv"))
    args = parser.parse_args()
    model = PracticeModel(args.scenario, Path("results/practice_reference.csv"))
    scores, programs = score_table(model)
    events = ordered_events(model, args.input)
    if args.scan_all_events:
        targets = [(model.tile_ids[i], request_id) for i, request_id, _ in events]
    elif args.scan_request_events:
        targets = [(model.tile_ids[i], request_id) for i, request_id, first in events if not first]
    else:
        targets = [(tile_id, None) for tile_id in (
            [args.tile] if args.tile else
            model.tile_ids if args.scan_all else
            [t for t in args.scan_tiles.split(",") if t]
        )]
    if args.passes < 1 or not targets or len(set(targets)) != len(targets):
        raise ValueError("passes must be positive and target tile IDs distinct")
    best = None
    trials = []
    for pass_index in range(args.passes):
        improved = False
        for tile_id, target_request in targets:
            candidates = [j for j, (i, request_id, first) in enumerate(events)
                          if model.tile_ids[i] == tile_id and
                          ((first and target_request is None) or
                           (target_request is not None and request_id == target_request))]
            if len(candidates) != 1:
                raise ValueError(f"{tile_id}/{target_request} must identify one required event")
            path, predicted, optional_count, position = solve_insertion(
                model, scores, programs, events, candidates[0]
            )
            accepted = best is None or predicted > best[1] + 1e-6
            record = {"pass": pass_index, "tile": tile_id,
                      "request_id": events[candidates[0]][1],
                      "input_position": candidates[0],
                      "optimized_position": position,
                      "predicted_without_requests": predicted,
                      "accepted": accepted}
            trials.append(record)
            print(json.dumps(record, sort_keys=True), file=sys.stderr, flush=True)
            if accepted:
                best = (path, predicted, optional_count, position,
                        tile_id, events[candidates[0]][1], candidates[0])
                seen = set()
                next_events = []
                for _, i, request_id, _, mandatory in path:
                    if not mandatory:
                        continue
                    first = i not in seen
                    seen.add(i)
                    next_events.append((i, request_id, first))
                if len(next_events) != len(events):
                    raise RuntimeError("insertion dropped a required event")
                events = next_events
                improved = True
        if not improved:
            break
    assert best is not None
    path, predicted, optional_count, position, best_tile, best_request, input_position = best
    _write(model, args.out, path)
    core = args.out.parent / "core.csv"
    _write(model, core, path, mandatory_only=True)
    report = model.authoritative_score(args.out)
    (args.out.parent / "score_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "tile": best_tile, "request_id": best_request,
        "input_position": input_position,
        "optimized_position": position, "required_events": len(events),
        "optional_events": optional_count,
        "predicted_without_requests": predicted,
        "official_total": report["score"]["total"],
        "science": report["score"]["base_science"] + report["score"]["program_bonus"],
        "request_reward": report["score"]["request_reward"],
        "avoidable_wait": report["score"]["penalties"].get("avoidable_wait", 0.0),
        "output": str(args.out), "core": str(core), "trials": trials,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
