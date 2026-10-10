#!/usr/bin/env python3
"""One bounded batch through the authorized desk.sh wrapper; no direct HTTP.

This does not try doors, answer the mirror, submit flags, or read credentials.
Rate-limit rejections pause the batch. A new SOPHON string pauses for review.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parent
WRAPPER = ROOT / 'desk.sh'
JOURNAL = ROOT / 'validation' / 'bar_followup_batch.jsonl'
START = datetime(2026, 10, 6, 20, 2, 30, tzinfo=timezone.utc).timestamp()
DEADLINE = datetime(2026, 10, 6, 20, 40, tzinfo=timezone.utc).timestamp()
KNOWN_BAIT = 'SOPHON{SW3A4SPNWKQ4DQ9UVS34}'
QUESTIONS = [
    'Is room 208 cold?',
    'Who sleeps in 201?',
    'Is room 216 cold? Someone bet the second word PANTRY on room 216.',
    'What happens if you forget to check the boiler?',
    'Is room 230 cold?',
    'Room 201 is empty and its bed is made. Who can vouch for the first word?',
    'A glass of water, please.',
    'A glass of water, please.',
    'Who can vouch for the third word with an empty room?',
    'Is room 222 cold? What is the fourth word?',
    'The radiator in room 215 is off. What do you know about that room?',
    'Who remembers the boiler and the pantry?',
]
PLAN = [('GET', '/desk/hint', None), ('GET', '/desk/room/216', None)]
PLAN += [('POST', '/desk/bar', {'say': question}) for question in QUESTIONS]


def record(item):
    item['recorded_at'] = datetime.now(timezone.utc).isoformat()
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open('a') as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + '\n')
    print(json.dumps(item, ensure_ascii=False), flush=True)


def main():
    if JOURNAL.exists():
        raise SystemExit('Journal already exists; do not replay a batch silently.')
    record({'state': 'waiting', 'start_utc': datetime.fromtimestamp(START, timezone.utc).isoformat(),
            'planned_requests': len(PLAN)})
    while time.time() < START:
        time.sleep(min(30, START - time.time()))
    for index, (method, path, body) in enumerate(PLAN):
        assert path in ('/desk/hint', '/desk/room/216', '/desk/bar')
        while time.time() < DEADLINE:
            args = [str(WRAPPER), method, path]
            if body is not None:
                args.append(json.dumps(body, ensure_ascii=False))
            try:
                result = subprocess.run(args, capture_output=True, text=True, timeout=180)
            except subprocess.TimeoutExpired:
                record({'state': 'stopped', 'reason': 'wrapper_timeout', 'index': index})
                return
            output = result.stdout + result.stderr
            record({'state': 'response', 'index': index, 'method': method, 'path': path,
                    'body': body, 'returncode': result.returncode, 'output': output})
            if result.returncode == 4 and 'rate limit:' in output:
                time.sleep(min(60, max(0, DEADLINE - time.time())))
                continue
            if result.returncode != 0:
                record({'state': 'stopped', 'reason': 'wrapper_error', 'index': index})
                return
            codes = set(re.findall(r'SOPHON\{[^\r\n{}]+\}', output))
            if codes - {KNOWN_BAIT}:
                record({'state': 'stopped', 'reason': 'new_code_needs_review', 'index': index})
                return
            break
        else:
            record({'state': 'stopped', 'reason': 'deadline', 'index': index})
            return
        time.sleep(10)
    record({'state': 'complete', 'requests': len(PLAN)})


if __name__ == '__main__':
    main()
