"""Finite Bellman checks and short official artificial score/geometry fixtures."""
from __future__ import annotations
import json, math, sys
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import numpy as np
from window_control import OutcomeModel, observable_posteriors, solve, expected_demand, query

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'formal_v4/upstream/gosim-observer-examples/runner'))
from challenge.v4_scorer import (WeatherTruth, SlotTruth, score_target_exposure,
    program_band, program_multiplier, lunar_quality_factor)
from challenge.v4_fiber_map import (FiberGrid, radec_to_altaz, altaz_to_radec,
    min_altitude_during)


def finite_checks():
    rng=np.random.default_rng(71903)
    pairs=np.array([[.2,.2],[.4,.4],[.6,.5],[.6,.6],[.8,.8],[1.2,1.]])
    maximum_error=0.; derivative_error=0.
    for case in range(100):
        ix=rng.integers(len(pairs),size=(2,2,2,3))
        c,g=pairs[ix,0],pairs[ix,1]
        model=OutcomeModel(c,g,np.full((2,2),.5),np.array([[60.,180.],[60.,180.]]),
            np.array([.45,1.,1.6]),np.array([0.,.4,2.]))
        price=np.array([.000231,.000473])*(1+case*.01)
        result=solve(model,price,score_bins=13,probability_bins=5)
        exact=[]
        for target in range(3):
            @lru_cache(None)
            def rec(k,b,p):
                if k == 2:
                    return model.weights[target]*b+model.required_bonus[target]*p
                answer=rec(k+1,b,p)
                for action in range(2):
                    score,tau=observable_posteriors(model,k,action)
                    value=sum(.5*rec(k+1,max(b,float(score[r,target])),
                                      p+(1-p)*float(tau[r,target])) for r in range(2))
                    value-=price[k]*model.durations[k,action]
                    answer=max(answer,value)
                return answer
            exact.append(rec(0,0.,0.))
        maximum_error=max(maximum_error,float(np.max(np.abs(result['value'][:,0,0]-exact))))
        demand=expected_demand(model,result)
        for k in range(2):
            eps=1e-8; q=price.copy();q[k]+=eps
            perturbed=solve(model,q,score_bins=13,probability_bins=5,keep_policy=False)
            derivative=(perturbed['value'][:,0,0].sum()-result['value'][:,0,0].sum())/eps
            derivative_error=max(derivative_error,abs(derivative+demand[k]))
    assert maximum_error < 1e-10, maximum_error
    assert derivative_error < 1e-5, derivative_error
    # Both worlds publish score .540000, yet raw completion differs.
    model=OutcomeModel(np.array([[[[.54],[.54]]]]),np.array([[[[.45],[.54]]]]),
        np.array([[.5,.5]]),np.array([[1800.]]),np.ones(1),np.ones(1)*50)
    observed,tau=observable_posteriors(model,0,0)
    assert np.all(observed==.54) and np.all(tau==.5)
    return dict(random_finite_cases=100,max_exact_error=maximum_error,
                max_demand_derivative_error=derivative_error,
                ambiguous_public_score=.54,latent_factors=[.45,.54],
                posterior_completion_given_score=float(tau[0,0]),
                prior_completion_probability=.2,
                posterior_historical_completion_probability=.2+.8*float(tau[0,0]))


def official_fixtures():
    base=ROOT/'formal_v4/practice_cards/delta/delta/config'
    config=json.loads((base/'v4_score_config.json').read_text())
    fiber=json.loads((base/'v4_fiber_config.json').read_text())
    site=fiber['site'];lat=site['latitude_deg'];lon=site['longitude_deg']
    grid=FiberGrid.from_config(fiber)
    start=datetime(2026,10,25,0,15,tzinfo=timezone.utc);duration=1800
    future=start+timedelta(hours=4)
    score_calls=[0,0]

    def score(target,t,transp=.85,sky=.95,eff=.95,enforce_altitude=True):
        score_calls[0]+=1
        end=t+timedelta(seconds=duration)
        if enforce_altitude and min_altitude_during(target['ra_deg'],target['dec_deg'],t,end,fiber)<30:
            return 0.,0.
        truth=SlotTruth('artificial',t,end,True,1.,transp,sky,eff)
        weather=WeatherTruth([truth],None)
        altaz=lambda moment:radec_to_altaz(target['ra_deg'],target['dec_deg'],moment,lat,lon)
        qband=weather.band_quality(t,end,config,lambda moment:altaz(moment)[0],
            lambda moment:lunar_quality_factor(target['ra_deg'],target['dec_deg'],moment,site,config))
        mult=program_multiplier('DARK',program_band(qband,config),config)
        score_calls[1]+=1
        answer=score_target_exposure(target,[(duration,truth)],[],weather,duration,mult,config,t,altaz,site)
        return answer.score,answer.factor

    # Make two real 16-fiber fields. The west field sets before the second stage.
    targets=[]
    for family,(alt,az),flux,weight in [('scarce',(50.,270.),.12,1.3),('repeatable',(50.,90.),.3,1.)]:
        a,z=map(math.radians,(alt,az))
        center=np.array([math.cos(a)*math.cos(z),math.cos(a)*math.sin(z),math.sin(a)])
        up=np.array([-math.sin(a)*math.cos(z),-math.sin(a)*math.sin(z),math.cos(a)])
        right=np.array([-math.sin(z),math.cos(z),0.])
        for f in range(16):
            da,dz=grid.fiber_center_offset(f)
            v=center+up*math.radians(da)+right*math.radians(dz);v/=np.linalg.norm(v)
            ta=math.degrees(math.asin(v[2]));tz=math.degrees(math.atan2(v[1],v[0]))%360
            ra,dec=altaz_to_radec(ta,tz,start,lat,lon)
            target=dict(target_id=f'{family}_{f}',ra_deg=ra,dec_deg=dec,
                        feature_flux=flux,science_weight=weight,required=False)
            classified=grid.classify_target(ra,dec,start,alt,az,lat,lon)
            assert classified.region=='glass' and classified.fiber_id==f
            targets.append(target)
    now=np.array([score(t,start)[0] for t in targets])
    later=np.array([score(t,future)[0] for t in targets])
    # A future alt/az grid has a different roll. Reclassify EVERY future hit and
    # retain only one target per real fiber instead of assuming 16 tracked hits.
    cra,cdec=altaz_to_radec(50.,90.,start,lat,lon)
    f_alt,f_az=radec_to_altaz(cra,cdec,future,lat,lon)
    per_fiber={}
    for i,target in enumerate(targets):
        cl=grid.classify_target(target['ra_deg'],target['dec_deg'],future,f_alt,f_az,lat,lon)
        if cl.region=='glass' and later[i]>0:
            previous=per_fiber.get(cl.fiber_id)
            if previous is None or later[i]>later[previous]:per_fiber[cl.fiber_id]=i
    legal_later=np.zeros(32)
    for i in per_fiber.values():legal_later[i]=later[i]
    later=legal_later
    weights=np.array([t['science_weight'] for t in targets])
    factors=np.zeros(32)
    for i in per_fiber.values():factors[i]=score(targets[i],future)[1]
    model=OutcomeModel((later/weights)[None,None,None,:],factors[None,None,None,:],
        np.ones((1,1)),np.array([[duration]]),weights,np.zeros(32))
    continuation=solve(model,[0.],score_bins=121,probability_bins=3,keep_suffix=True)
    b0=np.zeros(32);p0=np.zeros(32)
    before=query(continuation['value'],b0,p0,continuation['score_grid'],continuation['probability_grid'])
    after=query(continuation['value'],now/weights,p0,continuation['score_grid'],continuation['probability_grid'])
    raw_sums=[float(now[:16].sum()),float(now[16:].sum())]
    tail_sums=[float((after-before)[:16].sum()),float((after-before)[16:].sum())]
    plan_scarce=float(np.maximum(np.r_[now[:16],np.zeros(16)],later).sum())
    plan_repeatable=float(np.maximum(np.r_[np.zeros(16),now[16:]],later).sum())
    assert raw_sums[1]>raw_sums[0] and tail_sums[0]>tail_sums[1]
    assert plan_scarce>plan_repeatable

    # Official scorer collision: DARK match*g=.45 and mismatch*g=.54.
    ra,dec=altaz_to_radec(70.,180.,start,lat,lon)
    target=dict(target_id='ambiguous',ra_deg=ra,dec_deg=dec,feature_flux=.3,
                science_weight=1.,required=True)
    unity=SlotTruth('basis',start,start+timedelta(seconds=duration),True,1.,1.,1.,1.)
    basis=WeatherTruth([unity],None)
    altaz=lambda moment:radec_to_altaz(ra,dec,moment,lat,lon)
    h=basis.band_quality(start,start+timedelta(seconds=duration),config,
       lambda moment:altaz(moment)[0],lambda moment:lunar_quality_factor(ra,dec,moment,site,config))
    collide=[]
    for qband,factor in [(.8,.45),(.5,.54)]:
        sky=qband/h;eff=factor*450/(.3*duration*qband)
        assert 0<sky<=1 and 0<eff<=1
        s,g=score(target,start,transp=1.,sky=sky,eff=eff)
        collide.append(dict(score=s,raw_factor=g,band_quality=qband,efficiency=eff))
    assert round(collide[0]['score'],6)==round(collide[1]['score'],6)==.54
    assert collide[0]['raw_factor']<.5<=collide[1]['raw_factor']
    return dict(geometry_current_glass_hits_checked=32,
        geometry_future_candidates_reclassified=32,
        geometry_future_glass_hits_checked=len(per_fiber),
        future_pointing=dict(alt_deg=f_alt,az_deg=f_az),
        future_assignment={str(f):targets[i]['target_id'] for f,i in per_fiber.items()},
        score_attempts=score_calls[0],official_score_kernel_calls=score_calls[1],
        current_field_science=raw_sums,continuation_marginal=tail_sums,
        fixed_two_stage_science=[plan_scarce,plan_repeatable],
        scarce_first_advantage=plan_scarce-plan_repeatable,
        official_ambiguous_raw_collision=collide,
        interpretation='artificial public geometry and declared deterministic future; mechanism check only')


def main():
    result=dict(finite=finite_checks(),official=official_fixtures(),
                truth_input_files_read=[],full_season=False,deployed=False)
    Path(__file__).with_name('checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
