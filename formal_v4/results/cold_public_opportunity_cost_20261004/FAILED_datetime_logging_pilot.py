"""Public-only whole-calendar nominal science LP and reduced-price proposals.

No workflow loader, actual weather, future messages, requests or truth scores.
"""
from __future__ import annotations
import argparse, copy, hashlib, itertools, json, math, os, resource, sys, time
from datetime import timedelta
from pathlib import Path

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'official'))
sys.path.insert(0,str(ROOT/'baseline_package'))
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from sparse_exact import install
install()
import wrapper
from research.spatial_candidates import _shift_altaz, local_sidereal, SIDEREAL_SPEED, PROGRAMS
from research.geometry import parse_utc,format_utc
from research.feedback_model import seasonal_quality
from challenge.v4_fiber_map import min_altitude_during,FiberGrid,radec_to_altaz
from challenge.v4_scorer import SlotTruth,WeatherTruth,score_target_exposure,lunar_quality_factor,program_band,program_multiplier

DURATIONS=(120,600,1800,3600)
LIMIT=10.; RSS_LIMIT=512*1024**2

def audit(event,args):
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        parts=Path(os.fsdecode(args[0])).parts
        if 'truth' in parts or 'generated_worlds' in parts:
            raise PermissionError('Actor cannot open generated-world/truth files')
sys.addaudithook(audit)

def dump(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')

def digest(obj): return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

class CostStop(RuntimeError):pass

class Cost:
    def __init__(self):self.start=time.perf_counter();self.cpu=time.process_time();self.stages=[]
    def check(self):
        if time.perf_counter()-self.start>LIMIT:raise CostStop('selection total wall exceeded 10 seconds')
        if rss()>RSS_LIMIT:raise CostStop('selection max RSS exceeded 512 MiB')
    def stage(self,name,start,cpu):
        self.stages.append(dict(stage=name,wall_seconds=time.perf_counter()-start,cpu_seconds=time.process_time()-cpu))
        self.check()
    def result(self):return dict(wall_seconds=time.perf_counter()-self.start,cpu_seconds=time.process_time()-self.cpu,
        max_rss_bytes=rss(),stages=self.stages,total_limit_seconds=LIMIT,rss_limit_bytes=RSS_LIMIT)

class PublicGeometry:
    def __init__(self,p,slot_seconds,cost):
        self.p=p;self.slot=slot_seconds;self.cache={};self.cost=cost;self.calls=0;self.integration_pieces=0
        self.wall_seconds=0.;self.cpu_seconds=0.
    def value(self,start,d):
        key=(start.timestamp(),int(d))
        if key in self.cache:return self.cache[key]
        timer=time.perf_counter();cpu_timer=time.process_time()
        p=self.p;ni=next(k for k,(a,b) in enumerate(p.nights) if a<=start<b)
        a,b=p.nights[ni];end=start+timedelta(seconds=int(d))
        if end>b:raise ValueError('No hidden night clipping in finite columns')
        cursor=start;H=np.zeros(p.n)
        while cursor<end:
            slot_index=math.floor((cursor-a).total_seconds()/self.slot)
            piece_end=min(end,a+timedelta(seconds=(slot_index+1)*self.slot),cursor+timedelta(seconds=120))
            mid=cursor+(piece_end-cursor)/2;lst=local_sidereal(mid,p.lon);alt=p._altaz(lst)[0]
            H+=(piece_end-cursor).total_seconds()*p._public_quality(mid,lst,alt)*p.q0
            cursor=piece_end;self.integration_pieces+=1
        H/=d
        alt,az,hour,vectors=p._altaz(local_sidereal(start,p.lon))
        h1=hour+SIDEREAL_SPEED*d
        mc=np.minimum(np.cos(np.deg2rad(hour)),np.cos(np.deg2rad(h1)))
        critical=180+360*np.ceil((hour-180)/360)
        mc=np.where(critical<=h1,-1.,mc)
        min_alt=np.rad2deg(np.arcsin(np.clip(p.sin_lat*p.sin_dec+p.cos_lat*p.cos_dec*mc,-1.,1.)))
        eligible=min_alt>=p.min_alt
        C,E=seasonal_quality(start.timetuple().tm_yday,p.q0)
        factor=np.minimum(1.,p.flux*d*C*E*H/p.f0t0)
        band=np.where(C*H>=p.dark_threshold,0,np.where(C*H>=p.bright_threshold,1,2))
        c=np.stack([p.weight*factor*np.where(band==pr,p.multipliers[pr],p.mismatch) for pr in range(3)])
        out=dict(start=start,end=end,alt=alt,az=az,vectors=vectors,H=H,min_alt=min_alt,eligible=eligible,c=c,C=C,E=E)
        self.cache[key]=out;self.calls+=1
        self.wall_seconds+=time.perf_counter()-timer;self.cpu_seconds+=time.process_time()-cpu_timer
        if self.calls%32==0:self.cost.check()
        return out

def anchors(p):
    # Deterministic farthest-point catalogue coverage; no weight/flux/old rate.
    selected=[int(np.argmin(p.ra))];best=1-p.eq_vectors@p.eq_vectors[selected[0]]
    for _ in range(min(24,p.n)-1):
        best[selected]=-1;idx=int(np.argmax(best));selected.append(idx)
        best=np.minimum(best,1-p.eq_vectors@p.eq_vectors[idx])
    return selected

def columns_at(p,geom,start,anchor_ids,ds=DURATIONS):
    base=geom.value(start,120);cols=[]
    for idx in anchor_ids:
        center=(float(base['alt'][idx]),float(base['az'][idx]))
        if not 0<=center[0]<=90:continue
        fibers,hit,_=p._classify(base['vectors'],*center)
        for d in ds:
            if start+timedelta(seconds=d)>p.nights[next(k for k,(a,b) in enumerate(p.nights) if a<=start<b)][1]:continue
            v=geom.value(start,d);target=np.flatnonzero(hit & v['eligible'])
            if not len(target):continue
            for pr in range(3):
                cols.append(dict(start=start.timestamp(),end=(start+timedelta(seconds=d)).timestamp(),
                    center=center,duration=int(d),program=pr,target=target.copy(),fiber=fibers[target].copy(),c=v['c'][pr,target].copy()))
    return cols

class Graph:
    def __init__(self,p,cols):
        self.p=p;self.cols=cols;self.na=len(cols)
        self.target=np.concatenate([c['target'] for c in cols]).astype(np.int32)
        self.score=np.concatenate([c['c'] for c in cols])
        self.edge_action=np.repeat(np.arange(self.na,dtype=np.int32),[len(c['target']) for c in cols])
        self.fiber=np.concatenate([c['fiber'] for c in cols]).astype(np.int32)
        self.ne=len(self.target)
        keys=self.edge_action*p.nfib+self.fiber
        self.cell_keys,self.cell=np.unique(keys,return_inverse=True);self.cell_action=self.cell_keys//p.nfib;self.nc=len(self.cell_keys)
        self.endpoints=np.unique(np.asarray([[c['start'],c['end']] for c in cols]).ravel());self.nt=len(self.endpoints)-1
        tr=[];tc=[]
        for e,c in enumerate(cols):
            left=int(np.searchsorted(self.endpoints,c['start']));right=int(np.searchsorted(self.endpoints,c['end']))
            tr.extend(range(left,right));tc.extend([e]*(right-left))
        self.time_row=np.asarray(tr,dtype=np.int32);self.time_action=np.asarray(tc,dtype=np.int32)
        rows=np.r_[self.target,p.n+self.cell,p.n+np.arange(self.nc),p.n+self.nc+self.time_row]
        cols_ix=np.r_[np.arange(self.ne),np.arange(self.ne),self.ne+self.cell_action,self.ne+self.time_action]
        data=np.r_[np.ones(self.ne*2),-np.ones(self.nc),np.ones(len(tr))]
        self.A=coo_matrix((data,(rows,cols_ix)),shape=(p.n+self.nc+self.nt,self.ne+self.na)).tocsr()
        self.rhs=np.r_[np.ones(p.n),np.zeros(self.nc),np.ones(self.nt)]
    def solve(self,b,blocked_until,cost,name):
        t=time.perf_counter();cpu=time.process_time();cost.check()
        gain=np.maximum(0.,self.score-b[self.target]);upper=np.r_[np.full(self.ne,np.inf),np.ones(self.na)]
        # x<=1 is already implied by cell capacity and y<=1; leave it implicit so
        # its redundant bound cannot absorb the economic capacity marginals.
        for e,c in enumerate(self.cols):
            if c['start']<blocked_until and c['end']>self.p.nights[0][0].timestamp():upper[self.ne+e]=0.
        lp=linprog(-np.r_[gain,np.zeros(self.na)],A_ub=self.A,b_ub=self.rhs,
            bounds=np.column_stack([np.zeros(self.ne+self.na),upper]),method='highs',
            options=dict(time_limit=max(.001,LIMIT-(time.perf_counter()-cost.start)),threads=1))
        cost.stages.append(dict(stage=name,wall_seconds=time.perf_counter()-t,cpu_seconds=time.process_time()-cpu,
            status=int(lp.status),success=bool(lp.success),iterations=int(lp.nit)))
        if not lp.success:raise CostStop('LP unfinished within cost gate: '+lp.message)
        cost.check()
        sigma=np.maximum(0.,-lp.ineqlin.marginals[:self.p.n])
        lam=np.maximum(0.,-lp.ineqlin.marginals[self.p.n+self.nc:])
        cell=np.zeros(self.nc);np.maximum.at(cell,self.cell,np.maximum(0.,gain-sigma[self.target]))
        price=np.bincount(self.cell_action,weights=cell,minlength=self.na)
        price-=np.bincount(self.time_action,weights=lam[self.time_row],minlength=self.na)
        dual=float(sigma.sum()+lam.sum()+np.maximum(0.,price).sum())
        value=float(-lp.fun);row=dict(value=value,dual_value=dual,dual_gap=dual-value,
            positive_target_prices=int(np.count_nonzero(sigma>1e-9)),positive_time_prices=int(np.count_nonzero(lam>1e-9)))
        # y<=0 branch dual requires the disabled columns excluded from closed form.
        if blocked_until<=self.p.nights[0][0].timestamp() and abs(dual-value)>1e-6:
            raise RuntimeError('Compact closed-form dual parity failed')
        return row,sigma,lam,lp.x
    def metadata(self):return dict(actions=self.na,target_edges=self.ne,nonempty_action_fibers=self.nc,
        time_atoms=self.nt,variables=self.ne+self.na,constraints=self.A.shape[0],nonzeros=self.A.nnz,
        sparse_bytes=self.A.data.nbytes+self.A.indices.nbytes+self.A.indptr.nbytes)

def score_action(p,geom,action,now):
    b=np.zeros(p.n)
    if action.get('action')!='observe':return b
    v=geom.value(now,int(action['duration_seconds']));pr=PROGRAMS.index(action['program'])
    fiber,hit,_=p._classify(v['vectors'],float(action['pointing']['alt_deg']),float(action['pointing']['az_deg']))
    for f,tid in action['assignments'].items():
        i=p.index[tid]
        if not(hit[i] and int(f)==int(fiber[i]) and v['eligible'][i]):raise RuntimeError('First-action geometry invalid')
        b[i]=v['c'][pr,i]
    return b

def pricing(p,geom,now,sigma,graph,lam,cost):
    t=time.perf_counter();cpu=time.process_time();base=geom.value(now,120);actions=[];seen=set()
    # Four declared fibre phases, across every currently visible catalogue target.
    for idx in np.flatnonzero(base['alt']>=p.min_alt):
        for f in (0,3,12,15):
            r,col=divmod(f,p.side);center=_shift_altaz(float(base['alt'][idx]),float(base['az'][idx]),
                -(r-(p.side-1)/2)*p.pitch,-(col-(p.side-1)/2)*p.pitch)
            if not 0<=center[0]<=90:continue
            key=tuple(round(float(x),7) for x in center)
            if key in seen:continue
            seen.add(key);fiber,hit,_=p._classify(base['vectors'],*center)
            for d in DURATIONS:
                v=geom.value(now,d);ids=np.flatnonzero(hit & v['eligible'])
                if not len(ids):continue
                occupied=(graph.endpoints[:-1]<now.timestamp()+d)&(graph.endpoints[1:]>now.timestamp())
                time_price=float(lam[occupied].sum())
                for pr in range(3):
                    g=v['c'][pr,ids];adjusted=g-sigma[ids];chosen=[];value=-time_price
                    for f2 in np.unique(fiber[ids]):
                        local=np.flatnonzero(fiber[ids]==f2);winner=local[int(np.argmax(adjusted[local]))]
                        if adjusted[winner]>=-1e-9 and g[winner]>0:
                            chosen.append(int(ids[winner]));value+=float(adjusted[winner])
                    if not chosen:continue
                    action=dict(action='observe',duration_seconds=d,program=PROGRAMS[pr],
                        pointing=dict(alt_deg=key[0],az_deg=key[1]%360),
                        assignments={str(int(fiber[i])):p.ids[i] for i in chosen})
                    actions.append((value,action))
    actions.sort(key=lambda row:(-row[0],digest(row[1])))
    selected=[];selected_hash=set()
    for value,action in actions:
        h=digest(action)
        if h in selected_hash:continue
        selected_hash.add(h);selected.append(dict(pricing_value=value,action=action))
        if len(selected)==2:break
    cost.stage('current_pricing_all_target_four_phases',t,cpu)
    return selected,dict(centers=len(seen),legal_complete_actions=len(actions),pricing_rule='reduced dual price; not action gain')

def run(world):
    cost=Cost();out=ROOT/'pilot'/world;out.mkdir(parents=True,exist_ok=True)
    result=dict(world=world,future_truth_used=False,host_truth_scoring=False,initial_only=True)
    try:
        t=time.perf_counter();cpu=time.process_time()
        initial=json.loads((ROOT/'public_inputs'/world/'initialize.json').read_text())
        actor=wrapper.wrapped(copy.deepcopy(initial));now=parse_utc(initial['survey']['start_utc'])
        snapshot=dict(now_utc=format_utc(now),survey_end_utc=initial['survey']['end_utc'],observe_action_index=0,
            active_requests=[],new_messages=[],latest_bulletin=None,latest_forecast=None,last_result=None,
            wallclock=dict(remaining_seconds=120.))
        B=actor.decide(copy.deepcopy(snapshot));p=actor.planner
        result.update(initial_sha256=digest(initial),public_snapshot_sha256=digest(snapshot),baseline_action=B,
            baseline_pending_sha256=digest(actor.pending),targets=p.n,nights=len(p.nights))
        if B['action']!='observe':raise RuntimeError('B does not observe at initial public state')
        cost.stage('public_initialization_and_original_B',t,cpu)
        geom=PublicGeometry(p,int(initial['survey']['slot_seconds']),cost);anchor=anchors(p)
        t=time.perf_counter();cpu=time.process_time();cols=[];start_set=set()
        for a,b in p.nights:
            for q in range(4):
                moment=a+(b-a)*q/4;moment=moment.replace(microsecond=0);start_set.add(moment.timestamp())
                cols.extend(columns_at(p,geom,moment,anchor))
        # B end is known without future truth and shared by all recourse branches.
        base_end=now+timedelta(seconds=int(B['duration_seconds']))
        if base_end.timestamp() not in start_set:
            cols.extend(columns_at(p,geom,base_end,anchor));start_set.add(base_end.timestamp())
        cost.stage('whole_calendar_public_geometry_and_columns',t,cpu)
        t=time.perf_counter();cpu=time.process_time();graph=Graph(p,cols);cost.stage('initial_sparse_graph_build',t,cpu)
        result['initial_graph']=graph.metadata()
        baseline_model,sigma,lam,_=graph.solve(np.zeros(p.n),now.timestamp(),cost,'initial_LP_and_dual')
        result['initial_LP']=baseline_model
        proposals,price_meta=pricing(p,geom,now,sigma,graph,lam,cost)
        result.update(pricing=price_meta,proposals=proposals,
            proposals_outside_B=[digest(x['action'])!=digest(B) for x in proposals])
        t=time.perf_counter();cpu=time.process_time()
        for prop in proposals:
            end=now+timedelta(seconds=prop['action']['duration_seconds'])
            if end.timestamp() not in start_set:
                cols.extend(columns_at(p,geom,end,anchor));start_set.add(end.timestamp())
        graph=Graph(p,cols);cost.stage('common_end_union_geometry_and_sparse_rebuild',t,cpu)
        result['common_graph']=graph.metadata();rows=[]
        candidates=[('B',B)]+[(f'priced{k}',r['action']) for k,r in enumerate(proposals)]+[
            ('y_current=0',dict(action='none',duration_seconds=0)),
            ('empty_B_duration',dict(action='none',duration_seconds=B['duration_seconds']))]
        for name,action in candidates:
            b=score_action(p,geom,action,now);blocked=now.timestamp()+action['duration_seconds']
            model,_,_,_=graph.solve(b,blocked,cost,f'common_recourse_{name}')
            row=dict(name=name,action=action,current_nominal_gain=float(b.sum()),future_LP_increment=model['value'],
                joint_nominal_LP_value=float(b.sum()+model['value']))
            rows.append(row);result['recourse']=rows
        baseline=rows[0]['joint_nominal_LP_value'];observes=[r for r in rows if r['action']['action']=='observe']
        # Preserve B for a model tie; no prediction of execution/official score.
        winner=observes[0]
        for r in observes[1:]:
            if r['joint_nominal_LP_value']>winner['joint_nominal_LP_value']+1e-7:winner=r
        result.update(selected=winner['name'],selected_action=winner['action'],
            selected_model_delta_vs_B=winner['joint_nominal_LP_value']-baseline,
            proxy_science_capacity_ceiling=float(np.sum(p.weight*np.maximum(p.multipliers.max(),p.mismatch))),
            geometry_cache=dict(entries=geom.calls,integration_pieces=geom.integration_pieces,
                wall_seconds=geom.wall_seconds,cpu_seconds=geom.cpu_seconds),
            status='completed',changed_first_action=winner['name']!='B')
        np.savez_compressed(out/'PUBLIC_NOMINAL_GRAPH.npz',target=graph.target,score=graph.score,edge_action=graph.edge_action,
            fiber=graph.fiber,starts=np.asarray([x['start'] for x in graph.cols]),ends=np.asarray([x['end'] for x in graph.cols]),
            sigma=sigma,time_dual=lam)
        cost.check()
    except CostStop as e:result.update(status='cost_stop',reason=str(e))
    except Exception as e:
        result.update(status='error',error_type=type(e).__name__,reason=str(e));dump(out/'RESULT.json',dict(**result,cost=cost.result()));raise
    result['cost']=cost.result();dump(out/'RESULT.json',result);print(json.dumps(dict(world=world,status=result['status'],
        wall_seconds=result['cost']['wall_seconds'],selected=result.get('selected'),reason=result.get('reason'))))
    return result

def official_operator_contracts():
    initial=json.loads((ROOT/'public_inputs/W90501/initialize.json').read_text())
    actor=wrapper.wrapped(copy.deepcopy(initial));p=actor.planner;cost=Cost();geom=PublicGeometry(p,900,cost)
    targets=[dict(zip(initial['targets']['columns'],r)) for r in initial['targets']['rows']]
    max_score=0.;max_alt=0.;cases=0
    for ni in (0,7,15,31):
        a,b=p.nights[ni]
        for duration in (120,1800,3600):
            start=a+(b-a)/4;start=start.replace(microsecond=0);end=start+timedelta(seconds=duration)
            v=geom.value(start,duration);C,E=v['C'],v['E'];slots=[]
            cursor=a;slot_index=0
            while cursor<b:
                piece_end=min(b,cursor+timedelta(seconds=900))
                slots.append(SlotTruth(str(slot_index),cursor,piece_end,True,1.,C*p.q0,1.,E))
                cursor=piece_end;slot_index+=1
            weather=WeatherTruth(slots,None);segments=list(weather.segments(start,end))
            for i in np.flatnonzero(v['eligible'])[:2]:
                i=int(i);target=targets[i]
                altaz=lambda moment:radec_to_altaz(float(p.ra[i]),float(p.dec[i]),moment,p.lat,p.lon)
                alt=lambda moment:altaz(moment)[0]
                lunar=lambda moment:lunar_quality_factor(float(p.ra[i]),float(p.dec[i]),moment,initial['site'],initial['scoring'])
                qband=weather.band_quality(start,end,initial['scoring'],alt,lunar)
                band=program_band(qband,initial['scoring'])
                exact_alt=min_altitude_during(float(p.ra[i]),float(p.dec[i]),start,end,dict(site=initial['site']))
                max_alt=max(max_alt,abs(exact_alt-float(v['min_alt'][i])))
                for pr in range(3):
                    mult=program_multiplier(PROGRAMS[pr],band,initial['scoring'])
                    scored=score_target_exposure(target,segments,[],weather,duration,mult,initial['scoring'],start,altaz,initial['site'])
                    max_score=max(max_score,abs(scored.score-float(v['c'][pr,i])));cases+=1
    if max_score>1e-9 or max_alt>2e-7:raise RuntimeError('Official synthetic operator parity failed')
    dump(ROOT/'OFFICIAL_SYNTHETIC_OPERATOR_CONTRACTS.json',dict(cases=cases,max_science_error=max_score,
        max_minimum_altitude_error_deg=max_alt,all_passed=True,real_world_truth_used=False,
        fixture='explicit deterministic seasonal C/E synthetic SlotTruth; public geometry'))

def finite_contracts():
    rng=np.random.default_rng(20261004999);rows=[]
    for case in range(32):
        n=3;na=3;g=rng.uniform(.01,3,(na,n));baseline=rng.uniform(0,.5,n)
        g=np.maximum(g-baseline,0.);fiber=rng.integers(0,2,(na,n));dur=np.asarray([1,1,2]);start=np.asarray([0,1,0]);end=start+dur
        # Independent exhaustive physical action/assignment and official max ledger arithmetic.
        physical=0.
        for mask in range(1<<na):
            active=[e for e in range(na) if mask>>e&1]
            if any(start[e]<end[f] and start[f]<end[e] for e,f in itertools.combinations(active,2)):continue
            cells=[(e,f,np.flatnonzero(fiber[e]==f).tolist()) for e in active for f in (0,1)]
            for choice in itertools.product(*[[-1]+ids for e,f,ids in cells]):
                scores=np.zeros(n)
                for (e,f,ids),i in zip(cells,choice):
                    if i>=0:scores[i]=max(scores[i],g[e,i])
                physical=max(physical,float(scores.sum()))
        # Compact LP built independently for the tiny domain.
        E=na*n;A=np.zeros((n+na*2+2,E+na));b=np.r_[np.ones(n),np.zeros(na*2),np.ones(2)]
        for e in range(na):
            for i in range(n):
                A[i,e*n+i]=1;A[n+e*2+fiber[e,i],e*n+i]=1
            for f in (0,1):A[n+e*2+f,E+e]=-1
            for j in range(start[e],end[e]):A[n+na*2+j,E+e]=1
        compact=linprog(-np.r_[g.ravel(),np.zeros(na)],A_ub=A,b_ub=b,bounds=(0,1),method='highs')
        thresholds=[np.unique(g[:,i][g[:,i]>0]) for i in range(n)];layers=[(i,t) for i in range(n) for t in thresholds[i]]
        AL=np.zeros((na*2+2+len(layers),E+na+len(layers)));AL[:na*2+2,:E+na]=A[n:]
        BL=np.r_[b[n:],np.zeros(len(layers))];weights=[]
        for j,(i,t) in enumerate(layers):
            for e in range(na):
                if g[e,i]>=t:AL[na*2+2+j,e*n+i]=-1
            AL[na*2+2+j,E+na+j]=1
            prev=max([x for x in thresholds[i] if x<t],default=0);weights.append(t-prev)
        layer=linprog(-np.r_[np.zeros(E+na),weights],A_ub=AL,b_ub=BL,bounds=(0,1),method='highs')
        if not(compact.success and layer.success):raise RuntimeError('Tiny LP failed')
        # Integer y: independent exhaustive physical optimum equals winner matching LP optimum.
        compact_ip=0.
        for mask in range(1<<na):
            upper=np.r_[np.ones(E),[(mask>>e)&1 for e in range(na)]]
            lower=np.r_[np.zeros(E),upper[E:]]
            lp=linprog(-np.r_[g.ravel(),np.zeros(na)],A_ub=A,b_ub=b,bounds=np.c_[lower,upper],method='highs')
            if lp.success:compact_ip=max(compact_ip,float(-lp.fun))
        row=dict(case=case,physical_best=physical,compact_IP=compact_ip,compact_LP=float(-compact.fun),layer_LP=float(-layer.fun))
        if abs(physical-compact_ip)>1e-8 or abs(compact.fun-layer.fun)>1e-8 or -compact.fun+1e-8<physical:
            raise RuntimeError('Onebest contract failed '+str(row))
        rows.append(row)
    dump(ROOT/'FINITE_CONTRACTS.json',dict(cases=rows,all_passed=True,exact_layers_no_quantization=True,
        proof_scope='fixed c, science only; not REQ/required/Jain/rank/loss'))
    print(json.dumps(dict(finite_contracts=len(rows),all_passed=True)))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--world');parser.add_argument('--contracts',action='store_true');args=parser.parse_args()
    if args.contracts:
        finite_contracts();official_operator_contracts()
    elif args.world:run(args.world)
    else:raise ValueError('Specify an independent world or contracts')

if __name__=='__main__':main()
