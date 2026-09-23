#!/usr/bin/env python3
"""Certify a science bound conditional on earning all 17 feasible requests.

Only the publicly generated dev-reference practice instance is accepted. The
saved nonnegative capacity prices are a dual certificate; optimization is not
needed to verify the bound. All sums and maxima use integer score cents.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from bounds_practice_resource import all_arcs
import bounds_public as geometry
from challenge.scoring_core import ChallengeScorer


ROOT = Path(__file__).resolve().parent
PRACTICE = ROOT / "scenarios" / "dev-reference"
DEFAULT_PRICES = ROOT / "runs" / "practice_bound" / "resource_prices.npz"


def request_branches(scorer: ChallengeScorer, impossible: list[str]):
    """Return every minimal tile-choice branch for the feasible requests."""
    if impossible != ["RQ0015"]:
        raise ValueError(f"expected exactly RQ0015 impossible, got {impossible}")
    choices = []
    for request in sorted(scorer.requests.values(), key=lambda r: r.request_id):
        if request.request_id in impossible:
            continue
        links = scorer.request_tiles[request.request_id]
        if any(visits != 1 for visits in links.values()):
            raise ValueError("practice proof assumes one tagged visit per requested tile")
        if not 1 <= request.required_tile_count <= len(links):
            raise ValueError(f"invalid request cardinality: {request.request_id}")
        options = list(itertools.combinations(sorted(links), request.required_tile_count))
        choices.append((request, options))
    if len(choices) != 17:
        raise ValueError(f"expected 17 feasible requests, got {len(choices)}")
    return choices


def evaluate_branch(
    instants: np.ndarray,
    starts: list[np.ndarray],
    ends: list[np.ndarray],
    rewards: list[np.ndarray],
    prices: np.ndarray,
    tile_ids: list[str],
    deadlines: dict[str, float],
) -> dict:
    prefix = np.empty(len(prices) + 1, dtype=np.int64)
    prefix[0] = 0
    np.cumsum(prices, out=prefix[1:])
    capacity_sum = int(prefix[-1])
    dual_total = capacity_sum
    unpriced_total = 0
    details = []
    for tile_id, a, b, reward in zip(tile_ids, starts, ends, rewards):
        constrained = tile_id in deadlines
        allowed = (instants[a] < deadlines[tile_id]) if constrained else np.ones(len(a), dtype=np.bool_)
        if constrained and not np.any(allowed):
            return {"feasible_relaxation": False, "missing_tile": tile_id}
        if not len(a):
            details.append({"tile_id": tile_id, "mandatory": False,
                            "best_science_cents": 0, "best_reduced_cents": 0})
            continue
        reduced = reward - (prefix[b] - prefix[a])
        if constrained:
            best_science = int(np.max(reward[allowed]))
            best_reduced = int(np.max(reduced[allowed]))
            allowed_count = int(np.count_nonzero(allowed))
        else:
            best_science = max(0, int(np.max(reward)))
            best_reduced = max(0, int(np.max(reduced)))
            allowed_count = len(a)
        unpriced_total += best_science
        dual_total += best_reduced
        if constrained:
            details.append({
                "tile_id": tile_id,
                "deadline_utc": datetime.fromtimestamp(
                    deadlines[tile_id], timezone.utc
                ).isoformat().replace("+00:00", "Z"),
                "candidate_count": len(a),
                "allowed_count": allowed_count,
                "best_science_cents": best_science,
                "unrestricted_science_cents": int(np.max(reward)),
                "best_reduced_cents": best_reduced,
                "unrestricted_reduced_cents": int(np.max(reduced)),
            })
    return {
        "feasible_relaxation": True,
        "mandatory_tile_count": len(deadlines),
        "unpriced_science_upper_cents": unpriced_total,
        "resource_science_upper_cents": dual_total,
        "capacity_price_sum_cents": capacity_sum,
        "mandatory_tiles": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path, default=DEFAULT_PRICES)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    scenario = PRACTICE
    instants, starts, ends, rewards, request_upper_cents, impossible = all_arcs(scenario)
    scorer = ChallengeScorer.from_files(scenario)
    tile_ids = list(scorer.tiles)
    arc_tile_ids = [row["tile_id"] for row in geometry._read_csv(
        scenario / "outputs" / "reference" / "tiles.csv"
    )]
    if tile_ids != arc_tile_ids or len(tile_ids) != len(starts):
        raise AssertionError("scorer and arc tile ordering differ")
    if scorer.mechanics or scorer.tile_anomalies or float(scorer.config.get("coverage_bonus_weight", 0.0)):
        raise ValueError("this proof applies only to the non-anomaly practice score")
    with np.load(args.prices, allow_pickle=False) as loaded:
        prices = loaded["prices_cents"]
    if prices.shape != (len(instants),) or not np.issubdtype(prices.dtype, np.integer) or np.any(prices < 0):
        raise ValueError("prices must be nonnegative integer cents for every capacity unit")
    prices = prices.astype(np.int64, copy=False)
    choices = request_branches(scorer, impossible)
    expected_reward_cents = sum(round(100 * request.completion_reward) for request, _ in choices)
    if request_upper_cents != expected_reward_cents or request_upper_cents != 392000:
        raise AssertionError("practice request reward changed")
    branch_count = 1
    for _, options in choices:
        branch_count *= len(options)
    if branch_count > 1000:
        raise ValueError("too many branches for explicit certification")
    branches = []
    for selected in itertools.product(*(options for _, options in choices)):
        deadlines = {}
        selected_by_request = {}
        for (request, _), tiles in zip(choices, selected):
            selected_by_request[request.request_id] = list(tiles)
            deadline = request.deadline_utc.timestamp()
            for tile in tiles:
                deadlines[tile] = min(deadline, deadlines.get(tile, deadline))
        result = evaluate_branch(
            instants, starts, ends, rewards, prices, tile_ids, deadlines,
        )
        result["choice_by_request"] = {
            request_id: tiles for request_id, tiles in selected_by_request.items()
            if len(scorer.request_tiles[request_id]) != len(tiles)
        }
        if result["feasible_relaxation"]:
            result["conditional_total_upper_cents"] = (
                result["resource_science_upper_cents"] + request_upper_cents
            )
        branches.append(result)
    feasible = [branch for branch in branches if branch["feasible_relaxation"]]
    if not feasible:
        raise AssertionError("all-request condition is impossible under relaxed tile deadlines")
    winning = max(feasible, key=lambda item: item["resource_science_upper_cents"])
    output = {
        "scope": "dev-reference; conditional on all 17 feasible request rewards",
        "candidate_count": sum(len(a) for a in starts),
        "capacity_units": len(instants),
        "request_reward_cents": request_upper_cents,
        "impossible_request_ids": impossible,
        "branch_count": branch_count,
        "branches": branches,
        "conditional_science_upper_cents": winning["resource_science_upper_cents"],
        "conditional_total_upper_cents": winning["conditional_total_upper_cents"],
        "price_certificate": str(args.prices.relative_to(ROOT))
        if args.prices.is_relative_to(ROOT) else str(args.prices),
        "price_sha256": hashlib.sha256(args.prices.read_bytes()).hexdigest(),
    }
    compact = {key: value for key, value in output.items() if key != "branches"}
    compact["branch_summaries"] = [
        {key: value for key, value in b.items() if key != "mandatory_tiles"}
        for b in branches
    ]
    print(json.dumps(compact, ensure_ascii=False, sort_keys=True))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
