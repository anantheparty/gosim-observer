"""Public history adapter for frozen calibrated report posterior/quota DP.

False report releases the exact already chosen physical action. Correct report
lets the strong policy ingest repair and replan. Host generator is absent.
"""
from __future__ import annotations
import copy,time
from datetime import timedelta
import numpy as np
import report_support
from report_core import ReportModel,ReportDP
from sensor_core import score_token
from research.geometry import parse_utc,local_sidereal_deg
from research.feedback_model import seasonal_quality

KINDS=['earthquake','overcast','haze','cold_snap','rain','storm','rocket_launch']
PROGRAMS=['DARK','BRIGHT','BACKUP']
def nv(notices):
    kinds={x.get('event_kind') for x in notices};return np.asarray([float(k in kinds) for k in KINDS])

class ReportValueGuard(report_support.PersistentFaultGuard):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.model=ReportModel();self.dp=ReportDP();self.history=[];self.last_public_report=None
        self.last_outcome=0.;self.quake_start=None;self.latest_forecast={};self.model_queries=0
        self.supported=0;self.model_seconds=0.;self.rejected={};self.last_features={}
        pc=self.initial['scoring']['program'];p=self.p
        self.contract=(abs(p.q0-.68)<1e-12 and abs(p.f0t0-450)<1e-12 and self.slot_seconds==900 and
            abs(float(pc['bands']['DARK'])-.65)<1e-12 and abs(float(pc['bands']['BRIGHT'])-.4)<1e-12 and
            all(abs(float(pc['multipliers'][k])-v)<1e-12 for k,v in zip(PROGRAMS,[1.2,1.12,1.06])) and
            abs(float(pc['mismatch_multiplier'])-1)<1e-12 and int(self.reporting.get('false_report_free_allowance',0))==2 and
            float(self.reporting['correct_reward'])==100. and float(self.reporting['false_penalty'])==-150.)
    def reject(self,why):self.rejected[why]=self.rejected.get(why,0)+1
    def day(self,night):
        date=self.initial['survey']['nights'][night].get('night_date')
        return parse_utc(date+'T00:00:00Z').timetuple().tm_yday if date else (self.p.nights[night][0]-timedelta(days=1)).timetuple().tm_yday
    def ingest(self,snapshot):
        for m in snapshot.get('new_messages',[]):
            if m.get('record_type')=='forecast':self.latest_forecast=m
        if snapshot.get('latest_forecast'):self.latest_forecast=snapshot['latest_forecast']
        now=parse_utc(snapshot['now_utc']);night=self.actor._night(now)
        notices=(snapshot.get('latest_bulletin') or {}).get('notices',[])
        if any(n.get('event_kind')=='earthquake' for n in notices):
            if self.quake_start is None:self.quake_start=night
        else:self.quake_start=None
        if not self.last:return
        action=self.last['action'];result=snapshot.get('last_result') or {}
        if action.get('action')=='report':
            super().ingest(snapshot);self.last_public_report=now;self.last_outcome=1. if result['correct'] else -1.;return
        if action.get('action')!='observe' or result.get('action')!='observe':return
        rank=int(result['observe_index'])
        if rank in self.seen:return
        self.seen.add(rank);start=parse_utc(self.last['now_utc']);d=min(float(action['duration_seconds']),(now-start).total_seconds())
        n=self.actor._night(start)
        hits=[h for h in result.get('hits',[]) if str(h.get('target_id')) in self.p.index]
        if n<0 or len(hits)<12 or not (240<=d<=2400):self.reject('sensor_duration_or_hits');return
        idx=np.asarray([self.p.index[str(h['target_id'])] for h in hits],int)
        minimum=np.full(len(idx),90.)
        for t in [start,start+timedelta(seconds=d)]:
            alt=self.p._altaz(local_sidereal_deg(t,self.p.lon))[0];minimum=np.minimum(minimum,alt[idx])
        if float(minimum.min())<80.05:self.reject('directional_support_altitude');return
        H=self.actor._geometric_H(start,d,idx)
        if H.min()<.18 or H.max()>1.05 or np.max(np.abs(H/H.mean()-1))>.10:self.reject('common_geometry_support');return
        exposed=list(self.last.get('notices',[]))
        end=start+timedelta(seconds=d)
        for m in snapshot.get('new_messages',[]):
            if m.get('record_type')=='bulletin' and start<parse_utc(m['issued_at_utc'])<=end:exposed.extend(m.get('notices',[]))
        sc=seasonal_quality(self.day(n),self.p.q0)[0];prev=self.history[-1] if self.history else None
        token=score_token([float(h['score']) for h in hits],self.p.weight[idx],self.p.flux[idx],H,d,PROGRAMS.index(action['program']),
            elapsed_slots=(end.timestamp()-prev[1])/900 if prev else 8,new_night=not prev or prev[2]!=n,
            seasonal_c=sc,slot_fraction=((end-self.p.nights[n][0]).total_seconds()%900)/900)
        self.history.append((np.concatenate([token,nv(exposed)]),end.timestamp(),n));self.history=self.history[-8:]
        self.supported+=1
    def feature(self,snapshot):
        now=parse_utc(snapshot['now_utc']);n=self.actor._night(now)
        if len(self.history)<8 or n<0:return None
        # The trained history includes regular sensor observations. Sparse real
        # histories outside the trained age range receive no model intervention.
        if now.timestamp()-self.history[-1][1]>8*3600:return None
        if any((now.timestamp()-r[1])/900>96 for r in self.history):return None
        a,b=self.p.nights[n];sc=seasonal_quality(self.day(n),self.p.q0)[0]
        forecast=self.latest_forecast;date=self.initial['survey']['nights'][n].get('night_date')
        fn=[m for m in forecast.get('notices',[]) if date in m.get('nights',[])]
        notices=(snapshot.get('latest_bulletin') or {}).get('notices',[])
        qa=0. if self.quake_start is None else min(20,n-self.quake_start+1)/20
        age=3. if self.last_public_report is None else min(96.,max(0.,(now-self.last_public_report).total_seconds()/900))/32
        tail=[sc,n/len(self.p.nights),(now-a).total_seconds()/(b-a).total_seconds(),age,self.last_outcome,min(self.correct,2)/2,qa,
            float(self.last_public_report==now),*nv(notices),*nv(fn)]
        ages=[min(96.,max(0.,(now.timestamp()-r[1])/900))/32 for r in self.history]
        nightages=[min(8,n-r[2])/4 for r in self.history]
        x=np.concatenate([np.concatenate([r[0] for r in self.history]),ages,nightages,tail])
        total=sum((b-a).total_seconds() for a,b in self.p.nights)
        elapsed=sum(max(0.,(min(now,b)-a).total_seconds()) for a,b in self.p.nights if now>a)
        progress=min(.999999,elapsed/max(1,total));quake=0 if self.quake_start is None else (1 if n-self.quake_start<4 else 2)
        return x,progress,(quake,min(2,self.correct))
    def propose(self,snapshot,action,decision_started=None,analytical=False):
        if not self.enabled or not self.contract or self.cached is not None or action.get('action')!='observe':return action
        free=2-self.false_count
        if free<=0 or self.correct>=2:return action # frozen validation selected free-only reference domain.
        f=self.feature(snapshot)
        if f is None:self.reject('history_support');return action
        remaining=snapshot.get('wallclock',{}).get('remaining_seconds')
        if not analytical and (remaining is None or float(remaining)-(time.perf_counter()-decision_started)<15):return action
        x,progress,nuisance=f;start=time.perf_counter();p=float(self.model.posterior(x))
        value=self.dp.delta(p,free,int(progress*8),nuisance,progress,1.)
        self.model_seconds+=time.perf_counter()-start;self.model_queries+=1
        self.last_features=dict(posterior=p,report_minus_wait=value,quota=free,phase=progress,nuisance=nuisance)
        selected=(p>.9) if self.cfg.get('report_mode')=='posterior_p90_control' else (p>0 and value>0)
        if not selected:return action
        self.cached=copy.deepcopy(action);self.saved_pending=copy.deepcopy(self.actor.pending)
        self.report_snapshot=(snapshot['now_utc'],int(snapshot['observe_action_index']));self.inserted+=1
        self.event('calibrated_report_value',now_utc=snapshot['now_utc'],observe_action_index=snapshot['observe_action_index'],**self.last_features)
        return {'action':'report'}
    def release_false(self,snapshot):
        now,rank=self.report_snapshot
        if snapshot['now_utc']!=now or int(snapshot['observe_action_index'])!=rank:raise RuntimeError('Report advanced time/rank')
        result=snapshot.get('last_result') or {}
        if result.get('action')!='report' or result.get('correct') is not False or float(result.get('score_delta',1))!=0:raise RuntimeError('Unexpected free report result')
        if any(m.get('record_type')!='report_result' for m in snapshot.get('new_messages',[])):raise RuntimeError('Unexpected zero-time information')
        action=self.cached;self.actor.pending=self.saved_pending;self.actor.false_since_correct=self.false_count;self.actor.report_count+=1
        self.cached=None;self.saved_pending=None;self.report_snapshot=None
        self.event('calibrated_false_frozen_action_released',now_utc=now,observe_action_index=rank)
        return action
    def summary(self):
        return dict(enabled=self.enabled,contract=self.contract,inserted=self.inserted,correct=self.correct,false_since_correct=self.false_count,
            supported_sensor_records=self.supported,queries=self.model_queries,model_seconds=self.model_seconds,rejected=self.rejected,
            latest_features=self.last_features,events=self.events,public_only=True,mode=self.cfg.get('report_mode','dp_free'))

def make_policy_class(base,enabled=True,emit=None,mode='dp_free'):
    report_support.PersistentFaultGuard=ReportValueGuard
    return report_support.make_policy_class(base,enabled=enabled,emit=emit,config={'report_mode':mode})
