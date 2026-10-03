"""Paired, same-source phase/bypass full-card control using the official runner."""
import concurrent.futures
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent
windows_root = 'C:' + str(root).removeprefix('/mnt/c')
windows_python = '/mnt/c/Users/hedge/gosim-gpu-venv-20260926/Scripts/python.exe'
parser = argparse.ArgumentParser()
parser.add_argument('--cards', nargs='+', choices=('L1','L2','L3','L4'), default=['L1'])
args = parser.parse_args()

def run(mode, card):
    output = root / 'results' / mode / card
    output.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    print(json.dumps({'event':'start','mode':mode,'card':card,'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}),flush=True)
    command = [sys.executable,str(root/'runner/run_local.py'),'--card',str(root/'local-cards'/card),
               '--agent',f'{windows_python} -u {windows_root}/agents/{mode}/agent_gpu_phase.py',
               '--agent-cwd',str(root/'agents'/mode),'--out',str(output),'--wallclock','900','--inherit-env','--quiet']
    with (output/'driver.log').open('w') as log:
        completed = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    result = {'mode':mode,'card':card,'exit_code':completed.returncode,'elapsed_seconds':time.monotonic()-start}
    for name in ('score_report.json','workflow_result.json'):
        if (output/name).exists():result[name]=json.loads((output/name).read_text())
    print(json.dumps({'event':'complete','mode':mode,'card':card,'elapsed_seconds':result['elapsed_seconds'],
                      'score':result.get('score_report.json',{}).get('total'),
                      'termination':result.get('score_report.json',{}).get('termination')}),flush=True)
    return result

summary={'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'cards':[]}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    for card in args.cards:
        pending=[executor.submit(run,mode,card) for mode in ('bypass','phase')]
        for future in concurrent.futures.as_completed(pending):
            summary['cards'].append(future.result())
            (root/'pair_summary.json').write_text(json.dumps(summary,indent=2))
summary['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
(root/'pair_summary.json').write_text(json.dumps(summary,indent=2))
