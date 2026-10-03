"""Audit the strong phase24 confirmation without changing the locked controller."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from statistics import mean
from generator_diagnostic_analysis import report_audit
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/generator_forecast_20261003/diagnostic'

def main():
    manifest=json.loads((OUT/'strong_phase24_manifest.json').read_text())
    results=json.loads((OUT/'strong_phase24_results.json').read_text())
    source=Path(manifest['source'])
    for file,value in manifest['source_hashes'].items():
        assert hashlib.sha256((source/file).read_bytes()).hexdigest()==value
    assert hashlib.sha256((ROOT/'research/generator_diagnostic_model.py').read_bytes()).hexdigest()==manifest['model_sha256']
    assert hashlib.sha256((ROOT/'research/generator_diagnostic_strong_agent.py').read_bytes()).hexdigest()==manifest['entry_sha256']
    rows=[]
    for card in ['L3','L4']:
        baseline=next(r for r in results if r['card']==card and r['mode']=='baseline')
        variant=next(r for r in results if r['card']==card and r['mode']=='diagnostic-reserve')
        for r in [baseline,variant]:
            assert r['exit_code']==0 and r['termination']['reason']=='survey_complete'
            assert r['planner_summary']['phase_calls']>0 and r['planner_summary']['phase_exact_evaluations']>0
        rows.append({'card':card,'baseline_score':baseline['score'],'diagnostic_score':variant['score'],
            'delta':variant['score']-baseline['score'],
            'component_deltas':{k:variant['components'][k]-v for k,v in baseline['components'].items()},
            'baseline_counts':baseline['counts'],'diagnostic_counts':variant['counts'],
            'baseline_planner':baseline['planner_summary'],'diagnostic_planner':variant['planner_summary'],
            'baseline_report_audit':report_audit('strong_phase24','baseline',card),
            'diagnostic_report_audit':report_audit('strong_phase24','diagnostic-reserve',card),
            'diagnostic_stats':variant['diagnostic']})
    prior=json.loads((ROOT/'results/cpu_phase_pair_20261003/phase24/L4/score_report.json').read_text())
    current=json.loads((OUT/'strong_phase24/baseline/L4/score_report.json').read_text())
    result={'params':{'cpu_phase_mode':'phase','cpu_phase_fixed_workload':True,'anchor_count':24,
        'cpu_phase_top_count':4,'cpu_phase_local_target_count':50,'cpu_phase_boundary_target_count':24,
        'cpu_phase_exact_count':16,'OPENBLAS_NUM_THREADS':1,'MKL_NUM_THREADS':1,'OMP_NUM_THREADS':1,'PYTHONHASHSEED':0},
        'source_hashes_unchanged':True,'model_lock_unchanged':True,'rows':rows,
        'mean_delta':mean(r['delta'] for r in rows),'gate_passed':all(r['delta']>=0 for r in rows),
        'prior_strong_L4_reproduction':{'score_equal':prior['total']==current['total'],
           'components_equal':prior['components']==current['components'],
           'counts_equal':prior['counts']==current['counts'],
           'decisions_sha256_equal':prior['sha256']['decisions']==current['sha256']['decisions']},
        'decision':'Reject the current diagnostic controller. Bypass24 gains do not carry over to strong phase24.',
        'native':'Not started because parent required a passing strong phase24 gate first.',
        'finding':'Direct report cost is zero, but false-diagnostic belief resets and subsequent exposure trajectories can lose science/required credit.'}
    (OUT/'strong_phase24_summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'scores':[{k:r[k] for k in ['card','baseline_score','diagnostic_score','delta']} for r in rows],
      'mean_delta':result['mean_delta'],'reproduction':result['prior_strong_L4_reproduction'],'gate_passed':result['gate_passed']},indent=2))

if __name__=='__main__':main()
