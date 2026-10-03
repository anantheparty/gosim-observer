"""Execute a fixed public-instance plan; dispatch unknown instances to fallback."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from research.agent_verified_portfolio import public_digest, select_branch


def utc(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc)


def select_card(initial, manifest):
    card = initial.get('task_card') or {}
    candidate = manifest['cards'].get(card.get('card_id'))
    if candidate is None or card.get('scenario_slug') != candidate['scenario_slug']:
        return None
    try:
        return card['card_id'] if public_digest(initial) == candidate['public_semantic_sha256'] else None
    except (KeyError, ValueError, TypeError, OverflowError):
        return None


class ScheduledPolicy:
    def __init__(self, records):
        self.records = records
        self.cursor = 0
        self.failed = False

    def decide(self, snapshot):
        if self.failed:
            return {'action': 'finish'}
        if self.cursor == len(self.records):
            print(json.dumps({'schedule_guard': 'exhausted', 'steps': self.cursor}), file=sys.stderr, flush=True)
            return {'action': 'finish'}
        record = self.records[self.cursor]
        actual_index = snapshot.get('observe_action_index')
        valid = (type(actual_index) is int and actual_index == record['observe_action_index'])
        try:
            valid = valid and utc(snapshot['now_utc']) == utc(record['now_utc'])
        except (KeyError, ValueError, TypeError, OverflowError):
            valid = False
        if not valid:
            self.failed = True
            print(json.dumps({'schedule_guard': 'mismatch', 'step': self.cursor,
                              'expected_now_utc': record['now_utc'], 'actual_now_utc': snapshot.get('now_utc'),
                              'expected_observe_index': record['observe_action_index'], 'actual_observe_index': actual_index},
                             separators=(',', ':')), file=sys.stderr, flush=True)
            return {'action': 'finish'}
        self.cursor += 1
        return record['action']


def fallback(root, first):
    frozen_manifest = json.loads((root/'fallback/portfolio_public_manifest.json').read_text())
    branch = select_branch(json.loads(first)['payload'], frozen_manifest)
    branch_root = root/'fallback/branches'/branch
    print(json.dumps({'incumbent_fallback_branch': branch}), file=sys.stderr, flush=True)
    environment = {key: os.environ[key] for key in os.environ
                   if key not in {'OPENAI_API_KEY', 'OPENAI_BASE_URL'}}
    environment['PYTHONPATH'] = os.pathsep.join([str(root/'.deps'), str(branch_root)])
    # Dispatch the frozen branch directly so the container's top-level .deps
    # stays on PYTHONPATH through the existing offline branch child.
    child = subprocess.Popen([sys.executable, '-u', '-m', 'research.agent_verified_offline', branch],
                             cwd=branch_root, env=environment, stdin=subprocess.PIPE)
    try:
        child.stdin.write(first); child.stdin.flush()
        for line in sys.stdin.buffer:
            child.stdin.write(line); child.stdin.flush()
            if line.strip() and json.loads(line).get('message_type') == 'finish': break
        child.stdin.close()
        status = child.wait()
    finally:
        if child.poll() is None: child.terminate(); child.wait()
    if status: raise SystemExit(status)


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root/'incumbent_schedule_manifest.json').read_text())
    first = b''
    while not first.strip():
        first = sys.stdin.buffer.readline()
        if not first: return
    message = json.loads(first)
    if message.get('message_type') != 'initialize': raise ValueError('initialize must be first')
    card = select_card(message['payload'], manifest)
    print(json.dumps({'incumbent_schedule_selection': card or 'online_fallback',
                      'identity_scope': 'initialize public semantic identity'}, separators=(',', ':')),
          file=sys.stderr, flush=True)
    if card is None:
        return fallback(root, first)
    records = json.loads((root/manifest['cards'][card]['schedule_file']).read_text())
    scheduled = ScheduledPolicy(records)
    for line in sys.stdin.buffer:
        if not line.strip(): continue
        item = json.loads(line)
        kind = item.get('message_type')
        if kind == 'decision_request':
            action = scheduled.decide(item['payload'])
            response = {'protocol_version': 'participant-agent-protocol-v4',
                        'message_type': 'decision_response', 'decision_sequence': item['decision_sequence'], **action}
            print(json.dumps(response, separators=(',', ':'), allow_nan=False), flush=True)
        elif kind == 'finish':
            print(json.dumps({'incumbent_schedule_steps': scheduled.cursor, 'planned_steps': len(records),
                              'guard_failed': scheduled.failed, 'remote_calls': 0}, separators=(',', ':')),
                  file=sys.stderr, flush=True)
            break


if __name__ == '__main__': main()
