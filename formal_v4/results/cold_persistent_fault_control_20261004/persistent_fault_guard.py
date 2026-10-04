"""Public score product intervals and persistent anomaly report control.

No truth or fitted C/E is consumed. Rules and model are predeclared separately.
"""
from __future__ import annotations
import collections, copy, json, math, time
from datetime import timedelta
import numpy as np
from research.feedback_model import seasonal_quality
from research.geometry import parse_utc, format_utc, local_sidereal_deg
from research.spatial_candidates import DIRECTION_AZ

DEFAULTS = dict(normal_efficiency_reference=.95, product_ratio_threshold=.60,
                minimum_unsaturated_hits_per_exposure=3, distinct_public_slots=8,
                minimum_low_slots=6, minimum_nights=2, minimum_field_sectors=2,
                minimum_observing_span_seconds=5400, maximum_recent_nights=3,
                free_quota_reserve=1, minimum_wallclock_seconds=15,
                exclude_direction_distance_deg=60, new_level_after_false_ratio=.60,
                cooldown_observing_seconds=14400)

class PersistentFaultGuard:
    def __init__(self, actor, enabled=True, emit=None, config=None):
        self.actor=actor; self.enabled=bool(enabled); self.emit=emit
        self.cfg={**DEFAULTS,**(config or {})}
        self.initial=actor.initial; self.p=actor.planner
        self.reporting=self.initial['scoring']['reporting']
        self.slot_seconds=actor.slot_seconds
        self.rows=collections.deque(maxlen=256); self.last=None; self.seen=set()
        self.cached=None; self.saved_pending=None; self.report_snapshot=None
        self.false_count=0; self.consecutive_reports=0; self.inserted=0
        self.correct=0; self.events=[]; self.last_extra=None; self.negative_level=None
        self.negative_night=None; self.latest_features={}; self.suppress_duplicate_ingest=False

    def event(self,event,**fields):
        r={'event':event,**fields}; self.events.append(r)
        if self.emit:self.emit(r)

    def observing_seconds(self,a,b):
        return sum(max(0.,(min(b,end)-max(a,start)).total_seconds()) for start,end in self.p.nights)

    def ingest(self,snapshot):
        result=snapshot.get('last_result') or {}; now=parse_utc(snapshot['now_utc'])
        if not self.last:return
        action=self.last['action']
        if action['action']=='report':
            if result.get('action')!='report' or not isinstance(result.get('correct'),bool):
                raise RuntimeError('Missing public report feedback')
            if result['correct']:
                self.false_count=0; self.correct+=1
                self.rows.clear(); self.negative_level=None; self.negative_night=None
            else:
                self.false_count+=1
            return
        if action['action']!='observe' or result.get('action')!='observe':return
        rank=int(result['observe_index'])
        if rank in self.seen:return
        self.seen.add(rank)
        hits=[h for h in result.get('hits',[]) if str(h.get('target_id')) in self.p.index]
        start=parse_utc(self.last['now_utc']); d=min(float(action['duration_seconds']),(now-start).total_seconds())
        night=self.actor._night(start)
        if night<0 or d<=0:return
        # A public non-quake ALL event can explain loss and is not diagnostic.
        notices=list(self.last.get('notices',[]))
        for msg in snapshot.get('new_messages',[]):
            if msg.get('record_type')=='bulletin':notices.extend(msg.get('notices',[]))
        forecast=self.last.get('forecast') or {}
        night_date=self.initial['survey']['nights'][night].get('night_date')
        if forecast.get('coverage_start_utc','9999') <= self.last['now_utc'] < forecast.get('coverage_end_utc','0000'):
            notices.extend(n for n in forecast.get('notices',[]) if night_date in n.get('nights',[]))
        allowed=[]
        _, az, _, _=self.p._altaz(local_sidereal_deg(start+timedelta(seconds=d/2),self.p.lon))
        for h in hits:
            i=self.p.index[str(h['target_id'])]
            blocked=False
            for n in notices:
                kind=n.get('event_kind'); direction=n.get('direction')
                if kind=='earthquake':continue
                if kind=='terrain_obstruction' and direction not in DIRECTION_AZ:continue
                if direction=='ALL':blocked=True; break
                if direction in DIRECTION_AZ:
                    delta=abs((float(az[i])-DIRECTION_AZ[direction]+180)%360-180)
                    if delta<float(self.cfg['exclude_direction_distance_deg']):blocked=True; break
            if not blocked:allowed.append(h)
        if len(allowed)<int(self.cfg['minimum_unsaturated_hits_per_exposure']):return
        idx=np.asarray([self.p.index[str(h['target_id'])] for h in allowed],dtype=int)
        H=self.actor._geometric_H(start,d,idx)
        scoring=self.initial['scoring']; pc=scoring['program']
        mult=float(pc['multipliers'][action['program']]); mismatch=float(pc['mismatch_multiplier'])
        denominator=float(scoring['flux_zero_point'])*float(scoring['exposure_zero_point_seconds'])
        lows=[]; highs=[]
        for h,i,H_i in zip(allowed,idx,H):
            score=float(h['score']); w=float(self.p.weight[i]); a=float(self.p.flux[i])*d*float(H_i)/denominator
            yl=max(0.,score-.500001e-6)/w; yu=max(0.,score+.500001e-6)/w
            # Upper y<m_min guarantees unsaturation under either program band.
            if yl<=0 or yu>=min(mult,mismatch)*.985 or a<=0:continue
            lows.append(yl/(max(mult,mismatch)*a)); highs.append(yu/(min(mult,mismatch)*a))
        if len(lows)<int(self.cfg['minimum_unsaturated_hits_per_exposure']):return
        seasonal=seasonal_quality(start.timetuple().tm_yday,self.p.q0)[0]*float(self.cfg['normal_efficiency_reference'])
        anchor=self.p.nights[night][0]
        slot=int((start-anchor).total_seconds()//self.slot_seconds)
        sector=int(float(action['pointing']['az_deg'])//90)%4
        # Interval medians remain robust to a minority of localized losses.
        row={'rank':rank,'night':night,'slot':slot,'now_utc':snapshot['now_utc'],
             'start_utc':self.last['now_utc'],'ratio_lo':float(np.median(lows))/seasonal,
             'ratio_hi':float(np.median(highs))/seasonal,'hits':len(lows),
             'field_sector':sector,'program':action['program'],
             'earthquake_notice':any(n.get('event_kind')=='earthquake' for n in notices)}
        self.rows.append(row)

    def evidence(self,snapshot):
        now=parse_utc(snapshot['now_utc']); night=self.actor._night(now)
        recent=[r for r in self.rows if night-int(self.cfg['maximum_recent_nights'])<r['night']<=night]
        groups=collections.defaultdict(list)
        for r in recent:groups[(r['night'],r['slot'])].append(r)
        slots=[]
        for key,values in groups.items():
            slots.append({'night':key[0],'slot':key[1], 'ratio_hi':float(np.median([r['ratio_hi'] for r in values])),
                          'ratio_lo':float(np.median([r['ratio_lo'] for r in values])),
                          'start_utc':min(r['start_utc'] for r in values),'rows':values})
        slots=slots[-int(self.cfg['distinct_public_slots']):]
        low=[s for s in slots if s['ratio_hi']<float(self.cfg['product_ratio_threshold'])]
        sample=[r for s in low for r in s['rows']]
        span=self.observing_seconds(parse_utc(slots[0]['start_utc']),now) if slots else 0.
        ratio=float(np.median([s['ratio_hi'] for s in slots])) if slots else 1.
        feature={'distinct_slots':len(slots),'low_slots':len(low),'nights':len(set(s['night'] for s in low)),
                 'field_sectors':len(set(r['field_sector'] for r in sample)),
                 'programs':sorted(set(r['program'] for r in sample)), 'observing_span_seconds':span,
                 'median_ratio_upper':ratio,'earthquake_samples':sum(r['earthquake_notice'] for r in sample),
                 'evidence_ranks':[r['rank'] for r in sample]}
        qualifies=(len(slots)>=int(self.cfg['distinct_public_slots']) and len(low)>=int(self.cfg['minimum_low_slots'])
                   and feature['nights']>=int(self.cfg['minimum_nights']) and feature['field_sectors']>=int(self.cfg['minimum_field_sectors'])
                   and span>=float(self.cfg['minimum_observing_span_seconds']))
        if self.negative_level is not None:
            qualifies=qualifies and ratio<self.negative_level*float(self.cfg['new_level_after_false_ratio'])
        feature['qualified']=bool(qualifies); self.latest_features=feature
        return feature

    def propose(self,snapshot,action,decision_started=None,analytical=False):
        if not self.enabled or self.cached is not None:return action
        if action.get('action')!='observe':return action
        features=self.evidence(snapshot)
        if not features['qualified']:return action
        now=parse_utc(snapshot['now_utc'])
        if self.last_extra and self.observing_seconds(self.last_extra,now)<float(self.cfg['cooldown_observing_seconds']):return action
        free=int(self.reporting.get('false_report_free_allowance',0))-self.false_count
        if free<=int(self.cfg['free_quota_reserve']):return action
        if self.consecutive_reports>=int(self.reporting.get('max_consecutive_reports',32)):return action
        if not analytical:
            remaining=snapshot.get('wallclock',{}).get('remaining_seconds')
            if remaining is None:return action
            elapsed=0. if decision_started is None else max(0.,time.perf_counter()-decision_started)
            if float(remaining)-elapsed<float(self.cfg['minimum_wallclock_seconds']):return action
        self.cached=copy.deepcopy(action); self.saved_pending=copy.deepcopy(self.actor.pending)
        self.report_snapshot=(snapshot['now_utc'],int(snapshot['observe_action_index']))
        self.last_extra=now; self.inserted+=1
        self.event('persistent_diagnostic_report',now_utc=snapshot['now_utc'],observe_action_index=snapshot['observe_action_index'],
                   free_reports_remaining=free,quota_reserve=int(self.cfg['free_quota_reserve']),
                   features=features,analytical_only=bool(analytical))
        return {'action':'report'}

    def release_false(self,snapshot):
        now,rank=self.report_snapshot
        if snapshot['now_utc']!=now or int(snapshot['observe_action_index'])!=rank:
            raise RuntimeError('Extra report advanced simulation time/rank')
        result=snapshot.get('last_result') or {}
        if result.get('action')!='report' or result.get('correct') is not False or float(result.get('score_delta',1))!=0.:
            raise RuntimeError('False diagnostic violated public free quota')
        if any(m.get('record_type')!='report_result' for m in snapshot.get('new_messages',[])):
            raise RuntimeError('Unexpected information after zero-time report')
        action=self.cached; self.actor.pending=self.saved_pending
        self.actor.false_since_correct=self.false_count
        self.actor.report_count+=1
        # Actor C/E, low-efficiency samples, witness queues, belief clock and
        # last_report stay exactly as after the original chosen science action.
        self.negative_level=float(self.latest_features['median_ratio_upper'])
        self.negative_night=self.actor._night(parse_utc(now))
        self.cached=None; self.saved_pending=None; self.report_snapshot=None
        self.event('persistent_false_frozen_action_released',now_utc=now,observe_action_index=rank,
                   actor_belief_update_suppressed=True,negative_level=self.negative_level)
        return action

    def sent(self,snapshot,action):
        self.last={'action':copy.deepcopy(action),'now_utc':snapshot['now_utc'],
                   'rank':int(snapshot['observe_action_index']),
                   'notices':copy.deepcopy((snapshot.get('latest_bulletin') or {}).get('notices',[])),
                   'forecast':copy.deepcopy(snapshot.get('latest_forecast'))}
        self.consecutive_reports=self.consecutive_reports+1 if action['action']=='report' else 0

    def summary(self):
        return {'enabled':self.enabled,'inserted_reports':self.inserted,'correct_reports':self.correct,
                'false_reports_since_correct':self.false_count,'config':self.cfg,'events':self.events,
                'latest_features':self.latest_features,'reads_truth':False,'reads_teacher_labels':False}


def make_policy_class(base,enabled=True,emit=None,config=None):
    class PersistentPolicy(base):
        def __init__(self,initial):
            super().__init__(initial)
            self.persistent_guard=PersistentFaultGuard(self,enabled,emit,config)
        def decide(self,snapshot):
            started=time.perf_counter(); g=self.persistent_guard
            if not g.enabled:return super().decide(snapshot)
            g.ingest(snapshot)
            if g.cached is not None:
                result=snapshot.get('last_result') or {}
                if result.get('correct') is False:
                    action=g.release_false(snapshot)
                elif result.get('correct') is True:
                    self.pending={'action':{'action':'report'}}
                    self.report_count+=1; self.last_report=parse_utc(snapshot['now_utc'])
                    g.cached=None; g.saved_pending=None; g.report_snapshot=None
                    g.event('persistent_correct_replanning',now_utc=snapshot['now_utc'],observe_action_index=snapshot['observe_action_index'])
                    action=super().decide(snapshot)
                else:raise RuntimeError('Missing diagnostic acknowledgement')
            else:
                action=super().decide(snapshot)
                action=g.propose(snapshot,action,started)
            g.sent(snapshot,action)
            return action
        def summary(self):
            return {**super().summary(),'persistent_fault_control':self.persistent_guard.summary()}
    return PersistentPolicy
