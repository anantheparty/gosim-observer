"""One same-source, full official L2 protocol pair on owned cores4-7."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/band_identification_20261004/stage2'
IMAGE='python@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def run(mode,args,slot):
    project=OUT/'participant';dest=OUT/'protocol'/mode/'L2';dest.mkdir(parents=True,exist_ok=True)
    container=['docker','run','--rm','--interactive','--user','1000:1000','--name',f'band-identification-{mode}-l2',
        '--cpus','2','--cpuset-cpus',f'{slot*2},{slot*2+1}','--memory','2048m','--memory-swap','2048m',
        '--pids-limit','128','--cap-drop=ALL','--security-opt=no-new-privileges','--ulimit','nofile=512:512',
        '--read-only','--tmpfs','/tmp:rw,nosuid,size=256m','--network','none','--log-driver','none',
        '--mount',f'type=bind,src={project},dst=/workspace,readonly',
        '--mount',f'type=bind,src={args.dependencies},dst=/deps,readonly',
        '--workdir','/workspace','--env','PYTHONPATH=/deps','--env','PYTHONDONTWRITEBYTECODE=1',
        '--env','OPENBLAS_NUM_THREADS=1','--env','OMP_NUM_THREADS=1','--env','MKL_NUM_THREADS=1',
        '--env',f'BAND_IDENTIFICATION_MODE={mode}',IMAGE,'python3','-u','-m','research.band_identification_agent']
    cmd=[sys.executable,str(args.kit/'runner/run_local.py'),'--card',str(args.kit/'local-cards/L2'),
         '--agent',shlex.join(container),'--agent-cwd',str(project),'--wallclock','900','--out',str(dest),'--quiet']
    begin=time.monotonic();print(json.dumps(dict(event='start',mode=mode,cpus=f'{slot*2},{slot*2+1}')),flush=True)
    with (dest/'driver.log').open('w') as log:completed=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=990)
    workflow=json.loads((dest/'workflow_result.json').read_text()) if (dest/'workflow_result.json').exists() else {}
    report=json.loads((dest/'score_report.json').read_text()) if (dest/'score_report.json').exists() else {}
    log=(dest/'agent.log').read_text() if (dest/'agent.log').exists() else ''
    rows=[]
    for line in log.splitlines():
        try:
            value=json.loads(line)
            if isinstance(value,dict):rows.append(value)
        except ValueError:pass
    result=dict(mode=mode,card='L2',total=report.get('total'),components=report.get('components'),counts=report.get('counts'),
        termination=workflow.get('termination_reason'),exit_code=completed.returncode,
        host_seconds=time.monotonic()-begin,accounted_seconds=workflow.get('accounted_wallclock_seconds'),
        traceback='Traceback' in log,participant_has_truth_mount=False,source_lock_sha256=sha(OUT/'source_lock.json'),
        public_constraint_logs=[r for r in rows if r.get('event')=='band_constraint_projection'],
        participant_summary=rows[-1] if rows else {},command=cmd)
    result['protocol_passed']=completed.returncode==0 and result['termination']=='survey_complete' and not result['traceback']
    (dest/'gate_result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('mode','total','termination','accounted_seconds','protocol_passed')}),flush=True)
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--dependencies',type=Path,required=True);ap.add_argument('--kit',type=Path,required=True)
    args=ap.parse_args()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run,m,args,2+i) for i,m in enumerate(('control','constraint'))]
        results=[f.result() for f in futures]
    (OUT/'protocol_summary.json').write_text(json.dumps(results,indent=2)+'\n')
