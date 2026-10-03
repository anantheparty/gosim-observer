"""Small gates: official scorer + synthetic quality cells, never hidden files."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'upstream/gosim-observer-examples/runner'))
from challenge.v4_scorer import SlotTruth, WeatherTruth, ScoreEvent, score_target_exposure
from challenge.v4_fiber_map import radec_to_altaz
from quality_profile_inversion import (all_target_model,PublicQualityMatrix,propagate_intervals,
                                      fit_nonnegative_profile,ROUNDING_RADIUS,GEOMETRY_GUARD)


def check():
    model=all_target_model(HERE.parent/'practice_cards/delta/delta')
    rng=np.random.default_rng(20261003)
    worst=0.;cap_quality_examples=0;count=0
    for _ in range(40):
        night=int(rng.integers(len(model.nights)))
        a,b=model.nights[night]
        z=rng.uniform(.15,1.35,len(np.arange(a,b,900)))
        slots=[SlotTruth(str(j),datetime.fromtimestamp(t,timezone.utc),datetime.fromtimestamp(min(t+900,b),timezone.utc),
                         True,1.,1.,float(z[j]),1.) for j,t in enumerate(np.arange(a,b,900))]
        weather=WeatherTruth(slots,None)
        i=int(rng.integers(len(model.ids)))
        wins=model.windows(i,night)
        if not wins:continue
        left,right=wins[0]
        start=float(rng.uniform(left,right-60));duration=int(rng.integers(60,int(min(3600,right-start))+1))
        matrix=PublicQualityMatrix(model)
        cells,coeff=matrix.coefficients(start,duration,[i])
        zcells=np.array([z[matrix.slots[matrix.cells[c][1]][1]] for c in cells])
        expected=float(coeff[0]@zcells)
        sd=datetime.fromtimestamp(start,timezone.utc);ed=sd+timedelta(seconds=duration)
        target=dict(target_id=model.ids[i],ra_deg=model.ra[i],dec_deg=model.dec[i],feature_flux=100.,science_weight=1.)
        scored=score_target_exposure(target,list(weather.segments(sd,ed)),[],weather,duration,1.,model.score,sd,
                                    lambda t:radec_to_altaz(model.ra[i],model.dec[i],t,model.latitude,model.longitude),
                                    dict(latitude_deg=model.latitude,longitude_deg=model.longitude))
        worst=max(worst,abs(scored.quality-expected));assert abs(scored.quality-expected)<1e-8
        if scored.factor==1 and scored.quality>1:cap_quality_examples+=1
        count+=1

    # One-cell rows identify a site product even when the target's factor was 1.
    co=np.array([1.4,1.2,.9]);truth=np.array([.8,.8,.8]);q=np.round(co*truth,6)
    bounds=propagate_intervals(np.arange(3),np.zeros(3,int),co,q,1)
    assert bounds['lower'][0]<=.8<=bounds['upper'][0]
    assert bounds['upper'][0]-bounds['lower'][0]<1e-6
    assert float(np.max(q))>1

    # All rows proportional to [1,1] identify only one aggregate, not two slots.
    rows=np.repeat(np.arange(3),2);cols=np.tile([0,1],3)
    vals=np.repeat([.5,.7,.9],2);quality=np.array([.5,.7,.9])
    alias=propagate_intervals(rows,cols,vals,quality,2)
    assert np.linalg.matrix_rank(np.array([[.5,.5],[.7,.7],[.9,.9]]))==1
    assert np.all(alias['upper']-alias['lower']>.5)
    nnls=fit_nonnegative_profile(rows,cols,vals,quality,2)
    assert nnls['max_abs_residual']<1e-9
    assert np.max(np.abs(np.array([[.5,.5],[.7,.7],[.9,.9]])@np.array([.2,.8])-quality))<1e-12

    # A repaired efficiency changes within a 900s slot, requiring separate cells.
    a,b=model.nights[0];repair=a+450
    repaired=PublicQualityMatrix(model,[repair]);plain=PublicQualityMatrix(model)
    i=model.index['V4T004699']
    c1,h1=repaired.coefficients(a+120,120,[i]);c2,h2=repaired.coefficients(a+600,120,[i])
    assert c1[0]!=c2[0]
    cp1,hp1=plain.coefficients(a+120,120,[i]);cp2,hp2=plain.coefficients(a+600,120,[i])
    assert cp1[0]==cp2[0]
    assert abs(float(h1.sum())-float(hp1.sum()))<1e-12

    # Zero directional terrain and zero background quality are observationally
    # indistinguishable for the covered track. A positive clean neighbour adds
    # evidence, but a single zero must not be hard classified as global closure.
    sd=datetime.fromtimestamp(a,timezone.utc);ed=sd+timedelta(seconds=900)
    slot=SlotTruth('zero-confound',sd,ed,True,1.,1.,1.,1.)
    event=ScoreEvent('synthetic','terrain_obstruction',sd,ed,'HORIZON_SECTOR',0.,360.,0.,90.,1.,1.,1.,1.)
    target=dict(target_id=model.ids[i],ra_deg=model.ra[i],dec_deg=model.dec[i],feature_flux=100.,science_weight=1.)
    def score(truth,events):
        w=WeatherTruth([truth],None)
        return score_target_exposure(target,list(w.segments(sd,ed)),events,w,900,1.,model.score,sd,
                       lambda t:radec_to_altaz(model.ra[i],model.dec[i],t,model.latitude,model.longitude),
                       dict(latitude_deg=model.latitude,longitude_deg=model.longitude)).quality
    closed=SlotTruth('closed',sd,ed,False,1.,1.,1.,1.)
    assert score(slot,[event])==score(closed,[])==0
    assert score(slot,[])>0
    return {'schema':'quality-inversion-small-gates-v1','official_synthetic_exposures':count,
            'maximum_official_quality_error':worst,'factor_capped_and_quality_over_one_examples':cap_quality_examples,
            'one_cell_rounding_interval_width':float(bounds['upper'][0]-bounds['lower'][0]),
            'two_slot_proportional_rank':1,'zero_direction_background_confounding':True,
            'repair_mid_slot_requires_split':True,'NNLS_zero_residual_does_not_prove_uniqueness':True,
            'scope':'synthetic engine variables constructed in memory + public catalog/calendar only'}


if __name__=='__main__':
    result=check();print(json.dumps(result,indent=2))
    HERE.joinpath('quality_profile_inversion_checks_result.json').write_text(json.dumps(result,indent=2)+'\n')
