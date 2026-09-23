#!/usr/bin/env python3
"""Population search using exact restricted-column CP as a crossover operator.

Each member is a complete, officially replayed public-practice schedule. A
cross takes the union of two or three parents' observation columns and solves
the exact time graph on that union. Optional first-start shifts are a mutation.
This produces feasible lower bounds only; restricted-column optimum values are
never presented as global bounds.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from practice_lns import PracticeModel


ROOT = Path(__file__).resolve().parent
SCENARIO = ROOT / "scenarios" / "dev-reference"


@dataclass(frozen=True)
class Member:
    path: Path
    score: float
    observations: frozenset[tuple[str, str]]


def member(model: PracticeModel, path: Path) -> Member:
    report = model.authoritative_score(path)
    score = report["score"]
    if (len(report["completion"]["completed_tiles"]) != len(model.tiles)
            or score["request_reward"] != 3920.0
            or any(a["penalty"] for a in report["actions"])):
        raise ValueError(f"parent has missing requirements or penalties: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if any(row["reason"] for row in rows):
        raise ValueError(f"reason must be empty: {path}")
    observations = frozenset(
        (action["start_utc"], action["tile_id"])
        for action in report["actions"] if action["action"] == "observe"
    )
    return Member(path.resolve(), float(score["total"]), observations)


def distance(a: Member, b: Member) -> float:
    return 1.0 - len(a.observations & b.observations) / len(
        a.observations | b.observations
    )


def select_pairs(population: list[Member], cap: int, min_distance: float):
    """Prefer high scores with complementary columns, retaining some diversity."""
    options = []
    best = max(x.score for x in population)
    for a, b in itertools.combinations(population, 2):
        d = distance(a, b)
        if d < min_distance:
            continue
        mean_gap = best - (a.score + b.score) / 2
        # A diverse, weaker parent competes with a close, strong parent.
        priority = mean_gap - 600.0 * d
        options.append((priority, a, b, d))
    options.sort(key=lambda x: x[0])
    return options[:cap]


def select_triples(population: list[Member], cap: int, min_distance: float):
    """Join the champion to two sufficiently distinct genetic lineages."""
    if cap <= 0 or len(population) < 3:
        return []
    champion = max(population, key=lambda p: p.score)
    options = []
    for a, b in itertools.combinations(
        (p for p in population if p is not champion), 2
    ):
        d = min(distance(champion, a), distance(champion, b), distance(a, b))
        if d < min_distance:
            continue
        mean_gap = champion.score - (a.score + b.score) / 2
        options.append((mean_gap - 600.0 * d, champion, a, b, d))
    options.sort(key=lambda x: x[0])
    return options[:cap]


def run_cross(
    index: int, parents: tuple[Member, ...], shift: int,
    wait_neighbor_shift: int, wait_neighbor_limit: int,
    outdir: Path, seconds: float, cp_workers: int, seed: int,
) -> dict:
    child_dir = outdir / f"cross_{index:03d}"
    child_dir.mkdir(parents=True, exist_ok=True)
    child = child_dir / "decisions.csv"
    command = [
        sys.executable, str(ROOT / "relink_restricted_cp.py"), "--seeds",
        *(str(p.path) for p in parents), "--shift-units", str(shift),
        "--wait-neighbor-shift-units", str(wait_neighbor_shift),
        "--wait-neighbor-limit", str(wait_neighbor_limit),
        "--time-limit", str(seconds), "--workers", str(cp_workers),
        "--seed", str(seed + index), "--out", str(child),
    ]
    started = time.monotonic()
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False,
    )
    (child_dir / "solver.log").write_text(
        result.stdout + result.stderr, encoding="utf-8"
    )
    summary = {
        "index": index, "parents": [str(p.path) for p in parents],
        "parent_scores": [p.score for p in parents], "shift_units": shift,
        "wait_neighbor_shift_units": wait_neighbor_shift,
        "seconds": round(time.monotonic() - started, 3),
        "returncode": result.returncode,
    }
    if result.returncode == 0:
        try:
            summary.update(json.loads(result.stdout.strip().splitlines()[-1]))
        except (ValueError, IndexError):
            summary["parse_error"] = True
    (child_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--generations", type=int, default=2)
    parser.add_argument("--crosses-per-generation", type=int, default=6)
    parser.add_argument("--triples-per-generation", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--cp-workers", type=int, default=8)
    parser.add_argument("--time-limit", type=float, default=90)
    parser.add_argument("--min-distance", type=float, default=0.02)
    parser.add_argument("--shift-schedule", type=int, nargs="+", default=[0, 1])
    parser.add_argument("--wait-neighbor-shift-schedule", type=int, nargs="+", default=[0, 1])
    parser.add_argument("--wait-neighbor-limit", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20260924)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    model = PracticeModel(SCENARIO, ROOT / "results" / "practice_reference.csv")
    population = [member(model, p) for p in args.seeds]
    population.sort(key=lambda x: x.score, reverse=True)
    if len(population) < 2:
        raise ValueError("need at least two parents")
    champion = population[0]
    index = 0
    all_results = []
    for generation in range(args.generations):
        shift = args.shift_schedule[min(generation, len(args.shift_schedule) - 1)]
        wait_neighbor_shift = args.wait_neighbor_shift_schedule[
            min(generation, len(args.wait_neighbor_shift_schedule) - 1)
        ]
        pair_rows = select_pairs(
            population, args.crosses_per_generation, args.min_distance
        )
        triple_rows = select_triples(
            population, args.triples_per_generation, args.min_distance
        )
        if not pair_rows and not triple_rows:
            break
        tasks = []
        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            for _, a, b, d in pair_rows:
                index += 1
                future = executor.submit(
                    run_cross, index, (a, b), shift, wait_neighbor_shift,
                    args.wait_neighbor_limit, args.out / f"generation_{generation}",
                    args.time_limit, args.cp_workers, args.seed,
                )
                tasks.append((future, d))
            for _, a, b, c, d in triple_rows:
                index += 1
                future = executor.submit(
                    run_cross, index, (a, b, c), shift, wait_neighbor_shift,
                    args.wait_neighbor_limit, args.out / f"generation_{generation}",
                    args.time_limit, args.cp_workers, args.seed,
                )
                tasks.append((future, d))
            for future, d in tasks:
                row = future.result()
                row["parent_distance"] = d
                if row.get("official_score") is not None:
                    candidate = member(model, Path(row["output"]))
                    # Distinct full observation sets are retained even if the
                    # objective falls, allowing later recombination.
                    if all(candidate.observations != p.observations for p in population):
                        population.append(candidate)
                    if candidate.score > champion.score + 1e-7:
                        champion = candidate
                        shutil.copy2(candidate.path, args.out / "best.csv")
                        print(json.dumps({
                            "generation": generation, "improved": champion.score,
                            "source": str(candidate.path),
                        }), flush=True)
                all_results.append(row)
                with (args.out / "results.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        population.sort(key=lambda x: x.score, reverse=True)
        # Elite plus diverse survivors; avoid population bloat and duplicate
        # near-identical schedules from CP crossover.
        selected = population[:4]
        for candidate in population[4:]:
            if len(selected) >= 12:
                break
            if all(distance(candidate, p) >= args.min_distance for p in selected):
                selected.append(candidate)
        population = selected
        print(json.dumps({
            "generation": generation, "population": len(population),
            "champion": champion.score, "shift_units": shift,
            "wait_neighbor_shift_units": wait_neighbor_shift,
        }), flush=True)
    manifest = {
        "scope": "public dev-reference only",
        "algorithm": "population restricted-column CP crossover and first-start shift mutation",
        "best": champion.score, "best_path": str(champion.path),
        "crosses": len(all_results), "feasible_crosses": sum(
            row.get("official_score") is not None for row in all_results
        ),
        "population": [{"score": p.score, "path": str(p.path)} for p in population],
        "online_submissions": 0,
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
