#!/usr/bin/env python3
"""WSL standard-library driver for four frozen Windows CUDA agent replays."""
import json
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent
windows_agent = 'C:' + str(root).removeprefix('/mnt/c') + '/agent/agent_gpu.py'
windows_python = '/mnt/c/Users/hedge/gosim-gpu-venv-20260926/Scripts/python.exe'
aggregate = {'cards': [], 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
for card in ('L1', 'L2', 'L3', 'L4'):
    output = root / 'results' / card
    output.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    print(json.dumps({'event': 'start', 'card': card, 'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}), flush=True)
    command = [sys.executable, str(root / 'runner/run_local.py'), '--card', str(root / 'local-cards' / card),
               '--agent', f'{windows_python} -u {windows_agent}', '--agent-cwd', str(root / 'agent'),
               '--out', str(output), '--wallclock', '900', '--inherit-env', '--quiet']
    with (output / 'driver.log').open('w') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    record = {'card': card, 'exit_code': result.returncode, 'elapsed_seconds': time.monotonic() - start}
    for name in ('workflow_result.json', 'score_report.json'):
        path = output / name
        if path.exists():
            record[name] = json.loads(path.read_text())
    aggregate['cards'].append(record)
    (root / 'suite_summary.json').write_text(json.dumps(aggregate, indent=2))
    report = record.get('score_report.json', {})
    print(json.dumps({'event': 'complete', 'card': card, 'exit_code': result.returncode,
                      'elapsed_seconds': record['elapsed_seconds'], 'score': report.get('total'),
                      'termination': report.get('termination')}), flush=True)
aggregate['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
(root / 'suite_summary.json').write_text(json.dumps(aggregate, indent=2))
