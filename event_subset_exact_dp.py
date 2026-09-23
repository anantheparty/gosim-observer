#!/usr/bin/env python3
"""Exact event-level LNS for k selected first-visit tiles on dev-reference.

All nonselected first completions and one sufficient set of their request
witnesses stay at the incumbent's exact 150-second times.  Every selected
tile's first completion, request-labeled revisit, and legal weather partial
may move anywhere in the season.  Other legal tagged revisits and weather
partials remain optional fillers.  The state (time, selected completion mask,
active request visit mask) optimizes exact waiting OR, science, and all 17
requests.  This is an exact restricted neighborhood, then officially replayed.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from numba import njit

import bounds_public as geometry
import sequence_active_requests_dp as active
from multistart_large_neighborhood import Oracle, REFERENCE, SCENARIO
from practice_lns import PracticeModel
from sequence_block_dp import _write
from sequence_dp import PROGRAMS


WAIT = 0
OPTIONAL_BASE = 1
PARTIAL_BASE = 2048
FIRST_BASE = 4096
FIXED = 8192
CODE_WIDTH = 32


def _unit(model: PracticeModel, instant: str) -> int:
    epoch = datetime.fromisoformat(instant.replace("Z", "+00:00")).timestamp()
    u = int(np.searchsorted(model.instants, epoch, side="left"))
    if u >= model.n_units or abs(model.instants[u] - epoch) > 1e-6:
        raise AssertionError("action instant off public 150-second grid")
    return u


def _core_events(model: PracticeModel, path: Path):
    """Reduce incumbent to all 64 first successes plus enough request tags."""
    report = model.authoritative_score(path)
    actions = [a for a in report["actions"] if a["action"] == "observe"]
    first_index = {}
    tagged = defaultdict(dict)
    for index, action in enumerate(actions):
        if action["outcome"] != "completed":
            continue
        i = model.tile_index[action["tile_id"]]
        first_index.setdefault(i, index)
        rid = action["request_id"]
        if rid and rid != "RQ0015":
            tagged[rid].setdefault(i, index)
    if len(first_index) != 64:
        raise AssertionError("incumbent does not complete 64 tiles")
    chosen = set(first_index.values())
    for rid, request in model.scorer.requests.items():
        if rid == "RQ0015":
            continue
        available = tagged[rid]
        eligible = [
            (index, i) for i, index in available.items()
            if model.tile_ids[i] in model.scorer.request_tiles[rid]
        ]
        eligible.sort()
        if len(eligible) < request.required_tile_count:
            raise AssertionError(f"incumbent lacks {rid} witness")
        chosen.update(index for index, _ in eligible[:request.required_tile_count])
    events = []
    first_set = set(first_index.values())
    for index in sorted(chosen):
        a = actions[index]
        start = _unit(model, a["start_utc"])
        end = start + int(a["elapsed_seconds"]) // 150
        events.append({
            "start": start, "end": end,
            "tile": model.tile_index[a["tile_id"]],
            "request": a["request_id"],
            "first": index in first_set,
            "program": a["program"],
        })
    return events, report


def _fixed_arrays(model: PracticeModel, data: dict, events: list[dict], selected: list[int]):
    n = model.n_units
    selected_set = set(selected)
    fixed = [e for e in events if e["tile"] not in selected_set]
    fixed_end = np.full(n + 1, -1, dtype=np.int32)
    fixed_tile = np.full(n + 1, -1, dtype=np.int16)
    fixed_link = np.full(n + 1, -1, dtype=np.int8)
    fixed_first = np.zeros(n + 1, dtype=np.uint8)
    fixed_gain = np.zeros(n + 1, dtype=np.float64)
    occupied = np.zeros(n + 1, dtype=np.int32)
    complete_at = np.zeros(n + 1, dtype=np.uint64)
    for e in fixed:
        u, v, i = e["start"], e["end"], e["tile"]
        if fixed_end[u] >= 0:
            raise AssertionError("two mandatory events start simultaneously")
        if np.any(occupied[u:v]):
            raise AssertionError("fixed mandatory events overlap")
        fixed_end[u] = v
        fixed_tile[u] = i
        fixed_first[u] = e["first"]
        fixed_gain[u] = float(model.scorer.tile_values[model.tile_ids[i]]) * 0.0
        occupied[u:v] = 1
        if e["first"]:
            complete_at[v] |= np.uint64(1) << np.uint64(i)
        if e["request"]:
            matches = [
                int(data["tile_links"][i, j])
                for j in range(int(data["tile_link_count"][i]))
                if data["tag_names"][int(data["link_req"][int(data["tile_links"][i, j])])] == e["request"]
            ]
            if len(matches) != 1:
                raise AssertionError("mandatory request link missing")
            fixed_link[u] = matches[0]
    occupied_prefix = np.zeros(n + 2, dtype=np.int32)
    np.cumsum(occupied, out=occupied_prefix[1:])
    done_fixed = np.bitwise_or.accumulate(complete_at)
    last_fixed_end = max((e["end"] for e in fixed), default=0)
    return fixed, fixed_end, fixed_tile, fixed_link, fixed_first, fixed_gain, occupied_prefix, done_fixed, last_fixed_end


@njit(cache=True)
def _solve_graph(
    dp, parent_source, parent_action,
    nstates, selected, selected_global,
    scores, exposure_units,
    fixed_end, fixed_tile, fixed_link, fixed_first, fixed_gain,
    occupied_prefix, done_fixed,
    actionable, offsets, active_count, epochs, next_deadline,
    active_global, local_bit, local_global,
    req_deadline, req_mask, req_need,
    tile_links, tile_link_count,
    ptr, arc_end, arc_tile, arc_link,
    partial_ptr, partial_end, partial_tile, partial_link,
    all_tiles_mask,
):
    n = len(actionable)
    nsub = len(selected_global)
    for u in range(n):
        fixed_v = fixed_end[u]
        boundary = (u // geometry.POINTS_PER_SLOT + 1) * geometry.POINTS_PER_SLOT
        free_wait = fixed_v < 0 and occupied_prefix[boundary] == occupied_prefix[u]
        for subset in range(nsub):
            global_done = done_fixed[u] | selected_global[subset]
            missing = all_tiles_mask ^ global_done
            row = subset * nstates + offsets[u]
            for mask in range(1 << active_count[u]):
                source = row + mask
                value = dp[source]
                if not np.isfinite(value):
                    continue
                if fixed_v >= 0:
                    mapped = active._map_mask(
                        u, fixed_v, mask, int(fixed_link[u]),
                        epochs, next_deadline, active_global, local_bit,
                        local_global, active_count, req_deadline,
                        req_mask, req_need,
                    )
                    if mapped >= 0:
                        target = subset * nstates + offsets[fixed_v] + mapped
                        proposal = value + fixed_gain[u]
                        if proposal > dp[target] + 1e-9:
                            dp[target] = proposal
                            parent_source[target] = source
                            parent_action[target] = FIXED
                    continue
                if free_wait:
                    mapped = active._map_mask(
                        u, boundary, mask, -1,
                        epochs, next_deadline, active_global, local_bit,
                        local_global, active_count, req_deadline,
                        req_mask, req_need,
                    )
                    if mapped >= 0:
                        charge = (
                            (boundary - u) * geometry.UNIT_SECONDS * 0.001
                            if actionable[u] & missing else 0.0
                        )
                        target = subset * nstates + offsets[boundary] + mapped
                        proposal = value - charge
                        if proposal > dp[target] + 1e-9:
                            dp[target] = proposal
                            parent_source[target] = source
                            parent_action[target] = WAIT
                for a in range(ptr[u], ptr[u + 1]):
                    i = arc_tile[a]
                    if not (global_done & (np.uint64(1) << np.uint64(i))):
                        continue
                    v = arc_end[a]
                    if occupied_prefix[v] != occupied_prefix[u]:
                        continue
                    link = arc_link[a]
                    mapped = active._map_mask(
                        u, v, mask, int(link),
                        epochs, next_deadline, active_global, local_bit,
                        local_global, active_count, req_deadline,
                        req_mask, req_need,
                    )
                    if mapped < 0:
                        continue
                    target = subset * nstates + offsets[v] + mapped
                    if value > dp[target] + 1e-9:
                        dp[target] = value
                        parent_source[target] = source
                        parent_action[target] = OPTIONAL_BASE + i * CODE_WIDTH + link
                for a in range(partial_ptr[u], partial_ptr[u + 1]):
                    i = partial_tile[a]
                    v = partial_end[a]
                    if occupied_prefix[v] != occupied_prefix[u]:
                        continue
                    link = -1
                    if global_done & (np.uint64(1) << np.uint64(i)):
                        link = partial_link[a]
                        if link < 0:
                            continue
                    mapped = active._map_mask(
                        u, v, mask, -1,
                        epochs, next_deadline, active_global, local_bit,
                        local_global, active_count, req_deadline,
                        req_mask, req_need,
                    )
                    if mapped < 0:
                        continue
                    target = subset * nstates + offsets[v] + mapped
                    if value > dp[target] + 1e-9:
                        dp[target] = value
                        parent_source[target] = source
                        parent_action[target] = PARTIAL_BASE + i * CODE_WIDTH + link + 1
                for j in range(len(selected)):
                    if subset & (1 << j):
                        continue
                    i = selected[j]
                    gain = scores[i, u]
                    if not np.isfinite(gain):
                        continue
                    v = u + exposure_units[i]
                    if occupied_prefix[v] != occupied_prefix[u]:
                        continue
                    following_subset = subset | (1 << j)
                    for choice in range(tile_link_count[i] + 1):
                        link = -1 if choice == 0 else int(tile_links[i, choice - 1])
                        if link >= 0 and local_bit[u, link] == -1:
                            continue
                        mapped = active._map_mask(
                            u, v, mask, link,
                            epochs, next_deadline, active_global, local_bit,
                            local_global, active_count, req_deadline,
                            req_mask, req_need,
                        )
                        if mapped < 0:
                            continue
                        target = following_subset * nstates + offsets[v] + mapped
                        proposal = value + gain
                        if proposal > dp[target] + 1e-9:
                            dp[target] = proposal
                            parent_source[target] = source
                            parent_action[target] = FIRST_BASE + i * CODE_WIDTH + link + 1


def solve(model: PracticeModel, oracle: Oracle, incumbent: Path, selected: list[int], out: Path):
    if len(set(selected)) != len(selected) or not 1 <= len(selected) <= 10:
        raise ValueError("selected tile set must contain 1 to 10 distinct tiles")
    data = oracle.data
    core, original = _core_events(model, incumbent)
    (
        fixed, fixed_end, fixed_tile, fixed_link, fixed_first, fixed_gain,
        occupied_prefix, done_fixed, last_fixed_end,
    ) = _fixed_arrays(model, data, core, selected)
    for event in fixed:
        if event["first"]:
            fixed_gain[event["start"]] = float(oracle.scores[event["tile"], event["start"]])
    nstates = int(data["offsets"][-1])
    total = nstates * (1 << len(selected))
    if total > 900_000_000:
        raise ValueError("dense selected-state table exceeds 900 million entries")
    dp = np.full(total, -np.inf, dtype=np.float64)
    parent_source = np.full(total, -1, dtype=np.int32)
    parent_action = np.zeros(total, dtype=np.uint16)
    dp[0] = 0.0
    selected_global = np.zeros(1 << len(selected), dtype=np.uint64)
    for subset in range(1, len(selected_global)):
        bit = subset & -subset
        j = bit.bit_length() - 1
        selected_global[subset] = selected_global[subset ^ bit] | (np.uint64(1) << np.uint64(selected[j]))
    all_mask = np.uint64((1 << len(model.tiles)) - 1)
    start = time.monotonic()
    _solve_graph(
        dp, parent_source, parent_action,
        nstates, np.asarray(selected, dtype=np.int16), selected_global,
        oracle.scores, model.exposure_units,
        fixed_end, fixed_tile, fixed_link, fixed_first, fixed_gain,
        occupied_prefix, done_fixed,
        model.actionable, data["offsets"], data["active_count"],
        data["epochs"], data["next_deadline"], data["active_global"],
        data["local_bit"], data["local_global"],
        data["req_deadline"], data["req_mask"], data["req_need"],
        data["tile_links"], data["tile_link_count"],
        data["ptr"], data["arc_end"], data["arc_tile"], data["arc_link"],
        data["partial_ptr"], data["partial_end"], data["partial_tile"],
        data["partial_link"], all_mask,
    )
    search_seconds = time.monotonic() - start
    final_subset = (1 << len(selected)) - 1
    best = -math.inf
    final_index = -1
    for u in range(last_fixed_end, model.n_units + 1):
        for mask in range(1 << int(data["active_count"][u])):
            index = final_subset * nstates + int(data["offsets"][u]) + mask
            value = dp[index]
            if value > best + 1e-9 and active._terminal_ok(
                u, mask, data["epochs"], data["active_count"],
                data["local_global"], data["req_start"],
                data["req_deadline"], data["req_mask"], data["req_need"],
            ):
                best, final_index = float(value), index
    if final_index < 0:
        return {"status": "INFEASIBLE", "selected_tiles": [model.tile_ids[i] for i in selected],
                "states": total, "search_seconds": search_seconds}
    path = []
    partial_flags = []
    index = final_index
    while index:
        source = int(parent_source[index])
        if source < 0:
            raise RuntimeError("broken event-level DP predecessor")
        action = int(parent_action[index])
        u = int(data["state_time"][source % nstates])
        if action == WAIT:
            pass
        elif action < PARTIAL_BASE:
            i, link = divmod(action - OPTIONAL_BASE, CODE_WIDTH)
            rid = data["tag_names"][int(data["link_req"][link])]
            path.append((u, i, rid, "DARK", False))
            partial_flags.append(False)
        elif action < FIRST_BASE:
            i, tag_code = divmod(action - PARTIAL_BASE, CODE_WIDTH)
            link = tag_code - 1
            rid = "" if link < 0 else data["tag_names"][int(data["link_req"][link])]
            path.append((u, i, rid, "DARK", False))
            partial_flags.append(True)
        elif action < FIXED:
            i, tag_code = divmod(action - FIRST_BASE, CODE_WIDTH)
            link = tag_code - 1
            rid = "" if link < 0 else data["tag_names"][int(data["link_req"][link])]
            path.append((u, i, rid, PROGRAMS[int(oracle.programs[i, u])], True))
            partial_flags.append(False)
        else:
            i = int(fixed_tile[u])
            link = int(fixed_link[u])
            rid = "" if link < 0 else data["tag_names"][int(data["link_req"][link])]
            path.append((u, i, rid, PROGRAMS[int(oracle.programs[i, u])], bool(fixed_first[u])))
            partial_flags.append(False)
        index = source
    path.reverse()
    partial_flags.reverse()
    _write(model, out, path)
    report = model.authoritative_score(out)
    observations = [a for a in report["actions"] if a["action"] == "observe"]
    if len(observations) != len(partial_flags) or any(
        a["outcome"] != ("weather_interrupted" if flag else "completed") or a["penalty"] != 0.0
        for a, flag in zip(observations, partial_flags)
    ):
        raise AssertionError("event-level DP action does not replay as modeled")
    if report["score"]["request_reward"] != data["request_reward"]:
        raise AssertionError("event-level DP lost a feasible request")
    if len(report["completion"]["completed_tiles"]) != 64:
        raise AssertionError("event-level DP lost a tile")
    if abs(report["score"]["total"] - best - data["request_reward"]) > 1e-5:
        raise AssertionError("event-level DP objective differs from scorer")
    return {
        "status": "OPTIMAL_RESTRICTED", "selected_tiles": [model.tile_ids[i] for i in selected],
        "fixed_events": len(fixed), "released_core_events": len(core) - len(fixed),
        "states": total, "search_seconds": search_seconds,
        "original_total": original["score"]["total"],
        "candidate_total": report["score"]["total"],
        "improvement": report["score"]["total"] - original["score"]["total"],
        "score": report["score"], "observations": len(observations),
        "weather_interruptions": sum(partial_flags), "output": str(out),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incumbent", type=Path, default=Path("results/practice_best.csv"))
    parser.add_argument("--tiles", nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    model = PracticeModel(SCENARIO, REFERENCE)
    oracle = Oracle(model)
    selected = [model.tile_index[t] for t in args.tiles]
    result = solve(model, oracle, args.incumbent, selected, args.out)
    args.out.with_suffix(".json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
