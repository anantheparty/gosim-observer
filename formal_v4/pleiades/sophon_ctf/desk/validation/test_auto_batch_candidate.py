"""Offline tests only: all network entry points are mocked; no engine or credentials."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[2] / 'packages' / 'o4s_sophon4_autobatch_candidate'
spec = importlib.util.spec_from_file_location('candidate_authcheck', PACKAGE / 'authcheck.py')
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)
FLAGS = [{'no': n, 'flag': 'SOPHON{' + f'{n:020d}' + '}'} for n in range(1, 23) if n != 4]
CONFIG = {'enabled': True, 'auth_mode': 'body_observer', 'verified_board': 'auto',
          'verification_run_id': '00000000-0000-0000-0000-000000000000', 'verified_nos': [1]}
FAKE = 'dummy-only-for-offline-test'


class Reply:
    status = 200
    def __init__(self, body):
        self.body = json.dumps(body).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, size): return self.body[:size]


class BatchTests(unittest.TestCase):
    def execute(self, response, **kwargs):
        stream, calls = io.StringIO(), []
        def post(mode, token, flag, seconds):
            calls.append(flag)
            if callable(response): return response(len(calls))
            return response
        env = {'OBSERVER_RUN_TOKEN': FAKE}
        env.update(kwargs.get('env', {}))
        config = {**CONFIG, **kwargs.get('config', {})}
        with patch.object(batch.os, 'environ', env), patch.object(batch, '_load', return_value=(config, FLAGS)), \
             patch.object(batch, '_bounded_post', side_effect=post), patch.object(batch.time, 'sleep'), \
             contextlib.redirect_stderr(stream):
            batch.run(kwargs.get('sequence', 1))
        self.assertNotIn(FAKE, stream.getvalue())
        for item in FLAGS: self.assertNotIn(item['flag'], stream.getvalue())
        return calls, [json.loads(line) for line in stream.getvalue().splitlines()]

    def test_default_disabled_does_not_read_token_or_call_network(self):
        stream = io.StringIO()
        class Environment(dict):
            def get(self, key, default=None):
                if key.endswith('TOKEN'): raise AssertionError('Token read while disabled')
                return super().get(key, default)
        with patch.object(batch.os, 'environ', Environment()), \
             patch.object(batch, '_bounded_post', side_effect=AssertionError('Network')), \
             contextlib.redirect_stderr(stream):
            batch.run(1)
        self.assertEqual(json.loads(stream.getvalue())['reason'], 'disabled')

    def test_all_success_preserves_order_and_no22_last(self):
        remaining = FLAGS[1:]
        calls, logs = self.execute(lambda i: {'status': 200, 'solved': True, 'no': remaining[i-1]['no'], 'board': 'auto'})
        self.assertEqual(calls, [f['flag'] for f in remaining])
        self.assertEqual(logs[0]['skipped_count'], 1)
        self.assertEqual(logs[0]['count'], 20)
        self.assertEqual(logs[-1]['solved'], 20)
        self.assertEqual(logs[-1]['reason'], 'complete')
        self.assertNotIn('verified_nos', json.dumps(logs))
        self.assertNotIn(1, [r['requested_no'] for r in logs if 'requested_no' in r])

    def test_required_and_auth_stops(self):
        for response in ({'status': 429}, {'status': 404, 'error': 'closed'},
                         {'status': 200, 'error': 'closed'}, {'status': 401},
                         {'status': 403}, {'status': 500}, {'status': None, 'error': 'hard_timeout'},
                         {'status': 200, 'board': 'debug'}, {'status': 200, 'solved': False},
                         {'status': 200, 'solved': True, 'no': 22}):
            with self.subTest(response=response):
                calls, _ = self.execute(response)
                self.assertEqual(len(calls), 1)

    def test_known_rejection_is_not_retried(self):
        calls, logs = self.execute({'status': 422, 'error': 'wrong_answer'})
        self.assertEqual(len(calls), 20)
        self.assertEqual(len(set(calls)), 20)
        self.assertEqual(logs[-1]['solved'], 0)

    def test_missing_decision_barrier_skips(self):
        calls, logs = self.execute({'status': 200}, sequence=None)
        self.assertFalse(calls)
        self.assertEqual(logs[-1]['reason'], 'decision_barrier_missing')

    def test_local_skips(self):
        calls, logs = self.execute({'status': 200}, env={'SAC_LOCAL_RUNNER': '1'})
        self.assertFalse(calls)
        self.assertEqual(logs[-1]['reason'], 'local_runner')

    def test_total_deadline_skips_network(self):
        with patch.object(batch, 'BATCH_SECONDS', 0):
            calls, logs = self.execute({'status': 200})
        self.assertFalse(calls)
        self.assertEqual(logs[-1]['reason'], 'batch_deadline')

    def test_hard_deadline_stops_waiting(self):
        gate = threading.Event()
        def delayed(*args):
            gate.wait(1)
            return {'status': 200}
        with patch.object(batch, '_request', side_effect=delayed):
            out = batch._bounded_post('body_observer', FAKE, FLAGS[0]['flag'], 0.01)
            gate.set()
        self.assertEqual(out['error'], 'hard_timeout')

    def test_response_reflections_are_never_emitted(self):
        body = {'ok': True, 'solved': True, 'no': 1, 'board': FAKE, 'error': FAKE,
                FAKE: FAKE, 'johnny': FAKE, 'url': FAKE, 'token': FAKE}
        class Opener:
            def open(self, *args, **kwargs): return Reply(body)
        with patch.object(batch.urllib.request, 'build_opener', return_value=Opener()):
            out = batch._request('body_observer', FAKE, FLAGS[0]['flag'], 1)
        self.assertNotIn(FAKE, json.dumps(out))
        self.assertEqual(out, {'status': 200, 'ok': True, 'solved': True, 'no': 1, 'error': 'other'})

    def test_transport_modes_use_fixed_route_without_fallback(self):
        for mode in batch.MODES:
            captured = []
            class Opener:
                def open(self, request, **kwargs):
                    captured.append(request)
                    return Reply({'solved': True, 'no': 1})
            with self.subTest(mode=mode), patch.object(batch.urllib.request, 'build_opener', return_value=Opener()):
                batch._request(mode, FAKE, FLAGS[0]['flag'], 1)
            self.assertEqual(len(captured), 1)
            request = captured[0]
            self.assertEqual(request.full_url.split('?')[0], batch.BASE + '/desk/flag')
            body = json.loads(request.data)
            self.assertEqual('token' in body, mode in ('body_sophon', 'body_observer', 'body_bearer_observer'))
            self.assertEqual(request.get_header('Authorization') is not None,
                             mode in ('bearer_observer', 'body_bearer_observer', 'bearer_observer_site'))
            self.assertEqual('?token=' in request.full_url, mode == 'query_observer')

    def test_static_list_matches_success_provenance(self):
        records = json.loads((PACKAGE / 'flags.json').read_text())
        self.assertEqual([x['no'] for x in records], [x['no'] for x in FLAGS])
        self.assertEqual(len({x['flag'] for x in records}), 21)

    def test_multiple_confirmed_numbers_skip_without_per_item_log(self):
        skipped = [1, 17, 18]
        remaining = [f for f in FLAGS if f['no'] not in skipped]
        calls, logs = self.execute(
            lambda i: {'status': 200, 'solved': True, 'no': remaining[i-1]['no']},
            config={'verified_nos': skipped})
        self.assertEqual(calls, [f['flag'] for f in remaining])
        self.assertEqual(logs[0]['skipped_count'], 3)
        self.assertEqual(logs[0]['count'], 18)
        self.assertTrue(set(skipped).isdisjoint(r['requested_no'] for r in logs if 'requested_no' in r))

    def test_all_verified_no_network(self):
        calls, logs = self.execute({'status': 200}, config={'verified_nos': [f['no'] for f in FLAGS]})
        self.assertFalse(calls)
        self.assertEqual(logs, [{'event': 'autobatch_skipped', 'reason': 'all_verified', 'skipped_count': 21}])

    def test_already_solved_stops_even_when_auto_and_no_match(self):
        for status in (200, 409, 422):
            with self.subTest(status=status):
                calls, logs = self.execute({'status': status, 'error': 'already_solved',
                                            'no': 2, 'board': 'auto', 'solved': True})
                self.assertEqual(len(calls), 1)
                self.assertEqual(logs[-1]['reason'], 'already_solved_stop')
                self.assertEqual(logs[-1]['solved'], 0)

    def test_enable_requires_auto_verification_metadata(self):
        with patch.object(batch.Path, 'read_text', side_effect=[json.dumps(CONFIG), json.dumps(FLAGS)]):
            config, flags = batch._load()
        self.assertEqual(config, CONFIG)
        self.assertEqual(flags, FLAGS)
        for change in ({'auth_mode': None}, {'verified_board': 'debug'}, {'verification_run_id': None}):
            with self.subTest(change=change), patch.object(batch.Path, 'read_text', return_value=json.dumps({**CONFIG, **change})):
                with self.assertRaises(ValueError): batch._load()

    def test_enabled_config_requires_nonempty_valid_verified_numbers(self):
        for value in (None, [], [4], [True], ['1'], [1, 1], [23], [0], '1', {'no': 1}):
            with self.subTest(value=value), patch.object(batch.Path, 'read_text',
                    side_effect=[json.dumps({**CONFIG, 'verified_nos': value}), json.dumps(FLAGS)]):
                with self.assertRaises(ValueError): batch._load()

    def test_fake_number_or_bad_order_rejected(self):
        for flags in (FLAGS[:-1], list(reversed(FLAGS)), [{'no': 4, 'flag': FLAGS[0]['flag']}] + FLAGS[1:]):
            with self.subTest(numbers=[x['no'] for x in flags]), \
                 patch.object(batch.Path, 'read_text', side_effect=[json.dumps(CONFIG), json.dumps(flags)]):
                with self.assertRaises(ValueError): batch._load()


if __name__ == '__main__':
    unittest.main()
