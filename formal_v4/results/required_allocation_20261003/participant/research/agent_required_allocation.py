#!/usr/bin/env python3
"""Public-input CPUPhase plus calendar reservation participant entry."""
import os
from pathlib import Path

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
import policy
from research.required_allocation_calendar import RequiredAllocationPlanner

if Path(policy.__file__).with_name('remote_runtime.json').exists():
    raise ValueError('Required calendar gate requires an isolated CPU participant')
policy.SpatialPlanner = RequiredAllocationPlanner
old_summary = policy.Policy.summary
def summary(self):
    return {**old_summary(self), 'cpu_phase': self.planner.cpu_phase_summary,
            'required_allocation': self.planner.calendar.summary}
policy.Policy.summary = summary
from agent import main
if __name__ == '__main__':
    main()
