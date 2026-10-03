#!/usr/bin/env python3
"""Independent CPU-only phase/bypass entry for official local full-card gates."""
import os
from pathlib import Path
os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
os.environ.setdefault("OMP_NUM_THREADS","1")
os.environ.setdefault("MKL_NUM_THREADS","1")
import policy
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
if Path(policy.__file__).with_name("remote_runtime.json").exists():
    raise ValueError("CPU phase gate requires an isolated agent without RPC config")
policy.SpatialPlanner=CPUPhaseSpatialPlanner
old_summary=policy.Policy.summary
def summary(self):
    return {**old_summary(self),"cpu_phase":self.planner.cpu_phase_summary}
policy.Policy.summary=summary
from agent import main
if __name__=="__main__":main()
