#!/usr/bin/env python3
"""Opt-in shared terrain state + CPU phase + published future request DP."""
import os
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import policy
from research.request_deadline_cpu import RequestCPUDeadlinePlanner
from research.terrain_policy import install_terrain_policy
if Path(policy.__file__).with_name('remote_runtime.json').exists():
    raise ValueError('future request-DP gate requires an isolated agent')
policy.SpatialPlanner=RequestCPUDeadlinePlanner
policy.Policy=install_terrain_policy(policy.Policy)
old_summary=policy.Policy.summary
def summary(self):
    return {**old_summary(self),'cpu_phase':self.planner.cpu_phase_summary,
            'request_dp':self.planner.request_dp_summary()}
policy.Policy.summary=summary
from agent import main
if __name__=='__main__':main()
