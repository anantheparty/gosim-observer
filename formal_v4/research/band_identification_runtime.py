"""Public-only, same-slot feasibility of clean <=120s hit feedback.

No files, truth, priors, seeds, network, or production mutations. The caller
supplies its public geometry H, exactly one scorer midpoint for accepted rows.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone


def utc(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)


def feasibility(records, scoring):
    settings=scoring['program'];bands=settings['bands'];bonuses=settings['multipliers']
    dark,bright=float(bands['DARK']),float(bands['BRIGHT'])
    mismatch=float(settings['mismatch_multiplier'])
    edges=sorted({0.,*(threshold/r['H'] for r in records for threshold in (bright,dark))})+[math.inf]
    states=[]
    for left,right in zip(edges,edges[1:]):
        c=(left+right)/2 if math.isfinite(right) else left+max(1.,left)
        zlo,zhi=0.,math.inf
        for r in records:
            q=c*r['H'];band='DARK' if q>=dark else 'BRIGHT' if q>=bright else 'BACKUP'
            m=float(bonuses[r['program']]) if r['program']==band else mismatch
            lo=max(0.,r['score']-.500001e-6)/r['weight']
            hi=(r['score']+.500001e-6)/r['weight']
            if lo>m:
                zlo,zhi=1.,0.;break
            zlo=max(zlo,lo/(m*r['a']))
            if hi<m:zhi=min(zhi,hi/(m*r['a']))
        clow=max(left,zlo)
        if zlo<=zhi and clow<right:
            states.append(dict(C_lower=clow,C_upper=right,Z_lower=zlo,Z_upper=zhi))
    return states


def allows_c(states,c):
    return any(s['C_lower']<=c<s['C_upper'] for s in states)


def contains(states,c,e):
    return any(s['C_lower']-1e-10<=c<s['C_upper']+1e-10
               and s['Z_lower']-1e-10<=c*e<=s['Z_upper']+1e-10 for s in states)


def log_projection(states,c,e):
    """Nearest(log C,log E) on each convex(log C,log Z) polygon."""
    u,v=math.log(c),math.log(e);candidates=[]
    for s in states:
        cl=math.log(s['C_lower']);ch=math.log(math.nextafter(s['C_upper'],0.)) if math.isfinite(s['C_upper']) else math.inf
        zl=math.log(s['Z_lower']);zh=math.log(s['Z_upper']) if math.isfinite(s['Z_upper']) else math.inf
        def add(x,z):
            if cl<=x<=ch and zl<=z<=zh and z<=x+1e-14:
                candidates.append(((x-u)**2+(z-x-v)**2,math.exp(x),math.exp(z-x)))
        def clip(x,a,b):return max(a,min(b,x))
        add(u,u+v)
        for x in (cl,ch):
            if math.isfinite(x) and zl<=min(zh,x):add(x,clip(x+v,zl,min(zh,x)))
        for z in (zl,zh):
            if math.isfinite(z) and max(cl,z)<=ch:add(clip((u+z-v)/2,max(cl,z),ch),z)
        if max(cl,zl)<=min(ch,zh):
            x=clip(u,max(cl,zl),min(ch,zh));add(x,x)
    if not candidates:return None
    _,cc,ee=min(candidates)
    return cc,min(1.,ee)


class PublicSlotConstraint:
    def __init__(self,initial):
        self.scoring=initial['scoring'];survey=initial['survey']
        self.seconds=int(survey['slot_seconds'])
        self.nights=[(n['night_id'],utc(n['observing_start_utc']),utc(n['observing_end_utc']),int(n['slot_count'])) for n in survey['nights']]
        self.key=None;self.records=[];self.states=[];self.latest=[];self.programs=set();self.indices=[]
        self.stats={}

    def count(self,name):self.stats[name]=self.stats.get(name,0)+1

    def clear(self):
        self.key=None;self.records=[];self.states=[];self.latest=[];self.programs=set();self.indices=[]

    def slot(self,moment):
        for nid,start,end,count in self.nights:
            if start<=moment<end:
                k=int((moment-start).total_seconds()//self.seconds)
                if k>=count:return None
                left=start+timedelta(seconds=k*self.seconds)
                return (nid,k,left,min(end,left+timedelta(seconds=self.seconds)))
        return None

    def ingest(self,start,end,program,index,hits,bulletin):
        """hits contain score/weight/flux/H from public catalog and geometry."""
        slot=self.slot(start)
        if not slot or end>slot[3] or end<=start:
            self.clear();self.count('cross_slot_or_invalid');return False
        key=slot[:2]
        if self.key!=key:self.clear()
        if not bulletin or utc(bulletin['issued_at_utc'])!=slot[2] or bulletin.get('night_id')!=slot[0] or bulletin.get('slot_id')!=f'{slot[0]}-S{slot[1]+1:03d}':
            self.clear();self.count('missing_or_mismatched_bulletin');return False
        if any(n.get('event_kind')!='terrain_obstruction' for n in bulletin.get('notices',[])):
            self.clear();self.count('event_notice');return False
        duration=(end-start).total_seconds()
        if duration>120:
            self.count('multiple_midpoints');return False
        denominator=float(self.scoring['flux_zero_point'])*float(self.scoring['exposure_zero_point_seconds'])
        records=[dict(score=float(h['score']),weight=float(h['weight']),H=float(h['H']),
                      a=float(h['flux'])*duration*float(h['H'])/denominator,program=program)
                 for h in hits if float(h['score'])-.500001e-6>0]
        if len(records)<3:
            self.count('few_positive_hits');return False
        self.key=key;self.latest=records;self.records+=records;self.indices.append(index);self.programs.add(program)
        self.states=feasibility(self.records,self.scoring)
        if not self.states:
            self.clear();self.count('empty_feasible_set');return False
        self.count('accepted')
        if len(self.indices)>1 and len(self.programs)>1:self.count('natural_multiprogram')
        return True

    def constrain(self,now,c,e):
        slot=self.slot(now)
        if not slot or self.key!=slot[:2]:
            self.clear();return None
        if len(self.indices)<2 or len(self.programs)<2 or allows_c(self.states,c):return None
        if not allows_c(feasibility(self.latest,self.scoring),c):
            self.count('current_fit_already_conflicts');return None
        projection=log_projection(self.states,c,e)
        if projection is not None:self.count('joint_only_conflicts')
        return projection
