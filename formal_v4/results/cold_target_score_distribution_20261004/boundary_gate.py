"""Canonical actual duration, public causality and weight contracts before fit."""
import csv,json,sys
from datetime import timedelta
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/'official'))
from pilot import public_context,design,labels,dump
from challenge.v4_runner import load_scenario,run_scenario
from challenge.v4_scorer import WeatherTruth
from public_features import clip_duration,query_features,history_target_features,notice_features,action_metadata,utc

def main():
    records=[];maxerr=0.;checks=0
    for seed in [940901,940902,940903,940904]:
        base=ROOT/'worlds'/str(seed);public=public_context(base);initial=public.initial
        scenario=load_scenario(base/'config/v4_scenario.json')
        weather=WeatherTruth(scenario.slots,[e for e in scenario.events if e.event_type=='instrument_fault'])
        for which,night in [('night_tail',initial['survey']['nights'][0]),('season_tail',initial['survey']['nights'][-1])]:
            start=utc(night['observing_end_utc'])-timedelta(seconds=52)
            action=design(public,start,52,np.random.default_rng(seed+len(records)))
            assert action
            action['duration_seconds']=initial['instrument']['exposure']['max_duration_seconds']
            actual=clip_duration(initial,start,action['duration_seconds']);assert actual==52
            rows=labels(scenario,weather,action,start,initial)
            for r in rows:
                target=next(t for t in public.targets if t['target_id']==r['target_id'])
                q1=query_features(initial,target,action,start)
                q2=query_features(initial,target,{**action,'duration_seconds':52},start)
                assert np.array_equal(q1,q2)
                altered_target={**target,'science_weight':0.}
                assert np.array_equal(q1,query_features(initial,altered_target,{**action,'program':'BACKUP'},start))
                token=dict(actual_hit=r['actual_hit'],score_six_decimal=r['public_score'])
                zero=history_target_features(initial,altered_target,action,start,token,start+timedelta(seconds=52),True)
                assert np.array_equal(zero,np.zeros(24,dtype=np.float32))
                checks+=1
            state={'stage':0}
            def factory(_):
                def actor(snapshot):
                    if state['stage']==0:
                        state['stage']=1;return dict(action='wait',until_utc=start.isoformat())
                    if state['stage']==1:
                        state['stage']=2;return action
                    return None
                return actor
            out=ROOT/'boundary_runtime'/str(seed)/which
            run_scenario(base/'config/v4_scenario.json',factory,out)
            with (out/'observations.csv').open() as f:official={r['target_id']:r for r in csv.DictReader(f)}
            with (out/'decisions.csv').open() as f:observes=[r for r in csv.DictReader(f) if r['action']=='observe']
            assert len(observes)==1 and int(observes[0]['duration_seconds'])==52
            for r in rows:
                assert r['actual_hit']==(r['target_id'] in official)
                if r['actual_hit']:
                    err=abs(float(official[r['target_id']]['factor'])-r['physical_factor']);maxerr=max(maxerr,err)
                    assert err<=.5e-6+1e-12
                    assert float(official[r['target_id']]['score'])==r['public_score']
            seen=[m for m in scenario.bulletins+scenario.forecasts if utc(m['issued_at_utc'])<=start]
            x=notice_features(initial,seen,start,night['night_date'])
            future=dict(record_type='bulletin',issued_at_utc=(start+timedelta(seconds=1)).isoformat(),initial=False,
                notices=[dict(event_kind='storm',direction='ALL')])
            y=notice_features(initial,[*seen,future],start,night['night_date']);assert np.array_equal(x,y)
            meta=action_metadata(initial,None,[],start,start,seen,night['night_date']);assert meta.shape==(16,)
            records.append(dict(seed=seed,boundary=which,requested=action['duration_seconds'],actual=actual,
                target_rows=len(rows),actual_hits=len(official),canonical_query_equal=True,public_future_message_ignored=True))
    result=dict(records=records,query_target_checks=checks,official_factor_rounding_max_error=maxerr,
        source_program_weight_best_invariance=True,zero_weight_history_safe=True,
        source_public_issue_time_censoring=True,actor_fit_started=False)
    dump(ROOT/'BOUNDARY_GATE.json',result);print(json.dumps(result))

if __name__=='__main__':main()
