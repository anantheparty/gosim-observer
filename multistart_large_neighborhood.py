#!/usr/bin/env python3
"""Order-free large-block search around several public-practice first-visit seeds.

The outer neighborhood destroys 8--16 first-visit positions, possibly spread
across the whole season.  The exact inner oracle reconstructs every 150-second
start, request tag, legal revisit, wait, and weather interruption for the new
64-tile order.  Every reported incumbent is replayed by the authoritative
scorer.  This reads only the public dev-reference scenario.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

import sequence_active_requests_dp as active
from practice_lns import PracticeModel
from sequence_block_dp import _write
from sequence_dp import score_table
from challenge.scoring_core import load_decisions


ROOT = Path(__file__).resolve().parent
SCENARIO = ROOT / "scenarios" / "dev-reference"
REFERENCE = ROOT / "results" / "practice_reference.csv"
DEFAULT_SEED = ROOT / "results" / "practice_core.csv"
BEST_PATH = ROOT / "results" / "practice_best.csv"


def _terminal_indices(data: dict) -> np.ndarray:
    indices = []
    for u in range(len(data["active_count"])):
        for mask in range(1 << int(data["active_count"][u])):
            if active._terminal_ok(
                u, mask, data["epochs"], data["active_count"],
                data["local_global"], data["req_start"],
                data["req_deadline"], data["req_mask"], data["req_need"],
            ):
                indices.append(int(data["offsets"][u]) + mask)
    return np.asarray(indices, dtype=np.int32)


class Oracle:
    def __init__(self, model: PracticeModel):
        self.model = model
        self.scores, self.programs = score_table(model)
        self.data = active._request_data(model, self.scores)
        self.starts = [
            np.flatnonzero(np.isfinite(self.scores[i])).astype(np.int32)
            for i in range(len(model.tiles))
        ]
        self.terminal = _terminal_indices(self.data)
        self.nstates = int(self.data["offsets"][-1])
        self.source = np.empty(self.nstates, dtype=np.int32)
        self.action = np.empty(self.nstates, dtype=np.uint16)

    def value(self, order: list[int]) -> float:
        """Exact best all-request-complete score for a first-tile order."""
        model, data = self.model, self.data
        self.last_failure = None
        current = np.full(self.nstates, -np.inf, dtype=np.float64)
        current[0] = 0.0
        completed = np.uint64(0)
        all_mask = np.uint64((1 << len(model.tiles)) - 1)
        for k in range(len(order) + 1):
            active._close_layer(
                current, self.source, self.action,
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
            following = np.full(self.nstates, -np.inf, dtype=np.float64)
            active._advance_first(
                current, following, self.source, self.action,
                self.starts[i], self.scores[i],
                int(model.exposure_units[i]), data["tile_links"][i],
                int(data["tile_link_count"][i]),
                data["offsets"], data["active_count"], data["epochs"],
                data["next_deadline"], data["active_global"],
                data["local_bit"], data["local_global"],
                data["req_deadline"], data["req_mask"], data["req_need"],
            )
            current = following
            completed |= np.uint64(1) << np.uint64(i)
            if not np.any(np.isfinite(current)):
                self.last_failure = (k, model.tile_ids[i])
                return -math.inf
        best = float(np.max(current[self.terminal]))
        return best + data["request_reward"]

    def write_and_verify(self, order: list[int], destination: Path) -> dict:
        path, partial, predicted, optional, interrupted, data = active.solve(
            self.model, self.scores, self.programs, order
        )
        _write(self.model, destination, path)
        report = self.model.authoritative_score(destination)
        actions = [a for a in report["actions"] if a["action"] == "observe"]
        if len(actions) != len(partial) or any(
            a["outcome"] != ("weather_interrupted" if flag else "completed")
            or a["penalty"] != 0.0
            for a, flag in zip(actions, partial)
        ):
            raise AssertionError("inner oracle and official replay disagree")
        if len(report["completion"]["completed_tiles"]) != 64:
            raise AssertionError("not all tiles completed")
        if report["score"]["request_reward"] != data["request_reward"]:
            raise AssertionError("not all feasible requests complete")
        if abs(report["score"]["total"] - predicted - data["request_reward"]) > 1e-5:
            raise AssertionError("predicted score and official replay disagree")
        return {
            "score": report["score"], "observations": len(actions),
            "optional_revisits": optional,
            "weather_interruptions": interrupted,
        }


def _request_hyperedges(model: PracticeModel) -> list[set[int]]:
    return [
        {model.tile_index[tile] for tile in model.scorer.request_tiles[rid]}
        for rid in sorted(model.scorer.requests)
        if rid != "RQ0015"
    ]


def _rank_windows(model: PracticeModel, oracle: Oracle, source: Path):
    """Conservative rank windows from public availability and request deadlines."""
    rows = load_decisions(source, allow_reports=False)
    first = {}
    for row in rows:
        i = model.tile_index[row.tile_id]
        if i not in first:
            first[i] = model.scorer.slot_indices[row.slot_id] * 6
    if len(first) != len(model.tiles):
        raise ValueError("seed does not contain all first visits")
    order = active._first_order(model, source)
    reference_times = np.array([first[i] for i in order], dtype=np.int32)
    minimum = np.zeros(len(model.tiles), dtype=np.int32)
    maximum = np.full(len(model.tiles), model.n_units, dtype=np.int32)
    for i in range(len(model.tiles)):
        if len(oracle.starts[i]) == 0:
            raise ValueError(f"tile {i} has no completed arc")
        minimum[i] = int(oracle.starts[i][0])
        maximum[i] = int(oracle.starts[i][-1])
    # First completion of a requested tile must precede the closing window to
    # contribute a tagged visit.  This is a conservative construction filter;
    # the exact oracle still decides feasibility and labels.
    for rid, request in model.scorer.requests.items():
        if rid == "RQ0015":
            continue
        deadline = request.deadline_utc.timestamp()
        for tile_id in model.scorer.request_tiles[rid]:
            i = model.tile_index[tile_id]
            starts = oracle.starts[i]
            allowed = starts[model.instants[starts] < deadline]
            if len(allowed):
                maximum[i] = min(maximum[i], int(allowed[-1]))
    windows = []
    for i in range(len(model.tiles)):
        # A one-day guard lets the exact timing optimizer slide neighboring
        # events while preserving a broad long-distance move range.
        lo = max(0, int(np.searchsorted(reference_times, minimum[i] - 300, side="left")))
        hi = min(len(order), int(np.searchsorted(reference_times, maximum[i] + 300, side="right")))
        windows.append((lo, hi))
    return windows, reference_times


def _science_targets(
    model: PracticeModel, oracle: Oracle, seed_path: Path,
    reference_times: np.ndarray, rank_windows: list[tuple[int, int]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[tuple[int, int, float]]]:
    """Potential gain and season rank of each tile's best legal first arc."""
    report = model.authoritative_score(seed_path)
    achieved = np.zeros(len(model.tiles), dtype=np.float64)
    first_finish = np.full(len(model.tiles), -1, dtype=np.int32)
    seen = set()
    zero_waits: list[tuple[int, int, float]] = []
    cursor = 0
    completed = np.uint64(0)
    for action in report["actions"]:
        if action["action"] != "observe":
            continue
        instant = datetime.fromisoformat(action["start_utc"].replace("Z", "+00:00")).timestamp()
        start = int(np.searchsorted(model.instants, instant, side="left"))
        if start >= model.n_units or abs(model.instants[start] - instant) > 1e-6:
            raise AssertionError("scorer action start outside 150-second time graph")
        while cursor < start:
            boundary = (cursor // 6 + 1) * 6
            if boundary > start:
                raise AssertionError("implicit wait fails to reach action start")
            actionable = int(model.actionable[cursor])
            if actionable & ~int(completed) == 0:
                zero_waits.append((cursor, actionable, (boundary - cursor) * 0.15))
            cursor = boundary
        i = model.tile_index[action["tile_id"]]
        cursor = start + int(action["elapsed_seconds"]) // 150
        if action["outcome"] == "completed" and i not in seen:
            seen.add(i)
            achieved[i] = action["base_science_score"] + action["program_bonus_score"]
            first_finish[i] = cursor
            completed |= np.uint64(1) << np.uint64(i)
    if len(seen) != len(model.tiles):
        raise ValueError("scored seed does not complete all tiles")
    regret = np.zeros(len(model.tiles), dtype=np.float64)
    target = np.zeros(len(model.tiles), dtype=np.int32)
    target_unit = np.zeros(len(model.tiles), dtype=np.int32)
    for i, starts in enumerate(oracle.starts):
        lo, hi = rank_windows[i]
        allowed = starts[
            (starts >= (reference_times[min(lo, 63)] if lo < 64 else model.n_units))
            & (starts <= reference_times[min(hi, 63)])
        ]
        if len(allowed) == 0:
            allowed = starts
        argmax = int(allowed[np.argmax(oracle.scores[i, allowed])])
        regret[i] = max(0.0, float(oracle.scores[i, argmax] - achieved[i]))
        target[i] = int(np.searchsorted(reference_times, argmax, side="left"))
        target_unit[i] = argmax
    return regret, target, target_unit, first_finish, zero_waits


def _mincut_delay_group(
    regret: np.ndarray, target_unit: np.ndarray,
    first_finish: np.ndarray, zero_waits: list[tuple[int, int, float]],
    exposure_units: np.ndarray,
) -> tuple[set[int], float, int]:
    """Exact max-weight closure for fixed target dates and added-wait OR cost.

    Each selected tile yields its isolated peak-science gain.  A formerly
    uncharged wait edge costs once if any selected delayed tile is actionable
    there.  This fixed-path surrogate is solved by an s-t min-cut; it is not a
    certificate for the full rescheduling problem.
    """
    eligible = {
        i for i in range(len(regret))
        if regret[i] > 1e-8 and target_unit[i] > first_finish[i]
    }
    if not eligible:
        return set(), 0.0, 0
    groups: defaultdict[int, float] = defaultdict(float)
    for u, actionable, cost in zero_waits:
        implicated = 0
        mask = actionable
        while mask:
            bit = mask & -mask
            i = bit.bit_length() - 1
            if i in eligible and first_finish[i] <= u < target_unit[i] + int(exposure_units[i]):
                implicated |= bit
            mask ^= bit
        if implicated:
            groups[implicated] += cost

    class Dinic:
        def __init__(self, n):
            self.adj = [[] for _ in range(n)]
        def add(self, u, v, cap):
            a = [v, float(cap), len(self.adj[v])]
            b = [u, 0.0, len(self.adj[u])]
            self.adj[u].append(a)
            self.adj[v].append(b)
        def flow(self, s, t):
            value = 0.0
            while True:
                level = [-1] * len(self.adj)
                level[s] = 0
                queue = [s]
                for u in queue:
                    for v, cap, _ in self.adj[u]:
                        if cap > 1e-9 and level[v] < 0:
                            level[v] = level[u] + 1
                            queue.append(v)
                if level[t] < 0:
                    break
                ptr = [0] * len(self.adj)
                def dfs(u, sent):
                    if u == t:
                        return sent
                    while ptr[u] < len(self.adj[u]):
                        edge = self.adj[u][ptr[u]]
                        v, cap, rev = edge
                        if cap > 1e-9 and level[v] == level[u] + 1:
                            pushed = dfs(v, min(sent, cap))
                            if pushed > 1e-9:
                                edge[1] -= pushed
                                self.adj[v][rev][1] += pushed
                                return pushed
                        ptr[u] += 1
                    return 0.0
                while True:
                    sent = dfs(s, 1e12)
                    if sent <= 1e-9:
                        break
                    value += sent
            return value
        def reachable(self, source):
            seen = {source}
            queue = [source]
            for u in queue:
                for v, cap, _ in self.adj[u]:
                    if cap > 1e-9 and v not in seen:
                        seen.add(v)
                        queue.append(v)
            return seen

    keys = list(groups)
    sink = 65 + len(keys)
    graph = Dinic(sink + 1)
    for i in eligible:
        graph.add(0, i + 1, float(regret[i]))
    for j, mask in enumerate(keys):
        node = 65 + j
        graph.add(node, sink, groups[mask])
        while mask:
            bit = mask & -mask
            i = bit.bit_length() - 1
            graph.add(i + 1, node, 1e9)
            mask ^= bit
    graph.flow(0, sink)
    selected = {i for i in eligible if i + 1 in graph.reachable(0)}
    total_gain = sum(float(regret[i]) for i in selected)
    wait_cost = sum(cost for mask, cost in groups.items() if any(mask & (1 << i) for i in selected))
    return selected, total_gain - wait_cost, len(groups)


def _destroy_set(
    order: list[int], rng: random.Random, kind: str,
    hyperedges: list[set[int]], size: int, unrestricted: set[int],
    regret: np.ndarray, closure_group: set[int],
    mate_rank: dict[int, int] | None,
) -> set[int]:
    if kind == "closure":
        return closure_group.copy()
    if kind == "random":
        pool = [i for i in order if i in unrestricted]
        return set(rng.sample(pool, size))
    if kind == "window":
        start = rng.randrange(len(order) - size + 1)
        return set(order[start:start + size])
    if kind == "rotation":
        pool = [i for i in order if i in unrestricted]
        return set(rng.sample(pool, size))
    if kind == "crossover":
        if mate_rank is None:
            raise ValueError("crossover requires --mate-seed")
        ranked = sorted(
            (i for i in order if i in unrestricted),
            key=lambda i: abs(order.index(i) - mate_rank[i]), reverse=True,
        )
        pool = ranked[:max(size * 2, 20)]
        return set(rng.sample(pool, size))
    if kind == "request":
        selected: set[int] = set()
        for edge in rng.sample(hyperedges, min(len(hyperedges), rng.randint(2, 5))):
            selected.update(edge)
            if len(selected) >= size:
                break
        if len(selected) > size:
            selected = set(rng.sample(sorted(selected), size))
        selected.update(rng.sample([i for i in order if i not in selected], size - len(selected)))
        return selected
    if kind == "span":
        # Five separated anchors force the neighborhood to cross distant ranks.
        chunks = np.array_split(np.arange(len(order)), 5)
        selected = set()
        for chunk in chunks:
            eligible = [order[int(k)] for k in chunk if order[int(k)] in unrestricted]
            if eligible:
                selected.add(rng.choice(eligible))
        selected.update(rng.sample([i for i in order if i in unrestricted and i not in selected], size - len(selected)))
        return selected
    if kind in {"guided", "closure"}:
        # Regret is the exact best legal single-arc science less the scorer's
        # achieved science.  It guides construction; the full DP remains judge.
        pool = [i for i in order if i in unrestricted]
        weights = [max(1.0, float(regret[i])) ** 1.5 for i in pool]
        chosen = set()
        while len(chosen) < size:
            chosen.add(rng.choices(pool, weights=weights, k=1)[0])
        return chosen
    raise ValueError(kind)


def _reinsert(
    order: list[int], selected: set[int], rng: random.Random,
    radius: int, rank_windows: list[tuple[int, int]],
    kind: str, target_ranks: np.ndarray,
) -> list[int]:
    """Reinsert a destroyed group jointly, allowing large rank changes."""
    if kind == "rotation":
        positions = [k for k, tile in enumerate(order) if tile in selected]
        values = [order[k] for k in positions]
        shift = rng.choice([-3, -2, -1, 1, 2, 3]) % len(values)
        rotated = values[shift:] + values[:shift]
        result = order.copy()
        for k, tile in zip(positions, rotated):
            result[k] = tile
        return result
    stable = [i for i in order if i not in selected]
    chosen = sorted(selected, key=lambda i: order.index(i))
    if kind in {"guided", "closure", "crossover"}:
        chosen.sort(key=lambda i: int(target_ranks[i]))
    else:
        rng.shuffle(chosen)
    result = stable.copy()
    for tile in chosen:
        original_rank = order.index(tile)
        lo, hi = rank_windows[tile]
        lo = max(0, min(lo, len(result)))
        hi = max(lo, min(hi, len(result)))
        if kind in {"guided", "closure", "crossover"}:
            position = max(lo, min(hi, int(target_ranks[tile]) + rng.randint(-4, 4)))
        elif kind == "window":
            position = max(lo, min(hi, original_rank + rng.randint(-4, 4)))
        elif rng.random() < 0.35:
            position = rng.randint(lo, hi)
        else:
            position = max(lo, min(hi, original_rank + rng.randint(-radius, radius)))
        result.insert(position, tile)
    assert len(result) == len(order) and len(set(result)) == len(order)
    return result


def _movement(before: list[int], after: list[int]) -> tuple[int, int]:
    original = {tile: k for k, tile in enumerate(before)}
    shifts = [abs(k - original[tile]) for k, tile in enumerate(after)]
    return max(shifts), sum(shifts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--science-seed", type=Path, default=BEST_PATH)
    parser.add_argument("--mate-seed", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "runs" / "multistart_lns")
    parser.add_argument("--rng-seed", type=int, default=71011)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--min-destroy", type=int, default=8)
    parser.add_argument("--max-destroy", type=int, default=16)
    parser.add_argument("--radius", type=int, default=20)
    parser.add_argument("--restart-period", type=int, default=20)
    parser.add_argument("--temperature", type=float, default=350.0)
    args = parser.parse_args()
    if not 1 <= args.min_destroy <= args.max_destroy <= 64:
        raise ValueError("invalid destroy range")
    args.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.rng_seed)
    start = time.monotonic()
    model = PracticeModel(SCENARIO, REFERENCE)
    oracle = Oracle(model)
    hyperedges = _request_hyperedges(model)
    baseline = active._first_order(model, args.seed)
    mate_order = active._first_order(model, args.mate_seed) if args.mate_seed else None
    mate_rank = (
        {tile: k for k, tile in enumerate(mate_order)}
        if mate_order is not None else None
    )
    windows, reference_times = _rank_windows(model, oracle, args.seed)
    regret, targets, target_units, first_finish, zero_waits = _science_targets(
        model, oracle, args.science_seed,
        reference_times, windows,
    )
    closure_group, closure_gain, closure_masks = _mincut_delay_group(
        regret, target_units, first_finish, zero_waits, model.exposure_units
    )
    print(json.dumps({"closure_group": [model.tile_ids[i] for i in sorted(closure_group)],
                      "surrogate_gain": closure_gain, "mask_groups": closure_masks,
                      "zero_wait_edges": len(zero_waits)}), flush=True)
    linked = set().union(*hyperedges)
    unrestricted = {
        i for i in baseline if i not in linked and windows[i][1] - windows[i][0] >= 30
    }
    best_order = baseline.copy()
    best = oracle.value(best_order)
    current_order = baseline.copy()
    current = best
    elite: list[tuple[float, list[int]]] = [(best, baseline.copy())]
    trace = args.out / f"trace_{args.rng_seed}.jsonl"
    with trace.open("w", encoding="utf-8") as log:
        log.write(json.dumps({"iteration": 0, "score": best,
                              "order": [model.tile_ids[i] for i in baseline]}) + "\n")
        if math.isfinite(best):
            checked = oracle.write_and_verify(best_order, args.out / f"best_{args.rng_seed}.csv")
            (args.out / f"best_{args.rng_seed}.json").write_text(
                json.dumps(checked, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        for iteration in range(1, args.iterations + 1):
            if iteration % args.restart_period == 0:
                current, current_order = rng.choice(elite[: min(8, len(elite))])
                current_order = current_order.copy()
            base = current_order
            kinds = (
                "window", "rotation", "guided", "request", "span", "random",
                "window", "rotation", "closure", "window",
                "crossover" if mate_rank is not None else "guided",
            )
            kind = kinds[(iteration - 1) % len(kinds)]
            selected = _destroy_set(
                base, rng, kind, hyperedges,
                rng.randint(args.min_destroy, args.max_destroy),
                unrestricted, regret, closure_group, mate_rank,
            )
            position_targets = (
                np.asarray([mate_rank[i] for i in range(len(model.tiles))], dtype=np.int32)
                if kind == "crossover" else targets
            )
            candidate = _reinsert(
                base, selected, rng, args.radius, windows, kind, position_targets
            )
            displacement, total_shift = _movement(base, candidate)
            t0 = time.monotonic()
            value = oracle.value(candidate)
            record = {
                "iteration": iteration, "kind": kind,
                "destroyed": len(selected), "max_rank_shift": displacement,
                "total_rank_shift": total_shift, "score": value,
                "seconds": time.monotonic() - t0,
                "order": [model.tile_ids[i] for i in candidate],
            }
            if not math.isfinite(value):
                record["first_infeasible_event"] = oracle.last_failure
            if value > best + 1e-7:
                report = oracle.write_and_verify(
                    candidate, args.out / f"best_{args.rng_seed}.csv"
                )
                if abs(report["score"]["total"] - value) > 1e-5:
                    raise AssertionError("fast oracle disagrees with replay")
                best = value
                best_order = candidate
                record["improved"] = True
                record["verified"] = report
                (args.out / f"best_{args.rng_seed}.json").write_text(
                    json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            if math.isfinite(value):
                if all(candidate != old for _, old in elite):
                    elite.append((value, candidate.copy()))
                    elite.sort(key=lambda item: item[0], reverse=True)
                    elite = elite[:16]
                phase = (iteration % args.restart_period) / max(1, args.restart_period)
                temperature = args.temperature * (1.0 - 0.7 * phase)
                if value >= current or rng.random() < math.exp((value - current) / temperature):
                    current, current_order = value, candidate.copy()
                    record["accepted"] = True
            log.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n"
            ) if math.isfinite(value) else log.write(
                json.dumps({**record, "score": None}, sort_keys=True) + "\n"
            )
            log.flush()
            print(json.dumps({"iteration": iteration, "value": value,
                              "best": best, "current": current,
                              "elapsed": time.monotonic() - start,
                              "shift": displacement, "kind": kind}), flush=True)


if __name__ == "__main__":
    main()
