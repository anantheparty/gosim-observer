#!/usr/bin/env python3
"""Audit completed rollout predictions against its realized official results.

Posthoc only: observation factors/quality are diagnostic scoring outputs and are
never fed into the participant optimizer. No truth files are opened.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import sys

import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from global_lp_pilot import public_initialization
from research.spatial_candidates import SpatialPlanner,PROGRAMS,parse_utc,local_sidereal
from research.efficiency_bounds import infer_efficiency_upper


def efficiency_witnesses(run,p):
    decisions=[r for r in csv.DictReader((run/'decisions.csv').open()) if r['action']=='observe']
    observations={}
    for r in csv.DictReader((run/'observations.csv').open()):observations.setdefault(int(r['observe_index']),[]).append(r)
    messages=[json.loads(s) for s in (run/'messages.jsonl').read_text().splitlines()]
    bulletins=[m for m in messages if m.get('record_type')=='bulletin']
    high=clean=strong=low=0;examples=[]
    for d in decisions:
        hits=observations.get(int(d['observe_index']),[])
        if not hits:continue
        start,end=parse_utc(d['start_utc']),parse_utc(d['end_utc']);idx=[p.index[h['target_id']] for h in hits]
        alt=p._altaz(local_sidereal(start,p.lon))[0][idx]
        if min(alt)<65:continue
        high+=1
        earlier=[b for b in bulletins if parse_utc(b['issued_at_utc'])<=start]
        notices=(earlier[-1].get('notices',[]) if earlier else [])+sum(
            [b.get('notices',[]) for b in bulletins if start<parse_utc(b['issued_at_utc'])<=end],[])
        if notices:continue
        clean+=1
        b=infer_efficiency_upper(hits,p.weight[idx],p.flux[idx],int(d['duration_seconds']),d['program'],p.init['scoring'])
        if b['strong_count']>=1 and b['E_upper'] is not None:
            strong+=1
            if b['E_upper']<.8:
                low+=1;examples.append({'start_utc':d['start_utc'],'duration':int(d['duration_seconds']),'E_upper':b['E_upper']})
    return {'all_hit_altitude_ge65_actions':high,'clean_high_altitude_actions':clean,
            'strong_efficiency_bound_actions':strong,'bound_below_point8_actions':low,'examples':examples}


def audit(run,trace_path=None):
    initial,_=public_initialization(Path(__file__).resolve().parents[1]/'upstream/gosim-observer-examples/local-cards/L1')
    p=SpatialPlanner(initial)
    traces=[]
    for line in (trace_path or run/'agent.log').read_text().splitlines():
        try:r=json.loads(line)
        except ValueError:continue
        if 'rolling_trace' in r:traces.append(r['rolling_trace'])
    decisions=[r for r in csv.DictReader((run/'decisions.csv').open()) if r['action']=='observe']
    observations=list(csv.DictReader((run/'observations.csv').open()))
    by_index={}
    for r in observations:by_index.setdefault(int(r['observe_index']),{})[r['target_id']]=r
    assert len(traces)==len(decisions)
    best=np.zeros(p.n);rows=[];factor_errors=[];score_errors=[];floors=[];stale=[]
    predicted_actual_program_mismatch=0
    for trace,decision in zip(traces,decisions):
        assert trace['now_utc']==decision['start_utc']
        assert int(trace['action']['duration_seconds'])==int(decision['duration_seconds'])
        floors.append(abs(trace['current_best_science']-float(best.sum())))
        hits=by_index.get(int(decision['observe_index']),{})
        for target,pred in trace['prediction'].items():
            i=p.index[target];duration=trace['action']['duration_seconds']
            factor=min(1.,p.flux[i]*duration*pred['quality']/p.f0t0)
            program=PROGRAMS.index(trace['action']['program'])
            multiplier=p.multipliers[program] if trace['action']['program']==pred['predicted_band'] else p.mismatch
            expected=p.weight[i]*factor*multiplier
            factor_errors.append(abs(factor-pred['factor']));score_errors.append(abs(expected-pred['predicted_score']))
            floors.append(abs(pred['science_floor_now']-best[i]))
            stale.append(pred['science_floor_now']-pred['science_floor_at_build'])
            actual=hits.get(target);score=float(actual['score']) if actual else 0.
            actual_multiplier=float(actual['prog_mult']) if actual else None
            if actual and abs(actual_multiplier-multiplier)>1e-5:predicted_actual_program_mismatch+=1
            rows.append({'target_id':target,'start_utc':trace['now_utc'],'duration':duration,
                'predicted_score':expected,'actual_score':score,'predicted_quality':pred['quality'],
                'predicted_factor':factor,'actual_factor':float(actual['factor']) if actual else None,
                'actual_quality':float(actual['quality']) if actual else None,
                'science_floor':float(best[i]),'predicted_gain':max(0,expected-best[i]),
                'actual_gain':max(0,score-best[i]),'predicted_multiplier':float(multiplier),
                'actual_multiplier':actual_multiplier,'frozen_C':pred['frozen_C'],'frozen_E':pred['frozen_E'],
                'target_scale':pred['target_scale'],'alt_deg':pred['alt_deg']})
        for target,actual in hits.items():best[p.index[target]]=max(best[p.index[target]],float(actual['score']))
    quarter=[]
    for subset in np.array_split(np.arange(len(rows)),4):
        selected=[rows[i] for i in subset]
        ratios=[r['actual_score']/r['predicted_score'] for r in selected if r['predicted_score']>1e-9]
        quarter.append({'assignments':len(selected),'predicted_science_gain':sum(r['predicted_gain'] for r in selected),
            'actual_science_gain':sum(r['actual_gain'] for r in selected),
            'median_actual_over_predicted_score':float(np.median(ratios)) if ratios else None,
            'mean_duration':float(np.mean([r['duration'] for r in selected]))})
    summary={'observes':len(traces),'assigned':len(rows),'hits':len(observations),
        'max_factor_formula_error':max(factor_errors,default=0),'max_score_formula_error':max(score_errors,default=0),
        'max_public_history_floor_error_from_csv_rounding':max(floors,default=0),
        'stale_build_floor_assignments':sum(abs(x)>1e-6 for x in stale),'max_cached_floor_difference':max(stale,default=0),
        'predicted_actual_program_mismatches':predicted_actual_program_mismatch,
        'predicted_total_gain_on_actual_history':sum(r['predicted_gain'] for r in rows),
        'realized_science_from_history':float(best.sum()),
        'efficiency_witnesses':efficiency_witnesses(run,p),
        'saturated_predicted_assignments':int(sum(r['predicted_factor'] >= 1-1e-9 for r in rows)),
        'saturated_realized_hits':int(sum(r['actual_factor'] is not None and r['actual_factor'] >= 1-1e-6 for r in rows)),
        'actual_quality_over_predicted_quantiles_positive_hits':np.quantile([
            r['actual_quality']/r['predicted_quality'] for r in rows if r['actual_quality'] is not None
            and r['actual_quality']>0 and r['predicted_quality']>0],[.1,.5,.9]).tolist(),
        'quarter_metrics':quarter,'posthoc_realized_scoring_fields_never_input_to_optimizer':True}
    return summary,rows


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--trace',type=Path)
    args=ap.parse_args();summary,rows=audit(args.run,args.trace);args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'prediction_audit.json').write_text(json.dumps(summary,indent=2)+'\n')
    (args.run/'prediction_pairs.json').write_text(json.dumps(rows,separators=(',',':'))+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
