#!/usr/bin/env python3
"""Official local whole-season held-out tests for the locked weather clock."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/generator_forecast_20261003'
OFFICIAL=ROOT/'upstream/gosim-observer-examples'
ENTRY=ROOT/'research/generator_forecast_fixed_agent.py'
SOURCE=ROOT/'runs/cold_neural_value_20261003/production_frozen'
TAG='seasons'

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
    print(json.dumps(rec),flush=True);return rec

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--cards',nargs='+',default=['L3','L4'])
    ap.add_argument('--tag',default='fixed24');a=ap.parse_args()
    global TAG
    TAG=a.tag
    manifest={'source':str(SOURCE),'split':{'training':'L1','validation':'L2','heldout':['L3','L4']},
              'params':{'night_variance':.03,'slot_variance':.015,'measurement_variance':.04},
              'entry_sha256':hashlib.sha256(ENTRY.read_bytes()).hexdigest(),
              'model_sha256':hashlib.sha256(ENTRY.with_name('generator_forecast_model.py').read_bytes()).hexdigest(),
              'source_policy_sha256':hashlib.sha256((SOURCE/'policy.py').read_bytes()).hexdigest(),
              'source_feedback_sha256':hashlib.sha256((SOURCE/'research/feedback_model.py').read_bytes()).hexdigest(),
              'clock_sha256':hashlib.sha256((SOURCE/'research/belief_clock.py').read_bytes()).hexdigest(),
              'environment':{'PYTHONHASHSEED':'0','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'},
              'no_LLM':True,'no_truth_reads_in_solver':True,'gpu':False}
    (OUT/(TAG+'_manifest.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    results=[]
    for card in a.cards:
        with ThreadPoolExecutor(max_workers=2) as ex:
            for f in as_completed([ex.submit(run,m,card) for m in ('baseline','hierarchical')]):
                results.append(f.result());(OUT/(TAG+'_results.json')).write_text(json.dumps(results,indent=2)+'\n')

if __name__=='__main__':main()
