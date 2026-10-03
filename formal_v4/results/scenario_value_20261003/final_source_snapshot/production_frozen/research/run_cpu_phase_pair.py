"""Same-source CPU phase/bypass full-card controls, no external accelerator."""
import argparse
import concurrent.futures
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

root=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument('--cards',nargs='+',choices=('L1','L2','L3','L4'),default=['L1','L4'])
parser.add_argument('--modes',nargs='+',choices=('bypass','phase','bypass24','phase24','deadline'),default=['bypass','phase'])
parser.add_argument('--entry',default='agent_cpu_phase.py')
args=parser.parse_args()

def run(mode,card):
    output=root/'results'/mode/card
    output.mkdir(parents=True,exist_ok=True)
    start=time.monotonic()
    print(json.dumps({'event':'start','mode':mode,'card':card,'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}),flush=True)
    entry=root/'agents'/mode/args.entry
    command=[sys.executable,str(root/'runner/run_local.py'),'--card',str(root/'local-cards'/card),
        '--agent',shlex.join([sys.executable,'-u',str(entry)]),'--agent-cwd',str(entry.parent),
        '--out',str(output),'--wallclock','900','--inherit-env','--quiet']
    environment={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    with (output/'driver.log').open('w') as log:
        completed=subprocess.run(command,env=environment,stdout=log,stderr=subprocess.STDOUT)
    result={'mode':mode,'card':card,'exit_code':completed.returncode,'elapsed_seconds':time.monotonic()-start}
    for name in ('score_report.json','workflow_result.json'):
        if (output/name).exists():result[name]=json.loads((output/name).read_text())
    print(json.dumps({'event':'complete','mode':mode,'card':card,'elapsed_seconds':result['elapsed_seconds'],
        'score':result.get('score_report.json',{}).get('total'),'termination':result.get('score_report.json',{}).get('termination')}),flush=True)
    return result

summary={'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'cards':[]}
with concurrent.futures.ThreadPoolExecutor(max_workers=len(args.modes)) as executor:
    for card in args.cards:
        futures=[executor.submit(run,mode,card) for mode in args.modes]
        for future in concurrent.futures.as_completed(futures):
            summary['cards'].append(future.result())
            (root/'pair_summary.json').write_text(json.dumps(summary,indent=2))
summary['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
(root/'pair_summary.json').write_text(json.dumps(summary,indent=2))
