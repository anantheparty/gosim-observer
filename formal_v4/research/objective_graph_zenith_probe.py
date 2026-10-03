#!/usr/bin/env python3
"""Source-locked, small prefix audit of the legal zenith azimuth degree of freedom.

Scores and raw factors are reconstructed from an existing official local trace.
The latter are offline truth, NOT inferred public factor bounds.  Weather belief
is held at the same declared prior for the control and every azimuth proposal.
This is a frozen-current-utility experiment, not a season score experiment.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
import numpy as np

BASE = Path(__file__).resolve().parents[1]
OFFICIAL = BASE / "upstream/gosim-observer-examples"
FROZEN = BASE / "results/global_field_20261004/source_snapshot/participant"
OUT = BASE / "results/objective_graph_20261004"
sys.path.insert(0, str(FROZEN))
sys.path.insert(1, str(OFFICIAL))
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner, coarse_numpy_local
from research.spatial_candidates import DEG, PROGRAMS, parse_utc
from runner.challenge.v4_workflow import V4Workflow
from runner.challenge.v4_fiber_map import FiberGrid, min_altitude_during
from runner.challenge.v4_runner import load_scenario, normalize_action


def zenith_events(planner, vectors, pool):
    """All open azimuth classification intervals for production's .008 margin.

    At actual altitude 90, target tangent coordinates are sinusoids of azimuth.
    Roots at both sides of each glass square include the outer field edge.
    Every interval has identical valid fibers; utility is independent of azimuth.
    """
    angles = [0., 2 * math.pi]
    half = planner.glass / 2 - .008
    centers = (np.arange(planner.side) - (planner.side - 1) / 2) * planner.pitch
    borders = np.unique(np.r_[centers - half, centers + half,
                              -planner.fov / 2, planner.fov / 2])
    for x, y, z in vectors[pool]:
        if z <= 0:
            continue
        for a, b in ((-x / z / DEG, -y / z / DEG),
                     (y / z / DEG, -x / z / DEG)):
            radius = math.hypot(a, b)
            if radius < 1e-14:
                continue
            phase = math.atan2(b, a)
            for boundary in borders:
                if abs(boundary) < radius:
                    delta = math.acos(boundary / radius)
                    angles.extend(((phase - delta) % (2 * math.pi),
                                   (phase + delta) % (2 * math.pi)))
    events = np.unique(np.round(angles, 13))
    mids = (events[1:] + events[:-1]) / 2 / DEG
    return np.column_stack((np.full(len(mids) + 1, 90.), np.r_[0., mids]))


def legal(planner, grid, scenario, now, candidate):
    _, center, duration, program, chosen, fibers = candidate
    action = {"action": "observe", "pointing": {"alt_deg": float(center[0]),
              "az_deg": float(center[1])}, "duration_seconds": int(duration),
              "program": PROGRAMS[program],
              "assignments": {str(f): planner.ids[int(i)] for f, i in zip(fibers, chosen)}}
    lookup = {t["target_id"]: t for t in scenario.targets}
    normalize_action(action, scenario, lookup, now)
    end = now + __import__("datetime").timedelta(seconds=duration)
    for fiber, target_id in action["assignments"].items():
        target = lookup[target_id]
        found = grid.classify_target(target["ra_deg"], target["dec_deg"], now,
                                    center[0], center[1], planner.lat, planner.lon)
        assert found.region == "glass" and found.fiber_id == int(fiber), (fiber, target_id, found)
        assert min_altitude_during(target["ra_deg"], target["dec_deg"], now, end,
                                   scenario.config) >= scenario.minimum_altitude_deg
    return action


def run(card, sample_count=8):
    init = V4Workflow(OFFICIAL / "local-cards" / card).initialize_payload(900)
    p = CPUPhaseSpatialPlanner(init)
    scenario = load_scenario(OFFICIAL / "local-cards" / card / "config/v4_scenario.json")
    grid = FiberGrid.from_config(scenario.fiber_config)
    trace = BASE / "results/geometry_native_20261003/protocol_phase_control" / card
    decisions = list(csv.DictReader((trace / "decisions.csv").open()))
    observations = list(csv.DictReader((trace / "observations.csv").open()))
    first = [d for d in decisions if d["action"] == "observe"
             and parse_utc(d["start_utc"]) < p.nights[0][1]]
    chosen_rows = [first[i] for i in np.unique(np.rint(np.linspace(0, len(first)-1, sample_count)).astype(int))]
    records = []
    for row in chosen_rows:
        now = parse_utc(row["start_utc"])
        rank = int(row["observe_index"])
        scores, factors = np.zeros(p.n), np.zeros(p.n)
        for hit in observations:
            if int(hit["observe_index"]) < rank:
                i = p.index[hit["target_id"]]
                scores[i] = max(scores[i], float(hit["score"]))
                factors[i] = max(factors[i], float(hit["factor"]))
        snap = dict(now_utc=row["start_utc"], observe_action_index=rank,
                    new_messages=[], active_requests=[])
        env = dict(anchor_count=24, quality_scale=.55, program_band_quality_scale=.55/.95,
                   duration_safety=1.10, use_bulletin_directional_prior=False)
        started = time.perf_counter()
        baseline = p.choose(snap, scores, factors, env, [])
        frame = p._cpu_phase_frame
        if baseline is None or frame is None:
            continue
        vectors = frame[0]
        # A target fits some rotation of the square iff tangent radius <= half diagonal.
        radius = np.hypot(vectors[:, 0], vectors[:, 1]) / np.maximum(vectors[:, 2], 1e-12) / DEG
        pool = np.flatnonzero((vectors[:, 2] > 0) & (radius <= p.fov / math.sqrt(2) + 1e-9))
        if len(pool):
            np.savez_compressed(OUT / f"prefix_{card}_{rank}.npz", vectors=frame[0],
                                up=frame[1], k=frame[2], scores=frame[3], factors=frame[4],
                                mult=frame[5], missing=frame[6], rr=frame[7], rt=frame[8],
                                rd=frame[9], ub=frame[10], urg=frame[11],
                                seconds=np.array(frame[12]), safety=np.array(frame[13]),
                                focus_is_none=np.array(frame[14] is None), pool=pool)
        centers = zenith_events(p, vectors, pool)
        duration = baseline["duration_seconds"]
        rates = coarse_numpy_local(p, centers, pool, frame, [duration])
        zero = p._evaluate((90., 0.), pool, *frame)
        top = np.argsort(rates, kind="stable")[-min(16, len(rates)):]
        probes = [p._evaluate(tuple(centers[j]), pool, *frame) for j in top]
        best = max((r for r in probes if r is not None), key=lambda r: r[0], default=None)
        control_rate = float(p.stats["selected_exact_rate"])
        record = dict(card=card, now_utc=row["start_utc"], rank=rank,
                      historical_science=float(scores.sum()), history_targets=int(np.count_nonzero(scores)),
                      zenith_pool=len(pool), az_event_intervals=len(centers)-1,
                      fixed_duration=duration, fixed_duration_best_rate=float(rates.max(initial=0.)),
                      control_rate=control_rate, zero_az_rate=0. if zero is None else float(zero[0]),
                      best_zenith_rate=0. if best is None else float(best[0]),
                      seconds=time.perf_counter()-started, control_action=baseline,
                      zenith_action=None if best is None else legal(p, grid, scenario, now, best))
        records.append(record)
    return records


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    records = [record for card in ("L1", "L2") for record in run(card)]
    result = dict(mechanism="legal zenith azimuth classification-event proposals",
                  offline_factor_truth=True, common_declared_weather_prior=True,
                  full_season=False, records=records,
                  source_lock=json.loads((FROZEN.parent.parent / "source_lock.json").read_text()),
                  probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT / "zenith_prefix_probe.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"states": len(records),
                     "improved_vs_cpu_phase": sum(r["best_zenith_rate"] > r["control_rate"] + 1e-10 for r in records),
                     "improved_vs_zero_az": sum(r["best_zenith_rate"] > r["zero_az_rate"] + 1e-10 for r in records),
                     "seconds": sum(r["seconds"] for r in records),
                     "records": [{k: r[k] for k in ("card", "now_utc", "history_targets", "zenith_pool",
                                                     "control_rate", "zero_az_rate", "best_zenith_rate")} for r in records]}, indent=2))
