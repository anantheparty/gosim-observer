#!/usr/bin/env python3
"""Independent value recomputation + sampled official-exposure containment."""
import sys,json,hashlib,math
from pathlib import Path
from datetime import timedelta
import numpy as np
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'upstream/gosim-observer-examples/runner'))
from challenge.v4_runner import load_scenario
from challenge.v4_scorer import WeatherTruth,score_target_exposure
from challenge.v4_fiber_map import radec_to_altaz,min_altitude_during
OUT=BASE/'results/cold_probabilistic_model_20261003/resource_graph'

def main():
    result={}
    for card in ('L1','L2'):
        summary=json.loads((OUT/f'{card}_summary.json').read_text());data=np.load(OUT/f'{card}_dual_certificate.npz')
        i,k,v,r=(data[x] for x in ('target_index','slot_index','edge_visible_900s_capacity','edge_factor_per_900s_upper'))
        nu,lam=data['target_nu'],data['slot_lambda'];cap=data['slot_fiber_900s_capacity'];a=data['science_slope'];p=data['effective_required_reward'];allp=data['required_reward'];threshold=float(data['required_threshold']);gm=data['target_max_single_exposure_factor_upper']
        zs=np.vstack([np.zeros(len(a)),np.minimum(threshold,gm),gm]).astype(np.longdouble)
        reward=np.vstack([np.zeros(len(a)),a*np.minimum(threshold,gm)+p,a*gm+p]).astype(np.longdouble)
        conjugate=np.max(reward-zs*nu.astype(np.longdouble),axis=0).sum(dtype=np.longdouble)
        capacity=np.sum(cap.astype(np.longdouble)*lam.astype(np.longdouble),dtype=np.longdouble)
        edge=np.sum(v.astype(np.longdouble)*np.maximum(0,nu[i].astype(np.longdouble)*r.astype(np.longdouble)-lam[k].astype(np.longdouble)),dtype=np.longdouble)
        recomputed=float(conjugate+capacity+edge-allp.sum(dtype=np.longdouble))
        residual=abs(recomputed-summary['science_required_upper_before_padding'])
        assert residual<1e-6 and min(nu.min(),lam.min())>=0
        slots=json.loads((OUT/f'{card}_slot_prices.json').read_text())
        original_to_k={s['original_slot_index']:j for j,s in enumerate(slots)}
        sc=load_scenario(BASE/f'upstream/gosim-observer-examples/local-cards/{card}/config/v4_scenario.json')
        weather=WeatherTruth(sc.slots,[e for e in sc.events if e.event_type=='instrument_fault'])
        for fault in weather.faults:weather.repair_fault(fault.actual_start_utc)
        directional=[e for e in sc.events if e.scope_type=='HORIZON_SECTOR']
        # Dictionary only for sampled target rows, rather than the whole graph.
        rng=np.random.default_rng(601003);tests=0;maxviolation=0.;cross=0;long=0;minslack=math.inf
        for draw in range(600):
            original=int(rng.integers(len(sc.slots)));slot=sc.slots[original];ti=int(rng.integers(len(sc.targets)));t=sc.targets[ti]
            start=slot.start_utc+timedelta(seconds=int(rng.integers(0,840)))
            night=slot.slot_id.split('-S')[0];endnight=max(s.end_utc for s in sc.slots if s.slot_id.split('-S')[0]==night)
            duration=int(rng.choice([60,83,311,900,1377,2400,3599]));end=min(start+timedelta(seconds=duration),endnight);duration=int((end-start).total_seconds())
            if duration<=0 or min_altitude_during(t['ra_deg'],t['dec_deg'],start,end,sc.config)<sc.minimum_altitude_deg:continue
            segments=list(weather.segments(start,end));events=[e for e in directional if e.overlaps(start,end)]
            pos=lambda moment:radec_to_altaz(t['ra_deg'],t['dec_deg'],moment,sc.site['latitude_deg'],sc.site['longitude_deg'])
            actual=score_target_exposure(t,segments,events,weather,duration,1.,sc.score_config,start,pos,sc.site)
            targetedge={int(k[x]):float(r[x]) for x in np.flatnonzero(i==ti)}
            dose=0.;overlapcount=0
            for original2,s in enumerate(sc.slots):
                seconds=max(0.,(min(end,s.end_utc)-max(start,s.start_utc)).total_seconds())
                if seconds<=0:continue
                overlapcount+=1
                if s.is_observable:
                    rate=targetedge.get(original_to_k.get(original2,-1),0.)
                    dose+=seconds/900*rate
            factorupper=min(1.,dose,float(gm[ti]))
            violation=actual.factor-factorupper;maxviolation=max(maxviolation,violation);minslack=min(minslack,factorupper-actual.factor)
            assert violation<=1e-8,(card,ti,start,duration,actual.factor,factorupper)
            tests+=1;cross+=overlapcount>1;long+=duration>900
            if tests>=160:break
        source=BASE/'research/cold_probabilistic_resource_graph.py'
        assert hashlib.sha256(source.read_bytes()).hexdigest()==summary['source_sha256']
        strongest=dict(L1=6409.988920,L2=7006.280570)[card]
        assert summary['total_upper']>=strongest
        result[card]={'dual_recomputation_absolute_residual':residual,'nonnegative_dual_violation':0.,'sampled_official_exposures_contained':tests,'sampled_cross_slot_exposures':cross,'sampled_long_exposures':long,'maximum_sampled_factor_upper_violation':maxviolation,'minimum_sampled_factor_slack':minslack,'maximum_reported_total_upper':summary['total_upper'],'latest_root_reported_feasible_lower_bound':strongest,'contains_latest_lower_bound':True,'source_sha256_matches':True,'finite_coordinate_best_is_zero_dual':bool(np.all(nu==0)&np.all(lam==0)),'scope':'Sampling checks implementation; arbitrary-exposure embedding + nonnegative dual inequality establish model coverage. Latest lower bounds are parent-reported, not new runs by this script.'}
        print(card,json.dumps(result[card]),flush=True)
    (OUT/'certificate_verification.json').write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
