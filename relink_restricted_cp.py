#!/usr/bin/env python3
"""Recombine public-practice schedules in a restricted exact time-graph CP.

Every observation start in the input schedules is a candidate. Optional shifts
of first completions and actions adjacent to paid waits, per-night top first
starts, and complete legal columns on selected nights expand the catalog. The
model may choose any order, first/revisit identity, and legal request tag. Its
time graph, all-request constraints, completion precedence, and OR waiting
charge are exact for the chosen action columns. Since the column set is
restricted, its CP objective is not an upper bound on the unrestricted
competition problem. Only authoritative replay gives a feasible lower bound.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from ortools.sat.python import cp_model

from challenge.contracts import DECISION_COLUMNS
from challenge.scoring_core import ChallengeScorer, load_decisions
from practice_lns import PracticeModel
from sequence_dp import PROGRAMS, score_table


ROOT = Path(__file__).resolve().parent
SCENARIO = ROOT / "scenarios" / "dev-reference"
SCALE = 1_000_000
POINTS_PER_SLOT = 6


@dataclass(frozen=True)
class Arc:
    start: int
    end: int
    tile: int
    complete: bool
    score: float
    program: str


@dataclass(frozen=True)
class Choice:
    arc: Arc
    kind: str
    tag: str
    var: cp_model.IntVar


def _unit(model: PracticeModel, iso: str) -> int:
    epoch = datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    u = int(np.searchsorted(model.instants, epoch, side="left"))
    if u >= model.n_units or abs(model.instants[u] - epoch) > 1e-6:
        raise ValueError(f"action start outside public 150-second grid: {iso}")
    return u


def build_catalog(
    model: PracticeModel,
    scores: np.ndarray,
    programs: np.ndarray,
    seeds: list[Path],
    shift_units: int,
    wait_neighbor_shift_units: int = 0,
    wait_neighbor_limit: int = 256,
    global_first_tiles: int = 0,
    global_first_per_night: int = 1,
    open_regret_nights: int = 0,
    open_nights: list[str] | None = None,
    priced_first_tiles: int = 0,
    priced_nights_per_tile: int = 0,
    price_file: Path | None = None,
    all_weather_partials: bool = False,
) -> tuple[list[Arc], list[dict], dict]:
    arcs: dict[tuple[int, int, int, bool], Arc] = {}
    donor_actions = []
    first_starts = set()
    donor_scores = {}
    wait_neighbor_priority: dict[tuple[int, int], float] = defaultdict(float)
    seed_first_scores: dict[str, dict[int, float]] = {}
    seed_first_starts: dict[str, dict[int, int]] = {}
    for path in seeds:
        report = model.authoritative_score(path)
        donor_scores[str(path)] = report["score"]["total"]
        seen = set()
        actions = [a for a in report["actions"] if a["action"] == "observe"]
        local_arcs: list[Arc] = []
        first_scores: dict[int, float] = {}
        first_origins: dict[int, int] = {}
        cursor = 0
        completed = 0
        for a in actions:
            if a["outcome"] not in ("completed", "weather_interrupted"):
                raise ValueError(f"seed has penalized observation: {path} {a['outcome']}")
            u = _unit(model, a["start_utc"])
            i = model.tile_index[a["tile_id"]]
            v = u + int(a["elapsed_seconds"]) // 150
            complete = a["outcome"] == "completed"
            if a["elapsed_seconds"] % 150 or v <= u:
                raise AssertionError("donor arc duration is off grid")
            while cursor < u:
                boundary = ((cursor // POINTS_PER_SLOT) + 1) * POINTS_PER_SLOT
                if int(model.actionable[cursor]) & ~completed:
                    # Only actions adjacent to an actually charged wait are
                    # mutated. Each shifted completed arc is validated against
                    # the exact public legal-start/science catalog below.
                    weight = (boundary - cursor) * 0.15
                    if local_arcs and local_arcs[-1].complete:
                        prev = local_arcs[-1]
                        wait_neighbor_priority[(prev.tile, prev.start)] += weight
                    if complete:
                        wait_neighbor_priority[(i, u)] += weight
                cursor = boundary
            if cursor != u:
                raise AssertionError("donor action times overlap")
            if complete:
                if not np.isfinite(scores[i, u]) or v != u + int(model.exposure_units[i]):
                    raise AssertionError("donor completion missing from exact catalog")
                score = float(scores[i, u])
                program = PROGRAMS[int(programs[i, u])]
            else:
                score, program = 0.0, "DARK"
            arc = Arc(u, v, i, complete, score, program)
            arcs[(u, v, i, complete)] = arc
            local_arcs.append(arc)
            first = complete and i not in seen
            if first:
                first_starts.add((i, u))
                seen.add(i)
                completed |= 1 << i
                first_scores[i] = float(score)
                first_origins[i] = u
            donor_actions.append({
                "seed": str(path), "start": u, "end": v, "tile": i,
                "complete": complete, "first": first, "tag": a["request_id"],
            })
            cursor = v
        if len(seen) != len(model.tiles):
            raise ValueError(f"seed does not complete all tiles: {path}")
        seed_first_scores[str(path)] = first_scores
        seed_first_starts[str(path)] = first_origins
        if report["score"]["request_reward"] != 3920.0:
            raise ValueError(f"seed does not earn all 17 feasible requests: {path}")
    if shift_units:
        for i, origin in first_starts:
            for delta in range(-shift_units, shift_units + 1):
                u = origin + delta
                if not (0 <= u < model.n_units) or not np.isfinite(scores[i, u]):
                    continue
                v = u + int(model.exposure_units[i])
                arcs[(u, v, i, True)] = Arc(
                    u, v, i, True, float(scores[i, u]),
                    PROGRAMS[int(programs[i, u])],
                )
    if wait_neighbor_shift_units:
        selected = sorted(
            wait_neighbor_priority.items(), key=lambda item: item[1], reverse=True
        )[:wait_neighbor_limit]
        for (i, origin), _ in selected:
            for delta in range(-wait_neighbor_shift_units, wait_neighbor_shift_units + 1):
                u = origin + delta
                if not (0 <= u < model.n_units) or not np.isfinite(scores[i, u]):
                    continue
                v = u + int(model.exposure_units[i])
                arcs[(u, v, i, True)] = Arc(
                    u, v, i, True, float(scores[i, u]),
                    PROGRAMS[int(programs[i, u])],
                )
    regret = []
    if global_first_tiles or open_regret_nights:
        best_seed = max(seeds, key=lambda p: donor_scores[str(p)])
        achieved = seed_first_scores[str(best_seed)]
        for i in range(len(model.tiles)):
            legal = scores[i, np.isfinite(scores[i])]
            regret.append((float(np.max(legal) - achieved[i]), i))
        regret.sort(reverse=True)
    if global_first_tiles:
        chosen_tiles = [i for _, i in regret[:global_first_tiles]]
        per_night = defaultdict(list)
        for i in chosen_tiles:
            for u in np.flatnonzero(np.isfinite(scores[i])):
                night = model.slots[int(u) // POINTS_PER_SLOT]["night_id"]
                per_night[(i, night)].append(int(u))
        for (i, _night), starts in per_night.items():
            starts.sort(key=lambda u: scores[i, u], reverse=True)
            chosen = starts[:global_first_per_night]
            # A slot-boundary candidate can always be reached by legal waits;
            # a numerically better mid-slot start might lack an incoming arc.
            boundaries = [u for u in starts if u % POINTS_PER_SLOT == 0]
            if boundaries and boundaries[0] not in chosen:
                chosen = chosen[:-1] + [boundaries[0]]
            for u in chosen:
                v = u + int(model.exposure_units[i])
                arcs[(u, v, i, True)] = Arc(
                    u, v, i, True, float(scores[i, u]),
                    PROGRAMS[int(programs[i, u])],
                )
    selected_nights = set(open_nights or [])
    if open_regret_nights:
        for _, i in regret:
            legal = np.flatnonzero(np.isfinite(scores[i]))
            boundary = legal[legal % POINTS_PER_SLOT == 0]
            if len(boundary) == 0:
                continue
            u = int(boundary[np.argmax(scores[i, boundary])])
            selected_nights.add(model.slots[u // POINTS_PER_SLOT]["night_id"])
            if len(selected_nights) >= open_regret_nights:
                break
    if selected_nights:
        night_by_unit = np.asarray([
            model.slots[u // POINTS_PER_SLOT]["night_id"]
            for u in range(model.n_units)
        ])
        open_units = np.flatnonzero(np.isin(night_by_unit, list(selected_nights)))
        before = len(arcs)
        for i in range(len(model.tiles)):
            for u in open_units[np.isfinite(scores[i, open_units])]:
                start = int(u)
                v = start + int(model.exposure_units[i])
                arcs[(start, v, i, True)] = Arc(
                    start, v, i, True, float(scores[i, start]),
                    PROGRAMS[int(programs[i, start])],
                )
        print(json.dumps({
            "phase": "open_nights", "nights": sorted(selected_nights),
            "additional_arcs": len(arcs) - before,
        }), flush=True)
    if priced_first_tiles:
        if price_file is None or priced_nights_per_tile <= 0:
            raise ValueError("priced starts require a price file and positive night cap")
        with np.load(price_file) as price_data:
            prices = np.asarray(price_data["prices_cents"], dtype=np.float64) / 100.0
        if len(prices) != model.n_units:
            raise ValueError("capacity price grid differs from public scenario")
        prefix = np.empty(model.n_units + 1, dtype=np.float64)
        prefix[0] = 0.0
        np.cumsum(prices, out=prefix[1:])
        best_seed = max(seeds, key=lambda p: donor_scores[str(p)])
        before = len(arcs)
        ranked = []
        best_night_arcs = {}
        for i in range(len(model.tiles)):
            legal = np.flatnonzero(np.isfinite(scores[i]))
            d = int(model.exposure_units[i])
            reduced = scores[i, legal] - (prefix[legal + d] - prefix[legal])
            origin = seed_first_starts[str(best_seed)][i]
            incumbent_reduced = (
                seed_first_scores[str(best_seed)][i]
                - (prefix[origin + d] - prefix[origin])
            )
            ranked.append((float(np.max(reduced) - incumbent_reduced), i))
            best_by_night: dict[str, tuple[float, int]] = {}
            for u, value in zip(legal, reduced):
                if int(u) % POINTS_PER_SLOT:
                    continue
                night = model.slots[int(u) // POINTS_PER_SLOT]["night_id"]
                if night not in best_by_night or value > best_by_night[night][0]:
                    best_by_night[night] = (float(value), int(u))
            best_night_arcs[i] = sorted(
                best_by_night.values(), reverse=True
            )[:priced_nights_per_tile]
        ranked.sort(reverse=True)
        selected = ranked[:priced_first_tiles]
        for _, i in selected:
            d = int(model.exposure_units[i])
            for _, u in best_night_arcs[i]:
                arcs[(u, u + d, i, True)] = Arc(
                    u, u + d, i, True, float(scores[i, u]),
                    PROGRAMS[int(programs[i, u])],
                )
        print(json.dumps({
            "phase": "priced_first", "selected_tiles": [
                model.tile_ids[i] for _, i in selected
            ], "capacity_adjusted_regret": [round(g, 6) for g, _ in selected],
            "additional_arcs": len(arcs) - before,
        }), flush=True)
    if all_weather_partials:
        import sequence_active_requests_dp as active

        before = len(arcs)
        data = active._request_data(model, scores)
        for u, v, i in zip(
            data["partial_start"], data["partial_end"], data["partial_tile"]
        ):
            start, end, tile = int(u), int(v), int(i)
            arcs[(start, end, tile, False)] = Arc(
                start, end, tile, False, 0.0, "DARK"
            )
        print(json.dumps({
            "phase": "all_weather_partials", "additional_arcs": len(arcs) - before,
            "enumerated_arcs": len(data["partial_start"]),
        }), flush=True)
    return sorted(arcs.values(), key=lambda a: (a.start, a.end, a.tile)), donor_actions, donor_scores


def solve(args: argparse.Namespace) -> dict:
    started = time.perf_counter()
    model = PracticeModel(SCENARIO, ROOT / "results" / "practice_reference.csv")
    scores, programs = score_table(model)
    arcs, donor_actions, donor_scores = build_catalog(
        model, scores, programs, args.seeds, args.shift_units,
        args.wait_neighbor_shift_units, args.wait_neighbor_limit,
        args.global_first_tiles, args.global_first_per_night,
        args.open_regret_nights, args.open_nights,
        args.priced_first_tiles, args.priced_nights_per_tile,
        args.price_file,
        args.all_weather_partials,
    )
    scorer = model.scorer
    n = model.n_units
    requests = sorted(scorer.requests.values(), key=lambda r: r.request_id)
    latest_release = max(
        r.available_from_utc.timestamp() for r in requests if r.request_id != "RQ0015"
    )
    terminal_min = int(np.searchsorted(model.instants, latest_release, side="left"))

    cp = cp_model.CpModel()
    incoming: dict[int, list] = defaultdict(list)
    outgoing: dict[int, list] = defaultdict(list)
    first: dict[int, list] = defaultdict(list)
    visits: dict[tuple[str, int], list] = defaultdict(list)
    choices: list[Choice] = []
    choice_by_key: dict[tuple[int, int, int, bool, str, str], cp_model.IntVar] = {}
    first_min = [n + 1] * len(model.tiles)
    first_max = [0] * len(model.tiles)
    tag_options = 0
    for arc in arcs:
        instant = model.instants[arc.start]
        tags = [r.request_id for r in requests
                if model.tile_ids[arc.tile] in scorer.request_tiles[r.request_id]
                and r.available_from_utc.timestamp() <= instant < r.deadline_utc.timestamp()]
        options = ([('first', '')] + [('first', tag) for tag in tags]
                   + [('revisit', tag) for tag in tags]) if arc.complete else (
                       [('partial', '')] + [('partial', tag) for tag in tags]
                   )
        for kind, tag in options:
            var = cp.NewBoolVar(f"o_{arc.start}_{arc.end}_{arc.tile}_{kind}_{tag}")
            choice = Choice(arc, kind, tag, var)
            choices.append(choice)
            choice_by_key[(arc.start, arc.end, arc.tile, arc.complete, kind, tag)] = var
            outgoing[arc.start].append(var)
            incoming[arc.end].append(var)
            tag_options += bool(tag)
            if kind == 'first':
                first[arc.tile].append(choice)
                first_min[arc.tile] = min(first_min[arc.tile], arc.end)
                first_max[arc.tile] = max(first_max[arc.tile], arc.end)
            if arc.complete and tag:
                visits[(tag, arc.tile)].append(var)
    for i in range(len(model.tiles)):
        if not first[i]:
            raise RuntimeError(f"tile has no first candidate: {model.tile_ids[i]}")
        cp.Add(sum(c.var for c in first[i]) == 1)
    finish = [cp.NewIntVar(first_min[i], first_max[i], f"finish_{i}")
              for i in range(len(model.tiles))]
    for i in range(len(model.tiles)):
        cp.Add(finish[i] == sum(c.arc.end * c.var for c in first[i]))
    for c in choices:
        if c.kind == 'revisit':
            cp.Add(finish[c.arc.tile] <= c.arc.start).OnlyEnforceIf(c.var)
        elif c.kind == 'partial' and not c.tag:
            cp.Add(finish[c.arc.tile] > c.arc.start).OnlyEnforceIf(c.var)

    for r in requests:
        if r.request_id == 'RQ0015':
            continue
        links = scorer.request_tiles[r.request_id]
        if any(v != 1 for v in links.values()):
            raise ValueError('this restricted CP assumes one visit per link')
        if r.required_tile_count == len(links):
            for tile_id in links:
                cp.Add(sum(visits[(r.request_id, model.tile_index[tile_id])]) >= 1)
        elif r.required_tile_count == 1:
            cp.Add(sum(v for tile_id in links
                       for v in visits[(r.request_id, model.tile_index[tile_id])]) >= 1)
        else:
            raise ValueError('unsupported request threshold in practice instance')

    # A node can be reached by waiting only from a slot boundary or an actual
    # candidate observation end. Sparse wait nodes reduce the full-season CP.
    wait_nodes = set(range(0, n, POINTS_PER_SLOT))
    wait_nodes.update(arc.end for arc in arcs if arc.end < n)
    waits = {}
    for u in sorted(wait_nodes):
        boundary = ((u // POINTS_PER_SLOT) + 1) * POINTS_PER_SLOT
        var = cp.NewBoolVar(f"w_{u}")
        waits[u] = var
        outgoing[u].append(var)
        incoming[boundary].append(var)
    stop_nodes = {u for u in incoming if u >= terminal_min}
    stop_nodes.update(range(((terminal_min + 5) // 6) * 6, n + 1, 6))
    stops = {}
    for u in sorted(stop_nodes):
        var = cp.NewBoolVar(f"stop_{u}")
        stops[u] = var
        outgoing[u].append(var)
    cp.Add(sum(stops.values()) == 1)
    nodes = set(incoming) | set(outgoing) | {0}
    for u in nodes:
        cp.Add(sum(outgoing[u]) - sum(incoming[u]) == int(u == 0))

    charges = {}
    implied = 0
    fixed_charges = 0
    for u, wait in waits.items():
        mask = int(model.actionable[u])
        if mask == 0:
            continue
        relevant = []
        must_charge = False
        while mask:
            bit = mask & -mask
            i = bit.bit_length() - 1
            mask ^= bit
            if first_min[i] > u:
                must_charge = True
                break
            if first_max[i] > u:
                relevant.append(i)
        if must_charge:
            charges[u] = wait
            fixed_charges += 1
        elif relevant:
            charge = cp.NewBoolVar(f"charge_{u}")
            charges[u] = charge
            cp.Add(charge <= wait)
            for i in relevant:
                cp.Add(finish[i] <= u).OnlyEnforceIf([wait, charge.Not()])
                implied += 1
    science = sum(round(c.arc.score * SCALE) * c.var for c in choices if c.kind == 'first')
    wait_cost = sum((POINTS_PER_SLOT - u % POINTS_PER_SLOT) * 150_000 * charge
                    for u, charge in charges.items())
    cp.Maximize(science - wait_cost)

    # The strongest donor is a guaranteed feasible warm start in this column
    # set. Hints can be incomplete; all selected observations and implicit
    # waits are supplied, with charges inferred from donor first completions.
    best_seed = max(args.seeds, key=lambda p: donor_scores[str(p)])
    seed_actions = [a for a in donor_actions if a['seed'] == str(best_seed)]
    completed = set()
    selected = []
    for a in seed_actions:
        kind = 'first' if a['first'] else ('revisit' if a['complete'] else 'partial')
        key = (a['start'], a['end'], a['tile'], a['complete'], kind, a['tag'])
        var = choice_by_key.get(key)
        if var is None:
            raise AssertionError(f"donor action absent from catalog: {key}")
        cp.AddHint(var, 1)
        selected.append(a)
        if a['complete']:
            completed.add(a['tile'])
    cursor = 0
    first_finish = {a['tile']: a['end'] for a in seed_actions if a['first']}
    for a in selected:
        while cursor < a['start']:
            if cursor not in waits:
                raise AssertionError(f"donor needs missing wait at {cursor}")
            cp.AddHint(waits[cursor], 1)
            if cursor in charges and charges[cursor] is not waits[cursor]:
                unfinished = int(model.actionable[cursor]) & ~sum(
                    1 << i for i, end in first_finish.items() if end <= cursor
                )
                cp.AddHint(charges[cursor], int(bool(unfinished)))
            cursor = ((cursor // POINTS_PER_SLOT) + 1) * POINTS_PER_SLOT
        if cursor != a['start']:
            raise AssertionError('donor action overlaps previous action')
        cursor = a['end']
    if cursor in stops:
        cp.AddHint(stops[cursor], 1)

    built = time.perf_counter()
    print(json.dumps({
        'phase': 'built', 'arcs': len(arcs), 'choices': len(choices),
        'wait_edges': len(waits), 'charge_edges': len(charges),
        'wait_implications': implied, 'forced_charge_edges': fixed_charges,
        'nodes': len(nodes), 'variables': len(cp.Proto().variables),
        'constraints': len(cp.Proto().constraints), 'tag_options': tag_options,
        'donor_scores': donor_scores, 'build_seconds': round(built - started, 3),
    }), flush=True)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = args.time_limit
    solver.parameters.num_search_workers = args.workers
    solver.parameters.random_seed = args.seed
    status = solver.Solve(cp)
    summary = {
        'status': solver.StatusName(status),
        'solver_objective_without_requests': (
            solver.ObjectiveValue() / SCALE if status in (cp_model.FEASIBLE, cp_model.OPTIMAL) else None
        ),
        'solver_upper_for_restricted_columns': (
            solver.BestObjectiveBound() / SCALE if status in (cp_model.FEASIBLE, cp_model.OPTIMAL) else None
        ),
        'solve_seconds': round(solver.WallTime(), 3),
        'catalog_arcs': len(arcs), 'catalog_choices': len(choices),
        'wait_implications': implied, 'donor_scores': donor_scores,
    }
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        chosen = sorted((c for c in choices if solver.Value(c.var)),
                        key=lambda c: c.arc.start)
        terminal = next(u for u, var in stops.items() if solver.Value(var))
        rows = [{
            'action': 'observe',
            'slot_id': scorer.slots[c.arc.start // POINTS_PER_SLOT].slot_id,
            'tile_id': model.tile_ids[c.arc.tile],
            'program': c.arc.program,
            'request_id': c.tag,
            'reason': '',
        } for c in chosen]
        last_end = chosen[-1].arc.end if chosen else 0
        if terminal > last_end:
            if terminal % POINTS_PER_SLOT:
                raise AssertionError('terminal after wait must be slot boundary')
            rows.append({
                'action': 'wait', 'slot_id': scorer.slots[terminal // 6 - 1].slot_id,
                'tile_id': '', 'program': '', 'request_id': '', 'reason': '',
            })
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS)
            writer.writeheader()
            for j, row in enumerate(rows, 1):
                writer.writerow({'decision_id': f'D{j:06d}', **row})
        report = model.authoritative_score(args.out)
        (args.out.parent / 'score_report.json').write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n',
            encoding='utf-8',
        )
        if (len(report['completion']['completed_tiles']) != len(model.tiles)
            or report['score']['request_reward'] != 3920.0
            or any(a['penalty'] for a in report['actions'])):
            raise AssertionError('CP path failed authoritative replay validity')
        summary.update({
            'official_score': report['score']['total'],
            'official_science': report['score']['base_science'] + report['score']['program_bonus'],
            'official_wait': report['score']['penalties']['avoidable_wait'],
            'observations': len(chosen), 'output': str(args.out),
        })
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=Path, nargs='+', default=[
        ROOT / 'results' / 'practice_best.csv',
        ROOT / 'runs' / 'global_interval_seed' / 'decisions.csv',
    ])
    parser.add_argument('--shift-units', type=int, default=0)
    parser.add_argument('--wait-neighbor-shift-units', type=int, default=0)
    parser.add_argument('--wait-neighbor-limit', type=int, default=256)
    parser.add_argument('--global-first-tiles', type=int, default=0)
    parser.add_argument('--global-first-per-night', type=int, default=1)
    parser.add_argument('--open-regret-nights', type=int, default=0)
    parser.add_argument('--open-nights', nargs='*', default=[])
    parser.add_argument('--priced-first-tiles', type=int, default=0)
    parser.add_argument('--priced-nights-per-tile', type=int, default=0)
    parser.add_argument('--price-file', type=Path,
                        default=ROOT / 'results' / 'practice_global_interval_prices.npz')
    parser.add_argument('--all-weather-partials', action='store_true')
    parser.add_argument('--time-limit', type=float, default=600)
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--out', type=Path,
                        default=ROOT / 'runs' / 'relink_restricted_cp' / 'decisions.csv')
    args = parser.parse_args()
    solve(args)


if __name__ == '__main__':
    main()
