#!/usr/bin/env python3
"""Frozen-policy weighted sweep microbenchmarks and complete native seasons."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'results/candidate_geometry_20261003'
FROZEN=BASE/'runs/cold_neural_value_20261003/production_frozen'
OFFICIAL=BASE/'upstream/gosim-observer-examples'
sys.path.insert(0,str(FROZEN));sys.path.insert(0,str(OFFICIAL))
from runner.challenge.v4_workflow import V4Workflow
from runner.challenge.v4_runner import run_scenario
from runner.challenge.v4_fiber_map import FiberGrid
from research.spatial_candidates import SpatialPlanner
import numpy as np
import policy

spec=importlib.util.spec_from_file_location('research.candidate_geometry_sweep',BASE/'research/candidate_geometry_sweep.py')
cg=importlib.util.module_from_spec(spec);sys.modules[spec.name]=cg;spec.loader.exec_module(cg)


class DeterministicPlanner(SpatialPlanner):
    def choose(self,snapshot,scores,factors,env_estimate=None,active_requests=None):
        env=dict(env_estimate or {});env['planning_budget_seconds']=30.
        return super().choose(snapshot,scores,factors,env,active_requests)


def manifest():
    files=[FROZEN/'policy.py',FROZEN/'research/spatial_candidates.py',FROZEN/'research/cpu_phase_candidates.py',
           BASE/'research/candidate_geometry_sweep.py',Path(__file__).resolve()]
    return {str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def export_hook(card,period=12):
    folder=OUT/'labels'/card;folder.mkdir(parents=True,exist_ok=True)
    def export(snapshot,groups,stats,base,best):
        idx=int(snapshot.get('observe_action_index',0))
        if idx%period:return
        for j,g in enumerate(groups):
            np.savez_compressed(folder/f'{idx:05d}_{j}.npz',**g)
        record={'card':card,'observe_index':idx,'now_utc':snapshot['now_utc'],'stats':stats,
                'baseline_action':base,'selected_center':list(best[1]),'selected_duration':int(best[2]),
                'selected_program_index':int(best[3]),'groups':len(groups)}
        (folder/f'{idx:05d}.json').write_text(json.dumps(record,indent=2))
    return export


def run(card,mode,period):
    policy.SpatialPlanner=cg.CandidateGeometryPlanner if mode=='sweep' else DeterministicPlanner
    initial=V4Workflow(OFFICIAL/'local-cards'/card).initialize_payload(900)
    p=policy.Policy(initial)
    if p.remote is not None:raise ValueError('CPU-only frozen source required')
    if mode=='sweep':p.planner.export_hook=export_hook(card,period)
    raw=OUT/mode/card;raw.mkdir(parents=True,exist_ok=True)
    begin=time.perf_counter();calls=0
    def decide(snapshot):
        nonlocal calls
        action=p.decide(snapshot);calls+=1
        if calls%200==0:
            print(json.dumps(dict(event='progress',card=card,mode=mode,calls=calls,observe=snapshot['observe_action_index'],
                                 now=snapshot['now_utc'],seconds=time.perf_counter()-begin)),flush=True)
        return action
    report=run_scenario(OFFICIAL/'local-cards'/card/'config/v4_scenario.json',lambda _:decide,raw)
    result=dict(card=card,mode=mode,seconds=time.perf_counter()-begin,total=report['total'],components=report['components'],
                counts=report['counts'],termination=report['termination'],policy_summary=p.summary(),source_sha256=manifest())
    if mode=='sweep':result['geometry_summary']=p.planner.geometry_summary
    (raw/'experiment_summary.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)


def micro(card):
    initial=V4Workflow(OFFICIAL/'local-cards'/card).initialize_payload(900)
    planner=cg.CandidateGeometryPlanner(initial)
    snap=dict(now_utc=initial['survey']['nights'][0]['observing_start_utc'],observe_action_index=0,new_messages=[],active_requests=[])
    env=dict(anchor_count=24,quality_scale=.55,program_band_quality_scale=.55/.95)
    planner.export_hook=export_hook(card,1)
    begin=time.perf_counter();action=planner.choose(snap,{}, {},env,[])
    result=dict(card=card,seconds=time.perf_counter()-begin,stats=planner.stats,action=action,geometry_summary=planner.geometry_summary)
    # Official geometry validator independently checks every assignment.
    config=json.loads((OFFICIAL/'local-cards'/card/'config/v4_fiber_config.json').read_text());grid=FiberGrid.from_config(config)
    lookup={row[0]:row for row in initial['targets']['rows']}
    for fiber,target in action['assignments'].items():
        row=lookup[target]
        cl=grid.classify_target(float(row[1]),float(row[2]),cg.parse_utc(snap['now_utc']),
                               action['pointing']['alt_deg'],action['pointing']['az_deg'],planner.lat,planner.lon)
        assert cl.region=='glass' and cl.fiber_id==int(fiber),(cl,fiber,target)
    result['official_geometry_valid']=True
    OUT.mkdir(parents=True,exist_ok=True);(OUT/f'micro_{card}.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--card',choices=['L1','L2','L3','L4'],default='L1')
    parser.add_argument('--mode',choices=['baseline','sweep','micro'],default='micro');parser.add_argument('--export-period',type=int,default=12)
    args=parser.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    if args.mode=='micro':micro(args.card)
    else:run(args.card,args.mode,args.export_period)


if __name__=='__main__':main()
