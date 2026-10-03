"""Run real score feedback + diagnostic stopping on synthetic quake/fault overlap.

The solver sees only the same public initial payload, score hits and quake notice.
Pointing/exposure schedule is fixed to isolate report mechanics from planning.
"""
from __future__ import annotations
import copy,csv,json,sys,tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from generator_diagnostic_checks import ROOT,SCORE,SITE,START
from policy import Policy
from generator_diagnostic_model import install_diagnostic_policy
from research.spatial_candidates import _shift_altaz
from research.geometry import parse_utc
from challenge.v4_runner import Scenario,run_scenario
from challenge.v4_fiber_map import FiberGrid,altaz_to_radec,radec_to_altaz
from challenge.v4_scorer import SlotTruth,ScoreEvent

def run(mode):
    config={'name':'synthetic quake/fault overlap','minimum_altitude_deg':30.,'site':SITE,
       'products':{'footprint_csv':'unused.csv'},'stress':{'enabled':False}}
    fiber={'field':{'fiber_area_deg2':.04,'gap_deg':0.,'n_fibers':9},
       'exposure':{'min_duration_seconds':60,'max_duration_seconds':1800}}
    grid=FiberGrid.from_config(fiber)
    score=copy.deepcopy(SCORE);score['lunar_model']['maximum_penalty']=0.
    end=START+timedelta(seconds=600);targets=[]
    for i in range(9):
        alt,az=_shift_altaz(65,0,*grid.fiber_center_offset(i))
        ra,dec=altaz_to_radec(alt,az,START,**SITE)
        targets.append({'target_id':f'T{i}','ra_deg':ra,'dec_deg':dec,'feature_flux':.1+.01*i,
            'science_weight':1.,'required':False,'target_class':'Star'})
    # All-scope quake effects are folded into slot truth by the official generator.
    # Fault (.4) and quake (.65) efficiency multipliers act independently.
    slot=SlotTruth('N-S000',START,end,True,1.3,.85,.9,.95*.65*.4)
    fault=ScoreEvent('F','instrument_fault',START,end,'ALL',None,None,None,None,1.,1.,1.,.4)
    quake_notice={'event_kind':'earthquake','direction':'ALL'}
    bulletin={'record_type':'bulletin','slot_id':'N-S000','night_id':'N','issued_at_utc':START.isoformat(),
       'initial':True,'notices':[quake_notice]}
    scenario=Scenario(config,Path('/synthetic'),SITE,fiber,score,targets,[slot],[fault],[bulletin],[],[],[],START,end)
    cols=['target_id','ra_deg','dec_deg','feature_flux','science_weight','required','target_class']
    initial={'site':{**SITE,'minimum_altitude_deg':30.},'instrument':{
        'n_fibers':9,'grid_side':3,'glass_side_deg':grid.fiber_side_deg,'pitch_deg':grid.pitch_deg,
        'fov_side_deg':grid.fov_side_deg,'exposure':fiber['exposure']},'scoring':score,
        'survey':{'start_utc':START.isoformat(),'end_utc':end.isoformat(),'slot_seconds':600,
           'nights':[{'observing_start_utc':START.isoformat(),'observing_end_utc':end.isoformat()}]},
        'targets':{'columns':cols,'rows':[[t[k] for k in cols] for t in targets]},'footprint':[]}
    cls=Policy if mode=='baseline' else install_diagnostic_policy(Policy,reserve_coupons=1)
    p=cls(initial);p.calibrator=None;p.notices=[quake_notice]
    if p.remote:p.remote.close();p.remote=None
    fits=[]
    def factory(context):
        def decide(snapshot):
            now=parse_utc(snapshot['now_utc']);p._ingest_result(snapshot)
            fits.append({'now_utc':snapshot['now_utc'],'C':p.C,'E':p.E,
                'diagnostic_evidence':len(getattr(p,'diagnostic_evidence',[]))})
            if p._repair(now):return {'action':'report'}
            alt,az=radec_to_altaz(targets[4]['ra_deg'],targets[4]['dec_deg'],now,**SITE)
            action={'action':'observe','pointing':{'alt_deg':alt,'az_deg':az},
               'assignments':{str(i):f'T{i}' for i in range(9)},'duration_seconds':60,'program':'DARK'}
            p.pending={'action':action,'start':now,'prior_C':p.C,'prior_E':p.E,'notices':[quake_notice],
               'prediction':{f'T{i}':{'alt_deg':65.} for i in range(9)}}
            return action
        return decide
    with tempfile.TemporaryDirectory() as temporary:
        path=Path(temporary);sp=path/'synthetic.json';sp.write_text(json.dumps(config))
        with patch('challenge.v4_runner.load_scenario',return_value=scenario),patch('challenge.v4_runner._read_csv',return_value=[]):
            report=run_scenario(sp,factory,path)
        decisions=list(csv.DictReader((path/'decisions.csv').open()))
        messages=[json.loads(s) for s in (path/'messages.jsonl').read_text().splitlines()]
    return {'mode':mode,'report':report,'fit_trace':fits,
        'report_results':[m for m in messages if m.get('record_type')=='report_result'],
        'reports':[{k:r[k] for k in ('start_utc','duration_seconds','observe_index')} for r in decisions if r['action']=='report'],
        'diagnostic':getattr(p,'diagnostic_stats',None)}

if __name__=='__main__':
    baseline=run('baseline');diagnostic=run('diagnostic-reserve')
    assert not baseline['reports'] and len(diagnostic['reports'])==1
    assert diagnostic['report_results'][0]['correct']
    assert diagnostic['reports'][0]['duration_seconds']=='0'
    assert diagnostic['report']['total']>baseline['report']['total']
    out=ROOT/'results/generator_forecast_20261003/diagnostic'
    result={'all_passed':True,'baseline':baseline,'diagnostic':diagnostic}
    (out/'live_fault.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'all_passed':True,'baseline_score':baseline['report']['total'],
        'diagnostic_score':diagnostic['report']['total'],'correct_reports':diagnostic['report_results'],
        'diagnostic_stats':diagnostic['diagnostic']},indent=2))
