"""Finite common-exposure coverage control. Public input only; no runner import.

One binary column is an entire physically executable exposure. Continuous winner
variables choose at most one contribution per target; with integral exposure
variables their optimum is exactly best-only science. Interval capacity couples
all columns. No target reserves its own best start or its own fibre time.
"""
from __future__ import annotations
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import copy, csv, hashlib, json, math, sys, time, zipfile
from pathlib import Path
from datetime import timedelta
from dataclasses import dataclass
import numpy as np

OUT=Path(__file__).resolve().parent
BASE=OUT.parents[1]
sys.path.insert(0,str(OUT/'deps'))
from scipy.optimize import milp, Bounds, LinearConstraint, linear_sum_assignment
from scipy.sparse import coo_matrix
CONTROL=OUT/'control_package'
ZIP=Path('/Users/kamico/Downloads/observer_request_exact_cache.zip')
if not CONTROL.exists():
    with zipfile.ZipFile(ZIP) as z:z.extractall(CONTROL)
sys.path.insert(0,str(CONTROL))
from research import agent_request_exact_cache as entry
from research.spatial_candidates import PROGRAMS, parse_utc, local_sidereal, DEG
from research.feedback_model import seasonal_quality
from research.request_future_field import PublishedFutureField
from research.terrain_policy import temporary_weather_scale
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner


def dump(path,obj):Path(path).write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def initial(card):
    root=BASE/'upstream/gosim-observer-examples/local-cards'/card
    fiber=json.loads((root/'config/v4_fiber_config.json').read_text())
    score=json.loads((root/'config/v4_score_config.json').read_text())
    with (root/'public/targets.csv').open() as f:
        r=csv.DictReader(f);columns=r.fieldnames;rows=list(r)
    with (root/'public/v4_night_calendar.csv').open() as f:nights=list(csv.DictReader(f))
    return dict(site={**fiber['site'],'minimum_altitude_deg':30.},scoring=score,
        instrument={**fiber['field'],'grid_side':math.isqrt(fiber['field']['n_fibers']),
            'glass_side_deg':math.sqrt(fiber['field']['fiber_area_deg2']),
            'pitch_deg':math.sqrt(fiber['field']['fiber_area_deg2'])+fiber['field']['gap_deg'],
            'fov_side_deg':math.isqrt(fiber['field']['n_fibers'])*(math.sqrt(fiber['field']['fiber_area_deg2'])+fiber['field']['gap_deg']),
            'exposure':fiber['exposure']},
        targets=dict(columns=columns,rows=[[r[k] for k in columns] for r in rows]),
        survey=dict(start_utc=nights[0]['observing_start_utc'],end_utc=nights[-1]['observing_end_utc'],
                    slot_seconds=900,nights=nights),limits=dict(global_wallclock_seconds=900))

def public_prefix(card,night_index):
    """Reconstruct legal history using target_id/score only from old hit table.

    The CSV contains private diagnostic columns. They are discarded at ingress
    and never supplied to Policy or the operator. This is a reconstructed public
    state, not a claim that old wallclock/budget decisions are reproduced.
    """
    init=initial(card);p=entry.ExactCachedRequestPolicy(init)
    trace=BASE/'results/request_geometry_integration_20261004/seasons/control'/card
    decs=list(csv.DictReader((trace/'decisions.csv').open()))
    events=[json.loads(l) for l in (trace/'messages.jsonl').read_text().splitlines()]
    hits={}
    with (trace/'observations.csv').open() as f:
        for r in csv.DictReader(f):
            public=dict(target_id=r['target_id'],score=float(r['score']))
            hits.setdefault(int(r['observe_index']),[]).append(public)
    start,end=p.planner.nights[night_index]
    selected=next(k for k,r in enumerate(decs) if r['action']=='observe'
        and parse_utc(r['start_utc'])>=start+timedelta(seconds=3600)
        and parse_utc(r['start_utc'])<=end-timedelta(seconds=14400))
    cursor=0;last=None;latest_b=None;latest_f=None;issued={};prefix=hashlib.sha256()
    for k,r in enumerate(decs[:selected+1]):
        now=parse_utc(r['start_utc']);messages=[]
        while cursor<len(events) and parse_utc(events[cursor]['issued_at_utc'])<=now:
            m=events[cursor];messages.append(m);cursor+=1
            if m['record_type']=='bulletin':latest_b=m
            if m['record_type']=='forecast':latest_f=m
            if m['record_type']=='observation_request':issued[m['request_id']]=m
        active=[m for m in issued.values() if parse_utc(m['deadline_utc'])>now]
        snapshot=dict(now_utc=r['start_utc'],survey_end_utc=init['survey']['end_utc'],
            observe_action_index=sum(d['action']=='observe' for d in decs[:k]),
            running_total=float(p.scores.sum()),new_messages=messages,
            latest_bulletin=latest_b,latest_forecast=latest_f,last_result=last,
            active_requests=active,wallclock=dict(remaining_seconds=900))
        p._ingest_result(snapshot);p._messages(snapshot)
        n=p._night(now);seasonal=seasonal_quality(now.timetuple().tm_yday,p.planner.q0)[0]
        C,E=p.belief_clock.prior(p.C,p.E,now,seasonal);p.last_night=n
        if k==selected:
            assert not active,'predeclared no-active-REQ gate failed'
            assert not any(m.get('event_kind') in ('rain','storm') and m.get('direction')=='ALL' for m in p.notices)
            env=dict(p.config,quality_scale=C*E*p.planner.q0,program_band_quality_scale=C*p.planner.q0,
                     target_quality_scale=p._target_scale(now),use_bulletin_directional_prior=False)
            if p.calibrator:
                env['pointing_offset_alt_deg'],env['pointing_offset_az_deg']=p.calibrator.estimate[:2]
            return p,snapshot,env,dict(card=card,night_index=night_index,decision_row=selected,
                prefix_sha256=prefix.hexdigest(),public_score_sum=float(p.scores.sum()),C=C,E=E,
                original_decision={k:r[k] for k in ('observe_index','start_utc','duration_seconds','alt_deg','az_deg','program')},
                historical_action_parity_claimed=False,history_feedback_columns=['target_id','score'],
                diagnostic_columns_not_used=['factor','quality','prog_mult','fiber_id','valid','invalidated_by'])
        if r['action']=='observe':
            # Original geometry/assignments are public actions. Recover them from
            # actions.jsonl by observe order, independent of runner wait expansion.
            if 'original_observe' not in locals():
                original_observe=[json.loads(l) for l in (trace/'actions.jsonl').read_text().splitlines()
                                  if json.loads(l)['action']=='observe']
            idx=int(r['observe_index']);a=copy.deepcopy(original_observe[idx])
            pl=p.planner;alt,az,_,_=pl._altaz(local_sidereal(now,pl.lon))
            prediction={tid:dict(alt_deg=float(alt[pl.index[tid]]),az_deg=float(az[pl.index[tid]]))
                        for tid in a['assignments'].values()}
            p.pending=dict(action=a,start=now,prediction=prediction,notices=list(p.notices),prior_C=C,prior_E=E)
            last=dict(action='observe',observe_index=idx,hits=hits.get(idx,[]),assigned_count=len(a['assignments']),hit_count=len(hits.get(idx,[])))
            prefix.update((json.dumps(a,sort_keys=True,separators=(',',':'))+'\n').encode())
        elif r['action']=='report':
            result=next((m for m in messages if m['record_type']=='report_result'),None)
            p.pending=dict(action=dict(action='report'));last=dict(action='report',**(result or {}))
        else:
            p.pending=None;last=dict(action='wait')

@dataclass
class Arc:
    start:float
    duration:int
    action:dict
    idx:np.ndarray
    H:np.ndarray
    rawH:np.ndarray
    clearH:np.ndarray
    fiber:np.ndarray|None=None
    def outcomes(self,p,env,scale=1.):
        # H includes public lunar/airmass and q0. rawH adds only directional
        # published/terrain expectation. C/E remain explicit conditional values.
        raw=np.minimum(1.,p.flux[self.idx]*self.duration*self.rawH*env['quality_scale']*scale/p.f0t0)
        band_q=self.H*env['program_band_quality_scale']*scale
        bands=np.where(band_q>=p.dark_threshold,0,np.where(band_q>=p.bright_threshold,1,2))
        prog=PROGRAMS.index(self.action['program'])
        score=p.weight[self.idx]*raw*np.where(bands==prog,p.multipliers[prog],p.mismatch)
        return score,raw

def integration(p,start,duration,field):
    key=(start.timestamp(),int(duration))
    cache=getattr(field,'_common_integral_cache',None)
    if cache is None:
        cache={};field._common_integral_cache=cache
    if key in cache:return cache[key]
    H=np.zeros(p.n);rawH=np.zeros(p.n);clearH=np.zeros(p.n)
    cursor=start;end=start+timedelta(seconds=duration)
    night=next(k for k,(a,b) in enumerate(p.nights) if a<=start<b)
    anchor=p.nights[night][0]
    while cursor<end:
        slot=math.floor((cursor-anchor).total_seconds()/900)
        boundary=min(end,anchor+timedelta(seconds=(slot+1)*900))
        while cursor<boundary:
            right=min(boundary,cursor+timedelta(seconds=120));mid=cursor+(right-cursor)/2
            lst=local_sidereal(mid,p.lon);alt=p._altaz(lst)[0]
            geom=p._public_quality(mid,lst,alt);ds=field.raw_scale_at(mid)
            dt=(right-cursor).total_seconds();H+=dt*geom;rawH+=dt*geom*ds;clearH+=dt*ds;cursor=right
    result=H/duration,rawH/duration,clearH/duration
    cache[key]=result
    return result

def make_arc(p,start,origin,d,center,prog,env,field,scores,assigned=None,all_options=False):
    if d<60 or d>3600:return None
    alt,az,hour,vectors=p._altaz(local_sidereal(start,p.lon))
    last=p._altaz(local_sidereal(start+timedelta(seconds=d),p.lon))[0]
    up=np.where(p.hmax>=180,1e9,(p.hmax-hour)/(360.98564736629/86400))
    fibers,ok,_=p._classify(vectors,*center)
    ok&=(np.minimum(alt,last)>=p.min_alt+.04)&(up>=d+1)
    H,rawH,clearH=integration(p,start,d,field)
    raw=np.minimum(1.,p.flux*d*rawH*env['quality_scale']/p.f0t0)
    band=np.where(H*env['program_band_quality_scale']>=p.dark_threshold,0,
                  np.where(H*env['program_band_quality_scale']>=p.bright_threshold,1,2))
    gain=np.maximum(0.,p.weight*raw*np.where(band==prog,p.multipliers[prog],p.mismatch)-scores)
    if all_options:
        chosen=np.flatnonzero(ok&(gain>1e-10)).tolist();fs=fibers[chosen].tolist()
    elif assigned is None:
        chosen=[];fs=[]
        for f in range(p.nfib):
            cell=np.flatnonzero(ok&(fibers==f)&(gain>1e-10))
            if len(cell):chosen.append(int(cell[np.argmax(gain[cell])]));fs.append(f)
    else:
        fs=[int(f) for f in assigned];chosen=[p.index[assigned[str(f)]] for f in fs]
        if not all(ok[i] and int(fibers[i])==f for i,f in zip(chosen,fs)):return None
    if not chosen:return None
    ix=np.array(chosen,int)
    cmd_alt=round(center[0]-env.get('pointing_offset_alt_deg',0),7)
    cmd_az=round((center[1]-env.get('pointing_offset_az_deg',0))%360,7)
    if not 0<=cmd_alt<=90:return None
    # Check rounded actual command as production does.
    actual=(cmd_alt+env.get('pointing_offset_alt_deg',0),(cmd_az+env.get('pointing_offset_az_deg',0))%360)
    ff,vv,_=p._classify(vectors[ix],*actual)
    if not np.all(vv) or not np.array_equal(ff,np.array(fs)):return None
    a=dict(action='observe',pointing=dict(alt_deg=cmd_alt,az_deg=cmd_az),duration_seconds=d,
           program=PROGRAMS[prog],assignments={} if all_options else {str(f):p.ids[i] for f,i in zip(fs,chosen)})
    return Arc((start-origin).total_seconds(),d,a,ix,H[ix],rawH[ix],clearH[ix],np.asarray(fs,int))

def fields(p,snap,scores,lower,env):
    found=[];original=CPUPhaseSpatialPlanner._evaluate
    def capture(self,center,pool,*frame):
        c=original(self,center,pool,*frame)
        if self is p and c is not None:found.append(c)
        return c
    CPUPhaseSpatialPlanner._evaluate=capture
    try:a=p.choose(snap,scores,lower,dict(env),[])
    finally:CPUPhaseSpatialPlanner._evaluate=original
    centers=[]
    if a:
        centers.append((a['pointing']['alt_deg']+env.get('pointing_offset_alt_deg',0),
                        (a['pointing']['az_deg']+env.get('pointing_offset_az_deg',0))%360))
    for c in sorted(found,key=lambda x:-x[0]):
        if all(max(abs(c[1][0]-v[0]),abs((c[1][1]-v[1]+180)%360-180))>.5 for v in centers):
            centers.append(c[1])
        if len(centers)>=4:break
    return a,centers

def build(p,snap,env,scores,lower):
    origin=parse_utc(snap['now_utc']);pl=copy.deepcopy(p.planner)
    field=PublishedFutureField(pl,snap,p.terrain_model,weather_scenario=temporary_weather_scale,empirical_blocks=p.blocked_spots)
    baseline,centers=fields(pl,snap,scores,lower,env)
    assert baseline is not None
    candidates=[]
    base=make_arc(pl,origin,origin,baseline['duration_seconds'],centers[0],PROGRAMS.index(baseline['program']),env,field,scores,baseline['assignments'])
    assert base is not None,'strong incumbent not executable under public point estimate'
    candidates.append(base)
    for d in (300,900,1800):
        if d==base.duration:continue
        options=[make_arc(pl,origin,origin,d,centers[0],prog,env,field,scores) for prog in range(3)]
        options=[a for a in options if a]
        if options:candidates.append(max(options,key=lambda a:np.maximum(0,a.outcomes(pl,env)[0]-scores[a.idx]).sum()))
    horizon=14400;arcs=[]
    starts=sorted({t for offset in {0}|{a.duration for a in candidates}
                   for t in range(offset,horizon,600)})
    for t in starts:
        moment=origin+timedelta(seconds=t);ns=dict(snap,now_utc=moment.strftime('%Y-%m-%dT%H:%M:%SZ'),new_messages=[],last_result=None)
        # PublishedFutureField controls future evidence; never treat old bulletin
        # as freshly issued at future start. Frame's directional scales refreshed.
        fenv=dict(env,target_quality_scale=field.raw_scale_at(moment))
        _,cs=fields(pl,ns,scores,lower,fenv)
        for center in cs[:4]:
            for d in (300,900,1800):
                if t+d>horizon:continue
                for prog in range(3):
                    arc=make_arc(pl,moment,origin,d,center,prog,env,field,scores,all_options=True)
                    if arc:arcs.append(arc)
    return pl,baseline,candidates,arcs,horizon,field.summary()

def greedy_matching(p,arcs,outcomes,base):
    """Executable greedy time path, then exact whole-path fibre matching.

    This is a guaranteed manual primal solution on the unchanged domain. SciPy
    milp cannot accept a warm start, so it is retained outside the solver.
    """
    started=time.perf_counter();work=base.copy();chosen=[];cursor=0.
    groups={}
    for e,a in enumerate(arcs):groups.setdefault(a.start,[]).append(e)
    for start,options in sorted(groups.items()):
        if start<cursor:continue
        winner=None;rate=0.;picked=None
        for e in options:
            a=arcs[e];gain=np.maximum(0.,outcomes[e]-work[a.idx])
            fs=a.fiber if getattr(a,'fiber',None) is not None else np.arange(len(a.idx))
            pos=[]
            for f in np.unique(fs):
                pp=np.flatnonzero(fs==f);j=int(pp[np.argmax(gain[pp])])
                if gain[j]>1e-10:pos.append(j)
            rr=float(gain[pos].sum()/a.duration)
            if rr>rate+1e-12:winner=e;rate=rr;picked=pos
        if winner is not None:
            a=arcs[winner];chosen.append(winner);cursor=a.start+a.duration
            np.maximum.at(work,a.idx[picked],outcomes[winner][picked])
    cells=[];edges={};targets=set()
    for e in chosen:
        a=arcs[e];fs=a.fiber if getattr(a,'fiber',None) is not None else np.arange(len(a.idx))
        for f in np.unique(fs):
            row=len(cells);cells.append((e,int(f)))
            for pos in np.flatnonzero(fs==f):
                i=int(a.idx[pos]);g=max(0.,float(outcomes[e][pos]-base[i]))
                if g>1e-10:edges[row,i]=g;targets.add(i)
    best=base.copy();assignments={e:{} for e in chosen}
    if cells:
        targets=sorted(targets);col={i:k for k,i in enumerate(targets)}
        costs=np.zeros((len(cells),len(targets)+len(cells)))
        for (row,i),g in edges.items():costs[row,col[i]]=-g
        rs,cs=linear_sum_assignment(costs)
        for row,k in zip(rs,cs):
            if k>=len(targets) or costs[row,k]>=-1e-10:continue
            i=targets[k];e,f=cells[row];assignments[e][str(f)]=p.ids[i]
            best[i]=base[i]+edges[row,i]
    return best,chosen,assignments,time.perf_counter()-started

def solve(p,arcs,scores,lower,env,scale=1.,first=None,blocked_seconds=0,time_limit=8.):
    """Exact finite coverage MILP, solver gap retained if time budget expires.

    This version optimizes science only. Initial factors are retained for public
    uncertainty reporting; no ambiguous completion is silently made true.
    """
    base=scores.copy();first_gain=0.
    if first is not None:
        ss,_=first.outcomes(p,env,scale);np.maximum.at(base,first.idx,ss)
        first_gain=float(base.sum()-scores.sum());blocked_seconds=first.duration
    eligible=[a for a in arcs if a.start>=blocked_seconds]
    outcomes=[a.outcomes(p,env,scale)[0] for a in eligible]
    manual_best,manual_keys,manual_assign,manual_seconds=greedy_matching(p,eligible,outcomes,base)
    m=len(eligible);target_entries={};fiber_entries={};pairs=[]
    for e,(a,s) in enumerate(zip(eligible,outcomes)):
        for pos,(i,c) in enumerate(zip(a.idx,s)):
            gain=max(0.,float(c-base[i]))
            if gain>1e-10:
                f=int(a.fiber[pos]) if getattr(a,'fiber',None) is not None else pos
                j=m+len(pairs);pairs.append((e,int(i),gain,f));target_entries.setdefault(int(i),[]).append(j)
                fiber_entries.setdefault((e,f),[]).append(j)
    n=m+len(pairs);objective=np.zeros(n);integrality=np.zeros(n,dtype=np.uint8);integrality[:m]=1
    for k,(_,_,g,_) in enumerate(pairs):objective[m+k]=-g
    rr=[];cc=[];vv=[];lb=[];ub=[]
    def row(cols,vals,lo=-np.inf,hi=1.):
        r=len(lb);rr.extend([r]*len(cols));cc.extend(cols);vv.extend(vals);lb.append(lo);ub.append(hi)
    knots=sorted({float(blocked_seconds)}|{a.start for a in eligible}|{a.start+a.duration for a in eligible})
    for left,right in zip(knots,knots[1:]):
        touching=[k for k,a in enumerate(eligible) if a.start<right and a.start+a.duration>left]
        if touching:row(touching,[1.]*len(touching))
    for (e,f),cols in fiber_entries.items():row(cols+[e],[1.]*len(cols)+[-1.],hi=0.)
    for cols in target_entries.values():row(cols,[1.]*len(cols))
    A=coo_matrix((vv,(rr,cc)),shape=(len(lb),n)).tocsr()
    started=time.perf_counter()
    result=milp(objective,integrality=integrality,bounds=Bounds(np.zeros(n),np.ones(n)),
        constraints=LinearConstraint(A,np.array(lb),np.array(ub)),
        options=dict(time_limit=time_limit,mip_rel_gap=1e-7))
    if result.x is None:
        # The manual greedy path with joint matching is always executable. A per-target maximum over the same
        # domain is a safe finite-model upper bound when HiGHS has not produced
        # any bound. It is only a failure certificate, never an adopted policy.
        cap=base.copy()
        for a,ss in zip(eligible,outcomes):np.maximum.at(cap,a.idx,ss)
        upper=float(cap.sum()-scores.sum())
        raw_bound=getattr(result,'mip_dual_bound',None)
        if raw_bound is not None and np.isfinite(raw_bound):upper=min(upper,first_gain-float(raw_bound))
        value=float(manual_best.sum()-scores.sum())
        return dict(value=value,first_gain=first_gain,suffix_gain=value-first_gain,status=int(result.status),
            optimal=False,gap=None,upper_value=upper,solve_seconds=time.perf_counter()-started,
            columns=m,winner_variables=len(pairs),affected_targets=int(np.count_nonzero(manual_best>scores+1e-10)),
            contributions={p.ids[i]:float(manual_best[i]-scores[i]) for i in np.flatnonzero(manual_best>scores+1e-10)},
            path=[dict(start_seconds=eligible[e].start,**{**eligible[e].action,'assignments':manual_assign[e]})
                  for e in manual_keys if manual_assign[e]],no_solver_incumbent=True,message=str(result.message),
            primal_source='greedy_time_path_then_joint_matching',manual_primal_seconds=manual_seconds)
    selected_keys=np.flatnonzero(result.x[:m]>.5).tolist()
    selected=[eligible[k] for k in selected_keys]
    assignments={e:{} for e in selected_keys}
    matched=np.flatnonzero(result.x[m:]>1e-6)
    assert all(abs(result.x[m+k]-1.)<1e-6 for k in matched),'fractional target/fibre winner'
    best=base.copy()
    for k in matched:
        e,i,g,f=pairs[k];assignments[e][str(f)]=p.ids[i]
        best[i]=max(best[i],base[i]+g)
    value=float(best.sum()-scores.sum())
    model_value=first_gain-float(result.fun)
    assert abs(value-model_value)<1e-5,(value,model_value)
    primal_source='MILP'
    if manual_best.sum()>best.sum()+1e-9:
        best=manual_best;selected_keys=manual_keys;selected=[eligible[e] for e in selected_keys]
        assignments=manual_assign;value=float(best.sum()-scores.sum());primal_source='manual_better_than_MILP_incumbent'
    selected.sort(key=lambda a:a.start)
    assert all(a.start+a.duration<=b.start+1e-8 for a,b in zip(selected,selected[1:])), 'overlapping exposure path'
    return dict(value=value,first_gain=first_gain,suffix_gain=value-first_gain,
        status=int(result.status),optimal=result.status==0,gap=float(getattr(result,'mip_gap',0)),
        upper_value=first_gain-float(getattr(result,'mip_dual_bound',result.fun)),
        solve_seconds=time.perf_counter()-started,columns=m,winner_variables=len(pairs),
        affected_targets=int(np.count_nonzero(best>scores+1e-10)),
        primal_source=primal_source,manual_primal_seconds=manual_seconds,
        contributions={p.ids[i]:float(best[i]-scores[i]) for i in np.flatnonzero(best>scores+1e-10)},
        path=[dict(start_seconds=eligible[e].start,**{**eligible[e].action,'assignments':assignments[e]})
              for e in sorted(selected_keys,key=lambda e:eligible[e].start) if assignments[e]])

def run_state(card,night):
    begun=time.perf_counter();pol,snap,env,meta=public_prefix(card,night)
    scores=pol.scores.copy();lower=pol.factor_lower.copy()
    p,baseline,candidates,arcs,horizon,field=build(pol,snap,env,scores,lower)
    built=time.perf_counter();results=[]
    for scale in (.9,1.,1.1):
        unrestricted=solve(p,arcs,scores,lower,env,scale,time_limit=8.)
        ranked=[]
        for i,first in enumerate(candidates):
            got=solve(p,arcs,scores,lower,env,scale,first=first,time_limit=8.)
            empty=solve(p,arcs,scores,lower,env,scale,blocked_seconds=first.duration,time_limit=8.)
            # All-target opportunity loss of reserving this interval: same
            # initial ledger, same future column domain, no first target reward.
            opportunity=unrestricted['value']-empty['value']
            displaced={tid:unrestricted['contributions'].get(tid,0.)-empty['contributions'].get(tid,0.)
                       for tid in set(unrestricted['contributions'])|set(empty['contributions'])}
            ranked.append(dict(candidate=i,action=first.action,joint=got,empty_interval=empty,
                all_target_time_opportunity_loss=opportunity,
                opportunity_loss_interval=[unrestricted['value']-empty['upper_value'],unrestricted['upper_value']-empty['value']],
                displaced_unassigned_net=sum(v for tid,v in displaced.items() if tid not in first.action['assignments'].values()),
                displaced_target_contributions=displaced,
                net_first_after_time=got['first_gain']-opportunity,
                coverage_overlap_loss=empty['value']-got['suffix_gain'],
                coverage_overlap_loss_interval=[empty['value']-(got['upper_value']-got['first_gain']),
                                                empty['upper_value']-got['suffix_gain']]))
        order=sorted(range(len(ranked)),key=lambda i:-ranked[i]['joint']['value'])
        # Certified strict ordering when incumbent lower exceeds all rival bounds.
        win=order[0];certified=all(ranked[win]['joint']['value']>ranked[j]['joint']['upper_value']+1e-6 for j in order[1:])
        results.append(dict(quality_scale_multiplier=scale,unrestricted=unrestricted,
            order=order,winner=win,certified_strict_winner=certified,candidates=ranked))
        dump(OUT/f'{card}_night{night}_partial.json',dict(metadata=meta,results=results))
        print(json.dumps(dict(card=card,night=night,sensitivity=scale,order=order,certified=certified,
            no_incumbent_solves=int(unrestricted.get('no_solver_incumbent',False))+sum(
                int(x['joint'].get('no_solver_incumbent',False))+int(x['empty_interval'].get('no_solver_incumbent',False)) for x in ranked))),flush=True)
    upper=np.minimum(1.,(scores+.5e-6)/(p.weight*min(p.mismatch,float(p.multipliers.min()))))
    lb=np.maximum(0.,scores-.5e-6)/(p.weight*max(p.multipliers))
    meta.update(now_utc=snap['now_utc'],catalog=p.n,horizon_seconds=horizon,
        build_seconds=built-begun,total_seconds=time.perf_counter()-begun,
        first_candidates=len(candidates),future_columns=len(arcs),strong_baseline=baseline,
        public_completion_interval=dict(guaranteed_complete=int(np.count_nonzero(lb>=.5)),
            guaranteed_incomplete=int(np.count_nonzero(upper<.5)),ambiguous=int(np.count_nonzero((lb<.5)&(upper>=.5)))),
        model='common exposure interval + joint target-to-exposure-fibre matching MILP; science-only; conditional public C/E',
        active_request_count=0,published_future_field=field,results=results,
        stable_ranking_change=all(r['winner']!=0 and r['certified_strict_winner'] for r in results)
                            and len(set(r['winner'] for r in results))==1)
    dump(OUT/f'{card}_night{night}.json',meta)
    print(json.dumps({k:meta[k] for k in ('card','night_index','now_utc','future_columns','build_seconds','total_seconds','stable_ranking_change')}
        |dict(orders=[r['order'] for r in results],certified=[r['certified_strict_winner'] for r in results])),flush=True)
    return meta

def main():
    declaration=dict(prefixes=[['L1',7],['L1',17],['L2',7],['L2',17]],
        horizon_seconds=14400,future_start_step=600,
        common_start_offsets='0 plus every first-candidate duration; identical domain for all first candidates',
        field_count=4,durations=[300,900,1800],
        future_assignment='joint target-to-(exposure,fibre) winner matching; no fixed greedy suffix assignment',
        first_alternatives='strong actual source action plus same field duration variants',
        sensitivity=[.9,1.,1.1],milp_seconds_per_solve=8,mip_rel_gap=1e-7,
        positive='same nonzero first candidate is certified strict winner at all three fixed sensitivities',
        no_incumbent='retain greedy nonoverlap time path with exact fixed-path fibre matching and upper certificate; classify as failed solver; do not extend time',
        negative='no stable certified change; retain result and stop without expanding samples',
        forbidden_inputs=['future weather','future bulletin/forecast publication','raw observation factor/quality/prog_mult'],
        scope='public-prefix conditional model ranking only; no old feedback after changed action; no full season',
        control_zip_sha256=sha(ZIP),source_members=29)
    dump(OUT/'PREDECLARATION.json',declaration)
    with zipfile.ZipFile(ZIP) as z:
        assert len(z.namelist())==29
        assert all((CONTROL/name).read_bytes()==z.read(name) for name in z.namelist())
    rows=[]
    for card,night in declaration['prefixes']:
        try:rows.append(run_state(card,night))
        except Exception as error:
            failure=dict(card=card,night_index=night,stable_ranking_change=False,total_seconds=0.,
                         now_utc='',error=repr(error))
            dump(OUT/f'{card}_night{night}_failure.json',failure);rows.append(failure)
            print(json.dumps(failure),flush=True)
    dump(OUT/'summary.json',dict(predeclaration=declaration,stable_changes=sum(r['stable_ranking_change'] for r in rows),
        prefixes=[{k:r[k] for k in ('card','night_index','now_utc','stable_ranking_change','total_seconds')} for r in rows],
        production_adopted=False,full_season_run=False))

if __name__=='__main__':main()
