#!/usr/bin/env python3
"""Independent CPU phase + request-DP entry for an official local gate."""
import os
from pathlib import Path
os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
os.environ.setdefault("OMP_NUM_THREADS","1")
os.environ.setdefault("MKL_NUM_THREADS","1")
import policy
from research.request_deadline_cpu import RequestCPUDeadlinePlanner
if Path(policy.__file__).with_name("remote_runtime.json").exists():
    raise ValueError("CPU request-DP gate requires an isolated agent")
policy.SpatialPlanner=RequestCPUDeadlinePlanner
old_summary=policy.Policy.summary
def summary(self):
    return {**old_summary(self),"cpu_phase":self.planner.cpu_phase_summary,
            "request_dp":self.planner.request_dp_summary()}
policy.Policy.summary=summary
from agent import main
if __name__=="__main__":main()
