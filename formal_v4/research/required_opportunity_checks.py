"""Validate public opportunity integration and upper envelopes against engine."""
import json,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'upstream/gosim-observer-examples/runner'))
from challenge.v4_scorer import SlotTruth,WeatherTruth,score_target_exposure
from challenge.v4_fiber_map import radec_to_altaz,min_altitude_during
from required_opportunity_model import RequiredOpportunityModel,public_initial


def checks():
    model=RequiredOpportunityModel(public_initial(Path(__file__).resolve().parents[1]/'practice_cards/delta/delta'))
    rng=np.random.default_rng(20261003);maxerr=0.;minmargin=float('inf');count=0
    for _ in range(200):
        i=int(rng.integers(len(model.ids)));night=int(rng.integers(len(model.nights)))
        wins=model.windows(i,night)
        if not wins:continue
        a,b=wins[int(rng.integers(len(wins)))];start=float(rng.uniform(a,b-model.tmin))
        duration=int(rng.integers(model.tmin,int(min(model.tmax,b-start))+1))
        startdt=datetime.fromtimestamp(start,timezone.utc);enddt=startdt+timedelta(seconds=duration)
        na,nb=model.nights[night]
        slots=[SlotTruth(str(j),datetime.fromtimestamp(t,timezone.utc),datetime.fromtimestamp(min(nb,t+900),timezone.utc),True,1.,1.,1.,.55)
               for j,t in enumerate(np.arange(na,nb,900))]
        weather=WeatherTruth(slots,None)
        target={'target_id':model.ids[i],'feature_flux':model.flux[i],'science_weight':1.,'ra_deg':model.ra[i],'dec_deg':model.dec[i]}
        score=score_target_exposure(target,list(weather.segments(startdt,enddt)),[],weather,duration,1.,model.score,startdt,
                  lambda t:radec_to_altaz(model.ra[i],model.dec[i],t,model.latitude,model.longitude),
                  {'latitude_deg':model.latitude,'longitude_deg':model.longitude})
        integral=model.exact_integrals(i,night,[start],[duration])[0]
        expected=.55*integral/duration
        maxerr=max(maxerr,abs(score.quality-expected))
        assert abs(score.quality-expected)<1e-8
        nodes,_,upper=model._night_cache(night)
        envelope=np.interp(start+duration,nodes,upper[:,i])-np.interp(start,nodes,upper[:,i])
        minmargin=min(minmargin,float(envelope-integral))
        assert envelope+1e-7>=integral
        # Public visibility interval must satisfy official whole-exposure altitude.
        assert min_altitude_during(model.ra[i],model.dec[i],startdt,enddt,
                                  {'site':{'latitude_deg':model.latitude,'longitude_deg':model.longitude}})>=model.minimum_altitude-1e-6
        count+=1
    # The very late faint target demonstrates quota != geometric >=60 seconds.
    p=model.profile(model.index['V4T008767'],len(model.nights)-1,site_scale=.55,duration_safety=1.1,exact_refine=True)
    assert p['frozen_checked_feasible'] and p['frozen_checked_factor']>.99
    return {'schema':'required-public-opportunity-checks-v1','official_engine_exposures':count,
            'max_quality_error':maxerr,'minimum_geometry_envelope_margin_seconds':minmargin,
            'whole_exposure_visibility':True,'single_exposure_quota_not_accumulated':True,
            'late_target_last_start':p['latest_checked_start_utc'],
            'scope':'synthetic weather scalar .55; public catalog/calendar/geometry only'}


if __name__=='__main__':
    result=checks();print(json.dumps(result,indent=2))
    Path(__file__).with_name('required_opportunity_checks_result.json').write_text(json.dumps(result,indent=2)+'\n')
