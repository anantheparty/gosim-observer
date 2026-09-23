#!/usr/bin/env python3
"""Optimize a public-weather candidate subset with exact cursor wait charges.

The restricted action graph contains slot-boundary observations selected from
``optimize_public`` candidates, their non-boundary finish cursors, and one wait
edge from every cursor to the next slot. CP-SAT chooses a single source-to-end
path. The wait charge uses the scorer's exact ``_can_complete_from`` predicate
at each wait start and whether each actionable tile has finished by then.

This is an offline dev-reference research solver. Candidate observations are
only a subset: ``exact_option`` uses a conservative midpoint check, requests
are sampled per night, failed exposures are omitted, and the path always runs
through the full season. OPTIMAL would certify only this restricted model.
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
from optimize_public import enumerate_options, reduced_primary
from relabel_requests import request_weights


SCALE = 1_000_000


@dataclass(frozen=True)
class EdgeChoice:
    option: object
    kind: str  # "first" or "revisit"
    request_id: str
    variable: cp_model.IntVar
    end_index: int
    end_offset: int


def _request_reduced(options, request, night_of_slot, per_night):
    """Sample a request's starts without imposing the scorer's absent end cutoff."""
    by_night = defaultdict(list)
    for option in options:
        if request.available_from_utc <= option.start < request.deadline_utc:
            by_night[night_of_slot[option.slot_id]].append(option)
    kept = {}
    for rows in by_night.values():
        for row in sorted(rows, key=lambda x: x.start)[:per_night]:
            kept[row.slot_id] = row
        for row in sorted(rows, key=lambda x: x.start, reverse=True)[:1]:
            kept[row.slot_id] = row
        best = max(rows, key=lambda x: x.score)
        kept[best.slot_id] = best
    return kept.values()


def candidate_subset(scorer, all_options, per_week, per_night):
    nights = list(dict.fromkeys(slot.night_id for slot in scorer.slots))
    night_index = {night: index for index, night in enumerate(nights)}
    night_of_slot = {slot.slot_id: night_index[slot.night_id] for slot in scorer.slots}
    primary = reduced_primary(all_options, night_of_slot, per_week)
    chosen = {
        (tile_id, option.slot_id): option
        for tile_id, options in primary.items()
        for option in options
    }
    for request in scorer.requests.values():
        for tile_id in scorer.request_tiles[request.request_id]:
            for option in _request_reduced(
                all_options[tile_id], request, night_of_slot, per_night
            ):
                chosen[tile_id, option.slot_id] = option
    return sorted(chosen.values(), key=lambda row: (scorer.slot_indices[row.slot_id], row.tile_id))


def build_model(scorer, options, hint_csv=None):
    if scorer.mechanics:
        raise ValueError("this fixed-first-science model is for dev-reference mechanics")
    slots = scorer.slots
    count = len(slots)
    origin = slots[0].timestamp_utc
    horizon = int((slots[-1].end_utc - origin).total_seconds())
    terminal = (count, 0)
    model = cp_model.CpModel()
    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    nodes = {(index, 0) for index in range(count + 1)}
    option_rows = defaultdict(list)
    finish_terms = defaultdict(list)
    first_variables = defaultdict(list)
    visits = defaultdict(list)
    choices: list[EdgeChoice] = []
    choice_lookup = {}
    available_tags = {}
    for option in options:
        start_index = scorer.slot_indices[option.slot_id]
        duration = scorer.tiles[option.tile_id].nominal_exptime_seconds
        end_index = start_index + duration // 900
        end_offset = duration % 900
        if end_index > count or (end_index == count and end_offset):
            raise ValueError("candidate exposure ends outside the calendar")
        start_node = (start_index, 0)
        end_node = (end_index, end_offset)
        nodes.add(end_node)
        option_rows[option.tile_id].append(option)
        tags = [
            request_id for request_id, request in scorer.requests.items()
            if option.tile_id in scorer.request_tiles[request_id]
            and request.issued_at_utc <= option.start
            and request.available_from_utc <= option.start < request.deadline_utc
        ]
        available_tags[option.tile_id, option.slot_id] = tags
        end_seconds = int((option.end - origin).total_seconds())
        for kind, request_id in (
            [("first", "")] + [("first", tag) for tag in tags]
            + [("revisit", tag) for tag in tags]
        ):
            variable = model.NewBoolVar(
                f"obs_{option.tile_id}_{option.slot_id}_{kind}_{request_id or 'blank'}"
            )
            outgoing[start_node].append(variable)
            incoming[end_node].append(variable)
            choice = EdgeChoice(option, kind, request_id, variable, end_index, end_offset)
            choices.append(choice)
            choice_lookup[option.tile_id, option.slot_id, kind, request_id] = variable
            if kind == "first":
                first_variables[option.tile_id].append(variable)
                finish_terms[option.tile_id].append((end_seconds, variable))
            if request_id:
                visits[request_id, option.tile_id].append(variable)

    waiting = {}
    for node in sorted(nodes):
        if node == terminal:
            continue
        index, offset = node
        if index >= count:
            raise ValueError("nonterminal node beyond calendar")
        variable = model.NewBoolVar(f"wait_{index}_{offset}")
        waiting[node] = variable
        outgoing[node].append(variable)
        incoming[index + 1, 0].append(variable)
    for node in sorted(nodes):
        delta = int(node == (0, 0)) - int(node == terminal)
        model.Add(sum(outgoing[node]) - sum(incoming[node]) == delta)

    done = {}
    finish = {}
    for tile_id in scorer.tiles:
        completed = model.NewBoolVar(f"done_{tile_id}")
        model.Add(sum(first_variables[tile_id]) == completed)
        done[tile_id] = completed
        finish_time = model.NewIntVar(0, horizon, f"finish_{tile_id}")
        model.Add(
            finish_time
            == horizon * (1 - completed)
            + sum(end * variable for end, variable in finish_terms[tile_id])
        )
        finish[tile_id] = finish_time
    for choice in choices:
        if choice.kind != "revisit":
            continue
        tile_id = choice.option.tile_id
        start_seconds = int((choice.option.start - origin).total_seconds())
        model.Add(choice.variable <= done[tile_id])
        model.Add(finish[tile_id] <= start_seconds).OnlyEnforceIf(choice.variable)

    request_relevant, request_weight, request_miss = request_weights(
        scorer, slots[-1].end_utc
    )
    completed_request = {}
    for request_id, request in request_relevant.items():
        satisfied_tiles = []
        for tile_id, needed in scorer.request_tiles[request_id].items():
            satisfied = model.NewBoolVar(f"sat_{request_id}_{tile_id}")
            event_vars = visits[request_id, tile_id]
            if len(event_vars) < needed:
                model.Add(satisfied == 0)
            else:
                model.Add(sum(event_vars) >= needed).OnlyEnforceIf(satisfied)
                model.Add(sum(event_vars) <= needed - 1).OnlyEnforceIf(satisfied.Not())
            satisfied_tiles.append(satisfied)
        fulfilled = model.NewBoolVar(f"request_{request_id}")
        model.Add(sum(satisfied_tiles) >= request.required_tile_count).OnlyEnforceIf(fulfilled)
        model.Add(sum(satisfied_tiles) <= request.required_tile_count - 1).OnlyEnforceIf(fulfilled.Not())
        completed_request[request_id] = fulfilled

    regions = sorted({tile.region_id for tile in scorer.tiles.values()})
    quota = int(scorer.config["flexible_quota_per_region"])
    shortfalls = []
    for region in regions:
        variable = model.NewIntVar(0, quota, f"shortfall_{region}")
        flex = [
            done[tile.tile_id] for tile in scorer.tiles.values()
            if tile.region_id == region and tile.scheduling_class == "FLEXIBLE"
        ]
        model.Add(variable >= quota - sum(flex))
        shortfalls.append(variable)

    # Every wait starts at a known cursor, not merely at a night or slot. A
    # charged wait is the AND of taking that edge with the OR of unfinished
    # actionable tiles. With finish_i=season_end for a never-finished tile,
    # finish_i <= t + H*(1-w+z) forces charge z whenever w=1 and finish_i>t.
    wait_charge = {}
    actionability_checks = 0
    wait_constraints = 0
    for node, wait_var in waiting.items():
        index, offset = node
        started = slots[index].timestamp_utc + timedelta(seconds=offset)
        seconds = 900 - offset
        actionable = []
        for tile_id, tile in scorer.tiles.items():
            if not tile.available_from_utc <= started < tile.available_until_utc:
                continue
            actionability_checks += 1
            if scorer._can_complete_from(tile, index, offset):
                actionable.append(tile_id)
        if not actionable:
            continue
        charge = model.NewBoolVar(f"charged_{index}_{offset}")
        wait_charge[node] = (seconds, charge)
        model.Add(charge <= wait_var)
        t_seconds = int((started - origin).total_seconds())
        earliest = {
            tile_id: min((end for end, _ in finish_terms[tile_id]), default=horizon)
            for tile_id in actionable
        }
        if any(first_end > t_seconds for first_end in earliest.values()):
            model.Add(charge == wait_var)
            continue
        for tile_id in actionable:
            model.Add(
                finish[tile_id]
                <= t_seconds + horizon * (1 - wait_var + charge)
            )
            wait_constraints += 1

    req_penalty = float(scorer.config["penalties"]["required_miss"])
    flex_penalty = float(scorer.config["penalties"]["flexible_shortfall_per_tile"])
    objective = (
        sum(round(choice.option.score * SCALE) * choice.variable
            for choice in choices if choice.kind == "first")
        + round(req_penalty * SCALE) * sum(
            done[tile.tile_id] for tile in scorer.tiles.values()
            if tile.scheduling_class == "REQUIRED"
        )
        - round(flex_penalty * SCALE) * sum(shortfalls)
        + sum(round(float(request_weight[rid]) * SCALE) * variable
              for rid, variable in completed_request.items())
        - sum(seconds * (SCALE // 1000) * charge
              for seconds, charge in wait_charge.values())
    )
    model.Maximize(objective)

    hints = 0
    if hint_csv is not None:
        seen = set()
        selected = []
        for row in load_decisions(hint_csv, allow_reports=False):
            if row.action != "observe":
                continue
            kind = "revisit" if row.tile_id in seen else "first"
            seen.add(row.tile_id)
            variable = choice_lookup.get((row.tile_id, row.slot_id, kind, row.request_id))
            if variable is not None:
                choice = next(
                    choice for choice in choices
                    if choice.variable.Index() == variable.Index()
                )
                selected.append(choice)
                hints += 1
        selected_ids = {choice.variable.Index() for choice in selected}
        for choice in choices:
            model.AddHint(choice.variable, int(choice.variable.Index() in selected_ids))
        selected.sort(key=lambda choice: scorer.slot_indices[choice.option.slot_id])
        cursor = (0, 0)
        hinted_waits = set()
        for choice in selected:
            start_node = (scorer.slot_indices[choice.option.slot_id], 0)
            while cursor != start_node:
                if cursor not in waiting or cursor[0] >= start_node[0]:
                    raise ValueError("warm hint is not a chronologically legal path")
                hinted_waits.add(cursor)
                cursor = (cursor[0] + 1, 0)
            cursor = (choice.end_index, choice.end_offset)
        while cursor != terminal:
            if cursor not in waiting:
                raise ValueError("warm hint does not reach the calendar end")
            hinted_waits.add(cursor)
            cursor = (cursor[0] + 1, 0)
        for node, variable in waiting.items():
            model.AddHint(variable, int(node in hinted_waits))
        first_finish = {
            choice.option.tile_id: int((choice.option.end - origin).total_seconds())
            for choice in selected if choice.kind == "first"
        }
        for tile_id, variable in done.items():
            model.AddHint(variable, int(tile_id in first_finish))
            model.AddHint(finish[tile_id], first_finish.get(tile_id, horizon))
    return model, {
        "choices": choices,
        "waiting": waiting,
        "done": done,
        "finish": finish,
        "request_miss": request_miss,
        "horizon": horizon,
        "candidate_options": len(options),
        "actionability_checks": actionability_checks,
        "wait_constraints": wait_constraints,
        "charged_wait_nodes": len(wait_charge),
        "hinted_observations": hints,
    }


def chosen_decisions(scorer, solver, info):
    picked = [choice for choice in info["choices"] if solver.Value(choice.variable)]
    picked.sort(key=lambda choice: (scorer.slot_indices[choice.option.slot_id], choice.option.tile_id))
    result = []
    for choice in picked:
        option = choice.option
        result.append({
            "slot_id": option.slot_id,
            "action": "observe",
            "tile_id": option.tile_id,
            "program": option.program,
            "request_id": choice.request_id,
            "reason": "",
        })
    # Complete the modeled path through the final season slot. The scorer's
    # implicit waits between observations exactly match the graph wait edges.
    if not picked or (picked[-1].end_index, picked[-1].end_offset) != (len(scorer.slots), 0):
        result.append({
            "slot_id": scorer.slots[-1].slot_id,
            "action": "wait",
            "tile_id": "",
            "program": "",
            "request_id": "",
            "reason": "",
        })
    for index, row in enumerate(result, 1):
        row["decision_id"] = f"D{index:06d}"
    return result


def write_decisions(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/dev-reference"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-week", type=int, default=2)
    parser.add_argument("--per-night", type=int, default=1)
    parser.add_argument("--time-limit", type=float, default=1200)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--hint-csv", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    scorer = ChallengeScorer.from_files(args.scenario)
    options_all = enumerate_options(scorer)
    options = candidate_subset(scorer, options_all, args.per_week, args.per_night)
    print(f"candidate enumeration: {len(options)} selected of "
          f"{sum(map(len, options_all.values()))} complete starts in {time.perf_counter()-started:.1f}s", flush=True)
    model, info = build_model(scorer, options, args.hint_csv)
    built = time.perf_counter()
    print(f"model built in {built-started:.1f}s: "
          f"{info['charged_wait_nodes']} charged wait nodes, "
          f"{info['wait_constraints']} wait implications, "
          f"{info['hinted_observations']} hints", flush=True)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = args.time_limit
    solver.parameters.num_search_workers = args.workers
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"no feasible plan: {solver.StatusName(status)}")
    rows = chosen_decisions(scorer, solver, info)
    write_decisions(args.out, rows)
    replay_scorer = ChallengeScorer.from_files(args.scenario)
    for row in load_decisions(args.out, allow_reports=False):
        replay_scorer.apply_decision(row)
    report = replay_scorer.finalize("trace_complete")
    required_count = sum(tile.scheduling_class == "REQUIRED" for tile in scorer.tiles.values())
    constant = (
        required_count * float(scorer.config["penalties"]["required_miss"])
        + sum(float(value) for value in info["request_miss"].values())
    )
    modeled_total = solver.ObjectiveValue() / SCALE - constant
    summary = {
        "status": solver.StatusName(status),
        "score": report["score"]["total"],
        "science": report["score"]["base_science"] + report["score"]["program_bonus"],
        "request_reward": report["score"]["request_reward"],
        "avoidable_wait": report["score"]["penalties"]["avoidable_wait"],
        "modeled_score": modeled_total,
        "model_gap": modeled_total - report["score"]["total"],
        "observations": sum(row["action"] == "observe" for row in rows),
        "candidate_options": info["candidate_options"],
        "objective_bound": solver.BestObjectiveBound() / SCALE - constant,
        "build_seconds": built - started,
        "solve_seconds": solver.WallTime(),
        "total_seconds": time.perf_counter() - started,
    }
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
