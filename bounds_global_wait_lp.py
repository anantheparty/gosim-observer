#!/usr/bin/env python3
"""Diagnostic all-action interval LP with unavoidable full-slot waiting.

This is a conditional upper-bound relaxation for public dev-reference paths
earning all 17 feasible requests. It adds exact scorer-actionable boundaries,
first-completion prefixes, legal weather-interrupted occupancy, and a lower
bound on unavoidable 900-second wait charges. An optional rounded all-column
dual calculation can certify a strict upper bound after an optimal solve.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from ortools.linear_solver import linear_solver_pb2, pywraplp

from bounds_practice_resource import all_arcs
from bounds_practice_projection import _partial_weather_arcs
from challenge.scoring_core import ChallengeScorer


ROOT = Path(__file__).resolve().parent
PRACTICE = ROOT / "scenarios" / "dev-reference"
SCALE = 1_000_000  # integer units per cent


def certify_integer_dual(solver, dual_path: Path) -> dict:
    """Recompute a generic weak-duality bound over every exported LP column.

    All objective, constraint, and bound coefficients in this model must be
    exact integers. Rounded row duals are arbitrary sign-correct multipliers;
    the residual of every bounded variable is maximized explicitly. This
    avoids relying on GLOP's floating objective as the final certificate.
    """
    proto = linear_solver_pb2.MPModelProto()
    solver.ExportModelToProto(proto)
    if not proto.maximize:
        raise AssertionError("certificate expects a maximization model")
    nvar = len(proto.variable)
    nrow = len(proto.constraint)
    if nrow != solver.NumConstraints() or nvar != solver.NumVariables():
        raise AssertionError("exported model dimensions changed")
    coeff = np.array(
        [v.objective_coefficient for v in proto.variable], dtype=np.float64
    )
    if not np.allclose(coeff, np.rint(coeff), atol=1e-9, rtol=0):
        raise AssertionError("noninteger objective coefficient")
    residual = np.rint(coeff).astype(np.int64) * SCALE
    bound_constant = int(round(proto.objective_offset * SCALE))
    dual = np.empty(nrow, dtype=np.int64)
    for k, (row, constraint) in enumerate(zip(proto.constraint, solver.constraints())):
        lower, upper = row.lower_bound, row.upper_bound
        has_lower = math.isfinite(lower) and abs(lower) < 1e20
        has_upper = math.isfinite(upper) and abs(upper) < 1e20
        if has_lower and lower != round(lower):
            raise AssertionError("noninteger lower row bound")
        if has_upper and upper != round(upper):
            raise AssertionError("noninteger upper row bound")
        lam = round(constraint.dual_value() * SCALE)
        if not has_lower and lam < 0:
            lam = 0
        if not has_upper and lam > 0:
            lam = 0
        if not has_lower and not has_upper:
            lam = 0
        dual[k] = lam
        if lam > 0:
            bound_constant += lam * round(upper)
        elif lam < 0:
            bound_constant += lam * round(lower)
        if lam:
            indices = np.fromiter(row.var_index, dtype=np.int32,
                                  count=len(row.var_index))
            values = np.fromiter(row.coefficient, dtype=np.float64,
                                 count=len(row.coefficient))
            if not np.allclose(values, np.rint(values), atol=1e-9, rtol=0):
                raise AssertionError("noninteger matrix coefficient")
            np.add.at(residual, indices, -np.rint(values).astype(np.int64) * lam)
    lower = np.array([v.lower_bound for v in proto.variable], dtype=np.float64)
    upper = np.array([v.upper_bound for v in proto.variable], dtype=np.float64)
    if (not np.all(np.isfinite(lower)) or not np.all(np.isfinite(upper))
            or not np.allclose(lower, np.rint(lower), atol=1e-9, rtol=0)
            or not np.allclose(upper, np.rint(upper), atol=1e-9, rtol=0)):
        raise AssertionError("noninteger or unbounded variable domain")
    low = np.rint(lower).astype(np.int64)
    high = np.rint(upper).astype(np.int64)
    variable_residual = sum(
        max(int(r) * int(l), int(r) * int(h))
        for r, l, h in zip(residual, low, high)
    )
    bound = bound_constant + variable_residual
    dual_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dual_path, row_dual_microcents=dual)
    return {
        "microcents_per_cent": SCALE,
        "row_count": nrow,
        "column_count": nvar,
        "constant_microcents": bound_constant,
        "variable_residual_microcents": variable_residual,
        "upper_microcents": bound,
        "upper_cents_ceiling": (bound + SCALE - 1) // SCALE,
        "upper_points_ceiling": ((bound + SCALE - 1) // SCALE) / 100.0,
        "row_dual_file": str(dual_path),
        "row_dual_sha256": hashlib.sha256(dual_path.read_bytes()).hexdigest(),
        "model_proto_sha256": hashlib.sha256(proto.SerializeToString()).hexdigest(),
        "nonzero_row_duals": int(np.count_nonzero(dual)),
        "positive_variable_residuals": int(np.count_nonzero(residual > 0)),
    }


def wait_actionability(scorer: ChallengeScorer, instants: np.ndarray,
                       starts: list[np.ndarray], latest_release: float,
                       boundary_stride: int):
    """Exact scorer predicate at every pre-release 900-second boundary.

    Full-scan eligibility also independently checks that the successful-arc
    catalog did not omit a scorer-actionable first observation at a boundary.
    """
    boundaries = np.flatnonzero(
        (np.arange(len(instants)) % (6 * boundary_stride) == 0)
        & (instants < latest_release)
    ).astype(np.int32)
    tile_ids = list(scorer.tiles)
    if len(tile_ids) != len(starts):
        raise AssertionError("tile ordering/count changed")
    by_tile = []
    by_boundary: dict[int, list[int]] = defaultdict(list)
    omitted = 0
    examined = 0
    for i, tile_id in enumerate(tile_ids):
        tile = scorer.tiles[tile_id]
        catalog = set(map(int, starts[i][starts[i] % 6 == 0]))
        active = []
        for b in boundaries:
            actionable = scorer._can_complete_from(tile, int(b) // 6, 0)
            examined += 1
            if actionable:
                if int(b) not in catalog:
                    omitted += 1
                active.append(int(b))
                by_boundary[int(b)].append(i)
        by_tile.append(np.asarray(active, dtype=np.int32))
    if omitted:
        raise AssertionError(f"{omitted} scorer-actionable arcs absent from LP")
    return boundaries, by_tile, by_boundary, {
        "examined_tile_boundary_pairs": examined,
        "actionable_tile_boundary_pairs": sum(len(a) for a in by_tile),
        "omitted_scorer_actionable_first_arcs": omitted,
    }


def request_groups(scorer: ChallengeScorer, instants: np.ndarray,
                   starts: list[np.ndarray]):
    """Map each legal (successful arc, request label) to one award constraint."""
    tile_ids = list(scorer.tiles)
    tile_index = {tile_id: i for i, tile_id in enumerate(tile_ids)}
    offsets = np.cumsum([0] + [len(a) for a in starts], dtype=np.int64)
    group_members: dict[int, list[int]] = defaultdict(list)
    group_names: list[str] = []
    groups_by_request: list[list[int]] = []
    first_by_tile: list[list[tuple[int, float]]] = [[] for _ in tile_ids]
    requests = sorted(scorer.requests.values(), key=lambda r: r.request_id)
    for request in requests:
        links = scorer.request_tiles[request.request_id]
        if not all(m == 1 for m in links.values()):
            raise ValueError("this practice LP assumes one visit per request/tile")
        if request.required_tile_count == len(links):
            tilesets = [[tile_id] for tile_id in sorted(links)]
        elif request.required_tile_count == 1:
            tilesets = [sorted(links)]
        else:
            raise ValueError("unsupported request choice cardinality")
        g_for_r: list[int] = []
        for tileset in tilesets:
            g = len(group_names)
            g_for_r.append(g)
            group_names.append(request.request_id + ":" + "+".join(tileset))
            for tile_id in tileset:
                i = tile_index[tile_id]
                first_by_tile[i].append((g, request.deadline_utc.timestamp()))
                mask = (
                    (instants[starts[i]] >= request.available_from_utc.timestamp())
                    & (instants[starts[i]] < request.deadline_utc.timestamp())
                )
                for j in np.flatnonzero(mask):
                    group_members[int(offsets[i] + j)].append(g)
        groups_by_request.append(g_for_r)
    return requests, group_names, groups_by_request, group_members, first_by_tile



def solve(args):
    started = time.monotonic()
    instants, starts, ends, rewards, request_cents, impossible = all_arcs(args.scenario)
    scorer = ChallengeScorer.from_files(args.scenario)
    if scorer.mechanics or scorer.tile_anomalies or scorer.config.get("coverage_bonus_weight", 0):
        raise ValueError("only the public practice semantics are supported")
    if len(starts) != len(scorer.tiles) or len(instants) != len(scorer.slots) * 6:
        raise AssertionError("candidate/scorer dimension mismatch")
    requests, group_names, groups_by_request, group_members, first_by_tile = request_groups(
        scorer, instants, starts,
    )
    n_success = sum(len(a) for a in starts)
    n_tags = sum(map(len, group_members.values()))
    if n_success != 918_757 or n_tags != 46_382 or request_cents != 392_000:
        raise AssertionError((n_success, n_tags, request_cents))
    if impossible != ["RQ0015"]:
        raise AssertionError("all-earned condition assumes only RQ0015 impossible")
    latest_release = max(
        r.available_from_utc.timestamp()
        for r in requests if r.request_id not in impossible
    )
    boundaries, actionable_by_tile, actionable_by_boundary, action_audit = (
        wait_actionability(
            scorer, instants, starts, latest_release,
            args.boundary_stride,
        )
    )
    partial_starts, partial_ends = _partial_weather_arcs(
        args.scenario, scorer, instants
    )
    print(json.dumps({"phase": "enumerated", "seconds": time.monotonic() - started,
                      "successful_arcs": n_success, "tag_copies": n_tags,
                      "request_groups": len(group_names),
                      "wait_boundary_count": len(boundaries),
                      "actionable_pairs": action_audit["actionable_tile_boundary_pairs"],
                      "weather_partial_pair_count": len(partial_starts)}), flush=True)

    solver = pywraplp.Solver.CreateSolver(args.engine)
    if solver is None:
        raise RuntimeError(f"{args.engine} unavailable")
    if args.engine == "PDLP":
        solver.SetNumThreads(args.threads)
    solver.SetTimeLimit(args.time_limit_seconds * 1000)
    infinity = solver.infinity()
    capacity = [solver.RowConstraint(-infinity, 1.0, "") for _ in range(len(instants))]
    tile_once = [solver.RowConstraint(-infinity, 1.0, "") for _ in starts]
    access = [solver.RowConstraint(-infinity, 0.0, "") for _ in group_names]
    early_first = [solver.RowConstraint(-infinity, 0.0, "") for _ in group_names]
    objective = solver.Objective()
    objective.SetMaximization()
    # O_b is the fraction of the first 150-second cell of slot b covered by
    # a successful or weather-interrupted action. Capacity already gives
    # O_b <= 1. The equality supplies one sparse row rather than expanding
    # every action again in each of the 138k tile-specific wait cuts.
    occupancy_rows = {}
    occupancy_vars = {}
    wait_vars = {}
    wait_rows_by_tile = [[] for _ in starts]
    for b in boundaries:
        b = int(b)
        if b not in actionable_by_boundary:
            continue
        o = solver.NumVar(0.0, 1.0, "")
        occ_row = solver.RowConstraint(0.0, 0.0, "")
        occ_row.SetCoefficient(o, 1.0)
        occupancy_vars[b] = o
        occupancy_rows[b] = occ_row
        c = solver.NumVar(0.0, 1.0, "")
        wait_vars[b] = c
        objective.SetCoefficient(c, -90.0)
        for i in actionable_by_boundary[b]:
            row = solver.RowConstraint(1.0, infinity, "")
            row.SetCoefficient(c, 1.0)
            row.SetCoefficient(o, 1.0)
            wait_rows_by_tile[i].append((b, row))

    def add_occupancy(u: int, v: int, variable) -> None:
        first_boundary = ((u + 5) // 6) * 6
        for b in range(first_boundary, v, 6):
            row = occupancy_rows.get(b)
            if row is not None:
                row.SetCoefficient(variable, -1.0)

    link_rows: dict[int, object] = {}
    first_records = []
    repeat_records = []
    first_vars_by_tile: dict[int, list[tuple[int, object]]] = defaultdict(list)
    repeat_by_tile: dict[int, dict[int, list[object]]] = defaultdict(lambda: defaultdict(list))
    event = 0
    for i, (a, b, q) in enumerate(zip(starts, ends, rewards)):
        for j in range(len(a)):
            u, v = int(a[j]), int(b[j])
            x = solver.NumVar(0.0, 1.0, "")
            first_records.append((i, u, v, int(q[j]), x))
            objective.SetCoefficient(x, float(q[j]))
            tile_once[i].SetCoefficient(x, 1.0)
            first_vars_by_tile[i].append((v, x))
            for g, deadline in first_by_tile[i]:
                if instants[u] < deadline:
                    early_first[g].SetCoefficient(x, -1.0)
            for t in range(u, v):
                capacity[t].SetCoefficient(x, 1.0)
            add_occupancy(u, v, x)
            gs = group_members.get(event)
            if gs:
                row = solver.RowConstraint(-infinity, 0.0, "")
                row.SetCoefficient(x, -1.0)
                link_rows[event] = row
                for g in gs:
                    tagged = solver.NumVar(0.0, 1.0, "")
                    row.SetCoefficient(tagged, 1.0)
                    access[g].SetCoefficient(tagged, -1.0)
                    repeat = solver.NumVar(0.0, 1.0, "")
                    repeat_records.append((i, u, v, g, repeat))
                    repeat_by_tile[i][u].append(repeat)
                    access[g].SetCoefficient(repeat, -1.0)
                    for t in range(u, v):
                        capacity[t].SetCoefficient(repeat, 1.0)
                    add_occupancy(u, v, repeat)
            event += 1
        if (i + 1) % 16 == 0:
            print(json.dumps({"phase": "building", "tiles": i + 1,
                              "variables": solver.NumVariables(),
                      "seconds": time.monotonic() - started}), flush=True)
    for u, v in zip(partial_starts, partial_ends):
        u, v = int(u), int(v)
        partial = solver.NumVar(0.0, 1.0, "")
        for t in range(u, v):
            capacity[t].SetCoefficient(partial, 1.0)
        add_occupancy(u, v, partial)
    awards = []
    # Prefix completion state only at timestamps where a tagged revisit could
    # start. Each first column enters exactly one recurrence equation.
    prefix_rows: dict[int, tuple[np.ndarray, list, list]] = {}
    for i in range(len(starts)):
        revisits = repeat_by_tile.get(i, {})
        wait_map = dict(wait_rows_by_tile[i])
        times = np.array(sorted(set(revisits) | set(wait_map)), dtype=np.int32)
        if len(times) == 0:
            continue
        completed = sorted(first_vars_by_tile[i], key=lambda item: item[0])
        before = None
        k = 0
        equalities = []
        revisit_rows = []
        for u in times:
            F = solver.NumVar(0.0, 1.0, "")
            eq = solver.RowConstraint(0.0, 0.0, "")
            eq.SetCoefficient(F, 1.0)
            if before is not None:
                eq.SetCoefficient(before, -1.0)
            while k < len(completed) and completed[k][0] <= u:
                eq.SetCoefficient(completed[k][1], -1.0)
                k += 1
            row = solver.RowConstraint(-infinity, 0.0, "")
            row.SetCoefficient(F, -1.0)
            for repeat in revisits.get(int(u), ()):
                row.SetCoefficient(repeat, 1.0)
            if int(u) in wait_map:
                wait_map[int(u)].SetCoefficient(F, 1.0)
            equalities.append(eq)
            revisit_rows.append(row)
            before = F
        prefix_rows[i] = (times, equalities, revisit_rows)
    for request, gs in zip(requests, groups_by_request):
        if request.request_id in impossible:
            award = solver.NumVar(0.0, 0.0, "")
        else:
            award = solver.NumVar(1.0, 1.0, "")
        awards.append(award)
        objective.SetCoefficient(award, round(100 * request.completion_reward))
        for g in gs:
            access[g].SetCoefficient(award, 1.0)
            early_first[g].SetCoefficient(award, 1.0)
    miss_rows = []
    for i, request in enumerate(requests):
        feasible_count = sum(
            scorer._tile_has_request_opportunity(
                scorer.tiles[tile_id], request.available_from_utc,
                request.deadline_utc,
            ) for tile_id in scorer.request_tiles[request.request_id]
        )
        if feasible_count < request.required_tile_count:
            continue  # The scorer excuses an unawarded expired request.
        later = [j for j, other in enumerate(requests)
                 if other.available_from_utc >= request.deadline_utc]
        if not later:
            continue
        miss = solver.NumVar(0.0, 1.0, "")
        objective.SetCoefficient(miss, -round(100 * request.miss_penalty))
        for j in later:
            row = solver.RowConstraint(-infinity, 0.0, "")
            row.SetCoefficient(awards[j], 1.0)
            row.SetCoefficient(awards[i], -1.0)
            row.SetCoefficient(miss, -1.0)
            miss_rows.append((i, j, row))
    built_seconds = time.monotonic() - started
    print(json.dumps({"phase": "solving", "variables": solver.NumVariables(),
                      "constraints": solver.NumConstraints(),
                      "seconds": built_seconds}), flush=True)
    status = solver.Solve()
    solved_seconds = time.monotonic() - started
    print(json.dumps({"phase": "solved", "status": status,
                      "lp_objective_cents": objective.Value(),
                      "seconds": solved_seconds}), flush=True)
    if status != pywraplp.Solver.OPTIMAL:
        # Feasible but nonoptimal restricted objective is not a global bound.
        # GLOP duals are only used after its optimal status is established.
        raise RuntimeError(f"{args.engine} did not report optimal LP status: {status}")
    first_science = sum(q * x.solution_value()
                        for _, _, _, q, x in first_records)
    request_reward = sum(round(100 * r.completion_reward) * y.solution_value()
                         for r, y in zip(requests, awards))
    wait_charge = 90.0 * sum(c.solution_value() for c in wait_vars.values())
    positive_first = sum(x.solution_value() > 1e-8
                         for _, _, _, _, x in first_records)
    positive_repeat = sum(z.solution_value() > 1e-8
                          for _, _, _, _, z in repeat_records)
    dual_cert = None
    if args.certify_dual:
        dual_cert = certify_integer_dual(solver, args.dual_out)
    output = {
        "scope": "public dev-reference; conditional on all 17 feasible requests awarded",
        "model": "all-action interval LP plus unavoidable full-slot wait lower bounds",
        "candidate_count": n_success,
        "tag_copy_count": n_tags,
        "weather_partial_pair_count": len(partial_starts),
        "full_action_column_count": n_success + 2 * n_tags + len(partial_starts),
        "request_group_count": len(group_names),
        "inevitable_miss_implication_count": len(miss_rows),
        "prefix_checkpoint_count": sum(len(item[0]) for item in prefix_rows.values()),
        "pre_last_release_slot_boundaries": len(boundaries),
        "boundary_stride": args.boundary_stride,
        "occupied_boundary_variables": len(occupancy_vars),
        "full_slot_wait_variables": len(wait_vars),
        "full_slot_wait_inequalities": sum(len(v) for v in wait_rows_by_tile),
        "actionability_audit": action_audit,
        "last_awarded_request_release_epoch": latest_release,
        "request_count": len(requests),
        "request_award_lp_values": {
            r.request_id: round(y.solution_value(), 9)
            for r, y in zip(requests, awards)
        },
        "lp_positive_first_column_count": positive_first,
        "lp_positive_repeat_column_count": positive_repeat,
        "impossible_requests": impossible,
        "capacity_cells": len(instants),
        "model_variables": solver.NumVariables(),
        "model_constraints": solver.NumConstraints(),
        "solver_engine": args.engine,
        "solver_status": "OPTIMAL",
        "solver_objective_cents": objective.Value(),
        "solver_objective_points": objective.Value() / 100.0,
        "lp_first_science_cents": first_science,
        "lp_request_reward_cents": request_reward,
        "lp_full_slot_wait_lower_bound_cents": wait_charge,
        "independent_dual_certificate_available": dual_cert is not None,
        "independent_dual_certificate": dual_cert,
        "runtime_seconds": {
            "build": built_seconds,
            "solve": time.monotonic() - started - built_seconds,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=PRACTICE)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "results" / "practice_global_wait_lp_diagnostic.json")
    parser.add_argument("--time-limit-seconds", type=int, default=1200)
    parser.add_argument("--boundary-stride", type=int, default=1)
    parser.add_argument("--engine", choices=("GLOP", "PDLP"), default="GLOP")
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--certify-dual", action="store_true")
    parser.add_argument("--dual-out", type=Path,
                        default=ROOT / "results" / "practice_global_wait_lp_dual.npz")
    solve(parser.parse_args())


if __name__ == "__main__":
    main()
