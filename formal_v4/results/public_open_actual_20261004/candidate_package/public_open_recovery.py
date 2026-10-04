"""Reuse an existing whole-slot public positive: no diagnostic exposure is added.

Global observability is certified from official slot semantics. Static terrain
clearance is conditional on the SAME reference domain as production terrain
prediction, whose maximum height is checked over the entire remaining interval.
This is a candidate, not a proof of total-score improvement (rank loss/Jain).
"""
import json, sys, time
from datetime import datetime, timedelta
import numpy as np
from research.geometry import parse_utc, format_utc, local_sidereal_deg

def public_slot(actor, moment):
    p=actor.planner
    ni=actor._night(moment)
    if ni<0:return None
    a,b=p.nights[ni]
    si=int((moment-a).total_seconds()//actor.slot_seconds)
    left=a+timedelta(seconds=si*actor.slot_seconds)
    return ni,si,left,min(b,left+timedelta(seconds=actor.slot_seconds),actor.survey_end)

def minimum_altitudes(p, start, end):
    """Vectorization of official v4_fiber_map.min_altitude_during, incl. nadir."""
    a,_,_,_=p._altaz(local_sidereal_deg(start,p.lon))
    b,_,_,_=p._altaz(local_sidereal_deg(end,p.lon))
    minimum=np.minimum(a,b)
    hour=(local_sidereal_deg(start,p.lon)-p.ra)%360.
    sweep=360.98564736629*(end-start).total_seconds()/86400.
    crosses=(180.-hour)%360.<=sweep
    lower=np.degrees(np.arcsin(np.clip(p.sin_lat*p.sin_dec-p.cos_lat*p.cos_dec,-1,1)))
    return np.where(crosses,np.minimum(minimum,lower),minimum)

def install(base, terrain_base):
    old_ingest=base._ingest_result;old_messages=base._messages;old_decide=base.decide;old_summary=base.summary
    old_scale=terrain_base._target_scale

    def ingest(self,snapshot):
        pending=self.pending
        result=snapshot.get('last_result') or {}
        if pending and pending.get('action',{}).get('action')=='observe' and result.get('action')=='observe':
            start=pending['start'] if isinstance(pending['start'],datetime) else parse_utc(pending['start']);end=parse_utc(snapshot['now_utc'])
            slot=public_slot(self,start)
            if slot and start<end<=slot[3]:
                positive=[h for h in result.get('hits',[]) if float(h.get('score',0))>0]
                if positive:
                    self._public_open_slot=slot[:2]
                    self._public_open_anchor=dict(observe_index=int(result['observe_index']),start_utc=format_utc(start),end_utc=format_utc(end),positive_hits=len(positive))
                elif result.get('hits'):
                    self._last_local_zero_slot=slot[:2]
        return old_ingest(self,snapshot)

    def messages(self,snapshot):
        answer=old_messages(self,snapshot)
        if not getattr(self,'public_open_recovery_enabled',True) or not self.last_closed:return answer
        now=parse_utc(snapshot['now_utc']);slot=public_slot(self,now)
        if not slot or slot[:2]!=getattr(self,'_public_open_slot',None) or slot[:2]!=getattr(self,'_last_local_zero_slot',None):return answer
        if snapshot.get('active_requests'):return answer  # REQ controller/cache stays untouched.
        if any(n.get('event_kind') not in ('terrain_obstruction','earthquake') for n in self.notices):return answer
        remaining=int((slot[3]-now).total_seconds())
        if remaining<self.planner.tmin:return answer
        terrain=getattr(self,'terrain_model',None)
        if terrain is None or terrain.domain_conflicts:return answer
        started=time.perf_counter()
        height=max((float(np.max(terrain.h_hi[a])) for a in terrain.active.values() if np.any(a)),default=0.)
        mins=minimum_altitudes(self.planner,now,slot[3])
        clear=mins>height+1e-7
        if not np.any(clear):return answer
        self._public_open_recovery_mask=clear
        self._public_open_recovery_until=slot[3]
        self.planner.tmax=min(self.planner.tmax,remaining)
        self.last_closed=False
        self._public_open_recovery_event=dict(now_utc=snapshot['now_utc'],observe_action_index=int(snapshot['observe_action_index']),
            public_anchor=self._public_open_anchor,slot_end=format_utc(slot[3]),recoverable_seconds=remaining,
            terrain_maximum_height_conditional_deg=height,clear_targets=int(clear.sum()),geometry_seconds=time.perf_counter()-started,
            clearance_scope='existing production reference terrain domain, not a universal protocol bound')
        return answer

    def scale(self,now):
        result=old_scale(self,now)
        mask=getattr(self,'_public_open_recovery_mask',None)
        return result if mask is None else result*mask

    def decide(self,snapshot):
        original_tmax=self.planner.tmax
        self._public_open_recovery_mask=None;self._public_open_recovery_event=None
        try:
            action=old_decide(self,snapshot)
            event=self._public_open_recovery_event
            if event:
                if action.get('action')=='observe':
                    indices=[self.planner.index[t] for t in action['assignments'].values()]
                    if not all(self._public_open_recovery_mask[indices]):raise RuntimeError('Recovery assigned an uncertified trajectory')
                    now=parse_utc(snapshot['now_utc'])
                    if now+timedelta(seconds=action['duration_seconds'])>self._public_open_recovery_until:raise RuntimeError('Recovery crossed certified slot')
                elif action.get('action')=='wait':
                    action={'action':'wait','until_utc':format_utc(self._public_open_recovery_until)};self.pending=None
                record={**event,'action':action}
                self.public_open_recovery_events=getattr(self,'public_open_recovery_events',[])+[record]
                print(json.dumps({'event':'public_open_recovery',**record},separators=(',',':'),allow_nan=False),file=sys.stderr,flush=True)
            return action
        finally:
            self.planner.tmax=original_tmax;self._public_open_recovery_mask=None

    def summary(self):
        return {**old_summary(self),'public_open_recovery':{'events':getattr(self,'public_open_recovery_events',[]),
            'reads_future_truth':False,'pure_probe_inserted':False,'terrain_clearance_conditional_on_existing_production_domain':True}}

    base._ingest_result=ingest;base._messages=messages;base.decide=decide;base.summary=summary
    terrain_base._target_scale=scale
