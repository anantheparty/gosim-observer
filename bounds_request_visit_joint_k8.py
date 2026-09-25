#!/usr/bin/env python3
"""Exact request-witness residuals for the audited eight-tile projection.

Only the all-17-awarded branch is recomputed. Every other award subset retains
its earlier, exhaustive upper bound. The per-tile residual jointly prices the
first successful scientific exposure and one distinct successful tagged visit
for each awarded request that chose this non-key tile.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

import bounds_practice_projection as projection
from bounds_request_conditioned import PRACTICE, ROOT, request_branches
from bounds_request_projection import calculate_conditional
from bounds_request_visit_joint import tile_value


PRICE_FILE = ROOT / "results" / "practice_global_interval_prices.npz"
PROJECTION_CERT = ROOT / "results" / "projected_wait_global_k8_certificate.json"
CONDITIONAL_CERT = ROOT / "results" / "practice_request_global_k8_conditional.json"
UNCONDITIONAL_CERT = ROOT / "results" / "practice_global_k8_unconditional.json"


def certify(prices_path: Path = PRICE_FILE, theta_cents: int = 140) -> dict:
    prices_sha = hashlib.sha256(prices_path.read_bytes()).hexdigest()
    projected = json.loads(PROJECTION_CERT.read_text())
    conditional = json.loads(CONDITIONAL_CERT.read_text())
    unconditional = json.loads(UNCONDITIONAL_CERT.read_text())
    old_prices_sha = projected["price_sha256"]
    if (conditional["price_sha256"] != old_prices_sha
            or unconditional["capacity_price_sha256"] != old_prices_sha):
        raise AssertionError("published baseline certificates use different prices")
    reused_published_projection = prices_sha == old_prices_sha and theta_cents == 140
    key_tiles = tuple(conditional["key_tiles"])
    if tuple(projected["results"][0]["key_tiles"]) != key_tiles:
        raise AssertionError("key-tile projection changed")
    if conditional["theta_uniform_cents"] != 140:
        raise AssertionError("expected audited theta = 140 cents")
    for name in ("omitted_scalar_legal_arcs", "omitted_weather_interruption_arcs",
                 "max_envelope_violation_cents"):
        if projected["scalar_audit"][name] != 0:
            raise AssertionError(f"prior full scalar audit failed: {name}")
    if projected["complete_arc_count"] != conditional["candidate_count"]:
        raise AssertionError("complete-arc counts differ")
    if unconditional["unconditional_upper_bound_cents"] != conditional["conditional_total_upper_cents"]:
        raise AssertionError("published maximizer is not the all-awarded branch")

    data = projection.build_data(PRACTICE, prices_path, audit=False)
    if data["complete_arc_count"] != projected["complete_arc_count"]:
        raise AssertionError("arc enumeration changed")
    if data["partial_arc_count"] != projected["weather_interruption_arc_count"]:
        raise AssertionError("weather interruption enumeration changed")
    if data["impossible_requests"] != ["RQ0015"]:
        raise AssertionError("request opportunity set changed")
    scorer = data["scorer"]
    choices = request_branches(scorer, data["impossible_requests"])
    if len(choices) != 17 or np.any(data["prices"] < 0):
        raise AssertionError("request count or nonnegative-price premise changed")
    if any(len(options) != 1 for request, options in choices if request.request_id != "RQ0004"):
        raise AssertionError("unexpected request-choice branch")

    instants = np.fromiter(
        (slot.timestamp_utc.timestamp() + 150 * k
         for slot in scorer.slots for k in range(6)),
        dtype=np.float64, count=data["n"],
    )
    starts_all = np.repeat(np.arange(data["n"], dtype=np.int32),
                           np.diff(data["complete_ptr"]))
    price_prefix = np.empty(data["n"] + 1, dtype=np.int64)
    price_prefix[0] = 0
    np.cumsum(data["prices"], out=price_prefix[1:])
    fresh_projected = None
    earliest_terminal_unit = None
    if not reused_published_projection:
        # This first DP also fills the exact scorer actionability cache needed
        # by calculate_conditional. The audited graph and science envelopes are
        # price independent; only the reduced costs must be recomputed.
        fresh_projected = projection.calculate(data, list(key_tiles), theta_cents)
        last_available = max(
            request.available_from_utc.timestamp() for request, _ in choices
        )
        earliest_terminal_unit = int(np.searchsorted(
            instants, last_available, side="left"
        ))
    key_set = set(key_tiles)
    arc_table = {}
    for tile_index, tile_id in enumerate(data["tile_ids"]):
        if tile_id in key_set:
            continue
        mask = data["complete_tile"] == tile_index
        arc_table[tile_id] = (
            starts_all[mask], data["complete_end"][mask],
            data["complete_reduced"][mask],
            int(data["tile_residual_max"][tile_index]),
        )
    price_sum = int(price_prefix[-1])
    other_award_subsets_cents = max(
        int(row["upper_cents"]) for row in unconditional["best_by_awarded_count"]
        if row["awarded_count"] < len(choices)
    )

    rows = []
    for selected in itertools.product(*(options for _, options in choices)):
        selection = {request.request_id: tuple(tiles)
                     for (request, _), tiles in zip(choices, selected)}
        needed = defaultdict(list)
        for request, _ in choices:
            for tile_id in selection[request.request_id]:
                if tile_id not in key_set:
                    needed[tile_id].append(request)
        if any(len(requests) > 2 for requests in needed.values()):
            raise AssertionError("local DP supports at most two tags per tile")
        externally_priced = price_sum
        old_externally_priced = price_sum
        tile_rows = []
        feasible = True
        for tile_id, (starts, ends, reduced, free) in arc_table.items():
            reqs = needed.get(tile_id, ())
            if reqs:
                deadline = min(r.deadline_utc.timestamp() for r in reqs)
                valid_old = reduced[instants[starts] < deadline]
                old = int(valid_old.max()) if len(valid_old) else None
                joint = tile_value(
                    starts, ends, reduced, price_prefix, instants, list(reqs)
                )
                if old is None or joint is None:
                    feasible = False
                    break
                if joint > old or old > free:
                    raise AssertionError("joint local residual violates prior envelope")
                externally_priced += joint
                old_externally_priced += old
                tile_rows.append({
                    "tile_id": tile_id,
                    "request_ids": [r.request_id for r in reqs],
                    "old_first_before_deadline_cents": old,
                    "joint_first_and_witness_cents": joint,
                    "extra_witness_loss_cents": old - joint,
                })
            else:
                externally_priced += free
                old_externally_priced += free
        branch_choice = {
            request_id: list(tiles) for request_id, tiles in selection.items()
            if len(scorer.request_tiles[request_id]) != len(tiles)
        }
        if reused_published_projection:
            previous = [row for row in conditional["branches"]
                        if row["choice_by_request"] == branch_choice]
            if len(previous) != 1:
                raise AssertionError("audited conditional branch missing")
            prior = previous[0]
        else:
            prior = calculate_conditional(
                data, list(key_tiles), theta_cents, selection,
                instants, starts_all, earliest_terminal_unit,
            )
            if prior["choice_by_request"] != branch_choice:
                raise AssertionError("fresh branch choice differs")
        if not feasible:
            rows.append({"choice_by_request": branch_choice, "feasible": False})
            continue
        if old_externally_priced != prior["external_science_cents"]:
            raise AssertionError("old external branch residual did not reproduce")
        fixed = (int(prior["request_cents"]) + int(prior["theta_constant_cents"])
                 + int(prior["projected_dp_cents"]))
        joint_bound = externally_priced + fixed
        if joint_bound > prior["total_upper_bound_cents"]:
            raise AssertionError("joint branch exceeded audited old upper bound")
        rows.append({
            "choice_by_request": branch_choice,
            "feasible": True,
            "old_branch_upper_cents": int(prior["total_upper_bound_cents"]),
            "joint_branch_upper_cents": joint_bound,
            "external_science_and_capacity_cents": externally_priced,
            "fixed_projection_and_request_cents": fixed,
            "extra_witness_loss_cents": int(prior["total_upper_bound_cents"] - joint_bound),
            "tiles_with_awarded_request": tile_rows,
        })
    feasible_rows = [row for row in rows if row["feasible"]]
    if not feasible_rows:
        raise AssertionError("all-awarded branch became infeasible")
    all_awarded_cents = max(row["joint_branch_upper_cents"] for row in feasible_rows)
    global_cents = max(other_award_subsets_cents, all_awarded_cents)
    best_known_cents = min(global_cents, unconditional["unconditional_upper_bound_cents"])
    return {
        "scope": "public dev-reference, all valid decision traces",
        "price_sha256": prices_sha,
        "prior_projection_sha256": hashlib.sha256(PROJECTION_CERT.read_bytes()).hexdigest(),
        "prior_conditional_sha256": hashlib.sha256(CONDITIONAL_CERT.read_bytes()).hexdigest(),
        "prior_unconditional_sha256": hashlib.sha256(UNCONDITIONAL_CERT.read_bytes()).hexdigest(),
        "key_tiles": list(key_tiles),
        "theta_uniform_cents": theta_cents,
        "successful_exposure_arcs": int(data["complete_arc_count"]),
        "capacity_units": int(data["n"]),
        "positive_price_units": int(np.count_nonzero(data["prices"])),
        "reused_published_projection": reused_published_projection,
        "fresh_projected_unconditional_upper_cents": (
            None if fresh_projected is None
            else int(fresh_projected["total_upper_bound_cents"])
        ),
        "prior_unconditional_upper_cents": int(unconditional["unconditional_upper_bound_cents"]),
        "other_award_subsets_upper_cents": other_award_subsets_cents,
        "all_awarded_joint_upper_cents": all_awarded_cents,
        "combined_unconditional_upper_cents": global_cents,
        "best_known_unconditional_upper_cents": best_known_cents,
        "strict_improvement_cents": int(unconditional["unconditional_upper_bound_cents"] - best_known_cents),
        "branches": rows,
        "proof_note": (
            "For each all-awarded branch, price each non-key tile's first "
            "successful scientific arc and every distinct required tagged "
            "witness arc jointly. Their distinct union is a capacity-feasible "
            "subset of any actual schedule, so nonnegative unit prices are "
            "paid at most once. Each local exact maximum upper-bounds its "
            "tile's scientific reward minus those prices. Key-tile witness "
            "restrictions remain relaxed in the audited projected DP. Every "
            "other award subset is bounded by the earlier exhaustive subset "
            "certificate, and the maximum of the two cases is unconditional."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path, default=PRICE_FILE)
    parser.add_argument("--theta-cents", type=int, default=140)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "results" / "practice_request_visit_joint_k8.json")
    args = parser.parse_args()
    result = certify(args.prices, args.theta_cents)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                   sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "prior_upper": result["prior_unconditional_upper_cents"] / 100,
        "joint_all_awarded_upper": result["all_awarded_joint_upper_cents"] / 100,
        "other_subsets_upper": result["other_award_subsets_upper_cents"] / 100,
        "global_upper": result["combined_unconditional_upper_cents"] / 100,
        "best_known_upper": result["best_known_unconditional_upper_cents"] / 100,
        "improvement_cents": result["strict_improvement_cents"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
