"""Minimal official-runner/scorer checks for closure diagnostics and counterexamples.

All scenarios are synthetic and contain public scoring constants. Root policy is
not imported or modified, and no development-card or private weather is read.
"""
from __future__ import annotations

import copy,csv,json,math,sys,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(BASE/'formal_v4/upstream/gosim-observer-examples/runner'))
from challenge.v4_runner import Scenario,run_scenario
from challenge.v4_fiber_map import altaz_to_radec
from challenge.v4_scorer import BestLedger,ScoreEvent,SlotTruth,WeatherTruth,score_target_exposure,uniformity_penalty

START=datetime(2026,10,4,0,tzinfo=timezone.utc)
SCORE=json.loads((BASE/'formal_v4/practice_cards/alpha/alpha/config/v4_score_config.json').read_text())
SITE={'latitude_deg':-24.6157,'longitude_deg':-70.3976}
TARGET={'target_id':'T','ra_deg':0.,'dec_deg':0.,'feature_flux':.1,'science_weight':1.,'required':False,'target_class':'Star'}


def runner_probe(night_seconds=900):
    config={'name':'synthetic closure','minimum_altitude_deg':30.,'site':SITE,
            'products':{'footprint_csv':'unused.csv'},'stress':{'enabled':False}}
    fiber={'field':{'fiber_area_deg2':.02,'gap_deg':0.,'n_fibers':1},
           'exposure':{'min_duration_seconds':60,'max_duration_seconds':1800}}
    target=dict(TARGET)
    target['ra_deg'],target['dec_deg']=altaz_to_radec(60,0,START,**SITE)
    slot=SlotTruth('N-S000',START,START+timedelta(seconds=night_seconds),False,1.,1.,1.,1.)
    scenario=Scenario(config,Path('/synthetic'),SITE,fiber,SCORE,[target],[slot],[],[],[],[],[],
                      START,START+timedelta(seconds=night_seconds))
    snapshots=[]
    def factory(context):
        def decide(snapshot):
            snapshots.append(snapshot)
            if len(snapshots)==1:
                return {'action':'observe','pointing':{'alt_deg':60.,'az_deg':0.},
                        'assignments':{'0':'T'},'duration_seconds':60,'program':'BACKUP'}
            return {'action':'wait','until_utc':scenario.survey_end.isoformat().replace('+00:00','Z')}
        return decide
    with tempfile.TemporaryDirectory() as temporary:
        scenario_path=Path(temporary)/'synthetic.json'
        scenario_path.write_text(json.dumps(config))
        with patch('challenge.v4_runner.load_scenario',return_value=scenario),patch('challenge.v4_runner._read_csv',return_value=[]):
            report=run_scenario(scenario_path,factory,Path(temporary))
        decisions=list(csv.DictReader((Path(temporary)/'decisions.csv').open()))
        observations=list(csv.DictReader((Path(temporary)/'observations.csv').open()))
    assert decisions[0]['valid']=='true' and decisions[0]['hit_count']=='1'
    assert float(observations[0]['score'])==0
    if night_seconds>60:
        result=snapshots[1]['last_result']
        assert result=={'action':'observe','observe_index':0,'assigned_count':1,'hit_count':1,
                        'hits':[{'target_id':'T','score':0.}]}
    return {'night_seconds':night_seconds,'valid':True,'actual_seconds':int(decisions[0]['duration_seconds']),
            'hit_score':float(observations[0]['score']),
            'feedback_keys':sorted(snapshots[1]['last_result']) if len(snapshots)>1 else []}


def score(duration,start=START,slots=None,events=None,position=None):
    scoring=copy.deepcopy(SCORE);scoring.pop('lunar_model')
    slots=slots or [SlotTruth('N-S000',START,START+timedelta(seconds=1800),True,1.,1.,1.,1.)]
    weather=WeatherTruth(slots,[])
    return score_target_exposure(TARGET,list(weather.segments(start,start+timedelta(seconds=duration))),
                                 events or [],weather,duration,1.,scoring,start,position or (lambda moment:(90.,0.)))


def checks():
    results={'closed_valid_runner':runner_probe(),'short_night_clips_legal_exposure':runner_probe(20)}
    full=score(900).score
    split=max(score(60).score,score(840,start=START+timedelta(seconds=60)).score)
    assert split<full
    results['best_does_not_accumulate']={'900_score':full,'best_60_840_score':split}
    slots=[SlotTruth('N-S000',START,START+timedelta(seconds=900),False,1.,1.,1.,1.),
           SlotTruth('N-S001',START+timedelta(seconds=900),START+timedelta(seconds=1800),True,1.,1.,1.,1.)]
    crossing=score(60,start=START+timedelta(seconds=850),slots=slots).score
    assert crossing>0
    results['crossing_probe_cannot_identify_initial_slot']={'score':crossing,'closed_seconds':50,'open_seconds':10}
    event=ScoreEvent('E','rocket_launch',START,START+timedelta(seconds=900),'HORIZON_SECTOR',
                     0.,.2,0.,90.,1.,1.,1.,1.,True)
    position=lambda moment:(90.,.004*(moment-START).total_seconds())
    early=score(60,events=[event],position=position).score
    later=score(840,start=START+timedelta(seconds=60),events=[event],position=position).score
    assert early==0 and later>0
    results['zero_directional_probe_not_global_closure']={'early':early,'later':later}
    baseline,probe=BestLedger(),BestLedger()
    probe.record(0,'diagnostic',0.,0.)
    for index in range(20):
        value=100. if index==4 else 0.
        baseline.record(index,f'T{index}',value>0,value)
        probe.record(index+1,f'T{index}',value>0,value)
    baseline.invalidate_window(math.floor(.25*20),math.floor(.30*20),'LOSS')
    probe.invalidate_window(math.floor(.25*21),math.floor(.30*21),'LOSS')
    old=sum(value[1] for value in baseline.best().values())
    new=sum(value[1] for value in probe.best().values())
    assert old==100 and new==0
    results['zero_probe_changes_invalidation']={'baseline_N':20,'probe_N':21,'baseline_raw':old,'probe_raw':new}
    targets=[dict(TARGET,target_id=name,ra_deg=ra) for name,ra in [('A',0.),('B',1.),('C',20.),('D',21.)]]
    before={'A':.5,'C':.5}
    after={**before,'B':.5}
    old_penalty=uniformity_penalty(targets,before,SCORE)[1]
    new_penalty=uniformity_penalty(targets,after,SCORE)[1]
    assert old_penalty==0 and new_penalty>19.99
    results['extra_completion_can_increase_jain_penalty']={'before':old_penalty,'after':new_penalty}
    return results


if __name__=='__main__':
    result=checks()
    (Path(__file__).with_name('closure_probe_checks_result.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'checks':len(result),'all_passed':True,'results':result},indent=2))
