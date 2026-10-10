#!/usr/bin/env python3
"""Offline checks for the one-mode observer-token caretaker handshake."""
import importlib.util
import json
import os
from pathlib import Path
from unittest import mock

SOURCE = (Path(__file__).parents[2] / 'packages' /
          'o4s_sophon4_observer_handshake' / 'authcheck.py')
SPEC = importlib.util.spec_from_file_location('observer_handshake', SOURCE)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def execute(env, replies):
    calls, logs = [], []

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return replies.pop(0)

    with mock.patch.object(MOD, '_request', side_effect=request), \
            mock.patch.object(MOD, 'log', side_effect=lambda event, **fields:
                              logs.append({'event': event, **fields})), \
            mock.patch.dict(os.environ, env, clear=True):
        MOD.run(1)
    return calls, logs


def test_observer_contact_success_enables_answer_and_status():
    replies = [
        {'probe': 'contact', 'status': 200, 'ok': True},
        {'probe': 'answer', 'status': 200, 'ok': True},
        {'probe': 'status', 'status': 200, 'ok': True},
    ]
    calls, logs = execute({'OBSERVER_RUN_TOKEN': 'observer-secret'}, replies)
    assert [call[0][0] for call in calls] == ['contact', 'answer', 'status']
    encoded = json.dumps(logs)
    assert 'observer-secret' not in encoded
    assert logs[-1]['credential_kind'] == 'observer'


def test_contact_rejection_stops_without_answer():
    calls, logs = execute(
        {'OBSERVER_RUN_TOKEN': 'observer-secret'},
        [{'probe': 'contact', 'status': 401, 'ok': False, 'error': 'unauthorized'}])
    assert len(calls) == 1
    assert logs[-1]['probes'][0]['status'] == 401


def test_public_test_and_missing_credential_make_no_request():
    for env, reason in [
        ({'SAC_LOCAL_RUNNER': '1', 'OBSERVER_RUN_TOKEN': 'observer-secret'},
         'local_runner'),
        ({}, None),
    ]:
        calls, logs = execute(env, [])
        assert calls == []
        if reason:
            assert logs[-1]['reason'] == reason
        else:
            assert logs[-1]['credential_kind'] == 'none'


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items())
             if name.startswith('test_') and callable(value)]
    for test in tests:
        test()
    print(f'{len(tests)} tests passed')
