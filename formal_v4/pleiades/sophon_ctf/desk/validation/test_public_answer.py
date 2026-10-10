#!/usr/bin/env python3
"""Offline checks for the public-test-capable caretaker contract package."""
import importlib.util
import json
import os
from pathlib import Path
from unittest import mock

SOURCE = (Path(__file__).parents[2] / 'packages' /
          'o4s_sophon4_public_answer' / 'authcheck.py')
SPEC = importlib.util.spec_from_file_location('public_answer', SOURCE)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def execute(env):
    calls, logs = [], []

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return {'probe': args[0], 'status': 200, 'ok': True}

    with mock.patch.object(MOD, '_request', side_effect=request), \
            mock.patch.object(MOD, 'log', side_effect=lambda event, **fields:
                              logs.append({'event': event, **fields})), \
            mock.patch.dict(os.environ, env, clear=True):
        MOD.run(1)
    return calls, logs


def test_public_test_with_s_uses_exact_three_step_contract():
    calls, logs = execute({'SAC_LOCAL_RUNNER': '1',
                           'SOPHON_RUN_TOKEN': 'runtime-secret',
                           'OBSERVER_RUN_TOKEN': 'observer-secret'})
    assert [call[0][0] for call in calls] == ['contact', 'answer', 'status']
    encoded = json.dumps(logs)
    assert 'runtime-secret' not in encoded and 'observer-secret' not in encoded
    assert logs[-1]['public_test'] is True and logs[-1]['sophon_present'] is True


def test_any_environment_without_s_makes_no_request():
    for env in ({'SAC_LOCAL_RUNNER': '1', 'OBSERVER_RUN_TOKEN': 'observer-secret'},
                {'OBSERVER_RUN_TOKEN': 'observer-secret'}):
        calls, logs = execute(env)
        assert calls == []
        assert logs[-1]['sophon_present'] is False


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items())
             if name.startswith('test_') and callable(value)]
    for test in tests:
        test()
    print(f'{len(tests)} tests passed')
