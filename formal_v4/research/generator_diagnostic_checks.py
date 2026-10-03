"""Official scorer/runner coupon lifecycle and source-policy stopping checks."""
from __future__ import annotations
from collections import deque
import copy,csv,json,sys,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runs/cold_neural_value_20261003/production_frozen'
sys.path.insert(0,str(SOURCE))
from policy import Policy
from generator_diagnostic_model import install_diagnostic_policy
sys.path.insert(0,str(ROOT/'upstream/gosim-observer-examples/runner'))
from challenge.v4_runner import Scenario,run_scenario
from challenge.v4_fiber_map import altaz_to_radec,radec_to_altaz
from challenge.v4_scorer import SlotTruth,ScoreEvent,WeatherTruth

START=datetime(2026,10,4,0,tzinfo=timezone.utc)
SCORE=json.loads((ROOT/'practice_cards/alpha/alpha/config/v4_score_config.json').read_text())
SITE={'latitude_deg':-24.6157,'longitude_deg':-70.3976}
FAULT=ScoreEvent('F','instrument_fault',START+timedelta(seconds=60),START+timedelta(days=10),
                 'ALL',None,None,None,None,1.,1.,1.,.4)

def fresh(p,now,value=.45):
    p.diagnostic_evidence=deque([(now-timedelta(seconds=60*i),value,.8,.1) for i in (3,2,1)],maxlen=12)

def source_policy_fixture(allowance=2,reserve=0):
    # Bypass catalog construction only; invoke the real source _repair/_ingest_result.
    cls=install_diagnostic_policy(Policy,reserve_coupons=reserve);p=object.__new__(cls)
    p.initial={'scoring':copy.deepcopy(SCORE)}
    p.initial['scoring']['reporting']['false_report_free_allowance']=allowance
    p.config={'repair_enabled':True,'require_efficiency_witness':True}
    p.false_since_correct=0;p.correct_reports=0;p.report_count=0;p.last_report=None;p.pending=None
    p.low_efficiency=deque(maxlen=12);p.efficiency_witnesses=deque(maxlen=16)
    p.notices=[{'event_kind':'earthquake','direction':'ALL'}]
    p.planner=SimpleNamespace(q0=SCORE['q0'])
    p.belief_clock=SimpleNamespace(mark=lambda moment:None)
    p.C=.8;p.E=.45;p.diagnostic_seen=set();p.diagnostic_pending=False
    p.diagnostic_stats={'fresh_fits':0,'coupon_reports':0,'coupon_reports_with_quake':0,
       'original_reports':0,'correct_coupon_reports':0,'false_coupon_reports':0,
       'minimum_coupon_remaining_before_report':None}
    fresh(p,START);return p

def stopping_checks():
    p=source_policy_fixture();now=START
    for false_count in (1,2):
        fresh(p,now);assert p._repair(now)
        assert p.pending=={'action':{'action':'report'}}
        p._ingest_result({'now_utc':now.isoformat(),'last_result':{'action':'report','correct':False}})
        assert p.false_since_correct==false_count
        now+=timedelta(days=1)
    fresh(p,now);assert not p._repair(now)
    assert p.report_count==2 and p.diagnostic_stats['minimum_coupon_remaining_before_report']==1
    # A correct report arriving through the ordinary source protocol restores allowance.
    p.pending={'action':{'action':'report'}}
    p._ingest_result({'now_utc':now.isoformat(),'last_result':{'action':'report','correct':True}})
    assert p.false_since_correct==0 and p.correct_reports==1
    fresh(p,now);assert p._repair(now)
    p._ingest_result({'now_utc':now.isoformat(),'last_result':{'action':'report','correct':True}})
    assert p.false_since_correct==0 and p.diagnostic_stats['correct_coupon_reports']==1
    zero=source_policy_fixture(0);assert not zero._repair(START)
    stale=source_policy_fixture();fresh(stale,START-timedelta(hours=3));assert not stale._repair(START)
    weak=source_policy_fixture();fresh(weak,START,.68);assert not weak._repair(START)
    cool=source_policy_fixture();cool.last_report=START-timedelta(hours=1);assert not cool._repair(START)
    reserved=source_policy_fixture(reserve=1);assert reserved._repair(START)
    reserved._ingest_result({'now_utc':START.isoformat(),'last_result':{'action':'report','correct':False}})
    later=START+timedelta(days=1);fresh(reserved,later);assert not reserved._repair(later)
    # Strong ordinary witnesses may spend the retained coupon.
    reserved.notices=[]
    reserved.low_efficiency=deque([(later,.5,.8,'BACKUP',3,.1)]*3,maxlen=12)
    reserved.efficiency_witnesses=deque([(later,.5)]*2,maxlen=16)
    assert reserved._repair(later) and reserved.diagnostic_stats['original_reports']==1
    for allowance in range(5):
        configurable=source_policy_fixture(allowance,reserve=1)
        for day in range(6):
            moment=START+timedelta(days=day);fresh(configurable,moment)
            if configurable._repair(moment):
                configurable._ingest_result({'now_utc':moment.isoformat(),
                    'last_result':{'action':'report','correct':False}})
        assert configurable.false_since_correct==max(0,allowance-1)
    return {'false_coupons_consumed':2,'no_report_when_remaining_zero':True,
       'correct_replenishes_allowance':True,'zero_configured_allowance_blocks':True,
       'stale_weak_and_cooldown_block':True,'quake_diagnostic_reports':p.diagnostic_stats['coupon_reports_with_quake'],
       'reserve_retains_coupon_for_original_witness':True,'allowances_0_through_4_passed':True}

def settlement_checks():
    slot=SlotTruth('S',START,START+timedelta(days=10),True,1.,1.,1.,.38)
    weather=WeatherTruth([slot],[FAULT])
    actions=[(START,0),(START,0),(START+timedelta(seconds=60),100),
       (START+timedelta(seconds=60),0),(START+timedelta(seconds=60),0),
       (START+timedelta(seconds=60),-150)]
    values=[];counts=[]
    for moment,expected in actions:
        value=weather.report_fault(moment,SCORE);assert value==expected
        values.append(value);counts.append(weather.false_reports_since_correct)
    assert counts==[1,2,0,1,2,3]
    return {'settlements':values,'false_counts':counts,'repair_time':weather.fault_repair_utc.isoformat()}

def live_runner_check():
    config={'name':'synthetic coupon','minimum_altitude_deg':30.,'site':SITE,
        'products':{'footprint_csv':'unused.csv'},'stress':{'enabled':False}}
    fiber={'field':{'fiber_area_deg2':.02,'gap_deg':0.,'n_fibers':1},
       'exposure':{'min_duration_seconds':60,'max_duration_seconds':1800}}
    score=copy.deepcopy(SCORE);score['lunar_model']['maximum_penalty']=0.
    target={'target_id':'T','feature_flux':.001,'science_weight':1.,'required':False,'target_class':'Star'}
    target['ra_deg'],target['dec_deg']=altaz_to_radec(60,0,START,**SITE)
    slot=SlotTruth('S',START,START+timedelta(seconds=300),True,1.,1.,1.,.38)
    fault=ScoreEvent('F','instrument_fault',START,START+timedelta(seconds=300),
       'ALL',None,None,None,None,1.,1.,1.,.4)
    scenario=Scenario(config,Path('/synthetic'),SITE,fiber,score,[target],[slot],[fault],[],[],[],[],
       START,START+timedelta(seconds=300))
    snapshots=[]
    def factory(context):
        def decide(snapshot):
            snapshots.append(snapshot)
            n=len(snapshots)
            if n in (1,4):
                alt,az=radec_to_altaz(target['ra_deg'],target['dec_deg'],
                   datetime.fromisoformat(snapshot['now_utc'].replace('Z','+00:00')),**SITE)
                return {'action':'observe','pointing':{'alt_deg':alt,'az_deg':az},'assignments':{'0':'T'},
                   'duration_seconds':60,'program':'BACKUP'}
            if n in (2,3):return {'action':'report'}
            return {'action':'wait','until_utc':scenario.survey_end.isoformat().replace('+00:00','Z')}
        return decide
    with tempfile.TemporaryDirectory() as temporary:
        path=Path(temporary);scenario_path=path/'synthetic.json';scenario_path.write_text(json.dumps(config))
        with patch('challenge.v4_runner.load_scenario',return_value=scenario),patch('challenge.v4_runner._read_csv',return_value=[]):
            report=run_scenario(scenario_path,factory,path)
        decisions=list(csv.DictReader((path/'decisions.csv').open()))
        observations=list(csv.DictReader((path/'observations.csv').open()))
    reports=[r for r in decisions if r['action']=='report']
    assert all(r['duration_seconds']=='0' and r['start_utc']==r['end_utc'] and r['observe_index']=='' for r in reports)
    assert [r['observe_index'] for r in decisions if r['action']=='observe']==['0','1']
    assert snapshots[1]['now_utc']==snapshots[2]['now_utc']==snapshots[3]['now_utc']
    assert snapshots[2]['last_result']['score_delta']==100 and snapshots[3]['last_result']['score_delta']==0
    before,after=[float(r['score']) for r in observations]
    assert after>2.4*before
    return {'report_sim_seconds':0,'observe_indexes':[0,1],'before_score':before,'after_score':after,
       'repair_improvement_ratio':after/before,'report_settlement':report['components']['report_settlement']}

if __name__=='__main__':
    result={'all_passed':True,'stopping':stopping_checks(),'settlement':settlement_checks(),'live_runner':live_runner_check()}
    out=ROOT/'results/generator_forecast_20261003/diagnostic';out.mkdir(parents=True,exist_ok=True)
    (out/'checks.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
