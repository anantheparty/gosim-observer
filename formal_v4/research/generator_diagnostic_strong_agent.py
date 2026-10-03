#!/usr/bin/env python3
"""Frozen diagnostic controller paired with phase24 or frozen native geometry."""
from __future__ import annotations
import argparse,json,os
from pathlib import Path
import sys
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--mode',choices=['baseline','diagnostic-reserve'],required=True)
    ap.add_argument('--planner',choices=['phase24','native'],required=True)
    a=ap.parse_args()
    source=ROOT/'runs/cold_neural_value_20261003/production_frozen' if a.planner=='phase24' else ROOT/'runs/generator_diagnostic_native_snapshot_20261003'
    sys.path.insert(0,str(source))
    import policy
    from generator_diagnostic_model import install_diagnostic_policy
    if a.planner=='phase24':
        from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
        policy.SpatialPlanner=CPUPhaseSpatialPlanner
    else:
        from research.geometry_native import load_library
        from research.candidate_geometry_sweep import CandidateGeometryPlanner
        load_library();policy.SpatialPlanner=CandidateGeometryPlanner
    cls=policy.Policy if a.mode=='baseline' else install_diagnostic_policy(policy.Policy,reserve_coupons=1)
    p=None
    for line in sys.stdin:
        if not line.strip():continue
        m=json.loads(line);kind=m.get('message_type')
        if kind=='initialize':
            p=cls(m['payload'])
            if a.planner=='phase24':
                p.config.update(cpu_phase_mode='phase',cpu_phase_fixed_workload=True,anchor_count=24,
                   cpu_phase_top_count=4,cpu_phase_local_target_count=50,cpu_phase_boundary_target_count=24,
                   cpu_phase_exact_count=16)
        elif kind=='decision_request':
            action=p.decide(m['payload'])
            print(json.dumps({'protocol_version':'participant-agent-protocol-v4',
                'message_type':'decision_response','decision_sequence':m['decision_sequence'],**action},
                separators=(',',':'),allow_nan=False),flush=True)
        elif kind=='finish':
            planner_summary=p.planner.cpu_phase_summary if a.planner=='phase24' else p.planner.geometry_summary
            print(json.dumps({**p.summary(),'generator_diagnostic_planner':a.planner,
                'planner_summary':planner_summary}),file=sys.stderr,flush=True);break
    if p and p.remote:p.remote.close()

if __name__=='__main__':main()
