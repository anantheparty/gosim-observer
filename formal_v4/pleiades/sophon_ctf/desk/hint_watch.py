#!/usr/bin/env python3
"""Hourly, read-only Sophon watch using only the approved desk wrapper."""
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/home/shu/kamico/observer')
DESK = ROOT / 'work/sophon_desk'
OUT = DESK / 'validation/hint_watch'
CALLS = DESK / 'desk_calls.jsonl'
PEER = 'c0d5a1e6-962e-4e7e-b489-3ca01774dce2'
REPLY_TO = '41c17175-fbc4-4e82-a9a0-e1173e6acb56'
ROUTES = ('/desk/hint', '/desk')
INTERVAL = 3600


def utc(epoch=None):
    return dt.datetime.fromtimestamp(time.time() if epoch is None else epoch, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def epoch(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def save(state):
    tmp = OUT / 'state.tmp'
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(OUT / 'state.json')


def journal(event, **fields):
    with (OUT / 'events.jsonl').open('a') as f:
        f.write(json.dumps({'t': utc(), 'event': event, **fields}, ensure_ascii=False) + '\n')


def records(offset=0):
    with CALLS.open('rb') as f:
        f.seek(offset)
        data = f.read()
    for line in data.splitlines():
        try:
            row = json.loads(line)
            route = row.get('path', '').removeprefix('/functions/v1/sophon')
            if row.get('method') == 'GET' and route in ROUTES:
                yield route, row
        except (ValueError, TypeError, AttributeError):
            continue


def decoded(row):
    if row.get('status') != 200:
        raise ValueError('HTTP status ' + str(row.get('status')))
    reply = row['reply']
    body = json.loads(reply) if isinstance(reply, str) else reply
    if not isinstance(body, dict) or body.get('ok') is not True:
        raise ValueError('response is not an ok object')
    return body


def changes(route, before, after):
    if route == '/desk/hint':
        hints = after.get('hints')
        return ['hints 非空且为首次发现或内容改变'] if hints and hints != before.get('hints') else []
    return [key + ' 发生变化' for key in ('doors', 'next')
            if ({key: before[key]} if key in before else {}) !=
               ({key: after[key]} if key in after else {})]


def query(route):
    # No response text can select commands, methods, paths, or request bodies.
    if route not in ROUTES:
        raise ValueError('route not allowed')
    offset = CALLS.stat().st_size
    result = subprocess.run([str(DESK / 'desk.sh'), 'GET', route], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    matches = [row for key, row in records(offset) if key == route]
    if not matches:
        raise RuntimeError('wrapper returned no matching audit record; exit=' + str(result.returncode))
    row = matches[-1]
    body = decoded(row)
    if result.returncode:
        raise RuntimeError('wrapper exit=' + str(result.returncode))
    return row, body


def notify(message):
    # The HAPI CLI owns its authentication. Never inspect or print credentials.
    result = subprocess.run(['hapi', 'ping-peer', PEER, '--message-file', '-'],
                            input=message, cwd=ROOT, capture_output=True,
                            text=True, timeout=60)
    output = result.stdout + result.stderr
    return result.returncode == 0 and 'delivered' in output.lower()


def alert(state, route, reasons, row, body):
    original = row['reply'] if isinstance(row['reply'], str) else json.dumps(row['reply'], ensure_ascii=False)
    message = (f'From: Sophon 每小时值守\nReply-To: {REPLY_TO}\n目的：只读查询发现变化\n\n'
               f'{row["t"]} GET {route} → HTTP {row["status"]}\n'
               + '；'.join(reasons) + '\n\n响应原文：\n' + original
               + '\n\n仅转发响应内容；没有提交、开门或上传。')
    key = utc().replace(':', '').replace('-', '') + '_' + route.rsplit('/', 1)[-1]
    path = OUT / (key + '.txt')
    path.write_text(message + '\n')
    # Persist before sending. Ambiguous delivery is retained for inspection, not blindly retried.
    entry = {'t': utc(), 'route': route, 'message_file': str(path), 'delivery': 'pending'}
    state.setdefault('alerts', []).append(entry)
    save(state)
    try:
        delivered = notify(message)
        entry['delivery'] = 'delivered' if delivered else 'unconfirmed'
    except Exception as exc:
        entry['delivery'] = 'unconfirmed'
        entry['error'] = type(exc).__name__
    save(state)
    journal('alert', **entry)


def initial_state():
    latest = {}
    for route, row in records():
        try:
            decoded(row)
        except (ValueError, KeyError, TypeError):
            continue
        latest[route] = row
    if set(latest) != set(ROUTES):
        raise RuntimeError('Both existing successful baseline records are required')
    next_at = max(time.time(), max(epoch(row['t']) for row in latest.values()) + INTERVAL)
    return {'baseline': {route: decoded(row) for route, row in latest.items()},
            'baseline_time': {route: row['t'] for route, row in latest.items()},
            'next_poll_epoch': next_at, 'next_poll_utc': utc(next_at), 'cycles': 0, 'alerts': []}


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    lock = (OUT / 'watch.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state_path = OUT / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else initial_state()
    state.update(pid=os.getpid(), status='running', started_utc=utc())
    save(state)
    journal('started', pid=os.getpid(), next_poll_utc=state['next_poll_utc'])
    print(json.dumps({'pid': os.getpid(), 'next_poll_utc': state['next_poll_utc']}, ensure_ascii=False), flush=True)
    while not (OUT / 'STOP').exists():
        remaining = state['next_poll_epoch'] - time.time()
        if remaining > 0:
            time.sleep(min(remaining, 30))
            continue
        # Set next time first: failures or restarts must not cause rapid retries.
        state['next_poll_epoch'] = time.time() + INTERVAL
        state['next_poll_utc'] = utc(state['next_poll_epoch'])
        state['cycles'] += 1
        save(state)
        for route in ROUTES:
            if (OUT / 'STOP').exists():
                break
            try:
                row, body = query(route)
                before = state['baseline'][route]
                reasons = changes(route, before, body)
                journal('response', route=route, record=row, changed=reasons)
                if reasons:
                    alert(state, route, reasons, row, body)
                state['baseline'][route] = body
                state['baseline_time'][route] = row['t']
                state.setdefault('errors', {}).pop(route, None)
            except Exception as exc:
                # Keep the last valid baseline so a failed query cannot imitate removed doors.
                state.setdefault('errors', {})[route] = {'t': utc(), 'error': str(exc)}
                journal('query_error', route=route, error=str(exc))
            save(state)
    state.update(status='stopped', stopped_utc=utc())
    save(state)
    journal('stopped')


def self_test():
    assert not changes('/desk/hint', {'hints': []}, {'hints': []})
    assert changes('/desk/hint', {'hints': []}, {'hints': ['new']})
    assert not changes('/desk/hint', {'hints': ['new']}, {'hints': ['new']})
    assert changes('/desk/hint', {'hints': ['new']}, {'hints': ['different']})
    assert not changes('/desk', {'doors': {'a': 'b'}}, {'doors': {'a': 'b'}, 'found': [1]})
    assert changes('/desk', {'doors': {'a': 'b'}}, {'doors': {'a': 'c'}})
    assert changes('/desk', {'next': 'old'}, {'next': 'new'})
    assert changes('/desk', {'next': 'old'}, {})
    assert changes('/desk', {}, {'next': None})
    assert decoded({'status': 200, 'reply': '{"ok":true,"hints":[]}'})['hints'] == []
    for row in ({'status': 404, 'reply': '{}'}, {'status': 200, 'reply': '[]'},
                {'status': 200, 'reply': '{"ok":false}'}):
        try:
            decoded(row)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid response accepted')
    print('13 offline checks passed; no subprocesses or network calls')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    self_test() if args.self_test else run()
