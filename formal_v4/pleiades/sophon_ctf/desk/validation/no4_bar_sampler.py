#!/usr/bin/env python3
"""One bounded post-fooled bar sample, using only the audited desk wrapper."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path('/home/shu/kamico/observer')
DESK = ROOT / 'work/sophon_desk'
OUT = DESK / 'validation/no4_bar_sampler'
CALLS = DESK / 'desk_calls.jsonl'
STAMPS = ROOT / 'work/online/desk_calls.stamps'
PEER = 'c0d5a1e6-962e-4e7e-b489-3ca01774dce2'
REPLY_TO = '41c17175-fbc4-4e82-a9a0-e1173e6acb56'
MAX_CALLS = 120
START_WHEN_RECENT_AT_MOST = 20
ORDINARY_KEYS = {'ok', 'johnny', 'door', 'message'}


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def recent_calls() -> int:
    cutoff = int(time.time()) - 3600
    try:
        return sum(int(line) >= cutoff for line in STAMPS.read_text().splitlines() if line.strip())
    except FileNotFoundError:
        return 0


def save(state: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / 'state.tmp'
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(OUT / 'state.json')


def newest_bar_record(offset: int) -> dict:
    with CALLS.open('rb') as stream:
        stream.seek(offset)
        lines = stream.read().splitlines()
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if row.get('method') == 'POST' and row.get('path', '').endswith('/desk/bar'):
            rows.append(row)
    if not rows:
        raise RuntimeError('desk wrapper appended no bar audit row')
    return rows[-1]


def notify(row: dict, reason: str) -> str:
    original = row.get('reply', '')
    message = (f'From: Sophon No.4 受限采样器\nReply-To: {REPLY_TO}\n'
               f'目的：酒吧出现非普通响应，停止采样\n\n{reason}\n\n'
               f'{row.get("t")} POST /desk/bar → HTTP {row.get("status")}\n'
               f'响应原文：\n{original}\n\n未提交旗、未开门、未上传。')
    result = subprocess.run(['hapi', 'ping-peer', PEER, '--message-file', '-'],
                            input=message, cwd=ROOT, capture_output=True,
                            text=True, timeout=60)
    return 'delivered' if result.returncode == 0 and 'delivered' in (result.stdout + result.stderr).lower() else 'unconfirmed'


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    state = {'pid': os.getpid(), 'status': 'waiting', 'started_utc': utc(),
             'max_calls': MAX_CALLS, 'calls': 0}
    save(state)
    while recent_calls() > START_WHEN_RECENT_AT_MOST:
        if (OUT / 'STOP').exists():
            state.update(status='stopped', stopped_utc=utc())
            save(state)
            return
        state.update(recent_last_hour=recent_calls(), checked_utc=utc())
        save(state)
        time.sleep(30)

    state.update(status='sampling', sampling_started_utc=utc())
    save(state)
    for index in range(1, MAX_CALLS + 1):
        if (OUT / 'STOP').exists():
            state.update(status='stopped', stopped_utc=utc())
            save(state)
            return
        offset = CALLS.stat().st_size
        result = subprocess.run([str(DESK / 'desk.sh'), 'POST', '/desk/bar',
                                 '{"say":"listen"}'], cwd=ROOT,
                                capture_output=True, text=True, timeout=90)
        row = newest_bar_record(offset)
        body = json.loads(row.get('reply', '{}'))
        state.update(calls=index, last_utc=row.get('t'), last_status=row.get('status'))
        special = (result.returncode != 0 or row.get('status') != 200 or
                   not isinstance(body, dict) or set(body) != ORDINARY_KEYS or
                   body.get('ok') is not True)
        if special:
            reason = '响应字段、状态或 wrapper 退出码偏离普通 gossip 合同。'
            state.update(status='special', special_record=row,
                         notification=notify(row, reason), finished_utc=utc())
            save(state)
            return
        save(state)
    state.update(status='completed_no_special', finished_utc=utc(), recent_last_hour=recent_calls())
    save(state)


if __name__ == '__main__':
    run()
