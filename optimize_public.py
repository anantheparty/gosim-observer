#!/usr/bin/env python3
"""Solve a reduced public-weather interval scheduling model with CP-SAT.

This is a genuine mixed 0-1 scheduling model. Candidate observations are
fixed legal time intervals. The model chooses one first observation per tile,
non-overlapping request revisits, and a telescope timeline with no collisions.
A nightly indicator approximates the published avoidable-wait charge; the
authoritative scorer evaluates the resulting CSV after solving.

Install the separate offline-only solver with ``pip install ortools``.
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

from challenge.contracts import DECISION_COLUMNS
from challenge.scoring_core import ChallengeScorer
from offline_plan import exact_option, valid_for_request


def enumerate_options(scorer):
    options = defaultdict(list)
    for tile in scorer.tiles.values():
        for index, slot in enumerate(scorer.slots):
            if tile.available_from_utc <= slot.timestamp_utc < tile.available_until_utc:
                option = exact_option(scorer, tile, index)
                if option is not None:
                    options[tile.tile_id].append(option)
    return options


def reduced_primary(options, night_of_slot, per_week):
    result = {}
    for tile_id, rows in options.items():
        groups = defaultdict(list)
        for row in rows:
            groups[night_of_slot[row.slot_id] // 7].append(row)
        kept = {}
        for week_rows in groups.values():
            chosen = sorted(week_rows, key=lambda row: row.score, reverse=True)[:per_week]
            chosen += sorted(week_rows, key=lambda row: row.start)[:1]
            for row in chosen:
                kept[row.slot_id] = row
        result[tile_id] = sorted(kept.values(), key=lambda row: row.start)
    return result


def reduced_request(options, request, night_of_slot, per_night):
    groups = defaultdict(list)
    for row in options:
        if valid_for_request(row, request):
            groups[night_of_slot[row.slot_id]].append(row)
    kept = {}
    for night_rows in groups.values():
        for row in sorted(night_rows, key=lambda row: row.start)[:per_night]:
            kept[row.slot_id] = row
        for row in sorted(night_rows, key=lambda row: row.start, reverse=True)[:1]:
            kept[row.slot_id] = row
    return sorted(kept.values(), key=lambda row: row.start)


def solve(scorer, options, per_week, per_night, time_limit, workers):
    nights = list(dict.fromkeys(slot.night_id for slot in scorer.slots))
    night_index = {name: index for index, name in enumerate(nights)}
    night_of_slot = {slot.slot_id: night_index[slot.night_id] for slot in scorer.slots}
    origin = scorer.slots[0].timestamp_utc
    model = cp_model.CpModel()
    intervals = []
    primary_rows = {}
    primary_vars = {}
    primary_finish = {}
    completion = {}

    def interval(row, label, variable):
        start = int((row.start - origin).total_seconds())
        duration = int((row.end - row.start).total_seconds())
        intervals.append(model.NewOptionalFixedSizeIntervalVar(start, duration, variable, label))

    reduced = reduced_primary(options, night_of_slot, per_week)
    for tile_id in scorer.tiles:
        rows = reduced.get(tile_id, [])
        variables = []
        for index, row in enumerate(rows):
            var = model.NewBoolVar(f"p_{tile_id}_{index}")
            interval(row, f"P_{tile_id}_{index}", var)
            variables.append(var)
            primary_rows[tile_id, index] = row
            primary_vars[tile_id, index] = var
        done = model.NewBoolVar(f"done_{tile_id}")
        model.Add(sum(variables) == done)
        completion[tile_id] = done
        finish = model.NewIntVar(0, int((scorer.slots[-1].timestamp_utc - origin).total_seconds()) + 86400,
                                 f"finish_{tile_id}")
        model.Add(finish == sum(int((row.end - origin).total_seconds()) * variables[index]
                                for index, row in enumerate(rows)))
        primary_finish[tile_id] = finish

    request_rows = {}
    request_vars = {}
    active_requests = []
    request_complete = {}
    for request in scorer.requests.values():
        eligible = {}
        for tile_id in scorer.request_tiles[request.request_id]:
            rows = reduced_request(options[tile_id], request, night_of_slot, per_night)
            if rows:
                eligible[tile_id] = rows
        if len(eligible) < request.required_tile_count:
            continue  # Authoritative scorer excuses an impossible request.
        active_requests.append(request)
        fulfilled = model.NewBoolVar(f"fulfilled_{request.request_id}")
        request_complete[request.request_id] = fulfilled
        satisfied = []
        for tile_id, rows in eligible.items():
            choose_tile = model.NewBoolVar(f"s_{request.request_id}_{tile_id}")
            model.Add(choose_tile <= completion[tile_id])
            satisfied.append(choose_tile)
            visits = []
            for index, row in enumerate(rows):
                var = model.NewBoolVar(f"r_{request.request_id}_{tile_id}_{index}")
                interval(row, f"R_{request.request_id}_{tile_id}_{index}", var)
                model.Add(primary_finish[tile_id] <= int((row.start - origin).total_seconds())).OnlyEnforceIf(var)
                visits.append(var)
                request_rows[request.request_id, tile_id, index] = row
                request_vars[request.request_id, tile_id, index] = var
            model.Add(sum(visits) == choose_tile)
        model.Add(sum(satisfied) == request.required_tile_count * fulfilled)

    model.AddNoOverlap(intervals)

    # Published penalty is 0.001 per avoidable second. This nightly surrogate
    # can overestimate or underestimate replay cost: actionability may last
    # only part of a night, and a tile finished late can trigger earlier waits.
    active_by_night = defaultdict(set)
    slots_by_night = defaultdict(dict)
    for tile_id, rows in options.items():
        for row in rows:
            night = night_of_slot[row.slot_id]
            active_by_night[night].add(tile_id)
            slots_by_night[night][row.slot_id] = scorer.slots[scorer.slot_indices[row.slot_id]].duration_seconds
    wait_terms = []
    for night, active_tiles in active_by_night.items():
        wait = model.NewBoolVar(f"wait_night_{night}")
        for tile_id in active_tiles:
            later = [primary_vars[tile_id, index]
                     for index, row in enumerate(reduced.get(tile_id, []))
                     if night_of_slot[row.slot_id] > night]
            model.Add(wait >= 1 - completion[tile_id] + sum(later))
        wait_terms.append((sum(slots_by_night[night].values()), wait))

    required_reward = int(float(scorer.config["penalties"]["required_miss"]) * 1000)
    flexible_penalty = int(float(scorer.config["penalties"]["flexible_shortfall_per_tile"]) * 1000)
    quota = int(scorer.config["flexible_quota_per_region"])
    flex_terms = []
    regions = sorted({tile.region_id for tile in scorer.tiles.values()})
    for region in regions:
        flex_tiles = [tile.tile_id for tile in scorer.tiles.values()
                      if tile.region_id == region and tile.scheduling_class == "FLEXIBLE"]
        shortfall = model.NewIntVar(0, quota, f"shortfall_{region}")
        model.Add(shortfall >= quota - sum(completion[tile_id] for tile_id in flex_tiles))
        flex_terms.append(shortfall)
    request_bonus = sum(
        round((float(request.completion_reward) + float(request.miss_penalty))
              * 1000) * request_complete[request.request_id]
        for request in active_requests
    )
    model.Maximize(
        sum(round(row.score * 1000) * primary_vars[tile_id, index]
            for (tile_id, index), row in primary_rows.items())
        + required_reward * sum(completion[tile.tile_id] for tile in scorer.tiles.values()
                                if tile.scheduling_class == "REQUIRED")
        - flexible_penalty * sum(flex_terms)
        + request_bonus
        - sum(seconds * var for seconds, var in wait_terms)
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, {"status": solver.StatusName(status), "primary_candidates": len(primary_rows),
                      "request_candidates": len(request_rows)}
    chosen = [row for key, row in primary_rows.items() if solver.Value(primary_vars[key])]
    chosen += [row.__class__(row.tile_id, row.slot_id, row.start, row.end, row.score,
                             row.program, request_id=key[0])
               for key, row in request_rows.items() if solver.Value(request_vars[key])]
    chosen.sort(key=lambda row: row.start)
    info = {"status": solver.StatusName(status), "objective": solver.ObjectiveValue() / 1000,
            "bound": solver.BestObjectiveBound() / 1000,
            "primary_candidates": len(primary_rows), "request_candidates": len(request_rows),
            "requests_enforced": len(active_requests), "observations": len(chosen)}
    return chosen, info


def write_decisions(path, plan):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS)
        writer.writeheader()
        for index, row in enumerate(plan, 1):
            writer.writerow({"decision_id": f"D{index:06d}", "slot_id": row.slot_id,
                             "action": "observe", "tile_id": row.tile_id,
                             "program": row.program, "request_id": row.request_id,
                             "reason": "integer interval schedule"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--per-week", type=int, default=2)
    parser.add_argument("--per-night", type=int, default=1)
    parser.add_argument("--time-limit", type=float, default=120)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    scorer = ChallengeScorer.from_files(args.scenario)
    options = enumerate_options(scorer)
    plan, info = solve(scorer, options, args.per_week, args.per_night, args.time_limit, args.workers)
    print(info, flush=True)
    if plan is None:
        raise SystemExit(2)
    write_decisions(args.out, plan)


if __name__ == "__main__":
    main()
