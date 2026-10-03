#!/usr/bin/env python3
"""Fixed candidate-work control for the locked baseline/hierarchy pair."""
from __future__ import annotations
import os
from pathlib import Path
import sys
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
SOURCE=Path(__file__).resolve().parents[1]/'runs/cold_neural_value_20261003/production_frozen'
sys.path.insert(0,str(SOURCE))
import policy
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
policy.SpatialPlanner=CPUPhaseSpatialPlanner
old_init=policy.Policy.__init__
def fixed_init(self,initial):
    old_init(self,initial)
    self.config.update(cpu_phase_mode='bypass',cpu_phase_fixed_workload=True,anchor_count=24)
policy.Policy.__init__=fixed_init
old_summary=policy.Policy.summary
def fixed_summary(self):
    return {**old_summary(self),'cpu_phase':self.planner.cpu_phase_summary,
            'generator_forecast_fixed_workload':True}
policy.Policy.summary=fixed_summary
from generator_forecast_agent import main
if __name__=='__main__':main()
