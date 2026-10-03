#!/usr/bin/env python3
"""Public-prefix full-field competition beam and genuine replanning branches.

The participant observes only public snapshots. Truth is isolated in the
unmodified upstream evaluator. The finite beam is a public frozen-belief
surrogate, while teacher labels are genuine official terminal scores.
"""
from __future__ import annotations
import argparse, copy, csv, hashlib, json, math, os
from pathlib import Path
import sys, time
sys.dont_write_bytecode=True
from datetime import timedelta
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
os.environ.setdefault('PYTHONDONTWRITEBYTECODE','1')
BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'results/horizon_contention_20261004'
FROZEN=BASE/'runs/geometry_native_20261003/release'
UP=BASE/'upstream/gosim-observer-examples'
sys.path.insert(0,str(FROZEN));sys.path.insert(1,str(UP))
import numpy as np
import policy
from research.candidate_geometry_sweep import CandidateGeometryPlanner
from research.spatial_candidates import SpatialPlanner, PROGRAMS, parse_utc, local_sidereal
from runner.challenge.v4_runner import run_scenario,load_scenario,normalize_action
from runner.challenge.v4_workflow import V4Workflow
from runner.challenge.v4_fiber_map import FiberGrid,min_altitude_during
policy.SpatialPlanner=CandidateGeometryPlanner
TRACE={'L1':BASE/'results/geometry_native_20261003/protocol_gate_remaining/L1',
       'L2':BASE/'results/geometry_native_20261003/protocol_gate_retry/L2'}

def dump(name, obj):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def terminal(p,scores,factors):
    done=factors>=p.uniform_threshold
    n=np.bincount(p.ra_bands,weights=done,minlength=len(p.band_sizes))
    r=np.divide(n,p.band_sizes,out=np.zeros_like(n),where=p.band_sizes>0)
    v=float(r@r); j=float(r.sum()**2/(p.nonempty_bands*v)) if v else 0.
    return float(scores.sum()-p.req_penalty*np.count_nonzero(p.required&(factors<p.req_threshold))-p.uniform_weight*(1-j))

def action_tuple(p,a,frame,env):
    ix=np.array([p.index[x] for x in a['assignments'].values()],int)
    fs=np.array([int(x) for x in a['assignments']],int)
    center=(a['pointing']['alt_deg']+env.get('pointing_offset_alt_deg',0),
            (a['pointing']['az_deg']+env.get('pointing_offset_az_deg',0))%360)
    return (0.,center,a['duration_seconds'],PROGRAMS.index(a['program']),ix,fs)

def action_from(p,c,env):
    _,center,d,prog,ix,fs=c
    return dict(action='observe',pointing=dict(alt_deg=round(center[0]-env.get('pointing_offset_alt_deg',0),7),
        az_deg=round((center[1]-env.get('pointing_offset_az_deg',0))%360,7)),
        assignments={str(int(f)):p.ids[int(i)] for i,f in zip(ix,fs)},duration_seconds=int(d),program=PROGRAMS[int(prog)])

def apply(p,c,frame,scores,factors):
    _,_,d,prog,ix,_=c
    s=scores.copy();f=factors.copy()
    raw=np.minimum(1,d*frame[2][ix]);lower=raw/frame[13]
    np.maximum.at(s,ix,p.weight[ix]*raw*frame[5][prog,ix])
    np.maximum.at(f,ix,lower)
    return s,f

def candidate_set(p,snapshot,scores,factors,env,keep=3):
    found=[];original=SpatialPlanner._evaluate
    def capture(self,center,pool,*frame):
        c=original(self,center,pool,*frame)
        if self is p and c is not None:found.append(c)
        return c
    SpatialPlanner._evaluate=capture
    try:a=getattr(p,'horizon_real_choose',p.choose)(snapshot,scores,factors,env,[])
    finally:SpatialPlanner._evaluate=original
    frame=p.frame
    if a is None or frame is None:return [],frame
    actual=action_tuple(p,a,frame,env);found.insert(0,actual)
    # Retain native winner first; diversify other complete fields by assignment.
    candidates=[actual];seen={tuple(zip(actual[4],actual[5]))+(actual[2],actual[3])}
    for c in sorted(found,key=lambda c:-c[0]):
        key=tuple(zip(c[4],c[5]))+(c[2],c[3])
        if key in seen:continue
        seen.add(key);candidates.append(c)
        if len(candidates)>=keep:break
    return candidates,frame

def fixed_fields(p,snapshot,scores,factors,env,duration,keep=3):
    generated,frame=candidate_set(p,snapshot,scores,factors,env,keep=12)
    if frame is None:return [],frame
    allidx=np.arange(p.n);options=[];seen=set()
    raw=np.minimum(1.,duration*frame[2]);robust=raw/frame[13]
    terminal=(p.required&(factors<p.req_threshold)&(robust>=p.req_threshold))*p.req_penalty
    terminal+=(factors<p.uniform_threshold)*(robust>=p.uniform_threshold)*frame[10]
    for proposal in generated:
        center=proposal[1];fiber,ok,_=p._classify(frame[0],*center)
        ok &= frame[1]>=duration
        for program in range(3):
            gain=np.maximum(0.,p.weight*raw*frame[5][program]-scores)
            value=gain+terminal
            ix=[];fs=[]
            for f in range(p.nfib):
                cell=np.flatnonzero(ok&(fiber==f)&(value>0))
                if len(cell):
                    i=int(cell[np.argmax(value[cell])]);ix.append(i);fs.append(f)
            if not ix:continue
            c=(float(value[ix].sum()/duration),center,duration,program,np.array(ix,int),np.array(fs,int))
            key=tuple(zip(ix,fs))+(program,)
            if key in seen:continue
            seen.add(key);options.append(c)
    return sorted(options,key=lambda c:-c[0])[:keep],frame

def clone_planner(p):
    q=copy.deepcopy(p)
    q.choose=CandidateGeometryPlanner.choose.__get__(q,type(q))
    q.horizon_real_choose=q.choose
    return q

def beam(p,snapshot,scores,factors,env,first,frame,depth=3,width=3,keep=3):
    """Equal 1800-second horizon; regenerate and reassign every full field.

    Future arcs are 600 seconds on a shared time DAG. This finite horizon is
    a public surrogate, not a target reservation or a fixed suffix teacher.
    """
    s,f=apply(p,first,frame,scores,factors)
    end=parse_utc(snapshot['now_utc'])+timedelta(seconds=first[2])
    nodes=[(terminal(p,s,f),end,s,f,[action_from(p,first,env)])]
    start=time.perf_counter();calls=0;cell_options=0
    for _ in range(depth):
        expanded=[]
        for _,now,ss,ff,path in nodes:
            night=next((b for a,b in p.nights if a<=now<b),None)
            duration=min(600,int((night-now).total_seconds())) if night else 0
            if duration<p.tmin:
                expanded.append((terminal(p,ss,ff),now,ss,ff,path));continue
            snap=dict(now_utc=now.strftime('%Y-%m-%dT%H:%M:%SZ'),observe_action_index=snapshot['observe_action_index']+sum(a['action']=='observe' for a in path),
                new_messages=[],latest_bulletin=snapshot.get('latest_bulletin'),active_requests=[])
            branch_planner=clone_planner(p)
            assert branch_planner is not p and branch_planner.terrain_directions is not p.terrain_directions
            cand,fr=fixed_fields(branch_planner,snap,ss,ff,env,duration,keep);calls+=1
            if not cand:
                expanded.append((terminal(p,ss,ff),now+timedelta(seconds=duration),ss,ff,path+[dict(action='wait',duration_seconds=duration)]));continue
            for c in cand:
                s2,f2=apply(p,c,fr,ss,ff)
                expanded.append((terminal(p,s2,f2),now+timedelta(seconds=duration),s2,f2,path+[action_from(p,c,env)]))
                cell_options+=len(c[4])
        nodes=sorted(expanded,key=lambda x:-x[0])[:width]
    best=nodes[0]
    return dict(value=best[0],end=best[1].strftime('%Y-%m-%dT%H:%M:%SZ'),path=best[4],
        seconds=time.perf_counter()-start,choose_calls=calls,assignment_options=cell_options)

def validate(scenario,a,now,env):
    targets={t['target_id']:t for t in scenario.targets};normalize_action(a,scenario,targets,now)
    grid=FiberGrid.from_config(scenario.fiber_config)
    for f,tid in a['assignments'].items():
        t=targets[tid];r=grid.classify_target(t['ra_deg'],t['dec_deg'],now,
            a['pointing']['alt_deg'],a['pointing']['az_deg'],scenario.site['latitude_deg'],scenario.site['longitude_deg'],
            env.get('pointing_offset_alt_deg',0),env.get('pointing_offset_az_deg',0))
        assert r.region=='glass' and r.fiber_id==int(f),(f,tid,r)
        assert min_altitude_during(t['ra_deg'],t['dec_deg'],now,now+timedelta(seconds=a['duration_seconds']),scenario.config)>=scenario.minimum_altitude_deg

def scan(card,maxstates=8,maxpairs=3):
    start=time.monotonic();scenario=load_scenario(UP/'local-cards'/card/'config/v4_scenario.json')
    trace=TRACE[card];actions=[json.loads(l) for l in (trace/'actions.jsonl').read_text().splitlines()]
    decs=[r for r in csv.DictReader((trace/'decisions.csv').open()) if r['action']=='observe']
    lastnight=scenario.night_calendar[-1]['observing_start_utc'] if hasattr(scenario,'night_calendar') else None
    initial=V4Workflow(UP/'local-cards'/card).initialize_payload(900)
    p=policy.Policy(initial);assert p.remote is None
    lastnight=initial['survey']['nights'][-1]['observing_start_utc']
    rows=[d for d in decs if d['start_utc']>=lastnight]
    ranks=set(int(rows[j]['observe_index']) for j in np.unique(np.rint(np.linspace(0,len(rows)-1,maxstates)).astype(int)))
    original=p.planner.choose;p.planner.horizon_real_choose=original;seq=0;records=[];prefix=hashlib.sha256();picks=[]
    def forced(snapshot,scores,factors,env,requests):
        nonlocal picks
        a=actions[seq]
        assert a['action']=='observe',(seq,a)
        pl=p.planner;now=parse_utc(snapshot['now_utc']);rank=snapshot['observe_action_index']
        alt,az,_,vectors=pl._altaz(local_sidereal(now,pl.lon))
        if rank in ranks:
            # Same public state, fixed first pointing/duration/program, every
            # target fitting that cell is considered; no future truth read.
            assert not requests and not snapshot.get('active_requests'), 'Final-night surrogate excludes active REQ'
            probe_planner=clone_planner(pl)
            _,frame=candidate_set(probe_planner,snapshot,scores,factors,env)
            center=(a['pointing']['alt_deg']+env.get('pointing_offset_alt_deg',0),(a['pointing']['az_deg']+env.get('pointing_offset_az_deg',0))%360)
            fiber,ok,margin=pl._classify(vectors,*center)
            duration=a['duration_seconds'];prog=PROGRAMS.index(a['program'])
            raw=np.minimum(1.,duration*frame[2]);lower=raw/frame[13]
            gain=np.maximum(0,pl.weight*raw*frame[5][prog]-scores)
            req=(pl.required&(factors<pl.req_threshold)&(lower>=pl.req_threshold))*pl.req_penalty
            value=gain+req
            base=action_tuple(pl,a,frame,env);pairs=[]
            assigned=set(a['assignments'].values())
            for f,tid in a['assignments'].items():
                old=pl.index[tid]
                ids=np.flatnonzero(ok&(fiber==int(f))&(frame[1]>=duration)&(value>0))
                for i in ids:
                    if i==old or pl.ids[i] in assigned:continue
                    delta=float(value[i]-value[old])
                    if -.20<=delta<=.01:
                        pairs.append((delta,int(f),old,int(i)))
            pairs=sorted(pairs,key=lambda x:(-x[0],x[1],x[3]))[:maxpairs]
            if pairs:
                bbeam=beam(probe_planner,snapshot,scores,factors,env,base,frame)
                for delta,f,old,new in pairs:
                    c=list(base);c[4]=base[4].copy();c[4][np.flatnonzero(base[5]==f)[0]]=new;c=tuple(c)
                    other=action_from(pl,c,env);validate(scenario,other,now,env)
                    tbeam=beam(probe_planner,snapshot,scores,factors,env,c,frame)
                    row=dict(card=card,rank=rank,sequence=seq,now_utc=snapshot['now_utc'],fiber=f,
                        old=pl.ids[old],new=pl.ids[new],instant_delta=delta,beam_delta=tbeam['value']-bbeam['value'],
                        baseline=a,alternative=other,base_beam=bbeam,alternative_beam=tbeam,prefix_sha256=prefix.hexdigest(),
                        future_nights_old=int(pl.future_nights[-1,old]),future_nights_new=int(pl.future_nights[-1,new]),active_request_count=len(snapshot.get('active_requests',[])),
                        public_pointing_offset=[float(env.get('pointing_offset_alt_deg',0)),float(env.get('pointing_offset_az_deg',0))])
                    records.append(row)
                    print(json.dumps({k:row[k] for k in ('card','rank','fiber','old','new','instant_delta','beam_delta')}),flush=True)
        # Return the owned action and reconstruct public feedback metadata.
        pl.last_prediction={tid:{'alt_deg':float(alt[pl.index[tid]]),'az_deg':float(az[pl.index[tid]])} for tid in a['assignments'].values()}
        pl.stats={}
        return copy.deepcopy(a)
    p.planner.choose=forced
    def decide(snapshot):
        nonlocal seq
        a=p.decide(snapshot)
        assert a==actions[seq],(seq,snapshot['now_utc'],a,actions[seq])
        prefix.update((json.dumps(a,sort_keys=True,separators=(',',':'))+'\n').encode());seq+=1
        return a
    report=run_scenario(UP/'local-cards'/card/'config/v4_scenario.json',lambda _:decide,OUT/f'micro_replay_{card}')
    expected=json.loads((trace/'score_report.json').read_text())
    assert report['total']==expected['total'],(report['total'],expected['total'])
    assert not expected['invalidations'] and not scenario.stress_enabled
    assert all(r['deadline_utc']<lastnight for r in expected['observation_requests'])
    result=dict(card=card,source_total=expected['total'],replay_total=report['total'],same_tape=True,
        seconds=time.monotonic()-start,sample_ranks=sorted(ranks),pairs=records,
        source_hash={n:sha(trace/n) for n in ('actions.jsonl','decisions.csv','observations.csv','messages.jsonl','score_report.json')},
        scope_gates=dict(stress_enabled=False,source_invalidations=0,all_known_request_deadlines_before_final_night=True,
            active_request_counts=[r['active_request_count'] for r in records],planner_mutations='deep copy per public research frame and per beam node',
            future_loss='omitted in surrogate; supplied L1/L2 teacher scenarios stress disabled and full replay no invalidations'),
        beam_model='public frozen C/E prior; full-field regeneration/assignment; 3x600-second equal horizon,width3,keep3; required and Jain exact at each modeled leaf; no active final-night requests',
        scope='finite public surrogate plus official full tape replay; beam values are not actual continuation labels')
    dump(f'micro_{card}.json',result)
    print(json.dumps(dict(event='scan_done',card=card,seconds=result['seconds'],pairs=len(records),replay_total=report['total'])),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--card',choices=['L1','L2'],default='L1');ap.add_argument('--maxstates',type=int,default=8);ap.add_argument('--maxpairs',type=int,default=3)
    a=ap.parse_args();scan(a.card,a.maxstates,a.maxpairs)
