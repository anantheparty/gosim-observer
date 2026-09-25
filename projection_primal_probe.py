#!/usr/bin/env python3
"""Probe whether a certified K14 projected optimum yields a better real path.

This is a bounded diagnostic, not a proof or an online submission. The
projection accounts for nonkey first exposures independently, so its selected
arcs need not form a time-feasible or request-witness-feasible schedule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

import bounds_request_projection_k10 as bound
import projected_price_search as price_search
import sequence_active_requests_dp as active
from practice_lns import PracticeModel
from sequence_block_dp import _write
from sequence_dp import score_table


ROOT = Path(__file__).resolve().parent
CERT = ROOT / "results/practice_request_projection_k14_pilot.json"
BEST = ROOT / "results/practice_best.csv"


def _projected_trace(data: dict, inputs: dict, keys: tuple[str, ...], branch: int,
                     expected: dict) -> list[dict]:
    key_index = np.full(len(data["tile_ids"]), -1, np.int8)
    required = mandatory = 0
    deadlines = np.full(len(keys), data["n"], np.int32)
    for b, tile in enumerate(keys):
        i = data["tile_ids"].index(tile)
        key_index[i] = b
        bound._populate_actionability(data, tile)
        if data["scorer"].tiles[tile].scheduling_class == "REQUIRED":
            required |= 1 << b
        if tile in inputs["deadlines_by_branch"][branch]:
            mandatory |= 1 << b
            deadlines[b] = np.searchsorted(
                inputs["instants"], inputs["deadlines_by_branch"][branch][tile],
                side="left",
            )
    actionable = np.zeros(data["n"], np.uint16)
    for b, tile in enumerate(keys):
        actionable[data["actionable_cache"][tile]] |= np.uint16(1 << b)
    theta = np.full(len(data["tile_ids"]), 135, np.int64)
    theta[key_index >= 0] = 0
    dp, chosen = price_search._dp_with_trace(
        data["n"], data["complete_ptr"], data["complete_end"],
        data["complete_tile"], data["complete_reduced"],
        data["complete_tagged"], data["partial_ptr"], data["partial_end"],
        actionable, key_index, required, mandatory, deadlines,
        inputs["earliest_terminal_unit"], theta, len(keys),
    )
    if dp != int(expected["dp_cents"]) or required != expected["required_key_mask"]:
        raise AssertionError(f"K14 trace fails published DP check: {dp}")
    if mandatory != expected["mandatory_key_mask"] or np.any(deadlines != expected["key_deadline_unit"]):
        raise AssertionError("request branch masks/deadlines differ from certificate")
    if np.any(chosen < 0):
        raise AssertionError("projected optimum omitted a key first exposure")
    return [_arc(data, inputs, int(j), "key_dp") for j in chosen]


def _arc(data: dict, inputs: dict, j: int, kind: str) -> dict:
    i = int(data["complete_tile"][j])
    return {
        "tile_id": data["tile_ids"][i], "start": int(inputs["arc_starts"][j]),
        "end": int(data["complete_end"][j]),
        "reduced_cents": int(data["complete_reduced"][j]),
        "arc_index": j, "kind": kind,
    }


def _nonkey_choices(data: dict, inputs: dict, keys: tuple[str, ...], branch: int) -> list[dict]:
    rows = []
    keyset = set(keys)
    for i, tile in enumerate(data["tile_ids"]):
        if tile in keyset:
            continue
        js = np.flatnonzero(data["complete_tile"] == i)
        if tile in inputs["deadlines_by_branch"][branch]:
            deadline = np.searchsorted(
                inputs["instants"], inputs["deadlines_by_branch"][branch][tile],
                side="left",
            )
            js = js[inputs["arc_starts"][js] < deadline]
        if len(js) == 0:
            raise AssertionError(f"nonkey mandatory tile {tile} has no first arc")
        maximum = int(np.max(data["complete_reduced"][js]))
        tied = js[data["complete_reduced"][js] == maximum]
        # Earliest maximizer gives a deterministic representative; all ties
        # remain equivalent for the bound but may have different conflicts.
        j = int(tied[np.argmin(inputs["arc_starts"][tied])])
        row = _arc(data, inputs, j, "nonkey_independent")
        row["maximizer_count"] = int(len(tied))
        rows.append(row)
    return rows


def _conflicts(arcs: list[dict]) -> dict:
    pairs = []
    for a, left in enumerate(arcs):
        for right in arcs[a + 1:]:
            overlap = min(left["end"], right["end"]) - max(left["start"], right["start"])
            if overlap > 0:
                pairs.append({"a": left["tile_id"], "b": right["tile_id"],
                              "a_kind": left["kind"], "b_kind": right["kind"],
                              "overlap_units": overlap})
    return {"overlap_pair_count": len(pairs),
            "key_nonkey_pairs": sum(p["a_kind"] != p["b_kind"] for p in pairs),
            "key_key_pairs": sum(p["a_kind"] == p["b_kind"] == "key_dp" for p in pairs),
            "max_overlap_units": max((p["overlap_units"] for p in pairs), default=0),
            "pairs": pairs}


def _orders(model: PracticeModel, arcs: list[dict]) -> list[tuple[str, list[int]]]:
    by_tile = {row["tile_id"]: row for row in arcs}
    target = sorted(model.tile_ids, key=lambda t: (by_tile[t]["start"], by_tile[t]["end"], t))
    incumbent = active._first_order(model, BEST)
    incumbent_ids = [model.tile_ids[i] for i in incumbent]
    # Keep the proven incumbent order among nonkeys; insert keys according to
    # the K14 trace while preserving incumbent nonkey order.
    nonkeys = [tile for tile in incumbent_ids if by_tile[tile]["kind"] != "key_dp"]
    key_ids = sorted((tile for tile in model.tile_ids if by_tile[tile]["kind"] == "key_dp"),
                     key=lambda t: by_tile[t]["start"])
    merged = list(nonkeys)
    for key in key_ids:
        pos = sum(by_tile[other]["start"] <= by_tile[key]["start"] for other in merged)
        merged.insert(pos, key)
    return [("projection_all64", [model.tile_index[t] for t in target]),
            ("incumbent_nonkeys_k14_insert", [model.tile_index[t] for t in merged])]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "runs/projection_primal_probe")
    parser.add_argument("--trace", type=Path,
                        default=ROOT / "results/practice_projection_primal_probe.json")
    parser.add_argument("--max-seconds", type=float, default=300.0)
    args = parser.parse_args()
    start = time.monotonic()
    args.out.mkdir(parents=True, exist_ok=True)
    args.trace.parent.mkdir(parents=True, exist_ok=True)
    certificate = json.loads(CERT.read_text())
    case = next(row for row in certificate["cases"] if row["keys"][-1] == "T00011")
    keys = tuple(case["keys"])
    branch = 1  # RQ0004=T00012, the limiting all-17 branch.
    data, _ = bound._load_audited_data(bound.PRICE_FILE)
    inputs = bound._instance_inputs(data)
    key_arcs = _projected_trace(data, inputs, keys, branch, case["branches"][branch])
    nonkey_arcs = _nonkey_choices(data, inputs, keys, branch)
    all_arcs = key_arcs + nonkey_arcs
    if len(all_arcs) != 64:
        raise AssertionError("expected 64 first arcs")
    conflict = _conflicts(all_arcs)
    report = {
        "scope": "public dev-reference; K14 branch RQ0004=T00012",
        "k14_certificate_sha256": hashlib.sha256(CERT.read_bytes()).hexdigest(),
        "price_sha256": hashlib.sha256(bound.PRICE_FILE.read_bytes()).hexdigest(),
        "incumbent_csv_sha256": hashlib.sha256(BEST.read_bytes()).hexdigest(),
        "keys": list(keys), "branch": branch,
        "conditional_upper_cents": case["branches"][branch]["conditional_upper_cents"],
        "key_arcs": key_arcs, "nonkey_arcs": nonkey_arcs,
        "arc_conflicts": conflict, "candidates": [],
        "nonkey_tiles_with_tied_maximizers": sum(
            row["maximizer_count"] > 1 for row in nonkey_arcs
        ),
    }
    args.trace.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"stage": "trace", "overlap_pair_count": conflict["overlap_pair_count"],
                      "key_nonkey_pairs": conflict["key_nonkey_pairs"],
                      "seconds": time.monotonic() - start}), flush=True)
    model = PracticeModel(bound.PRACTICE, ROOT / "results/practice_reference.csv")
    scores, programs = score_table(model)
    incumbent_score = model.authoritative_score(BEST)["score"]["total"]
    for name, order in _orders(model, all_arcs):
        if time.monotonic() - start > args.max_seconds:
            break
        candidate = {"name": name, "order": [model.tile_ids[i] for i in order]}
        try:
            path, partial, predicted, optional_count, partial_count, req_data = active.solve(
                model, scores, programs, order,
            )
            destination = args.out / f"{name}.csv"
            _write(model, destination, path)
            scored = model.authoritative_score(destination)
            if (len(scored["completion"]["completed_tiles"]) != 64
                    or scored["score"]["request_reward"] != 3920.0
                    or any(a["penalty"] for a in scored["actions"] if a["action"] == "observe")
                    or abs(scored["score"]["total"] - predicted - 3920.0) > 1e-5):
                raise AssertionError("candidate differs from exact DP or scorer")
            candidate.update({"status": "scorer_verified", "score": scored["score"]["total"],
                              "improvement": scored["score"]["total"] - incumbent_score,
                              "observations": len(path), "partial_observations": partial_count,
                              "csv": str(destination)})
            if candidate["improvement"] <= 0:
                destination.unlink()
                candidate.pop("csv")
                candidate["csv_removed_after_verification"] = True
        except ValueError as exc:
            candidate.update({"status": "infeasible_fixed_order", "error": str(exc)})
        report["candidates"].append(candidate)
        print(json.dumps({"stage": "candidate", **{k: v for k, v in candidate.items() if k != "order"},
                          "seconds": time.monotonic() - start}), flush=True)
        args.trace.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    report["runtime_seconds"] = time.monotonic() - start
    args.trace.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
