#!/usr/bin/env python3
"""Run the authorized REDRUM evaluation after our envdiag wrapper exits.

Only calls the existing authorized sophon_eval.sh; no direct platform client.
"""
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'validation' / 'redrum_eval_queue.jsonl'
LOG = ROOT / 'validation' / 'redrum_eval_wrapper.log'
DEPENDENCY_PID = 87682
ZIP = ROOT.parent / 'packages' / 'o4s_sophon4_redrum_m.zip'


def save(**data):
    data['utc_epoch'] = time.time()
    with STATE.open('a') as handle:
        handle.write(json.dumps(data) + '\n')
    print(json.dumps(data), flush=True)


def main():
    with STATE.open('x'):
        pass
    assert ZIP.is_file()
    save(state='waiting_for_envdiag', dependency_pid=DEPENDENCY_PID, archive=str(ZIP))
    deadline = time.monotonic() + 3 * 3600
    while time.monotonic() < deadline:
        try:
            command = Path('/proc/%d/cmdline' % DEPENDENCY_PID).read_bytes()
        except FileNotFoundError:
            break
        if b'sophon_eval.sh' not in command or b'o4s_sophon3_envdiag.zip' not in command:
            break
        time.sleep(20)
    else:
        save(state='stopped', reason='dependency_wait_deadline')
        return
    save(state='authorized_wrapper_started')
    with LOG.open('x') as output:
        result = subprocess.run([str(ROOT / 'sophon_eval.sh'), str(ZIP),
                                 'Sophon REDRUM: seventeen exposures draw M'],
                                stdout=output, stderr=subprocess.STDOUT)
    save(state='wrapper_finished', returncode=result.returncode, output=str(LOG))


if __name__ == '__main__':
    main()
