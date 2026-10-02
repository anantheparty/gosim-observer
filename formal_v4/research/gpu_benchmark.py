"""Task-specific PRO 6000 microbenchmark; consumes public initialize JSON only."""
import argparse
import json
import time
from pathlib import Path

import numpy as np

try:
    from .gpu_spatial_candidates import GPUSpatialPlanner
except ImportError:
    from gpu_spatial_candidates import GPUSpatialPlanner

parser = argparse.ArgumentParser()
parser.add_argument("initialize_json")
parser.add_argument("--out", default="gpu_benchmark_result.json")
args = parser.parse_args()
payload = json.loads(Path(args.initialize_json).read_text())
planner = GPUSpatialPlanner(payload)
snapshot = {"now_utc": payload["survey"]["nights"][0]["observing_start_utc"]}
env = {"quality_scale": .55, "program_band_quality_scale": .55 / .95,
       "gpu_anchor_count": 320, "gpu_refine_count": 48,
       "gpu_refine_budget_seconds": .4}
runs = []
for run in range(3):
    start = time.perf_counter()
    action = planner.choose(snapshot, {}, {}, env, [])
    runs.append({"elapsed_seconds": time.perf_counter() - start, "stats": planner.stats, "action": action})
    print(json.dumps({"run": run, **runs[-1]}, ensure_ascii=False), flush=True)
centers, useful = planner._build_centers(planner._frame, env)
test_centers = centers[np.unique(np.rint(np.linspace(0, len(centers) - 1, 40)).astype(int))]
start = time.perf_counter()
gpu_rates, durations = planner.coarse_gpu(test_centers, useful, planner._frame, env)
gpu_seconds = time.perf_counter() - start
start = time.perf_counter()
cpu_rates = planner.coarse_numpy(test_centers, useful, planner._frame, durations)
cpu_seconds = time.perf_counter() - start
error = float(np.max(np.abs(cpu_rates - gpu_rates)))
assert error < 1e-10, (error, cpu_rates, gpu_rates)
result = {"runs": runs, "crosscheck_centers": len(test_centers), "crosscheck_max_absolute_error": error,
          "crosscheck_gpu_seconds": gpu_seconds, "crosscheck_cpu_seconds": cpu_seconds,
          "prediction": planner.last_prediction, "now_utc": snapshot["now_utc"]}
Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({k: v for k, v in result.items() if k not in ("runs", "prediction")}), flush=True)
