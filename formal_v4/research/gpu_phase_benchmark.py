"""Independent glass-boundary arrangement candidate pilot, public data only."""
import argparse
import csv
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

try:
    from .gpu_spatial_candidates import GPUSpatialPlanner
    from .spatial_candidates import DEG, _shift_altaz
except ImportError:
    from gpu_spatial_candidates import GPUSpatialPlanner
    from spatial_candidates import DEG, _shift_altaz


def phase_centers(planner, frame, seeds, local_target_limit):
    vectors, up, k, scores, factors, multiplier, missing, rr, rt, rd, ub, urgency, seconds_left, safety, _ = frame
    merit = (np.maximum(0, planner.weight * np.minimum(1., 400 * k) * multiplier.max(axis=0) - scores)
             + missing * planner.req_penalty * (k * seconds_left / safety >= planner.req_threshold)
             + rr * (k * seconds_left / safety >= rt)) * urgency
    answer = []
    local_counts = []
    for alt, az in seeds:
        a, z = alt * DEG, az * DEG
        basis = np.array([[math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)],
                          [-math.sin(a) * math.cos(z), -math.sin(a) * math.sin(z), math.cos(a)],
                          [-math.sin(z), math.cos(z), 0.]])
        projection = vectors @ basis.T
        north = projection[:, 1] / np.maximum(projection[:, 0], 1e-12) / DEG
        east = projection[:, 2] / np.maximum(projection[:, 0], 1e-12) / DEG
        relevant = np.flatnonzero((projection[:, 0] > 0) & (np.maximum(np.abs(north), np.abs(east)) < (planner.fov + planner.pitch) / 2)
                                 & (up >= planner.tmin) & (merit > 0))
        if local_target_limit:
            relevant = relevant[np.lexsort((relevant, -merit[relevant]))[:local_target_limit]]
        local_counts.append(len(relevant))
        axes = []
        half = planner.glass / 2 - .008
        for offsets in (north[relevant], east[relevant]):
            parity = .5 if planner.side % 2 == 0 else 0.
            nominal_cell = np.rint(offsets / planner.pitch - parity) + parity
            events = np.concatenate((offsets - nominal_cell * planner.pitch - half,
                                     offsets - nominal_cell * planner.pitch + half))
            events = (events + planner.pitch / 2) % planner.pitch - planner.pitch / 2
            events = np.unique(np.round(np.r_[events, -planner.pitch / 2, planner.pitch / 2], 10))
            # A representative interior point of every planar arrangement cell.
            axes.append(np.r_[0., (events[1:] + events[:-1]) / 2])
        dn, de = np.meshgrid(*axes, indexing="ij")
        shifted = basis[0] + dn.ravel()[:, None] * DEG * basis[1] + de.ravel()[:, None] * DEG * basis[2]
        shifted /= np.linalg.norm(shifted, axis=1)[:, None]
        local = np.column_stack((np.arcsin(np.clip(shifted[:, 2], -1, 1)) / DEG,
                                 np.arctan2(shifted[:, 1], shifted[:, 0]) / DEG % 360))
        answer.append(local[(local[:, 0] >= 0) & (local[:, 0] <= 90)])
    return np.unique(np.round(np.vstack(answer), 7), axis=0), local_counts


parser = argparse.ArgumentParser()
parser.add_argument("initialize_json")
parser.add_argument("--out", default="gpu_phase_benchmark.json")
parser.add_argument("--top", type=int, default=16)
parser.add_argument("--local-target-limit", type=int, default=24)
parser.add_argument("--exact-count", type=int, default=64)
parser.add_argument("--now-utc")
parser.add_argument("--history-dir", help="Read past valid public observations; does not read truth files")
args = parser.parse_args()
payload = json.loads(Path(args.initialize_json).read_text())
p = GPUSpatialPlanner(payload)
snapshot = {"now_utc": args.now_utc or payload["survey"]["nights"][0]["observing_start_utc"]}
best_scores, best_factors = {}, {}
if args.history_dir:
    history = Path(args.history_dir)
    decisions = {r["observe_index"]:r for r in csv.DictReader((history/"decisions.csv").open()) if r["action"] == "observe"}
    for observation in csv.DictReader((history/"observations.csv").open()):
        if observation["valid"].lower() == "true" and decisions[observation["observe_index"]]["end_utc"] <= snapshot["now_utc"]:
            target = observation["target_id"]
            best_scores[target] = max(best_scores.get(target, 0), float(observation["score"]))
            best_factors[target] = max(best_factors.get(target, 0), float(observation["factor"]))
env = {"quality_scale": .55, "program_band_quality_scale": .55 / .95,
       "gpu_anchor_count": 1024, "gpu_max_candidates": 32768, "gpu_refine_count": 64,
       "gpu_fixed_workload": True, "gpu_exact_candidate_count": 256, "gpu_refinement_steps": 32,
       "gpu_emergency_seconds": 3.0}
action = p.choose(snapshot, best_scores, best_factors, env, [])
if action is None:
    parser.error("No feasible observation at the requested public time; check the night calendar")
baseline_stats = dict(p.stats)
frame = p._frame
centers = p.last_candidate_centers.copy()
rates = p.last_coarse_rates.copy()
seed_idx = np.lexsort((np.arange(len(rates)), -rates))[:args.top]
start = time.perf_counter()
phases, local_counts = phase_centers(p, frame, centers[seed_idx], args.local_target_limit)
build_seconds = time.perf_counter() - start
_, useful = p._build_centers(frame, env)
start = time.perf_counter()
phase_rates, _ = p.coarse_gpu(phases, useful, frame, env)
scan_seconds = time.perf_counter() - start
vectors = frame[0]

def evaluate(center):
    a, z = center[0] * DEG, center[1] * DEG
    cvec = np.array([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])
    pool = useful[np.sum(vectors[useful] * cvec, axis=1) >= math.cos(p.fov * DEG)]
    return p._evaluate(center, pool, *frame)

best = evaluate((action["pointing"]["alt_deg"], action["pointing"]["az_deg"]))
baseline_rate = best[0]
start = time.perf_counter()
for i in np.lexsort((np.arange(len(phase_rates)), -phase_rates))[:args.exact_count]:
    candidate = evaluate(tuple(phases[i]))
    if candidate and candidate[0] > best[0]:
        best = candidate
exact_seconds = time.perf_counter() - start
fibers, valid, _ = p._classify(vectors[best[4]], *best[1])
assert np.all(valid) and np.all(fibers == best[5])
result = {"now_utc": snapshot["now_utc"], "baseline": {"rate": baseline_rate, "action": action, "stats": baseline_stats},
          "historical_targets_observed": len(best_scores), "active_requests_modeled": False,
          "phase_candidates": len(phases), "seed_count": args.top, "local_target_counts": local_counts,
          "local_target_limit": args.local_target_limit, "exact_count": args.exact_count,
          "build_seconds": build_seconds, "scan_seconds": scan_seconds, "exact_seconds": exact_seconds,
          "phase_max_coarse_rate": float(phase_rates.max()), "best_rate": float(best[0]),
          "gain_percent": 100 * (best[0] / baseline_rate - 1), "chosen_pointing": best[1],
          "chosen_duration": int(best[2]), "chosen_program_index": int(best[3]),
          "chosen_assignments": {int(f):p.ids[int(i)] for i,f in zip(best[4],best[5])},
          "sphere_geometry_check_passed": True,
          "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                            for name in ("gpu_phase_benchmark.py", "gpu_spatial_candidates.py", "spatial_candidates.py")},
          "coverage_claim": "complete planar phase cells for selected local targets only; spherical candidate coverage remains approximate"}
Path(args.out).write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
