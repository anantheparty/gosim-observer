#!/usr/bin/env python3
"""CPU-only isolated traditional NN continuation experiment entry."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
os.environ.setdefault("OMP_NUM_THREADS","1")
os.environ.setdefault("MKL_NUM_THREADS","1")
import policy
if Path(policy.__file__).with_name("remote_runtime.json").exists():
    raise ValueError("isolated CPU continuation gate must not contain remote config")
from research.cold_neural_policy import NeuralContinuationSpatialPlanner
policy.SpatialPlanner=NeuralContinuationSpatialPlanner
old_summary=policy.Policy.summary
def summary(self):
    return {**old_summary(self),"neural_continuation":{"calls":self.planner.nn_calls,
        "seconds":self.planner.nn_seconds,"strength":self.planner.nn_strength}}
policy.Policy.summary=summary
from agent import main
if __name__=="__main__":main()
