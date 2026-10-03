"""Causal two-level weather filtering, isolated from the production solver.

Only the official public local cards are labels. Predictor features are public
calendar, bulletin, and score-only feedback from our stored observer outputs.
The scalar log model is an approximation to the three clipped Gaussian fields.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
from datetime import timedelta
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'runs/cold_neural_value_20261003/production_frozen'
OUT = ROOT / 'results/generator_forecast_20261003'
OFFICIAL = ROOT / 'upstream/gosim-observer-examples'
sys.path.insert(0, str(SOURCE))
sys.path.insert(1, str(OFFICIAL / 'runner'))
from policy import Policy
from research.geometry import parse_utc, format_utc
from research.feedback_model import seasonal_quality
from research.belief_clock import BeliefClock
from challenge.v4_workflow import V4Workflow
from challenge.v4_runner import load_scenario
from challenge.v4_scorer import WeatherTruth, lunar_quality_factor
from challenge.v4_fiber_map import radec_to_altaz


def dump(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


from generator_forecast_model import HierarchicalClock


def history_folder(card):
    return ROOT / 'runs/cpu_calendar_witness_20261003' / card


def collect(card):
    scenario_path = OFFICIAL/'local-cards'/card/'config/v4_scenario.json'
    s = load_scenario(scenario_path)
    initial = V4Workflow(OFFICIAL/'local-cards'/card).initialize_payload(900)
    p = Policy(initial)
    p.remote = None
    p.calibrator = None
    path = history_folder(card)
    dec = list(csv.DictReader((path/'decisions.csv').open()))
    obs = defaultdict(list)
    for row in csv.DictReader((path/'observations.csv').open()):
        obs[int(row['observe_index'])].append({'target_id':row['target_id'],'score':float(row['score'])})
    published = s.bulletins
    pubtimes = [parse_utc(m['issued_at_utc']) for m in published]
    weather = WeatherTruth(s.slots,[e for e in s.events if e.event_type=='instrument_fault'])
    targets = {t['target_id']:t for t in s.targets}
    lat,lon = s.site['latitude_deg'],s.site['longitude_deg']
    # Truth is used only to construct evaluation labels below.
    records = []
    for d in dec:
        start,end = parse_utc(d['start_utc']),parse_utc(d['end_utc'])
        season = seasonal_quality(start.timetuple().tm_yday,p.planner.q0)[0]
        priorC,priorE = p.belief_clock.prior(p.C,p.E,start,season)
        if d['action']=='report':
            # Canonical own report result is public feedback.
            reports = [json.loads(x) for x in (path/'messages.jsonl').read_text().splitlines()
                       if x.strip() and json.loads(x).get('record_type')=='report_result']
            report = next((m for m in reports if m['issued_at_utc']==d['start_utc']),None)
            if report:
                p.pending={'action':{'action':'report'}}
                p._ingest_result({'now_utc':d['start_utc'],'last_result':{'action':'report',**report}})
                records.append({'kind':'report','time':start.timestamp(),'correct':bool(report['correct'])})
            continue
        if d['action']!='observe': continue
        oi=int(d['observe_index']);hits=obs[oi]
        idx=np.array([p.planner.index[h['target_id']] for h in hits],int)
        duration=int(d['duration_seconds'])
        if not len(idx):continue
        H=p._geometric_H(start,duration,idx)
        clean=not any(n['event_kind']!='terrain_obstruction' for m,t in zip(published,pubtimes)
                      if start<=t<end for n in m.get('notices',[]))
        latest=int(np.searchsorted(pubtimes,start,side='right')-1)
        notices=published[latest].get('notices',[]) if latest>=0 else []
        clean &= not any(n['event_kind']!='terrain_obstruction' for n in notices)
        truth_C=[]
        for h,hh in zip(hits,H):
            target=targets[h['target_id']]
            tq=weather.band_quality(start,end,s.score_config,
                lambda tm,t=target:radec_to_altaz(t['ra_deg'],t['dec_deg'],tm,lat,lon)[0],
                lambda tm,t=target:lunar_quality_factor(t['ra_deg'],t['dec_deg'],tm,s.site,s.score_config))
            truth_C.append(tq/hh)
        previous_feedback=p.last_feedback
        p.pending={'action':{'action':'observe','duration_seconds':duration,'program':d['program']},
                   'start':start,'notices':notices,'prior_C':priorC,'prior_E':priorE,
                   'prediction':{h['target_id']:{'alt_deg':radec_to_altaz(targets[h['target_id']]['ra_deg'],
                       targets[h['target_id']]['dec_deg'],start,lat,lon)[0],
                       'az_deg':radec_to_altaz(targets[h['target_id']]['ra_deg'],
                       targets[h['target_id']]['dec_deg'],start,lat,lon)[1]} for h in hits}}
        p._ingest_result({'now_utc':format_utc(end),'last_result':{'action':'observe','observe_index':oi,'hits':hits},
                         'new_messages':[m for m,t in zip(published,pubtimes) if start<t<=end]})
        records.append({'kind':'observe','time':start.timestamp(),'end':end.timestamp(),
                        'mid':(start.timestamp()+end.timestamp())/2,'night':p._night(start),
                        'label_C':float(np.median(truth_C)),'baseline_C':priorC,'baseline_E':priorE,
                        'fit_C':p.C,'fit_E':p.E,'updated':p.last_feedback!=previous_feedback,
                        'clean':bool(clean),'seasonal_C':season,'duration':duration,'hits':len(hits)})
    dump(card+'_feedback_records.json',records)
    return records,initial


def evaluate(records,initial,params):
    clock=HierarchicalClock([(parse_utc(n['observing_start_utc']),parse_utc(n['observing_end_utc']))
                            for n in initial['survey']['nights']],initial['survey']['slot_seconds'],
                            initial_time=initial['survey']['start_utc'],**params)
    result=[]
    for r in records:
        moment=parse_utc(format_utc(__import__('datetime').datetime.fromtimestamp(r['time'],__import__('datetime').timezone.utc)))
        if r['kind']=='report':
            clock.reset(moment);continue
        pred,_=clock.prior(1.,r['baseline_E'],moment,r['seasonal_C'])
        result.append({**r,'hierarchical_C':pred})
        if r['updated']:
            midpoint=__import__('datetime').datetime.fromtimestamp(r['mid'],__import__('datetime').timezone.utc)
            clock.update(r['fit_C'],midpoint,seasonal_quality(midpoint.timetuple().tm_yday)[0])
    return result


def metrics(rows,field,mask='positive'):
    eligible=[r for r in rows if r['label_C']>.02 and (mask!='clean' or r['clean'])]
    a=np.array([r[field] for r in eligible]);b=np.array([r['label_C'] for r in eligible])
    early=[r for r in eligible if r['time']-r['night_start']<2700] if eligible and 'night_start' in eligible[0] else []
    return {'n':len(eligible),'rmse':float(np.sqrt(np.mean((a-b)**2))),
            'log_rmse':float(np.sqrt(np.mean((np.log(a)-np.log(b))**2))),
            'mae':float(np.mean(np.abs(a-b)))}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--collect',action='store_true');a=ap.parse_args()
    data={};initials={}
    for card in ('L1','L2','L3','L4'):
        if a.collect or not (OUT/(card+'_feedback_records.json')).exists():
            data[card],initials[card]=collect(card)
        else:
            data[card]=json.loads((OUT/(card+'_feedback_records.json')).read_text())
            initials[card]=V4Workflow(OFFICIAL/'local-cards'/card).initialize_payload(900)
        print(json.dumps({'card':card,'records':len(data[card])}),flush=True)
    # Fixed generator AR coefficients. Variance scales are fit on L1; R is
    # selected using L2 only. L3/L4 are untouched until the parameters are frozen.
    candidates=[]
    for vn in (.01,.03,.06):
        for vs in (.001,.005,.015):
            for r in (.0001,.001,.01,.04):
                params={'night_variance':vn,'slot_variance':vs,'measurement_variance':r}
                pred=evaluate(data['L1'],initials['L1'],params)
                candidates.append({'params':params,'L1':metrics(pred,'hierarchical_C','clean')})
    shortlist=sorted(candidates,key=lambda c:c['L1']['log_rmse'])[:8]
    for c in shortlist:
        c['L2']=metrics(evaluate(data['L2'],initials['L2'],c['params']),'hierarchical_C','clean')
    selected=min(shortlist,key=lambda c:c['L2']['log_rmse'])
    dump('selection.json',{'training':'L1','validation':'L2','test':['L3','L4'],'candidates':candidates,
                           'shortlist':shortlist,'selected':selected})
    results={}
    for card in ('L1','L2','L3','L4'):
        pred=evaluate(data[card],initials[card],selected['params'])
        for row in pred:
            row['night_start']=parse_utc(initials[card]['survey']['nights'][row['night']]['observing_start_utc']).timestamp()
        results[card]={}
        for mask in ('positive','clean'):
            results[card][mask]={'baseline':metrics(pred,'baseline_C',mask),
                                 'hierarchical':metrics(pred,'hierarchical_C',mask)}
        early=[r for r in pred if r['time']-r['night_start']<2700]
        if early:results[card]['first45min']={'baseline':metrics(early,'baseline_C','clean'),
                                            'hierarchical':metrics(early,'hierarchical_C','clean')}
        dump(card+'_predictions.json',pred)
    dump('prediction_results.json',{'params':selected['params'],'cards':results,
          'scope':'Causal public feedback only; public local truth used for labels and offline selection only.',
          'source':str(SOURCE),'existing_action_history':'cpu_calendar_witness_20261003',
          'model':'approximate two-level scalar log C; E kept separate; no seed or LLM'})
    print(json.dumps(results,indent=2),flush=True)


if __name__=='__main__':main()
