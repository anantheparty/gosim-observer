#!/usr/bin/env python3
"""Fixed-work same-source baseline / free-coupon diagnostic participant."""
from __future__ import annotations
import argparse
import json
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
from generator_diagnostic_model import install_diagnostic_policy
policy.SpatialPlanner=CPUPhaseSpatialPlanner
old_init=policy.Policy.__init__
def fixed_init(self,initial):
    old_init(self,initial)
    self.config.update(cpu_phase_mode='bypass',cpu_phase_fixed_workload=True,anchor_count=24)
policy.Policy.__init__=fixed_init

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--mode',choices=['baseline','diagnostic'],required=True)
    mode=ap.parse_args().mode
    cls=policy.Policy if mode=='baseline' else install_diagnostic_policy(policy.Policy)
    p=None
    for line in sys.stdin:
        if not line.strip():continue
        m=json.loads(line);kind=m.get('message_type')
        if kind=='initialize':p=cls(m['payload'])
        elif kind=='decision_request':
            action=p.decide(m['payload'])
            print(json.dumps({'protocol_version':'participant-agent-protocol-v4',
                'message_type':'decision_response','decision_sequence':m['decision_sequence'],**action},
                separators=(',',':'),allow_nan=False),flush=True)
        elif kind=='finish':
            print(json.dumps({**p.summary(),'cpu_phase':p.planner.cpu_phase_summary,
                'generator_diagnostic_fixed_workload':True}),file=sys.stderr,flush=True);break
    if p and p.remote:p.remote.close()
if __name__=='__main__':main()
