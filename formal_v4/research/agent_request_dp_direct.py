#!/usr/bin/env python3
"""Independent direct GPU request-DP entry; policy_config enables/bypasses it."""
import os
from pathlib import Path
os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
os.environ.setdefault("OMP_NUM_THREADS","1")
os.environ.setdefault("MKL_NUM_THREADS","1")

import policy
from research.request_deadline_planner import RequestDPPlanner
if Path(policy.__file__).with_name("remote_runtime.json").exists():
    raise ValueError("Request DP experiment requires an isolated direct agent")
policy.SpatialPlanner = RequestDPPlanner
old_summary = policy.Policy.summary
def summary(self):
    return {**old_summary(self),"request_dp":self.planner.request_dp_summary()}
policy.Policy.summary = summary
from agent import main
if __name__=="__main__":main()
