#!/usr/bin/env python3
"""Independent GPU phase + shared terrain + future request DP local gate."""
import os
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import policy
from research.request_deadline_planner import RequestDPPlanner
from research.terrain_policy import install_terrain_policy
if Path(policy.__file__).with_name('remote_runtime.json').exists():
    raise ValueError('GPU future request-DP gate requires an isolated agent')

class AuditedGPUPlanner(RequestDPPlanner):
    def __init__(self,initial):
        super().__init__(initial)
        self.gpu_gate_counts={'choose_calls':0,'baseline_emergency_count':0,'phase_emergency_count':0}

    def choose(self,*args,**kwargs):
        action=super().choose(*args,**kwargs)
        self.gpu_gate_counts['choose_calls']+=1
        self.gpu_gate_counts['baseline_emergency_count']+=int(self.stats.get('emergency_triggered',False))
        self.gpu_gate_counts['phase_emergency_count']+=int(self.stats.get('phase_emergency_triggered',False))
        return action

policy.SpatialPlanner=AuditedGPUPlanner
policy.Policy=install_terrain_policy(policy.Policy)
old_summary=policy.Policy.summary
def summary(self):
    return {**old_summary(self),'gpu_gate':self.planner.gpu_gate_counts,
            'request_dp':self.planner.request_dp_summary()}
policy.Policy.summary=summary
from agent import main
if __name__=='__main__':main()
