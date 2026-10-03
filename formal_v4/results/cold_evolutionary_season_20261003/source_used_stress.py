#!/usr/bin/env python3
"""Independent full-season population search; public LOCAL truth only.

Independent derivation: max science and required coverage are set coupled; request
quota rewards and Jain create nonlocal effects, while retrospective loss makes
the validity of even unchanged exposures depend on the complete prefix action
count. A genotype is a set of absolute-time exposure columns, ordered only on
execution. Night-block crossover and interval repair produce legal whole seasons.

Reused engineering after independent derivation: cold_global_incumbent.Oracle's
official-mesh vector integration and already generated L1/L2 candidate columns.
Population, crossover, diversity, full loss model, and fair ablation are new here.
No production policy or platform truth is read or modified.
"""
from __future__ import annotations
import argparse,bisect,csv,hashlib,json,math,os,pickle,sys,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'upstream/gosim-observer-examples/runner'))
import cold_global_incumbent as old
from challenge.v4_runner import load_scenario,run_scenario,_data_loss_plan,_pointing_offset
from challenge.v4_fiber_map import min_altitude_during,radec_to_altaz
from challenge.v4_scorer import score_target_exposure,lunar_quality_factor,program_band,program_multiplier

OUT=ROOT/'results/cold_evolutionary_season_20261003'
SOURCES={'L1':ROOT/'results/gpu_direct_20261003/L1','L2':ROOT/'results/gpu_phase_followup_20261003/phase/L2','L3':ROOT/'runs/cpu_calendar_witness_20261003/L3','L4':ROOT/'runs/cpu_calendar_witness_20261003/L4'}
def utc(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
def stamp(t):return t.strftime('%Y-%m-%dT%H:%M:%SZ')
def dump(path,obj):path.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')
def actionkey(c):return (c['start'],c['end'],json.dumps(c['action'],sort_keys=True,separators=(',',':')))

class StressOracle(old.Oracle):
    """Extends verified mesh integration to official stress pointing geometry."""
    def __init__(self,s,reports):
        super().__init__(s,reports);self.offset=_pointing_offset(s)
    def row(self,start,end,action,exact_native=False):
        if not exact_native:return super().row(start,end,action,False)
        ids=np.full(16,self.n,np.int32);g=np.zeros(16);scores=np.zeros(16)
        events=[e for e in self.directional if e.overlaps(start,end)]
        for f,tid in action['assignments'].items():
            i=self.idxs[tid];t=self.s.targets[i]
            hit=self.grid.classify_target(t['ra_deg'],t['dec_deg'],start,action['pointing']['alt_deg'],action['pointing']['az_deg'],self.lat,self.lon,*self.offset)
            if hit.region!='glass' or hit.fiber_id!=int(f) or min_altitude_during(t['ra_deg'],t['dec_deg'],start,end,self.s.config)<self.s.minimum_altitude_deg:continue
            fn=lambda moment,t=t:radec_to_altaz(t['ra_deg'],t['dec_deg'],moment,self.lat,self.lon)
            bq=self.weather.band_quality(start,end,self.cfg,lambda moment:fn(moment)[0],lambda moment,t=t:lunar_quality_factor(t['ra_deg'],t['dec_deg'],moment,self.s.site,self.cfg))
            mult=program_multiplier(action['program'],program_band(bq,self.cfg),self.cfg)
            sc=score_target_exposure(t,list(self.weather.segments(start,end)),events,self.weather,int((end-start).total_seconds()),mult,self.cfg,start,fn,self.s.site)
            ids[int(f)]=i;g[int(f)]=sc.factor;scores[int(f)]=sc.score
        bits=self.request_bits(start,end,ids,g)
        return {'start':int(start.timestamp()),'end':int(end.timestamp()),'ids':ids,'g':g,'scores':scores,'bits':bits,'action':action}
    def request_bits(self,start,end,ids,g):
        ans=[]
        for r,ri in zip(self.s.observation_requests,self.request_ids):
            mask=0
            if r['issued_at_utc']<=start and end<=r['deadline_utc']:
                for j,i in enumerate(ri):
                    if np.any((ids==i)&(g>=r['completion_factor_threshold'])):mask|=1<<j
            ans.append(mask)
        return ans
    def candidates(self,*args,**kwargs):
        # Parent generator builds an ACTUAL field at the anchor. Translate it to
        # the known local-truth command; exposure-start classification is exact.
        for c in super().candidates(*args,**kwargs):
            a=c['action'];a['pointing']['alt_deg']-=self.offset[0];a['pointing']['az_deg']=(a['pointing']['az_deg']-self.offset[1])%360
            if 0<=a['pointing']['alt_deg']<=90:yield c

class Season:
    def __init__(self,s,cols,report,rng):
        self.s,self.cols,self.rng=s,cols,rng;self.n=len(s.targets);self.report=report
        self.start=np.array([c['start'] for c in cols],np.int64);self.end=np.array([c['end'] for c in cols],np.int64)
        self.atoms=np.unique(np.concatenate((self.start,self.end)));self.lo=np.searchsorted(self.atoms,self.start);self.hi=np.searchsorted(self.atoms,self.end)
        self.ids=np.array([c['ids'] for c in cols]);self.scores=np.array([c['scores'] for c in cols]);self.g=np.array([c['g'] for c in cols]);self.bits=np.array([c['bits'] for c in cols],np.int64)
        self.required=np.array([t['required'] for t in s.targets]+[False]);self.penalty=s.score_config['required']['penalty_per_missing'];self.rth=s.score_config['required']['observed_factor_threshold'];self.uth=s.score_config['uniformity']['observed_factor_threshold']
        bands=np.array([int(t['ra_deg']//s.score_config['uniformity']['ra_band_width_deg']) for t in s.targets]);_,self.binv,self.btotal=np.unique(bands,return_inverse=True,return_counts=True)
        nights={}
        for x in s.slots:nights.setdefault(x.slot_id.split('-S')[0],[int(x.start_utc.timestamp()),int(x.end_utc.timestamp())])[1]=int(x.end_utc.timestamp())
        self.nights=list(nights.values());self.night=np.searchsorted([a for a,b in self.nights],self.start,side='right')-1
        self.pools=[np.flatnonzero(self.night==k) for k in range(len(self.nights))];self.loss=_data_loss_plan(s)
    def ordered(self,sel):return sorted(set(map(int,sel)),key=lambda a:(self.start[a],self.end[a],a))
    def valid(self,sel):
        sel=self.ordered(sel)
        if self.loss is None:return sel,None
        n=int(sum(self.start[a]<self.loss.trigger_utc.timestamp() for a in sel))
        lo=math.floor(self.loss.window_start_fraction*n);hi=math.floor(self.loss.window_end_fraction*n)
        return sel[:lo]+sel[hi:],{'action_count_at_trigger':n,'start':lo,'end_exclusive':hi,'invalidated_actions':hi-lo}
    def state(self,sel):
        best=np.zeros(self.n+1);g=np.zeros(self.n+1);occ=np.zeros(len(self.atoms),bool)
        for a in sel:occ[self.lo[a]:self.hi[a]]=True
        valid,loss=self.valid(sel)
        if valid:
            ix=np.asarray(valid);np.maximum.at(best,self.ids[ix].ravel(),self.scores[ix].ravel());np.maximum.at(g,self.ids[ix].ravel(),self.g[ix].ravel());bits=np.bitwise_or.reduce(self.bits[ix],axis=0)
        else:bits=np.zeros(len(self.s.observation_requests),np.int64)
        return best,g,occ,bits,loss
    def objective(self,sel):
        best,g,_,bits,loss=self.state(sel);missing=int((self.required&(g<self.rth)).sum())
        ratios=np.bincount(self.binv,weights=g[:self.n]>=self.uth)/self.btotal;den=ratios@ratios;jain=ratios.sum()**2/(len(ratios)*den) if den else 0.
        completed=[int(b).bit_count()>=r['minimum_completed'] for r,b in zip(self.s.observation_requests,bits)]
        requests=sum(r['completion_reward'] for r,v in zip(self.s.observation_requests,completed) if v);uniform=self.s.score_config['uniformity']['weight']*(1-jain)
        return {'total':float(best.sum()-self.penalty*missing-uniform+requests+self.report),'science':float(best.sum()),'required_missing':missing,'uniformity_penalty':float(uniform),'request_reward':float(requests),'requests_completed':sum(completed),'report_settlement':self.report,'observe_actions':len(sel),'loss':loss}
    def legal(self,sel):
        end=-1
        for a in self.ordered(sel):
            if self.start[a]<end:return False
            n=self.night[a]
            if n<0 or self.start[a]<self.nights[n][0] or self.end[a]>self.nights[n][1] or not 60<=self.end[a]-self.start[a]<=3600:return False
            end=self.end[a]
        return True
    def normalize(self,sel):
        # Absolute-time repair: deterministic earliest-ending interval packing.
        keep=[];end=-1
        for a in sorted(set(sel),key=lambda a:(self.end[a],self.start[a])):
            n=self.night[a]
            if n>=0 and self.start[a]>=max(end,self.nights[n][0]) and self.end[a]<=self.nights[n][1] and 60<=self.end[a]-self.start[a]<=3600:keep.append(a);end=self.end[a]
        return keep
    def repair(self,retained,nights,noise=.08,mode='complete'):
        sel=self.normalize(retained);best,g,occ,bits,_=self.state(sel)
        pool=np.concatenate([self.pools[int(k)] for k in sorted(set(nights))]) if len(nights) else np.array([],int)
        while len(pool):
            prefix=np.concatenate(([0],np.cumsum(occ)));pool=pool[(prefix[self.hi[pool]]-prefix[self.lo[pool]])==0]
            if not len(pool):break
            ids=self.ids[pool];sg=self.scores[pool];gg=self.g[pool]
            gain=np.maximum(sg-best[ids],0).sum(axis=1)
            if mode!='science':
                gain+=self.penalty*((g[ids]<self.rth)&(gg>=self.rth)&self.required[ids]).sum(axis=1)
                for r,oldb,newb in zip(self.s.observation_requests,bits,self.bits[pool].T):
                    count=int(oldb).bit_count()
                    if count<r['minimum_completed']:
                        fresh=np.fromiter((int(x&~int(oldb)).bit_count() for x in newb),int,len(newb));gain+=r['completion_reward']*np.minimum(fresh,r['minimum_completed']-count)/r['minimum_completed']
                # Smooth repair heuristic for Jain, terminal objective remains exact.
                ratios=np.bincount(self.binv,weights=g[:self.n]>=self.uth)/self.btotal
                deficit=np.maximum(ratios.mean()-ratios,0);band=np.zeros(self.n+1);band[:self.n]=deficit[self.binv]*self.s.score_config['uniformity']['weight']/self.btotal[self.binv]
                gain+=(band[ids]*((g[ids]<self.uth)&(gg>=self.uth))).sum(axis=1)
            gain/=np.sqrt((self.end[pool]-self.start[pool]).astype(float)) if mode=='science' else self.end[pool]-self.start[pool]
            if gain.max()<=1e-12:break
            priority=gain*np.exp(self.rng.normal(0,noise,len(pool))) if noise else gain
            a=int(pool[np.argmax(priority)]);sel.append(a);occ[self.lo[a]:self.hi[a]]=True
            np.maximum.at(best,self.ids[a],self.scores[a]);np.maximum.at(g,self.ids[a],self.g[a]);bits|=self.bits[a]
        return self.ordered(sel)
    def mutate(self,parent):
        op=str(self.rng.choice(['night','range','related'],p=[.65,.25,.10]));alln=len(self.nights)
        if op=='night':
            width=min(alln,int(self.rng.choice([1,2,4,8],p=[.68,.22,.08,.02])));nights=self.rng.choice(alln,width,replace=False);retained=[a for a in parent if self.night[a] not in nights]
        elif op=='range':
            k=int(self.rng.integers(alln));aa=[a for a in parent if self.night[a]==k]
            if aa:
                chosen=int(self.rng.choice(aa));left=self.start[chosen];right=left+int(self.rng.choice([300,900,1800,3600]));retained=[a for a in parent if not(self.night[a]==k and self.start[a]<right and self.end[a]>left)]
            else:retained=list(parent)
            nights=[k]
        else:
            _,g,_,_,_=self.state(parent);ratios=np.bincount(self.binv,weights=g[:self.n]>=self.uth)/self.btotal;k=int(np.argmin(ratios));targets=set(np.flatnonzero(self.binv==k));affected=[a for a in parent if any(int(i) in targets for i in self.ids[a])]
            if affected:
                drop=set(self.rng.choice(affected,min(12,len(affected)),replace=False));nights=np.unique(self.night[list(drop)]);retained=[a for a in parent if a not in drop]
            else:nights=[int(self.rng.integers(alln))];retained=list(parent)
        return self.repair(retained,nights,float(self.rng.choice([0,.03,.12,.3]))),op
    def crossover(self,a,b):
        # Whole-night genes preserve each parent's timing; following destruction
        # admits different action counts/durations. No action indices are inherited.
        n=len(self.nights);k=int(self.rng.integers(n));width=min(n,int(self.rng.choice([1,2,4,8],p=[.2,.3,.3,.2])));ns=set((k+j)%n for j in range(width))
        child=[x for x in a if self.night[x] not in ns]+[x for x in b if self.night[x] in ns]
        return self.normalize(child)
    def distance(self,a,b):
        aa,bb=set(a),set(b);return len(aa^bb)/max(1,len(aa|bb))
    def archive(self,pop,new,size=20):
        # Score elite plus distance-filtered archive. Distinct exposure schedules
        # with lower current score can survive to provide useful crossover blocks.
        seen={};
        for p,o in pop+[new]:
            key=tuple(p)
            if key not in seen or o['total']>seen[key][1]['total']:seen[key]=(p,o)
        ordered=sorted(seen.values(),key=lambda x:x[1]['total'],reverse=True);out=ordered[:2]
        for x in ordered[2:]:
            if len(out)>=size:break
            if min(self.distance(x[0],y[0]) for y in out)>=.025:out.append(x)
        if len(out)<min(6,len(ordered)):
            for x in ordered:
                if all(x[0]!=y[0] for y in out):out.append(x)
                if len(out)>=min(6,len(ordered)):break
        return out
    def search(self,seeds,seconds,method,out):
        start=time.monotonic();pop=[(self.ordered(x),self.objective(x)) for x in seeds];pop=sorted(pop,key=lambda x:x[1]['total'],reverse=True);best,bobj=pop[0];current,cobj=best,bobj
        history=[{'elapsed':0,'iteration':0,**bobj}];stats={};iters=0;cross=0
        export(self.cols,best,out/'best_actions.jsonl');dump(out/'best_model.json',bobj)
        while time.monotonic()-start<seconds:
            if method=='ga':
                ix=self.rng.choice(len(pop),min(3,len(pop)),replace=False);parent,pobj=max((pop[int(k)] for k in ix),key=lambda x:x[1]['total'])
                if len(pop)>1 and self.rng.random()<.55:
                    mate=pop[int(self.rng.integers(len(pop)))][0];parent=self.crossover(parent,mate);cross+=1
                trial,op=self.mutate(parent)
            else:trial,op=self.mutate(current)
            if not self.legal(trial):raise RuntimeError('illegal interval repair')
            obj=self.objective(trial);iters+=1;stats.setdefault(op,{'tries':0,'best_improvements':0});stats[op]['tries']+=1
            if obj['total']>bobj['total']+1e-9:
                best,bobj=trial,obj;stats[op]['best_improvements']+=1;rec={'elapsed':time.monotonic()-start,'iteration':iters,'operator':op,**obj};history.append(rec);print(json.dumps({'improved':rec}),flush=True);export(self.cols,best,out/'best_actions.jsonl');dump(out/'best_model.json',bobj)
            if method=='ga':pop=self.archive(pop,(trial,obj))
            elif obj['total']>=cobj['total'] or self.rng.random()<math.exp(max(-700,(obj['total']-cobj['total'])/.3)):current,cobj=trial,obj
            if iters%100==0:
                div=float(np.mean([self.distance(pop[0][0],x[0]) for x in pop[1:]])) if len(pop)>1 else 0
                rec={'pid':os.getpid(),'method':method,'elapsed':time.monotonic()-start,'iterations':iters,'crossovers':cross,'population':len(pop),'diversity_to_elite':div,'best':bobj,'operators':stats};dump(out/'progress.json',rec);print(json.dumps({'progress':rec}),flush=True)
        dump(out/'history.json',history);dump(out/'population.json',[{'objective':o,'selected':p} for p,o in pop]);return best,bobj,{'iterations':iters,'elapsed_seconds':time.monotonic()-start,'crossovers':cross,'operators':stats}

def export(cols,sel,path):
    plan=[{'start_utc':stamp(datetime.fromtimestamp(cols[a]['start'],timezone.utc)),**cols[a]['action']} for a in sorted(sel,key=lambda a:cols[a]['start'])];path.write_text(''.join(json.dumps(a,separators=(',',':'))+'\n' for a in plan));return plan

def replay(path,s,plan,reports,out):
    return old.replay_plan(path,s,plan,reports,out)

def load_or_build(card,out,anchors=2):
    src=SOURCES[card];sp=ROOT/'upstream/gosim-observer-examples/local-cards'/card/'config/v4_scenario.json';s=load_scenario(sp)
    decisions=list(csv.DictReader((src/'decisions.csv').open()));actions=[json.loads(x) for x in (src/'actions.jsonl').read_text().splitlines()];observe=[a for a in actions if a['action']=='observe'];rows=[r for r in decisions if r['action']=='observe'];reports=[utc(r['start_utc']) for r in decisions if r['action']=='report'];expected=json.loads((src/'score_report.json').read_text())
    cached=OUT/card/'pool.pkl';manifest=OUT/card/'pool_manifest.json';OUT.joinpath(card).mkdir(parents=True,exist_ok=True)
    source_hash=hashlib.sha256((src/'actions.jsonl').read_bytes()).hexdigest()
    if cached.exists() and manifest.exists() and json.loads(manifest.read_text())['source_actions_sha256']==source_hash:
        cols,initial=pickle.loads(cached.read_bytes());return s,sp,cols,initial,reports,expected
    o=StressOracle(s,reports);rng=np.random.default_rng(1003);cols=[];initial=[]
    if card in ('L1','L2'):
        oldcache=ROOT/'results/cold_global_search_20261003'/f'continuous_{card}/columns_a3_s407.pkl';loaded=pickle.loads(oldcache.read_bytes());cols,initial=loaded[:2];print(json.dumps({'reused_columns':str(oldcache),'count':len(cols)}),flush=True)
    else:
        for j,(r,a) in enumerate(zip(rows,observe)):
            cols.append(o.row(utc(r['start_utc']),utc(r['end_utc']),a,True));initial.append(len(cols)-1)
        best=np.zeros(o.n+1);g=np.zeros(o.n+1)
        for c in cols:np.maximum.at(best,c['ids'],c['scores']);np.maximum.at(g,c['ids'],c['g'])
        nights={}
        for slot in s.slots:nights.setdefault(slot.slot_id.split('-S')[0],[slot.start_utc,slot.end_utc])[1]=slot.end_utc
        # Starts deliberately differ from the incumbent: published 900s slot
        # edges, plus actual request issue/deadline boundaries and one midpoint.
        starts={x.start_utc for x in s.slots if x.is_observable}
        for r in s.observation_requests:starts.add(r['issued_at_utc'])
        for j,t in enumerate(sorted(starts)):
            nb=next((b for a,b in nights.values() if a<=t<b),None)
            if nb is None:continue
            alt,_=old.m.altaz(o.ra,o.dec,t,o.lat,o.lon);visible=np.flatnonzero(alt>=31)
            if not len(visible):continue
            deficit=visible[o.required[visible]&(g[visible]<.5)];req=np.array([i for r,ii in zip(s.observation_requests,o.request_ids) if r['issued_at_utc']<=t<r['deadline_utc'] for i in ii if alt[i]>=31],int)
            aa=[]
            for pool in (req,deficit,visible):
                if len(pool):aa.append((int(rng.choice(pool)),rng.choice([-1.5,-.5,.5,1.5],2)))
                if len(aa)>=anchors:break
            cols.extend(o.candidates(t,nb,aa,best,g,None))
            if j%100==0:print(json.dumps({'build_start':j,'starts':len(starts),'columns':len(cols)}),flush=True)
    # Add the current strong oracle plan as an intact third source if available.
    optimized=ROOT/'results/cold_global_search_20261003'/f'continuous_{card}/optimized_actions.jsonl'
    if optimized.exists():
        lookup={actionkey(c):i for i,c in enumerate(cols)};strong=[]
        for line in optimized.read_text().splitlines():
            z=json.loads(line);t=utc(z.pop('start_utc'));en=t+timedelta(seconds=z['duration_seconds']);c=o.row(t,en,z,True);key=actionkey(c)
            if key not in lookup:lookup[key]=len(cols);cols.append(c)
            strong.append(lookup[key])
        dump(OUT/card/'strong_seed.json',strong)
    cached.write_bytes(pickle.dumps((cols,initial)));dump(manifest,{'source_actions_sha256':source_hash,'source':str(src),'candidate_count':len(cols),'local_truth_oracle':True,'offset_deg':o.offset,'reports':'fixed original report times','new_start_support':'all observable slot edges and request issue timestamps for stress cards; inherited continuous candidate support for L1/L2','anchors':anchors})
    return s,sp,cols,initial,reports,expected

def prepare(card,out,anchors):
    s,sp,cols,initial,reports,expected=load_or_build(card,out,anchors);search=Season(s,cols,sum(json.loads((SOURCES[card]/'score_report.json').read_text())['components'][k] for k in ['report_settlement']),np.random.default_rng(203))
    model=search.objective(initial);plan=export(cols,initial,out/'baseline_plan.jsonl');native=replay(sp,s,plan,reports,out/'baseline_native')
    gate={'expected_total':expected['total'],'native_total':native['total'],'model_total':model['total'],'native_matches_source':native['total']==expected['total'],'model_abs_error':abs(model['total']-native['total']),'loss':model['loss'],'native_invalidations':native['invalidations']};dump(out/'baseline_gate.json',gate);print(json.dumps({'gate':gate}),flush=True)
    if not gate['native_matches_source'] or gate['model_abs_error']>1e-5:raise RuntimeError('official source gate failed')
    seeds=[initial];sources=['unmodified strong production']
    strong=OUT/card/'strong_seed.json'
    if strong.exists():seeds.append(json.loads(strong.read_text()));sources.append('latest official replayed full-season oracle LNS')
    for mode,noise in [('science',.2),('complete',.10)]:
        t=time.monotonic();sel=[]
        # These are independently built trajectories: randomized NIGHT order
        # schedules all the season from an empty ledger with no inherited visits.
        order=search.rng.permutation(len(search.nights))
        for night in order:sel=search.repair(sel,[int(night)],noise,mode)
        seeds.append(sel);sources.append('independent empty-season '+mode+' construction');print(json.dumps({'seed_source':sources[-1],'night_order':order.tolist(),'construction_seconds':time.monotonic()-t,'objective':search.objective(sel)}),flush=True)
    dump(OUT/card/'seeds.json',seeds);dump(out/'seed_objectives.json',[{'source':name,'objective':search.objective(sel)} for name,sel in zip(sources,seeds)])
    return s,sp,cols,seeds,reports,expected

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--card',choices=list(SOURCES),default='L1');ap.add_argument('--method',choices=['prepare','ga','local'],default='ga');ap.add_argument('--seconds',type=float,default=600);ap.add_argument('--seed',type=int,default=411);ap.add_argument('--anchors',type=int,default=2);args=ap.parse_args()
    out=OUT/args.card/args.method;out.mkdir(parents=True,exist_ok=True);dump(out/'run_state.json',{'pid':os.getpid(),'stage':'starting','args':vars(args),'time_utc':stamp(datetime.now(timezone.utc))});print(json.dumps({'pid':os.getpid(),'args':vars(args)}),flush=True)
    t=time.monotonic()
    if args.method=='prepare':
        s,sp,cols,seeds,reports,expected=prepare(args.card,out,args.anchors);dump(out/'run_state.json',{'pid':os.getpid(),'stage':'prepared','seconds':time.monotonic()-t,'columns':len(cols)});return
    s,sp,cols,initial,reports,expected=load_or_build(args.card,out,args.anchors);seeds=json.loads((OUT/args.card/'seeds.json').read_text());search=Season(s,cols,expected['components']['report_settlement'],np.random.default_rng(args.seed));baseline=max((search.objective(x) for x in seeds),key=lambda x:x['total'])
    dump(out/'run_state.json',{'pid':os.getpid(),'stage':'search','columns':len(cols),'args':vars(args),'baseline':baseline})
    best,obj,stats=search.search(seeds,args.seconds,args.method,out);plan=export(cols,best,out/'optimized_actions.jsonl');native=replay(sp,s,plan,reports,out/'optimized_native')
    result={'scope':'public local-card clairvoyant full-season finite candidate population experiment','method':args.method,'seconds':args.seconds,'seed':args.seed,'columns':len(cols),'initial_best':baseline,'optimized_model':obj,'native':native,'native_model_abs_error':abs(native['total']-obj['total']),'delta_vs_production':native['total']-expected['total'],'delta_vs_initial_best':native['total']-baseline['total'],'statistics':stats,'limitations':['finite sampled columns; no global optimality certificate','report times fixed to unmodified production replay','L3/L4 exact loss count and local-truth offset; not online deployable','initial empty-season paths share candidate pool but do not inherit existing schedules']};dump(out/'summary.json',result);dump(out/'run_state.json',{'pid':os.getpid(),'stage':'complete','native_total':native['total'],'model_error':result['native_model_abs_error']});print(json.dumps({k:v for k,v in result.items() if k!='native'}),flush=True)

if __name__=='__main__':main()
