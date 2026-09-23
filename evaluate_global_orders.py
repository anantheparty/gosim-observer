#!/usr/bin/env python3
"""Parallel exact fixed-first-order evaluation of independent construction orders.

Designed for the public dev-reference practice instance, including a remote
machine with a read-only copy of the public repository. Each candidate is
replayed with the authoritative scorer; outputs live in its own directory.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


MODEL = None
SCORES = None
PROGRAMS = None


def _initialize(project_root: str) -> None:
    global MODEL, SCORES, PROGRAMS
    root = Path(project_root)
    sys.path.insert(0, str(root))
    from practice_lns import PracticeModel
    from sequence_dp import score_table
    MODEL = PracticeModel(
        root / "scenarios" / "dev-reference",
        root / "results" / "practice_reference.csv",
    )
    SCORES, PROGRAMS = score_table(MODEL)


def _evaluate(candidate: dict, output_root: str) -> dict:
    from sequence_active_requests_dp import solve
    from sequence_block_dp import _write
    if MODEL is None:
        raise RuntimeError("worker model not initialized")
    seed = candidate["seed"]
    order = [MODEL.tile_index[tile_id] for tile_id in candidate["first_order"]]
    output = Path(output_root) / f"seed_{seed}" / "decisions.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        path, partial_flags, predicted, optional, partial, data = solve(
            MODEL, SCORES, PROGRAMS, order
        )
        _write(MODEL, output, path)
        report = MODEL.authoritative_score(output)
        observed = [a for a in report["actions"] if a["action"] == "observe"]
        if len(observed) != len(partial_flags) or any(
            action["penalty"] != 0.0 or action["outcome"] !=
            ("weather_interrupted" if is_partial else "completed")
            for action, is_partial in zip(observed, partial_flags)
        ):
            raise AssertionError("official action outcomes disagree with DP")
        if report["score"]["request_reward"] != 3920.0:
            raise AssertionError("request reward below required amount")
        total = report["score"]["total"]
        if abs(total - predicted - 3920.0) > 1e-5:
            raise AssertionError("official score disagrees with DP")
        return {
            "seed": seed, "mode": candidate.get("mode"),
            "score": total,
            "science": report["score"]["base_science"] + report["score"]["program_bonus"],
            "wait": report["score"]["penalties"].get("avoidable_wait", 0.0),
            "weather_partial": partial, "optional": optional,
            "decisions": str(output),
            "seconds": time.monotonic() - started,
        }
    except ValueError as exc:
        return {"seed": seed, "mode": candidate.get("mode"),
                "error": str(exc), "seconds": time.monotonic() - started}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path,
                        default=Path(__file__).resolve().parent)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    source = json.loads(args.manifest.read_text())
    candidates = source["constructed_orders"]
    if args.limit:
        candidates = candidates[:args.limit]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    results = []
    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=_initialize,
        initargs=(str(args.project_root.resolve()),),
    ) as pool:
        futures = [pool.submit(_evaluate, c, str(args.out_dir.resolve()))
                   for c in candidates]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, sort_keys=True), flush=True)
    results.sort(key=lambda r: r["seed"])
    out = {
        "scope": "public dev-reference, exact fixed-order DP + official scorer",
        "candidate_count": len(candidates),
        "worker_count": args.workers,
        "elapsed_seconds": time.monotonic() - start,
        "results": results,
        "best": max((r for r in results if "score" in r),
                    key=lambda r: r["score"], default=None),
    }
    (args.out_dir / "evaluation.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"best": out["best"],
                      "elapsed_seconds": out["elapsed_seconds"]},
                     sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
