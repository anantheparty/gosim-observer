#!/usr/bin/env python3
"""Fit a transparent order surrogate and solve trust-region assignments.

The regression model only proposes first-visit permutations. Every proposal
must subsequently pass the exact active-request DP and official local scorer.
Training rows are public dev-reference DP traces; this script never opens an
evaluation scenario or submits to the website.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
TILES = tuple(f"T{i:05d}" for i in range(1, 65))
TILE_INDEX = {tile: i for i, tile in enumerate(TILES)}
KNOTS = 7


def load_traces(directory: Path):
    scored: dict[tuple[str, ...], tuple[float, str]] = {}
    total = 0
    for path in sorted(directory.glob("*/trace_*.jsonl")):
        family = path.parent.name.split("_")[0]
        for line in path.read_text().splitlines():
            total += 1
            row = json.loads(line)
            order = tuple(row.get("order", ()))
            score = row.get("score")
            if score is None or len(order) != 64 or set(order) != set(TILES):
                continue
            score = float(score)
            previous = scored.get(order)
            if previous is not None and abs(previous[0] - score) > 1e-5:
                raise AssertionError("same order has inconsistent exact DP scores")
            scored[order] = (score, family)
    if len(scored) < 100:
        raise ValueError("at least 100 unique scored orders required")
    orders = list(scored)
    y = np.array([scored[order][0] for order in orders], dtype=np.float64)
    family = np.array([scored[order][1] for order in orders])
    return orders, y, family, total


def order_features(orders: list[tuple[str, ...]]) -> np.ndarray:
    """Seven nonnegative piecewise-linear rank functions for each tile."""
    x = np.zeros((len(orders), 64 * KNOTS + 1), dtype=np.float64)
    x[:, -1] = 1.0
    for row, order in enumerate(orders):
        for position, tile in enumerate(order):
            index = TILE_INDEX[tile]
            location = position * (KNOTS - 1) / 63.0
            left = int(location)
            fraction = location - left
            x[row, index * KNOTS + left] += 1.0 - fraction
            if left + 1 < KNOTS:
                x[row, index * KNOTS + left + 1] += fraction
    return x


def fit_ridge(x: np.ndarray, y: np.ndarray, ridge: float):
    mean = float(y.mean())
    # Accelerate-backed NumPy on macOS sometimes sets spurious FP warning
    # flags inside a finite matrix product. Check all outputs explicitly.
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        gram = x.T @ x
        rhs = x.T @ (y - mean)
    if not np.isfinite(gram).all() or not np.isfinite(rhs).all():
        raise ArithmeticError("nonfinite ridge normal equations")
    gram.flat[::len(gram) + 1] += ridge
    gram[-1, -1] -= ridge  # intercept is unpenalized
    coefficients = np.linalg.solve(gram, rhs)
    if not np.isfinite(coefficients).all():
        raise ArithmeticError("nonfinite ridge coefficients")
    return coefficients, mean


def grouped_validation(x: np.ndarray, y: np.ndarray,
                       family: np.ndarray, ridge: float) -> dict:
    outcomes = {}
    for held_out in sorted(set(family)):
        test = family == held_out
        train = ~test
        coefficients, mean = fit_ridge(x[train], y[train], ridge)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            prediction = x[test] @ coefficients + mean
        if not np.isfinite(prediction).all():
            raise ArithmeticError("nonfinite held-out prediction")
        error = prediction - y[test]
        outcomes[held_out] = {
            "count": int(test.sum()),
            "mae": float(np.mean(np.abs(error))),
            "rmse": float(np.sqrt(np.mean(error * error))),
            "r2": float(1.0 - np.mean(error * error) / np.var(y[test])),
        }
    return outcomes


def utility_matrix(coefficients: np.ndarray) -> np.ndarray:
    utility = np.empty((64, 64), dtype=np.float64)
    basis = np.zeros((64, KNOTS), dtype=np.float64)
    for position in range(64):
        location = position * (KNOTS - 1) / 63.0
        left = int(location)
        fraction = location - left
        basis[position, left] = 1.0 - fraction
        if left + 1 < KNOTS:
            basis[position, left + 1] = fraction
    for i in range(64):
        utility[i] = basis @ coefficients[i * KNOTS:(i + 1) * KNOTS]
    return utility


def min_cost_assignment(cost: np.ndarray) -> list[int]:
    """Dense square Hungarian algorithm; row i is assigned to one column."""
    n = len(cost)
    potential_row = np.zeros(n + 1)
    potential_col = np.zeros(n + 1)
    matched_row = np.zeros(n + 1, dtype=np.int32)
    previous_col = np.zeros(n + 1, dtype=np.int32)
    for i in range(1, n + 1):
        matched_row[0] = i
        distance = np.full(n + 1, np.inf)
        used = np.zeros(n + 1, dtype=bool)
        column = 0
        while True:
            used[column] = True
            row = matched_row[column]
            delta = np.inf
            next_column = 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                candidate = (cost[row - 1, j - 1]
                             - potential_row[row] - potential_col[j])
                if candidate < distance[j]:
                    distance[j] = candidate
                    previous_col[j] = column
                if distance[j] < delta:
                    delta = distance[j]
                    next_column = j
            for j in range(n + 1):
                if used[j]:
                    potential_row[matched_row[j]] += delta
                    potential_col[j] -= delta
                else:
                    distance[j] -= delta
            column = next_column
            if matched_row[column] == 0:
                break
        while True:
            prior = previous_col[column]
            matched_row[column] = matched_row[prior]
            column = prior
            if column == 0:
                break
    assigned = [-1] * n
    for column in range(1, n + 1):
        assigned[matched_row[column] - 1] = column - 1
    if len(set(assigned)) != n:
        raise AssertionError("assignment is not a permutation")
    return assigned


def footrule(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    ranks = {tile: k for k, tile in enumerate(a)}
    return sum(abs(ranks[tile] - k) for k, tile in enumerate(b))


def choose_bases(orders: list[tuple[str, ...]], y: np.ndarray,
                 count: int) -> list[tuple[str, ...]]:
    candidates = np.argsort(-y)
    selected = []
    for k in candidates:
        order = orders[int(k)]
        if all(footrule(order, earlier) >= 80 for earlier in selected):
            selected.append(order)
        if len(selected) == count:
            break
    return selected


def proposal_bases(orders: list[tuple[str, ...]], y: np.ndarray,
                   count: int, external_base: dict | None):
    bases: list[tuple[tuple[str, ...], float]] = []
    if external_base:
        base = tuple(external_base["first_order"])
        if len(base) != 64 or set(base) != set(TILES):
            raise ValueError("external base must be a 64-tile permutation")
        bases.append((base, float(external_base["score"])))
    for base in choose_bases(orders, y, count + 4):
        if all(footrule(base, earlier) >= 80 for earlier, _ in bases):
            bases.append((base, float(y[orders.index(base)])))
        if len(bases) == count:
            break
    return bases


def propose(orders: list[tuple[str, ...]], y: np.ndarray,
            utility: np.ndarray, intercept: float,
            *, base_count: int, max_candidates: int,
            radii: tuple[int, ...], external_base: dict | None,
            seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    known = set(orders)
    bases = proposal_bases(orders, y, base_count, external_base)
    proposals: dict[tuple[str, ...], dict] = {}
    for base_index, (base, base_score) in enumerate(bases):
        base_position = np.empty(64, dtype=np.int32)
        for position, tile in enumerate(base):
            base_position[TILE_INDEX[tile]] = position
        displacement = np.abs(np.arange(64)[None, :] - base_position[:, None])
        for radius in radii:
            admissible = displacement <= radius
            for noise in (0.0, 10.0, 25.0, 50.0, 100.0):
                for repeat in range(4 if noise else 1):
                    perturbed = utility.copy()
                    if noise:
                        perturbed += rng.gumbel(0.0, noise, perturbed.shape)
                    cost = -perturbed + np.where(admissible, 0.0, 1e9)
                    tile_to_position = min_cost_assignment(cost)
                    if any(not admissible[i, k]
                           for i, k in enumerate(tile_to_position)):
                        raise AssertionError("forbidden tile assignment")
                    ordered = [None] * 64
                    for i, k in enumerate(tile_to_position):
                        ordered[k] = TILES[i]
                    order = tuple(ordered)
                    if order in known:
                        continue
                    predicted = float(
                        intercept + sum(utility[i, k]
                                        for i, k in enumerate(tile_to_position))
                    )
                    proposal = {
                        "seed": seed + len(proposals),
                        "mode": "rank_surrogate_assignment",
                        "base_index": base_index,
                        "base_exact_score": base_score,
                        "radius": radius,
                        "gumbel_scale": noise,
                        "footrule_from_base": footrule(base, order),
                        "surrogate_prediction": predicted,
                        "first_order": list(order),
                    }
                    previous = proposals.get(order)
                    if previous is None or predicted > previous["surrogate_prediction"]:
                        proposals[order] = proposal
    ranked = sorted(proposals.values(),
                    key=lambda row: row["surrogate_prediction"], reverse=True)
    selected = []
    for row in ranked:
        order = tuple(row["first_order"])
        if selected and min(footrule(order, tuple(other["first_order"]))
                            for other in selected) < 36:
            continue
        selected.append(row)
        if len(selected) >= max_candidates:
            break
    for index, row in enumerate(selected):
        row["seed"] = seed + index
    return selected


def propose_subset(orders: list[tuple[str, ...]], y: np.ndarray,
                   utility: np.ndarray, intercept: float,
                   *, base_count: int, max_candidates: int,
                   trials_per_base: int, external_base: dict | None,
                   allowed_tiles: set[str] | None,
                   rank_windows: dict[str, tuple[int, int]] | None,
                   seed: int) -> list[dict]:
    """Solve many exact small assignment neighborhoods around feasible orders."""
    rng = np.random.default_rng(seed)
    known = set(orders)
    bases = proposal_bases(orders, y, base_count, external_base)
    proposals: dict[tuple[str, ...], dict] = {}
    sizes = (6, 8, 10, 12, 16)
    for base_index, (base, base_score) in enumerate(bases):
        available_positions = [
            k for k, tile in enumerate(base)
            if allowed_tiles is None or tile in allowed_tiles
        ]
        if len(available_positions) < max(sizes):
            raise ValueError("too few movable tiles for subset assignment")
        for trial in range(trials_per_base):
            size = sizes[trial % len(sizes)]
            # Three short calendar windows can interact across the season,
            # while the other 48-58 first visits retain their exact ranks.
            selected: set[int] = set()
            for _ in range(3):
                beginning = int(rng.choice(available_positions))
                length = max(2, size // 3)
                selected.update(
                    position for position in available_positions
                    if beginning <= position < beginning + length
                )
            while len(selected) < size:
                selected.add(int(rng.choice(available_positions)))
            positions = sorted(selected)[:size]
            if len(positions) < size:
                continue
            indices = [TILE_INDEX[base[position]] for position in positions]
            local = utility[np.ix_(indices, positions)].copy()
            admissible = np.ones(local.shape, dtype=bool)
            if rank_windows is not None:
                for row, tile_index in enumerate(indices):
                    lo, hi = rank_windows[TILES[tile_index]]
                    admissible[row] = (lo <= np.asarray(positions)) & (
                        np.asarray(positions) <= hi
                    )
            noise = (0.0, 10.0, 25.0, 50.0)[trial % 4]
            if noise:
                local += rng.gumbel(0.0, noise, local.shape)
            assigned = min_cost_assignment(-local + np.where(admissible, 0, 1e9))
            if any(not admissible[row, column]
                   for row, column in enumerate(assigned)):
                continue
            order = list(base)
            for tile_index, destination_index in zip(indices, assigned):
                order[positions[destination_index]] = TILES[tile_index]
            order = tuple(order)
            if order in known or order == base:
                continue
            prediction = float(
                intercept + sum(utility[TILE_INDEX[tile], position]
                                for position, tile in enumerate(order))
            )
            row = {
                "seed": seed + len(proposals),
                "mode": "rank_surrogate_subset_assignment",
                "base_index": base_index,
                "base_exact_score": base_score,
                "selected_positions": positions,
                "changed_positions": sum(a != b for a, b in zip(order, base)),
                "gumbel_scale": noise,
                "footrule_from_base": footrule(base, order),
                "surrogate_prediction": prediction,
                "first_order": list(order),
            }
            previous = proposals.get(order)
            if previous is None or prediction > previous["surrogate_prediction"]:
                proposals[order] = row
    ranked = sorted(proposals.values(),
                    key=lambda row: row["surrogate_prediction"], reverse=True)
    selected = []
    for row in ranked:
        order = tuple(row["first_order"])
        if selected and min(footrule(order, tuple(other["first_order"]))
                            for other in selected) < 12:
            continue
        selected.append(row)
        if len(selected) >= max_candidates:
            break
    for index, row in enumerate(selected):
        row["seed"] = seed + index
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", type=Path,
                        default=ROOT / "runs" / "surrogate_training")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs" / "surrogate_proposals.json")
    parser.add_argument("--ridge", type=float, default=200.0)
    parser.add_argument("--base-count", type=int, default=6)
    parser.add_argument("--max-candidates", type=int, default=50)
    parser.add_argument("--radii", type=int, nargs="+", default=(4, 8, 12, 20))
    parser.add_argument("--external-base", type=Path)
    parser.add_argument("--method", choices=("global", "subset"),
                        default="global")
    parser.add_argument("--trials-per-base", type=int, default=200)
    parser.add_argument("--freeze-request-tiles", action="store_true")
    parser.add_argument("--rank-windows", type=Path)
    parser.add_argument("--seed", type=int, default=270924)
    args = parser.parse_args()
    orders, y, family, total = load_traces(args.traces)
    x = order_features(orders)
    validation = grouped_validation(x, y, family, args.ridge)
    coefficients, mean = fit_ridge(x, y, args.ridge)
    utility = utility_matrix(coefficients)
    external_base = (json.loads(args.external_base.read_text())
                     if args.external_base else None)
    common = dict(base_count=args.base_count,
                  max_candidates=args.max_candidates,
                  external_base=external_base, seed=args.seed)
    if args.method == "global":
        proposals = propose(orders, y, utility, mean + float(coefficients[-1]),
                            radii=tuple(args.radii), **common)
    else:
        allowed_tiles = None
        if args.freeze_request_tiles:
            from challenge.scoring_core import ChallengeScorer
            scorer = ChallengeScorer.from_files(ROOT / "scenarios" / "dev-reference")
            linked = {
                tile for rid, links in scorer.request_tiles.items()
                if rid != "RQ0015" for tile in links
            }
            allowed_tiles = set(TILES) - linked
        rank_windows = None
        if args.rank_windows:
            data = json.loads(args.rank_windows.read_text())
            if "window_by_tile" in data:
                rank_windows = {
                    tile: tuple(data["window_by_tile"][tile]) for tile in TILES
                }
            else:
                rank_windows = {
                    tile: (int(data[tile]["min_rank"]),
                           int(data[tile]["max_rank_exclusive"]) - 1)
                    for tile in TILES
                }
        proposals = propose_subset(
            orders, y, utility, mean + float(coefficients[-1]),
            trials_per_base=args.trials_per_base,
            allowed_tiles=allowed_tiles, rank_windows=rank_windows, **common,
        )
    output = {
        "scope": "public dev-reference scored-order traces only",
        "algorithm": "group-validated additive rank ridge model; exact Hungarian assignment within elite order trust neighborhoods",
        "proposal_method": args.method,
        "trace_rows": total,
        "distinct_scored_orders": len(orders),
        "best_training_score": float(y.max()),
        "ridge": args.ridge,
        "held_out_family_validation": validation,
        "proposed_count": len(proposals),
        "constructed_orders": proposals,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in output.items()
                      if k != "constructed_orders"}, sort_keys=True))


if __name__ == "__main__":
    main()
