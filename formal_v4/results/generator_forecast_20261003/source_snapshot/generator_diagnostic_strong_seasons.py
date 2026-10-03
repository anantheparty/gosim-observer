#!/usr/bin/env python3
"""Same-source, same-work paired phase24/native heldout confirmation."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib,json,os
from pathlib import Path
import shlex,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/generator_forecast_20261003/diagnostic'
OFFICIAL=ROOT/'upstream/gosim-observer-examples'
ENTRY=ROOT/'research/generator_diagnostic_strong_agent.py'

def run(mode,card,planner,source,tag):
    out=OUT/tag/mode/card;out.mkdir(parents=True,exist_ok=True)
    cmd=[sys.executable,str(OFFICIAL/'runner/run_local.py'),'--card',str(OFFICIAL/'local-cards'/card),
         '--agent',shlex.join([sys.executable,'-u',str(ENTRY),'--mode',mode,'--planner',planner]),
         '--agent-cwd',str(source),'--wallclock','900','--out',str(out),'--quiet','--inherit-env']
    env={**os.environ,'OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OMP_NUM_THREADS':'1','PYTHONHASHSEED':'0'}
    started=time.monotonic()
    with (out/'driver.log').open('w') as h:
        p=subprocess.Popen(cmd,stdout=h,stderr=subprocess.STDOUT,env=env)
        print(json.dumps({'event':'start','card':card,'mode':mode,'planner':planner,'runner_pid':p.pid,
            'driver_pid':os.getpid(),'log':str(out/'driver.log'),'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}),flush=True)
        rc=p.wait(timeout=1020)
    report=json.loads((out/'score_report.json').read_text()) if (out/'score_report.json').exists() else {}
    rec={'card':card,'mode':mode,'planner':planner,'exit_code':rc,'elapsed':time.monotonic()-started,
         'score':report.get('total'),'components':report.get('components'),'counts':report.get('counts'),
         'termination':report.get('termination')}
    if (out/'agent.log').exists():
        for line in (out/'agent.log').read_text().splitlines()[::-1]:
            try:
                obj=json.loads(line)
                if isinstance(obj,dict) and 'planner_summary' in obj:
                    rec['planner_summary']=obj['planner_summary'];rec['diagnostic']=obj.get('generator_diagnostic');break
            except (ValueError,TypeError):pass
    print(json.dumps(rec),flush=True);return rec

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--cards',nargs='+',default=['L3','L4'])
    ap.add_argument('--planner',choices=['phase24','native'],required=True)
    ap.add_argument('--parallel-cards',action='store_true');a=ap.parse_args()
    source=ROOT/'runs/cold_neural_value_20261003/production_frozen' if a.planner=='phase24' else ROOT/'runs/generator_diagnostic_native_snapshot_20261003'
    tag='strong_'+a.planner
    lock=json.loads((OUT/'lock.json').read_text())
    model=ROOT/'research/generator_diagnostic_model.py'
    assert hashlib.sha256(model.read_bytes()).hexdigest()==lock['model_sha256']
    relevant=['policy.py','policy_config.json','research/feedback_model.py','research/belief_clock.py','research/spatial_candidates.py']
    if a.planner=='phase24':relevant+=['research/cpu_phase_candidates.py']
    else:relevant+=['research/candidate_geometry_sweep.py','research/geometry_native.py',
      'research/geometry_native_darwin_arm64.dylib','research/geometry_native_linux_x86_64.so']
    manifest={'source':str(source),'planner':a.planner,'same_source_both_arms':True,
        'same_work_both_arms':True,'diagnostic_lock':lock,'source_hashes':{
          file:hashlib.sha256((source/file).read_bytes()).hexdigest() for file in relevant},
        'entry_sha256':hashlib.sha256(ENTRY.read_bytes()).hexdigest(),
        'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
        'no_LLM':True,'gpu':False,'cards':a.cards,'parallel_cards':a.parallel_cards}
    (OUT/(tag+'_manifest.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    results=[]
    batches=[a.cards] if a.parallel_cards else [[card] for card in a.cards]
    for cards in batches:
        with ThreadPoolExecutor(max_workers=2*len(cards)) as ex:
            for f in as_completed([ex.submit(run,m,card,a.planner,source,tag) for card in cards for m in ['baseline','diagnostic-reserve']]):
                results.append(f.result());(OUT/(tag+'_results.json')).write_text(json.dumps(results,indent=2)+'\n')

if __name__=='__main__':main()
