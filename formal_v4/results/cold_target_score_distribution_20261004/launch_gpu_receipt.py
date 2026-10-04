"""Host launch/exit/telemetry receipt. Does not alter the frozen model source."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parent
os.chdir(root)
receipt = root / 'GPU_PROCESS_RECEIPT.json'
if receipt.exists():
    raise RuntimeError('Refusing a second GPU fit launch receipt')
env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='4', MKL_NUM_THREADS='4')
def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
manifest = json.loads((root / 'DATA_MANIFEST.json').read_text())
assert manifest['world_count'] == 136 and manifest['no_test_generated']
for world in manifest['worlds']:
    path = root / 'datasets' / world['split'] / (str(world['seed']) + '.npz')
    assert sha(path) == world['npz_sha256'], ('transported data mismatch', world['seed'])
assert not list((root / 'datasets' / 'test').glob('*.npz'))
with (root / 'gpu_fit_stdout.log').open('wb') as output:
    command = [sys.executable, '-u', str(root / 'fit_driver.py')]
    child = subprocess.Popen(command, cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    info = dict(started_utc=utc(), actual_windows_process_pid=child.pid,
                launcher_pid=os.getpid(), command=command,
                source_freeze_sha256=sha(root / 'SOURCE_FREEZE.json'),
                data_manifest_sha256=sha(root / 'DATA_MANIFEST.json'),
                all_136_transported_npz_hashes_verified=True, test_world_count=0,
                scope='Authorized actual CUDA fit; external receipt only; frozen source unchanged')
    receipt.write_text(json.dumps(info, indent=2) + '\n')
    smi = Path('C:/Windows/System32/nvidia-smi.exe')
    with (root / 'gpu_telemetry.jsonl').open('a') as telemetry:
        while True:
            sample = dict(utc=utc(), actual_windows_process_pid=child.pid)
            for name, args in [('device', ['--query-gpu=name,memory.total,memory.used,power.draw,power.limit,utilization.gpu', '--format=csv,noheader,nounits']),
                               ('processes', ['--query-compute-apps=pid,process_name,used_gpu_memory', '--format=csv,noheader,nounits'])]:
                result = subprocess.run([str(smi), *args], capture_output=True, text=True)
                sample[name] = dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
            telemetry.write(json.dumps(sample) + '\n'); telemetry.flush()
            code = child.poll()
            if code is not None:
                info.update(completed_utc=utc(), raw_process_exit_code=code,
                            stdout_sha256=sha(root / 'gpu_fit_stdout.log'),
                            selected_model_lock_present=(root / 'SELECTED_MODEL_LOCK.json').exists())
                receipt.write_text(json.dumps(info, indent=2) + '\n')
                print(json.dumps(info), flush=True)
                raise SystemExit(code)
            time.sleep(20)
