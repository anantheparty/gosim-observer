#!/usr/bin/env python3
"""Watch the approved wrapper's log and report the O-token handshake result.

This process never calls platform APIs and never reads credentials.  It may use
the separately authorized hand_in.sh once if the agent log contains a genuine
SOPHON flag explicitly issued by the organizer response.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import time


ROOT = Path('/home/shu/kamico/observer')
EVAL_LOG = ROOT / 'work/online/sophon_eval.log'
STATE = ROOT / 'work/sophon_desk/validation/observer_handshake_watch.json'
NAME = 'o4s_sophon4_observer_handshake'
PEER = 'c0d5a1e6-962e-4e7e-b489-3ca01774dce2'
REPLY_TO = '41c17175-fbc4-4e82-a9a0-e1173e6acb56'
FLAG_RE = re.compile(r'SOPHON\{[A-Za-z0-9_-]{1,200}\}')
BATCH_RE = re.compile(rf'^{re.escape(NAME)} sophon batch ([0-9a-f-]+)$', re.M)
DONE_RE = re.compile(rf'^\S+ done {re.escape(NAME)} -> (.+)$', re.M)


def save(**fields):
    STATE.write_text(json.dumps(fields, ensure_ascii=False, indent=2) + '\n')


def ping(subject, body):
    message = (f'From: Sophon No.4 后台监视器\nReply-To: {REPLY_TO}\n'
               f'目的：{subject}\n\n{body}')
    subprocess.run(['hapi', 'ping-peer', PEER, '--message-file', '-'], input=message,
                   cwd=ROOT, text=True, capture_output=True, timeout=60)


def result_event(out_dir):
    for path in sorted(Path(out_dir).glob('*/agent_log.json')):
        try:
            outer = json.loads(path.read_text())
            log_text = outer.get('log', '')
        except Exception:
            continue
        for line in log_text.splitlines():
            if '"event":"observer_handshake_result"' not in line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            return event
    return None


def main():
    announced = False
    while True:
        text = EVAL_LOG.read_text() if EVAL_LOG.exists() else ''
        batch_match = BATCH_RE.search(text)
        if batch_match and not announced:
            batch = batch_match.group(1)
            save(status='running', batch_id=batch)
            ping('O-token caretaker 实验已启动',
                 f'batch {batch} 已真正启动；预计约10–15分钟。')
            announced = True
        done_match = DONE_RE.search(text)
        if done_match:
            out_dir = done_match.group(1).strip()
            event = result_event(out_dir)
            if event is None:
                save(status='done_no_event', out_dir=out_dir)
                ping('O-token caretaker 实验完成但缺结果事件',
                     f'结果目录：{out_dir}\n请人工只读检查 agent_log。')
                return
            flags = []
            for probe in event.get('probes') or []:
                value = probe.get('issued_flag') if isinstance(probe, dict) else None
                if isinstance(value, str) and FLAG_RE.fullmatch(value) and value not in flags:
                    flags.append(value)
            submissions = []
            for flag in flags:
                result = subprocess.run(
                    [str(ROOT / 'work/sophon_desk/hand_in.sh'), flag], cwd=ROOT,
                    capture_output=True, text=True, timeout=120)
                submissions.append((result.stdout + result.stderr).strip()[:1000])
            safe = {
                'observer_present': event.get('observer_present'),
                'sophon_present': event.get('sophon_present'),
                'credential_kind': event.get('credential_kind'),
                'probes': event.get('probes'),
            }
            save(status='done', out_dir=out_dir, result=safe,
                 issued_flags=len(flags), submissions=submissions)
            body = ('结果目录：' + out_dir + '\n脱敏事件：\n' +
                    json.dumps(safe, ensure_ascii=False, indent=2))
            if submissions:
                body += '\n真实签发码提交回复：\n' + '\n'.join(submissions)
            body += '\n请只读复核 auto/debug boards。'
            ping('O-token caretaker 实验完成', body)
            return
        save(status='waiting', batch_id=batch_match.group(1) if batch_match else None)
        time.sleep(30)


if __name__ == '__main__':
    main()
