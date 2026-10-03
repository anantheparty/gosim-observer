"""Fixed source/parameters, official full-season strong CPUPhase pair."""
from __future__ import annotations
import argparse,concurrent.futures,hashlib,json,os,shlex,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/scenario_value_20261003'
SOURCE=ROOT/'runs/cold_neural_value_20261003/production_frozen'
ENTRY=ROOT/'research/scenario_value_agent.py'
OFFICIAL=ROOT/'upstream/gosim-observer-examples'

def run(mode,card,tag):
    out=OUT/tag/mode/card;out.mkdir(parents=True,exist_ok=True)
    if (out/'score_report.json').exists():raise ValueError('new tag required')
    env={**os.environ,'OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OMP_NUM_THREADS':'1','PYTHONHASHSEED':'0'}
    cmd=[sys.executable,str(OFFICIAL/'runner/run_local.py'),'--card',str(OFFICIAL/'local-cards'/card),
        '--agent',shlex.join([sys.executable,'-u',str(ENTRY),'--mode',mode]),'--agent-cwd',str(SOURCE),
        '--wallclock','900','--out',str(out),'--quiet','--inherit-env']
    started=time.monotonic()
    with (out/'driver.log').open('w') as log:
        process=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,env=env)
        record=dict(event='started',mode=mode,card=card,pid=process.pid,log=str(out/'driver.log'))
        (out/'process.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)
        code=process.wait(timeout=1020)
    report=json.loads((out/'score_report.json').read_text()) if (out/'score_report.json').exists() else {}
    workflow=json.loads((out/'workflow_result.json').read_text()) if (out/'workflow_result.json').exists() else {}
    record=dict(mode=mode,card=card,exit_code=code,elapsed=time.monotonic()-started,score=report.get('total'),
        components=report.get('components'),counts=report.get('counts'),termination=report.get('termination'),
        agent_seconds=workflow.get('agent_wallclock_seconds'),output=str(out))
    (out/'summary.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)
    return record

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--cards',nargs='+',default=['L1'])
    ap.add_argument('--modes',nargs='+',default=['baseline','scenario']);ap.add_argument('--tag',default='locked16x8')
    args=ap.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    from scenario_value_model import PARAMS
    files=[ENTRY,ENTRY.with_name('scenario_value_model.py'),ENTRY.with_name('scenario_value_checks.py')]
    files.extend(p for p in SOURCE.rglob('*.py') if '__pycache__' not in p.parts)
    files.append(SOURCE/'policy_config.json')
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    manifest=dict(schema='scenario-value-full-season-v1',params=PARAMS,source=str(SOURCE),source_hashes=hashes,
        split=dict(development=['L1'],validation=['L2'],locked_holdout=['L3','L4']),
        parameter_source='official reference generator delta-method component variances, no card truth fitting',
        fixed_work=dict(anchor_count=24,cpu_phase_top_count=4,cpu_phase_local_target_count=50,
            cpu_phase_boundary_target_count=24,cpu_phase_exact_count=16),wallclock=900,
        cpu_threads=1,max_parallel=2,no_llm=True,no_truth_features=True,modes=args.modes,cards=args.cards)
    (OUT/(args.tag+'_manifest.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    results=[]
    for card in args.cards:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            pending=[pool.submit(run,mode,card,args.tag) for mode in args.modes]
            for future in concurrent.futures.as_completed(pending):
                results.append(future.result());(OUT/(args.tag+'_results.json')).write_text(json.dumps(results,indent=2)+'\n')
if __name__=='__main__':
    sys.path.insert(0,str(SOURCE));main()
