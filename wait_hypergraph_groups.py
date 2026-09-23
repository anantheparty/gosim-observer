#!/usr/bin/env python3
"""Select exact event-LNS tile groups from the incumbent's charged-wait OR hypergraph.

`extract` uses the local practice scorer and NumPy/Numba environment. `select`
uses OR-Tools CP-SAT. These stages may run in separate Python environments.
The hypergraph objective only ranks destroy sets; every repaired schedule must
still be evaluated by the full event DP and official scorer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def extract(incumbent: Path, output: Path) -> None:
    import numpy as np

    from multistart_large_neighborhood import REFERENCE, SCENARIO
    from practice_lns import PracticeModel

    model = PracticeModel(SCENARIO, REFERENCE)
    report = model.authoritative_score(incumbent)
    completion = 0
    cursor = 0
    waits = []
    by_mask = defaultdict(int)
    for action in report["actions"]:
        if action["action"] != "observe":
            continue
        epoch = datetime.fromisoformat(
            action["start_utc"].replace("Z", "+00:00")
        ).timestamp()
        start = int(np.searchsorted(model.instants, epoch))
        if start >= model.n_units or abs(model.instants[start] - epoch) > 1e-6:
            raise AssertionError("observation is off the public 150-second grid")
        while cursor < start:
            boundary = (cursor // 6 + 1) * 6
            if boundary > start:
                raise AssertionError("gap does not consist of legal waits")
            blockers = int(model.actionable[cursor]) & ~completion
            if blockers:
                cost_cents = (boundary - cursor) * 15
                waits.append({"unit": cursor, "mask": blockers, "cents": cost_cents})
                by_mask[blockers] += cost_cents
            cursor = boundary
        if cursor != start:
            raise AssertionError("gap ended at the wrong cursor")
        cursor = start + int(action["elapsed_seconds"]) // 150
        if action["outcome"] == "completed":
            completion |= 1 << model.tile_index[action["tile_id"]]
    actual_cents = round(report["score"]["penalties"]["avoidable_wait"] * 100)
    if sum(by_mask.values()) != actual_cents:
        raise AssertionError("wait hypergraph does not reproduce official wait penalty")
    result = {
        "scenario": "dev-reference",
        "path": str(incumbent),
        "sha256": hashlib.sha256(incumbent.read_bytes()).hexdigest(),
        "score": report["score"]["total"],
        "tile_ids": model.tile_ids,
        "wait_cents": actual_cents,
        "charged_waits": len(waits),
        "masks": [
            {"mask": mask, "cents": cents, "size": mask.bit_count()}
            for mask, cents in sorted(by_mask.items(), key=lambda p: (-p[1], p[0]))
        ],
        "wait_edges": waits,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "score": result["score"], "wait_cents": actual_cents,
        "charged_waits": len(waits), "distinct_masks": len(by_mask),
        "output": str(output),
    }))


def select(input_path: Path, group_out: Path, report_out: Path,
           sizes: list[int], per_size: int, min_replace: int,
           seconds: float) -> None:
    from ortools.sat.python import cp_model

    data = json.loads(input_path.read_text())
    tile_ids = data["tile_ids"]
    all_groups = []
    rows = []
    for k in sizes:
        eligible = [row for row in data["masks"] if row["size"] <= k]
        model = cp_model.CpModel()
        x = [model.NewBoolVar(f"tile_{i}") for i in range(len(tile_ids))]
        model.Add(sum(x) == k)
        y = []
        for j, row in enumerate(eligible):
            match = model.NewBoolVar(f"mask_{j}")
            for i in range(len(tile_ids)):
                if (row["mask"] >> i) & 1:
                    model.Add(match <= x[i])
            y.append(match)
        model.Maximize(sum(row["cents"] * match for row, match in zip(eligible, y)))
        for rank in range(per_size):
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = seconds
            solver.parameters.num_search_workers = 4
            solver.parameters.random_seed = 47 + 101 * k + rank
            status = solver.Solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                break
            chosen = [i for i, bit in enumerate(x) if solver.Value(bit)]
            mask = sum(1 << i for i in chosen)
            covered = sum(
                row["cents"] for row in data["masks"]
                if row["mask"] & mask == row["mask"]
            )
            if abs(solver.ObjectiveValue() - covered) > 1e-6:
                raise AssertionError("CP objective and explicit hyperedge sum disagree")
            group = [tile_ids[i] for i in chosen]
            all_groups.append(group)
            rows.append({
                "k": k, "rank": rank, "tiles": group,
                "covered_wait_cents": covered,
                "status": solver.StatusName(status),
                "best_bound_cents": solver.BestObjectiveBound(),
            })
            model.Add(sum(x[i] for i in chosen) <= k - min_replace)
    group_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    group_out.write_text(json.dumps(all_groups, indent=2) + "\n")
    report_out.write_text(json.dumps({
        "source_sha256": data["sha256"], "groups": rows,
        "interpretation": "destroy-set priority only, not score gain or original-problem bound",
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "groups": len(all_groups), "best_covered_wait_points":
        rows[0]["covered_wait_cents"] / 100 if rows else None,
        "group_out": str(group_out), "report_out": str(report_out),
    }))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_extract = sub.add_parser("extract")
    p_extract.add_argument("--incumbent", type=Path, required=True)
    p_extract.add_argument("--out", type=Path, required=True)
    p_select = sub.add_parser("select")
    p_select.add_argument("--hyperedges", type=Path, required=True)
    p_select.add_argument("--groups-out", type=Path, required=True)
    p_select.add_argument("--report-out", type=Path, required=True)
    p_select.add_argument("--sizes", type=int, nargs="+", default=[6, 8, 10])
    p_select.add_argument("--per-size", type=int, default=12)
    p_select.add_argument("--min-replace", type=int, default=2)
    p_select.add_argument("--seconds", type=float, default=8.0)
    args = parser.parse_args()
    if args.command == "extract":
        extract(args.incumbent, args.out)
    else:
        select(args.hyperedges, args.groups_out, args.report_out,
               args.sizes, args.per_size, args.min_replace, args.seconds)


if __name__ == "__main__":
    main()
