#!/usr/bin/env python3
"""Official local paired tests of the frozen free-coupon diagnostic rule."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib,json,os
from pathlib import Path
import shlex,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/generator_forecast_20261003/diagnostic'
OFFICIAL=ROOT/'upstream/gosim-observer-examples'
ENTRY=ROOT/'research/generator_diagnostic_agent.py'
SOURCE=ROOT/'runs/cold_neural_value_20261003/production_frozen'
TAG='training'

def run(mode,card):
    out=OUT/TAG/mode/card;out.mkdir(parents=True,exist_ok=True)
    cmd=[sys.executable,str(OFFICIAL/'runner/run_local.py'),'--card',str(OFFICIAL/'local-cards'/card),
         '--agent',shlex.join([sys.executable,'-u',str(ENTRY),'--mode',mode]),
         '--agent-cwd',str(SOURCE),'--wallclock','900','--out',str(out),'--quiet','--inherit-env']
    env={**os.environ,'OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OMP_NUM_THREADS':'1','PYTHONHASHSEED':'0'}
    started=time.monotonic();print(json.dumps({'event':'start','card':card,'mode':mode}),flush=True)
    with (out/'driver.log').open('w') as h:
        p=subprocess.run(cmd,stdout=h,stderr=subprocess.STDOUT,env=env,timeout=1020)
    report=json.loads((out/'score_report.json').read_text()) if (out/'score_report.json').exists() else {}
    rec={'card':card,'mode':mode,'exit_code':p.returncode,'elapsed':time.monotonic()-started,
         'score':report.get('total'),'components':report.get('components'),'counts':report.get('counts'),
         'termination':report.get('termination')}
    # The participant summary is a compact final JSON line in the agent log.
    if (out/'agent.log').exists():
        for line in (out/'agent.log').read_text().splitlines()[::-1]:
            try:
                obj=json.loads(line)
                if isinstance(obj,dict) and 'generator_diagnostic' in obj:
                    rec['diagnostic']=obj['generator_diagnostic'];break
            except (ValueError,TypeError):pass
    print(json.dumps(rec),flush=True);return rec

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--cards',nargs='+',required=True)
    ap.add_argument('--tag',required=True)
    ap.add_argument('--modes',nargs='+',default=['baseline','diagnostic'],choices=['baseline','diagnostic','diagnostic-reserve']);a=ap.parse_args()
    global TAG
    TAG=a.tag;OUT.mkdir(parents=True,exist_ok=True)
    manifest={'source':str(SOURCE),'split':{'training':'L1','validation':'L2','heldout':['L3','L4']},
      'params':{'efficiency_threshold':.68,'confidence_loss':.5,'fresh_seconds':7200,
                'cooldown_seconds':86400,'minimum_feedback':3},
      'choice':'existing source suspicion threshold, frozen before any diagnostic run',
      'modes':a.modes,'diagnostic_reserve_coupons':1,
      'planner':{'mode':'bypass','fixed_workload':True,'anchor_count':24},
      'entry_sha256':hashlib.sha256(ENTRY.read_bytes()).hexdigest(),
      'model_sha256':hashlib.sha256(ENTRY.with_name('generator_diagnostic_model.py').read_bytes()).hexdigest(),
      'source_policy_sha256':hashlib.sha256((SOURCE/'policy.py').read_bytes()).hexdigest(),
      'source_feedback_sha256':hashlib.sha256((SOURCE/'research/feedback_model.py').read_bytes()).hexdigest(),
      'clock_sha256':hashlib.sha256((SOURCE/'research/belief_clock.py').read_bytes()).hexdigest(),
      'fixed_planner_sha256':hashlib.sha256((SOURCE/'research/cpu_phase_candidates.py').read_bytes()).hexdigest(),
      'environment':{'PYTHONHASHSEED':'0','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'},
      'no_LLM':True,'no_truth_reads_in_solver':True,'gpu':False}
    (OUT/(TAG+'_manifest.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    results=[]
    for card in a.cards:
        with ThreadPoolExecutor(max_workers=2) as ex:
            for f in as_completed([ex.submit(run,m,card) for m in a.modes]):
                results.append(f.result());(OUT/(TAG+'_results.json')).write_text(json.dumps(results,indent=2)+'\n')

if __name__=='__main__':main()
