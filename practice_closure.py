#!/usr/bin/env python3
"""Solve a night-milestone closure surrogate for public-weather practice.

This is deliberately *not* a GOSIM schedule, a feasible score, or an upper bound
on the scorer's optimum.  Every slot-start wait is treated as mandatory while
each tile may independently collect its best first-observation science on one
night, without occupying telescope time.  A tile chosen on night n is deemed
complete only before night n+1, so every wait in night n sees the same set of
tiles completed on earlier nights.

For a fixed night n and slot s, A[s] is exactly the set of tiles for which the
practice scorer's `_can_complete_from(tile, s, 0)` returns true.  The wait costs
0.001 * slot_seconds iff A[s] contains a tile not completed before night n.
The same (night, A[s]) masks are aggregated into one group reward.  A night's
science unary for a tile is the maximum first-completion science obtainable by
one exposure begun at any 150-second grid cursor that night.  Such a cursor
need not be reachable in a joint schedule.  The final
finite model uses integer micro-points (rounding each night unary once).

Let z[i,n] mean tile i is complete before night n, for n=1..N.  z[i,n] implies
z[i,n+1], and a transition from 0 to 1 is permitted only after a night with a
complete observation candidate.  Science is a telescoping linear function of
these nodes.  Each fixed-wait group has a positive node y[g,n] implying every
z[i,n] for i in its actionable mask.  This is a maximum-weight closure and is
solved exactly by one integer-capacity s-t minimum cut.

Usage:
  .venv-solver/bin/python practice_closure.py --self-test
  .venv-solver/bin/python practice_closure.py --scenario scenarios/dev-reference
  .venv-solver/bin/python practice_closure.py --nights 7 --summary-only
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Sequence

import numpy as np

import bounds_public as geometry_bound
from challenge.scoring_core import ChallengeScorer
from challenge.weather_simulator import weather_quality


POINTS_PER_SLOT = 6
UNIT_SECONDS = 150
SCALE = 1_000_000


def _max_flow_module():
    try:
        from ortools.graph.python import max_flow
    except ImportError as exc:
        raise RuntimeError("OR-Tools is required; run with .venv-solver/bin/python") from exc
    return max_flow


def _observation_score(scorer: ChallengeScorer, tile, start_slot: int,
                       offset_seconds: int, weather_rows: Sequence[dict]) -> float | None:
    """Score a first, fully completed observation using apply_decision's tests.

    This does not modify the scorer.  In particular, actual completion checks
    geometry only at each segment *start*, while segment science uses midpoints.
    """
    first = scorer.slots[start_slot]
    started = first.timestamp_utc + timedelta(seconds=offset_seconds)
    if not weather_rows[start_slot]["is_observable"] or not scorer._tile_legal(tile, started):
        return None
    remaining = tile.nominal_exptime_seconds
    current = start_slot
    offset = offset_seconds
    base_sum = 0.0
    bonus_sums = {program: 0.0 for program in scorer.config["program_bonus"]}
    while remaining > 0:
        if current >= len(scorer.slots):
            return None
        slot = scorer.slots[current]
        moment = slot.timestamp_utc + timedelta(seconds=offset)
        if slot.night_id != first.night_id or not scorer._tile_legal(tile, moment):
            return None
        conditions = weather_rows[current]
        if not conditions["is_observable"]:
            return None
        seconds = min(remaining, slot.duration_seconds - offset)
        midpoint = moment + timedelta(seconds=seconds / 2)
        sample = scorer.geometry.get_tile_geometry(tile.tile_id, midpoint)
        atmospheric = weather_quality(
            conditions, float(sample["airmass"]), scorer.weather.config
        )
        lunar = float(sample["lunar_quality_factor"])
        combined = atmospheric * lunar
        band = scorer._quality_band(combined)  # practice scorer uses efficiency
        base = (
            scorer.tile_values[tile.tile_id]
            * seconds / tile.nominal_exptime_seconds
            * combined
        )
        base_sum += base
        bonus_sums[band] += base * float(scorer.config["program_bonus"][band])
        remaining -= seconds
        current += 1
        offset = 0
    return base_sum + max(bonus_sums.values())


def collect_practice_data(root: Path, limit_nights: int | None = None) -> tuple[list[str], list[str], list[list[int]], list[list[int]], dict[tuple[int, int], int], int, int]:
    """Return nights, tiles, science unaries, winner starts, wait groups.

    All weather data comes from the explicitly public dev-reference practice
    files.  No formal-evaluation scenario files are read by this module.
    """
    if root.name != "dev-reference":
        raise ValueError("this prototype only accepts the public dev-reference scenario")
    scorer = ChallengeScorer.from_files(root)
    if scorer.mechanics:
        raise ValueError("expected pre-anomaly practice scoring")
    night_ids = list(dict.fromkeys(slot.night_id for slot in scorer.slots))
    if limit_nights is not None:
        if not 1 <= limit_nights <= len(night_ids):
            raise ValueError("--nights must lie within the scenario's night count")
        night_ids = night_ids[:limit_nights]
    night_index = {night_id: n for n, night_id in enumerate(night_ids)}
    slot_count = sum(slot.night_id in night_index for slot in scorer.slots)
    slots = scorer.slots[:slot_count]
    tile_ids = sorted(scorer.tiles)
    q = [[0] * len(night_ids) for _ in tile_ids]
    best_start = [[-1] * len(night_ids) for _ in tile_ids]
    actionable_masks = [0] * slot_count
    public_slots = [slot.csv_row() for slot in scorer.slots]
    instants, sidereal, night_end = geometry_bound._time_grid(
        public_slots, float(scorer.geometry.calendar_config["site"]["longitude_deg"])
    )
    latitude = float(scorer.geometry.calendar_config["site"]["latitude_deg"])
    minimum_altitude = float(scorer.geometry.tile_config["geometry"]["minimum_altitude_deg"])
    candidate_count = 0

    for i, tile_id in enumerate(tile_ids):
        tile = scorer.tiles[tile_id]
        tile_row = tile.csv_row()
        mask = geometry_bound._geometry_candidate_mask(
            tile_row, instants, sidereal, night_end, latitude, minimum_altitude
        )
        weather_rows = [
            scorer.weather.get_effective_conditions(slot.slot_id, tile_id)
            for slot in scorer.slots[:slot_count]
        ]
        open_slots = [bool(row["is_observable"]) for row in weather_rows]

        # The scorer's own actionable predicate, sampled at *every* mandatory
        # slot-start wait.  Do not infer this from candidate windows or the
        # science prefilter: actionability checks midpoint geometry too.
        for s in range(slot_count):
            if scorer._can_complete_from(tile, s, 0):
                actionable_masks[s] |= 1 << i

        for point in np.flatnonzero(mask[:slot_count * POINTS_PER_SLOT]):
            point = int(point)
            s, offset_units = divmod(point, POINTS_PER_SLOT)
            segment_count = len(geometry_bound._segments(
                tile.nominal_exptime_seconds, offset_units * UNIT_SECONDS
            ))
            if not all(open_slots[s + j] for j in range(segment_count)):
                continue
            candidate_count += 1
            score = _observation_score(
                scorer, tile, s, offset_units * UNIT_SECONDS, weather_rows
            )
            if score is None:
                continue
            n = night_index[slots[s].night_id]
            units = round(score * SCALE)
            if best_start[i][n] < 0 or units > q[i][n]:
                q[i][n] = units
                best_start[i][n] = point

    # Every nonempty actionable mask incurs 0.9 points per full 900-second
    # mandatory wait, unless all mask members completed before this night.
    wait_per_second = float(scorer.config["penalties"]["avoidable_wait_per_second"])
    groups: dict[tuple[int, int], int] = defaultdict(int)
    charged_wait_units = 0
    for s, mask in enumerate(actionable_masks):
        if mask == 0:
            continue
        n = night_index[slots[s].night_id]
        units = round(slots[s].duration_seconds * wait_per_second * SCALE)
        groups[(n, mask)] += units
        charged_wait_units += units
    return night_ids, tile_ids, q, best_start, dict(groups), charged_wait_units, candidate_count


def evaluate_assignment(q: Sequence[Sequence[int]], groups: dict[tuple[int, int], int],
                        assigned: Sequence[int | None]) -> int:
    science = sum(0 if night is None else q[i][night] for i, night in enumerate(assigned))
    wait = 0
    for (night, mask), units in groups.items():
        completed_before = all(
            assigned[i] is not None and assigned[i] < night
            for i in range(len(assigned)) if mask & (1 << i)
        )
        if not completed_before:
            wait += units
    return science - wait


def solve_closure(q: Sequence[Sequence[int]], feasible: Sequence[Sequence[bool]],
                  groups: dict[tuple[int, int], int]) -> tuple[int, list[int | None], dict]:
    """Exactly maximize the quantized night-milestone model by one min cut."""
    flow_api = _max_flow_module()
    tile_count = len(q)
    if tile_count != len(feasible) or tile_count == 0:
        raise ValueError("q and feasible must have the same nonzero tile count")
    nights = len(q[0])
    if nights == 0 or any(len(row) != nights for row in q) or any(len(row) != nights for row in feasible):
        raise ValueError("inconsistent number of nights")

    # z(i,n), n=1..N, means completed before night n.  Coefficients come
    # from Σ_k q(i,k) [z(i,k+1)-z(i,k)], with z(i,0)=0.
    z_count = tile_count * nights
    group_items = sorted((key, units) for key, units in groups.items() if units > 0)
    weights = [0] * (z_count + len(group_items))
    def z(i: int, n: int) -> int:
        return i * nights + (n - 1)
    for i in range(tile_count):
        for n in range(1, nights + 1):
            weights[z(i, n)] = q[i][n - 1] - (q[i][n] if n < nights else 0)
    for j, (_, units) in enumerate(group_items):
        weights[z_count + j] = units

    source = len(weights)
    sink = source + 1
    positive = sum(max(0, value) for value in weights)
    negative = sum(max(0, -value) for value in weights)
    infinite = positive + negative + 1
    flow = flow_api.SimpleMaxFlow()
    # Register the sink even when all closure weights are nonnegative; without
    # an incident arc OR-Tools returns an empty min-cut side for an isolated sink.
    flow.add_arc_with_capacity(source, sink, 0)
    for node, weight in enumerate(weights):
        if weight > 0:
            flow.add_arc_with_capacity(source, node, weight)
        elif weight < 0:
            flow.add_arc_with_capacity(node, sink, -weight)

    # Monotonic completion; impossible completion nights have no 0->1 edge.
    for i in range(tile_count):
        for n in range(1, nights):
            flow.add_arc_with_capacity(z(i, n), z(i, n + 1), infinite)
        for k in range(nights):
            if feasible[i][k]:
                continue
            if k == 0:
                flow.add_arc_with_capacity(z(i, 1), sink, infinite)
            else:
                flow.add_arc_with_capacity(z(i, k + 1), z(i, k), infinite)

    # A positive group reward can be selected only if every actionable tile
    # was complete before that night's first slot.  Night 0 has no such tiles.
    for j, ((night, mask), _units) in enumerate(group_items):
        node = z_count + j
        if night == 0:
            flow.add_arc_with_capacity(node, sink, infinite)
            continue
        for i in range(tile_count):
            if mask & (1 << i):
                flow.add_arc_with_capacity(node, z(i, night), infinite)

    status = flow.solve(source, sink)
    if status != flow_api.SimpleMaxFlow.OPTIMAL:
        raise RuntimeError(f"max flow failed with status {status}")
    selected = set(flow.get_source_side_min_cut())
    assigned: list[int | None] = []
    for i in range(tile_count):
        completion_night = next(
            (n - 1 for n in range(1, nights + 1) if z(i, n) in selected), None
        )
        assigned.append(completion_night)
    objective = evaluate_assignment(q, groups, assigned)
    closure_value = positive - flow.optimal_flow()
    total_wait = sum(groups.values())
    if objective != closure_value - total_wait:
        raise AssertionError(
            f"closure and direct objective disagree: objective={objective}, "
            f"closure={closure_value}, wait={total_wait}, assigned={assigned}, "
            f"selected={sorted(selected)}, weights={weights}"
        )
    return objective, assigned, {
        "network_nodes": flow.num_nodes(),
        "network_arcs": flow.num_arcs(),
        "min_cut_capacity": flow.optimal_flow(),
        "positive_node_weight": positive,
        "fixed_wait_cost": total_wait,
    }


def self_test(trials: int = 120, seed: int = 1729) -> dict:
    """Compare closure with exhaustive assignments on small random models."""
    from itertools import product

    rng = random.Random(seed)
    for trial in range(trials):
        tiles = rng.randint(1, 4)
        nights = rng.randint(1, 5)
        feasible = [[rng.random() < 0.68 for _ in range(nights)] for _ in range(tiles)]
        q = [[rng.randint(0, 30) if feasible[i][n] else 0 for n in range(nights)]
             for i in range(tiles)]
        groups: dict[tuple[int, int], int] = defaultdict(int)
        for _ in range(rng.randint(0, 15)):
            n = rng.randrange(nights)
            mask = rng.randint(1, (1 << tiles) - 1)
            groups[(n, mask)] += rng.randint(1, 12)
        optimum, assigned, _ = solve_closure(q, feasible, dict(groups))
        choices = [[None] + [n for n in range(nights) if feasible[i][n]]
                   for i in range(tiles)]
        brute = max(evaluate_assignment(q, groups, candidate)
                    for candidate in product(*choices))
        if optimum != brute or evaluate_assignment(q, groups, assigned) != brute:
            raise AssertionError(f"trial {trial}: closure {optimum} != brute {brute}")
    return {"self_test": "passed", "trials": trials, "seed": seed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/dev-reference"))
    parser.add_argument("--nights", type=int, default=None,
                        help="use the first N nights (useful for a quick research run)")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, sort_keys=True))
        return
    nights, tiles, q, starts, groups, fixed_wait, candidates = collect_practice_data(
        args.scenario, args.nights
    )
    feasible = [[point >= 0 for point in row] for row in starts]
    objective, assigned, network = solve_closure(q, feasible, groups)
    science = sum(q[i][n] for i, n in enumerate(assigned) if n is not None)
    allocation = []
    scorer = ChallengeScorer.from_files(args.scenario)
    for i, n in enumerate(assigned):
        if n is None:
            allocation.append({"tile_id": tiles[i], "night_id": None, "science": 0.0})
            continue
        point = starts[i][n]
        slot_index, offset_units = divmod(point, POINTS_PER_SLOT)
        allocation.append({
            "tile_id": tiles[i], "night_id": nights[n],
            "science": q[i][n] / SCALE,
            "best_start_slot_id": scorer.slots[slot_index].slot_id,
            "best_start_offset_seconds": offset_units * UNIT_SECONDS,
        })
    result = {
        "model": "mandatory-slot-waits-night-milestones-no-capacity",
        "warning": "research surrogate only: neither a legal schedule nor an original-problem upper bound",
        "scenario": str(args.scenario),
        "nights": len(nights), "tiles": len(tiles),
        "complete_candidate_starts_evaluated": candidates,
        "actionable_wait_groups": len(groups),
        "selected_tiles": sum(n is not None for n in assigned),
        "science_unary_total": science / SCALE,
        "fixed_wait_if_no_tiles_done": fixed_wait / SCALE,
        "actual_wait_in_surrogate": (science - objective) / SCALE,
        "model_objective": objective / SCALE,
        **network,
    }
    if not args.summary_only:
        result["allocation"] = allocation
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
