#!/usr/bin/env python3
"""Schedule the public-practice closure allocation by exact fixed-order timing DP.

The input is a *surrogate* maximum-closure solution, not a feasible schedule or
an upper bound for the original contest problem.  Its chosen starts provide
ordering priorities only: timing DP may move observations to any legal
150-second start.  The 28 request-tagged revisits are taken, in their original
relative order, from the public practice reference.  No visits are invented.

This two-stage construction is deterministic and is not a global optimization
algorithm.  The resulting decisions are always checked with the authoritative
public-practice scorer.  If the fixed order is infeasible, an exact reachable
cursor calculation identifies the first impossible event.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import bounds_public as geometry
from challenge.contracts import DECISION_COLUMNS
from challenge.scoring_core import load_decisions
from practice_lns import PracticeModel
from sequence_dp import PROGRAMS, score_table, solve_order


@dataclass(frozen=True)
class OrderedEvent:
    tile_index: int
    request_id: str
    first: bool
    anchor: int
    priority: int
    reference_index: int | None

    def dp_tuple(self) -> tuple[int, str, bool]:
        return (self.tile_index, self.request_id, self.first)


def construct_events(
    model: PracticeModel, closure_path: Path, reference_path: Path,
) -> tuple[list[OrderedEvent], dict]:
    """Merge closure first visits and globally ordered reference requests.

    The only precedence arcs are first(tile) -> each request visit of tile and
    request(j) -> request(j+1).  Available nodes are selected by their anchor
    time.  A first visit that has an earlier request is promoted to that
    request's reference time minus its exposure, so precedence can be met.
    """
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    if closure.get("model") != "mandatory-slot-waits-night-milestones-no-capacity":
        raise ValueError("unexpected closure model")
    if closure.get("tiles") != len(model.tiles) or closure.get("selected_tiles") != len(model.tiles):
        raise ValueError("closure allocation must contain all practice tiles")
    allocation = closure.get("allocation")
    if not isinstance(allocation, list) or len(allocation) != len(model.tiles):
        raise ValueError("closure result needs one allocation per practice tile")

    first_anchor: dict[int, int] = {}
    for row in allocation:
        tile_id = row["tile_id"]
        if tile_id not in model.tile_index:
            raise ValueError(f"unknown closure tile {tile_id}")
        i = model.tile_index[tile_id]
        if i in first_anchor:
            raise ValueError(f"duplicate closure tile {tile_id}")
        slot_id = row.get("best_start_slot_id")
        if slot_id not in model.scorer.slot_indices:
            raise ValueError(f"no closure start for {tile_id}")
        slot = model.scorer.slots[model.scorer.slot_indices[slot_id]]
        if slot.night_id != row["night_id"]:
            raise ValueError(f"closure night/start mismatch for {tile_id}")
        offset = int(row["best_start_offset_seconds"])
        if offset not in range(0, slot.duration_seconds, geometry.UNIT_SECONDS):
            raise ValueError(f"off-grid closure start for {tile_id}")
        first_anchor[i] = (
            model.scorer.slot_indices[slot_id] * geometry.POINTS_PER_SLOT
            + offset // geometry.UNIT_SECONDS
        )

    reference = load_decisions(reference_path, allow_reports=False)
    if any(row.action != "observe" for row in reference):
        raise ValueError("reference must consist solely of observations")
    seen_first: set[int] = set()
    requests: list[tuple[int, str, int, int]] = []
    earliest_request_for_tile: dict[int, int] = {}
    for row_index, row in enumerate(reference):
        if row.tile_id not in model.tile_index:
            raise ValueError(f"unknown reference tile {row.tile_id}")
        i = model.tile_index[row.tile_id]
        if i not in seen_first:
            if row.request_id:
                raise ValueError(f"request visit precedes first visit for {row.tile_id}")
            seen_first.add(i)
        else:
            if not row.request_id:
                raise ValueError("this experiment accepts request-tagged revisits only")
            if row.request_id not in model.scorer.requests:
                raise ValueError(f"unknown request {row.request_id}")
            anchor = model.scorer.slot_indices[row.slot_id] * geometry.POINTS_PER_SLOT
            requests.append((i, row.request_id, anchor, row_index))
            earliest_request_for_tile[i] = min(
                earliest_request_for_tile.get(i, anchor), anchor
            )
    if seen_first != set(range(len(model.tiles))):
        raise ValueError("reference must have one first visit per tile")

    # First visits are initially available.  Each request waits for its own
    # first visit and for the preceding reference request, globally.
    first_nodes = len(model.tiles)
    nodes: list[OrderedEvent] = []
    for i in range(first_nodes):
        anchor = first_anchor[i]
        urgency = earliest_request_for_tile.get(i)
        priority = min(anchor, urgency - int(model.exposure_units[i])) if urgency is not None else anchor
        nodes.append(OrderedEvent(i, "", True, anchor, priority, None))
    for i, request_id, anchor, row_index in requests:
        nodes.append(OrderedEvent(i, request_id, False, anchor, anchor, row_index))

    successors: list[list[int]] = [[] for _ in nodes]
    indegree = [0] * len(nodes)
    for j, (i, _request_id, _anchor, _row_index) in enumerate(requests):
        request_node = first_nodes + j
        successors[i].append(request_node)
        indegree[request_node] += 1
        if j:
            successors[request_node - 1].append(request_node)
            indegree[request_node] += 1
    queue: list[tuple[int, int]] = []
    for node_index, degree in enumerate(indegree):
        if degree == 0:
            event = nodes[node_index]
            heapq.heappush(queue, (event.priority, node_index))
    order: list[OrderedEvent] = []
    while queue:
        _, node_index = heapq.heappop(queue)
        order.append(nodes[node_index])
        for successor in successors[node_index]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                event = nodes[successor]
                heapq.heappush(queue, (event.priority, successor))
    if len(order) != len(nodes):
        raise AssertionError("precedence graph contains a cycle")
    if sum(event.first for event in order) != first_nodes:
        raise AssertionError("lost a first visit")
    assert [event.reference_index for event in order if not event.first] == [
        row_index for _, _, _, row_index in requests
    ]
    seen: set[int] = set()
    for event in order:
        if event.first:
            if event.tile_index in seen:
                raise AssertionError("duplicated first visit")
            seen.add(event.tile_index)
        elif event.tile_index not in seen:
            raise AssertionError("request precedes its first visit")
    return order, {
        "closure_model_objective": closure["model_objective"],
        "closure_warning": closure["warning"],
        "reference_observations": len(reference),
        "first_visits": first_nodes,
        "request_visits": len(requests),
        "promoted_first_visits": sum(
            e.first and e.priority < e.anchor for e in order
        ),
    }


def first_infeasible_event(
    model: PracticeModel, scores: np.ndarray, order: list[OrderedEvent]
) -> dict | None:
    """Exact feasibility of each fixed-order prefix, ignoring scores only."""
    n = model.n_units
    points = geometry.POINTS_PER_SLOT
    reachable = np.zeros(n + 1, dtype=np.bool_)
    reachable[0] = True
    candidates = [np.flatnonzero(np.isfinite(scores[i])) for i in range(len(model.tiles))]
    for position, event in enumerate(order, 1):
        # Wait edges have no feasibility dependence on completed tiles.  A
        # legal wait from any offset in a slot reaches its next boundary.
        for slot_index in range(len(model.slots)):
            lo = slot_index * points
            hi = lo + points
            if reachable[lo:hi].any():
                reachable[hi] = True
        possible = candidates[event.tile_index]
        request_window = None
        if event.request_id:
            request = model.scorer.requests[event.request_id]
            issued = request.issued_at_utc.timestamp()
            available = request.available_from_utc.timestamp()
            deadline = request.deadline_utc.timestamp()
            moments = model.instants[possible]
            possible = possible[
                (moments >= issued) & (moments >= available) & (moments < deadline)
            ]
            request_window = {
                "issued_at_utc": request.issued_at_utc.isoformat(),
                "available_from_utc": request.available_from_utc.isoformat(),
                "deadline_utc": request.deadline_utc.isoformat(),
            }
        feasible = possible[reachable[possible]]
        if len(feasible) == 0:
            front = np.flatnonzero(reachable)
            return {
                "position_1_based": position,
                "tile_id": model.tile_ids[event.tile_index],
                "request_id": event.request_id,
                "first_visit": event.first,
                "candidate_starts_in_request_window": int(len(possible)),
                "earliest_candidate_unit": int(possible[0]) if len(possible) else None,
                "latest_candidate_unit": int(possible[-1]) if len(possible) else None,
                "earliest_reachable_cursor_unit": int(front[0]) if len(front) else None,
                "latest_reachable_cursor_unit": int(front[-1]) if len(front) else None,
                "request_window": request_window,
                "proof": "No legal start lies in the exact reachable cursor set after this prefix and any number of legal waits.",
            }
        ends = feasible + int(model.exposure_units[event.tile_index])
        reachable = np.zeros(n + 1, dtype=np.bool_)
        reachable[ends] = True
    return None


def write_order(path: Path, model: PracticeModel, order: list[OrderedEvent]) -> None:
    rows = []
    for position, event in enumerate(order, 1):
        rows.append({
            "position": position,
            "tile_id": model.tile_ids[event.tile_index],
            "request_id": event.request_id,
            "first_visit": event.first,
            "closure_anchor_unit": event.anchor if event.first else None,
            "reference_anchor_unit": event.anchor if not event.first else None,
            "priority_unit": event.priority,
            "reference_index": event.reference_index,
        })
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/dev-reference"))
    parser.add_argument("--closure", type=Path, default=Path("runs/practice_closure_result.json"))
    parser.add_argument("--reference", type=Path, default=Path("results/practice_reference.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("runs/practice_closure_schedule"))
    args = parser.parse_args()
    if args.scenario.name != "dev-reference":
        raise ValueError("only the public dev-reference practice scenario is supported")
    model = PracticeModel(args.scenario, args.reference)
    order, metadata = construct_events(model, args.closure, args.reference)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_order(args.out_dir / "order.json", model, order)
    scores, programs = score_table(model)
    try:
        path, predicted_without_requests = solve_order(
            model, scores, programs, [event.dp_tuple() for event in order]
        )
    except ValueError as exc:
        failure = first_infeasible_event(model, scores, order)
        summary = {
            "status": "fixed_order_infeasible",
            "reason": str(exc),
            "first_failure": failure,
            "systematic_repair": "If the event has legal candidate starts but none reachable, move independent first visits out of its prefix while preserving the global request chain and all first-before-request arcs, then rerun exact timing DP. Zero legal candidates in its request window cannot be repaired by reordering.",
            **metadata,
        }
        (args.out_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return

    decisions_path = args.out_dir / "decisions.csv"
    with decisions_path.open("w", newline="", encoding="utf-8") as handle:
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
    report = model.authoritative_score(decisions_path)
    if any(action["outcome"] != "completed" for action in report["actions"]):
        raise RuntimeError("authoritative practice replay did not complete every observation")
    if set(report["completion"]["completed_tiles"]) != set(model.tile_ids):
        raise RuntimeError("authoritative practice replay did not complete every tile")
    penalties = report["score"]["penalties"]
    modeled_total = (
        predicted_without_requests
        + report["score"]["request_reward"]
        + report["score"]["coverage_bonus"]
        + report["score"]["report_reward"]
        - sum(value for key, value in penalties.items() if key != "avoidable_wait")
    )
    if abs(modeled_total - report["score"]["total"]) > 0.0001:
        raise RuntimeError("timing DP and authoritative practice replay disagree")
    (args.out_dir / "score_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "status": "scored",
        "order_is_globally_optimal": False,
        "timing_is_optimal_given_order": True,
        "surrogate_is_original_upper_bound": False,
        "observations": len(path),
        "full_grid_complete_candidates": int(np.isfinite(scores).sum()),
        "predicted_without_request_reward": predicted_without_requests,
        "official_score": report["score"]["total"],
        "science": round(report["score"]["base_science"] + report["score"]["program_bonus"], 6),
        "request_reward": report["score"]["request_reward"],
        "avoidable_wait_penalty": report["score"]["penalties"].get("avoidable_wait", 0.0),
        "all_observations_completed": True,
        "all_tiles_completed": True,
        "timing_replay_discrepancy": round(modeled_total - report["score"]["total"], 9),
        **metadata,
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
