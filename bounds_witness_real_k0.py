#!/usr/bin/env python3
"""Audited full-arc K0 request-witness automaton for dev-reference.

This is an integration pilot. K=0 removes all key-tile reward and avoidable
wait costs; the already-known all-17 feasible schedule predicts a zero DP
value at theta=0. Do not present its conditional number as a new global bound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
from numba import njit

import bounds_practice_projection as projection
import bounds_request_projection_k10 as original
import bounds_request_projection_ring as ring
from bounds_witness_window_automaton import (
    WitnessLink, active_ids, mask_from_global, mask_to_global, transition,
    terminal_allowed,
)
from challenge.scoring_core import ChallengeScorer, load_decisions


ROOT = Path(__file__).resolve().parent
BEST = ROOT / "results" / "practice_best.csv"
NEG_INF = -(10**15)


def _links(data: dict, inputs: dict, branch: int) -> tuple[WitnessLink, ...]:
    selected = inputs["branches"][branch]
    links = []
    for request_id, tiles in selected.items():
        request = data["scorer"].requests[request_id]
        a = int(np.searchsorted(inputs["instants"],
                                request.available_from_utc.timestamp(), side="left"))
        d = int(np.searchsorted(inputs["instants"],
                                request.deadline_utc.timestamp(), side="left"))
        for tile in tiles:
            if tile not in data["scorer"].request_tiles[request_id]:
                raise AssertionError("selected request/tile link not in scorer")
            if data["scorer"].request_tiles[request_id][tile] != 1:
                raise AssertionError("pilot expects exactly one visit per link")
            links.append(WitnessLink(request_id, tile, a, d))
    if len(links) != 28:
        raise AssertionError(f"expected 28 selected request links, got {len(links)}")
    return tuple(links)


def _regions(data: dict, links: tuple[WitnessLink, ...]) -> dict:
    n = data["n"]
    events = np.array(sorted({0, n} | {link.available_unit for link in links} |
                             {link.deadline_unit for link in links}), dtype=np.int32)
    if events[0] != 0 or events[-1] != n:
        raise AssertionError("request windows extend beyond the complete grid")
    region = np.searchsorted(events, np.arange(n + 1), side="right") - 1
    region_count = len(events)
    if region_count > 100:
        raise AssertionError("unexpectedly many request endpoints")
    tile_ids = data["tile_ids"]
    tile_index = {tile: i for i, tile in enumerate(tile_ids)}
    active = [active_ids(links, int(event)) for event in events]
    max_active = max(map(len, active))
    if max_active > 8:
        raise AssertionError("pilot's 8-bit witness state is too small")
    states = 1 << max_active
    maps = np.full((region_count, region_count, states), -1, dtype=np.int16)
    credit_by_tile = np.zeros((region_count, len(tile_ids)), dtype=np.uint16)
    counts = np.array([len(row) for row in active], dtype=np.uint8)
    for r, ids in enumerate(active):
        for bit, link_id in enumerate(ids):
            credit_by_tile[r, tile_index[links[link_id].tile_id]] |= np.uint16(1 << bit)
        for s in range(r, region_count):
            expired = sum(1 << i for i, link in enumerate(links)
                          if int(events[r]) < link.deadline_unit <= int(events[s]))
            for local_mask in range(1 << len(ids)):
                done = mask_to_global(ids, local_mask)
                if expired & ~done:
                    continue
                maps[r, s, local_mask] = mask_from_global(active[s], done)
    starts = np.repeat(np.arange(n, dtype=np.int32), np.diff(data["complete_ptr"]))
    credit_for_arc = credit_by_tile[region[starts], data["complete_tile"]]
    illegal_credit = int(np.count_nonzero((credit_for_arc != 0) &
                                          ~data["complete_tagged"]))
    if illegal_credit:
        raise AssertionError(f"{illegal_credit} witness candidate arcs are not taggable")
    histogram = Counter(int(counts[int(region[u])]) for u in range(n))
    return {"events": events, "region": region.astype(np.int16),
            "maps": maps, "credit_by_tile": credit_by_tile,
            "active_count": counts, "max_active": max_active,
            "states": states, "histogram": dict(sorted(histogram.items())),
            "weighted_state_rows": sum((1 << count) * cells
                                       for count, cells in histogram.items()),
            "illegal_credit_arc_count": illegal_credit,
            "region_count": region_count}


def _audit_region_maps(links: tuple[WitnessLink, ...], compiled: dict,
                       sample_count: int = 2000) -> dict:
    rng = np.random.default_rng(260925)
    region = compiled["region"]
    n = len(region) - 1
    checked = 0
    for _ in range(sample_count):
        u = int(rng.integers(0, n))
        v = int(rng.integers(u + 1, min(n, u + 9) + 1))
        active = active_ids(links, u)
        mask = int(rng.integers(0, 1 << len(active)))
        tile = None if rng.integers(0, 5) == 0 else links[int(rng.integers(0, len(links)))].tile_id
        expected = transition(links, u, v, mask, tile)
        r, s = int(region[u]), int(region[v])
        got = set()
        candidates = [0]
        if tile is not None:
            candidates.extend(1 << bit for bit, i in enumerate(active)
                              if links[i].tile_id == tile)
        for credit in candidates:
            next_mask = int(compiled["maps"][r, s, mask | credit])
            if next_mask >= 0:
                got.add(next_mask)
        if got != set(expected):
            raise AssertionError(f"compiled witness map differs at {u}->{v}, {mask}, {tile}")
        checked += 1
    return {"random_arc_state_transition_checks": checked, "mismatches": 0}


@njit(cache=True)
def _k0_witness_dp(n, complete_ptr, complete_end, complete_tile,
                   complete_tagged, partial_ptr, partial_end, region,
                   active_count, maps, credit_by_tile, latest_available,
                   theta_cents, horizon):
    states = maps.shape[2]
    dp = np.full((horizon, states), NEG_INF, dtype=np.int64)
    rn = region[n]
    full_n = (1 << active_count[rn]) - 1
    if n >= latest_available:
        dp[n % horizon, full_n] = 0
    for u in range(n - 1, -1, -1):
        ru = region[u]
        state_count = 1 << active_count[ru]
        boundary = ((u // projection.POINTS_PER_SLOT) + 1) * projection.POINTS_PER_SLOT
        full_u = state_count - 1
        for mask in range(state_count):
            best = 0 if u >= latest_available and mask == full_u else NEG_INF
            mv = maps[ru, region[boundary], mask]
            if mv >= 0:
                future = dp[boundary % horizon, mv]
                if future > best:
                    best = future
            for j in range(partial_ptr[u], partial_ptr[u + 1]):
                v = partial_end[j]
                mv = maps[ru, region[v], mask]
                if mv >= 0:
                    future = dp[v % horizon, mv]
                    if future > best:
                        best = future
            for j in range(complete_ptr[u], complete_ptr[u + 1]):
                v = complete_end[j]
                tile = complete_tile[j]
                toll = 0 if complete_tagged[j] else theta_cents[tile]
                mv = maps[ru, region[v], mask]
                if mv >= 0:
                    future = dp[v % horizon, mv]
                    if future > NEG_INF // 2:
                        candidate = future - toll
                        if candidate > best:
                            best = candidate
                bits = credit_by_tile[ru, tile]
                while bits:
                    bit = bits & (-bits)
                    bits ^= bit
                    mv = maps[ru, region[v], mask | bit]
                    if mv >= 0:
                        future = dp[v % horizon, mv]
                        if future > best:
                            best = future
            dp[u % horizon, mask] = best
    return int(dp[0, 0])


def _external_cents(data: dict, inputs: dict, branch: int) -> int:
    deadlines = inputs["deadlines_by_branch"][branch]
    starts = inputs["arc_starts"]
    total = int(data["prices"].sum())
    for tile_index, tile in enumerate(data["tile_ids"]):
        if tile not in deadlines:
            total += int(data["tile_residual_max"][tile_index])
            continue
        d = np.searchsorted(inputs["instants"], deadlines[tile], side="left")
        mask = (data["complete_tile"] == tile_index) & (starts < d)
        if not np.any(mask):
            raise AssertionError(f"mandatory non-key tile has no first arc: {tile}")
        total += int(np.max(data["complete_reduced"][mask]))
    return total


def _unit_by_timestamp(instants: np.ndarray, moment: str) -> int:
    timestamp = datetime.fromisoformat(moment.replace("Z", "+00:00")).timestamp()
    unit = int(np.searchsorted(instants, timestamp, side="left"))
    if unit >= len(instants) or instants[unit] != timestamp:
        raise AssertionError(f"scorer action not on 150s grid: {moment}")
    return unit


def _check_real_trace(data: dict, inputs: dict, branch: int,
                      links: tuple[WitnessLink, ...], compiled: dict,
                      best_path: Path) -> dict:
    scorer = ChallengeScorer.from_files(original.PRACTICE)
    actions = []
    for decision in load_decisions(best_path, allow_reports=False):
        actions.append(scorer.apply_decision(decision))
    report = scorer.finalize("trace_complete")
    if report["score"]["request_reward"] != 3920.0:
        raise AssertionError("incumbent does not award all 17 feasible requests")
    link_index = {(link.request_id, link.tile_id): i for i, link in enumerate(links)}
    region = compiled["region"]
    current = 0
    state = 0
    done_global = 0
    transition_count = 0
    complete_count = 0
    completed_tagged_count = 0
    partial_count = 0
    witnessed = 0
    for action in actions:
        if not action["start_utc"] or action["elapsed_seconds"] == 0:
            continue
        u = _unit_by_timestamp(inputs["instants"], action["start_utc"])
        if u < current:
            raise AssertionError("scorer actions moved backward")
        while current < u:
            boundary = ((current // projection.POINTS_PER_SLOT) + 1) * projection.POINTS_PER_SLOT
            if boundary > u:
                raise AssertionError("implicit gap cannot be represented by slot waits")
            source_state = state
            choices = transition(links, current, boundary, state, None)
            if len(choices) != 1:
                raise AssertionError("actual implicit wait violates witness deadline")
            state = choices[0]
            if int(compiled["maps"][region[current], region[boundary], source_state]) != state:
                raise AssertionError("compiled implicit-wait transition differs")
            current = boundary
            transition_count += 1
        elapsed = int(action["elapsed_seconds"])
        if elapsed % 150:
            raise AssertionError("action duration leaves the grid")
        v = u + elapsed // 150
        if v > data["n"]:
            raise AssertionError("action ends beyond graph")
        kind = action["action"]
        tile = action["tile_id"] if kind == "observe" else None
        source_state = state
        credited_local = 0
        if kind == "observe" and action["outcome"] == "completed":
            tile_index = data["tile_ids"].index(tile)
            arc_range = range(data["complete_ptr"][u], data["complete_ptr"][u + 1])
            if not any(int(data["complete_tile"][j]) == tile_index and
                       int(data["complete_end"][j]) == v for j in arc_range):
                raise AssertionError(f"completed scorer action absent from graph: {tile}, {u}->{v}")
            complete_count += 1
            if action["request_id"]:
                request = scorer.requests[action["request_id"]]
                if (tile not in scorer.request_tiles[request.request_id]
                        or not (request.available_from_utc.timestamp()
                                <= inputs["instants"][u]
                                < request.deadline_utc.timestamp())):
                    raise AssertionError("scorer-completed tag is not legal at arc start")
                completed_tagged_count += 1
            chosen = link_index.get((action["request_id"], tile))
            if chosen is not None:
                link = links[chosen]
                if not link.available_unit <= u < link.deadline_unit:
                    raise AssertionError("scorer-accepted request tag outside selected window")
                source = active_ids(links, u)
                if chosen not in source:
                    raise AssertionError("selected link absent from active state")
                credited_local = 1 << source.index(chosen)
                credited = mask_to_global(source, state) | (1 << chosen)
                expired = sum(1 << i for i, link in enumerate(links)
                              if u < link.deadline_unit <= v)
                if expired & ~credited:
                    raise AssertionError("real action skipped an incomplete deadline")
                next_state = mask_from_global(active_ids(links, v), credited)
                if next_state not in transition(links, u, v, state, tile):
                    raise AssertionError("real tag choice absent from automaton")
                state = next_state
                if not (done_global & (1 << chosen)):
                    witnessed += 1
                done_global |= 1 << chosen
            else:
                choices = transition(links, u, v, state, None)
                if len(choices) != 1:
                    raise AssertionError("untagged/unselected real action skips deadline")
                state = choices[0]
        elif kind == "observe" and action["outcome"] == "weather_interrupted":
            if not any(int(data["partial_end"][j]) == v
                       for j in range(data["partial_ptr"][u], data["partial_ptr"][u + 1])):
                raise AssertionError("weather interruption absent from graph")
            choices = transition(links, u, v, state, None)
            if len(choices) != 1:
                raise AssertionError("partial action skips witness deadline")
            state = choices[0]
            partial_count += 1
        elif kind == "wait":
            boundary = ((u // projection.POINTS_PER_SLOT) + 1) * projection.POINTS_PER_SLOT
            if v != boundary:
                raise AssertionError("explicit wait differs from graph edge")
            choices = transition(links, u, v, state, None)
            if len(choices) != 1:
                raise AssertionError("explicit wait skips witness deadline")
            state = choices[0]
        else:
            raise AssertionError(f"incumbent action lacks legal projection edge: {kind}/{action['outcome']}")
        if int(compiled["maps"][region[u], region[v], source_state | credited_local]) != state:
            raise AssertionError("compiled scorer-action transition differs")
        current = v
        transition_count += 1
    if not terminal_allowed(links, current, state):
        raise AssertionError("all-awarded scorer trace cannot terminate in automaton")
    if done_global != (1 << len(links)) - 1:
        raise AssertionError("not all selected request links received their true tag")
    return {"decision_sha256": hashlib.sha256(best_path.read_bytes()).hexdigest(),
            "scorer_total": report["score"]["total"],
            "scorer_request_reward": report["score"]["request_reward"],
            "branch": branch,
            "selected_rq0004_tile": inputs["branches"][branch]["RQ0004"][0],
            "legal_graph_transitions": transition_count,
            "completed_actions_in_graph": complete_count,
            "completed_tagged_actions_checked": completed_tagged_count,
            "weather_partial_actions_in_graph": partial_count,
            "distinct_request_links_witnessed": witnessed,
            "terminal_unit": current, "terminal_active_mask": state}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "results" / "practice_witness_real_k0.json")
    args = parser.parse_args()
    started = time.monotonic()
    data, audit = original._load_audited_data(original.PRICE_FILE)
    inputs = original._instance_inputs(data)
    horizon = ring.transition_horizon(data)
    if horizon != 10:
        raise AssertionError("full graph edge span changed")
    rows = []
    for branch in range(2):
        links = _links(data, inputs, branch)
        compiled = _regions(data, links)
        mapping_audit = _audit_region_maps(links, compiled)
        # The actual incumbent satisfies RQ0004 with T00012. The other branch
        # may not map, so audit only the matching branch.
        tagged_rq4 = set()
        scorer_probe = ChallengeScorer.from_files(original.PRACTICE)
        for decision in load_decisions(BEST, allow_reports=False):
            if decision.request_id == "RQ0004":
                action = scorer_probe.apply_decision(decision)
                if action["outcome"] == "completed":
                    tagged_rq4.add(decision.tile_id)
            else:
                scorer_probe.apply_decision(decision)
        selected_tile = inputs["branches"][branch]["RQ0004"][0]
        trace = (_check_real_trace(data, inputs, branch, links, compiled, BEST)
                 if selected_tile in tagged_rq4 else None)
        external = _external_cents(data, inputs, branch)
        for theta in (0, 135):
            theta_vector = np.full(len(data["tile_ids"]), theta, dtype=np.int64)
            dp_started = time.monotonic()
            dp = _k0_witness_dp(
                data["n"], data["complete_ptr"], data["complete_end"],
                data["complete_tile"], data["complete_tagged"],
                data["partial_ptr"], data["partial_end"],
                compiled["region"], compiled["active_count"],
                compiled["maps"], compiled["credit_by_tile"],
                max(link.available_unit for link in links),
                theta_vector, horizon,
            )
            if dp <= NEG_INF // 2:
                raise AssertionError("real all-awarded schedule exists, but K0 DP is infeasible")
            if theta == 0 and dp != 0:
                raise AssertionError("K0 theta=0 must have zero optimum on feasible graph")
            before = external + int(data["request_cents"]) + theta * len(data["tile_ids"])
            after = before + dp
            row = {"branch": branch, "rq0004_tile": selected_tile,
                   "theta_cents": theta, "external_cents": external,
                   "request_cents": int(data["request_cents"]),
                   "theta_constant_cents": theta * len(data["tile_ids"]),
                   "witness_dp_cents": dp,
                   "unconstrained_k0_conditional_upper_cents": before,
                   "witness_k0_conditional_upper_cents": after,
                   "improvement_cents": before-after,
                   "dp_seconds": time.monotonic()-dp_started,
                   "active_link_histogram": compiled["histogram"],
                   "weighted_state_rows": compiled["weighted_state_rows"],
                   "region_count": compiled["region_count"],
                   "max_active_links": compiled["max_active"],
                   "mapping_audit": mapping_audit,
                   "real_trace_audit": trace}
            print(json.dumps({k: v for k, v in row.items()
                              if k not in ("active_link_histogram", "real_trace_audit")}),
                  flush=True)
            rows.append(row)
    payload = {"scope": "public dev-reference, conditional all-17 K0 integration pilot",
               "price_sha256": audit["price_sha256"],
               "decision_sha256": hashlib.sha256(BEST.read_bytes()).hexdigest(),
               "complete_arc_count": data["complete_arc_count"],
               "partial_arc_count": data["partial_arc_count"],
               "capacity_units": data["n"], "ring_horizon": horizon,
               "scalar_audit": audit["scalar_audit"],
               "rows": rows, "runtime_seconds": time.monotonic()-started,
               "note": "This K0 pilot cannot improve the theta=0 capacity bound when a full-request path exists."}
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
