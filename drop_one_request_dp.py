#!/usr/bin/env python3
"""Exact fixed-first-order DP for the no-tag dropped-request subfamily.

The scenario is public dev-reference. A dropped request cannot receive a tag;
its reward is omitted and its official deadline miss penalty is charged only
when the reconstructed schedule ends after the deadline. All other feasible
requests are still required. Partial tagging of an ultimately missed request
is outside this subfamily. Every candidate is replayed by the scorer.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

import sequence_active_requests_dp as active
from challenge.scoring_core import ChallengeScorer
from practice_lns import PracticeModel
from sequence_block_dp import _write
from sequence_dp import PROGRAMS, score_table


ROOT = Path(__file__).resolve().parent
MODEL = None
SCORES = None
PROGRAM_IDS = None
ORDERS = None


def drop_data(model: PracticeModel, scores: np.ndarray, request_id: str) -> dict:
    data = active._request_data(model, scores)
    if request_id not in data["req_names"]:
        raise ValueError(f"request is not one of the 17 feasible requests: {request_id}")
    r = data["req_names"].index(request_id)
    drop_links = np.flatnonzero(data["link_req"] == r)
    if not len(drop_links):
        raise AssertionError("dropped request has no links")
    # The state alphabet retains inert bit positions to reuse the proven
    # transition kernels. No first/revisit action can set any dropped link.
    data["local_bit"][:, drop_links] = -1
    data["req_need"][r] = 0
    data["req_start"][r] = 0
    request = model.scorer.requests[request_id]
    data["request_reward"] -= float(request.completion_reward)
    data["drop_id"] = request_id
    data["drop_deadline"] = int(request.deadline_utc.timestamp())
    data["drop_miss_penalty"] = float(request.miss_penalty)
    (data["partial_ptr"], data["partial_end"], data["partial_tile"],
     data["partial_link"], data["partial_start"]) = (
        active._weather_interruption_arcs(
            model, data["local_bit"], data["tile_links"],
            data["tile_link_count"],
        )
    )
    return data


def solve_drop(model: PracticeModel, scores: np.ndarray,
               programs: np.ndarray, order: list[int], request_id: str):
    data = drop_data(model, scores, request_id)
    nstates = int(data["offsets"][-1])
    layers = len(order) + 1
    parent_source = np.full((layers, nstates), -1, dtype=np.int32)
    parent_action = np.zeros((layers, nstates), dtype=np.uint16)
    current = np.full(nstates, -np.inf, dtype=np.float64)
    current[0] = 0.0
    completed = np.uint64(0)
    all_mask = np.uint64((1 << len(model.tiles)) - 1)
    for k in range(layers):
        active._close_layer(
            current, parent_source[k], parent_action[k],
            data["offsets"], data["active_count"], data["epochs"],
            data["next_deadline"], data["active_global"],
            data["local_bit"], data["local_global"],
            data["req_deadline"], data["req_mask"], data["req_need"],
            model.actionable, all_mask ^ completed, data["ptr"],
            data["arc_end"], data["arc_tile"], data["arc_link"],
            data["partial_ptr"], data["partial_end"],
            data["partial_tile"], data["partial_link"], completed,
        )
        if k == len(order):
            break
        i = order[k]
        following = np.full(nstates, -np.inf, dtype=np.float64)
        starts = np.flatnonzero(np.isfinite(scores[i])).astype(np.int32)
        active._advance_first(
            current, following, parent_source[k + 1], parent_action[k + 1],
            starts, scores[i], int(model.exposure_units[i]),
            data["tile_links"][i], int(data["tile_link_count"][i]),
            data["offsets"], data["active_count"], data["epochs"],
            data["next_deadline"], data["active_global"],
            data["local_bit"], data["local_global"],
            data["req_deadline"], data["req_mask"], data["req_need"],
        )
        current = following
        completed |= np.uint64(1) << np.uint64(i)

    best = -math.inf
    final_index = -1
    miss_applied = False
    for u in range(model.n_units + 1):
        for mask in range(1 << data["active_count"][u]):
            index = int(data["offsets"][u]) + mask
            value = current[index]
            expired = data["epochs"][u] >= data["drop_deadline"]
            adjusted = value - (data["drop_miss_penalty"] if expired else 0.0)
            if adjusted <= best + 1e-9:
                continue
            if active._terminal_ok(
                u, mask, data["epochs"], data["active_count"],
                data["local_global"], data["req_start"],
                data["req_deadline"], data["req_mask"], data["req_need"],
            ):
                best = float(adjusted)
                final_index = index
                miss_applied = bool(expired)
    if final_index < 0:
        raise ValueError("fixed first order cannot complete remaining requests")

    path = []
    partial_flags = []
    k = len(order)
    index = final_index
    optional_count = 0
    partial_count = 0
    while k or index != 0:
        source = int(parent_source[k, index])
        if source < 0:
            raise RuntimeError("missing drop-one DP backpointer")
        action = int(parent_action[k, index])
        u = int(data["state_time"][source])
        if action == active.WAIT_ACTION:
            pass
        elif action < active.PARTIAL_BASE:
            code = action - active.OPTIONAL_BASE
            i, link = divmod(code, active.LINKS_PER_TILE_CODE)
            request = data["tag_names"][int(data["link_req"][link])]
            path.append((u, i, request, "DARK", False))
            partial_flags.append(False)
            optional_count += 1
        elif action < active.FIRST_ACTION:
            code = action - active.PARTIAL_BASE
            i, tag_code = divmod(code, active.LINKS_PER_TILE_CODE)
            link = tag_code - 1
            request = (
                "" if link < 0
                else data["tag_names"][int(data["link_req"][link])]
            )
            path.append((u, i, request, "DARK", False))
            partial_flags.append(True)
            partial_count += 1
        else:
            if k == 0:
                raise RuntimeError("first-event pointer at layer zero")
            link = action - active.FIRST_ACTION - 1
            request = (
                "" if link < 0
                else data["tag_names"][int(data["link_req"][link])]
            )
            i = order[k - 1]
            path.append((
                u, i, request, PROGRAMS[int(programs[i, u])], True,
            ))
            partial_flags.append(False)
            k -= 1
        index = source
    path.reverse()
    partial_flags.reverse()
    return path, partial_flags, best, optional_count, partial_count, data, miss_applied


def _worker_init(project_root: str, orders: dict[str, list[str]]) -> None:
    global MODEL, SCORES, PROGRAM_IDS, ORDERS
    root = Path(project_root)
    MODEL = PracticeModel(
        root / "scenarios" / "dev-reference",
        root / "results" / "practice_reference.csv",
    )
    SCORES, PROGRAM_IDS = score_table(MODEL)
    ORDERS = {
        name: [MODEL.tile_index[tile] for tile in order_names]
        for name, order_names in orders.items()
    }


def _evaluate(order_name: str, request_id: str, out_dir: str) -> dict:
    started = time.monotonic()
    (path, partial_flags, predicted, optional_count, partial_count,
     data, miss_applied) = solve_drop(
        MODEL, SCORES, PROGRAM_IDS, ORDERS[order_name], request_id,
    )
    destination = Path(out_dir) / order_name / request_id / "decisions.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write(MODEL, destination, path)
    report = MODEL.authoritative_score(destination)
    scored_observations = [
        action for action in report["actions"] if action["action"] == "observe"
    ]
    if len(scored_observations) != len(partial_flags) or any(
        action["penalty"] != 0.0 or action["outcome"] !=
        ("weather_interrupted" if partial else "completed")
        for action, partial in zip(scored_observations, partial_flags)
    ):
        raise AssertionError("official action outcomes disagree with drop-one DP")
    statuses = {item["request_id"]: item for item in report["requests"]}
    if statuses[request_id]["status"] == "completed" or any(
        statuses[r]["status"] != "completed"
        for r in data["req_names"] if r != request_id
    ):
        raise AssertionError("scorer request awards disagree with drop branch")
    if len(report["completion"]["completed_tiles"]) != 64:
        raise AssertionError("drop branch does not complete all tiles")
    if bool(statuses[request_id]["penalty"]) != miss_applied:
        raise AssertionError("scorer miss penalty disagrees with terminal DP")
    if abs(report["score"]["total"] - predicted - data["request_reward"]) > 1e-5:
        raise AssertionError("scorer total disagrees with drop-one DP")
    return {
        "source_order": order_name,
        "dropped_request": request_id,
        "score": report["score"]["total"],
        "science": report["score"]["base_science"] + report["score"]["program_bonus"],
        "request_reward": report["score"]["request_reward"],
        "request_miss_penalty": report["score"]["penalties"].get("request_miss", 0.0),
        "avoidable_wait": report["score"]["penalties"].get("avoidable_wait", 0.0),
        "dropped_status": statuses[request_id]["status"],
        "optional_revisits": optional_count,
        "weather_interruptions": partial_count,
        "decision_file": str(destination),
        "runtime_seconds": time.monotonic() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--order-json", type=Path, nargs="+", required=True)
    parser.add_argument("--out-dir", type=Path,
                        default=ROOT / "runs" / "practice_drop_one")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    order_data = {
        path.stem: json.loads(path.read_text()) for path in args.order_json
    }
    if len(order_data) != len(args.order_json):
        raise ValueError("order JSON basenames must be unique")
    order_names = {
        name: data["first_order"] for name, data in order_data.items()
    }
    if any(len(names) != 64 or len(set(names)) != 64
           for names in order_names.values()):
        raise ValueError("each order JSON must contain 64 unique first visits")
    scorer = ChallengeScorer.from_files(
        args.project_root / "scenarios" / "dev-reference"
    )
    request_ids = sorted(set(scorer.requests) - {"RQ0015"})
    if args.only:
        request_ids = [request for request in args.only
                       if request in request_ids]
    started = time.monotonic()
    results = []
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(
        max_workers=args.workers, initializer=_worker_init,
        initargs=(str(args.project_root.resolve()), order_names),
    ) as pool:
        future_map = {
            pool.submit(_evaluate, name, request, str(args.out_dir.resolve())):
            (name, request)
            for name in order_names for request in request_ids
        }
        for future in as_completed(future_map):
            result = future.result()
            results.append(result)
            print(json.dumps(result, sort_keys=True), flush=True)
    results.sort(key=lambda row: (row["source_order"], row["dropped_request"]))
    output = {
        "scope": "public dev-reference; exact DP conditional on each supplied 64-tile first order and one request never tagged (a subfamily of all missed-request paths)",
        "baseline_scores": {
            name: data.get("score") for name, data in order_data.items()
        },
        "order_count": len(order_names),
        "request_count": len(results),
        "best": max(results, key=lambda row: row["score"]),
        "results": results,
        "runtime_seconds": time.monotonic() - started,
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"best": output["best"],
                      "runtime_seconds": output["runtime_seconds"]},
                     sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
