#!/usr/bin/env python3
"""Exact block-order and all-cursor path DP for public practice.

Partition required events into consecutive small blocks.  Within each block,
the DP optimizes every event permutation subject to first-before-revisit,
every 150-second start, all legal waits, and all available tagged revisits of
previously completed tiles.  Block order is fixed; the global original problem
is not claimed optimal.  With blocks of size b the complexity is
O(sum_blocks 2**b * (time_grid + revisit_arcs + b*candidate_starts)).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

import bounds_public as geometry
from challenge.contracts import DECISION_COLUMNS
from practice_lns import PracticeModel
from sequence_dp import PROGRAMS, ordered_events, score_table
from sequence_path_dp import _close_layer, _optional_revisit_arcs


def _blocks(count: int, size: int, offset: int) -> list[list[int]]:
    if size < 1 or not 0 <= offset < size:
        raise ValueError("invalid block size or offset")
    result = []
    start = 0
    if offset:
        result.append(list(range(min(offset, count))))
        start = min(offset, count)
    while start < count:
        result.append(list(range(start, min(start + size, count))))
        start += size
    return result


def solve_blocks(
    model: PracticeModel,
    scores: np.ndarray,
    programs: np.ndarray,
    events: list[tuple[int, str, bool]],
    block_size: int,
    offset: int,
):
    n = model.n_units
    ptr, arc_end, arc_tile, arc_request = _optional_revisit_arcs(model, scores)
    starts_for_event = []
    for i, request_id, _ in events:
        starts = np.flatnonzero(np.isfinite(scores[i]))
        if request_id:
            request = model.scorer.requests[request_id]
            moments = model.instants[starts]
            starts = starts[
                (moments >= max(request.issued_at_utc.timestamp(), request.available_from_utc.timestamp()))
                & (moments < request.deadline_utc.timestamp())
            ]
        starts_for_event.append(starts)

    grouping = _blocks(len(events), block_size, offset)
    all_mask = np.uint64((1 << len(model.tiles)) - 1)
    prefix_completed = np.uint64(0)
    previous = np.full(n + 1, -np.inf, dtype=np.float64)
    previous[0] = 0.0
    back = []
    state_count = 0
    for group in grouping:
        b = len(group)
        states = 1 << b
        state_count += states
        dp = np.full((states, n + 1), -np.inf, dtype=np.float64)
        dp[0] = previous
        pred_node = np.full((states, n + 1), -1, dtype=np.int32)
        pred_arc = np.full((states, n + 1), -2, dtype=np.int32)
        completed_for_mask = np.empty(states, dtype=np.uint64)
        for mask in range(states):
            value = prefix_completed
            for j, event_index in enumerate(group):
                i, _, first = events[event_index]
                if mask & (1 << j) and first:
                    value |= np.uint64(1) << np.uint64(i)
            completed_for_mask[mask] = value
        for mask in range(states):
            completed = completed_for_mask[mask]
            _close_layer(
                dp[mask], model.actionable, all_mask ^ completed, ptr,
                arc_end, arc_tile, completed, pred_node[mask], pred_arc[mask],
            )
            for j, event_index in enumerate(group):
                if mask & (1 << j):
                    continue
                i, _, first = events[event_index]
                if not first and not (completed & (np.uint64(1) << np.uint64(i))):
                    continue
                starts = starts_for_event[event_index]
                starts = starts[np.isfinite(dp[mask, starts])]
                if len(starts) == 0:
                    continue
                ends = starts + int(model.exposure_units[i])
                values = dp[mask, starts] + (scores[i, starts] if first else 0.0)
                target = mask | (1 << j)
                improve = values > dp[target, ends] + 1e-9
                ends = ends[improve]
                starts = starts[improve]
                dp[target, ends] = values[improve]
                pred_node[target, ends] = starts
                pred_arc[target, ends] = -3 - j
        full = states - 1
        if not np.any(np.isfinite(dp[full])):
            raise ValueError(f"block {group} is unreachable")
        previous = dp[full].copy()
        prefix_completed = completed_for_mask[full]
        back.append((group, pred_node, pred_arc))

    end = int(np.argmax(previous))
    predicted = float(previous[end])
    path = []
    mandatory_order = []
    optional_count = 0
    for group, pred_node, pred_arc in reversed(back):
        mask = (1 << len(group)) - 1
        cursor = end
        while True:
            start = int(pred_node[mask, cursor])
            action = int(pred_arc[mask, cursor])
            if start < 0:
                if mask != 0:
                    raise RuntimeError("broken block backtrace")
                end = cursor
                break
            if action >= 0:
                i = int(arc_tile[action])
                path.append((start, i, str(arc_request[action]), "DARK", False))
                optional_count += 1
                cursor = start
            elif action == -1:
                cursor = start
            else:
                j = -3 - action
                if not 0 <= j < len(group) or not (mask & (1 << j)):
                    raise RuntimeError("broken event pointer")
                event_index = group[j]
                i, request_id, _ = events[event_index]
                path.append((start, i, request_id, PROGRAMS[int(programs[i, start])], True))
                mandatory_order.append(event_index)
                cursor = start
                mask ^= 1 << j
    if end != 0:
        raise RuntimeError("block DP did not trace to initial cursor")
    path.reverse()
    mandatory_order.reverse()
    return path, mandatory_order, predicted, optional_count, state_count


def _write(model: PracticeModel, path: Path, actions: list[tuple], mandatory_only: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS, lineterminator="\n")
        writer.writeheader()
        counter = 0
        for start, i, request_id, program, mandatory in actions:
            if mandatory_only and not mandatory:
                continue
            counter += 1
            writer.writerow({
                "decision_id": f"D{counter:06d}",
                "slot_id": model.scorer.slots[start // geometry.POINTS_PER_SLOT].slot_id,
                "action": "observe", "tile_id": model.tile_ids[i],
                "program": program, "request_id": request_id, "reason": "",
            })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/dev-reference"))
    parser.add_argument("--input", type=Path, default=Path("results/practice_core.csv"))
    parser.add_argument("--block-size", type=int, default=3)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--sweeps", type=int, default=1,
                        help="cycle all block offsets this many times, accepting only strict improvements")
    parser.add_argument("--out", type=Path, default=Path("runs/practice_block_dp/decisions.csv"))
    args = parser.parse_args()
    model = PracticeModel(args.scenario, Path("results/practice_reference.csv"))
    scores, programs = score_table(model)
    events = ordered_events(model, args.input)
    if args.sweeps < 1:
        raise ValueError("--sweeps must be positive")
    best = None
    runs = []
    for sweep in range(args.sweeps):
        improved = False
        offsets = range(args.block_size) if args.sweeps > 1 else [args.offset]
        for offset in offsets:
            path, order, predicted, optional_count, states = solve_blocks(
                model, scores, programs, events, args.block_size, offset
            )
            accepted = best is None or predicted > best[2] + 1e-6
            runs.append({"sweep": sweep, "offset": offset,
                         "predicted_without_requests": predicted,
                         "accepted": accepted})
            print(json.dumps(runs[-1], sort_keys=True), file=sys.stderr, flush=True)
            if accepted:
                best = (path, order, predicted, optional_count, states, offset)
                events = [events[k] for k in order]
                improved = True
        if not improved:
            break
    assert best is not None
    path, order, predicted, optional_count, states, last_offset = best
    _write(model, args.out, path)
    core = args.out.parent / "core.csv"
    _write(model, core, path, mandatory_only=True)
    report = model.authoritative_score(args.out)
    (args.out.parent / "score_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "required_events": len(events), "optional_events": optional_count,
        "block_states": states, "block_size": args.block_size,
        "offset": last_offset, "mandatory_order": order,
        "search_runs": runs,
        "predicted_without_requests": predicted,
        "official_total": report["score"]["total"],
        "science": report["score"]["base_science"] + report["score"]["program_bonus"],
        "request_reward": report["score"]["request_reward"],
        "avoidable_wait": report["score"]["penalties"].get("avoidable_wait", 0.0),
        "output": str(args.out), "core": str(core),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
