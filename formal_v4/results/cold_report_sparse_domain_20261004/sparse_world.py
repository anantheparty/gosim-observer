"""CPU host independent worlds under fixed *public* physical sampling designs."""
from __future__ import annotations
import copy,json,pickle,sys,time,hashlib,math
from pathlib import Path
import numpy as np
from public_design import ROOT,OFFICIAL,utc
from sensor_core import score_token,BASE_DIM,HISTORY
from challenge.v4_weather_simulator import generate_events,generate_weather,generate_bulletins,generate_forecasts,generate_stress_events
from challenge.v4_fiber_map import FiberGrid
KINDS=['earthquake','overcast','haze','cold_snap','rain','storm','rocket_launch','terrain_obstruction']
DIRECTIONS={k:45*j for j,k in enumerate(['N','NE','E','SE','S','SW','W','NW'])}
TOKEN_DIM=BASE_DIM+3*len(KINDS)+4
TAIL_DIM=8+3*len(KINDS)+len(KINDS)
XDIM=8*TOKEN_DIM+16+TAIL_DIM
_designs=None
def designs():
    global _designs
    if _designs is None:
        with (ROOT/'public_design_cache.pkl').open('rb') as f:_designs=pickle.load(f)
    return _designs
def season(day):
    a=math.sin(2*math.pi*(day-210)/365.2425);return (.88-.07*a)*(1-.12*a)/((1.1+.15*a)*.68)
def notice_features(notices,az):
    rows=[]
    for kind in KINDS:
        items=[n for n in notices if n['event_kind']==kind]
        allscope=any(n['direction']=='ALL' for n in items)
        cosine=max([math.cos(math.radians((az-DIRECTIONS[n['direction']]+180)%360-180)) for n in items if n['direction'] in DIRECTIONS],default=-1.)
        rows.extend([float(bool(items)),float(allscope),cosine if items else -1.])
    return np.asarray(rows)
def sector(az,start,end):return (az>=start)&(az<=end) if start<=end else (az>=start)|(az<=end)

class World:
    def __init__(self,seed,card=None):
        self.seed=seed;self.card=card or ['L1','L2'][seed%2];self.design=designs()[self.card];d=self.design
        cfg=json.loads((OFFICIAL/'challenge/reference/v4/v4_weather_config.json').read_text());cfg['seed']=int(seed);cfg['seed_derivation']='sha256-v1'
        rng=np.random.default_rng(seed+777)
        cfg['instrument_fault']['count']=int(rng.choice([0,1,2],p=[.25,.5,.25]));cfg['earthquake']['count']=int(rng.integers(0,3))
        for definition in cfg['weather_events']['conditions'].values():definition['count']=int(rng.integers(0,4))
        self.events,self.effects=generate_events(cfg,d['nights'],d['slots'])
        cfg['stress_tests']['enabled']=True
        self.stress=generate_stress_events(cfg,self.events)
        offset=next(x for x in self.stress if x['event_type']=='pointing_offset')
        self.offset=(math.degrees(float(offset['alt_offset_rad'])),math.degrees(float(offset['az_offset_rad'])))
        self.rows=generate_weather(cfg,d['nights'],d['slots'],self.events,self.effects)
        self.bulletins=[json.loads(s) for s in generate_bulletins(cfg,d['nights'],d['slots'],self.events,self.effects)]
        self.forecasts=[json.loads(s) for s in generate_forecasts(cfg,d['nights'],self.events)]
        self.cc=np.zeros(len(self.rows));self.eff=np.zeros(len(self.rows))
        for i,r in enumerate(self.rows):
            if r['is_observable']=='true':self.cc[i]=float(r['transparency'])*float(r['sky_quality'])/(float(r['seeing_arcsec'])*.68);self.eff[i]=float(r['instrument_efficiency'])
        self.faults=[e for e in self.events if e.event_type=='instrument_fault'];self.geometry=[]
        grid=FiberGrid(float(d['initial']['instrument']['fiber_area_deg2']),float(d['initial']['instrument']['gap_deg']),16)
        lat=float(d['initial']['site']['latitude_deg']);lon=float(d['initial']['site']['longitude_deg'])
        for original in d['actions']:
            from datetime import datetime,timezone
            hits=grid.assigned_hits(dict(zip(original['fibers'],original['target_ids'])),dict(zip(original['target_ids'],zip(original['ra'],original['dec']))),datetime.fromtimestamp(original['start'],timezone.utc),*original['pointing'],lat,lon,*self.offset)
            mask=np.asarray([hits[s] for s in original['target_ids']]);a=dict(original)
            for key in ['ids','fibers','ra','dec','h_public','nominal_hits']:a[key]=original[key][mask]
            a['target_ids']=[s for s,h in zip(original['target_ids'],mask) if h]
            for key in ['H','alt','az']:a[key]=original[key][:,mask]
            self.geometry.append(a)
        self.directional=[]
        directions=[e for e in self.events if e.scope_type=='HORIZON_SECTOR']
        for a in self.geometry:
            factor=np.ones(a['H'].shape)
            for e in directions:
                active=(a['times']>=e.actual_start_utc.timestamp())&(a['times']<e.actual_end_utc.timestamp())
                hit=active[:,None]&(a['alt']>=e.min_altitude_deg)&(a['alt']<=e.max_altitude_deg)&sector(a['az'],e.azimuth_start_deg,e.azimuth_end_deg)
                mult=0. if e.force_close or e.event_type in ['rocket_launch','terrain_obstruction'] else e.transparency_multiplier*e.sky_quality_multiplier*e.instrument_efficiency_multiplier/e.seeing_multiplier
                factor[hit]*=mult
            self.directional.append(factor)
        self.flux=d['flux'];self.weight=d['weight']
    def active(self,t,repaired):return next((f for f in self.faults if f.actual_start_utc.timestamp()<=t<f.actual_end_utc.timestamp() and f.event_id not in repaired),None)
    def score(self,j,repaired):
        a=self.geometry[j];eff=self.eff[a['slots']].copy()
        for f in self.faults:
            if f.event_id in repaired:
                active=(a['times']>=f.actual_start_utc.timestamp())&(a['times']<f.actual_end_utc.timestamp());eff[active]=np.minimum(1.,eff[active]/f.instrument_efficiency_multiplier)
        c=self.cc[a['slots']];qb=a['seconds']@(c[:,None]*a['H'])/a['duration']
        qz=a['seconds']@(c[:,None]*eff[:,None]*a['H']*self.directional[j])/a['duration']
        ids=a['ids'];factor=np.minimum(1.,self.flux[ids]*a['duration']*qz/450.);band=np.where(qb>=.65,0,np.where(qb>=.4,1,2));mult=np.where(band==a['program'],[1.2,1.12,1.06][a['program']],1.)
        return np.round(factor*self.weight[ids]*mult,6),factor,qb,qz

class PublicState:
    def __init__(self,world):
        self.history=[];self.last_report=None;self.last_outcome=0.;self.correct=0;self.quake_start=None;self.best=np.zeros(len(world.flux));self.last_token_slot=None
        self.terrain_notices=[x for x in world.bulletins[0]['notices'] if x['event_kind']=='terrain_obstruction']
    def clone(self):
        q=copy.copy(self);q.history=list(self.history);q.best=self.best.copy();return q
    def report(self,t,y):self.last_report=t;self.last_outcome=1. if y else -1.;self.correct+=int(y)
    def feature(self,w,j):
        if len(self.history)<8:return None
        a=w.geometry[j];t=a['start'];n=a['night'];night=w.design['nights'][n]
        slot=int(a['slots'][0]);notices=[*w.bulletins[slot]['notices'],*self.terrain_notices]
        if any(x['event_kind']=='earthquake' for x in notices):
            if self.quake_start is None:self.quake_start=n
        else:self.quake_start=None
        qa=0. if self.quake_start is None else min(20,n-self.quake_start+1)/20
        forecast=next((f for f in reversed(w.forecasts) if utc(f['issued_at_utc']).timestamp()<=t),{})
        fn=[x for x in forecast.get('notices',[]) if night.night_date.isoformat() in x.get('nights',[])]
        sc=season(night.night_date.timetuple().tm_yday);age=3. if self.last_report is None else min(96.,max(0.,(t-self.last_report)/900))/32
        tail=[sc,n/len(w.design['nights']),(t-night.observing_start_utc.timestamp())/night.night_seconds,age,self.last_outcome,min(self.correct,2)/2,qa,float(self.last_report==t),
            *notice_features(notices,a['pointing'][1]),*[float(any(x['event_kind']==k for x in fn)) for k in KINDS]]
        ages=[min(192.,max(0.,(t-r[1])/900))/64 for r in self.history];nightages=[min(8,n-r[2])/4 for r in self.history]
        return np.concatenate([np.concatenate([r[0] for r in self.history]),ages,nightages,tail]).astype(np.float32)
    def ingest(self,w,j,scores,keep=True):
        a=w.geometry[j];n=a['night'];slot=int(a['slots'][0]);notices=[]
        for si in np.unique(a['slots']):notices.extend(w.bulletins[si]['notices'])
        notices.extend(self.terrain_notices)
        if any(x['event_kind']=='earthquake' for x in notices):
            if self.quake_start is None:self.quake_start=n
        else:self.quake_start=None
        np.maximum.at(self.best,a['ids'],scores)
        # Eight public measurements from distinct starting slots, not eight
        # repeated short exposures inside one correlated weather slot.
        if not keep or slot==self.last_token_slot or len(scores)<3:return
        sc=season(w.design['nights'][n].night_date.timetuple().tm_yday);prev=self.history[-1] if self.history else None
        token=score_token(scores,w.weight[a['ids']],w.flux[a['ids']],a['h_public'],a['duration'],a['program'],elapsed_slots=(a['end']-prev[1])/900 if prev else 8,
            new_night=not prev or prev[2]!=n,seasonal_c=sc,slot_fraction=(a['end']-w.design['nights'][n].observing_start_utc.timestamp())%900/900)
        g=[float(a['h_public'].mean()),float(a['h_public'].std()),float(a['alt'].min())/90,float(a['alt'].max())/90]
        self.history.append((np.concatenate([token,notice_features(notices,a['pointing'][1]),g]),a['end'],n));self.history=self.history[-8:];self.last_token_slot=slot
    def nuisance(self,w,j):
        n=w.geometry[j]['night'];qa=0 if self.quake_start is None else (1 if n-self.quake_start<4 else 2);return qa,min(2,self.correct)

def trajectory(seed,card=None,collect=False,policy=None):
    w=World(seed,card);state=PublicState(w);repaired=set();quota=2;records=[];rng=np.random.default_rng(seed+441)
    # Publicly independent dropout design; includes dense and sparse histories.
    dropout=float(rng.choice([0.,.15,.35]));keep=rng.random(len(w.geometry))>=dropout
    total=0.;science=0.;reportscore=0.;reports=correct=false=0
    for j,a in enumerate(w.geometry):
        x=state.feature(w,j);fault=w.active(a['start'],repaired);y=int(fault is not None);raw=w.score(j,repaired)[0];rr=set(repaired)
        if fault is not None:rr.add(fault.event_id)
        fixed=w.score(j,rr)[0];loss=max(0.,float(np.maximum(fixed-state.best[a['ids']],0).sum()-np.maximum(raw-state.best[a['ids']],0).sum()))
        if x is not None and collect and j+1<len(w.geometry):
            s0=state.clone();s0.ingest(w,j,raw,bool(keep[j]));s1=state.clone();s1.report(a['start'],y);s1.ingest(w,j,fixed if y else raw,bool(keep[j]))
            elapsed=sum(max(0.,min(a['start'],n.observing_end_utc.timestamp())-n.observing_start_utc.timestamp()) for n in w.design['nights'] if a['start']>n.observing_start_utc.timestamp())
            progress=elapsed/sum(n.night_seconds for n in w.design['nights'])
            records.append((x,y,loss,s0.feature(w,j+1),s1.feature(w,j+1),min(7,int(8*progress)),*state.nuisance(w,j),j,len(w.geometry),seed,
                int(w.active(w.geometry[j+1]['start'],repaired) is not None),int(w.active(w.geometry[j+1]['start'],rr) is not None)))
        doreport=(rng.random()<.012) if policy is None else (bool(y) if policy=='oracle' else bool(policy(x,quota,j,len(w.geometry),state.nuisance(w,j))) if x is not None else False)
        if doreport:
            reports+=1;correct+=y;false+=1-y;state.report(a['start'],y)
            if y:repaired=rr;quota=2;reportscore+=100.;raw=fixed
            else:reportscore-=150. if quota==0 else 0.;quota=max(0,quota-1)
        old=state.best[a['ids']].copy();state.ingest(w,j,raw,bool(keep[j]));science+=float((state.best[a['ids']]-old).sum())
    return records,dict(seed=seed,card=w.card,science=science,report=reportscore,score=science+reportscore,reports=reports,correct=correct,false=false,
        observed_records=len(w.geometry),measured_slots=int(sum(keep)),dropout=dropout,training_records=len(records),qdim=XDIM)

def pilot():
    start=time.time();rows=[]
    for seed in [810000,810001,810002,810003]:
        r,summary=trajectory(seed,collect=True);rows.append(summary);print(json.dumps(summary),flush=True)
        assert all(len(x[0])==XDIM and x[3] is not None and x[4] is not None for x in r)
    out=dict(worlds=rows,seconds=time.time()-start,seed_domain='pilot810000-810003 distinct from later train/cal/val/test',actor_inputs='only newworld public scores, report results, bulletin/forecast, physical public geometry and clocks',
        no_production_rollout=True,original_private_inputs=False,source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['public_design.py','sparse_world.py','sensor_core.py']})
    (ROOT/'pilot_result.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
if __name__=='__main__':pilot()
