"""Host/training-only official-seed-world labels. Not included in actor package."""
from __future__ import annotations
import copy,json,math,sys,time,hashlib
from pathlib import Path
import numpy as np
from predictive_core import score_token,HISTORY,BASE_DIM

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'official'))
from challenge.v4_weather_simulator import (build_nights,generate_events,generate_weather,
                                            generate_bulletins,generate_forecasts)

def season(night,q0=.68):
    s=math.sin(2*math.pi*(night.night_date.timetuple().tm_yday-210)/365.2425)
    return (.88-.07*s)*(1.-.12*s)/((1.10+.15*s)*q0)

def build(seed,nights,slots,base):
    cfg=copy.deepcopy(base);cfg['seed']=seed;cfg['seed_derivation']='sha256-v1'
    # Diverse counts, independent of participant card identities.
    counts=np.random.default_rng(seed+777)
    cfg['instrument_fault']['count']=int(counts.choice([0,1,2]))
    for definition in cfg['weather_events']['conditions'].values():
        definition['count']=int(counts.integers(0,4))
    cfg['earthquake']['count']=int(counts.integers(0,3))
    events,effects=generate_events(cfg,nights,slots)
    rows=generate_weather(cfg,nights,slots,events,effects)
    bulletins=[json.loads(x) for x in generate_bulletins(cfg,nights,slots,events,effects)]
    forecasts=[json.loads(x) for x in generate_forecasts(cfg,nights,events)]
    slotidx={s.slot_id:i for i,s in enumerate(slots)}
    cc=np.zeros(len(slots)); zz=np.zeros(len(slots));op=np.zeros(len(slots),bool)
    for i,row in enumerate(rows):
        op[i]=row['is_observable']=='true'
        if op[i]:
            cc[i]=float(row['transparency'])*float(row['sky_quality'])/(float(row['seeing_arcsec'])*.68)
            zz[i]=cc[i]*float(row['instrument_efficiency'])
    rng=np.random.default_rng(seed+991)
    records=[]; ys=[]; masks=[]; pats=[]; clocks=[]; evalrows=[]
    previous_end=None; previous_night=None;history=[];history_clock=[]
    current_forecast={}
    for n,night in enumerate(nights):
        sc=season(night);local=[slotidx[s.slot_id] for s in slots if s.night_id==night.night_id]
        for forecast in forecasts:
            if forecast['issued_at_utc']<=night.observing_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ'):
                current_forecast=forecast
        forecast_kinds={notice['event_kind'] for notice in current_forecast.get('notices',[])
                        if night.night_date.isoformat() in notice['nights']}
        now=0.
        while now<(len(local)-4)*900:
            # Random non-overlapping exposure history; no label-dependent action.
            duration=float(rng.choice([60,120,240,450,600,900,1200,1800,2400,3000]))
            duration=min(duration,(len(local)-4)*900-now)
            if duration<60:break
            start=now;end=now+duration
            left=int(start//900);right=int(math.ceil(end/900))
            inds=np.asarray(local[left:right]);seconds=np.asarray([min(end,(j+1)*900)-max(start,j*900) for j in range(left,right)])
            # Protected altitude85 excludes all generated directional events.
            # Constant H is a public geometric measurement design, not a label.
            # A real 16-fibre field has nearly common lunar/airmass geometry;
            # independent full-range H_i would artificially reveal band C.
            H=rng.uniform(.18,1.)*np.clip(1.+rng.normal(0.,.02,16),.9,1.1)
            cls=rng.choice(5,16,p=[.34,.24,.2,.14,.08])
            flux=rng.lognormal(np.log(np.asarray([.55,1.25,.35,.18,4.])[cls]),np.asarray([.4,.3,.35,.5,.25])[cls])
            w=np.asarray([1.,.45,1.,1.7,.3])[cls]
            program=int(rng.integers(3))
            cbar=float((cc[inds]*seconds).sum()/duration)
            zbar=float((zz[inds]*seconds).sum()/duration)
            band=np.where(cbar*H>=.65,0,np.where(cbar*H>=.40,1,2))
            factors=np.minimum(1.,flux*duration*H*zbar/450.)
            scores=np.round(factors*w*np.where(band==program,[1.2,1.12,1.06][program],1.),6)
            clock=night.observing_start_utc.timestamp()+end
            token=score_token(scores,w,flux,H,duration,program,elapsed_slots=(clock-previous_end)/900 if previous_end else 8,
                              new_night=previous_night!=n,seasonal_c=sc,slot_fraction=(end%900)/900)
            history.append(token);history_clock.append((clock,n))
            previous_end=clock;previous_night=n
            current=int(end//900)
            future=np.asarray(local[current:current+4])
            notices=bulletins[local[current]]['notices']
            clean=not any(x['event_kind']!='terrain_obstruction' for x in notices)
            # Closed background remains allowed, but published event nights are
            # not deployment-supported in this initial prototype.
            if len(history)>=HISTORY and clean and not forecast_kinds:
                f=np.concatenate(history[-HISTORY:])
                age=np.asarray([min(96.,(clock-t)/900)/32 for t,k in history_clock[-HISTORY:]])
                nightage=np.asarray([min(8,n-k)/4 for t,k in history_clock[-HISTORY:]])
                f=np.concatenate([f,age,nightage,[sc,end/((len(local))*900)]])
                label=np.concatenate([np.log(np.maximum(.001,cc[future])/sc),np.log(np.maximum(.001,zz[future])/(sc*.95))])/.3
                mask=np.concatenate([op[future],op[future]])
                pattern=int(sum(int(b)<<k for k,b in enumerate(op[future])))
                records.append(f);ys.append(label);masks.append(mask);pats.append(pattern)
                # Public candidate design for separate decision-calibration test.
                evalrows.append([sc, end%900, cbar, zbar, duration, program])
            now=end+float(rng.choice([0,0,60,180,300]))
    return np.asarray(records,np.float32),np.asarray(ys,np.float32),np.asarray(masks,bool),np.asarray(pats,np.int64),np.asarray(evalrows,np.float32)

def main():
    t=time.time();base=json.loads((ROOT/'official/challenge/reference/v4/v4_weather_config.json').read_text())
    base['survey']['end_date']='2026-11-08'
    nights,slots=build_nights(base)
    outputs={};summary={}
    for split,count,offset in [('train',128,710000),('val',32,720000),('test',32,730000)]:
        packs=[];world=[]
        for k in range(count):
            p=build(offset+k,nights,slots,base);packs.append(p);world.extend([offset+k]*len(p[0]))
            if k%16==0:print(split,k,len(p[0]),flush=True)
        names=['x','y','mask','pattern','evalrow']
        for j,name in enumerate(names):outputs[f'{split}_{name}']=np.concatenate([p[j] for p in packs])
        outputs[f'{split}_world']=np.asarray(world)
        summary[split]={'seeds':[offset,offset+count-1],'worlds':count,'records':len(world)}
    np.savez_compressed(ROOT/'world_dataset.npz',**outputs)
    summary.update(seconds=time.time()-t,official_commit='e01939d060f304c2a7cf04d9b3e46009b564fc23',
                   actor_inputs='past public six-decimal scores/known weights flux H duration program and clocks; current public forecast exclusion',
                   host_labels_only=True,record_feature_count=outputs['train_x'].shape[1],test_read_for_training=False,
                   generator_sha256=hashlib.sha256((ROOT/'official/challenge/v4_weather_simulator.py').read_bytes()).hexdigest())
    (ROOT/'dataset_manifest.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary),flush=True)
if __name__=='__main__':main()
