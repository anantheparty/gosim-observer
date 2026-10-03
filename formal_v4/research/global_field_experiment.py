#!/usr/bin/env python3
"""Source-locked global spherical search, microchecks and complete workflows."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import numpy as np

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'results/global_field_20261004'
FROZEN=BASE/'runs/cold_neural_value_20261003/production_frozen'
OFFICIAL=BASE/'upstream/gosim-observer-examples'
FILES=('policy.py','policy_config.json','research/geometry.py','research/feedback_model.py',
       'research/spatial_candidates.py','research/belief_clock.py','research/efficiency_bounds.py',
       'research/remote_budget.py','research/pointing_calibration.py')

def prepare():
    snapshot=OUT/'source_snapshot/participant'
    if not snapshot.exists():
        for name in FILES:
            dst=snapshot/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(FROZEN/name,dst)
        for name in ('cpu_phase_candidates.py','global_field_planner.py'):
            shutil.copyfile(BASE/'research'/name,snapshot/'research'/name)
        for kernel in OUT.glob('global_field_search_*'):
            if kernel.suffix in ('.dylib','.so'):
                shutil.copyfile(kernel,snapshot/'research'/kernel.name)
        hashes={str(p.relative_to(snapshot)):hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.rglob('*') if p.is_file()}
        (OUT/'source_lock.json').write_text(json.dumps(hashes,indent=2,sort_keys=True)+'\n')
    sys.path.insert(0,str(snapshot));sys.path.insert(1,str(OFFICIAL))
    from runner.challenge.v4_workflow import V4Workflow,PROTOCOL_VERSION
    from runner.challenge.v4_fiber_map import FiberGrid
    from research.global_field_planner import GlobalFieldPlanner,load_native,optimistic_rates
    import policy
    return snapshot,V4Workflow,FiberGrid,GlobalFieldPlanner,load_native,optimistic_rates,policy,PROTOCOL_VERSION

def micro(card,nodes):
    snapshot,V4Workflow,FiberGrid,Planner,load_native,optimistic_rates,policy,version=prepare()
    initial=V4Workflow(OFFICIAL/'local-cards'/card).initialize_payload(900)
    p=Planner(initial)
    snap=dict(now_utc=initial['survey']['nights'][0]['observing_start_utc'],observe_action_index=0,
              new_messages=[],active_requests=[])
    env=dict(anchor_count=24,quality_scale=.55,program_band_quality_scale=.55/.95,global_field_nodes=nodes)
    record={}
    def hook(s,frame,useful,upper,cfg,proposals,stats,base,best):
        np.savez_compressed(OUT/f'micro_{card}.npz',vectors=frame[0],up=frame[1],k=frame[2],scores=frame[3],
                           factors=frame[4],mult=frame[5],missing=frame[6],rr=frame[7],rt=frame[8],rd=frame[9],
                           ub=frame[10],urg=frame[11],useful=useful,upper=upper,cfg=cfg,proposals=proposals)
        record.update(stats=stats,baseline_action=base,selected_candidate=None if best is None else
                      dict(rate=float(best[0]),center=list(best[1]),duration=int(best[2]),program=int(best[3])))
    p.export_hook=hook
    started=time.perf_counter();action=p.choose(snap,{}, {},env,[]);seconds=time.perf_counter()-started
    grid=FiberGrid.from_config(json.loads((OFFICIAL/'local-cards'/card/'config/v4_fiber_config.json').read_text()))
    from research.spatial_candidates import parse_utc
    lookup={row[0]:row for row in initial['targets']['rows']}
    for f,tid in action['assignments'].items():
        row=lookup[tid]
        c=grid.classify_target(row[1],row[2],parse_utc(snap['now_utc']),action['pointing']['alt_deg'],
                              action['pointing']['az_deg'],p.lat,p.lon)
        assert c.fiber_id==int(f) and c.region=='glass',(c,f,tid)
    record.update(card=card,nodes=nodes,seconds=seconds,action=action,official_geometry_valid=True,
                  summary=p.global_summary,source_lock=json.loads((OUT/'source_lock.json').read_text()))
    (OUT/f'micro_{card}.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record),flush=True)

def check():
    snapshot,V4Workflow,FiberGrid,Planner,load_native,optimistic_rates,policy,version=prepare()
    native=load_native();rng=np.random.default_rng(2601004);cases=0
    # Independent official projection at random interior points of each box.
    grid=FiberGrid(.4,0.,16)
    for _ in range(1500):
        a=float(rng.uniform(28,90));z=float(rng.uniform(0,360))
        al,ah=sorted(rng.uniform(max(0,a-5),min(90,a+5),2));zl,zh=sorted(rng.uniform(z-8,z+8,2))
        mask=native.global_field_mask(a,z,al,ah,zl,zh,4,grid.pitch_deg,grid.fiber_side_deg)
        for j in range(40):
            ca=float(rng.uniform(al,ah));cz=float(rng.uniform(zl,zh))
            off=grid.tangent_offsets(a,z,ca,cz)
            if off is None:continue
            f,region=grid.classify_offset(*off)
            if region=='glass':
                r,c=divmod(f,4);rn,re=grid.fiber_center_offset(f)
                if max(abs(off[0]-rn),abs(off[1]-re))<=grid.fiber_side_deg/2-.008:
                    assert mask&(1<<f),(a,z,al,ah,zl,zh,ca,cz,f,mask)
                    cases+=1
    result=dict(event='mask_check',boxes=1500,points=60000,interior_hits=cases,violations=0)
    (OUT/'mask_check.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)

def run(card,mode,nodes):
    snapshot,V4Workflow,FiberGrid,Planner,load_native,optimistic_rates,policy,version=prepare()
    from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
    class Control(CPUPhaseSpatialPlanner):
        def choose(self,s,scores,factors,env=None,requests=None):
            e=dict(env or {});e['cpu_phase_fixed_workload']=True;e['anchor_count']=24
            return super().choose(s,scores,factors,e,requests)
    class Treatment(Planner):
        def choose(self,s,scores,factors,env=None,requests=None):
            e=dict(env or {});e['global_field_nodes']=nodes
            return super().choose(s,scores,factors,e,requests)
    policy.SpatialPlanner=Control if mode=='control' else Treatment
    workflow=V4Workflow(OFFICIAL/'local-cards'/card)
    initial=workflow.initialize_payload(900);p=policy.Policy(initial)
    if p.remote is not None:raise ValueError('unexpected remote policy')
    raw=OUT/mode/card;raw.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter();calls=0
    def decide(message,deadline):
        nonlocal calls
        calls+=1;snap=message['payload'];action=p.decide(snap)
        if calls%100==0:
            print(json.dumps(dict(event='progress',card=card,mode=mode,calls=calls,
                                 now=snap['now_utc'],observe=snap['observe_action_index'],seconds=time.perf_counter()-started)),flush=True)
        return dict(protocol_version=version,message_type='decision_response',decision_sequence=message['decision_sequence'],**action)
    result=workflow.run(decide,raw,wallclock_seconds=900)
    summary=dict(card=card,mode=mode,nodes=nodes,seconds=time.perf_counter()-started,
                 score_report=result['score_report'],termination=result['termination_reason'],
                 agent_seconds=result['agent_wallclock_seconds'],policy_summary=p.summary(),
                 phase_summary=p.planner.cpu_phase_summary,source_lock=json.loads((OUT/'source_lock.json').read_text()))
    if mode!='control':summary['global_summary']=p.planner.global_summary
    (raw/'experiment_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--card',choices=['L1','L2','L3','L4'],default='L1')
    ap.add_argument('--mode',choices=['check','micro','control','search'],default='micro');ap.add_argument('--nodes',type=int,default=1024)
    a=ap.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    if a.mode=='check':check()
    elif a.mode=='micro':micro(a.card,a.nodes)
    else:run(a.card,a.mode,a.nodes)
