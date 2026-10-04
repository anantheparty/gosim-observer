"""Joint-quality model adapter; first deployment keeps the strong physical action.

Only program is reconsidered. Field, duration, assignment, request machinery,
report logic and the strong action generator are inherited from BasePolicy.
Reference-generator support assumptions are statistical model gates, not claims
that the formal protocol reveals terrain heights or future event completeness.
"""
from __future__ import annotations
import math,time
from datetime import timedelta
from pathlib import Path
import numpy as np
try:
    from .predictive_core import NumpyPredictor,score_token,utility_samples,BASE_DIM,HISTORY
    from .geometry import parse_utc,local_sidereal_deg,normalized_airmass,Moon,lunar_factor,radec_to_altaz
    from .feedback_model import seasonal_quality
except ImportError:
    from predictive_core import NumpyPredictor,score_token,utility_samples,BASE_DIM,HISTORY

PROGRAMS=['DARK','BRIGHT','BACKUP']

def slot_geometry(p,start,duration,indices):
    night=next((k for k,(a,b) in enumerate(p.nights) if a<=start<b),-1)
    if night<0:return None
    anchor=p.nights[night][0];end=start+timedelta(seconds=float(duration))
    slot=int((start-anchor).total_seconds()//900);origin=anchor+timedelta(seconds=slot*900)
    if end>origin+timedelta(seconds=3600):return None
    hs=np.zeros((4,len(indices)));seconds=np.zeros(4);minimum=np.full(len(indices),90.)
    for stamp in [start,end]:
        lst=local_sidereal_deg(stamp,p.lon)
        minimum=np.minimum(minimum,[radec_to_altaz(float(p.ra[i]),float(p.dec[i]),lst,p.lat)[0] for i in indices])
    cursor=start
    while cursor<end:
        j=int((cursor-origin).total_seconds()//900)
        boundary=min(end,origin+timedelta(seconds=(j+1)*900))
        while cursor<boundary:
            right=min(boundary,cursor+timedelta(seconds=120));mid=cursor+(right-cursor)/2
            lst=local_sidereal_deg(mid,p.lon);moon=Moon(mid,lst,p.lat)
            h=[]
            for i in indices:
                alt,_=radec_to_altaz(float(p.ra[i]),float(p.dec[i]),lst,p.lat)
                value=normalized_airmass(alt)**(-p.airmass_exponent)
                if p.lunar:value*=lunar_factor(moon,float(p.ra[i]),float(p.dec[i]),p.lunar)
                h.append(value)
            span=(right-cursor).total_seconds();hs[j]+=span*np.asarray(h);seconds[j]+=span;cursor=right
    hs=np.divide(hs,seconds[:,None],out=np.zeros_like(hs),where=seconds[:,None]>0)
    return hs,seconds,minimum,night

def install_predictive_policy(BasePolicy):
    class PredictivePolicy(BasePolicy):
        def __init__(self,initial):
            super().__init__(initial)
            self.quality_nn=NumpyPredictor(Path(__file__).with_name('joint_model.npz'))
            self.quality_history=[];self.quality_seen=set();self.quality_forecast={}
            self.quality_counts={'public_tokens':0,'supported':0,'changed':0,'model_seconds':0.,'predicted_science_delta':0.}
            rng=np.random.default_rng(8954)
            self.quality_normal=rng.normal(size=(512,8));self.quality_um=(np.arange(512)+.5)/512
            self.quality_uc=rng.random(512)
            p=self.planner
            self.quality_contract=(abs(p.q0-.68)<1e-12 and abs(p.f0t0-450)<1e-12 and
                abs(p.dark_threshold-.65)<1e-12 and abs(p.bright_threshold-.4)<1e-12 and
                np.max(np.abs(p.multipliers-[1.2,1.12,1.06]))<1e-12 and abs(p.mismatch-1)<1e-12 and self.slot_seconds==900)

        def _ingest_result(self,snapshot):
            result=snapshot.get('last_result') or {};pending=self.pending
            if result.get('action')=='report':self.quality_history=[]
            if result.get('action')=='observe' and pending and result.get('observe_index') not in self.quality_seen:
                self.quality_seen.add(result.get('observe_index'));p=self.planner
                start=pending['start'] if hasattr(pending['start'],'timestamp') else parse_utc(pending['start'])
                now=parse_utc(snapshot['now_utc'])
                duration=min(float(pending['action']['duration_seconds']),(now-start).total_seconds())
                observed_end=start+timedelta(seconds=duration)
                notices=list(pending['notices'])
                for message in snapshot.get('new_messages',[]):
                    if message.get('record_type')=='bulletin' and start<parse_utc(message['issued_at_utc'])<observed_end:
                        notices.extend(message.get('notices',[]))
                clean=not any(n.get('event_kind')!='terrain_obstruction' for n in notices)
                hits=[h for h in result.get('hits',[]) if str(h['target_id']) in p.index]
                idx=np.asarray([p.index[str(h['target_id'])] for h in hits],int)
                if clean and len(idx)>=3 and 60<=duration<=3000:
                    geometry=slot_geometry(p,start,duration,idx)
                    if geometry is not None and np.min(geometry[2])>=55.05:
                        hs,seconds,minimum,night=geometry
                        h=(seconds@hs)/duration
                        seasonal=seasonal_quality(self._quality_day(night),p.q0)[0]
                        previous=self.quality_history[-1] if self.quality_history else None
                        elapsed=(observed_end.timestamp()-previous[1])/900 if previous else 8.
                        token=score_token([float(x['score']) for x in hits],p.weight[idx],p.flux[idx],h,duration,
                            PROGRAMS.index(pending['action']['program']),elapsed_slots=elapsed,
                            new_night=not previous or previous[2]!=night,seasonal_c=seasonal,
                            slot_fraction=((observed_end-p.nights[night][0]).total_seconds()%900)/900)
                        self.quality_history.append((token,observed_end.timestamp(),night));self.quality_history=self.quality_history[-8:]
                        self.quality_counts['public_tokens']+=1
            return super()._ingest_result(snapshot)

        def _quality_day(self,night):
            record=self.initial['survey']['nights'][night]
            # Calendar's local night date, matching the reference generator.
            if 'night_date' in record:return parse_utc(str(record['night_date'])+'T00:00:00Z').timetuple().tm_yday
            return (self.planner.nights[night][0]-timedelta(days=1)).timetuple().tm_yday

        def decide(self,snapshot):
            action=super().decide(snapshot)
            for message in snapshot.get('new_messages',[]):
                if message.get('record_type')=='forecast':self.quality_forecast=message
            if not self.quality_contract or action.get('action')!='observe' or len(self.quality_history)<8:return action
            if snapshot.get('active_requests'):return action
            now=parse_utc(snapshot['now_utc']);p=self.planner;night=self._night(now)
            if night<0 or (p.nights[night][1]-now).total_seconds()<3600:return action
            forecast=self.quality_forecast
            if not forecast or not (parse_utc(forecast['coverage_start_utc'])<=now<parse_utc(forecast['coverage_end_utc'])):return action
            date=self.initial['survey']['nights'][night].get('night_date',(p.nights[night][0]-timedelta(days=1)).date().isoformat())
            if any(date in n.get('nights',[]) for n in forecast.get('notices',[])):return action
            if any(n.get('event_kind')!='terrain_obstruction' for n in self.notices):return action
            if now.timestamp()-self.quality_history[-1][1]>8*3600:return action
            idx=np.asarray([p.index[t] for t in action['assignments'].values()],int)
            geometry=slot_geometry(p,now,int(action['duration_seconds']),idx)
            if geometry is None or np.min(geometry[2])<80.05:return action
            hs,seconds,minimum,_=geometry
            if not len(idx):return action
            start=time.perf_counter();seasonal=seasonal_quality(self._quality_day(night),p.q0)[0]
            ages=np.asarray([min(96.,(now.timestamp()-r[1])/900)/32 for r in self.quality_history])
            nightages=np.asarray([min(8,night-r[2])/4 for r in self.quality_history])
            fraction=(now-p.nights[night][0]).total_seconds()/(p.nights[night][1]-p.nights[night][0]).total_seconds()
            x=np.concatenate([np.concatenate([r[0] for r in self.quality_history]),ages,nightages,[seasonal,fraction]])
            c,z,opened=self.quality_nn.samples(x,seasonal,self.quality_normal,self.quality_um,self.quality_uc)
            values=[utility_samples(c,z,opened,p.weight[idx],p.flux[idx],self.scores[idx],hs,seconds,
                       int(action['duration_seconds']),program)[0] for program in range(3)]
            old=PROGRAMS.index(action['program']);new=int(np.argmax([v.mean() for v in values]))
            difference=values[new]-values[old];se=float(difference.std(ddof=1)/math.sqrt(len(difference)))
            self.quality_counts['supported']+=1
            if new!=old and float(difference.mean())>3*se+1e-8:
                action=dict(action);action['program']=PROGRAMS[new];self.pending['action']=action
                self.quality_counts['changed']+=1;self.quality_counts['predicted_science_delta']+=float(difference.mean())
            self.quality_counts['model_seconds']+=time.perf_counter()-start
            return action

        def summary(self):return {**super().summary(),'quality_nn':dict(self.quality_counts)}
    PredictivePolicy.__name__='PredictivePolicy'
    return PredictivePolicy
