"""Summarize frozen development/heldout coupon experiments and report audits."""
from __future__ import annotations
import csv,hashlib,json
from pathlib import Path
from statistics import mean
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/generator_forecast_20261003/diagnostic'
CARDS=ROOT/'upstream/gosim-observer-examples/local-cards'

def parse(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
def report_audit(tag,mode,card):
    path=OUT/tag/mode/card
    messages=[json.loads(s) for s in (path/'messages.jsonl').read_text().splitlines()]
    reports=[m for m in messages if m.get('record_type')=='report_result']
    score=json.loads((CARDS/card/'config/v4_score_config.json').read_text())
    allowance=score['reporting']['false_report_free_allowance'];false_count=0
    faults=[r for r in csv.DictReader((CARDS/card/'truth/v4_events.csv').open()) if r['event_type']=='instrument_fault']
    audit=[]
    for r in reports:
        row={**r,'free_coupons_before':allowance-false_count}
        assert allowance-false_count>0
        if r['correct']:
            false_count=0
            active=[f for f in faults if parse(f['actual_start_utc'])<=parse(r['issued_at_utc'])<parse(f['actual_end_utc'])]
            assert len(active)==1
            row['fault_start_utc']=active[0]['actual_start_utc']
            row['fault_repair_delay_hours']=(parse(r['issued_at_utc'])-parse(active[0]['actual_start_utc'])).total_seconds()/3600
        else:
            false_count+=1;assert false_count<=allowance
        assert r['score_delta']>=0
        row['false_since_correct_after']=false_count;audit.append(row)
    decisions=list(csv.DictReader((path/'decisions.csv').open()))
    report_rows=[r for r in decisions if r['action']=='report']
    assert len(report_rows)==len(reports)
    assert all(r['duration_seconds']=='0' and r['start_utc']==r['end_utc'] and not r['observe_index'] for r in report_rows)
    return {'reports':audit,'all_direct_report_settlements_nonnegative':True,'no_coupon_overspend':True,
       'reports_zero_time_and_no_observe_index':True}

def main():
    development=json.loads((OUT/'development_results.json').read_text())
    reserve_train=json.loads((OUT/'reserve_train_results.json').read_text())
    validation=json.loads((OUT/'reserve_validation_results.json').read_text())
    heldout=json.loads((OUT/'heldout_results.json').read_text())
    lock=json.loads((OUT/'lock.json').read_text())
    manifest=json.loads((OUT/'heldout_manifest.json').read_text())
    source=ROOT/'runs/cold_neural_value_20261003/production_frozen'
    for key,file in [('source_policy_sha256','policy.py'),('source_feedback_sha256','research/feedback_model.py'),
                     ('clock_sha256','research/belief_clock.py'),('fixed_planner_sha256','research/cpu_phase_candidates.py')]:
        assert hashlib.sha256((source/file).read_bytes()).hexdigest()==manifest[key]
    assert hashlib.sha256((ROOT/'research/generator_diagnostic_model.py').read_bytes()).hexdigest()==lock['model_sha256']
    assert hashlib.sha256((ROOT/'research/generator_diagnostic_agent.py').read_bytes()).hexdigest()==lock['entry_sha256']
    rows=[]
    for card in ('L1','L2','L3','L4'):
        baseline=next(r for r in development+heldout if r['card']==card and r['mode']=='baseline')
        variant=next(r for r in reserve_train+validation+heldout if r['card']==card and r['mode']=='diagnostic-reserve')
        tag='reserve_train' if card=='L1' else 'reserve_validation' if card=='L2' else 'heldout'
        base_tag='development' if card in ('L1','L2') else 'heldout'
        assert baseline['exit_code']==variant['exit_code']==0
        assert baseline['termination']['reason']==variant['termination']['reason']=='survey_complete'
        rows.append({'card':card,'split':'train' if card=='L1' else 'validation' if card=='L2' else 'heldout',
           'baseline_score':baseline['score'],'diagnostic_score':variant['score'],
           'delta':variant['score']-baseline['score'],
           'component_deltas':{k:variant['components'][k]-v for k,v in baseline['components'].items()},
           'baseline_counts':baseline['counts'],'diagnostic_counts':variant['counts'],
           'diagnostic_stats':variant['diagnostic'],
           'baseline_report_audit':report_audit(base_tag,'baseline',card),
           'diagnostic_report_audit':report_audit(tag,'diagnostic-reserve',card)})
    heldout_mean=mean(r['delta'] for r in rows if r['split']=='heldout')
    result={'lock':lock,'rows':rows,'heldout_mean_delta':heldout_mean,
       'heldout_all_positive':all(r['delta']>0 for r in rows if r['split']=='heldout'),
       'source_policy_unchanged':True,'mechanism':'Preserve one false-report coupon for original strong evidence; allow additional fresh E diagnostics even with earthquake notices.',
       'checks':json.loads((OUT/'checks.json').read_text()),
       'live_fault':{'delta':json.loads((OUT/'live_fault.json').read_text())['diagnostic']['report']['total']-json.loads((OUT/'live_fault.json').read_text())['baseline']['report']['total']},
       'caveat':'Free direct settlement does not prove nonnegative season effect. False reports consume later opportunity and reset C/E belief. Only four public cards tested.'}
    result['decision']='Candidate for root integration validation' if result['heldout_all_positive'] else 'Do not adopt: heldout paired scores do not both improve.'
    (OUT/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'scores':[{k:r[k] for k in ('card','split','baseline_score','diagnostic_score','delta')} for r in rows],
       'heldout_mean_delta':heldout_mean,'decision':result['decision']},indent=2))

if __name__=='__main__':main()
