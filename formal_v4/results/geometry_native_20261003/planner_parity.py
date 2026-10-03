#!/usr/bin/env python3
"""Four initial real decisions using unchanged frozen planner, both kernels."""
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

BASE = Path(__file__).resolve().parents[2]
FROZEN = BASE / "runs/cold_neural_value_20261003/production_frozen"
OFFICIAL = BASE / "upstream/gosim-observer-examples"
sys.path.insert(0, str(FROZEN))
sys.path.insert(0, str(OFFICIAL))
from runner.challenge.v4_workflow import V4Workflow
from research.spatial_candidates import SpatialPlanner

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded

cg = module("research.candidate_geometry_sweep", BASE / "research/candidate_geometry_sweep.py")
native = module("research.geometry_native", BASE / "research/geometry_native.py")
reference = cg.weighted_sweep
records = []
for card in ("L1", "L2", "L3", "L4"):
    initial = V4Workflow(OFFICIAL / "local-cards" / card).initialize_payload(900)
    snapshot = dict(now_utc=initial["survey"]["nights"][0]["observing_start_utc"], observe_action_index=0,
                    new_messages=[], active_requests=[])
    env = dict(anchor_count=24, quality_scale=.55, program_band_quality_scale=.55 / .95)
    observations = {}
    for backend, kernel in (("numba", reference), ("native", native.weighted_sweep)):
        cg.weighted_sweep = kernel
        samples = []
        for repeat in range(4):
            planner = cg.CandidateGeometryPlanner(initial)
            begin = time.perf_counter()
            action = planner.choose(snapshot, {}, {}, env, [])
            elapsed = time.perf_counter() - begin
            samples.append(dict(seconds=elapsed, stats=dict(planner.stats), action=action))
        observations[backend] = dict(first_seconds=samples[0]["seconds"],
                                    median_warm_seconds=statistics.median(s["seconds"] for s in samples[1:]),
                                    samples=samples)
    for sample in observations["numba"]["samples"] + observations["native"]["samples"]:
        assert sample["action"] == observations["numba"]["samples"][0]["action"], card
    records.append(dict(card=card, action_bit_identical=True, observations=observations,
                        total_choose_speedup=observations["numba"]["median_warm_seconds"] / observations["native"]["median_warm_seconds"]))
    print(json.dumps({"card": card, "native_warm_seconds": observations["native"]["median_warm_seconds"],
                      "numba_warm_seconds": observations["numba"]["median_warm_seconds"], "actions_identical": True}), flush=True)
result = dict(all_passed=True, records=records, scope="Unchanged frozen planner; first real decision per card; four repetitions each backend",
              baseline_source=str(FROZEN / "research/spatial_candidates.py"),
              baseline_sha256=hashlib.sha256((FROZEN / "research/spatial_candidates.py").read_bytes()).hexdigest(),
              candidate_geometry_sha256=hashlib.sha256((BASE / "research/candidate_geometry_sweep.py").read_bytes()).hexdigest())
(Path(__file__).resolve().parent / "planner_parity_darwin_arm64.json").write_text(json.dumps(result, indent=2) + "\n")
