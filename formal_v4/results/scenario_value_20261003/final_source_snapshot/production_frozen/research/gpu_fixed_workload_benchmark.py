"""Check work-count reproducibility under deliberately slower CPU refinement."""
import argparse
import hashlib
import json
import time
from pathlib import Path

try:
    from .gpu_spatial_candidates import GPUSpatialPlanner
    from .spatial_candidates import SpatialPlanner
except ImportError:
    from gpu_spatial_candidates import GPUSpatialPlanner
    from spatial_candidates import SpatialPlanner

parser = argparse.ArgumentParser()
parser.add_argument("initialize_json")
parser.add_argument("--out", default="gpu_fixed_workload_benchmark.json")
args = parser.parse_args()
payload = json.loads(Path(args.initialize_json).read_text())
planner = GPUSpatialPlanner(payload)
snapshot = {"now_utc": payload["survey"]["nights"][0]["observing_start_utc"]}
env = {"quality_scale": .55, "program_band_quality_scale": .55 / .95,
       "gpu_anchor_count": 1024, "gpu_max_candidates": 32768,
       "gpu_refine_count": 64, "gpu_refine_budget_seconds": .3,
       "gpu_fixed_workload": True, "gpu_exact_candidate_count": 256,
       "gpu_refinement_steps": 32, "gpu_emergency_seconds": 3.0}
base_evaluate = SpatialPlanner._evaluate
per_evaluation_delay = 0.0

def slower_evaluate(self, *values, **options):
    if per_evaluation_delay:
        time.sleep(per_evaluation_delay)
    return base_evaluate(self, *values, **options)

SpatialPlanner._evaluate = slower_evaluate
runs = []
try:
    for delay in (0.0, 0.0, .002, 0.0):
        per_evaluation_delay = delay
        start = time.perf_counter()
        action = planner.choose(snapshot, {}, {}, env, [])
        record = {"delay_seconds_per_exact_eval": delay,
                  "elapsed_seconds": time.perf_counter() - start,
                  "stats": dict(planner.stats), "action": action,
                  "action_sha256": hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()}
        runs.append(record)
        print(json.dumps(record), flush=True)
finally:
    SpatialPlanner._evaluate = base_evaluate
assert len({r["action_sha256"] for r in runs}) == 1
assert len({(r["stats"]["exact_candidates"], r["stats"]["refinement_probes"],
             r["stats"]["cpu_refinements"]) for r in runs}) == 1
assert not any(r["stats"]["emergency_triggered"] for r in runs)
result = {"parameters": env, "runs": runs, "identical_actions": True,
          "identical_work_counts": True, "source_sha256": {
              name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
              for name in ("gpu_spatial_candidates.py", "spatial_candidates.py")}}
Path(args.out).write_text(json.dumps(result, indent=2))
