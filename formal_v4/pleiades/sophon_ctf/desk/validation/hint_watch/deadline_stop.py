#!/usr/bin/env python3
"""Local-only deadline guard; never invokes the desk, platform, or messaging."""
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import time

OUT = Path(__file__).resolve().parent
DEADLINE = dt.datetime(2026, 10, 7, 16, 0, tzinfo=dt.timezone.utc).timestamp()


def read_state():
    return json.loads((OUT / 'state.json').read_text())


def write_status(status, **extra):
    payload = {'status': status, 'pid': os.getpid(),
               'at': dt.datetime.now(dt.timezone.utc).isoformat(),
               'deadline': '2026-10-07T16:00:00Z', **extra}
    tmp = OUT / 'deadline_stop.tmp'
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(OUT / 'deadline_stop.json')


def main():
    lock = (OUT / 'deadline_stop.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    initial = read_state()
    initial_alerts = len(initial.get('alerts', []))
    initial_found = initial.get('baseline', {}).get('/desk', {}).get('found', [])
    write_status('armed', initial_alerts=initial_alerts)
    while time.time() < DEADLINE:
        if (OUT / 'CANCEL_DEADLINE_STOP').exists():
            write_status('cancelled')
            return
        if (OUT / 'STOP').exists():
            write_status('already_stopped')
            return
        time.sleep(min(30, max(0, DEADLINE - time.time())))
    if (OUT / 'CANCEL_DEADLINE_STOP').exists():
        write_status('cancelled')
        return
    current = read_state()
    changed = (len(current.get('alerts', [])) != initial_alerts
               or current.get('baseline', {}).get('/desk', {}).get('found', []) != initial_found)
    if changed:
        write_status('held_for_new_progress')
        return
    try:
        with (OUT / 'STOP').open('x') as out:
            out.write('2026-10-07T16:00:00Z: competition deadline; no new watch alert or solve.\n')
    except FileExistsError:
        pass
    write_status('stop_created')


if __name__ == '__main__':
    main()
