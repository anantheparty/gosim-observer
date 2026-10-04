"""Official host short continuations; only public past actions enter participants."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
import os
import subprocess
import shlex
import sys
import time

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[2]
KIT=ROOT/'formal_v4/upstream/gosim-observer-examples'

def run(card,mode):
    folder=BASE/(card+'_night8')
    plan=json.loads((folder/'plan.json').read_text())
    out=folder/mode
    out.mkdir(exist_ok=False)
    env=dict(os.environ,SERVICE_MODE=mode,SERVICE_CUT_RANK=str(plan['cut_rank']),
        SERVICE_PREFIX=str(folder/'prefix_public_actions.jsonl'),SERVICE_STOP_UTC=plan['stop'],
        SERVICE_CAPTURE=str(out/'participant_public_trace.jsonl'),PYTHONDONTWRITEBYTECODE='1',
        OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    command=[sys.executable,str(KIT/'runner/run_local.py'),'--card',str(KIT/'local-cards'/card),
        '--agent',shlex.join(['env',*[key+'='+env[key] for key in ('SERVICE_MODE','SERVICE_CUT_RANK','SERVICE_PREFIX','SERVICE_STOP_UTC','SERVICE_CAPTURE','OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')],sys.executable,'-u','surplus_entry.py']),'--agent-cwd',str(BASE/'package'),
        '--wallclock','900','--out',str(out),'--quiet']
    start=time.perf_counter()
    with (out/'driver.log').open('w') as f:
        completed=subprocess.run(command,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=960)
    report=json.loads((out/'score_report.json').read_text()) if (out/'score_report.json').exists() else {}
    result={'card':card,'mode':mode,'elapsed':time.perf_counter()-start,'exit_code':completed.returncode,
        'total':report.get('total'),'components':report.get('components'),'counts':report.get('counts'),
        'termination':report.get('termination'),'actor_input':'initialize, currently reached public snapshot, public past action prefix',
        'host_only':'official scenario/truth and score outputs','wallclock':'fresh clock, historical planning bypassed; not historical snapshot parity'}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--cards',nargs='+',default=['L1','L2']);ap.add_argument('--modes',nargs='+',default=['control','debias','surplus']);ap.add_argument('--jobs',type=int,default=2)
    a=ap.parse_args();results=[]
    with ThreadPoolExecutor(max_workers=a.jobs) as e:
        jobs=[e.submit(run,c,m) for c in a.cards for m in a.modes]
        for job in as_completed(jobs):
            results.append(job.result());(BASE/'short_summary.json').write_text(json.dumps(results,indent=2)+'\n')
