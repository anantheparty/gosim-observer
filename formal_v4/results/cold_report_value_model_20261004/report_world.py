"""Host-only official generated worlds and public sensor histories.

Only this file imports the generator. Actor core never imports world truth.
Coupled one-step report/no-report branches share all future weather.
"""
from __future__ import annotations
import copy, json, math, sys
from pathlib import Path
import numpy as np
from sensor_core import score_token, HISTORY, BASE_DIM

ROOT=Path(__file__).resolve().parent
OFFICIAL=ROOT.parent/'cold_predictive_world_model_20261004'/'official'
sys.path.insert(0,str(OFFICIAL))
from challenge.v4_weather_simulator import build_nights,generate_events,generate_weather,generate_bulletins,generate_forecasts
KINDS=['earthquake','overcast','haze','cold_snap','rain','storm','rocket_launch']
DIM=HISTORY*(BASE_DIM+len(KINDS))+16+16

def season(night):
    a=math.sin(2*math.pi*(night.night_date.timetuple().tm_yday-210)/365.2425)
    return (.88-.07*a)*(1.-.12*a)/((1.1+.15*a)*.68)

def notices_vector(notices):
    kinds={x['event_kind'] for x in notices}
    return np.asarray([float(k in kinds) for k in KINDS])

class World:
    def __init__(self,seed):
        base=json.loads((OFFICIAL/'challenge/reference/v4/v4_weather_config.json').read_text())
        base['seed']=int(seed);base['seed_derivation']='sha256-v1';base['survey']['end_date']='2026-11-08'
        rng=np.random.default_rng(seed+777)
        base['instrument_fault']['count']=int(rng.choice([0,1,2],p=[.25,.50,.25]))
        for d in base['weather_events']['conditions'].values():d['count']=int(rng.integers(0,4))
        base['earthquake']['count']=int(rng.integers(0,3))
        self.nights,self.slots=build_nights(base)
        self.events,self.effects=generate_events(base,self.nights,self.slots)
        rows=generate_weather(base,self.nights,self.slots,self.events,self.effects)
        self.bulletins=[json.loads(x) for x in generate_bulletins(base,self.nights,self.slots,self.events,self.effects)]
        self.forecasts=[json.loads(x) for x in generate_forecasts(base,self.nights,self.events)]
        self.cc=np.zeros(len(rows));self.eff=np.zeros(len(rows))
        for i,row in enumerate(rows):
            if row['is_observable']=='true':
                self.cc[i]=float(row['transparency'])*float(row['sky_quality'])/(float(row['seeing_arcsec'])*.68)
                self.eff[i]=float(row['instrument_efficiency'])
        self.faults=[e for e in self.events if e.event_type=='instrument_fault']
        self.catalog_rng=np.random.default_rng(seed+1234)
        cls=self.catalog_rng.choice(5,9400,p=[.34,.24,.20,.14,.08])
        self.flux=self.catalog_rng.lognormal(np.log(np.asarray([.55,1.25,.35,.18,4.])[cls]),np.asarray([.4,.3,.35,.5,.25])[cls])
        self.w=np.asarray([1.,.45,1.,1.7,.3])[cls]
        self.actions=[];slotidx={s.slot_id:i for i,s in enumerate(self.slots)}
        r=np.random.default_rng(seed+991)
        for n,night in enumerate(self.nights):
            local=[slotidx[s.slot_id] for s in self.slots if s.night_id==night.night_id]
            now=0.
            while now<len(local)*900-60:
                d=min(float(r.choice([240,450,600,900,1200,1800,2400])),len(local)*900-now)
                left=int(now//900);right=int(math.ceil((now+d)/900))
                inds=np.asarray(local[left:right]);sec=np.asarray([min(now+d,(j+1)*900)-max(now,j*900) for j in range(left,right)])
                ids=r.choice(9400,16,replace=False)
                h=r.uniform(.18,1.)*np.clip(1+r.normal(0,.02,16),.9,1.1)
                prog=int(r.integers(3));start=night.observing_start_utc.timestamp()+now;end=start+d
                self.actions.append(dict(night=n,slot=local[left],indices=inds,seconds=sec,ids=ids,h=h,program=prog,duration=d,start=start,end=end))
                now+=d+float(r.choice([0,0,60,180]))
        self.seed=seed

    def active(self,t,repaired):
        return next((e for e in self.faults if e.actual_start_utc.timestamp()<=t<e.actual_end_utc.timestamp() and e.event_id not in repaired),None)

    def score(self,a,repaired):
        ix=a['indices'];eff=self.eff[ix].copy()
        for j,i in enumerate(ix):
            moment=self.slots[i].timestamp_utc.timestamp()
            fault=next((e for e in self.faults if e.actual_start_utc.timestamp()<=moment<e.actual_end_utc.timestamp()),None)
            if fault is not None and fault.event_id in repaired:eff[j]=min(1.,eff[j]/fault.instrument_efficiency_multiplier)
        c=float(self.cc[ix]@a['seconds']/a['duration']);z=float((self.cc[ix]*eff)@a['seconds']/a['duration'])
        ids=a['ids'];band=np.where(c*a['h']>=.65,0,np.where(c*a['h']>=.4,1,2))
        factor=np.minimum(1.,self.flux[ids]*a['duration']*a['h']*z/450.)
        scores=np.round(factor*self.w[ids]*np.where(band==a['program'],[1.2,1.12,1.06][a['program']],1.),6)
        return scores,c,z

class PublicState:
    def __init__(self):
        self.history=[];self.last_report=None;self.last_outcome=0.;self.correct_count=0;self.quake_start=None
        self.best=np.zeros(9400);self.report_timestamp=None
    def clone(self):
        c=PublicState();c.history=list(self.history);c.last_report=self.last_report;c.last_outcome=self.last_outcome
        c.correct_count=self.correct_count;c.quake_start=self.quake_start;c.best=self.best.copy();c.report_timestamp=self.report_timestamp;return c
    def report(self,t,correct):
        self.last_report=t;self.last_outcome=1. if correct else -1.;self.correct_count+=int(correct);self.report_timestamp=t
    def ingest(self,world,a,scores):
        n=a['night'];sc=season(world.nights[n]);prior=self.history[-1] if self.history else None
        notices=[]
        for i in a['indices']:notices.extend(world.bulletins[i]['notices'])
        nv=notices_vector(notices)
        if nv[0] and self.quake_start is None:self.quake_start=n
        if not nv[0]:self.quake_start=None
        token=score_token(scores,world.w[a['ids']],world.flux[a['ids']],a['h'],a['duration'],a['program'],
            elapsed_slots=(a['end']-prior[1])/900 if prior else 8,new_night=not prior or prior[2]!=n,
            seasonal_c=sc,slot_fraction=((a['end']-world.nights[n].observing_start_utc.timestamp())%900)/900)
        self.history.append((np.concatenate([token,nv]),a['end'],n));self.history=self.history[-8:]
        np.maximum.at(self.best,a['ids'],scores)
    def feature(self,world,a):
        if len(self.history)<8:return None
        t=a['start'];n=a['night'];sc=season(world.nights[n]);night=world.nights[n]
        forecast=next((f for f in reversed(world.forecasts) if f['issued_at_utc']<=night.observing_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')), {})
        notices=[x for x in forecast.get('notices',[]) if night.night_date.isoformat() in x['nights']]
        bv=notices_vector(world.bulletins[a['slot']]['notices']);fv=notices_vector(notices)
        quake_age=0. if self.quake_start is None else min(20,n-self.quake_start+1)/20
        reportage=3. if self.last_report is None else min(96.,max(0.,(t-self.last_report)/900))/32
        tail=np.asarray([sc,n/len(world.nights), (t-night.observing_start_utc.timestamp())/(night.observing_end_utc-night.observing_start_utc).total_seconds(),
            reportage,self.last_outcome,min(self.correct_count,2)/2,quake_age,float(self.report_timestamp==t),*bv,*fv])
        # Exactly 22 public scalars (not 16): clocks, outcomes and current notices.
        age=[min(96.,max(0.,(t-r[1])/900))/32 for r in self.history]
        nightage=[min(8,n-r[2])/4 for r in self.history]
        return np.concatenate([np.concatenate([r[0] for r in self.history]),age,nightage,tail]).astype(np.float32)
    def nuisance(self,world,a):
        n=a['night'];q=0 if self.quake_start is None else (1 if n-self.quake_start<4 else 2)
        return q,min(2,self.correct_count)

def trajectory(seed,policy=None,collect=False):
    w=World(seed);state=PublicState();repaired=set();quota=2;rs=np.random.default_rng(seed+5678)
    rows=[];rewards=0.;science=0.;reports=corrects=false=0;trace=[]
    for j,a in enumerate(w.actions):
        x=state.feature(w,a);fault=w.active(a['start'],repaired);y=int(fault is not None)
        raw,c,z=w.score(a,repaired);rr=set(repaired)
        if fault is not None:rr.add(fault.event_id)
        fixed,_,_=w.score(a,rr)
        loss=float(np.maximum(fixed-state.best[a['ids']],0).sum()-np.maximum(raw-state.best[a['ids']],0).sum())
        loss=max(0.,loss)
        phase=min(7,int(8*j/len(w.actions)));nuisance=state.nuisance(w,a)
        if x is not None and collect and j+1<len(w.actions):
            nexta=w.actions[j+1]
            s0=state.clone();s0.ingest(w,a,raw);xw=s0.feature(w,nexta)
            s1=state.clone();s1.report(a['start'],bool(y));s1.ingest(w,a,fixed if y else raw);xr=s1.feature(w,nexta)
            yw=int(w.active(nexta['start'],repaired) is not None)
            yr=int(w.active(nexta['start'],rr) is not None)
            rows.append((x,y,loss,xw,xr,phase,*nuisance,j,len(w.actions),seed,yw,yr))
        do_report=False
        if x is not None:
            if policy is None:do_report=bool(rs.random()<.012)
            elif policy=='oracle':do_report=bool(y)
            else:do_report=bool(policy(x,quota,phase,nuisance,j,len(w.actions)))
        if do_report:
            reports+=1;corrects+=y;false+=1-y;state.report(a['start'],bool(y))
            if y:repaired=rr;rewards+=100.;quota=2;raw=fixed
            else:rewards-=150. if quota==0 else 0.;quota=max(0,quota-1)
            trace.append([j,y,quota,loss])
        old=state.best[a['ids']].copy();state.ingest(w,a,raw)
        science+=float((state.best[a['ids']]-old).sum())
    return rows,dict(seed=seed,score=science+rewards,science=science,report=rewards,reports=reports,correct=corrects,false=false,trace=trace)

def main():
    import time,hashlib
    started=time.time();data={};manifest={}
    for split,offset,count in [('train',740000,128),('cal',750000,16),('val',750016,16)]:
        rows=[]
        for k in range(count):
            r,_=trajectory(offset+k,collect=True);rows.extend(r)
            if k%16==0:print(split,k,len(rows),flush=True)
        names=['x','y','loss','xw','xr','phase','quake','correct','step','total','world','yw','yr']
        for i,name in enumerate(names):data[f'{split}_{name}']=np.asarray([r[i] for r in rows],dtype=np.float32 if name in ['x','xw','xr','loss'] else np.int32)
        manifest[split]=dict(seed_first=offset,seed_last=offset+count-1,worlds=count,records=len(rows),faultprevalence=float(data[f'{split}_y'].mean()))
    np.savez_compressed(ROOT/'report_dataset.npz',**data)
    manifest.update(test=dict(seed_first=760000,seed_last=760031,worlds=32,unopened=True),seconds=time.time()-started,
        official_commit='e01939d060f304c2a7cf04d9b3e46009b564fc23',generator_sha256=hashlib.sha256((OFFICIAL/'challenge/v4_weather_simulator.py').read_bytes()).hexdigest(),
        xdim=int(data['train_x'].shape[1]),host_labels_only=True,limitations='protected high-altitude common-H sensor; fixed random fields; best-only science; no REQ/Jain/data-loss; empirical projected Bellman')
    (ROOT/'dataset_manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest),flush=True)
if __name__=='__main__':main()
