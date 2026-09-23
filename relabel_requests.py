#!/usr/bin/env python3
"""Optimize request labels on a fixed, already legal observation timeline.

This is an offline analysis tool. It changes only the ``request_id`` field of
observe rows; all starts, exposures, waits, programs, and reports stay fixed.
Each successful exposure can visit at most one request whose tile and
``available_from <= exposure_start < deadline`` match. A request earns its
whole reward only after enough distinct listed tiles reach their individual
visit counts. A practice revisit to an already completed tile must keep some
valid request label, even if that visit adds no useful progress.

For each request, the objective gives completion its full reward plus the
miss penalty it would otherwise incur at the trace endpoint; unexpired and
unobservable-excused misses have zero penalty. All variables and constraints
cover the full set of legal labels and visits on this fixed timeline. The
original trace and the result are both replayed by the authoritative scorer.
A CP-SAT OPTIMAL status proves the best request score attainable by relabeling
this particular physical timeline, not the best survey schedule. This tool
uses the complete local scenario and must not be used by a live agent to look
ahead at unreleased requests.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from ortools.sat.python import cp_model

from challenge.contracts import DECISION_COLUMNS, parse_utc
from challenge.scoring_core import ChallengeScorer, Decision, load_decisions


PHYSICAL_OBSERVE_OUTCOMES = {
    "completed",
    "weather_interrupted",
    "geometry_or_night_interrupted",
}


@dataclass(frozen=True)
class Exposure:
    row_index: int
    tile_id: str
    started: object
    completed: bool
    must_have_tag: bool
    original_tag: str


def replay(scenario: Path, rows: list[Decision]):
    scorer = ChallengeScorer.from_files(scenario)
    exposures: list[Exposure] = []
    physical_trace = []
    for index, row in enumerate(rows):
        completed_before = row.tile_id in scorer.completed_tiles
        result = scorer.apply_decision(row)
        physical_trace.append(
            (
                result.get("action"),
                result.get("slot_id"),
                result.get("tile_id"),
                result.get("program"),
                result.get("start_utc"),
                result.get("elapsed_seconds"),
                result.get("outcome"),
                result.get("base_science_score"),
                result.get("program_bonus_score"),
                result.get("penalty"),
            )
        )
        if row.action != "observe":
            continue
        if result["outcome"] not in PHYSICAL_OBSERVE_OUTCOMES:
            raise ValueError(
                f"{row.decision_id}: original outcome {result['outcome']!r} is "
                "not a legal physical exposure; changing its tag may change time or penalties"
            )
        exposures.append(
            Exposure(
                row_index=index,
                tile_id=row.tile_id,
                started=parse_utc(result["start_utc"]),
                completed=result["outcome"] == "completed",
                must_have_tag=not scorer.mechanics and completed_before,
                original_tag=row.request_id,
            )
        )
    final_time = scorer.current_time()
    if final_time is None and scorer.slots:
        final_time = scorer.slots[-1].end_utc
    report = scorer.finalize("trace_complete")
    return scorer, exposures, physical_trace, final_time, report


def request_weights(scorer: ChallengeScorer, final_time):
    """Return exact whole-request improvement over leaving it incomplete."""
    relevant = {
        request_id: request
        for request_id, request in scorer.requests.items()
        if final_time is not None and request.issued_at_utc <= final_time
    }
    weights: dict[str, Decimal] = {}
    miss_if_incomplete: dict[str, Decimal] = {}
    for request_id, request in relevant.items():
        miss = Decimal(0)
        if request.deadline_utc <= final_time:
            opportunity_count = sum(
                scorer._tile_has_request_opportunity(
                    scorer.tiles[tile_id], request.available_from_utc,
                    request.deadline_utc,
                )
                for tile_id in scorer.request_tiles[request_id]
            )
            if opportunity_count >= request.required_tile_count:
                miss = Decimal(str(request.miss_penalty))
        miss_if_incomplete[request_id] = miss
        weights[request_id] = Decimal(str(request.completion_reward)) + miss
    return relevant, weights, miss_if_incomplete


def _scale_weights(weights: dict[str, Decimal]) -> dict[str, int]:
    digits = max((max(0, -value.as_tuple().exponent) for value in weights.values()), default=0)
    factor = Decimal(10) ** digits
    return {key: int(value * factor) for key, value in weights.items()}


def optimize_labels(
    scorer: ChallengeScorer,
    rows: list[Decision],
    exposures: list[Exposure],
    final_time,
    time_limit: float,
    workers: int,
):
    relevant, weights, miss_if_incomplete = request_weights(scorer, final_time)
    model = cp_model.CpModel()
    tag: dict[tuple[int, str], cp_model.IntVar] = {}
    blank: dict[int, cp_model.IntVar] = {}
    usable: dict[tuple[str, str], list[cp_model.IntVar]] = {}
    preserve = []

    for exposure in exposures:
        options = []
        for request_id, request in relevant.items():
            if (
                exposure.tile_id in scorer.request_tiles[request_id]
                and request.issued_at_utc <= exposure.started
                and request.available_from_utc <= exposure.started < request.deadline_utc
            ):
                variable = model.NewBoolVar(f"tag_{exposure.row_index}_{request_id}")
                tag[exposure.row_index, request_id] = variable
                options.append(variable)
                if exposure.completed:
                    usable.setdefault((request_id, exposure.tile_id), []).append(variable)
                if exposure.original_tag == request_id:
                    preserve.append(variable)
        if exposure.must_have_tag:
            if not options:
                raise ValueError(
                    f"{rows[exposure.row_index].decision_id}: practice revisit has "
                    "no valid request label"
                )
            model.Add(sum(options) == 1)
        else:
            variable = model.NewBoolVar(f"blank_{exposure.row_index}")
            blank[exposure.row_index] = variable
            model.Add(sum(options) + variable == 1)
            if not exposure.original_tag:
                preserve.append(variable)
        if exposure.original_tag and (exposure.row_index, exposure.original_tag) not in tag:
            raise ValueError(
                f"{rows[exposure.row_index].decision_id}: original request tag "
                f"{exposure.original_tag!r} was not legally issued at exposure start"
            )

    complete: dict[str, cp_model.IntVar] = {}
    for request_id, request in relevant.items():
        satisfied = []
        for tile_id, visits_required in scorer.request_tiles[request_id].items():
            variable = model.NewBoolVar(f"sat_{request_id}_{tile_id}")
            eligible = usable.get((request_id, tile_id), [])
            if len(eligible) < visits_required:
                model.Add(variable == 0)
            else:
                model.Add(sum(eligible) >= visits_required).OnlyEnforceIf(variable)
                model.Add(sum(eligible) <= visits_required - 1).OnlyEnforceIf(variable.Not())
            satisfied.append(variable)
        fulfilled = model.NewBoolVar(f"complete_{request_id}")
        complete[request_id] = fulfilled
        if len(satisfied) < request.required_tile_count:
            model.Add(fulfilled == 0)
        else:
            model.Add(sum(satisfied) >= request.required_tile_count).OnlyEnforceIf(fulfilled)
            model.Add(sum(satisfied) <= request.required_tile_count - 1).OnlyEnforceIf(fulfilled.Not())

    scaled = _scale_weights(weights)
    # One unit of request objective outranks changing every tag. Among equally
    # scoring assignments, keep as many original labels as possible.
    tie_break_base = len(exposures) + 1
    model.Maximize(
        tie_break_base * sum(scaled[request_id] * variable for request_id, variable in complete.items())
        + sum(preserve)
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    if status != cp_model.OPTIMAL:
        raise RuntimeError(
            f"request relabeling was not proved optimal: {status_name}; "
            "increase --time-limit before writing a result"
        )

    output = list(rows)
    for exposure in exposures:
        selected = next(
            (request_id for (index, request_id), variable in tag.items()
             if index == exposure.row_index and solver.Value(variable)),
            "",
        )
        output[exposure.row_index] = replace(rows[exposure.row_index], request_id=selected)
    solved_request_gain = sum(
        weights[request_id] for request_id, variable in complete.items()
        if solver.Value(variable)
    ) - sum(miss_if_incomplete.values())
    return output, {
        "status": status_name,
        "request_score_model": float(solved_request_gain),
        "completed_requests": [
            request_id for request_id, variable in complete.items() if solver.Value(variable)
        ],
        "changed_labels": sum(
            old.request_id != new.request_id for old, new in zip(rows, output)
        ),
        "exposures": len(exposures),
        "label_options": len(tag),
    }


def write_csv(path: Path, rows: list[Decision]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS)
        writer.writeheader()
        writer.writerows(row.csv_row() for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--time-limit", type=float, default=600.0)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.input.resolve() == args.out.resolve():
        parser.error("--out must differ from --input")
    if args.time_limit <= 0 or args.workers < 1:
        parser.error("--time-limit and --workers must be positive")
    original = load_decisions(args.input)
    scorer, exposures, physical_before, final_time, before = replay(args.scenario, original)
    relabeled, model_info = optimize_labels(
        scorer, original, exposures, final_time, args.time_limit, args.workers
    )
    _, _, physical_after, final_after, after = replay(args.scenario, relabeled)
    if physical_before != physical_after or final_time != final_after:
        raise AssertionError("relabeling changed the physical action timeline")
    for key in ("base_science", "program_bonus", "coverage_bonus"):
        if abs(before["score"][key] - after["score"][key]) > 1e-6:
            raise AssertionError(f"relabeling unexpectedly changed {key}")
    for key, value in before["score"]["penalties"].items():
        if key == "request_miss":
            continue
        if abs(value - after["score"]["penalties"].get(key, 0.0)) > 1e-6:
            raise AssertionError(f"relabeling unexpectedly changed {key} penalty")
    replay_request_score = (
        after["score"]["request_reward"] - after["score"]["penalties"]["request_miss"]
    )
    if abs(replay_request_score - model_info["request_score_model"]) > 1e-6:
        raise AssertionError("CP-SAT request objective disagrees with authoritative replay")
    write_csv(args.out, relabeled)
    print(
        f"{model_info['status']}: {model_info['exposures']} exposures, "
        f"{model_info['label_options']} valid label options, "
        f"{model_info['changed_labels']} labels changed"
    )
    print(
        f"request score {before['score']['request_reward'] - before['score']['penalties']['request_miss']:.6f} "
        f"-> {replay_request_score:.6f}; total score "
        f"{before['score']['total']:.6f} -> {after['score']['total']:.6f}"
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
