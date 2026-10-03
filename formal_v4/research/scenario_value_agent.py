#!/usr/bin/env python3
"""Same frozen source, fixed strong CPUPhase baseline/finite-path participant."""
from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[name]='1'
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runs/cold_neural_value_20261003/production_frozen'
sys.path.insert(0,str(SOURCE))
import policy
from scenario_value_model import ScenarioValuePlanner,install_policy
policy.SpatialPlanner=ScenarioValuePlanner

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--mode',choices=('baseline','scenario','integrated'),required=True)
    args=ap.parse_args();cls=install_policy(policy.Policy,args.mode);p=None
    if (SOURCE/'remote_runtime.json').exists():raise ValueError('isolated CPU source required')
    for line in sys.stdin:
        if not line.strip():continue
        message=json.loads(line);kind=message.get('message_type')
        if kind=='initialize':p=cls(message['payload'])
        elif kind=='decision_request':
            action=p.decide(message['payload'])
            print(json.dumps(dict(protocol_version='participant-agent-protocol-v4',message_type='decision_response',
                decision_sequence=message['decision_sequence'],**action),separators=(',',':'),allow_nan=False),flush=True)
        elif kind=='finish':
            print(json.dumps(p.summary()),file=sys.stderr,flush=True);break
    if p and p.remote:p.remote.close()
if __name__=='__main__':main()
