#!/usr/bin/env python3
"""One-night interval/coverage LP-MIP pilot using public initialization and frozen C/E.

Run with the existing solver environment:
  .venv-solver/bin/python formal_v4/research/global_lp_pilot.py

No workflow/scenario loader is imported: it would also read weather truth. Only
public catalogue/calendar and public configuration files are opened here.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import csv
from datetime import timedelta
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import coo_matrix

from spatial_candidates import SpatialPlanner, PROGRAMS, _shift_altaz, local_sidereal, parse_utc

BASE = Path(__file__).resolve().parents[1]


def public_initialization(card: Path):
    names = ["config/v4_scenario.json", "config/v4_fiber_config.json", "config/v4_score_config.json",
             "public/targets.csv", "public/v4_night_calendar.csv"]
    inputs = {}

    def read(name):
        path = card / name
        if "truth" in path.parts:
            raise ValueError("truth input is forbidden in this pilot")
        data = path.read_bytes()
        inputs[name] = hashlib.sha256(data).hexdigest()
        return data.decode()

    scenario, fiber, score = [json.loads(read(name)) for name in names[:3]]
    targets = list(csv.DictReader(read(names[3]).splitlines()))
    calendar = list(csv.DictReader(read(names[4]).splitlines()))
    site = dict(scenario["site"])
    site["minimum_altitude_deg"] = float(scenario["minimum_altitude_deg"])
    field = fiber["field"]
    side = math.isqrt(int(field["n_fibers"]))
    glass = math.sqrt(float(field["fiber_area_deg2"]))
    pitch = glass + float(field["gap_deg"])
    columns = list(targets[0])
    rows = [[row[name] if name in ("target_id", "target_class") else
             row[name].lower() == "true" if name == "required" else float(row[name])
             for name in columns] for row in targets]
    nights = [{"night_id": row["night_id"], "night_date": row["night_date"],
               "observing_start_utc": row["observing_start_utc"],
               "observing_end_utc": row["observing_end_utc"]} for row in calendar]
    init = {"task_card": scenario["task_card"], "site": site,
            "survey": {"start_utc": nights[0]["observing_start_utc"],
                       "end_utc": nights[-1]["observing_end_utc"],
                       "slot_seconds": int(round(int(calendar[0]["night_seconds"]) / int(calendar[0]["slot_count"]))),
                       "nights": nights},
            "instrument": {**field, "grid_side": side, "glass_side_deg": glass,
                           "pitch_deg": pitch, "fov_side_deg": side * pitch,
                           "exposure": fiber["exposure"]},
            "scoring": score, "targets": {"columns": columns, "rows": rows}}
    return init, inputs


def integrated_H(planner, start, duration, night_start, slot_seconds):
    end = start + timedelta(seconds=duration)
    cursor, total = start, np.zeros(planner.n)
    while cursor < end:
        slot = math.floor((cursor - night_start).total_seconds() / slot_seconds)
        slot_end = night_start + timedelta(seconds=(slot + 1) * slot_seconds)
        piece_end = min(end, slot_end, cursor + timedelta(seconds=120))
        midpoint = cursor + (piece_end - cursor) / 2
        lst = local_sidereal(midpoint, planner.lon)
        altitude = planner._altaz(lst)[0]
        total += (piece_end - cursor).total_seconds() * planner._public_quality(midpoint, lst, altitude) * planner.q0
        cursor = piece_end
    return total / duration


def generate_candidates(planner, night_index, start_step, centers_per_start, durations, C, E, slot_seconds):
    night_start, night_end = planner.nights[night_index]
    length = int((night_end - night_start).total_seconds())
    candidates = []
    for second in range(0, length, start_step):
        start = night_start + timedelta(seconds=second)
        lst = local_sidereal(start, planner.lon)
        altitude, azimuth, hour, vectors = planner._altaz(lst)
        up = np.where(planner.hmax >= 180, 1e9, (planner.hmax - hour) / (360.98564736629 / 86400))
        visible = (altitude >= planner.min_alt + .04) & (up >= min(durations))
        priority = visible * (planner.weight * planner.multipliers.max() + planner.required * planner.req_penalty)
        bin_values = np.bincount(planner.space_bins, weights=priority, minlength=planner.bin_count)
        top_bins = np.argsort(bin_values)[-12:][::-1]
        anchors = []
        for spatial_bin in top_bins:
            members = np.flatnonzero((planner.space_bins == spatial_bin) & (priority > 0))
            if len(members):
                anchors.append(int(members[np.argmax(priority[members])]))
        centers = {}
        useful = np.flatnonzero(visible)
        for anchor in anchors:
            for fiber in range(planner.nfib):
                row, col = divmod(fiber, planner.side)
                center = _shift_altaz(float(altitude[anchor]), float(azimuth[anchor]),
                                      -(row - (planner.side - 1) / 2) * planner.pitch,
                                      -(col - (planner.side - 1) / 2) * planner.pitch)
                if not 0 <= center[0] <= 90:
                    continue
                a, z = math.radians(center[0]), math.radians(center[1])
                center_vector = np.array([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])
                # Every point in the square field lies inside this spherical
                # cap. Filter the opposite half-sky before integer cell lookup.
                radius = planner.fov * math.sqrt(2) / 2 + .05
                near = useful[np.sum(vectors[useful] * center_vector, axis=1)
                              >= math.cos(math.radians(radius))]
                cell, valid, _ = planner._classify(vectors[near], *center)
                target_ids, fibers = near[valid], cell[valid]
                maxima = np.zeros(planner.nfib)
                np.maximum.at(maxima, fibers, priority[target_ids])
                centers[tuple(round(x, 7) for x in center)] = (float(maxima.sum()), target_ids, fibers)
        ranked = sorted(centers.items(), key=lambda item: -item[1][0])[:centers_per_start]
        for duration in durations:
            if second + duration > length:
                continue
            H = integrated_H(planner, start, duration, night_start, slot_seconds)
            raw = np.minimum(1.0, planner.flux * duration * C * E * H / planner.f0t0)
            band_quality = C * H
            actual_bands = np.where(band_quality >= planner.dark_threshold, 0,
                                    np.where(band_quality >= planner.bright_threshold, 1, 2))
            for center, (_, target_ids, fibers) in ranked:
                eligible = up[target_ids] >= duration + 1
                target_ids, fibers = target_ids[eligible], fibers[eligible]
                if not len(target_ids):
                    continue
                for program in range(3):
                    multipliers = np.where(actual_bands[target_ids] == program, planner.multipliers[program], planner.mismatch)
                    scores = planner.weight[target_ids] * raw[target_ids] * multipliers
                    utility = scores + planner.req_penalty * planner.required[target_ids] * (raw[target_ids] >= planner.req_threshold)
                    chosen = []
                    for fiber in np.unique(fibers):
                        available = np.flatnonzero(fibers == fiber)
                        chosen.append(int(available[np.argmax(utility[available])]))
                    selected = target_ids[chosen]
                    candidates.append({"start": second, "end": second + duration,
                                       "center": center, "program": program,
                                       "targets": selected.tolist(), "fibers": fibers[chosen].tolist(),
                                       "scores": scores[chosen].tolist(), "factors": raw[selected].tolist()})
    return candidates, length


def coverage_model(candidates, planner):
    levels = {}
    for candidate in candidates:
        for target, score in zip(candidate["targets"], candidate["scores"]):
            levels.setdefault(target, set()).add(float(score))
    target_layers, descriptions, weights_exact = {}, [], []
    for target, values in sorted(levels.items()):
        previous = Fraction(0)
        pairs = []
        for value in sorted(values):
            exact = Fraction.from_float(value)
            pairs.append((value, len(descriptions)))
            descriptions.append({"target_index": target, "target_id": planner.ids[target],
                                 "kind": "science", "score_threshold": value})
            weights_exact.append(exact - previous)
            previous = exact
        target_layers[target] = pairs
    required_layers = {}
    for target in sorted(levels):
        if planner.required[target]:
            required_layers[target] = len(descriptions)
            descriptions.append({"target_index": target, "target_id": planner.ids[target],
                                 "kind": "required", "factor_threshold": planner.req_threshold})
            weights_exact.append(Fraction.from_float(float(planner.req_penalty)))
    column_layers = []
    for candidate in candidates:
        covered = []
        for target, score, factor in zip(candidate["targets"], candidate["scores"], candidate["factors"]):
            covered.extend(layer for threshold, layer in target_layers[target] if threshold <= score)
            if target in required_layers and factor >= planner.req_threshold:
                covered.append(required_layers[target])
        column_layers.append(covered)
    endpoints = sorted({value for c in candidates for value in (c["start"], c["end"])})
    midpoints = [(left + right) / 2 for left, right in zip(endpoints, endpoints[1:])]
    column_times = [[t for t, point in enumerate(midpoints) if c["start"] <= point < c["end"]]
                    for c in candidates]
    n_columns, n_layers = len(candidates), len(descriptions)
    rows, cols, data = [], [], []
    for column, layers in enumerate(column_layers):
        rows.extend(layers); cols.extend([column] * len(layers)); data.extend([-1] * len(layers))
    for layer in range(n_layers):
        rows.append(layer); cols.append(n_columns + layer); data.append(1)
    for column, times in enumerate(column_times):
        rows.extend(n_layers + t for t in times); cols.extend([column] * len(times)); data.extend([1] * len(times))
    A = coo_matrix((data, (rows, cols)), shape=(n_layers + len(midpoints), n_columns + n_layers)).tocsr()
    rhs = np.concatenate((np.zeros(n_layers), np.ones(len(midpoints))))
    objective = np.concatenate((np.zeros(n_columns), -np.asarray([float(w) for w in weights_exact])))
    return A, rhs, objective, descriptions, weights_exact, column_layers, column_times, midpoints


def schedule_value(selected, candidates, planner, weights_exact, column_layers):
    ordered = sorted(selected, key=lambda e: candidates[e]["start"])
    assert all(candidates[a]["end"] <= candidates[b]["start"] for a, b in zip(ordered, ordered[1:]))
    covered = set(layer for e in selected for layer in column_layers[e])
    utility_exact = sum((weights_exact[layer] for layer in covered), Fraction(0))
    scores, factors = np.zeros(planner.n), np.zeros(planner.n)
    for e in selected:
        c = candidates[e]
        np.maximum.at(scores, c["targets"], c["scores"])
        np.maximum.at(factors, c["targets"], c["factors"])
    observed = factors >= planner.uniform_threshold
    counts = np.bincount(planner.ra_bands, weights=observed, minlength=len(planner.band_sizes))
    proportions = counts[planner.band_sizes > 0] / planner.band_sizes[planner.band_sizes > 0]
    denominator = len(proportions) * float(proportions @ proportions)
    jain = float(proportions.sum()) ** 2 / denominator if denominator > 0 else 0.0
    missing = int(np.count_nonzero(planner.required & (factors < planner.req_threshold)))
    return {"candidate_indices": ordered, "exposures": len(ordered),
            "utility": float(utility_exact), "utility_exact_rational": str(utility_exact),
            "science": float(scores.sum()), "required_missing": missing,
            "uniformity_penalty": -planner.uniform_weight * (1 - jain),
            "frozen_model_full_score": float(scores.sum()) - missing * planner.req_penalty - planner.uniform_weight * (1 - jain)}


def greedy_schedule(candidates, weights_exact, column_layers):
    selected, covered, current = [], set(), 0
    starts = sorted({c["start"] for c in candidates})

    def opportunity_seconds(e):
        # A short exposure cannot create a new start outside this fixed pool.
        # Charge its forced wait to the next candidate start, avoiding an
        # artificial comparison that rewards unusable idle gaps in the grid.
        end = candidates[e]["end"]
        following = next((s for s in starts if s >= end), end)
        return max(1, following - candidates[e]["start"])

    while True:
        available = [e for e, c in enumerate(candidates) if c["start"] >= current]
        if not available:
            break
        first_start = min(candidates[e]["start"] for e in available)
        same_start = [e for e in available if candidates[e]["start"] == first_start]
        best = max(same_start, key=lambda e: sum(float(weights_exact[j]) for j in column_layers[e] if j not in covered)
                   / opportunity_seconds(e))
        gain = sum(float(weights_exact[j]) for j in column_layers[best] if j not in covered)
        if gain <= 0:
            current = first_start + 1
            continue
        selected.append(best); covered.update(column_layers[best]); current = candidates[best]["end"]
    return selected


def exact_dual_certificate(lp, weights_exact, column_layers, column_times, n_layers, n_times):
    # Interpret each IEEE-754 input as an exact rational. Repair dual feasibility
    # upward, so the bound does not depend on the solver's floating tolerance.
    alpha = [min(w, max(Fraction(0), Fraction.from_float(float(-lp.ineqlin.marginals[j]))))
             for j, w in enumerate(weights_exact)]
    beta = [max(Fraction(0), Fraction.from_float(float(-lp.ineqlin.marginals[n_layers + t])))
            for t in range(n_times)]
    worst = Fraction(0)
    for layers, times in zip(column_layers, column_times):
        gap = sum((alpha[j] for j in layers), Fraction(0)) - sum((beta[t] for t in times), Fraction(0))
        worst = max(worst, gap)
    beta = [value + worst for value in beta]
    for layers, times in zip(column_layers, column_times):
        assert sum((beta[t] for t in times), Fraction(0)) >= sum((alpha[j] for j in layers), Fraction(0))
    exact_bound = sum(beta, Fraction(0)) + sum((w - a for w, a in zip(weights_exact, alpha)), Fraction(0))
    return alpha, beta, exact_bound, worst


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--card", default="L1", choices=("L1",))
    parser.add_argument("--night-index", type=int, default=0)
    parser.add_argument("--start-step", type=int, default=1800)
    parser.add_argument("--centers-per-start", type=int, default=16)
    parser.add_argument("--C", type=float, default=1.0)
    parser.add_argument("--E", type=float, default=.95)
    parser.add_argument("--mip-seconds", type=float, default=30)
    parser.add_argument("--out", type=Path, default=BASE / "results/global_lp_pilot_L1_night0")
    args = parser.parse_args()
    started = time.perf_counter()
    card = BASE / "upstream/gosim-observer-examples/local-cards" / args.card
    init, inputs = public_initialization(card)
    planner = SpatialPlanner(init)
    generation_start = time.perf_counter()
    candidates, night_seconds = generate_candidates(planner, args.night_index, args.start_step,
        args.centers_per_start, (600, 1200, 1800), args.C, args.E, init["survey"]["slot_seconds"])
    generation_seconds = time.perf_counter() - generation_start
    A, rhs, objective, descriptions, weights_exact, column_layers, column_times, midpoints = coverage_model(candidates, planner)
    ne, nl = len(candidates), len(descriptions)
    solve_start = time.perf_counter()
    lp = linprog(objective, A_ub=A, b_ub=rhs, bounds=[(0, None)] * ne + [(0, 1)] * nl,
                 method="highs", options={"time_limit": 30, "dual_feasibility_tolerance": 1e-8,
                                          "primal_feasibility_tolerance": 1e-8})
    lp_seconds = time.perf_counter() - solve_start
    if not lp.success:
        raise RuntimeError(f"LP failed: {lp.message}")
    certificate_start = time.perf_counter()
    alpha, beta, upper_exact, dual_repair = exact_dual_certificate(lp, weights_exact, column_layers,
                                                                  column_times, nl, len(midpoints))
    certificate_seconds = time.perf_counter() - certificate_start
    solve_start = time.perf_counter()
    mip = milp(objective, integrality=np.concatenate((np.ones(ne), np.zeros(nl))),
               bounds=Bounds(np.zeros(ne + nl), np.ones(ne + nl)),
               constraints=LinearConstraint(A, -np.inf, rhs),
               options={"time_limit": args.mip_seconds, "mip_rel_gap": .005})
    mip_seconds = time.perf_counter() - solve_start
    greedy = schedule_value(greedy_schedule(candidates, weights_exact, column_layers), candidates,
                            planner, weights_exact, column_layers)
    incumbent = None
    if mip.x is not None:
        assert np.max(np.abs(mip.x[:ne] - np.rint(mip.x[:ne]))) < 1e-5
        incumbent = schedule_value(np.flatnonzero(mip.x[:ne] > .5).tolist(), candidates,
                                   planner, weights_exact, column_layers)
    prices = {}
    for layer, (description, weight, price) in enumerate(zip(descriptions, weights_exact, alpha)):
        target_id = description["target_id"]
        prices.setdefault(target_id, []).append({**description, "layer_index": layer,
                                                "layer_weight": float(weight), "layer_weight_exact": str(weight),
                                                "shadow_price": float(price), "shadow_exact": str(price)})
    baseline_required = float(planner.required.sum() * planner.req_penalty)
    result = {"card": args.card, "night_index": args.night_index, "night_seconds": night_seconds,
              "frozen_quality": {"C": args.C, "E": args.E, "definition": "C=transparency*sky/(seeing*q0); E=instrument_efficiency"},
              "public_input_sha256": inputs, "candidate_universe_complete": False,
              "candidate_generation": {"start_step_seconds": args.start_step, "centers_per_start": args.centers_per_start,
                                       "durations_seconds": [600, 1200, 1800], "programs": list(PROGRAMS),
                                       "assignment": "one fixed utility-maximizing target per fiber per generated action"},
              "model_size": {"columns": ne, "coverage_layers": nl, "time_cliques": len(midpoints),
                             "nonzeros": int(A.nnz), "targets_covered_by_pool": len(prices)},
              "lp_utility_upper_numeric": float(-lp.fun), "lp_utility_upper_exact_certificate": str(upper_exact),
              "lp_utility_upper_certificate_float": float(upper_exact), "dual_repair_per_time_clique": str(dual_repair),
              "frozen_full_score_upper_from_pool": float(upper_exact) - baseline_required,
              "mip_status": int(mip.status), "mip_message": mip.message,
              "mip_requested_relative_gap": .005, "pool_exact_optimum_proven": False,
              "mip_gap_numeric": float(mip.mip_gap) if mip.x is not None else None,
              "mip_utility_upper_numeric": float(-mip.mip_dual_bound) if mip.x is not None else None,
              "greedy": greedy, "mip_incumbent": incumbent,
              "runtime_seconds": {"generation": generation_seconds, "lp": lp_seconds,
                                  "rational_certificate": certificate_seconds, "mip": mip_seconds,
                                  "total": time.perf_counter() - started},
              "limits": ["bounds apply to the finite candidate pool and specified frozen C/E model",
                         "no future weather truth, requests, faults, data-loss truth, or report rewards are used",
                         "uniformity omitted in optimization upper bound, evaluated for each feasible schedule"],
              "source_sha256": {str(Path(__file__).name): hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                "spatial_candidates.py": hashlib.sha256(Path(__file__).with_name("spatial_candidates.py").read_bytes()).hexdigest()}}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    (args.out / "target_shadow_prices.json").write_text(json.dumps(prices, sort_keys=True, indent=2) + "\n")
    (args.out / "time_shadow_prices.json").write_text(json.dumps([
        {"midpoint_seconds": point, "shadow_price": float(price), "shadow_exact": str(price)}
        for point, price in zip(midpoints, beta)], sort_keys=True, indent=2) + "\n")
    (args.out / "candidates.json").write_text(json.dumps(candidates, sort_keys=True) + "\n")
    print(json.dumps({key: result[key] for key in ("model_size", "lp_utility_upper_certificate_float", "greedy",
                     "mip_incumbent", "mip_gap_numeric", "runtime_seconds")}, indent=2))


if __name__ == "__main__":
    main()
