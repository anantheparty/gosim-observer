#!/usr/bin/env python3
"""Certified pairwise non-key first-exposure residual tightening.

Each non-key tile independently contributes its maximum reduced first-success
reward to an existing key-projection upper bound. Two different tiles cannot
take overlapping first-success arcs in one real schedule. For each pair we
compute their exact joint maximum over disjoint arcs, then use a maximum-
weight matching to select disjoint pair corrections without double counting.
The projected time DP is unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import networkx as nx
import numpy as np
from numba import njit

import bounds_request_projection_k10 as kbound
import bounds_sixteen_request_k10 as sixteen


ROOT = kbound.ROOT
PRICE_FILE = kbound.PRICE_FILE
ALL17_CERT = ROOT / "results" / "practice_request_projection_k14_pilot.json"
SIXTEEN_CERT = ROOT / "results" / "practice_sixteen_request_k13_targeted.json"
NEG_INF = -(10**15)


@njit(cache=True)
def _joint_two_arc_max(
    a_start: np.ndarray, a_end: np.ndarray, a_value: np.ndarray,
    a_end_order: np.ndarray, b_start: np.ndarray, b_end: np.ndarray,
    b_value: np.ndarray, b_end_order: np.ndarray,
) -> int:
    """O(|A|+|B|) given start- and end-sorted orders of the two arc sets."""
    if len(a_start) == 0 or len(b_start) == 0:
        return NEG_INF
    before = np.empty(len(a_start), dtype=np.int64)
    p = 0
    best = NEG_INF
    for i in range(len(a_start)):
        while p < len(b_end) and b_end[b_end_order[p]] <= a_start[i]:
            value = b_value[b_end_order[p]]
            if value > best:
                best = value
            p += 1
        before[i] = best
    after = np.empty(len(a_start), dtype=np.int64)
    p = len(b_start) - 1
    best = NEG_INF
    for pos in range(len(a_start) - 1, -1, -1):
        i = a_end_order[pos]
        while p >= 0 and b_start[p] >= a_end[i]:
            value = b_value[p]
            if value > best:
                best = value
            p -= 1
        after[i] = best
    joint = NEG_INF
    for i in range(len(a_start)):
        bbest = before[i] if before[i] > after[i] else after[i]
        if bbest > NEG_INF // 2:
            value = a_value[i] + bbest
            if value > joint:
                joint = value
    return joint


def _arc_sets(data: dict, arc_starts: np.ndarray, keys: tuple[str, ...],
              deadlines: dict[str, float], instants: np.ndarray) -> dict:
    key_set = set(keys)
    by_tile = {}
    for index, tile in enumerate(data["tile_ids"]):
        if tile in key_set:
            continue
        indices = np.flatnonzero(data["complete_tile"] == index)
        starts = arc_starts[indices]
        ends = data["complete_end"][indices]
        values = data["complete_reduced"][indices]
        mandatory = tile in deadlines
        if mandatory:
            deadline_unit = int(np.searchsorted(instants, deadlines[tile], side="left"))
            allowed = starts < deadline_unit
            starts, ends, values = starts[allowed], ends[allowed], values[allowed]
            if len(starts) == 0:
                raise AssertionError(f"mandatory tile has no relaxed first arc: {tile}")
            maximum = int(np.max(values))
        else:
            maximum = int(data["tile_residual_max"][index])
            if maximum != max(0, int(np.max(values)) if len(values) else 0):
                raise AssertionError("independent tile residual changed")
        if len(starts) and np.any(starts[1:] < starts[:-1]):
            raise AssertionError("arc starts are not sorted")
        by_tile[tile] = {
            "start": starts, "end": ends, "value": values,
            "end_order": np.argsort(ends, kind="stable"),
            "mandatory": mandatory, "maximum": maximum,
        }
    return by_tile


def pair_joint(a: dict, b: dict) -> int:
    both = int(_joint_two_arc_max(
        a["start"], a["end"], a["value"], a["end_order"],
        b["start"], b["end"], b["value"], b["end_order"],
    ))
    # An optional tile may be omitted. Mandatory tiles must contribute one
    # successful first-exposure arc each in the selected request branch.
    if not a["mandatory"]:
        both = max(both, b["maximum"])
    if not b["mandatory"]:
        both = max(both, a["maximum"])
    return both


def _matching_bound(data: dict, arc_starts: np.ndarray, instants: np.ndarray,
                    keys: tuple[str, ...], deadlines: dict[str, float],
                    certified_external: int) -> dict:
    tiles = _arc_sets(data, arc_starts, keys, deadlines, instants)
    independent = int(data["prices"].sum()) + sum(t["maximum"] for t in tiles.values())
    if independent != certified_external:
        raise AssertionError(f"published external term mismatch: {independent} != {certified_external}")
    graph = nx.Graph()
    graph.add_nodes_from(tiles)
    tested = 0
    positive_pairs = []
    tile_rows = list(tiles.items())
    for i, (tile_a, a) in enumerate(tile_rows):
        for tile_b, b in tile_rows[i + 1:]:
            tested += 1
            if not a["mandatory"] and a["maximum"] == 0:
                continue
            if not b["mandatory"] and b["maximum"] == 0:
                continue
            joint = pair_joint(a, b)
            if joint <= NEG_INF // 2:
                # Two mandatory first exposures cannot be scheduled together.
                # An actual branch is therefore infeasible, even in this
                # relaxed two-tile subproblem.
                return {"feasible_relaxation": False,
                        "incompatible_mandatory_pair": [tile_a, tile_b]}
            saving = a["maximum"] + b["maximum"] - joint
            if saving < 0:
                raise AssertionError("pair max exceeds independent residuals")
            if saving > 0:
                positive_pairs.append({"tile_a": tile_a, "tile_b": tile_b,
                                       "saving_cents": int(saving)})
                graph.add_edge(tile_a, tile_b, weight=int(saving), joint_cents=joint)
    matching = nx.algorithms.matching.max_weight_matching(graph, maxcardinality=False,
                                                            weight="weight")
    pairs = []
    for aa, bb in matching:
        a, b = sorted((aa, bb))
        pairs.append({"tile_a": a, "tile_b": b,
                      "saving_cents": int(graph[a][b]["weight"]),
                      "joint_cents": int(graph[a][b]["joint_cents"]),
                      "individual_sum_cents": tiles[a]["maximum"] + tiles[b]["maximum"]})
    pairs.sort(key=lambda row: (-row["saving_cents"], row["tile_a"], row["tile_b"]))
    saving = sum(row["saving_cents"] for row in pairs)
    return {
        "feasible_relaxation": True,
        "nonkey_tile_count": len(tiles),
        "pair_count": tested,
        "positive_pair_count": len(positive_pairs),
        "positive_pairs": positive_pairs,
        "matched_pair_count": len(pairs),
        "independent_external_cents": independent,
        "pair_saving_cents": saving,
        "matched_pairs": pairs,
        "paired_external_cents": independent - saving,
    }


def _all17(data: dict, cert: dict, arc_starts: np.ndarray, instants: np.ndarray) -> dict:
    inputs = kbound._instance_inputs(data)
    if not np.array_equal(instants, inputs["instants"]):
        raise AssertionError("time-grid mismatch")
    rows = []
    for case in cert["cases"]:
        keys = tuple(case["keys"])
        if len(keys) != 14 or len(case["branches"]) != 2:
            continue
        for branch_idx, old in enumerate(case["branches"]):
            match = _matching_bound(data, arc_starts, instants, keys,
                                    inputs["deadlines_by_branch"][branch_idx],
                                    int(old["external_cents"]))
            after = None if not match["feasible_relaxation"] else (
                int(old["conditional_upper_cents"]) - match["pair_saving_cents"]
            )
            rows.append({"keys": list(keys), "rq0004_branch": branch_idx,
                         "old_upper_cents": int(old["conditional_upper_cents"]),
                         "paired_upper_cents": after, "matching": match})
    if not rows:
        raise AssertionError("no 14-key cases")
    cases = {}
    for row in rows:
        keys = tuple(row["keys"])
        cases.setdefault(keys, []).append(row)
    best_case_upper = min(max(row["paired_upper_cents"] for row in case)
                          for case in cases.values())
    return {"kind": "all17", "source_all17_upper_cents": int(cert["all_awarded_upper_cents"]),
            "pair_matched_all17_upper_cents": best_case_upper, "rows": rows}


def _exactly16(data: dict, cert: dict, arc_starts: np.ndarray,
               instants: np.ndarray) -> dict:
    choices, _, _, subset, _ = sixteen._certified_inputs(data)
    lookup = {request.request_id: i for i, (request, _) in enumerate(choices)}
    keys = tuple(cert["keys"])
    rows = []
    for item in cert["branch_rows"]:
        refined = item["thirteen_key_refinement"]
        if refined is None:
            rows.append({"missed_request": item["missed_request"],
                         "rq0004_branch": item["rq0004_branch"],
                         "old_merged_upper_cents": item["merged_upper_cents"],
                         "paired_merged_upper_cents": item["merged_upper_cents"],
                         "matching": None})
            continue
        missed = lookup[item["missed_request"]]
        deadlines = {}
        for i, (request, options) in enumerate(choices):
            if i == missed:
                continue
            branch = item["rq0004_branch"] if i == 3 else 0
            for tile in options[branch]:
                deadline = request.deadline_utc.timestamp()
                deadlines[tile] = min(deadlines.get(tile, deadline), deadline)
        match = _matching_bound(data, arc_starts, instants, keys, deadlines,
                                int(refined["external_cents"]))
        new_upper = (None if not match["feasible_relaxation"] else
                     min(int(item["ten_key_upper_cents"]),
                         int(refined["upper_cents"]) - match["pair_saving_cents"]))
        rows.append({"missed_request": item["missed_request"],
                     "rq0004_branch": item["rq0004_branch"],
                     "old_merged_upper_cents": item["merged_upper_cents"],
                     "paired_merged_upper_cents": new_upper, "matching": match})
    if len(rows) != 33:
        raise AssertionError("exactly-16 branch enumeration changed")
    maximum = max(row["paired_merged_upper_cents"] for row in rows
                  if row["paired_merged_upper_cents"] is not None)
    return {"kind": "exactly16", "source_exactly16_upper_cents":
            int(cert["exactly_sixteen_upper_cents"]),
            "pair_matched_exactly16_upper_cents": maximum,
            "at_most_fifteen_upper_cents": int(cert["at_most_fifteen_upper_cents"]),
            "rows": rows}


def _self_test() -> dict:
    rng = np.random.default_rng(3186)
    cases = 0
    for _ in range(1000):
        arrays = []
        for _tile in range(2):
            n = int(rng.integers(0, 8))
            start = rng.integers(0, 15, n, dtype=np.int64)
            end = start + rng.integers(1, 6, n, dtype=np.int64)
            value = rng.integers(-9, 17, n, dtype=np.int64)
            order = np.argsort(start, kind="stable")
            start, end, value = start[order], end[order], value[order]
            mandatory = bool(rng.integers(0, 2))
            if mandatory and not n:
                mandatory = False
            arrays.append({"start": start, "end": end, "value": value,
                           "end_order": np.argsort(end, kind="stable"),
                           "mandatory": mandatory,
                           "maximum": int(np.max(value)) if mandatory else
                           max(0, int(np.max(value)) if n else 0)})
        a, b = arrays
        got = pair_joint(a, b)
        brute = NEG_INF
        aa = range(len(a["start"])) if a["mandatory"] else range(-1, len(a["start"]))
        bb = range(len(b["start"])) if b["mandatory"] else range(-1, len(b["start"]))
        for i in aa:
            for j in bb:
                if i >= 0 and j >= 0 and not (
                    a["end"][i] <= b["start"][j] or
                    b["end"][j] <= a["start"][i]
                ):
                    continue
                score = (int(a["value"][i]) if i >= 0 else 0) + (
                    int(b["value"][j]) if j >= 0 else 0)
                brute = max(brute, score)
        if got != brute:
            raise AssertionError(f"pair sweep mismatch: {got} != {brute}")
        cases += 1
    return {"random_tiny_pair_cases": cases, "mismatches": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all17-cert", type=Path, default=ALL17_CERT)
    parser.add_argument("--exactly16-cert", type=Path, default=SIXTEEN_CERT)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "results" / "practice_nonkey_pair_matching.json")
    args = parser.parse_args()
    test = _self_test()
    data, audit = kbound._load_audited_data(PRICE_FILE)
    all17 = json.loads(args.all17_cert.read_text())
    exactly16 = json.loads(args.exactly16_cert.read_text())
    if (all17["certificates"]["price_sha256"] != audit["price_sha256"] or
            exactly16["capacity_price_sha256"] != audit["price_sha256"]):
        raise AssertionError("capacity-price certificate mismatch")
    instants = kbound._instance_inputs(data)["instants"]
    arc_starts = np.repeat(np.arange(data["n"], dtype=np.int32),
                           np.diff(data["complete_ptr"]))
    result17 = _all17(data, all17, arc_starts, instants)
    result16 = _exactly16(data, exactly16, arc_starts, instants)
    global_upper = max(result17["pair_matched_all17_upper_cents"],
                       result16["pair_matched_exactly16_upper_cents"],
                       result16["at_most_fifteen_upper_cents"])
    result = {
        "scope": "public dev-reference, all valid decision traces",
        "capacity_price_sha256": audit["price_sha256"],
        "all17_certificate_sha256": hashlib.sha256(args.all17_cert.read_bytes()).hexdigest(),
        "exactly16_certificate_sha256": hashlib.sha256(args.exactly16_cert.read_bytes()).hexdigest(),
        "scalar_audit": audit["scalar_audit"],
        "self_test": test,
        "complete_arc_count": int(data["complete_arc_count"]),
        "all17": result17,
        "exactly16": result16,
        "unconditional_upper_cents": global_upper,
        "proof_note": (
            "For any branch and non-key tile i, its actual first-success arc "
            "is one element of the audited feasible arc set, restricted by "
            "the selected request deadline when mandatory. The old external "
            "term uses independent maxima M_i of reduced rewards. For any "
            "two tiles i,j, actual first arcs cannot overlap, so their sum "
            "is at most the exact pair maximum J_ij. Replacing M_i+M_j by "
            "J_ij saves delta_ij >= 0. A matching uses each tile at most once, "
            "so all selected savings are simultaneously valid. The key-tile "
            "projected DP, request terms, and capacity-price constant remain "
            "the previously certified ones."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                   sort_keys=True) + "\n")
    print(json.dumps({
        "all17_before_cents": result17["source_all17_upper_cents"],
        "all17_after_cents": result17["pair_matched_all17_upper_cents"],
        "exactly16_before_cents": result16["source_exactly16_upper_cents"],
        "exactly16_after_cents": result16["pair_matched_exactly16_upper_cents"],
        "unconditional_upper_cents": global_upper,
        "self_test": test,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
