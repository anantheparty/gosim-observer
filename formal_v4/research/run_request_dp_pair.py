"""Same-source direct request-DP / bypass complete-card control."""
import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path

root=Path(__file__).resolve().parent
windows_root='C:'+str(root).removeprefix('/mnt/c')
windows_python='/mnt/c/Users/hedge/gosim-gpu-venv-20260926/Scripts/python.exe'

def run(mode):
    output=root/'results'/mode/'L1'
    output.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    print(json.dumps({'event':'start','mode':mode,'card':'L1','utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}),flush=True)
    cmd=[sys.executable,str(root/'runner/run_local.py'),'--card',str(root/'local-cards/L1'),
        '--agent',f'{windows_python} -u {windows_root}/agents/{mode}/agent_request_dp.py',
        '--agent-cwd',str(root/'agents'/mode),'--out',str(output),'--wallclock','900','--inherit-env','--quiet']
    with (output/'driver.log').open('w') as log:
        finished=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
    record={'mode':mode,'card':'L1','exit_code':finished.returncode,'elapsed_seconds':time.monotonic()-started}
    for name in ('score_report.json','workflow_result.json'):
        if (output/name).exists():record[name]=json.loads((output/name).read_text())
    print(json.dumps({'event':'complete','mode':mode,'elapsed_seconds':record['elapsed_seconds'],
        'score':record.get('score_report.json',{}).get('total'),'termination':record.get('score_report.json',{}).get('termination')}),flush=True)
    return record

summary={'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'cards':[]}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    futures=[executor.submit(run,mode) for mode in ('bypass','deadline')]
    for future in concurrent.futures.as_completed(futures):
        summary['cards'].append(future.result())
        (root/'pair_summary.json').write_text(json.dumps(summary,indent=2))
summary['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
(root/'pair_summary.json').write_text(json.dumps(summary,indent=2))
