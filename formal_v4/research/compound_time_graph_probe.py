#!/usr/bin/env python3
"""Two complete fields, continuous integer time exchange, public prefix only.

Candidate search imports public-release geometry and causal feedback policy.
Official evaluator is called only after a candidate list has been frozen.
"""
from __future__ import annotations
import copy,csv,hashlib,json,math,os,sys,time
from pathlib import Path
from datetime import timedelta
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
sys.dont_write_bytecode=True
BASE=Path(__file__).resolve().parents[1];FROZEN=BASE/'runs/geometry_native_20261003/release';UP=BASE/'upstream/gosim-observer-examples';OUT=BASE/'results/compound_time_graph_20261004'
sys.path.insert(0,str(FROZEN));sys.path.insert(1,str(UP))
import numpy as np
import policy
from research.candidate_geometry_sweep import CandidateGeometryPlanner
from research.spatial_candidates import SpatialPlanner,PROGRAMS,parse_utc,local_sidereal,SIDEREAL_SPEED
from runner.challenge.v4_runner import run_scenario,load_scenario,normalize_action
from runner.challenge.v4_workflow import V4Workflow
from runner.challenge.v4_fiber_map import FiberGrid,min_altitude_during,altaz_to_radec,radec_to_altaz
policy.SpatialPlanner=CandidateGeometryPlanner
TRACE={'L1':BASE/'results/geometry_native_20261003/protocol_gate_remaining/L1','L2':BASE/'results/geometry_native_20261003/protocol_gate_retry/L2'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,obj):p.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
def center_actual(a,env):return (a['pointing']['alt_deg']+env.get('pointing_offset_alt_deg',0),(a['pointing']['az_deg']+env.get('pointing_offset_az_deg',0))%360)
def serialize(p,c,env):
    center,d,prog,ix,fs=c
    return dict(action='observe',pointing=dict(alt_deg=round(center[0]-env.get('pointing_offset_alt_deg',0),7),az_deg=round((center[1]-env.get('pointing_offset_az_deg',0))%360,7)),assignments={str(int(f)):p.ids[int(i)] for i,f in zip(ix,fs)},duration_seconds=int(d),program=PROGRAMS[int(prog)])
def capture(p,snap,scores,factors,env):
    pl=copy.deepcopy(p);pl.choose=CandidateGeometryPlanner.choose.__get__(pl,type(pl));found=[];original=SpatialPlanner._evaluate
    def wrapper(self,center,pool,*frame):
        c=original(self,center,pool,*frame)
        if self is pl and c is not None:found.append(c)
        return c
    SpatialPlanner._evaluate=wrapper
    try:a=pl.choose(snap,scores,factors,env,snap.get('active_requests',[]))
    finally:SpatialPlanner._evaluate=original
    winner=(0.,center_actual(a,env),a['duration_seconds'],PROGRAMS.index(a['program']),np.array([pl.index[x] for x in a['assignments'].values()]),np.array(list(map(int,a['assignments']))))
    proposals=[winner]+sorted(found,key=lambda c:-c[0]);centers=[]
    for c in proposals:
        if all(np.linalg.norm(np.array(c[1])-np.array(old))>.15 for old in centers):centers.append(c[1])
        if len(centers)==12:break
    return a,pl,centers

def terminal(p,s,f,idx,baseline):
    science=baseline['science']+np.sum(s-baseline['s0'])
    missing=baseline['missing']-np.count_nonzero(p.required[idx]&(baseline['f0']<p.req_threshold)&(f>=p.req_threshold))
    bc=baseline['band_count'].copy();cross=(baseline['f0']<p.uniform_threshold)&(f>=p.uniform_threshold)
    np.add.at(bc,p.ra_bands[idx[cross]],1)
    r=np.divide(bc,p.band_sizes,out=np.zeros_like(bc,dtype=float),where=p.band_sizes>0);v=float(r@r)
    j=float(r.sum()**2/(p.nonempty_bands*v)) if v else 0.
    return float(science-p.req_penalty*missing-p.uniform_weight*(1-j))

def prepare(p,s,f,idx):
    return dict(science=float(s.sum()),missing=int(np.count_nonzero(p.required&(f<p.req_threshold))),band_count=np.bincount(p.ra_bands,weights=f>=p.uniform_threshold,minlength=len(p.band_sizes)),s0=s[idx].copy(),f0=f[idx].copy())

class PairDomain:
    def __init__(self,p,snap,scores,factors,env,centers,H):
        self.p=p;self.snap=snap;self.env=env;self.now=parse_utc(snap['now_utc']);self.H=H;self.calls=0
        self.eq=[altaz_to_radec(*c,self.now,p.lat,p.lon) for c in centers]
        # Public full-catalog spherical cap around each field includes every possible
        # rotation of the 4x4 grid (circumradius), plus conservative 0.1deg padding.
        cv=[]
        for ra,de in self.eq:cv.append([math.cos(de*math.pi/180)*math.cos(ra*math.pi/180),math.cos(de*math.pi/180)*math.sin(ra*math.pi/180),math.sin(de*math.pi/180)])
        dots=p.eq_vectors@np.array(cv).T
        self.idx=np.flatnonzero(np.max(dots,axis=1)>=math.cos((p.fov/math.sqrt(2)+.1)*math.pi/180))
        self.s=np.asarray(scores)[self.idx].copy();self.f=np.asarray(factors)[self.idx].copy();self.b=prepare(p,np.asarray(scores),np.asarray(factors),self.idx)
        self.k0=p.flux[self.idx]/p.f0t0;self.weight=p.weight[self.idx];self.required=p.required[self.idx]
        self.scale=max(.005,float(env['quality_scale']));self.band_scale=max(.005,float(env['program_band_quality_scale']));self.safety=max(1.,float(env.get('duration_safety',1.06)))
        tq=env.get('target_quality_scale');self.tq=np.ones(len(self.idx)) if tq is None else np.asarray(tq)[self.idx]
        self.geometry_cache={};self.quality_cache={}
    def geometry(self,offset):
        if offset in self.geometry_cache:return self.geometry_cache[offset]
        p=self.p;now=self.now+timedelta(seconds=int(offset));lst=local_sidereal(now,p.lon);alt,az,h,v=p._altaz(lst)
        up=np.where(p.hmax>=180,1e9,(p.hmax-h)/SIDEREAL_SPEED)-1
        centers=[radec_to_altaz(ra,de,now,p.lat,p.lon) for ra,de in self.eq]
        cells=[]
        for c in centers:
            fi,ok,_=p._classify(v,*c);cells.append((fi[self.idx],ok[self.idx]))
        self.geometry_cache[offset]=(centers,cells,up[self.idx],alt[self.idx])
        return self.geometry_cache[offset]
    def quality(self,offset,d):
        key=(offset,d)
        if key in self.quality_cache:return self.quality_cache[key]
        p=self.p;cursor=self.now+timedelta(seconds=int(offset));end=cursor+timedelta(seconds=int(d));total=np.zeros(len(self.idx))
        while cursor<end:
            right=min(end,cursor+timedelta(seconds=120));mid=cursor+(right-cursor)/2;lst=local_sidereal(mid,p.lon);alt,*_=p._altaz(lst)
            total+=(right-cursor).total_seconds()*p._public_quality(mid,lst,alt)[self.idx];cursor=right
        q=total/d;raw=np.minimum(1.,self.k0*d*q*self.scale*self.tq);lower=raw/self.safety
        bands=np.where(q*self.band_scale>=p.dark_threshold,0,np.where(q*self.band_scale>=p.bright_threshold,1,2))
        mult=np.where(bands[None,:]==np.arange(3)[:,None],p.multipliers[:,None],p.mismatch)
        result=(raw,lower,self.weight[None,:]*raw[None,:]*mult);self.quality_cache[key]=result;return result
    def options(self,offset,d,s,f):
        p=self.p;centers,cells,up,alt=self.geometry(offset);raw,lower,contrib=self.quality(offset,d);result=[]
        req=(self.required&(f<p.req_threshold)&(lower>=p.req_threshold))*p.req_penalty
        # Assignment uses exact separable science+required; exact Jain is evaluated
        # jointly for each complete action and compound leaf, without a gradient.
        for ci,(fiber,hit) in enumerate(cells):
            eligible=hit&(alt>=p.min_alt+.04)&(up>=d)
            for prog in range(3):
                value=np.maximum(0.,contrib[prog]-s)+req;chosen=[];fs=[]
                for fi in range(p.nfib):
                    jj=np.flatnonzero(eligible&(fiber==fi)&(value>0))
                    if len(jj):j=int(jj[np.argmax(value[jj])]);chosen.append(j);fs.append(fi)
                if not chosen:continue
                selected=np.asarray(chosen,int);ss=s.copy();ff=f.copy();ss[selected]=np.maximum(ss[selected],contrib[prog,selected]);ff[selected]=np.maximum(ff[selected],lower[selected])
                gain=terminal(p,ss,ff,self.idx,self.b);c=(centers[ci],int(d),prog,self.idx[selected],np.asarray(fs,int))
                result.append((gain,ss,ff,c,ci))
        self.calls+=len(result)
        return result
    def duration_set(self):
        H=self.H;p=self.p;centers,cells,up,alt=self.geometry(0);raw,lower,c=self.quality(0,1)
        ks=raw;times={60,H-60,H}
        # All threshold and replacement crossings in both sides of the shared
        # capacity. Public geometry integration then reranks them at actual starts.
        for k in range(len(self.idx)):
            if ks[k]<=0:continue
            roots=[1/ks[k],p.req_threshold*self.safety/ks[k],p.uniform_threshold*self.safety/ks[k]]
            roots.extend(self.s[k]/max(c[j,k],1e-12) for j in range(3))
            for x in roots:
                for d in (math.floor(x)-1,math.floor(x),math.ceil(x),math.ceil(x)+1):
                    if 60<=d<=H-60:times.add(int(d));times.add(H-int(d))
        return sorted(times)
    def best_seconds(self,offset,d,first):
        """Batch the exact same second-field assignment across first ledgers."""
        p=self.p;centers,cells,up,alt=self.geometry(offset);raw,lower,contrib=self.quality(offset,d)
        S=np.asarray([x[1] for x in first]);F=np.asarray([x[2] for x in first]);N=len(first)
        best=np.full(N,-np.inf);chosen_actions=[None]*N
        req=(self.required[None,:]&(F<p.req_threshold)&(lower[None,:]>=p.req_threshold))*p.req_penalty
        rows=np.arange(N)
        for ci,(fiber,hit) in enumerate(cells):
            eligible=hit&(alt>=p.min_alt+.04)&(up>=d)
            groups=[np.flatnonzero(eligible&(fiber==fi)) for fi in range(p.nfib)]
            for prog in range(3):
                value=np.maximum(0.,contrib[prog][None,:]-S)+req
                ss=S.copy();ff=F.copy();selected=np.full((N,p.nfib),-1,int)
                for fi,jj in enumerate(groups):
                    if not len(jj):continue
                    local=value[:,jj];win=jj[np.argmax(local,axis=1)];valid=local.max(axis=1)>0
                    rr=rows[valid];ww=win[valid];selected[rr,fi]=ww
                    ss[rr,ww]=np.maximum(ss[rr,ww],contrib[prog,ww]);ff[rr,ww]=np.maximum(ff[rr,ww],lower[ww])
                science=self.b['science']+np.sum(ss-self.b['s0'][None,:],axis=1)
                missing=self.b['missing']-np.count_nonzero(self.required[None,:]&(self.b['f0'][None,:]<p.req_threshold)&(ff>=p.req_threshold),axis=1)
                counts=np.tile(self.b['band_count'],(N,1));cross=(self.b['f0'][None,:]<p.uniform_threshold)&(ff>=p.uniform_threshold)
                ri,tj=np.nonzero(cross);np.add.at(counts,(ri,p.ra_bands[self.idx[tj]]),1)
                rat=np.divide(counts,p.band_sizes[None,:],out=np.zeros_like(counts),where=p.band_sizes[None,:]>0)
                v=np.sum(rat*rat,axis=1);j=np.divide(rat.sum(axis=1)**2,p.nonempty_bands*v,out=np.zeros(N),where=v>0)
                values=science-p.req_penalty*missing-p.uniform_weight*(1-j)
                for r in np.flatnonzero(values>best):
                    chosen=selected[r];fib=np.flatnonzero(chosen>=0);ix=self.idx[chosen[fib]]
                    if len(ix):best[r]=values[r];chosen_actions[r]=(centers[ci],int(d),prog,ix,fib)
                self.calls+=N
        return [(float(best[r]),chosen_actions[r]) for r in range(N)]
    def optimize(self,native):
        started=time.perf_counter();p=self.p;H=self.H;native_d=min(native['duration_seconds'],H-60)
        baseline_terminal=terminal(p,self.s,self.f,self.idx,self.b)
        candidates=[];durations=self.duration_set();leaves=0;greed=[]
        print(json.dumps(dict(phase='domain',H=H,durations=len(durations),targets=len(self.idx),fields=len(self.eq))),flush=True)
        # Enumerate all breakpoint proposals; no scan-count tuning. Pair assignments
        # are recomputed after first-field overwrites, with second sky geometry at t+d.
        for d in durations:
            if d>H-60:continue
            first=self.options(0,d,self.s,self.f)
            seconds=self.best_seconds(d,H-d,first);leaves+=len(first)*len(self.eq)*3
            for x,(v2,c2) in zip(first,seconds):
                v,ss,ff,c,ci=x
                if c2 is not None:candidates.append((v2,[c,c2],d,ci,-2))
                greed.append(((v-baseline_terminal)/d,v,ss,ff,c,ci))
            candidates.sort(key=lambda c:-c[0]);candidates=candidates[:8]
        single=self.options(0,H,self.s,self.f)
        for v,ss,ff,c,ci in single:candidates.append((v,[c],H,ci,-1))
        candidates.sort(key=lambda c:-c[0]);best=candidates[0]
        # Greedy finite-domain control: highest first marginal rate, then best full
        # second action over exactly the same horizon; compares like-for-like time.
        g=max(greed,key=lambda x:x[0]);second=max(self.options(g[4][1],H-g[4][1],g[2],g[3]),key=lambda x:x[0]);greedy=(second[0],[g[4],second[3]],g[4][1],g[5],second[4])
        # Strong release action first, exact native assignments, then full reassignment
        # from the public field library. It can be outside these twelve field centers.
        ix=np.array([p.index[x] for x in native['assignments'].values()]);fs=np.array(list(map(int,native['assignments'])));ci=(center_actual(native,self.env),native_d,PROGRAMS.index(native['program']),ix,fs)
        pos={int(i):j for j,i in enumerate(self.idx)};ss=self.s.copy();ff=self.f.copy();raw,lower,contrib=self.quality(0,native_d)
        for i in ix:
            j=pos[int(i)];ss[j]=max(ss[j],contrib[ci[2],j]);ff[j]=max(ff[j],lower[j])
        strongsecond=max(self.options(native_d,H-native_d,ss,ff),key=lambda x:x[0]);strong=(strongsecond[0],[ci,strongsecond[3]],native_d,0,strongsecond[4])
        def record(x):return dict(model_terminal=x[0],model_gain=x[0]-baseline_terminal,durations=[int(c[1]) for c in x[1]],fields=[int(x[3]),int(x[4])],actions=[serialize(p,c,self.env) for c in x[1]])
        return dict(best=record(best),greedy=record(greedy),strong_first=record(strong),top_candidates=[record(x) for x in candidates[:8]],baseline_terminal=baseline_terminal,integer_duration_candidates=len(durations),field_centers=len(self.eq),relevant_targets=len(self.idx),pair_leaves=leaves,assignment_options=self.calls,seconds=time.perf_counter()-started)

def micro(card):
    started=time.perf_counter();trace=TRACE[card];tape=[json.loads(l) for l in (trace/'actions.jsonl').read_text().splitlines()];rows=list(csv.DictReader((trace/'decisions.csv').open()));observes=[r for r in rows if r['action']=='observe'];pick=None
    for prev,r in zip(observes,observes[1:]):
        now=parse_utc(r['start_utc']);pr=parse_utc(prev['start_utc']);remain=900-(int(now.timestamp())%900)
        if int(r['observe_index'])<200 and int(now.timestamp())//900==int(pr.timestamp())//900 and remain>=600:
            pick=r;break
    assert pick is not None;now=parse_utc(pick['start_utc']);H=900-(int(now.timestamp())%900);target_rank=int(pick['observe_index']);initial=V4Workflow(UP/'local-cards'/card).initialize_payload(900);p=policy.Policy(initial);seq=0;captured={};prefix=[];source_action=None
    def forced(snapshot,scores,factors,env,requests):
        nonlocal captured,source_action
        pl=p.planner;a=tape[seq]
        if snapshot['observe_action_index']==target_rank:
            source_action=copy.deepcopy(a);generated,q,centers=capture(pl,snapshot,scores,factors,env)
            captured=dict(snapshot=copy.deepcopy(snapshot),scores=scores.copy(),factors=factors.copy(),env=copy.deepcopy(env),planner=q,centers=centers,natural_action=generated)
        alt,az,_,_=pl._altaz(local_sidereal(parse_utc(snapshot['now_utc']),pl.lon));pl.last_prediction={tid:dict(alt_deg=float(alt[pl.index[tid]]),az_deg=float(az[pl.index[tid]])) for tid in a['assignments'].values()};pl.stats={};return copy.deepcopy(a)
    p.planner.choose=forced
    def decide(snapshot):
        nonlocal seq
        a=p.decide(snapshot)
        if captured:return None
        assert a==tape[seq],(seq,a,tape[seq]);prefix.append(copy.deepcopy(a));seq+=1;return a
    run_scenario(UP/'local-cards'/card/'config/v4_scenario.json',lambda _:decide,OUT/f'prefix_{card}')
    assert not captured['snapshot'].get('active_requests'), 'Chosen current-slot study excludes active requests, model handles gates separately'
    pl=captured.pop('planner');env=captured['env'];domain=PairDomain(pl,captured['snapshot'],captured['scores'],captured['factors'],env,captured['centers'],H)
    summary=domain.optimize(source_action)
    result=dict(card=card,rank=target_rank,prefix_actions=len(prefix),now_utc=pick['start_utc'],horizon_seconds=H,source_action=source_action,natural_action=captured['natural_action'],natural_action_matches=captured['natural_action']==source_action,prefix_sha256=hashlib.sha256(('\n'.join(json.dumps(a,sort_keys=True,separators=(',',':')) for a in prefix)+'\n').encode()).hexdigest(),source_hash={n:sha(trace/n) for n in ('actions.jsonl','decisions.csv','observations.csv','messages.jsonl','score_report.json')},env={k:v for k,v in env.items() if k!='target_quality_scale'},search=summary)
    # Freeze the full candidate list before loading scenario truth for adjudication.
    write(OUT/f'{card}_search_frozen.json',result)
    scenario=load_scenario(UP/'local-cards'/card/'config/v4_scenario.json');grid=FiberGrid.from_config(scenario.fiber_config);td={t['target_id']:t for t in scenario.targets}
    unique=[]
    for name in ('best','greedy','strong_first'):
        branch=summary[name];actions=branch['actions'];start=now
        for a in actions:
            normalize_action(a,scenario,td,start)
            for fi,tid in a['assignments'].items():
                t=td[tid];classification=grid.classify_target(t['ra_deg'],t['dec_deg'],start,a['pointing']['alt_deg'],a['pointing']['az_deg'],pl.lat,pl.lon,env.get('pointing_offset_alt_deg',0),env.get('pointing_offset_az_deg',0))
                assert classification.region=='glass' and classification.fiber_id==int(fi),(fi,tid,classification)
                assert min_altitude_during(t['ra_deg'],t['dec_deg'],start,start+timedelta(seconds=a['duration_seconds']),scenario.config)>=scenario.minimum_altitude_deg
            start+=timedelta(seconds=a['duration_seconds'])
        branch_tape=prefix+actions;cursor=0
        def callback(snap):
            nonlocal cursor
            if cursor>=len(branch_tape):return None
            a=branch_tape[cursor];cursor+=1;return a
        report=run_scenario(UP/'local-cards'/card/'config/v4_scenario.json',lambda _:callback,OUT/f'{card}_{name}')
        branch['official_micro_terminal']=report['total'];branch['official_components']=report['components'];branch['official_counts']=report['counts']
    result['official_best_minus_greedy']=summary['best']['official_micro_terminal']-summary['greedy']['official_micro_terminal'];result['official_best_minus_strong_first']=summary['best']['official_micro_terminal']-summary['strong_first']['official_micro_terminal'];result['seconds']=time.perf_counter()-started
    write(OUT/f'{card}_result.json',result);print(json.dumps({k:result[k] for k in ('card','rank','horizon_seconds','natural_action_matches','official_best_minus_greedy','official_best_minus_strong_first','seconds')}),flush=True)
    return result
if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True);results=[]
    for card in sys.argv[1:] or ['L1','L2']:results.append(micro(card))
    write(OUT/'summary.json',results)
