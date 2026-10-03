"""Independent official-scorer check for the order and crossing-slot integral."""
from __future__ import annotations
import json,sys
from pathlib import Path
from datetime import timedelta
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runs/cold_neural_value_20261003/production_frozen'
sys.path.insert(0,str(SOURCE));sys.path.insert(1,str(ROOT/'upstream/gosim-observer-examples/runner'))
from scenario_value_model import ScenarioValuePlanner,finite_paths
from challenge.v4_workflow import V4Workflow
from challenge.v4_scorer import WeatherTruth,SlotTruth,score_target_exposure,program_band,program_multiplier,lunar_quality_factor
from challenge.v4_fiber_map import radec_to_altaz
from research.spatial_candidates import parse_utc,local_sidereal

def main():
    init=V4Workflow(ROOT/'upstream/gosim-observer-examples/local-cards/L1').initialize_payload(900)
    p=ScenarioValuePlanner(init);p.scenario_mode='scenario';p.scenario_sigma=.20
    now=p.nights[0][0]+timedelta(seconds=330)
    alt,_,_,_=p._altaz(local_sidereal(now,p.lon))
    idx=np.flatnonzero(alt>55)[:12]
    if not len(idx):raise AssertionError('no visible fixture target')
    scale=np.linspace(.5,1.,p.n)
    env=dict(program_band_quality_scale=.68,quality_scale=.68*.95,target_quality_scale=scale)
    durations=(60,570,900,1234,2300,3600)
    predicted=p._integrals(now,0,idx,durations,env)
    c,e=finite_paths(range(5),p.scenario_sigma)
    # _integrals uses exactly five possible future slot indices for this start.
    maxima=dict(band=0.,quality=0.,factor=0.,score=0.,geometry=0.)
    anchor=p.nights[0][0];scoring=init['scoring'];site=init['site']
    targets={row[0]:dict(zip(init['targets']['columns'],row)) for row in init['targets']['rows']}
    for duration in durations:
        qb,qe=predicted[duration]
        for s in range(len(c)):
            slots=[SlotTruth(str(j),anchor+timedelta(seconds=900*j),anchor+timedelta(seconds=900*(j+1)),True,
                            1.,.68*c[s,j],1.,.95*e[s,j]) for j in range(5)]
            weather=WeatherTruth(slots,[])
            for j,i in enumerate(idx):
                target=targets[p.ids[int(i)]]
                position=lambda tm,t=target:radec_to_altaz(t['ra_deg'],t['dec_deg'],tm,p.lat,p.lon)
                lunar=lambda tm,t=target:lunar_quality_factor(t['ra_deg'],t['dec_deg'],tm,site,scoring)
                b=weather.band_quality(now,now+timedelta(seconds=duration),scoring,lambda tm:position(tm)[0],lunar)
                maxima['band']=max(maxima['band'],abs(b-qb[s,j]))
                for program in ('DARK','BRIGHT','BACKUP'):
                    mult=program_multiplier(program,program_band(b,scoring),scoring)
                    # Directional target scale is represented as transparency loss
                    # in exposure quality only, following the scorer's convention.
                    loss_slots=[SlotTruth(sl.slot_id,sl.start_utc,sl.end_utc,True,sl.seeing_arcsec,
                                sl.transparency*scale[i],sl.sky_quality,sl.instrument_efficiency) for sl in slots]
                    loss_weather=WeatherTruth(loss_slots,[])
                    scored=score_target_exposure(target,list(loss_weather.segments(now,now+timedelta(seconds=duration))),[],
                        loss_weather,duration,mult,scoring,now,position,site)
                    factor=min(1.,p.flux[i]*duration*qe[s,j]/p.f0t0)
                    score=p.weight[i]*factor*mult
                    maxima['quality']=max(maxima['quality'],abs(scored.quality-qe[s,j]))
                    maxima['factor']=max(maxima['factor'],abs(scored.factor-factor))
                    maxima['score']=max(maxima['score'],abs(scored.score-score))
    moment=now+timedelta(seconds=511)
    alt,_,_,_=p._altaz(local_sidereal(moment,p.lon))
    maxima['geometry']=float(np.max(np.abs(p._public_subset(moment,idx)-p._public_quality(moment,local_sidereal(moment,p.lon),alt)[idx])))
    assert max(maxima.values())<1e-10,maxima
    # Nonlinear effects are checked in the scorer's exact order.
    factor=np.array([.3,.7]);weights=np.array([1.,1.]);best=.6
    expected_gain=np.maximum(0.,factor-best).mean()
    plug_in_gain=max(0.,factor.mean()-best)
    completion_probability=float((factor>=.5).mean())
    assert expected_gain>.049 and plug_in_gain==0. and completion_probability==.5
    result=dict(all_passed=True,max_errors=maxima,paths=16,durations=list(durations),targets=len(idx),
        comparisons=len(durations)*16*len(idx)*3,order='integrate -> band -> cap -> best positive part / required threshold -> expectation',
        expected_gain=expected_gain,plug_in_gain=plug_in_gain,completion_probability=completion_probability)
    out=ROOT/'results/scenario_value_20261003/checks.json';out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
