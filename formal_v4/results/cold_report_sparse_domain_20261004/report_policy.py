"""Sparse public-score report DP with frozen faultv1 fallback."""
from __future__ import annotations
import copy,time,math
from datetime import timedelta
import numpy as np
import report_support
from report_core import ReportModel,ReportDP
from sensor_core import score_token,BASE_DIM
from research.geometry import parse_utc,local_sidereal_deg
from research.feedback_model import seasonal_quality
KINDS=['earthquake','overcast','haze','cold_snap','rain','storm','rocket_launch','terrain_obstruction']
DIRECTIONS={k:45*j for j,k in enumerate(['N','NE','E','SE','S','SW','W','NW'])}
PROGRAMS=['DARK','BRIGHT','BACKUP'];TOKEN_DIM=BASE_DIM+28;TAIL_DIM=40
def notice_features(notices,az):
    rows=[]
    for kind in KINDS:
        items=[n for n in notices if n.get('event_kind')==kind]
        cosine=max([math.cos(math.radians((az-DIRECTIONS[n['direction']]+180)%360-180)) for n in items if n.get('direction') in DIRECTIONS],default=-1.)
        rows.extend([float(bool(items)),float(any(n.get('direction')=='ALL' for n in items)),cosine if items else -1.])
    return np.asarray(rows)

class SparseReportGuard(report_support.PersistentFaultGuard):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.model=None;self.dp=None;self.history=[];self.sparse_seen=set();self.last_token_slot=None
        self.last_public_report=None;self.last_outcome=0.;self.quake_start=None;self.latest_forecast={};self.terrain_notices=[]
        self.model_queries=0;self.model_seconds=0.;self.supported=0;self.rejected={};self.dp_features={};self.insert_reason=None
        pc=self.initial['scoring']['program'];p=self.p
        self.contract=(abs(p.q0-.68)<1e-12 and abs(p.f0t0-450)<1e-12 and self.slot_seconds==900 and
            abs(float(pc['bands']['DARK'])-.65)<1e-12 and abs(float(pc['bands']['BRIGHT'])-.4)<1e-12 and
            all(abs(float(pc['multipliers'][k])-v)<1e-12 for k,v in zip(PROGRAMS,[1.2,1.12,1.06])) and
            abs(float(pc['mismatch_multiplier'])-1)<1e-12 and int(self.reporting.get('false_report_free_allowance',0))==2 and
            float(self.reporting['correct_reward'])==100. and float(self.reporting['false_penalty'])==-150.)
    def reject(self,why):self.rejected[why]=self.rejected.get(why,0)+1
    def day(self,n):return parse_utc(self.initial['survey']['nights'][n]['night_date']+'T00:00:00Z').timetuple().tm_yday
    def ingest(self,snapshot):
        messages=snapshot.get('new_messages',[])
        for m in messages:
            if m.get('record_type')=='forecast':self.latest_forecast=m
            if m.get('record_type')=='bulletin':self.terrain_notices.extend(x for x in m.get('notices',[]) if x.get('event_kind')=='terrain_obstruction' and x not in self.terrain_notices)
        if snapshot.get('latest_forecast'):self.latest_forecast=snapshot['latest_forecast']
        now=parse_utc(snapshot['now_utc']);n=self.actor._night(now);notices=(snapshot.get('latest_bulletin') or {}).get('notices',[])
        self.terrain_notices.extend(x for x in notices if x.get('event_kind')=='terrain_obstruction' and x not in self.terrain_notices)
        if any(m.get('record_type')=='state_resync' for m in messages):
            self.history.clear();self.last_token_slot=None;self.reject('public_resync')
        if not self.last:return
        action=self.last['action'];result=snapshot.get('last_result') or {}
        super().ingest(snapshot)
        if action['action']=='report':
            self.last_public_report=now;self.last_outcome=1. if result['correct'] else -1.;return
        if action['action']!='observe' or result.get('action')!='observe':return
        rank=int(result['observe_index'])
        if rank in self.sparse_seen:return
        self.sparse_seen.add(rank);start=parse_utc(self.last['now_utc']);d=min(float(action['duration_seconds']),(now-start).total_seconds());n=self.actor._night(start)
        exposed=list(self.last.get('notices',[]));end=start+timedelta(seconds=d)
        for m in messages:
            if m.get('record_type')=='bulletin' and start<parse_utc(m['issued_at_utc'])<=end:exposed.extend(m.get('notices',[]))
        exposed.extend(self.terrain_notices)
        if any(x.get('event_kind')=='earthquake' for x in exposed):
            if self.quake_start is None:self.quake_start=n
        else:self.quake_start=None
        hits=[h for h in result.get('hits',[]) if str(h.get('target_id')) in self.p.index]
        if n<0 or len(hits)<3 or not 60<=d<=3600:self.reject('public_hitcount_or_duration');return
        slot=(n,int((start-self.p.nights[n][0]).total_seconds()//900))
        if slot==self.last_token_slot:return
        idx=np.asarray([self.p.index[str(h['target_id'])] for h in hits],int);H=self.actor._geometric_H(start,d,idx)
        # All geometry comes from public RA/Dec of the observed ids. No offset,
        # actual center, weather, validity, quality or factor is actor input.
        gcache=self.actor._sparse_geometry_cache
        g=[float(H.mean()),float(H.std()),float(gcache[2][idx].min())/90,float(gcache[3][idx].max())/90]
        sc=seasonal_quality(self.day(n),self.p.q0)[0];prev=self.history[-1] if self.history else None
        token=score_token([float(h['score']) for h in hits],self.p.weight[idx],self.p.flux[idx],H,d,PROGRAMS.index(action['program']),
            elapsed_slots=(end.timestamp()-prev[1])/900 if prev else 8,new_night=not prev or prev[2]!=n,seasonal_c=sc,
            slot_fraction=((end-self.p.nights[n][0]).total_seconds()%900)/900)
        self.history.append((np.concatenate([token,notice_features(exposed,float(action['pointing']['az_deg'])),g]),end.timestamp(),n));self.history=self.history[-8:]
        self.last_token_slot=slot;self.supported+=1
    def feature(self,snapshot,action):
        now=parse_utc(snapshot['now_utc']);n=self.actor._night(now)
        if len(self.history)<8 or n<0:return None
        if now.timestamp()-self.history[-1][1]>8*3600 or any((now.timestamp()-r[1])/900>192 for r in self.history):return None
        a,b=self.p.nights[n];date=self.initial['survey']['nights'][n]['night_date'];fn=[m for m in self.latest_forecast.get('notices',[]) if date in m.get('nights',[])]
        notices=[*(snapshot.get('latest_bulletin') or {}).get('notices',[]),*self.terrain_notices];qa=0. if self.quake_start is None else min(20,n-self.quake_start+1)/20
        if any(x.get('event_kind')=='earthquake' for x in notices):
            if self.quake_start is None:self.quake_start=n
        else:self.quake_start=None
        qa=0. if self.quake_start is None else min(20,n-self.quake_start+1)/20
        age=3. if self.last_public_report is None else min(96.,max(0.,(now-self.last_public_report).total_seconds()/900))/32
        tail=[seasonal_quality(self.day(n),self.p.q0)[0],n/len(self.p.nights),(now-a).total_seconds()/(b-a).total_seconds(),age,self.last_outcome,min(self.correct,2)/2,qa,float(self.last_public_report==now),
            *notice_features(notices,float(action['pointing']['az_deg'])),*[float(any(m.get('event_kind')==k for m in fn)) for k in KINDS]]
        ages=[min(192.,max(0.,(now.timestamp()-r[1])/900))/64 for r in self.history];nightages=[min(8,n-r[2])/4 for r in self.history]
        x=np.concatenate([np.concatenate([r[0] for r in self.history]),ages,nightages,tail]);assert len(x)==1568
        total=sum((b-a).total_seconds() for a,b in self.p.nights);elapsed=sum(max(0.,(min(now,b)-a).total_seconds()) for a,b in self.p.nights if now>a)
        progress=min(.999999,elapsed/max(1,total));quake=0 if self.quake_start is None else (1 if n-self.quake_start<4 else 2)
        return x,progress,(quake,min(2,self.correct))
    def propose(self,snapshot,action,decision_started=None,analytical=False):
        fallback=super().propose(snapshot,action,decision_started,analytical)
        if fallback.get('action')=='report':self.insert_reason='faultv1';return fallback
        if not self.enabled or not self.contract or self.cached is not None or action.get('action')!='observe':return action
        free=2-self.false_count
        if free<=0 or self.correct>=2:return action
        remaining=snapshot.get('wallclock',{}).get('remaining_seconds')
        if not analytical and (remaining is None or float(remaining)-(time.perf_counter()-decision_started)<15):return action
        f=self.feature(snapshot,action)
        if f is None:self.reject('sparse_history_support');return action
        if self.model is None:self.model=ReportModel();self.dp=ReportDP()
        x,progress,nuisance=f;started=time.perf_counter();p=float(self.model.posterior(x));value=self.dp.delta(p,free,int(progress*8),nuisance,progress,1.)
        self.model_queries+=1;self.model_seconds+=time.perf_counter()-started
        self.dp_features=dict(posterior=p,report_minus_wait=value,quota=free,progress=progress,nuisance=nuisance)
        selected=(p>.9) if self.cfg.get('report_mode')=='posterior_p90_control' else p>0 and value>0
        if not selected:return action
        self.cached=copy.deepcopy(action);self.saved_pending=copy.deepcopy(self.actor.pending);self.report_snapshot=(snapshot['now_utc'],int(snapshot['observe_action_index']))
        self.inserted+=1;self.insert_reason='sparse_dp';self.event('sparse_calibrated_report',now_utc=snapshot['now_utc'],observe_action_index=snapshot['observe_action_index'],**self.dp_features)
        return {'action':'report'}
    def release_false(self,snapshot):
        if self.insert_reason=='faultv1':return super().release_false(snapshot)
        now,rank=self.report_snapshot;result=snapshot.get('last_result') or {}
        if snapshot['now_utc']!=now or int(snapshot['observe_action_index'])!=rank or result.get('correct') is not False or float(result.get('score_delta',1))!=0:raise RuntimeError('Report zero-time/free contract')
        if any(m.get('record_type')!='report_result' for m in snapshot.get('new_messages',[])):raise RuntimeError('Unexpected zero-time information')
        action=self.cached;self.actor.pending=self.saved_pending;self.actor.false_since_correct=self.false_count;self.actor.report_count+=1
        self.cached=None;self.saved_pending=None;self.report_snapshot=None;self.event('sparse_false_frozen_action_released',now_utc=now,observe_action_index=rank)
        return action
    def summary(self):return {**super().summary(),'sparse_report':dict(contract=self.contract,queries=self.model_queries,seconds=self.model_seconds,supported=self.supported,rejected=self.rejected,latest=self.dp_features,public_only=True)}

def make_policy_class(base,enabled=True,emit=None,mode='dp_free'):
    class GeometryMemoPolicy(base):
        def _geometric_H(self,start,duration,idx):
            if not enabled:return super()._geometric_H(start,duration,idx)
            key=(start,float(duration));cached=getattr(self,'_sparse_geometry_cache',None)
            if cached is None or cached[0]!=key:
                p=self.planner;end=start+timedelta(seconds=duration);n=self._night(start);anchor=p.nights[n][0] if n>=0 else start;cursor=start
                total=np.zeros(p.n);lo=np.full(p.n,np.inf);hi=np.full(p.n,-np.inf)
                while cursor<end:
                    sn=math.floor((cursor-anchor).total_seconds()/self.slot_seconds);se=min(end,anchor+timedelta(seconds=(sn+1)*self.slot_seconds))
                    if se<=cursor:se=min(end,cursor+timedelta(seconds=self.slot_seconds))
                    while cursor<se:
                        right=min(se,cursor+timedelta(seconds=120));mid=cursor+(right-cursor)/2;lst=local_sidereal_deg(mid,p.lon);alt=p._altaz(lst)[0]
                        total+=(right-cursor).total_seconds()*p._public_quality(mid,lst,alt)*p.q0;lo=np.minimum(lo,alt);hi=np.maximum(hi,alt);cursor=right
                cached=(key,np.maximum(1e-9,total/duration),lo,hi);self._sparse_geometry_cache=cached
            return cached[1][idx]
    report_support.PersistentFaultGuard=SparseReportGuard
    return report_support.make_policy_class(GeometryMemoPolicy,enabled=enabled,emit=emit,config={'report_mode':mode})
