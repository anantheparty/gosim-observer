"""Actor-safe public score history and exact per-target quotient intervals."""
import math
import numpy as np
PROGRAMS=('DARK','BRIGHT','BACKUP')

class PublicHistory:
    def __init__(self):self.observations=[];self.reports=[]
    def observe(self,index,action,hits,start):
        lookup={str(h['target_id']):float(h['score']) for h in hits}
        tokens=[dict(target_id=tid,actual_hit=tid in lookup,
                     score_six_decimal=lookup.get(tid))
                for f,tid in sorted(action['assignments'].items(),key=lambda z:int(z[0]))]
        self.observations.append(dict(action_index=int(index),action=action,
                                      tokens=tokens,start=start,valid=True))
    def resync(self,message):
        w=message['invalidated_window']
        for o in self.observations:
            if w['action_index_start']<=o['action_index']<w['action_index_end_exclusive']:
                o['valid']=False
    def best(self):
        out={}
        for o in self.observations:
            if o['valid']:
                for t in o['tokens']:
                    if t['actual_hit']:out[t['target_id']]=max(out.get(t['target_id'],0.),t['score_six_decimal'])
        return out

def quotient_intervals(score,hit,weight,flux,duration,hbar,declared,scoring):
    """Three exact marginal band preimages; not a multi-slot joint posterior.

    Each band: log1p(lower), log1p(finite upper), unbounded upper, possible.
    Missing hits contribute no quality-zero likelihood.
    """
    out=np.zeros((3,4),np.float64)
    raw=[]
    if not hit or min(weight,flux,duration,hbar)<=0:return out.astype(np.float32),raw
    a=flux*duration*hbar/(scoring['flux_zero_point']*scoring['exposure_zero_point_seconds'])
    ylo=max(0.,score-.500001e-6);yhi=score+.500001e-6
    for bi,band in enumerate(PROGRAMS):
        m=float(scoring['program']['multipliers'][declared] if declared==band
                else scoring['program']['mismatch_multiplier']);wm=weight*m
        possible=ylo<=wm
        lo=ylo/(wm*a)
        hi=yhi/(wm*a) if yhi<wm else math.inf
        if possible:out[bi]=[math.log1p(lo),math.log1p(hi) if math.isfinite(hi) else 0.,not math.isfinite(hi),1.]
        raw.append(dict(band=band,possible=possible,lower=lo,
                        upper=hi if math.isfinite(hi) else None))
    return out.astype(np.float32),raw
