#!/usr/bin/env python3
"""Check the completed full-season run, then exercise early dive with a five-second budget.

Offline only. The tiny extra engine run observes once and skips the rest of the season.
"""
import contextlib
import csv
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
DESK = ROOT / 'work/sophon_desk'
PKG = ROOT / 'work/packages/o4s_sophon3_jupiter_full'
KIT = ROOT / 'hackathon-survey26/archive/starter_kit_v4'
sys.path[:0] = [str(PKG), str(KIT)]
from sophon_policy import Policy
from challenge.v4_workflow import V4Workflow, PROTOCOL_VERSION


def csv_rows(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def main():
    normal = DESK / 'validation/sophon3_jupiter_full'
    baseline = DESK / 'validation/sophon3_jupiter'
    wf = json.loads((normal / 'workflow_result.json').read_text())
    dec = csv_rows(normal / 'decisions.csv')
    old_dec = csv_rows(baseline / 'decisions.csv')
    assert wf['termination_reason'] == 'survey_complete'
    assert dec[:-1] == old_dec
    assert dec[-1]['action'] == 'wait' and dec[-1]['end_utc'] == '2026-11-30T08:15:00Z'
    assert (normal / 'observations.csv').read_bytes() == (baseline / 'observations.csv').read_bytes()
    actions = [json.loads(s) for s in (normal / 'actions.jsonl').read_text().splitlines()]
    assert actions[-1] == {'action': 'wait', 'until_utc': '2026-11-30T08:15:00Z'}
    assert not any(a['action'] == 'finish' for a in actions)
    result = {'normal': {'termination': wf['termination_reason'],
        'charged_seconds': wf['accounted_wallclock_seconds'], 'decision_requests': wf['decision_requests'],
        'prior_decisions_identical': True, 'observations_byte_identical': True,
        'last_decisions': dec[-5:], 'last_action': actions[-1]}}

    output = DESK / 'validation/sophon3_jupiter_full_budget'
    output.mkdir(exist_ok=True)
    state = {}
    calls = []
    def initialize(payload):
        state['policy'] = Policy(payload)
    def decide(message, deadline):
        snap = message['payload']
        action = state['policy'].decide(snap)
        calls.append({'now_utc': snap['now_utc'], 'remaining': snap['wallclock']['remaining_seconds'],
                      'action': action})
        return dict(protocol_version=PROTOCOL_VERSION, message_type='decision_response',
                    decision_sequence=message['decision_sequence'], **action)
    # Force the local network guard even if the launching shell carries unrelated credentials.
    with patch.dict(os.environ, {'SAC_LOCAL_RUNNER': '1'}), \
            (output / 'agent.log').open('w') as log, contextlib.redirect_stderr(log):
        started = time.monotonic()
        budget_wf = V4Workflow(DESK / 'local/sophon-local').run(
            decide, output, initialize=initialize, wallclock_seconds=5)
        state['policy'].summary()
        elapsed = time.monotonic() - started
    assert state['policy'].emergency
    assert budget_wf['termination_reason'] == 'survey_complete'
    assert len(calls) <= 3, calls
    assert calls[-1]['action'] == {'action': 'wait', 'until_utc': '2026-11-30T08:15:00Z'}
    assert sum(c['action']['action'] == 'observe' for c in calls) == 1
    assert not any(c['action']['action'] == 'finish' for c in calls)
    bdec = csv_rows(output / 'decisions.csv')
    assert bdec[-1]['end_utc'] == '2026-11-30T08:15:00Z'
    result['budget'] = {'termination': budget_wf['termination_reason'], 'budget_seconds': 5,
        'charged_seconds': budget_wf['accounted_wallclock_seconds'],
        'elapsed_seconds': elapsed, 'decision_requests': budget_wf['decision_requests'],
        'expanded_decision_rows': len(bdec), 'calls': calls}
    dest = DESK / 'validation/sophon3_jupiter_full_validation.json'
    dest.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
