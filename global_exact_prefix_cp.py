#!/usr/bin/env python3
"""Exact order-free path CP for a public-practice time prefix.

All 150-second starts, successful observations, weather interruptions, waits,
request tags, and early stops are enumerated for the requested prefix.  The
prefix is a deliberately restricted action horizon; an OPTIMAL status is a
proof only for that prefix (and any requested tile subset), never for the
180-night instance.  Observation rewards are rounded to micro-points in the
integer objective.  The authoritative scorer validates the chosen path.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from ortools.sat.python import cp_model

from challenge.contracts import DECISION_COLUMNS
from challenge.scoring_core import ChallengeScorer, load_decisions
from challenge.weather_simulator import weather_quality


PROGRAMS = ("DARK", "BRIGHT", "BACKUP")
UNIT_SECONDS = 150
POINTS_PER_SLOT = 6
SCALE = 1_000_000


@dataclass(frozen=True)
class Arc:
    start: int
    end: int
    tile_id: str
    program: str
    score: float
    outcome: str


@dataclass(frozen=True)
class Choice:
    arc: Arc
    request_id: str
    kind: str
    var: cp_model.IntVar


def _calendar_prefix(scorer: ChallengeScorer, nights: int) -> int:
    if nights <= 0:
        raise ValueError("nights must be positive")
    observed = 0
    previous_night = None
    for index, slot in enumerate(scorer.slots):
        if slot.night_id != previous_night:
            observed += 1
            previous_night = slot.night_id
            if observed > nights:
                return index
    return len(scorer.slots)


def _arc_at(scorer: ChallengeScorer, tile_id: str, start: int, limit: int) -> Arc | None:
    """Reproduce the scorer's legal success/weather interruption from a grid start."""
    tile = scorer.tiles[tile_id]
    start_slot, offset = divmod(start, POINTS_PER_SLOT)
    slot = scorer.slots[start_slot]
    moment = slot.timestamp_utc + timedelta(seconds=offset * UNIT_SECONDS)
    if not scorer._tile_legal(tile, moment):
        return None
    if not scorer.weather.get_effective_conditions(slot.slot_id, tile_id)["is_observable"]:
        return None
    remaining = tile.nominal_exptime_seconds
    current_slot = start_slot
    current_offset = offset * UNIT_SECONDS
    base = 0.0
    matched = {program: 0.0 for program in PROGRAMS}
    while remaining:
        if current_slot >= limit:
            return None
        segment_slot = scorer.slots[current_slot]
        segment_start = segment_slot.timestamp_utc + timedelta(seconds=current_offset)
        if segment_slot.night_id != slot.night_id or not scorer._tile_legal(tile, segment_start):
            return None  # A 100-point geometry interruption is dominated by waiting.
        conditions = scorer.weather.get_effective_conditions(segment_slot.slot_id, tile_id)
        if not conditions["is_observable"]:
            end = current_slot * POINTS_PER_SLOT
            return Arc(start, end, tile_id, "DARK", 0.0, "weather_interrupted")
        seconds = min(remaining, segment_slot.duration_seconds - current_offset)
        midpoint = segment_start + timedelta(seconds=seconds / 2)
        geo = scorer.geometry.get_tile_geometry(tile_id, midpoint)
        atmospheric = weather_quality(conditions, float(geo["airmass"]), scorer.weather.config)
        lunar = float(geo["lunar_quality_factor"])
        part = scorer.tile_values[tile_id] * seconds / tile.nominal_exptime_seconds * atmospheric * lunar
        base += part
        band = scorer._quality_band(atmospheric * lunar)
        matched[band] += part * float(scorer.config["program_bonus"][band])
        remaining -= seconds
        current_slot += 1
        current_offset = 0
    end = start + tile.nominal_exptime_seconds // UNIT_SECONDS
    if end > limit * POINTS_PER_SLOT:
        return None
    program = max(PROGRAMS, key=lambda key: matched[key])
    return Arc(start, end, tile_id, program, base + matched[program], "completed")


def enumerate_arcs(scorer: ChallengeScorer, limit_slots: int, tile_ids: list[str]) -> tuple[list[Arc], dict]:
    horizon = limit_slots * POINTS_PER_SLOT
    arcs = []
    outcomes = defaultdict(int)
    for tile_id in tile_ids:
        for start in range(horizon):
            arc = _arc_at(scorer, tile_id, start, limit_slots)
            if arc is not None:
                if arc.end <= start:
                    raise AssertionError("action edge must advance the cursor")
                arcs.append(arc)
                outcomes[arc.outcome] += 1
    return arcs, dict(outcomes)


def _instant(scorer: ChallengeScorer, unit: int):
    slot_index, offset = divmod(unit, POINTS_PER_SLOT)
    if slot_index == len(scorer.slots):
        return scorer.slots[-1].end_utc
    return scorer.slots[slot_index].timestamp_utc + timedelta(seconds=offset * UNIT_SECONDS)


def _excused_if_missed(scorer: ChallengeScorer, request) -> bool:
    feasible = sum(
        scorer._tile_has_request_opportunity(
            scorer.tiles[tile_id], request.available_from_utc, request.deadline_utc
        )
        for tile_id in scorer.request_tiles[request.request_id]
    )
    return feasible < request.required_tile_count


def build_model(scorer: ChallengeScorer, limit_slots: int, arcs: list[Arc]):
    if scorer.mechanics or scorer.tile_anomalies:
        raise ValueError("the exact-prefix model supports the public practice rules only")
    horizon = limit_slots * POINTS_PER_SLOT
    model = cp_model.CpModel()
    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    first = defaultdict(list)
    first_finishes = defaultdict(list)
    visits = defaultdict(list)
    choices: list[Choice] = []
    wait = {}
    stop = {}
    tag_copies = 0

    for arc in arcs:
        started = _instant(scorer, arc.start)
        tags = [
            req.request_id for req in scorer.requests.values()
            if arc.tile_id in scorer.request_tiles[req.request_id]
            and req.available_from_utc <= started < req.deadline_utc
        ]
        kinds = []
        if arc.outcome == "completed":
            kinds.append(("first", ""))
            kinds.extend(("first", tag) for tag in tags)
            kinds.extend(("revisit", tag) for tag in tags)
        else:
            kinds.append(("partial", ""))
            kinds.extend(("partial", tag) for tag in tags)
        for kind, tag in kinds:
            var = model.NewBoolVar(f"a_{arc.start}_{arc.end}_{arc.tile_id}_{kind}_{tag or 'blank'}")
            outgoing[arc.start].append(var)
            incoming[arc.end].append(var)
            choices.append(Choice(arc, tag, kind, var))
            tag_copies += bool(tag)
            if kind == "first":
                first[arc.tile_id].append(var)
                first_finishes[arc.tile_id].append((arc.end, var))
            if tag and arc.outcome == "completed":
                visits[tag, arc.tile_id].append(var)

    for unit in range(horizon):
        boundary = (unit // POINTS_PER_SLOT + 1) * POINTS_PER_SLOT
        var = model.NewBoolVar(f"w_{unit}")
        wait[unit] = var
        outgoing[unit].append(var)
        incoming[boundary].append(var)
    for unit in range(horizon + 1):
        var = model.NewBoolVar(f"stop_{unit}")
        stop[unit] = var
        outgoing[unit].append(var)
        model.Add(sum(outgoing[unit]) - sum(incoming[unit]) == int(unit == 0))
    model.Add(sum(stop.values()) == 1)

    done = {}
    finish = {}
    for tile_id in scorer.tiles:
        present = model.NewBoolVar(f"done_{tile_id}")
        model.Add(sum(first[tile_id]) == present)
        done[tile_id] = present
        end = model.NewIntVar(0, horizon + 1, f"finish_{tile_id}")
        model.Add(end == (horizon + 1) * (1 - present) + sum(
            unit * var for unit, var in first_finishes[tile_id]
        ))
        finish[tile_id] = end

    for choice in choices:
        if choice.kind == "revisit":
            model.Add(finish[choice.arc.tile_id] <= choice.arc.start).OnlyEnforceIf(choice.var)
        elif choice.kind == "partial" and not choice.request_id:
            model.Add(finish[choice.arc.tile_id] > choice.arc.start).OnlyEnforceIf(choice.var)

    reward_terms = []
    miss_terms = []
    request_count = 0
    for req in scorer.requests.values():
        rid = req.request_id
        satisfied = []
        for tile_id, needed in scorer.request_tiles[rid].items():
            count = sum(visits[rid, tile_id])
            bit = model.NewBoolVar(f"satisfied_{rid}_{tile_id}")
            model.Add(count >= needed).OnlyEnforceIf(bit)
            model.Add(count <= needed - 1).OnlyEnforceIf(bit.Not())
            satisfied.append(bit)
        awarded = model.NewBoolVar(f"awarded_{rid}")
        model.Add(sum(satisfied) >= req.required_tile_count).OnlyEnforceIf(awarded)
        model.Add(sum(satisfied) <= req.required_tile_count - 1).OnlyEnforceIf(awarded.Not())
        published_stops = [stop[u] for u in stop if _instant(scorer, u) >= req.issued_at_utc]
        model.Add(awarded <= sum(published_stops))
        reward_terms.append(round(req.completion_reward * SCALE) * awarded)
        expired_stops = [stop[u] for u in stop if _instant(scorer, u) >= req.deadline_utc]
        if expired_stops and not _excused_if_missed(scorer, req):
            expired = model.NewBoolVar(f"expired_{rid}")
            model.Add(expired == sum(expired_stops))
            missed = model.NewBoolVar(f"missed_{rid}")
            model.Add(missed <= expired)
            model.Add(missed <= 1 - awarded)
            model.Add(missed >= expired - awarded)
            miss_terms.append(round(req.miss_penalty * SCALE) * missed)
        request_count += 1

    regions = sorted({tile.region_id for tile in scorer.tiles.values()})
    quota = int(scorer.config["flexible_quota_per_region"])
    shortfalls = []
    for region in regions:
        flex = [done[t.tile_id] for t in scorer.tiles.values()
                if t.region_id == region and t.scheduling_class == "FLEXIBLE"]
        shortfall = model.NewIntVar(0, quota, f"shortfall_{region}")
        model.Add(shortfall >= quota - sum(flex))
        shortfalls.append(shortfall)

    wait_charges = []
    wait_implications = 0
    for unit, edge in wait.items():
        index, offset = divmod(unit, POINTS_PER_SLOT)
        instant = _instant(scorer, unit)
        actionable = [tile_id for tile_id, tile in scorer.tiles.items()
                      if tile.available_from_utc <= instant < tile.available_until_utc
                      and scorer._can_complete_from(tile, index, offset * UNIT_SECONDS)]
        if not actionable:
            continue
        charge = model.NewBoolVar(f"charge_{unit}")
        model.Add(charge <= edge)
        for tile_id in actionable:
            model.Add(finish[tile_id] <= unit + (horizon + 1) * (1 - edge + charge))
            wait_implications += 1
        wait_charges.append(((POINTS_PER_SLOT - offset) * UNIT_SECONDS, charge))

    required = [done[t.tile_id] for t in scorer.tiles.values() if t.scheduling_class == "REQUIRED"]
    objective = (
        sum(round(c.arc.score * SCALE) * c.var for c in choices if c.kind == "first")
        + round(float(scorer.config["penalties"]["required_miss"]) * SCALE) * sum(required)
        - round(float(scorer.config["penalties"]["flexible_shortfall_per_tile"]) * SCALE) * sum(shortfalls)
        + sum(reward_terms) - sum(miss_terms)
        - sum(seconds * (SCALE // 1000) * charge for seconds, charge in wait_charges)
    )
    model.Maximize(objective)
    return model, {
        "choices": choices, "wait": wait, "stop": stop, "horizon": horizon,
        "first": first, "done": done, "finish": finish,
        "wait_charges": len(wait_charges), "wait_implications": wait_implications,
        "tag_copies": tag_copies, "request_count": request_count,
        "variables": len(model.Proto().variables), "constraints": len(model.Proto().constraints),
    }


def _write_path(path: Path, scorer: ChallengeScorer, solver: cp_model.CpSolver, info: dict) -> int:
    selected = [choice for choice in info["choices"] if solver.Value(choice.var)]
    selected.sort(key=lambda c: c.arc.start)
    rows = []
    for choice in selected:
        slot_id = scorer.slots[choice.arc.start // POINTS_PER_SLOT].slot_id
        rows.append({
            "slot_id": slot_id, "action": "observe", "tile_id": choice.arc.tile_id,
            "program": choice.arc.program, "request_id": choice.request_id, "reason": "",
        })
    terminal = next(unit for unit, var in info["stop"].items() if solver.Value(var))
    last_end = selected[-1].arc.end if selected else 0
    if terminal > last_end:
        if terminal % POINTS_PER_SLOT:
            raise AssertionError("waiting can end only at a slot boundary")
        rows.append({
            "slot_id": scorer.slots[terminal // POINTS_PER_SLOT - 1].slot_id,
            "action": "wait", "tile_id": "", "program": "", "request_id": "", "reason": "",
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS)
        writer.writeheader()
        for number, row in enumerate(rows, 1):
            writer.writerow({"decision_id": f"D{number:06d}", **row})
    return terminal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/dev-reference"))
    parser.add_argument("--nights", type=int, default=1)
    parser.add_argument("--tiles", nargs="*", help="restrict actions to these tiles; default all 64")
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, default=Path("runs/global_exact_prefix/decisions.csv"))
    args = parser.parse_args()
    started = time.perf_counter()
    scorer = ChallengeScorer.from_files(args.scenario)
    limit_slots = _calendar_prefix(scorer, args.nights)
    tile_ids = args.tiles if args.tiles is not None else list(scorer.tiles)
    if len(tile_ids) != len(set(tile_ids)) or any(tile_id not in scorer.tiles for tile_id in tile_ids):
        raise ValueError("tile subset must contain distinct known IDs")
    arcs, outcomes = enumerate_arcs(scorer, limit_slots, tile_ids)
    enumerated = time.perf_counter()
    model, info = build_model(scorer, limit_slots, arcs)
    built = time.perf_counter()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = args.time_limit
    solver.parameters.num_search_workers = args.workers
    status = solver.Solve(model)
    summary = {
        "status": solver.StatusName(status), "nights": args.nights,
        "slots": limit_slots, "grid_nodes": limit_slots * POINTS_PER_SLOT + 1,
        "tile_count": len(tile_ids), "arcs": len(arcs), "arc_outcomes": outcomes,
        "tag_copies": info["tag_copies"], "variables": info["variables"],
        "constraints": info["constraints"], "wait_charges": info["wait_charges"],
        "wait_implications": info["wait_implications"],
        "enumeration_seconds": round(enumerated - started, 3),
        "build_seconds": round(built - enumerated, 3),
        "solve_seconds": round(solver.WallTime(), 3),
    }
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        terminal = _write_path(args.out, scorer, solver, info)
        replay = ChallengeScorer.from_files(args.scenario)
        for decision in load_decisions(args.out, allow_reports=False):
            replay.apply_decision(decision)
        report = replay.finalize("trace_complete")
        required_count = sum(t.scheduling_class == "REQUIRED" for t in scorer.tiles.values())
        modeled = solver.ObjectiveValue() / SCALE - required_count * float(
            scorer.config["penalties"]["required_miss"]
        )
        with args.out.open(newline="", encoding="utf-8") as handle:
            observations = sum(row["action"] == "observe" for row in csv.DictReader(handle))
        summary.update({
            "terminal_unit": terminal, "modeled_score": modeled,
            "authoritative_score": report["score"]["total"],
            "replay_gap": round(modeled - report["score"]["total"], 6),
            "objective_bound_restricted": solver.BestObjectiveBound() / SCALE
            - required_count * float(scorer.config["penalties"]["required_miss"]),
            "out": str(args.out),
            "observations": observations,
        })
        if any(action["outcome"] not in {"completed", "weather_interrupted", "wait"}
               for action in report["actions"]):
            raise AssertionError("CP path used an invalid scorer action")
        if abs(summary["replay_gap"]) > len(tile_ids) * 0.0000006 + 0.000001:
            raise AssertionError("integer objective and replay disagree beyond rounding")
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
