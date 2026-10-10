#!/usr/bin/env python3
"""Offline tests for the disabled auto No.4 candidate; no network calls."""
import importlib.util
import json
import os
from pathlib import Path
from unittest import mock

SOURCE = (Path(__file__).parents[2] / 'packages' /
          'o4s_sophon4_auto_no4_candidate' / 'authcheck.py')
SPEC = importlib.util.spec_from_file_location('auto_no4_candidate', SOURCE)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
RUN_ID = '11111111-2222-3333-4444-555555555555'
CONFIG = {'enabled': True, 'auth_mode': 'body_observer',
          'verified_board': 'auto', 'verification_run_id': RUN_ID}
PASS = 'SOPHON{SW3A4SPNWKQ4DQ9UVS34}'


def execute(replies, config=CONFIG, sequence=1):
    calls, logs = [], []

    def request(mode, token, probe, path, body, **kwargs):
        calls.append((mode, token, probe, path, dict(body), dict(kwargs)))
        return replies.pop(0)

    with mock.patch.object(MOD, '_load_config', return_value=config), \
            mock.patch.object(MOD, '_request', side_effect=request), \
            mock.patch.object(MOD, 'log', side_effect=lambda event, **fields:
                              logs.append({'event': event, **fields})), \
            mock.patch.dict(os.environ, {'OBSERVER_RUN_TOKEN': 'runtime-secret'}, clear=True):
        MOD._run(sequence)
    return calls, logs


def test_success_is_immediate_and_redacted():
    replies = [({'probe': 'front_door', 'status': 200, 'ok': True}, None)]
    replies += [({'probe': 'bar', 'status': 200, 'ok': True,
                  'has_pass': False}, None) for _ in range(4)]
    replies += [({'probe': 'bar', 'status': 200, 'ok': True,
                  'has_pass': True}, PASS)]
    replies += [({'probe': 'immediate_pass', 'status': 200, 'ok': True,
                  'solved': True, 'no': 4, 'board': 'auto'}, None)]
    calls, logs = execute(replies)
    assert [call[3] for call in calls] == ['/desk/door'] + ['/desk/bar'] * 5 + ['/desk/flag']
    assert not any(path.startswith('/desk/door/') for *_, path, body, kwargs in calls)
    assert calls[-1][4] == {'flag': PASS}
    assert calls[-1][5] == {'secret': PASS, 'capture_issued': True}
    encoded = json.dumps(logs)
    assert PASS not in encoded and 'runtime-secret' not in encoded
    assert logs[-1]['solved_no'] == 4


def test_no_pass_stops_at_bound():
    replies = [({'probe': 'front_door', 'status': 200, 'ok': True}, None)]
    replies += [({'probe': 'bar', 'status': 200, 'ok': True,
                  'has_pass': False}, None) for _ in range(MOD.BAR_LIMIT)]
    calls, logs = execute(replies)
    assert len(calls) == 1 + MOD.BAR_LIMIT
    assert logs[-1]['reason'] == 'no_pass'


def test_debug_or_bad_door_never_reaches_bar():
    for reply in [
        ({'probe': 'front_door', 'status': 200, 'ok': True, 'board': 'debug'}, None),
        ({'probe': 'front_door', 'status': 422, 'ok': False,
          'error': 'wrong_answer'}, None),
    ]:
        calls, logs = execute([reply])
        assert len(calls) == 1 and logs[-1]['reason'] == 'front_door_stop'


def test_disabled_does_not_read_token_or_request():
    calls = []
    with mock.patch.object(MOD, '_load_config', return_value=None), \
            mock.patch.object(MOD, '_request', side_effect=lambda *a, **k: calls.append(a)), \
            mock.patch.object(MOD, 'log'), \
            mock.patch.dict(os.environ, {}, clear=True):
        MOD._run(1)
    assert calls == []


def test_auth_shapes_are_fixed():
    token = 'do-not-log'
    path, headers, body = MOD._auth('body_observer', token, '/desk/bar', {'say': 'x'})
    assert path == '/desk/bar' and body['token'] == token and 'Authorization' not in headers
    path, headers, body = MOD._auth('query_observer', token, '/desk/bar', {'say': 'x'})
    assert path == '/desk/bar?token=do-not-log' and 'token' not in body
    path, headers, body = MOD._auth('bearer_observer', token, '/desk/bar', {'say': 'x'})
    assert headers['Authorization'] == 'Bearer ' + token and 'token' not in body


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items())
             if name.startswith('test_') and callable(value)]
    for test in tests:
        test()
    print(f'{len(tests)} tests passed')
