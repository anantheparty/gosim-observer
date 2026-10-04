"""Host-only independent audit of sufficient quality integrals.

No actual local-card truth is read. Every scoring truth used below is constructed
from explicit test values or a new official generator world.
"""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import sys, json, math, hashlib
import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
OFFICIAL = REPO / 'formal_v4/runs/official_generator_e01939d0'
sys.path.insert(0, str(OFFICIAL))
from challenge.v4_scorer import (SlotTruth, ScoreEvent, WeatherTruth,
    score_target_exposure, program_band, program_multiplier, lunar_quality_factor)
from challenge.v4_fiber_map import altaz_to_radec, radec_to_altaz
from challenge.tile_geometry_simulator import _normalized_airmass


def integral_weights(start, end, origin, target, site, config, events=()):
    """Two public/conditional path weights; cuts match official q-band and q-exp.

    Directional event times/scopes are scenario variables, not actor input.
    Their cuts affect q-exp and never q-band. All five weather slots are kept.
    """
    seconds = int((end-start).total_seconds())
    K = int(math.ceil((end-origin).total_seconds()/900))
    qb = np.zeros(K); qe = np.zeros(K)
    for kind, out in [('band', qb), ('exp', qe)]:
        cursor = start
        while cursor < end:
            k = int((cursor-origin).total_seconds()//900)
            right = min(end, origin+timedelta(seconds=900*(k+1)))
            cuts = {cursor, right}
            if kind == 'exp':
                for event in events:
                    if cursor < event.actual_start_utc < right: cuts.add(event.actual_start_utc)
                    if cursor < event.actual_end_utc < right: cuts.add(event.actual_end_utc)
            boundaries = sorted(cuts)
            for a,b in zip(boundaries,boundaries[1:]):
                piece=a
                while piece < b:
                    r=min(b,piece+timedelta(seconds=120)); mid=piece+(r-piece)/2
                    alt,az=radec_to_altaz(target['ra_deg'],target['dec_deg'],mid,
                                        site['latitude_deg'],site['longitude_deg'])
                    h=lunar_quality_factor(target['ra_deg'],target['dec_deg'],mid,site,config)
                    h/=_normalized_airmass(alt)**float(config['airmass_exponent'])
                    scale=1.
                    if kind=='exp':
                        for event in events:
                            if event.actual_start_utc<=mid<event.actual_end_utc and event.covers_altaz(alt,az):
                                if event.force_close or event.event_type in ('rocket_launch','terrain_obstruction'):
                                    scale=0.
                                elif event.event_type in ('rainy','cloudy','smoggy','cold_wave','tornado'):
                                    scale*=event.transparency_multiplier*event.sky_quality_multiplier*event.instrument_efficiency_multiplier/event.seeing_multiplier
                    out[k]+=(r-piece).total_seconds()*h*scale/seconds
                    piece=r
            cursor=right
    return qb,qe


def settle(c,z,opened,hb,he,flux,weight,best,duration,declared,config):
    """Expectation is taken only after cap, band and positive best increment."""
    b=np.asarray(c*opened)@hb; e=np.asarray(z*opened)@he
    factor=np.minimum(1.,flux*duration*e/450.)
    band=np.where(b>=.65,0,np.where(b>=.4,1,2))
    mult=np.where(band==declared,[1.2,1.12,1.06][declared],1.)
    return np.maximum(0.,weight*factor*mult-best),factor,b


def main():
    config=json.loads((OFFICIAL/'challenge/reference/v4/v4_score_config.json').read_text())
    site={'latitude_deg':-24.6157,'longitude_deg':-70.3976}
    origin=datetime(2026,11,7,1,tzinfo=timezone.utc)
    rng=np.random.default_rng(869401)
    cases=[]; max_factor=max_band=max_gain=0.
    for n in range(160):
        frac=int(rng.integers(0,900)); duration=int(rng.integers(60,3601))
        start=origin+timedelta(seconds=frac);end=start+timedelta(seconds=duration)
        alt=float(rng.uniform(30,89));az=float(rng.uniform(0,360))
        ra,dec=altaz_to_radec(alt,az,start,site['latitude_deg'],site['longitude_deg'])
        target={'target_id':'audit','ra_deg':ra,'dec_deg':dec,'feature_flux':float(rng.uniform(.03,2.5)),
                'science_weight':float(rng.uniform(.3,1.7))}
        slots=[]
        for k in range(5):
            op=bool(rng.random()>.1)
            slots.append(SlotTruth(str(k),origin+timedelta(seconds=900*k),origin+timedelta(seconds=900*(k+1)),
                                  op,float(rng.uniform(.5,2.)),float(rng.uniform(.2,1.)),
                                  float(rng.uniform(.2,1.5)),float(rng.uniform(.1,1.))))
        events=[]
        if n%3:
            a=start+timedelta(seconds=int(duration*.27));b=start+timedelta(seconds=int(duration*.73))
            events=[ScoreEvent('cut','cloudy' if n%3==1 else 'rocket_launch',a,b,'HORIZON_SECTOR',
                              (az-70)%360,(az+70)%360,0.,80.,1.3,.65,.7,1.,n%3==2)]
        weather=WeatherTruth(slots,None);segments=list(weather.segments(start,end))
        hb,he=integral_weights(start,end,origin,target,site,config,events)
        c=np.array([s.transparency*s.sky_quality/(s.seeing_arcsec*config['q0']) for s in slots[:len(hb)]])
        z=c*np.array([s.instrument_efficiency for s in slots[:len(hb)]])
        opened=np.array([s.is_observable for s in slots[:len(hb)]],float)
        actual=weather.band_quality(start,end,config,
            lambda t:radec_to_altaz(ra,dec,t,site['latitude_deg'],site['longitude_deg'])[0],
            lambda t:lunar_quality_factor(ra,dec,t,site,config))
        max_band=max(max_band,abs(actual-float((c*opened)@hb)))
        for declared in range(3):
            prog=['DARK','BRIGHT','BACKUP'][declared]
            mult=program_multiplier(prog,program_band(actual,config),config)
            score=score_target_exposure(target,segments,events,weather,duration,mult,config,start,
              lambda t:radec_to_altaz(ra,dec,t,site['latitude_deg'],site['longitude_deg']),site)
            best=float(rng.uniform(0,1.5));value,factor,band=settle(c,z,opened,hb,he,target['feature_flux'],target['science_weight'],best,duration,declared,config)
            max_factor=max(max_factor,abs(score.factor-float(factor)))
            max_gain=max(max_gain,abs(max(0,score.score-best)-float(value)))
        cases.append({'altitude_start':alt,'duration':duration,'slots':len(hb),'directional':bool(events)})
    # A mixed path versus a mean path can select different program AND duration.
    c=np.array([[.25],[.95]]);z=np.array([[.2375],[.9025]]);opened=np.ones_like(c)
    durations=np.arange(60,901);menu=[]
    for d in durations:
        for p in range(3):
            gain,*_=settle(c,z,opened,[1.],[1.],.5,1.,.35,int(d),p,config)
            plug,*_=settle(c.mean(0,keepdims=True),z.mean(0,keepdims=True),opened.mean(0,keepdims=True),
                           [1.],[1.],.5,1.,.35,int(d),p,config)
            menu.append([int(d),p,float(gain.mean()/d),float(plug.mean()/d)])
    arr=np.array(menu); expected=arr[arr[:,2].argmax()];mean=arr[arr[:,3].argmax()]
    result={'official_commit':'e01939d0','cases':len(cases),'scores':3*len(cases),
      'max_factor_error':max_factor,'max_band_error':max_band,'max_gain_error':max_gain,
      'altitude_min':min(x['altitude_start'] for x in cases),'five_slot_cases':sum(x['slots']==5 for x in cases),
      'directional_cases':sum(x['directional'] for x in cases),'expectation_duration_program':expected.tolist(),
      'mean_duration_program':mean.tolist(),'same_slot_example_has_duration_change':expected[0]!=mean[0],
      'scope':'Exact official algebra for constructed truth paths; no actor posterior or production improvement'}
    assert max(max_factor,max_band,max_gain)<1e-12
    (ROOT/'integral_audit.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))

if __name__=='__main__':main()
