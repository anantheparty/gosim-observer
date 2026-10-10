#!/usr/bin/env python3
"""Watch local download completion and notify the main HAPI session once.

No platform requests, credential access, submissions or engine runs. The authorized
sophon_eval.sh owns all remote actions. This watcher only reads its local output.
"""
import importlib.util
import json
import subprocess
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ONLINE = ROOT / 'work/online'
OUT = ROOT / 'work/sophon_desk/validation'
PEER = 'c0d5a1e6-962e-4e7e-b489-3ca01774dce2'
REPLY = '41c17175-fbc4-4e82-a9a0-e1173e6acb56'
HAPI = '/home/shu/.nvm/versions/node/v24.13.0/bin/hapi'
STATE = OUT / 'saturn_full_watch.json'


def notify(message):
    response = subprocess.run([HAPI, 'ping-peer', PEER,
        'From: Sophon 探测子会话（本地完成通知）\nReply-To: ' + REPLY +
        '\n目的：土星 full 下载状态\n\n' + message],
        capture_output=True, text=True, timeout=45)
    # Persist the delivery result, so a timeout never causes an automatic resend.
    return {'returncode': response.returncode,
            'stdout': response.stdout[-2000:], 'stderr': response.stderr[-1000:]}


def scan(directory):
    spec = importlib.util.spec_from_file_location('scan_receipts', ROOT / 'work/sophon_desk/scan_receipts.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    records = []
    for path in sorted(directory.rglob('*')):
        if not path.is_file():
            continue
        if path.suffix == '.zip':
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    if not info.is_dir() and info.file_size <= module.CAP:
                        records.append(module.scan_text(str(path) + '!' + info.filename, archive.read(info)))
        elif path.suffix in ('.json', '.jsonl', '.log', '.txt', '.csv') and path.stat().st_size <= module.CAP:
            records.append(module.scan_text(str(path), path.read_bytes()))
    report = {'flags': sorted({f for record in records for f in record['flags']}), 'files': records}
    target = OUT / (directory.name + '_watch_receipts.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return target, report


def main():
    if STATE.exists():
        raise SystemExit('existing watcher state; refusing duplicate notification')
    state = {'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'status': 'waiting'}
    STATE.write_text(json.dumps(state, indent=2) + '\n')
    deadline = time.monotonic() + 4 * 3600
    candidate, signature, stable_since = None, None, None
    while time.monotonic() < deadline:
        directories = sorted({p for pattern in ('o4s_sophon3_saturn_full_*', 'sophon3_saturn_full_*')
                              for p in ONLINE.glob(pattern) if p.is_dir()})
        for directory in directories:
            paths = sorted(p for p in directory.rglob('*') if p.is_file())
            basenames = {p.name for p in paths}
            if not {'result.zip', 'run.json', 'diagnostics.json', 'boards.json'} <= basenames:
                continue
            current = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths)
            if directory != candidate or current != signature:
                candidate, signature, stable_since = directory, current, time.monotonic()
                continue
            if time.monotonic() - stable_since < 30:
                continue
            try:
                report_path, report = scan(directory)
                runs = []
                for p in directory.rglob('run.json'):
                    run = json.loads(p.read_text())
                    runs.append({k: run.get(k) for k in ('id', 'status', 'score', 'score_check')})
            except (OSError, ValueError, zipfile.BadZipFile):
                continue
            state.update(status='download_ready', directory=str(directory),
                         receipt_scan=str(report_path), flags=report['flags'], runs=runs)
            STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
            body = ('授权脚本的下载目录已经稳定：' + str(directory) + '\n'
                    '自动离线扫描：' + str(report_path) + '\n'
                    'flags=' + json.dumps(report['flags'], ensure_ascii=False) + '\n'
                    'run=' + json.dumps(runs, ensure_ascii=False) + '\n'
                    '本通知器没有提交任何flag或调用平台。请给 Reply-To 子会话发一条完成通知，'
                    '唤醒它继续人工核对回执、提交真实flag及安排下一轮。')
            try:
                state['delivery'] = notify(body)
            except subprocess.TimeoutExpired:
                state['delivery'] = {'ambiguous': 'HAPI call timed out; inspect before retry'}
            STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
            return
        time.sleep(30)
    state['status'] = 'deadline_reached'
    STATE.write_text(json.dumps(state, indent=2) + '\n')
    try:
        state['delivery'] = notify('本地监视已等4小时，未见完整土星full结果。请唤醒子会话检查已有评测脚本，不要重复上传。')
    except subprocess.TimeoutExpired:
        state['delivery'] = {'ambiguous': 'HAPI call timed out; inspect before retry'}
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
