"""Replay an owned all-observe prefix using public rounded protocol feedback.

The first divergence being studied is alpha action index 24. No engine/truth.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

FORMAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FORMAL))
from pack_verified_portfolio import public_card

SHA = lambda b: hashlib.sha256(b).hexdigest()

CHILD = r'''
import json,sys,hashlib,time,os
from datetime import datetime
import numpy as np
from research import agent_model_gpu
import policy,remote_planner
from research import spatial_candidates as spatial,cpu_phase_candidates as phase
class Disabled:
    enabled=False
    def __init__(self,*a):pass
    def check(self):return {'remote_check':'disabled','seconds':0}
remote_planner.RemotePlanner=Disabled
inp=json.load(open(sys.argv[1]))
p=policy.Policy(inp['initial'])
assert type(p.planner) is phase.CPUPhaseSpatialPlanner
sha=lambda b:hashlib.sha256(b).hexdigest()
def clean(x):
    if isinstance(x,np.ndarray):return {'dtype':str(x.dtype),'shape':list(x.shape),'sha256':sha(x.tobytes())}
    if isinstance(x,np.generic):return x.item()
    if isinstance(x,datetime):return x.isoformat()
    if isinstance(x,set):return sorted(x)
    if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
    if isinstance(x,(tuple,list)):return [clean(v) for v in x]
    return x
def hashvalue(v):return sha(json.dumps(clean(v),sort_keys=True,separators=(',',':'),allow_nan=False).encode())
exact=[];coarse=[];captured={};rawframe=[None]
oldexact=spatial.SpatialPlanner._evaluate
def exact_hook(self,center,pool,*frame):
    if rawframe[0] is None:rawframe[0]=frame
    result=oldexact(self,center,pool,*frame)
    exact.append({'center':list(center),'pool':clean(np.asarray(pool)),'result':clean(result)})
    return result
spatial.SpatialPlanner._evaluate=exact_hook
oldcoarse=phase.coarse_numpy_local
def coarse_hook(*args,**kwargs):
    result=oldcoarse(*args,**kwargs)
    coarse.append({'centers':clean(np.asarray(args[1])),'pool':clean(np.asarray(args[2])),'durations':clean(np.asarray(args[4])),'rates':clean(result)})
    return result
phase.coarse_numpy_local=coarse_hook
oldchoose=p.planner.choose
def choose_hook(snapshot,scores,factors,env,requests):
    captured.clear()
    captured.update({'env':clean({k:v for k,v in env.items() if k!='planning_budget_seconds'}),
                    'ignored_outer_planning_budget_seconds':env.get('planning_budget_seconds'),
                    'state':clean({'C':p.C,'E':p.E,'scores':p.scores,'factors':p.factors,'factor_lower':p.factor_lower,
                                  'calibration_estimate':p.calibrator.estimate,'calibration_diagnostics':p.calibrator.diagnostics,
                                  'terrain':p.terrain,'notices':p.notices,'blocked_spots':list(p.blocked_spots),
                                  'belief_anchor':p.belief_clock.anchor})})
    return oldchoose(snapshot,scores,factors,env,requests)
p.planner.choose=choose_hook
trace=[];first_mismatch=None
for i,snapshot in enumerate(inp['snapshots']):
    exact.clear();coarse.clear();captured.clear();rawframe[0]=None
    action=p.decide(snapshot)
    expected=inp['prefix_actions'][i] if i<len(inp['prefix_actions']) else None
    equal=action==expected if expected is not None else None
    if equal is False and first_mismatch is None:first_mismatch=i
    trace.append({'action_index':i,'now_utc':snapshot['now_utc'],'generated_action':action,
                  'matches_owned_prefix':equal,'state':captured.get('state'),
                  'state_sha256':hashvalue(captured.get('state')),'env':captured.get('env'),
                  'env_sha256':hashvalue(captured.get('env')),
                  'outer_planning_budget_seconds':captured.get('ignored_outer_planning_budget_seconds'),
                  'exact_count':len(exact),'exact_candidates_sha256':hashvalue(exact),
                  'coarse_groups':coarse,'coarse_sha256':hashvalue(coarse),
                  'phase_stats':{k:v for k,v in p.planner.stats.items() if 'seconds' not in k}})
    if expected is None and rawframe[0] is not None:
        frame=rawframe[0]
        old=inp['next_old_action']
        center=(old['pointing']['alt_deg']+p.calibrator.estimate[0],(old['pointing']['az_deg']+p.calibrator.estimate[1])%360)
        useful=np.flatnonzero(p.planner._merit(frame)>1e-10)
        oldresult=oldexact(p.planner,center,useful,*frame)
        trace[-1]['old_command_exact_reoptimized']=clean(oldresult)
        trace[-1]['top_exact_results']=sorted([x['result'] for x in exact if x['result'] is not None],key=lambda x:-x[0])[:10]
        vectors,up,k,scores,factors,mult,missing,rr,rt,rd,ub,urgency,secondsleft,safety,focus=frame
        idx=np.asarray([p.planner.index[t] for t in old['assignments'].values()])
        duration=old['duration_seconds'];prog=spatial.PROGRAMS.index(old['program'])
        raw=np.minimum(1.,duration*k[idx]);robust=np.minimum(1.,duration*k[idx]/safety)
        gain=np.maximum(0.,p.planner.weight[idx]*raw*mult[prog,idx]-scores[idx])
        terminal=missing[idx]*(robust+1e-10>=p.planner.req_threshold)*p.planner.req_penalty
        terminal+=(factors[idx]<p.planner.uniform_threshold)*(robust+1e-10>=p.planner.uniform_threshold)*ub[idx]
        terminal+=(rr[idx]>0)*(robust+1e-10>=rt[idx])*(duration<=rd[idx])*rr[idx]
        trace[-1]['old_actual_assignments_frozen_rate']=float(((gain+terminal)*urgency[idx]).sum()/duration)
    if expected is not None and equal is False:
        # Continue on the actual owned action. Only alt/az prediction is read
        # by stable feedback ingestion; reconstruct it from exact public sky
        # geometry and the actual assigned targets. This is explicitly marked.
        now=spatial.parse_utc(snapshot['now_utc']);alt,az,_,_=p.planner._altaz(spatial.local_sidereal(now,p.planner.lon))
        prediction={tid:{'alt_deg':float(alt[p.planner.index[tid]]),'az_deg':float(az[p.planner.index[tid]])} for tid in expected['assignments'].values()}
        pending=p.pending or {}
        p.pending={'action':expected,'start':now,'prediction':prediction,'notices':list(p.notices),
                   'prior_C':pending.get('prior_C',p.C),'prior_E':pending.get('prior_E',p.E)}
        trace[-1]['owned_action_forced_after_local_divergence']=True
print(json.dumps({'python_hash_seed':os.environ.get('PYTHONHASHSEED'),'numpy_version':np.__version__,
                  'python_version':sys.version,'policy_module_path':policy.__file__,
                  'actual_config_file':str(__import__('pathlib').Path(policy.__file__).with_name('policy_config.json')),
                  'actual_config_sha256':sha(__import__('pathlib').Path(policy.__file__).with_name('policy_config.json').read_bytes()),
                  'initial_sha256':hashvalue(inp['initial']),'first_local_prefix_mismatch':first_mismatch,'trace':trace},allow_nan=False))
'''


def prepare(prefix=24):
    old=FORMAL/'results/cloud_phase_gpu_alpha_20261003'
    new=FORMAL/'results/cloud_verified_portfolio_alpha_20261003'
    a=[json.loads(s) for s in (old/'actions.jsonl').read_text().splitlines()]
    b=[json.loads(s) for s in (new/'actions.jsonl').read_text().splitlines()]
    assert next(i for i,(x,y) in enumerate(zip(a,b)) if x!=y)==prefix
    actions=a[:prefix]
    assert all(x['action']=='observe' for x in actions)
    aa=list(csv.DictReader((old/'decisions.csv').open()))[:prefix]
    bb=list(csv.DictReader((new/'decisions.csv').open()))[:prefix]
    assert aa==bb
    oa=[r for r in csv.DictReader((old/'observations.csv').open()) if int(r['observe_index'])<prefix]
    ob=[r for r in csv.DictReader((new/'observations.csv').open()) if int(r['observe_index'])<prefix]
    assert oa==ob
    cutoff=aa[-1]['end_utc']
    ma=[json.loads(s) for s in (old/'messages.jsonl').read_text().splitlines()]
    mb=[json.loads(s) for s in (new/'messages.jsonl').read_text().splitlines()]
    ma=[r for r in ma if r.get('issued_at_utc','')<=cutoff]
    mb=[r for r in mb if r.get('issued_at_utc','')<=cutoff]
    assert ma==mb and not any(r['record_type'] not in ('bulletin','forecast') for r in ma)
    initial,public_hashes=public_card('alpha')
    snapshots=[];cursor=0
    for i in range(prefix+1):
        now=aa[i]['start_utc'] if i<prefix else cutoff
        issued=[r for r in ma if r['issued_at_utc']<=now]
        news=issued[cursor:];cursor=len(issued)
        last=None
        if i:
            hits=[{'target_id':r['target_id'],'score':float(r['score'])} for r in oa if int(r['observe_index'])==i-1]
            last={'action':'observe','observe_index':i-1,'assigned_count':len(actions[i-1]['assignments']),'hit_count':len(hits),'hits':hits}
        snapshots.append({'now_utc':now,'survey_end_utc':initial['survey']['end_utc'],'observe_action_index':i,
                          'latest_bulletin':next((r for r in reversed(issued) if r['record_type']=='bulletin'),None),
                          'latest_forecast':next((r for r in reversed(issued) if r['record_type']=='forecast'),None),
                          'active_requests':[],'new_messages':news,'last_result':last,'wallclock':{'remaining_seconds':900,'elapsed_seconds':0}})
    return {'initial':initial,'prefix_actions':actions,'snapshots':snapshots,'next_old_action':a[prefix],'next_new_action':b[prefix]}, {'public_input_hashes':public_hashes,
             'first_old_new_action_difference':prefix,'same_prefix_observations':len(oa),'same_prefix_decisions':len(aa),
             'same_prefix_messages':len(ma),'observation_row_order_identical':True,
             'official_hits_scores_rounded_6':True,'snapshot_reconstruction_scope':'all-observe first24; no activeREQ/report/resync/expandedwait; running_total unused by Policy omitted; wallclock controlled'}


def main():
    dest=FORMAL/'results/phase_prefix_hashseed_audit_20261003';dest.mkdir(exist_ok=True)
    inp,evidence=prepare()
    results=[]
    with tempfile.TemporaryDirectory(prefix='gosim-phase-prefix-audit-') as tmp:
        root=Path(tmp)
        with zipfile.ZipFile('/Users/kamico/Downloads/observer_phase_gpu.zip') as z:
            for n in z.namelist():
                if n=='remote_runtime.json':continue
                p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(n))
        (root/'remote_runtime.json').write_text('{"enabled":false,"enable_search":false}\n')
        (root/'input.json').write_text(json.dumps(inp))
        for seed in ['0','1','2','17']:
            env={**os.environ,'PYTHONHASHSEED':seed,'PYTHONPATH':str(root),'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
            proc=subprocess.run([sys.executable,'-u','-c',CHILD,str(root/'input.json')],cwd=root,env=env,capture_output=True,check=True,timeout=90)
            output=json.loads(proc.stdout)
            results.append(output)
            (dest/f'hashseed_{seed}.json').write_text(json.dumps(output,indent=2)+'\n')
            print(json.dumps({'seed':seed,'first_local_prefix_mismatch':output['first_local_prefix_mismatch'],'next_action':output['trace'][-1]['generated_action'],'next_env_sha':output['trace'][-1]['env_sha256'],'next_state_sha':output['trace'][-1]['state_sha256'],'exact_count':output['trace'][-1]['exact_count']}),flush=True)
    evidence.update({'schema':'owned-phase-prefix-hashseed-audit-v1','seeds':[r['python_hash_seed'] for r in results],
                     'same_state_hashes_across_seeds':all([t['state_sha256'] for t in r['trace']]==[t['state_sha256'] for t in results[0]['trace']] for r in results),
                     'same_env_hashes_across_seeds':all([t['env_sha256'] for t in r['trace']]==[t['env_sha256'] for t in results[0]['trace']] for r in results),
                     'same_actions_across_seeds':all([t['generated_action'] for t in r['trace']]==[t['generated_action'] for t in results[0]['trace']] for r in results),
                     'same_exact_candidate_hashes_across_seeds':all([t['exact_candidates_sha256'] for t in r['trace']]==[t['exact_candidates_sha256'] for t in results[0]['trace']] for r in results),
                     'same_coarse_hashes_across_seeds':all([t['coarse_sha256'] for t in r['trace']]==[t['coarse_sha256'] for t in results[0]['trace']] for r in results),
                     'new_online_evaluation':False,'production_or_package_changes':False})
    (dest/'audit.json').write_text(json.dumps(evidence,indent=2)+'\n')
    (dest/'reconstructed_public_input.json').write_text(json.dumps(inp,indent=2)+'\n')


if __name__=='__main__':main()
