#!/usr/bin/env python3
"""Recover a feasible first order from a grouped interval-packing model.

This is a lower-bound experiment. A projected arc objective is only a guide;
every reported schedule is replayed with the authoritative local scorer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from ortools.sat.python import cp_model

import bounds_request_projection_k10 as bound
import projection_primal_probe as probe
import sequence_active_requests_dp as active
from practice_lns import PracticeModel
from sequence_block_dp import _write
from sequence_dp import score_table


ROOT = Path(__file__).resolve().parent
TRACE = ROOT / "results/practice_projection_primal_probe.json"
BEST = ROOT / "results/practice_best.csv"


def candidates(data: dict, inputs: dict, branch: int, trace: dict,
               incumbent: dict[str, int]) -> list[list[int]]:
    """Top reduced arcs in distinct nights/epochs, plus proven schedule arcs."""
    starts = inputs["arc_starts"]
    reduced = data["complete_reduced"]
    tile = data["complete_tile"]
    n = data["n"]
    mandatory = inputs["deadlines_by_branch"][branch]
    forced = {row["tile_id"]: row["arc_index"] for row in trace["key_arcs"]}
    result = []
    for i, tile_id in enumerate(data["tile_ids"]):
        js = np.flatnonzero(tile == i)
        if tile_id in mandatory:
            limit = int(np.searchsorted(inputs["instants"], mandatory[tile_id], side="left"))
            js = js[starts[js] < limit]
        if len(js) == 0:
            raise AssertionError(f"mandatory tile has no legal arc: {tile_id}")
        # First take the best arc of each observing night; spread retained
        # nights over the horizon before adding fine alternatives.
        by_night: dict[int, int] = {}
        by_epoch: dict[int, int] = {}
        for j0 in js:
            j = int(j0)
            night = int(starts[j] // 264)
            epoch = int(12 * starts[j] // n)
            old = by_night.get(night)
            if old is None or (reduced[j], -starts[j]) > (reduced[old], -starts[old]):
                by_night[night] = j
            old = by_epoch.get(epoch)
            if old is None or (reduced[j], -starts[j]) > (reduced[old], -starts[old]):
                by_epoch[epoch] = j
        nights = sorted(by_night.values(), key=lambda j: (-int(reduced[j]), int(starts[j])))[:28]
        epochs = sorted(by_epoch.values(), key=lambda j: int(starts[j]))
        top = sorted(js, key=lambda j: (-int(reduced[j]), int(starts[j])))[:12]
        selected = set(map(int, nights + epochs + top))
        if tile_id in forced:
            selected.add(int(forced[tile_id]))
        if tile_id in incumbent:
            matched = js[starts[js] == incumbent[tile_id]]
            if len(matched):
                selected.add(int(matched[np.argmax(reduced[matched])]))
        result.append(sorted(selected, key=lambda j: (int(starts[j]), -int(reduced[j]))))
    return result


def incumbent_first_starts(model: PracticeModel, inputs: dict) -> dict[str, int]:
    report = model.authoritative_score(BEST)
    origin = float(inputs["instants"][0])
    seen = set()
    result = {}
    for action in report["actions"]:
        if action["action"] != "observe" or action["outcome"] != "completed":
            continue
        tile_id = action["tile_id"]
        if tile_id in seen:
            continue
        seen.add(tile_id)
        instant = datetime.fromisoformat(action["start_utc"].replace("Z", "+00:00")).timestamp()
        # Slots are contiguous in this benchmark, with 150-second arc units.
        unit = int(np.searchsorted(inputs["instants"], instant, side="left"))
        if unit >= len(inputs["instants"]) or abs(inputs["instants"][unit] - instant) > 1e-6:
            raise AssertionError(f"incumbent start not in arc grid: {tile_id}")
        result[tile_id] = unit
    if len(result) != len(model.tile_ids):
        raise AssertionError("incumbent lacks a completed tile")
    return result


def packing(data: dict, inputs: dict, choices: list[list[int]], trace: dict,
            incumbent: dict[str, int], *, fixed_keys: bool, seconds: float,
            workers: int, anchor_cents_per_unit: float) -> tuple[dict, list[int]]:
    model = cp_model.CpModel()
    selected: dict[int, cp_model.IntVar] = {}
    intervals = []
    starts = inputs["arc_starts"]
    ends = data["complete_end"]
    reduced = data["complete_reduced"]
    key_arc = {row["tile_id"]: int(row["arc_index"]) for row in trace["key_arcs"]}
    objective = []
    for i, tile_id in enumerate(data["tile_ids"]):
        options = choices[i]
        variables = []
        for j in options:
            var = model.NewBoolVar(f"x_{i}_{j}")
            selected[j] = var
            variables.append(var)
            intervals.append(model.NewOptionalFixedSizeIntervalVar(
                int(starts[j]), int(ends[j] - starts[j]), var, f"a_{i}_{j}"))
            # The reduced score prices scarce time; a small tie breaker keeps
            # an arc close to the incumbent without locking its order.
            deviation = abs(int(starts[j]) - incumbent[tile_id])
            objective.append((100 * int(reduced[j]) -
                              round(100 * anchor_cents_per_unit * deviation)) * var)
            if j == key_arc.get(tile_id):
                model.AddHint(var, 1)
            elif int(starts[j]) == incumbent[tile_id]:
                model.AddHint(var, 1)
        model.AddExactlyOne(variables)
        if fixed_keys and tile_id in key_arc:
            model.Add(selected[key_arc[tile_id]] == 1)
    model.AddNoOverlap(intervals)
    model.Maximize(sum(objective))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = 20260925
    solver.parameters.relative_gap_limit = 0.002
    started = time.monotonic()
    status = solver.Solve(model)
    row = {
        "status": solver.StatusName(status),
        "runtime_seconds": time.monotonic() - started,
        "candidate_arcs": sum(map(len, choices)),
        "fixed_key_arcs": fixed_keys,
        "objective_scaled": solver.ObjectiveValue() if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
        "best_bound_scaled": solver.BestObjectiveBound() if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
    }
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return row, []
    picked = [j for j, var in selected.items() if solver.BooleanValue(var)]
    if len(picked) != 64:
        raise AssertionError("packing selected wrong tile count")
    picked.sort(key=lambda j: (int(starts[j]), int(ends[j])))
    if any(int(ends[a]) > int(starts[b]) for a, b in zip(picked, picked[1:])):
        raise AssertionError("packing has overlapping intervals")
    row["selected_reduced_cents"] = int(sum(int(reduced[j]) for j in picked))
    row["selected_first_order"] = [data["tile_ids"][int(data["complete_tile"][j])] for j in picked]
    row["selected_arc_indices"] = picked
    return row, picked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "results/practice_grouped_arc_primal.json")
    parser.add_argument("--run-dir", type=Path, default=ROOT / "runs/grouped_arc_primal")
    parser.add_argument("--cp-seconds", type=float, default=45)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-seconds", type=float, default=300)
    parser.add_argument("--anchor-cents-per-unit", type=float, default=0.0005)
    parser.add_argument("--only-free", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    trace = json.loads(TRACE.read_text())
    data, _ = bound._load_audited_data(bound.PRICE_FILE)
    inputs = bound._instance_inputs(data)
    practice = PracticeModel(bound.PRACTICE, ROOT / "results/practice_reference.csv")
    incumbent = incumbent_first_starts(practice, inputs)
    choices = candidates(data, inputs, 1, trace, incumbent)
    scores, programs = score_table(practice)
    incumbent_score = practice.authoritative_score(BEST)["score"]["total"]
    report = {"scope": "public dev-reference only", "method": "grouped first-arc interval CP then exact fixed-order request DP",
              "incumbent_score": incumbent_score, "online_submissions": 0,
              "trace_sha256": hashlib.sha256(TRACE.read_bytes()).hexdigest(), "cases": []}
    args.run_dir.mkdir(parents=True, exist_ok=True)
    for fixed_keys in ((False,) if args.only_free else (True, False)):
        if time.monotonic() - started > args.max_seconds - 55:
            break
        case, picked = packing(data, inputs, choices, trace, incumbent,
                               fixed_keys=fixed_keys, seconds=args.cp_seconds,
                               workers=args.workers,
                               anchor_cents_per_unit=args.anchor_cents_per_unit)
        case["anchor_cents_per_unit"] = args.anchor_cents_per_unit
        if picked:
            order = [int(data["complete_tile"][j]) for j in picked]
            try:
                path, partial, predicted, optional_count, partial_count, req_data = active.solve(
                    practice, scores, programs, order)
                csv_path = args.run_dir / ("fixed_keys.csv" if fixed_keys else "free_keys.csv")
                _write(practice, csv_path, path)
                scored = practice.authoritative_score(csv_path)
                case.update({"exact_dp_status": "feasible", "official_score": scored["score"]["total"],
                             "score_gap_from_incumbent": scored["score"]["total"] - incumbent_score,
                             "completed_tiles": len(scored["completion"]["completed_tiles"]),
                             "request_reward": scored["score"]["request_reward"],
                             "avoidable_wait": scored["score"]["penalties"]["avoidable_wait"],
                             "decision_count": len(path), "partial_count": partial_count})
                if (case["score_gap_from_incumbent"] <= 1e-7 or case["completed_tiles"] != 64
                        or case["request_reward"] != 3920.0):
                    csv_path.unlink()
                else:
                    case["improved_csv"] = str(csv_path)
            except ValueError as exc:
                case.update({"exact_dp_status": "infeasible", "error": str(exc)})
        report["cases"].append(case)
        report["runtime_seconds"] = time.monotonic() - started
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        print(json.dumps({k: v for k, v in case.items() if k not in ("selected_arc_indices", "selected_first_order")}), flush=True)
    report["runtime_seconds"] = time.monotonic() - started
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
