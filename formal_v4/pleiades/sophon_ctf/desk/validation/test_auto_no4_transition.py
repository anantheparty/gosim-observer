#!/usr/bin/env python3
"""Offline tests for the disabled fresh-auto No.4 transition package."""
import importlib.util
import json
import os
from pathlib import Path
from unittest import mock

SOURCE = (Path(__file__).parents[2] / 'packages' /
          'o4s_sophon4_auto_no4_transition' / 'authcheck.py')
SPEC = importlib.util.spec_from_file_location('auto_no4_transition', SOURCE)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
RUN_ID = '11111111-2222-3333-4444-555555555555'
CONFIG = {'enabled': True, 'auth_mode': 'sophon_token',
          'verified_board': 'auto', 'verification_run_id': RUN_ID}
DECOY = 'SOPHON{SW3A4SPNWKQ4DQ9UVS34}'
GENUINE = 'SOPHON{B4S3ZRGD7K3MWEAFZAUP}'
NO4 = 'SOPHON{CCCCCCCCCCCCCCCCCCCC}'


def accepted(probe, **fields):
    return {'probe': probe, 'status': 200, 'ok': True, **fields}


def execute(replies, env=None, config=CONFIG):
    calls, logs = [], []

    def request(token, probe, method, path, body=None):
        calls.append((token, probe, method, path, dict(body or {})))
        return replies.pop(0)

    with mock.patch.object(MOD, '_load_config', return_value=config), \
            mock.patch.object(MOD, '_request', side_effect=request), \
            mock.patch.object(MOD, 'log', side_effect=lambda event, **fields:
                              logs.append({'event': event, **fields})), \
            mock.patch.dict(os.environ, ({'SOPHON_RUN_TOKEN': 'runtime-secret'}
                                         if env is None else env),
                            clear=True):
        MOD._run(1)
    return calls, logs


def test_full_transition_is_bounded_and_logs_no_secrets():
    quotes = ('"As sure as room 237 is locked, the first word is MIRROR." '
              '"As sure as room 237 is locked, the second word is TOPIARY." '
              '"I\'d swear it on 237: word number 3 is ELEVATOR." '
              '"Room 237 never lies, and neither do I about this - '
              'the fourth one is BASEMENT."')
    replies = [
        (accepted('contact'), {}),
        (accepted('answer'), {}),
        (accepted('auto_root_before', board='auto'), {'board': 'auto'}),
        (accepted('front_door'), {'flag': 'SOPHON{AAAAAAAAAAAAAAAAAAAA}'}),
        (accepted('bar', has_pass=True), {'johnny': quotes, 'pass': DECOY}),
        ({'probe': 'decoy_submit', 'status': 422, 'ok': False, 'error': 'fooled'},
         {'error': 'fooled'}),
        (accepted('four_word_door'), {'flag': 'SOPHON{AAAAAAAAAAAAAAAAAAAA}'}),
        (accepted('door_issued_submit', solved=True, no=3), {'solved': True, 'no': 3}),
        (accepted('house_line'), {'flag': 'SOPHON{BBBBBBBBBBBBBBBBBBBB}'}),
        (accepted('house_issued_submit', solved=True, no=9), {'solved': True, 'no': 9}),
        (accepted('house_enter'), {'room': 'r0'}),
        (accepted('house_room'), {'doors': {'stairs down': 'r1', 'left': 'r2'}}),
        (accepted('house_room'), {'doors': {'back': 'r0'}}),
        (accepted('house_room', has_flag=True),
         {'flag': GENUINE, 'doors': {'the far door': 'r0'}}),
    ]
    replies += [
        (accepted('genuine_submit', solved=True, no=10), {'solved': True, 'no': 10}),
        (accepted('auto_root_after', board='auto', found_numbers=[10]),
         {'board': 'auto', 'found': [{'no': 10}]}),
    ]
    calls, logs = execute(replies)
    assert not replies
    assert calls[0][1:4] == ('contact', 'POST', '/contact-johnny')
    assert calls[4][1:4] == ('bar', 'POST', '/desk/bar')
    assert calls[5][4] == {'flag': DECOY}
    assert calls[-2][4] == {'flag': GENUINE}
    assert calls[-1][1:4] == ('auto_root_after', 'GET', '/desk')
    room_calls = [call for call in calls if call[1] == 'house_room']
    assert [call[3].rsplit('/', 1)[-1] for call in room_calls] == ['r0', 'r1', 'r2']
    encoded = json.dumps(logs)
    assert 'runtime-secret' not in encoded
    assert DECOY not in encoded and GENUINE not in encoded and NO4 not in encoded
    assert not any('r0' in str(row) or 'r10' in str(row) for row in logs)
    assert logs[-1]['reason'] == 'transition_complete'
    assert logs[-1]['house_visits'] == 3


def test_house_crawl_is_bounded_when_no_pass_exists():
    quotes = ('"As sure as room 237 is locked, the first word is MIRROR." '
              '"As sure as room 237 is locked, the second word is TOPIARY." '
              '"I\'d swear it on 237: word number 3 is ELEVATOR." '
              '"Room 237 never lies, and neither do I about this - '
              'the fourth one is BASEMENT."')
    prefix = [
        (accepted('contact'), {}),
        (accepted('answer'), {}),
        (accepted('auto_root_before', board='auto'), {'board': 'auto'}),
        (accepted('front_door'), {}),
        (accepted('bar', has_pass=True), {'johnny': quotes, 'pass': DECOY}),
        ({'probe': 'decoy_submit', 'status': 422, 'ok': False, 'error': 'fooled'},
         {'error': 'fooled'}),
        (accepted('four_word_door'), {}),
        (accepted('house_line'), {}),
        (accepted('house_enter'), {'room': 'r0'}),
    ]
    old_limit = MOD.HOUSE_VISIT_LIMIT
    MOD.HOUSE_VISIT_LIMIT = 3
    try:
        replies = prefix + [
            (accepted('house_room'), {'doors': {'ahead': 'r1'}}),
            (accepted('house_room'), {'doors': {'ahead': 'r2'}}),
            (accepted('house_room'), {'doors': {'ahead': 'r3'}}),
        ]
        calls, logs = execute(replies)
    finally:
        MOD.HOUSE_VISIT_LIMIT = old_limit
    assert not replies
    assert logs[-1]['reason'] == 'genuine_pass_missing'
    assert logs[-1]['house_visits'] == 3
    assert logs[-1]['frontier_remaining'] == 1
    assert len([call for call in calls if call[1] == 'house_room']) == 3


def test_no4_issued_by_door_is_confirmed_and_logged():
    quotes = ('"As sure as room 237 is locked, the first word is MIRROR." '
              '"As sure as room 237 is locked, the second word is TOPIARY." '
              '"I\'d swear it on 237: word number 3 is ELEVATOR." '
              '"Room 237 never lies, and neither do I about this - '
              'the fourth one is BASEMENT."')
    replies = [
        (accepted('contact'), {}),
        (accepted('answer'), {}),
        (accepted('auto_root_before', board='auto'), {'board': 'auto'}),
        (accepted('front_door'), {}),
        (accepted('bar', has_pass=True), {'johnny': quotes, 'pass': DECOY}),
        ({'probe': 'decoy_submit', 'status': 422, 'ok': False, 'error': 'fooled'},
         {'error': 'fooled'}),
        (accepted('four_word_door', has_flag=True), {'flag': NO4}),
        (accepted('door_issued_submit', solved=True, no=4),
         {'solved': True, 'no': 4}),
    ]
    calls, logs = execute(replies)
    assert not replies
    assert calls[-1][4] == {'flag': NO4}
    assert logs[-2] == {'event': 'auto_no4_issued', 'issued_flag': NO4}
    assert logs[-1]['reason'] == 'door_transition_solved_no4'


def test_disabled_and_missing_credential_make_no_request():
    for config, env, reason in [
        (None, {'SOPHON_RUN_TOKEN': 'runtime-secret'}, 'disabled'),
        (CONFIG, {}, 'sophon_credential_absent'),
    ]:
        calls, logs = execute([], env=env, config=config)
        assert calls == [] and logs[-1]['reason'] == reason


def test_237_parser_rejects_unbacked_claims():
    parsed = {'johnny': ('"Word 1 is BOILER, kid. Trust me." '
                         '"The first word? CHAPEL. I\'d bet room 214 on it." '
                         '"As sure as room 237 is locked, the first word is MIRROR." '
                         '"I\'d swear it on 237: word number 2 is TOPIARY."')}
    words = {}
    MOD._remember_237(words, parsed)
    assert words == {1: 'MIRROR', 2: 'TOPIARY'}


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items())
             if name.startswith('test_') and callable(value)]
    for test in tests:
        test()
    print(f'{len(tests)} tests passed')
