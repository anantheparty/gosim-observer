#!/usr/bin/env python3
"""Greedy parameter scan for a proven order-free request/wait projection.

Every displayed value is a valid *conditional* bound given all 17 feasible
request rewards. It becomes unconditional only after the other request subsets
are separately bounded. K is augmented one tile at a time; no tile order is
fixed in the path DP. This scan is a parameter search, not a proof that the
chosen K is the best subset of its size.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path

import numpy as np

import bounds_practice_projection as projection
from bounds_request_conditioned import PRACTICE, request_branches
from bounds_request_projection import calculate_conditional


DEFAULT_KEYS = ("T00018", "T00029", "T00030", "T00031")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path,
                        default=Path("results/practice_global_interval_prices.npz"))
    parser.add_argument("--keys", default=",".join(DEFAULT_KEYS))
    parser.add_argument("--theta", type=int, default=134)
    parser.add_argument("--max-k", type=int, default=8)
    parser.add_argument("--theta-scan", action="store_true")
    parser.add_argument("--out", type=Path,
                        default=Path("results/practice_global_key_scan.json"))
    args = parser.parse_args()

    clock = time.monotonic()
    data = projection.build_data(PRACTICE, args.prices, False)
    scorer = data["scorer"]
    tile_ids = data["tile_ids"]
    keys = [name for name in args.keys.split(",") if name]
    if len(set(keys)) != len(keys) or any(k not in tile_ids for k in keys):
        raise ValueError("invalid initial key set")
    if args.max_k > 8:
        raise ValueError("uint8 actionable masks support at most eight keys")
    choices = request_branches(scorer, data["impossible_requests"])
    branches = [
        {request.request_id: selected
         for (request, _), selected in zip(choices, choice)}
        for choice in itertools.product(*(options for _, options in choices))
    ]
    instants = np.array([
        slot.timestamp_utc.timestamp() + 150 * offset
        for slot in scorer.slots for offset in range(6)
    ], dtype=np.float64)
    arc_starts = np.repeat(
        np.arange(data["n"], dtype=np.int32),
        np.diff(data["complete_ptr"]),
    )
    earliest_terminal = int(np.searchsorted(
        instants,
        max(r.available_from_utc.timestamp() for r, _ in choices),
        side="left",
    ))
    history = []

    def bound_for(tile_set, theta):
        # The unconditional projection call populates the exact scorer
        # actionability cache for any newly added tile.
        base = projection.calculate(data, tile_set, theta)
        conditional = [
            calculate_conditional(
                data, tile_set, theta, branch, instants,
                arc_starts, earliest_terminal,
            ) for branch in branches
        ]
        valid = [c["total_upper_bound_cents"] for c in conditional
                 if c["feasible_relaxation"]]
        if not valid:
            return None, base["total_upper_bound_cents"]
        return max(valid), base["total_upper_bound_cents"]

    theta = args.theta
    initial, base = bound_for(keys, theta)
    print(json.dumps({"stage": len(keys), "keys": keys,
                      "theta": theta, "conditional_cents": initial,
                      "base_cents": base,
                      "elapsed_seconds": time.monotonic() - clock}), flush=True)
    history.append({"keys": keys[:], "theta": theta,
                    "conditional_cents": initial, "base_cents": base})
    if args.theta_scan and len(keys) == args.max_k:
        sweep = []
        for candidate_theta in range(0, 301, 10):
            v, b = bound_for(keys, candidate_theta)
            sweep.append((v, b, candidate_theta))
        sweep.sort()
        theta = sweep[0][2]
        history[-1]["theta_scan"] = [
            {"theta": t, "conditional_cents": v, "base_cents": b}
            for v, b, t in sorted(sweep, key=lambda item: item[2])
        ]
        print(json.dumps({"stage": len(keys), "best_theta": theta,
                          "best_conditional_cents": sweep[0][0],
                          "elapsed_seconds": time.monotonic() - clock}), flush=True)
    while len(keys) < args.max_k:
        contenders = []
        for candidate in tile_ids:
            if candidate in keys:
                continue
            trial = keys + [candidate]
            result, base = bound_for(trial, theta)
            if result is None:
                continue
            contenders.append((result, base, candidate))
        contenders.sort()
        if not contenders:
            break
        best, base, candidate = contenders[0]
        keys.append(candidate)
        entry = {"keys": keys[:], "theta": theta,
                 "conditional_cents": best, "base_cents": base,
                 "candidate_count": len(contenders),
                 "next_best_candidates": [
                     {"tile_id": t, "conditional_cents": v, "base_cents": b}
                     for v, b, t in contenders[:12]
                 ]}
        history.append(entry)
        print(json.dumps({"stage": len(keys), **entry,
                          "elapsed_seconds": time.monotonic() - clock}), flush=True)
        if args.theta_scan:
            sweep = []
            for candidate_theta in range(0, 301, 10):
                v, b = bound_for(keys, candidate_theta)
                sweep.append((v, b, candidate_theta))
            sweep.sort()
            theta = sweep[0][2]
            entry["theta_scan"] = [
                {"theta": t, "conditional_cents": v, "base_cents": b}
                for v, b, t in sorted(sweep, key=lambda item: item[2])
            ]
            print(json.dumps({"stage": len(keys), "best_theta": theta,
                              "best_conditional_cents": sweep[0][0],
                              "elapsed_seconds": time.monotonic() - clock}), flush=True)
    payload = {"scope": "conditional on all 17 feasible request rewards",
               "capacity_price_file": str(args.prices), "scan": history,
               "runtime_seconds": time.monotonic() - clock}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
