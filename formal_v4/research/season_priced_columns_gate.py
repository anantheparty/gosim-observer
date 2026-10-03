"""Append an independently priced conditional column batch to the season master.

New research output only. No hidden data, production change, network or GPU.
"""
from __future__ import annotations
import argparse,csv,json,math,os,sys,time
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('MKL_NUM_THREADS','1')
import numpy as np
import season_column_dual_audit as dual_audit
import season_science_required_master as frozen
from required_opportunity_model import parse,stamp


def gate(root,input_path,out):
    began=time.perf_counter();batch=json.loads(input_path.read_text());card=batch['card']
    old=dual_audit.capture(root,card);columns,model,requests,fixed=[old[k] for k in ('columns','model','requests','fixed')]
    source=json.loads((root/'formal_v4/results'/f'cloud_cd2_{card}_20261003/score_report.json').read_text())
    report_value=source['components']['report_settlement'];times=set(x['start'] for x in columns)|set(x['end'] for x in columns)
    report_times=[parse(d['start_utc']).timestamp() for d in csv.DictReader((root/'formal_v4/results'/f'cloud_cd2_{card}_20261003/decisions.csv').open()) if d['action']=='report']
    messages=[json.loads(l) for l in (root/'formal_v4/results'/f'cloud_cd2_{card}_20261003/messages.jsonl').read_text().splitlines()]
    prefix=max((parse(m['issued_at_utc']).timestamp() for m in messages if m['record_type']=='state_resync'),default=None)
    from request_remote_owned_gate import initial_public
    from spatial_candidates import SpatialPlanner,local_sidereal,SIDEREAL_SPEED
    from challenge.v4_fiber_map import FiberGrid
    initial,_=initial_public(root/'formal_v4/practice_cards'/card/card);planner=SpatialPlanner(initial)
    grid=FiberGrid(planner.glass**2,planner.pitch-planner.glass,planner.nfib)
    checks=0;new=[]
    for c in batch['columns']:
        assert c['start'] in times and c['end'] in times,'new endpoint is not an existing pricing node'
        assert prefix is None or c['start']>=prefix
        assert not any(c['start']<t<c['end'] for t in report_times)
        action=c['action'];duration=c['end']-c['start']
        assert duration==action['duration_seconds'] and planner.tmin<=duration<=planner.tmax
        assert action['program'] in ('DARK','BRIGHT','BACKUP')
        assignment=action['assignments'];assert len(set(assignment.values()))==len(assignment)
        assert set(assignment.values())==set(c['entries'])
        now=parse(stamp(c['start']));point=action['pointing'];alt,az,hour,vectors=planner._altaz(local_sidereal(now,planner.lon))
        fiber,valid,margin=planner._classify(vectors,point['alt_deg'],point['az_deg']);up=np.where(planner.hmax>=180,1e9,(planner.hmax-hour)/SIDEREAL_SPEED)
        for fid,tid in assignment.items():
            i=model.index[tid];e=c['entries'][tid]
            assert all(math.isfinite(float(e[k])) for k in ('factor_lower','factor_upper','score_lower','score_upper'))
            assert 0<=e['factor_lower']<=e['factor_upper']<=1+1e-9
            assert 0<=e['score_lower']<=e['score_upper']<=planner.weight[i]*1.2+1e-8
            hit=grid.classify_target(model.ra[i],model.dec[i],now,point['alt_deg'],point['az_deg'],planner.lat,planner.lon)
            assert hit.region=='glass' and hit.fiber_id==int(fid)
            assert alt[i]>=planner.min_alt+.04-1e-9 and up[i]>=duration-1e-8 and margin[i]>.03-1e-9
            checks+=1
        new.append({**c,'kind':'joint-dual-priced'})
    full=columns+new;historical=[j for j,c in enumerate(columns) if c['kind']=='historical']
    baseline=frozen.settle(full,historical,model,requests,report_value)
    mip,stats=frozen.solve_master(full,model,requests,fixed,'lower',90)
    selected=[j for j in range(len(full)) if mip.x is not None and mip.x[j]>.5] if mip.x is not None else historical
    primal=frozen.settle(full,selected,model,requests,report_value)
    old_lp,olddual,old_lp_stats=dual_audit.lp_duals(columns,model,requests,fixed)
    new_lp,newdual,new_lp_stats=dual_audit.lp_duals(full,model,requests,fixed)
    incumbent_kept=primal['total_conditional_conservative']<=baseline['total_conditional_conservative']+.0000005*len(model.ids)
    output={'card':card,'input':str(input_path),'research_scope':batch.get('scope'),'hidden_inputs_read':False,
            'new_columns':len(new),'official_assignment_geometry_checks':checks,
            'old_finite_lp_objective_without_constants':-old_lp.fun,'new_finite_lp_objective_without_constants':-new_lp.fun,
            'optimistic_finite_lp_change':old_lp.fun-new_lp.fun,'mip_status':mip.status,'mip_gap':getattr(mip,'mip_gap',None),'mip_stats':stats,
            'baseline':baseline,'conservative_primal':primal,'conditional_net_change':primal['total_conditional_conservative']-baseline['total_conditional_conservative'],
            'science_change':primal['science']-baseline['science'],'required_reward_change':50*(baseline['required_missing']-primal['required_missing']),
            'request_reward_change':sum(primal['request_rewards'])-sum(baseline['request_rewards']),
            'uniformity_change':baseline['uniformity_penalty']-primal['uniformity_penalty'],
            'selected_new_column_indices':[j-len(columns) for j in selected if j>=len(columns)],
            'incumbent_preferred_on_net_tie':incumbent_kept,'missing_column_global_bound_available':False,
            'elapsed_seconds':time.perf_counter()-began}
    out.mkdir(parents=True,exist_ok=True);(out/'gate.json').write_text(json.dumps(output,indent=2))
    schedule=[{'start_utc':stamp(full[j]['start']),'end_utc':stamp(full[j]['end']),'kind':full[j]['kind'],'action':full[j]['action']} for j in sorted(selected,key=lambda j:full[j]['start'])]
    schedule+=[{'start_utc':stamp(t),'end_utc':stamp(t),'kind':'fixed-report','action':{'action':'report'}} for t in report_times]
    (out/'primal_schedule.json').write_text(json.dumps(sorted(schedule,key=lambda s:(s['start_utc'],s['kind'])),indent=2))
    print(json.dumps(output,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'formal_v4/upstream/gosim-observer-examples/runner'))
    gate(root,Path(args.input),Path(args.out))
