#!/usr/bin/env python3
"""Request-preserving LP→baseline crossover guided by exact wait-OR closure.

Treat the high-science LP path as incumbent and each earlier baseline first
completion as a binary advancement option.  On the fixed LP wait timeline, a
charged wait edge disappears only when every actionable unfinished tile at
that edge is advanced past it.  The resulting AND rewards minus tile science
losses form a maximum-weight closure solvable by one min-cut.  The chosen tile
group is transferred jointly in first-visit order; full timing and request
visits are then reoptimized by the active-request DP and officially replayed.
The closure is a construction heuristic, never a full-problem upper bound.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

import sequence_active_requests_dp as active
from multistart_large_neighborhood import Oracle, REFERENCE, SCENARIO
from practice_lns import PracticeModel


def timeline(model: PracticeModel, path: Path):
    report = model.authoritative_score(path)
    first_finish = np.full(len(model.tiles), -1, dtype=np.int32)
    first_science = np.zeros(len(model.tiles), dtype=np.float64)
    waits = []
    cursor = 0
    done = 0
    for action in report["actions"]:
        if action["action"] != "observe":
            continue
        epoch = datetime.fromisoformat(action["start_utc"].replace("Z", "+00:00")).timestamp()
        start = int(np.searchsorted(model.instants, epoch))
        if start >= model.n_units or abs(model.instants[start] - epoch) > 1e-6:
            raise AssertionError("off-grid action")
        while cursor < start:
            boundary = (cursor // 6 + 1) * 6
            if boundary > start:
                raise AssertionError("unreachable action start")
            blockers = int(model.actionable[cursor]) & ~done
            if blockers:
                waits.append((cursor, blockers, (boundary - cursor) * 0.15))
            cursor = boundary
        i = model.tile_index[action["tile_id"]]
        cursor = start + int(action["elapsed_seconds"]) // 150
        if action["outcome"] == "completed" and first_finish[i] < 0:
            first_finish[i] = cursor
            first_science[i] = action["base_science_score"] + action["program_bonus_score"]
            done |= 1 << i
    if np.any(first_finish < 0):
        raise AssertionError("path does not complete all tiles")
    return first_finish, first_science, waits, report


def max_closure(options: dict[int, float], rewards: dict[int, float]):
    """Maximize sum of selected wait rewards minus selected tile science cost."""
    groups = list(rewards)
    sink = 65 + len(groups)
    graph = [[] for _ in range(sink + 1)]
    def add(u, v, cap):
        graph[u].append([v, float(cap), len(graph[v])])
        graph[v].append([u, 0.0, len(graph[u]) - 1])
    for i, loss in options.items():
        if loss >= 0:
            add(i + 1, sink, loss)
        else:
            add(0, i + 1, -loss)
    for j, mask in enumerate(groups):
        node = 65 + j
        add(0, node, rewards[mask])
        while mask:
            bit = mask & -mask
            i = bit.bit_length() - 1
            add(node, i + 1, 1e9)
            mask ^= bit
    flow = 0.0
    while True:
        level = [-1] * len(graph)
        level[0] = 0
        queue = [0]
        for u in queue:
            for v, cap, _ in graph[u]:
                if cap > 1e-9 and level[v] < 0:
                    level[v] = level[u] + 1
                    queue.append(v)
        if level[sink] < 0:
            break
        ptr = [0] * len(graph)
        def dfs(u, sent):
            if u == sink:
                return sent
            while ptr[u] < len(graph[u]):
                edge = graph[u][ptr[u]]
                v, cap, rev = edge
                if cap > 1e-9 and level[v] == level[u] + 1:
                    pushed = dfs(v, min(sent, cap))
                    if pushed > 1e-9:
                        edge[1] -= pushed
                        graph[v][rev][1] += pushed
                        return pushed
                ptr[u] += 1
            return 0.0
        while True:
            sent = dfs(0, 1e12)
            if sent <= 1e-9:
                break
            flow += sent
    reachable = {0}
    queue = [0]
    for u in queue:
        for v, cap, _ in graph[u]:
            if cap > 1e-9 and v not in reachable:
                reachable.add(v)
                queue.append(v)
    selected = {i for i in options if i + 1 in reachable}
    gained_wait = sum(v for mask, v in rewards.items() if mask and (mask & sum(1 << i for i in selected)) == mask)
    science_loss = sum(options[i] for i in selected)
    return selected, gained_wait - science_loss, gained_wait, science_loss


def transfer(base: list[int], donor: list[int], selected: set[int]) -> list[int]:
    donor_rank = {tile: rank for rank, tile in enumerate(donor)}
    result = [tile for tile in base if tile not in selected]
    for tile in sorted(selected, key=lambda i: donor_rank[i]):
        result.insert(min(len(result), donor_rank[tile]), tile)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--high-science-core", type=Path, required=True)
    parser.add_argument("--high-science-path", type=Path, required=True)
    parser.add_argument("--low-wait-core", type=Path, required=True)
    parser.add_argument("--low-wait-path", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    model = PracticeModel(SCENARIO, REFERENCE)
    high_finish, high_science, waits, high_report = timeline(model, args.high_science_path)
    low_finish, low_science, _, low_report = timeline(model, args.low_wait_path)
    high_order = active._first_order(model, args.high_science_core)
    low_order = active._first_order(model, args.low_wait_core)
    options = {
        i: float(high_science[i] - low_science[i])
        for i in range(len(model.tiles)) if low_finish[i] < high_finish[i]
    }
    rewards: defaultdict[int, float] = defaultdict(float)
    for u, blockers, cost in waits:
        bits = blockers
        valid = True
        while bits:
            bit = bits & -bits
            i = bit.bit_length() - 1
            if i not in options or low_finish[i] > u:
                valid = False
                break
            bits ^= bit
        if valid:
            rewards[blockers] += cost
    selected, surrogate, wait_gain, science_loss = max_closure(options, rewards)
    candidate = transfer(high_order, low_order, selected)
    oracle = Oracle(model)
    predicted = oracle.value(candidate)
    report = None
    if np.isfinite(predicted):
        report = oracle.write_and_verify(candidate, args.out / "candidate.csv")
    summary = {
        "high_score": high_report["score"]["total"],
        "low_score": low_report["score"]["total"],
        "eligible_advancements": len(options),
        "charged_wait_edges": len(waits),
        "reward_masks": len(rewards),
        "selected_tiles": [model.tile_ids[i] for i in sorted(selected)],
        "selected_count": len(selected),
        "surrogate_gain": surrogate,
        "surrogate_wait_saved": wait_gain,
        "surrogate_science_lost": science_loss,
        "candidate_predicted": predicted if np.isfinite(predicted) else None,
        "first_infeasible_event": oracle.last_failure,
        "candidate_score": report["score"] if report else None,
        "candidate_order": [model.tile_ids[i] for i in candidate],
    }
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
