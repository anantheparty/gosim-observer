#!/usr/bin/env python3
"""Fixed-first-order exact DP with all feasible practice requests enforced.

The 64 first-completion tiles retain their input relative order.  Request
labels and revisit witnesses are chosen freely within their published windows.
Completed observations, zero-penalty weather interruptions, and legal waits
are in this graph.
"""

from __future__ import annotations

import argparse
import json
import math
from bisect import bisect_right
from pathlib import Path

import numpy as np
from numba import njit

import bounds_public as geometry
from challenge.scoring_core import load_decisions
from practice_lns import PracticeModel
from sequence_block_dp import _write
from sequence_dp import PROGRAMS, score_table


WAIT_ACTION = 0
FIRST_ACTION = 4096
OPTIONAL_BASE = 1
PARTIAL_BASE = 2048
LINKS_PER_TILE_CODE = 32
MAX_ACTIVE_LINKS = 8


@njit(cache=True)
def _popcount(value: np.uint32) -> int:
    count = 0
    while value:
        value &= value - np.uint32(1)
        count += 1
    return count


@njit(cache=True)
def _map_mask(
    u: int,
    v: int,
    mask: int,
    link: int,
    epochs: np.ndarray,
    next_deadline: np.ndarray,
    active_global: np.ndarray,
    local_bit: np.ndarray,
    local_global: np.ndarray,
    active_count: np.ndarray,
    req_deadline: np.ndarray,
    req_mask: np.ndarray,
    req_need: np.ndarray,
) -> int:
    """Set a completed tag visit, settle crossed deadlines, then relabel bits."""
    if active_global[u] == active_global[v] and next_deadline[u] > epochs[v]:
        if link < 0:
            return mask
        bit = local_bit[u, link]
        if bit == -1:
            return -1
        if bit == -2:
            return mask
        return mask | (1 << bit)

    global_mask = np.uint32(0)
    for b in range(active_count[u]):
        if mask & (1 << b):
            global_mask |= local_global[u, b]
    if link >= 0:
        bit = local_bit[u, link]
        if bit == -1:
            return -1
        if bit >= 0:
            global_mask |= np.uint32(1) << np.uint32(link)

    for r in range(len(req_deadline)):
        if epochs[u] < req_deadline[r] <= epochs[v]:
            if _popcount(global_mask & req_mask[r]) < req_need[r]:
                return -1
    result = 0
    for b in range(active_count[v]):
        if global_mask & local_global[v, b]:
            result |= 1 << b
    return result


@njit(cache=True)
def _close_layer(
    dp: np.ndarray,
    parent_source: np.ndarray,
    parent_action: np.ndarray,
    offsets: np.ndarray,
    active_count: np.ndarray,
    epochs: np.ndarray,
    next_deadline: np.ndarray,
    active_global: np.ndarray,
    local_bit: np.ndarray,
    local_global: np.ndarray,
    req_deadline: np.ndarray,
    req_mask: np.ndarray,
    req_need: np.ndarray,
    actionable: np.ndarray,
    uncompleted: np.uint64,
    ptr: np.ndarray,
    arc_end: np.ndarray,
    arc_tile: np.ndarray,
    arc_link: np.ndarray,
    partial_ptr: np.ndarray,
    partial_end: np.ndarray,
    partial_tile: np.ndarray,
    partial_link: np.ndarray,
    completed: np.uint64,
) -> None:
    n = len(actionable)
    for u in range(n):
        row_start = offsets[u]
        boundary = (u // geometry.POINTS_PER_SLOT + 1) * geometry.POINTS_PER_SLOT
        charge = (
            (boundary - u) * geometry.UNIT_SECONDS * 0.001
            if actionable[u] & uncompleted else 0.0
        )
        for mask in range(1 << active_count[u]):
            src = row_start + mask
            value = dp[src]
            if not np.isfinite(value):
                continue
            target_mask = _map_mask(
                u, boundary, mask, -1, epochs, next_deadline, active_global,
                local_bit, local_global, active_count, req_deadline, req_mask,
                req_need,
            )
            if target_mask >= 0:
                dst = offsets[boundary] + target_mask
                proposed = value - charge
                if proposed > dp[dst] + 1e-9:
                    dp[dst] = proposed
                    parent_source[dst] = src
                    parent_action[dst] = WAIT_ACTION
            for a in range(ptr[u], ptr[u + 1]):
                tile = arc_tile[a]
                if not (completed & (np.uint64(1) << np.uint64(tile))):
                    continue
                end = arc_end[a]
                link = arc_link[a]
                target_mask = _map_mask(
                    u, end, mask, link, epochs, next_deadline,
                    active_global, local_bit, local_global, active_count,
                    req_deadline, req_mask, req_need,
                )
                if target_mask < 0:
                    continue
                dst = offsets[end] + target_mask
                if value > dp[dst] + 1e-9:
                    dp[dst] = value
                    parent_source[dst] = src
                    parent_action[dst] = OPTIONAL_BASE + tile * LINKS_PER_TILE_CODE + link
            for a in range(partial_ptr[u], partial_ptr[u + 1]):
                tile = partial_tile[a]
                link = -1
                if completed & (np.uint64(1) << np.uint64(tile)):
                    link = partial_link[a]
                    if link < 0:
                        continue
                end = partial_end[a]
                target_mask = _map_mask(
                    u, end, mask, -1, epochs, next_deadline,
                    active_global, local_bit, local_global, active_count,
                    req_deadline, req_mask, req_need,
                )
                if target_mask < 0:
                    continue
                dst = offsets[end] + target_mask
                if value > dp[dst] + 1e-9:
                    dp[dst] = value
                    parent_source[dst] = src
                    parent_action[dst] = PARTIAL_BASE + tile * LINKS_PER_TILE_CODE + link + 1


@njit(cache=True)
def _advance_first(
    current: np.ndarray,
    following: np.ndarray,
    parent_source: np.ndarray,
    parent_action: np.ndarray,
    starts: np.ndarray,
    score_row: np.ndarray,
    duration: int,
    tile_links: np.ndarray,
    tile_link_count: int,
    offsets: np.ndarray,
    active_count: np.ndarray,
    epochs: np.ndarray,
    next_deadline: np.ndarray,
    active_global: np.ndarray,
    local_bit: np.ndarray,
    local_global: np.ndarray,
    req_deadline: np.ndarray,
    req_mask: np.ndarray,
    req_need: np.ndarray,
) -> None:
    for u in starts:
        end = u + duration
        gain = score_row[u]
        for mask in range(1 << active_count[u]):
            src = offsets[u] + mask
            value = current[src]
            if not np.isfinite(value):
                continue
            for choice in range(tile_link_count + 1):
                link = -1 if choice == 0 else int(tile_links[choice - 1])
                if link >= 0 and local_bit[u, link] == -1:
                    continue
                target_mask = _map_mask(
                    u, end, mask, link, epochs, next_deadline,
                    active_global, local_bit, local_global, active_count,
                    req_deadline, req_mask, req_need,
                )
                if target_mask < 0:
                    continue
                dst = offsets[end] + target_mask
                proposed = value + gain
                if proposed > following[dst] + 1e-9:
                    following[dst] = proposed
                    parent_source[dst] = src
                    parent_action[dst] = FIRST_ACTION + link + 1


@njit(cache=True)
def _terminal_ok(
    u: int,
    mask: int,
    epochs: np.ndarray,
    active_count: np.ndarray,
    local_global: np.ndarray,
    req_start: np.ndarray,
    req_deadline: np.ndarray,
    req_mask: np.ndarray,
    req_need: np.ndarray,
) -> bool:
    global_mask = np.uint32(0)
    for b in range(active_count[u]):
        if mask & (1 << b):
            global_mask |= local_global[u, b]
    for r in range(len(req_start)):
        if epochs[u] < req_start[r]:
            return False
        if epochs[u] < req_deadline[r]:
            if _popcount(global_mask & req_mask[r]) < req_need[r]:
                return False
    return True


def _first_order(model: PracticeModel, source: Path) -> list[int]:
    result = []
    seen = set()
    for row in load_decisions(source, allow_reports=False):
        if row.action != "observe":
            raise ValueError("source must contain only observations")
        i = model.tile_index[row.tile_id]
        if i not in seen:
            seen.add(i)
            result.append(i)
    if len(result) != len(model.tiles):
        raise ValueError("source must visit all 64 tiles")
    return result


def _weather_interruption_arcs(
    model: PracticeModel,
    local_bit: np.ndarray,
    tile_links: np.ndarray,
    tile_link_count: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Per-tile zero-penalty weather interruptions, with a valid repeat tag."""
    scorer = model.scorer
    n = model.n_units
    slots = geometry._read_csv(
        model.scenario / "outputs" / "reference" / "slots.csv"
    )
    instants, sidereal, night_end = geometry._time_grid(slots, model.longitude)
    if not np.array_equal(instants, model.instants):
        raise AssertionError("partial arc grid differs from completed arc grid")
    unit = np.arange(n, dtype=np.int32)
    slot_index = unit // geometry.POINTS_PER_SLOT
    sin_limit = math.sin(math.radians(model.minimum_altitude)) - 1e-12
    lat = math.radians(model.latitude)
    start_parts = []
    end_parts = []
    tile_parts = []
    for i, tile in enumerate(model.tiles):
        tile_id = tile["tile_id"]
        dec = math.radians(float(tile["dec_deg"]))
        hour_angle = np.deg2rad(
            (sidereal - float(tile["ra_deg"]) + 180.0) % 360.0 - 180.0
        )
        sin_altitude = (
            math.sin(lat) * math.sin(dec)
            + math.cos(lat) * math.cos(dec) * np.cos(hour_angle)
        )
        legal = (
            (instants >= geometry._epoch(tile["available_from_utc"]))
            & (instants < geometry._epoch(tile["available_until_utc"]))
            & (sin_altitude >= sin_limit)
        )
        open_slots = np.fromiter(
            (
                scorer.weather.get_effective_conditions(slot.slot_id, tile_id)[
                    "is_observable"
                ]
                for slot in scorer.slots
            ),
            dtype=np.bool_, count=len(scorer.slots),
        )
        open_units = open_slots[slot_index]
        duration = int(model.exposure_units[i])
        starts = np.flatnonzero(legal & open_units).astype(np.int32)
        if len(starts) == 0:
            continue
        exposure_end = starts + duration
        boundary = ((starts // geometry.POINTS_PER_SLOT) + 1) * geometry.POINTS_PER_SLOT
        active = boundary < exposure_end
        while np.any(active):
            rows = np.flatnonzero(active)
            next_slot_start = boundary[rows]
            possible = (
                (next_slot_start < night_end[starts[rows]])
                & (next_slot_start < n)
            )
            geometry_ok = np.zeros(len(rows), dtype=np.bool_)
            geometry_ok[possible] = legal[next_slot_start[possible]]
            weather_closed = np.zeros(len(rows), dtype=np.bool_)
            checks = possible & geometry_ok
            weather_closed[checks] = ~open_units[next_slot_start[checks]]
            if np.any(weather_closed):
                chosen = rows[weather_closed]
                start_parts.append(starts[chosen])
                end_parts.append(boundary[chosen])
                tile_parts.append(np.full(len(chosen), i, dtype=np.int16))
            continuing = checks & ~weather_closed
            active[:] = False
            if np.any(continuing):
                next_rows = rows[continuing]
                boundary[next_rows] += geometry.POINTS_PER_SLOT
                active[next_rows] = boundary[next_rows] < exposure_end[next_rows]

    if not start_parts:
        raise ValueError("no legal weather-interrupted action starts")
    starts = np.concatenate(start_parts)
    ends = np.concatenate(end_parts).astype(np.int32)
    tiles = np.concatenate(tile_parts)
    order = np.argsort(starts, kind="stable")
    starts, ends, tiles = starts[order], ends[order], tiles[order]
    first_valid_link = np.full(len(starts), -1, dtype=np.int8)
    for a, (u, i) in enumerate(zip(starts, tiles)):
        for j in range(tile_link_count[i]):
            link = tile_links[i, j]
            if local_bit[u, link] != -1:
                first_valid_link[a] = link
                break
    ptr = np.empty(n + 1, dtype=np.int64)
    ptr[0] = 0
    np.cumsum(np.bincount(starts, minlength=n), out=ptr[1:])
    return ptr, ends, tiles, first_valid_link, starts


def _request_data(model: PracticeModel, scores: np.ndarray) -> dict:
    scorer = model.scorer
    n = model.n_units
    epochs = np.empty(n + 1, dtype=np.int64)
    epochs[:n] = np.rint(model.instants).astype(np.int64)
    epochs[n] = int(scorer.slots[-1].end_utc.timestamp())

    requests = []
    omitted = []
    filler_requests = []
    for request in sorted(scorer.requests.values(), key=lambda item: item.request_id):
        starts_at = int(max(
            request.issued_at_utc.timestamp(), request.available_from_utc.timestamp()
        ))
        deadline = int(request.deadline_utc.timestamp())
        requirements = scorer.request_tiles[request.request_id]
        if any(visits != 1 for visits in requirements.values()):
            raise ValueError("one-bit-per-link model requires required_visits == 1")
        feasible = sum(
            np.any(
                np.isfinite(scores[model.tile_index[tile_id]])
                & (epochs[:n] >= starts_at)
                & (epochs[:n] < deadline)
            )
            for tile_id in requirements
        )
        if feasible < request.required_tile_count:
            omitted.append(request.request_id)
            filler_requests.append((request, starts_at, deadline, requirements))
            continue
        requests.append((request, starts_at, deadline, requirements))
    if len(requests) != 17 or omitted != ["RQ0015"]:
        raise ValueError(f"unexpected feasible request split: {len(requests)} / {omitted}")

    link_req = []
    link_tile = []
    link_start = []
    link_deadline = []
    req_names = []
    tag_names = []
    req_start = []
    req_deadline = []
    req_need = []
    req_reward = []
    req_mask = []
    for r, (request, start, deadline, requirements) in enumerate(requests):
        req_names.append(request.request_id)
        tag_names.append(request.request_id)
        req_start.append(start)
        req_deadline.append(deadline)
        req_need.append(request.required_tile_count)
        req_reward.append(request.completion_reward)
        bits = np.uint32(0)
        for tile_id in sorted(requirements):
            g = len(link_req)
            if g >= 32:
                raise ValueError("request link count exceeds uint32 bit mask")
            link_req.append(r)
            link_tile.append(model.tile_index[tile_id])
            link_start.append(start)
            link_deadline.append(deadline)
            bits |= np.uint32(1) << np.uint32(g)
        req_mask.append(bits)
    for request, start, deadline, requirements in filler_requests:
        r = len(tag_names)
        tag_names.append(request.request_id)
        for tile_id in sorted(requirements):
            if len(link_req) >= 32:
                raise ValueError("request link count exceeds uint32 bit mask")
            link_req.append(r)
            link_tile.append(model.tile_index[tile_id])
            link_start.append(start)
            link_deadline.append(deadline)
    req_start = np.asarray(req_start, dtype=np.int64)
    req_deadline = np.asarray(req_deadline, dtype=np.int64)
    req_need = np.asarray(req_need, dtype=np.int8)
    req_mask = np.asarray(req_mask, dtype=np.uint32)
    link_req = np.asarray(link_req, dtype=np.int8)
    link_tile = np.asarray(link_tile, dtype=np.int16)
    link_start = np.asarray(link_start, dtype=np.int64)
    link_deadline = np.asarray(link_deadline, dtype=np.int64)
    link_count = len(link_req)

    active_count = np.zeros(n + 1, dtype=np.uint8)
    active_global = np.zeros(n + 1, dtype=np.uint32)
    local_bit = np.full((n + 1, link_count), -1, dtype=np.int8)
    local_global = np.zeros((n + 1, MAX_ACTIVE_LINKS), dtype=np.uint32)
    for u in range(n + 1):
        for g in range(link_count):
            r = int(link_req[g])
            if link_start[g] <= epochs[u] < link_deadline[g]:
                if r >= len(req_names):
                    local_bit[u, g] = -2
                    continue
                b = int(active_count[u])
                if b >= MAX_ACTIVE_LINKS:
                    raise ValueError("more than eight active request links")
                active_count[u] += 1
                local_bit[u, g] = b
                bit = np.uint32(1) << np.uint32(g)
                local_global[u, b] = bit
                active_global[u] |= bit
    counts = np.left_shift(1, active_count.astype(np.int32))
    offsets = np.empty(n + 2, dtype=np.int32)
    offsets[0] = 0
    np.cumsum(counts, out=offsets[1:])
    state_time = np.repeat(np.arange(n + 1, dtype=np.int32), counts)
    sorted_deadlines = sorted(map(int, req_deadline))
    next_deadline = np.asarray([
        sorted_deadlines[bisect_right(sorted_deadlines, int(moment))]
        if bisect_right(sorted_deadlines, int(moment)) < len(sorted_deadlines)
        else np.iinfo(np.int64).max
        for moment in epochs
    ], dtype=np.int64)

    tile_links_list = [[] for _ in model.tiles]
    for g, i in enumerate(link_tile):
        tile_links_list[int(i)].append(g)
    max_links = max(map(len, tile_links_list))
    tile_links = np.full((len(model.tiles), max_links), -1, dtype=np.int8)
    tile_link_count = np.zeros(len(model.tiles), dtype=np.int8)
    for i, links in enumerate(tile_links_list):
        tile_link_count[i] = len(links)
        tile_links[i, :len(links)] = links

    start_parts = []
    end_parts = []
    tile_parts = []
    link_parts = []
    for g, i in enumerate(link_tile):
        starts = np.flatnonzero(
            np.isfinite(scores[i])
            & (epochs[:n] >= link_start[g])
            & (epochs[:n] < link_deadline[g])
        ).astype(np.int32)
        if len(starts):
            start_parts.append(starts)
            end_parts.append(starts + int(model.exposure_units[i]))
            tile_parts.append(np.full(len(starts), i, dtype=np.int16))
            link_parts.append(np.full(len(starts), g, dtype=np.int8))
    starts = np.concatenate(start_parts)
    ends = np.concatenate(end_parts).astype(np.int32)
    arc_tile = np.concatenate(tile_parts)
    arc_link = np.concatenate(link_parts)
    order = np.argsort(starts, kind="stable")
    starts, ends, arc_tile, arc_link = (
        starts[order], ends[order], arc_tile[order], arc_link[order]
    )
    ptr = np.empty(n + 1, dtype=np.int64)
    ptr[0] = 0
    np.cumsum(np.bincount(starts, minlength=n), out=ptr[1:])
    partial_ptr, partial_end, partial_tile, partial_link, partial_start = (
        _weather_interruption_arcs(
            model, local_bit, tile_links, tile_link_count
        )
    )
    return {
        "epochs": epochs, "req_names": req_names,
        "tag_names": tag_names,
        "req_start": req_start, "req_deadline": req_deadline,
        "req_need": req_need, "req_mask": req_mask,
        "request_reward": float(sum(req_reward)), "omitted": omitted,
        "link_req": link_req, "active_count": active_count,
        "active_global": active_global, "local_bit": local_bit,
        "local_global": local_global, "offsets": offsets,
        "state_time": state_time, "next_deadline": next_deadline,
        "tile_links": tile_links, "tile_link_count": tile_link_count,
        "ptr": ptr, "arc_end": ends, "arc_tile": arc_tile,
        "arc_link": arc_link,
        "partial_ptr": partial_ptr, "partial_end": partial_end,
        "partial_tile": partial_tile, "partial_link": partial_link,
        "partial_start": partial_start,
    }


def solve(
    model: PracticeModel,
    scores: np.ndarray,
    programs: np.ndarray,
    order: list[int],
):
    data = _request_data(model, scores)
    nstates = int(data["offsets"][-1])
    layers = len(order) + 1
    parent_source = np.full((layers, nstates), -1, dtype=np.int32)
    parent_action = np.zeros((layers, nstates), dtype=np.uint16)
    current = np.full(nstates, -np.inf, dtype=np.float64)
    current[0] = 0.0
    completed = np.uint64(0)
    all_mask = np.uint64((1 << len(model.tiles)) - 1)
    for k in range(layers):
        _close_layer(
            current, parent_source[k], parent_action[k],
            data["offsets"], data["active_count"], data["epochs"],
            data["next_deadline"], data["active_global"],
            data["local_bit"], data["local_global"],
            data["req_deadline"], data["req_mask"], data["req_need"],
            model.actionable, all_mask ^ completed, data["ptr"],
            data["arc_end"], data["arc_tile"], data["arc_link"],
            data["partial_ptr"], data["partial_end"],
            data["partial_tile"], data["partial_link"],
            completed,
        )
        if k == len(order):
            break
        i = order[k]
        following = np.full(nstates, -np.inf, dtype=np.float64)
        starts = np.flatnonzero(np.isfinite(scores[i])).astype(np.int32)
        _advance_first(
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

    best = -np.inf
    final_index = -1
    for u in range(model.n_units + 1):
        for mask in range(1 << data["active_count"][u]):
            index = int(data["offsets"][u]) + mask
            value = current[index]
            if value <= best + 1e-9:
                continue
            if _terminal_ok(
                u, mask, data["epochs"], data["active_count"],
                data["local_global"], data["req_start"],
                data["req_deadline"], data["req_mask"], data["req_need"],
            ):
                best = float(value)
                final_index = index
    if final_index < 0:
        raise ValueError("fixed first order cannot complete all feasible requests")

    path = []
    partial_flags = []
    k = len(order)
    index = final_index
    optional_count = 0
    partial_count = 0
    while k or index != 0:
        source = int(parent_source[k, index])
        if source < 0:
            raise RuntimeError("missing active-request DP backpointer")
        action = int(parent_action[k, index])
        u = int(data["state_time"][source])
        if action == WAIT_ACTION:
            pass
        elif action < PARTIAL_BASE:
            code = action - OPTIONAL_BASE
            i, link = divmod(code, LINKS_PER_TILE_CODE)
            request_id = data["tag_names"][int(data["link_req"][link])]
            path.append((u, i, request_id, "DARK", False))
            partial_flags.append(False)
            optional_count += 1
        elif action < FIRST_ACTION:
            code = action - PARTIAL_BASE
            i, tag_code = divmod(code, LINKS_PER_TILE_CODE)
            link = tag_code - 1
            request_id = (
                "" if link < 0
                else data["tag_names"][int(data["link_req"][link])]
            )
            path.append((u, i, request_id, "DARK", False))
            partial_flags.append(True)
            partial_count += 1
        else:
            if k == 0:
                raise RuntimeError("first-event pointer at layer zero")
            link = action - FIRST_ACTION - 1
            request_id = (
                "" if link < 0
                else data["tag_names"][int(data["link_req"][link])]
            )
            i = order[k - 1]
            path.append((
                u, i, request_id, PROGRAMS[int(programs[i, u])], True
            ))
            partial_flags.append(False)
            k -= 1
        index = source
    path.reverse()
    partial_flags.reverse()
    return path, partial_flags, best, optional_count, partial_count, data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/dev-reference"))
    parser.add_argument(
        "--input", type=Path,
        default=Path("results/practice_core.csv"),
        help="completed observation trace supplying only the 64-first-visit order",
    )
    parser.add_argument(
        "--out", type=Path,
        default=Path("runs/practice_active_requests/decisions.csv"),
    )
    args = parser.parse_args()
    model = PracticeModel(args.scenario, Path("results/practice_reference.csv"))
    scores, programs = score_table(model)
    order = _first_order(model, args.input)
    path, partial_flags, predicted, optional_count, partial_count, data = solve(
        model, scores, programs, order
    )
    _write(model, args.out, path)
    report = model.authoritative_score(args.out)
    (args.out.parent / "score_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    observations = [
        action for action in report["actions"] if action["action"] == "observe"
    ]
    if len(observations) != len(partial_flags):
        raise AssertionError("DP action count and scorer observation count disagree")
    if any(
        action["outcome"] != (
            "weather_interrupted" if is_partial else "completed"
        ) or action["penalty"] != 0.0
        for action, is_partial in zip(observations, partial_flags)
    ):
        raise AssertionError("DP arc classification and scorer disagree")
    if report["score"]["request_reward"] != data["request_reward"]:
        raise AssertionError("a required request was not awarded")
    if abs(report["score"]["total"] - predicted - data["request_reward"]) > 1e-5:
        raise AssertionError("DP value and scorer disagree")
    print(json.dumps({
        "first_events": len(order), "optional_events": optional_count,
        "weather_interrupted_events": partial_count,
        "feasible_requests": len(data["req_names"]),
        "excluded_requests": data["omitted"],
        "compressed_states_per_layer": int(data["offsets"][-1]),
        "all_label_revisit_arcs": len(data["arc_end"]),
        "per_tile_weather_interruption_arcs": len(data["partial_end"]),
        "predicted_without_requests": predicted,
        "official_total": report["score"]["total"],
        "science": report["score"]["base_science"] + report["score"]["program_bonus"],
        "request_reward": report["score"]["request_reward"],
        "avoidable_wait": report["score"]["penalties"].get("avoidable_wait", 0.0),
        "output": str(args.out),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
