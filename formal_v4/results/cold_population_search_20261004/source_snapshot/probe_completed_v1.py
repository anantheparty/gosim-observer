#!/usr/bin/env python3
"""Fixed strong fields, joint fiber-target matching; public inputs only.

The nominal weather below is a declared conditional world, never card truth.
The unmodified official geometry and scorer judge all edges and terminal values.
"""
from __future__ import annotations
import csv, hashlib, json, math, os, random, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.dont_write_bytecode = True
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[key] = '1'
OUT = Path(__file__).resolve().parent
BASE = OUT.parents[1]
UP = BASE / 'upstream/gosim-observer-examples'
FROZEN = BASE / 'runs/geometry_native_20261003/release'
sys.path.insert(0, str(FROZEN))
sys.path.insert(1, str(UP))
import numpy as np
import policy
from research.candidate_geometry_sweep import CandidateGeometryPlanner
from runner.challenge.v4_fiber_map import FiberGrid, altaz_to_radec, min_altitude_during, radec_to_altaz, validate_action
from runner.challenge.v4_scorer import BestLedger, SlotTruth, WeatherTruth, lunar_quality_factor, program_band, program_multiplier, required_penalty, score_target_exposure, uniformity_penalty
policy.SpatialPlanner = CandidateGeometryPlanner

def utc(value): return datetime.fromisoformat(value.replace('Z', '+00:00'))
def fmt(value): return value.strftime('%Y-%m-%dT%H:%M:%SZ')
def readcsv(path): return list(csv.DictReader(path.open()))
def dump(path, obj): path.write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n')
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def public(card):
    root = UP / 'local-cards' / card
    cfg = json.loads((root/'config/v4_scenario.json').read_text())
    fiber = json.loads((root/'config/v4_fiber_config.json').read_text())
    scoring = json.loads((root/'config/v4_score_config.json').read_text())
    targets = []
    for t in readcsv(root/'public/targets.csv'):
        targets.append(dict(target_id=t['target_id'], ra_deg=float(t['ra_deg']), dec_deg=float(t['dec_deg']),
                            target_class=t['target_class'], feature_flux=float(t['feature_flux']),
                            science_weight=float(t['science_weight']), required=t['required']=='true'))
    nights = readcsv(root/'public/v4_night_calendar.csv')
    grid = FiberGrid.from_config(fiber)
    footprints = {}
    for row in readcsv(root/'public/footprint.csv'):
        footprints.setdefault(row['component_id'], []).append([float(row['ra_deg']), float(row['dec_deg'])])
    site = dict(cfg['site']); site['minimum_altitude_deg'] = cfg['minimum_altitude_deg']
    init = dict(schema_version='v4-initialize-v1', task_card={'card_id':card}, site=site,
                survey=dict(start_utc=nights[0]['observing_start_utc'], end_utc=nights[-1]['observing_end_utc'], slot_seconds=900,
                            nights=[dict(night_id=n['night_id'], night_date=n['night_date'], observing_start_utc=n['observing_start_utc'],
                                         observing_end_utc=n['observing_end_utc'], slot_count=int(n['slot_count'])) for n in nights]),
                instrument=dict(n_fibers=grid.n_fibers, grid_side=grid.n_side, fiber_area_deg2=grid.fiber_area_deg2,
                                gap_deg=grid.gap_deg, glass_side_deg=round(grid.fiber_side_deg,6), pitch_deg=round(grid.pitch_deg,6),
                                fov_side_deg=round(grid.fov_side_deg,6), exposure=fiber['exposure']),
                scoring=scoring, targets=dict(columns=list(targets[0]), rows=[list(t.values()) for t in targets]),
                footprint=[dict(component_id=k, vertices=v) for k,v in footprints.items()], limits={'global_wallclock_seconds':900})
    return root, cfg, fiber, scoring, targets, nights, grid, init

def hungarian(edges, n_targets):
    """Maximum-weight partial bipartite matching, with row-specific zero dummies."""
    nr = len(edges); nc = n_targets + nr
    if nr == 0: return [], 0.
    cost = np.full((nr, nc), 1e9)
    for row, es in enumerate(edges):
        for target, weight in es.items(): cost[row,target] = -weight
        cost[row,n_targets:] = 0.
    u=np.zeros(nr+1); v=np.zeros(nc+1); p=np.zeros(nc+1,dtype=int); way=np.zeros(nc+1,dtype=int)
    for i in range(1,nr+1):
        p[0]=i; j0=0; minv=np.full(nc+1, np.inf); used=np.zeros(nc+1,dtype=bool)
        while True:
            used[j0]=True; i0=p[j0]
            cur=cost[i0-1]-u[i0]-v[1:]
            available=~used[1:]
            better=available & (cur<minv[1:])
            minv[1:][better]=cur[better]; way[1:][better]=j0
            choice=np.where(available,minv[1:],np.inf); j1=int(np.argmin(choice))+1; delta=minv[j1]
            u[p[used]] += delta; v[used] -= delta; minv[~used] -= delta
            j0=j1
            if p[j0]==0: break
        while True:
            j1=way[j0]; p[j0]=p[j1]; j0=j1
            if j0==0: break
    match=[None]*nr
    for j in range(1,nc+1):
        if p[j] and j<=n_targets and (j-1) in edges[p[j]-1]: match[p[j]-1]=j-1
    return match, float(sum(edges[r][t] for r,t in enumerate(match) if t is not None))

def brutematch(edges):
    best=-math.inf
    def visit(r, used, value):
        nonlocal best
        if r==len(edges): best=max(best,value); return
        visit(r+1,used,value)
        for target, w in edges[r].items():
            if target not in used: visit(r+1,used|{target},value+w)
    visit(0,set(),0.)
    return best

def sanity():
    rng=random.Random(1019); maxerr=0.
    for _ in range(100):
        nr=rng.randint(1,5); nt=rng.randint(1,6)
        es=[{t:rng.uniform(-2,6) for t in range(nt) if rng.random()<.6} for _ in range(nr)]
        _,value=hungarian(es,nt); maxerr=max(maxerr,abs(value-brutematch(es)))
    # Science-best and completion witnesses separate: capacity-1 flow misses .026.
    sc={'required':{'observed_factor_threshold':.5,'penalty_per_missing':50}}
    target={'target_id':'A','required':True}
    led=BestLedger();led.record(0,'A',.49,.588);led.record(1,'A',.53,.562)
    both=sum(v[1] for v in led.best().values())-required_penalty([target],led.max_factors(),sc)[1]
    one=max(.588-50,.562)
    return dict(random_graphs=100, brute_force_max_error=maxerr,
                separated_witness=dict(both=both, best_single=one, loss=both-one,
                                       science_factor=.49,science_multiplier=1.2,completion_factor=.53,completion_multiplier=1.06))

def conditional_weather(night):
    a=utc(night['observing_start_utc']); b=utc(night['observing_end_utc']); slots=[]
    while a<b:
        end=min(b,a+timedelta(seconds=900))
        slots.append(SlotTruth('conditional',a,end,True,1.1,.88,1.,.95));a=end
    return WeatherTruth(slots,None)

def all_edges(action, start, model, cfg, grid, scoring, targets, vectors):
    end=start+timedelta(seconds=action['duration_seconds'])
    site=cfg['site']; lat=site['latitude_deg'];lon=site['longitude_deg']
    ra,dec=altaz_to_radec(action['pointing']['alt_deg'],action['pointing']['az_deg'],start,lat,lon)
    ar,dr=math.radians(ra),math.radians(dec)
    center=np.array([math.cos(dr)*math.cos(ar),math.cos(dr)*math.sin(ar),math.sin(dr)])
    radius=math.degrees(math.atan(math.sqrt(2)*math.radians(grid.fov_side_deg/2)))+.3
    # Row-wise dot avoids BLAS-specific warnings for small-width Apple kernels.
    ids=np.flatnonzero(np.sum(vectors*center,axis=1)>=math.cos(math.radians(radius)))
    rows={f:{} for f in range(grid.n_fibers)}; segments=list(model.segments(start,end))
    for i in ids:
        t=targets[int(i)]
        if min_altitude_during(t['ra_deg'],t['dec_deg'],start,end,cfg)<cfg['minimum_altitude_deg']:continue
        hit=grid.classify_target(t['ra_deg'],t['dec_deg'],start,action['pointing']['alt_deg'],action['pointing']['az_deg'],lat,lon)
        if hit.region!='glass':continue
        def aa(m,t=t):return radec_to_altaz(t['ra_deg'],t['dec_deg'],m,lat,lon)
        q=model.band_quality(start,end,scoring,lambda m:aa(m)[0],lambda m:lunar_quality_factor(t['ra_deg'],t['dec_deg'],m,site,scoring))
        mult=program_multiplier(action['program'],program_band(q,scoring),scoring)
        result=score_target_exposure(t,segments,[],model,action['duration_seconds'],mult,scoring,start,aa,site)
        rows[hit.fiber_id][int(i)]=(result.factor,result.score)
    return rows

def ledger_value(assignments, rows, targets, scoring):
    led=BestLedger()
    for r,t in enumerate(assignments):
        if t is not None:
            factor,score=rows[r][t]
            led.record(r,targets[t]['target_id'],factor,score)
    science=sum(v[1] for v in led.best().values())
    missing,required=required_penalty(targets,led.max_factors(),scoring)
    bands,uniform=uniformity_penalty(targets,led.max_factors(),scoring)
    return dict(total=science-required-uniform,science=science,required_penalty=required,required_missing=missing,
                uniformity_penalty=uniform,observed_targets=len(led.best()),completed_targets=sum(f>=.5 for f in led.max_factors().values()))

def sequential(rows, targets, scoring):
    s={}; f={}; out=[]; penalty=scoring['required']['penalty_per_missing']; threshold=scoring['required']['observed_factor_threshold']
    for es in rows:
        opts=[]
        for t,(factor,score) in es.items():
            gain=max(0.,score-s.get(t,0.))
            gain+=penalty*(targets[t]['required'] and f.get(t,0.)<threshold<=factor)
            opts.append((gain,-t,t))
        t=max(opts)[2] if opts and max(opts)[0]>0 else None;out.append(t)
        if t is not None:s[t]=max(s.get(t,0.),es[t][1]);f[t]=max(f.get(t,0.),es[t][0])
    return out

def refill(match, rows, targets, scoring):
    result=list(match);s={};f={}
    for r,t in enumerate(match):
        if t is not None:s[t]=max(s.get(t,0.),rows[r][t][1]);f[t]=max(f.get(t,0.),rows[r][t][0])
    for r,t in enumerate(result):
        if t is not None:continue
        opts=[]
        for i,(factor,score) in rows[r].items():
            val=max(0.,score-s.get(i,0.))+scoring['required']['penalty_per_missing']*(targets[i]['required'] and f.get(i,0.)<.5<=factor)
            opts.append((val,-i,i))
        if opts and max(opts)[0]>0:
            i=max(opts)[2];result[r]=i;s[i]=max(s.get(i,0.),rows[r][i][1]);f[i]=max(f.get(i,0.),rows[r][i][0])
    return result

def probe(card, offset):
    begun=time.perf_counter(); root,cfg,fiber,scoring,targets,nights,grid,init=public(card)
    actor=policy.Policy(init); assert actor.remote is None
    night=nights[0]; start=utc(night['observing_start_utc'])+timedelta(seconds=offset); end=start+timedelta(seconds=1800)
    weather=conditional_weather(night); now=start;rank=0;last=None;rows=[];base=[];blocks=[];idx={t['target_id']:i for i,t in enumerate(targets)}
    vectors=actor.planner.eq_vectors; public_bulletin={'record_type':'bulletin','issued_at_utc':fmt(start),'notices':[],'initial':True}
    actor_seconds=0.; edge_seconds=0.; reports=0; baseline_misses=[]
    while now<end:
        remaining=int((end-now).total_seconds())
        if remaining<60: break
        snap=dict(now_utc=fmt(now),survey_end_utc=init['survey']['end_utc'],observe_action_index=rank,running_total=0.,
                  latest_bulletin=public_bulletin,latest_forecast=None,active_requests=[],new_messages=[public_bulletin] if rank==0 else [],last_result=last,
                  wallclock={'remaining_seconds':900.})
        begun_call=time.perf_counter();action=actor.decide(snap);actor_seconds+=time.perf_counter()-begun_call
        if action['action']=='report':
            reports+=1; last=dict(action='report',correct=False,repaired=False,score_delta=0.)
            assert reports<=2;continue
        if action['action']!='observe':
            raise RuntimeError('unexpected synthetic nominal action '+str(action))
        action=dict(action);action['duration_seconds']=min(action['duration_seconds'],remaining)
        actor.pending['action']=action
        validate_action({k:v for k,v in action.items() if k!='program'},fiber)
        begun_edges=time.perf_counter();es=all_edges(action,now,weather,cfg,grid,scoring,targets,vectors);edge_seconds+=time.perf_counter()-begun_edges
        hits=[];orig=[]
        for f in range(grid.n_fibers):
            tid=action['assignments'].get(str(f)); i=idx[tid] if tid else None
            if i is not None and i not in es[f]:
                t=targets[i];h=grid.classify_target(t['ra_deg'],t['dec_deg'],now,action['pointing']['alt_deg'],action['pointing']['az_deg'],cfg['site']['latitude_deg'],cfg['site']['longitude_deg'])
                baseline_misses.append(dict(rank=rank,fiber=f,target_id=tid,region=h.region,actual_fiber=h.fiber_id,
                    minimum_altitude=min_altitude_during(t['ra_deg'],t['dec_deg'],now,now+timedelta(seconds=action['duration_seconds']),cfg)))
                i=None
            rows.append(es[f]);base.append(i);orig.append(tid)
            if i is not None:hits.append(dict(target_id=tid,score=round(es[f][i][1],6)))
        blocks.append(dict(start_utc=fmt(now),observe_rank=rank,action=action))
        last=dict(action='observe',observe_index=rank,assigned_count=len(action['assignments']),hit_count=len(hits),hits=hits)
        now+=timedelta(seconds=action['duration_seconds']);rank+=1
        if rank>64:raise RuntimeError('horizon safety bound')
    compact=sorted({t for row in rows for t in row}); reverse={t:i for i,t in enumerate(compact)}
    weighted=[{reverse[t]:score+50*(targets[t]['required'] and factor>=.5) for t,(factor,score) in row.items()} for row in rows]
    flowbeg=time.perf_counter();compactmatch,core=hungarian(weighted,len(compact));flow_seconds=time.perf_counter()-flowbeg
    matched=[compact[t] if t is not None else None for t in compactmatch];joint=refill(matched,rows,targets,scoring)
    greedy=sequential(rows,targets,scoring)
    vals={name:ledger_value(a,rows,targets,scoring) for name,a in [('strong_fixed',base),('sequential',greedy),('flow_once',matched),('flow_refill',joint)]}
    selected=max(vals,key=lambda n:(vals[n]['total'], n=='strong_fixed'))
    split=[]
    for t in compact:
        if not targets[t]['required']:continue
        qual=[s for row in rows for i,(f,s) in row.items() if i==t and f>=.5]
        nonqual=[s for row in rows for i,(f,s) in row.items() if i==t and f<.5]
        if qual and nonqual and max(nonqual)>min(qual)+1e-12: split.append(targets[t]['target_id'])
    result=dict(card=card,offset_seconds=offset,start_utc=fmt(start),end_utc=fmt(now),scope='declared conditional nominal world; fixed strong-native physical skeleton',
                actions=len(blocks),resources=len(rows),edges=sum(map(len,rows)),targets=len(compact),reports=reports,baseline_misses=baseline_misses,
                values=vals,selected=selected,delta_vs_strong=vals[selected]['total']-vals['strong_fixed']['total'],
                flow_core_weight=core,witness_alignment_failure_targets=split,
                changed_assignments=sum(a!=b for a,b in zip(base,joint)),first_action_changes=sum(a!=b for a,b in zip(base[:16],joint[:16])),
                actor_seconds=actor_seconds,edge_seconds=edge_seconds,flow_seconds=flow_seconds,total_seconds=time.perf_counter()-begun,
                blocks=blocks,assignments={name:[targets[t]['target_id'] if t is not None else None for t in a] for name,a in [('strong_fixed',base),('sequential',greedy),('flow_once',matched),('flow_refill',joint)]})
    dump(OUT/f'{card}_{offset:05d}.json',result)
    return {k:v for k,v in result.items() if k not in ('blocks','assignments')}

def main():
    OUT.mkdir(exist_ok=True);san=sanity();assert san['brute_force_max_error']<1e-9
    dump(OUT/'sanity.json',san); results=[]
    for card in ('L1','L2'):
        for offset in (0,7200,14400,21600):
            res=probe(card,offset);results.append(res)
            print(json.dumps({k:res[k] for k in ('card','offset_seconds','actions','edges','selected','delta_vs_strong','first_action_changes','flow_seconds','total_seconds')}),flush=True)
    source_files=[p for p in FROZEN.rglob('*') if p.is_file() and '__pycache__' not in str(p)]
    source_files += [UP/'runner/challenge/v4_fiber_map.py',UP/'runner/challenge/v4_scorer.py',Path(__file__)]
    manifest=dict(schema='cold-multiexposure-matching-v1',sanity=san,results=results, source_sha256={str(p.relative_to(BASE)):digest(p) for p in source_files},
                  hidden_truth_reads=0,actual_season_runs=0,gpu_jobs=0,ssh_jobs=0,sealed_L4_reads=0,
                  nominal_weather=dict(seeing_arcsec=1.1,transparency=.88,sky_quality=1.,instrument_efficiency=.95),
                  scope='mechanism only; no actual hidden future outcome or strong full-season superiority claimed')
    dump(OUT/'MANIFEST.json',manifest)
if __name__=='__main__':main()
