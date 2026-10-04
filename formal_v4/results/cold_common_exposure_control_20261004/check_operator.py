"""Independent finite enumeration and synthetic official-integrator checks."""
import itertools, json, sys
from types import SimpleNamespace
from datetime import timedelta
import numpy as np
import common_exposure as c

class Toy:
    def __init__(self,start,d,idx,ss,fiber=None):
        self.start,self.duration,self.idx=start,d,np.array(idx,int)
        self.ss=np.array(ss,float);self.action=dict(action='observe',duration_seconds=d)
        self.fiber=np.arange(len(idx)) if fiber is None else np.array(fiber,int)
    def outcomes(self,p,env,scale=1.):return self.ss*scale,np.zeros(len(self.idx))

def enumeration(arcs,initial,first=None,blocked=0):
    base=initial.copy()
    if first:
        np.maximum.at(base,first.idx,first.ss);blocked=first.duration
    best=-1.;path=None
    for mask in range(1<<len(arcs)):
        selected=[a for k,a in enumerate(arcs) if mask>>k&1]
        if any(a.start<blocked for a in selected):continue
        selected.sort(key=lambda a:a.start)
        if any(a.start+a.duration>b.start for a,b in zip(selected,selected[1:])):continue
        cells=[[(int(a.idx[pos]),float(a.ss[pos])) for pos in np.flatnonzero(a.fiber==f)]
               for a in selected for f in np.unique(a.fiber)]
        for matching in itertools.product(*cells):
            s=base.copy()
            for i,cost in matching:s[i]=max(s[i],cost)
            v=float(s.sum()-initial.sum())
            if v>best:best=v;path=selected
    return best

def main():
    p=SimpleNamespace(n=3,ids=['A','B','C'])
    arcs=[Toy(0,60,[0,1],[.8,.4]),Toy(0,120,[2],[1.]),Toy(60,60,[0,2],[.9,.6]),
          Toy(120,60,[1],[1.]),Toy(60,120,[1,2],[.9,.9])]
    collision=[Toy(0,60,[0,1],[.8,.7],[0,0]),Toy(60,60,[0,2],[.9,.8],[0,0]),
               Toy(120,60,[1,2],[1.,.9],[0,0]),Toy(0,120,[1,2],[.9,.9],[0,1])]
    rows=[]
    for family,aa in (('distinct_fibres',arcs),('same_fibre_competition',collision)):
        for initial in (np.zeros(3),np.array([.5,.2,.1])):
            for first in (None,Toy(0,60,[0],[.7]),Toy(0,120,[0],[.9])):
                r=c.solve(p,aa,initial,np.zeros(3),{},first=first,time_limit=8)
                e=enumeration(aa,initial,first)
                assert r['optimal'] and abs(r['value']-e)<1e-9,(r,e)
                rows.append(dict(family=family,initial=initial.tolist(),first_duration=first.duration if first else None,
                                 enumerated=e,milp=r['value']))
    sys.path.insert(0,str(c.BASE/'upstream/gosim-observer-examples'))
    from runner.challenge.v4_fiber_map import FiberGrid, radec_to_altaz
    from runner.challenge.v4_scorer import WeatherTruth, SlotTruth, score_target_exposure, program_band,program_multiplier
    init=c.initial('L1');pl=c.entry.ExactCachedRequestPolicy(init).planner
    start=pl.nights[7][0]+timedelta(seconds=3600)
    alt=pl._altaz(c.local_sidereal(start,pl.lon))[0]
    indices=np.flatnonzero(alt>60)[:8]
    field=SimpleNamespace(raw_scale_at=lambda t:np.ones(pl.n))
    check=[];C=.65;E=.95
    for d in (300,900,1800):
        H,rawH,_=c.integration(pl,start,d,field)
        slots=[SlotTruth('SYNTHETIC',start+timedelta(seconds=t),start+timedelta(seconds=min(t+900,d)),True,1.,C,1.,E)
               for t in range(0,d,900)]
        weather=WeatherTruth(slots,None);segments=list(weather.segments(start,start+timedelta(seconds=d)))
        for i in indices:
            target=dict(target_id=pl.ids[i],ra_deg=pl.ra[i],dec_deg=pl.dec[i],feature_flux=pl.flux[i],science_weight=pl.weight[i])
            def at(t):return radec_to_altaz(pl.ra[i],pl.dec[i],t,pl.lat,pl.lon)
            bandq=weather.band_quality(start,start+timedelta(seconds=d),init['scoring'],lambda t:at(t)[0],
                lambda t:__import__('runner.challenge.v4_scorer',fromlist=['lunar_quality_factor']).lunar_quality_factor(pl.ra[i],pl.dec[i],t,init['site'],init['scoring']))
            for prog in range(3):
                mult=program_multiplier(c.PROGRAMS[prog],program_band(bandq,init['scoring']),init['scoring'])
                actual=score_target_exposure(target,segments,[],weather,d,mult,init['scoring'],start,at,init['site'])
                predicted_raw=min(1.,pl.flux[i]*d*rawH[i]*C*E/pl.f0t0)
                pb=0 if H[i]*C>=pl.dark_threshold else 1 if H[i]*C>=pl.bright_threshold else 2
                predicted=pl.weight[i]*predicted_raw*(pl.multipliers[prog] if prog==pb else pl.mismatch)
                error=abs(actual.score-predicted)
                assert error<1e-8,(i,d,prog,error)
                check.append(error)
    c.dump(c.OUT/'checks.json',dict(enumeration=rows,synthetic_official_integrations=len(check),
        max_score_error=max(check),synthetic_weather_only=True,actual_truth_read=False))
    print(json.dumps(dict(enumeration=len(rows),synthetic_integrations=len(check),max_error=max(check))))

if __name__=='__main__':main()
