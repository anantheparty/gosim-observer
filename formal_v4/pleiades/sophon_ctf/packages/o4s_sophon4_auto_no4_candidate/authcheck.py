"""Disabled-by-default auto-board experiment for the bar's one-time pass.

Enable only after one exact authentication mode has been proved to write to the
auto board. The dynamic pass and runtime capability remain in memory and are
never printed, hashed, persisted, or sent anywhere except the fixed Sophon host.
"""
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://vdiemcofukuxglqsmlyz.supabase.co/functions/v1/sophon'
MODES = {'body_sophon', 'body_observer', 'query_observer', 'bearer_observer',
         'body_bearer_observer', 'bearer_observer_site'}
KNOWN_ERRORS = {'closed', 'wrong_answer', 'locked', 'unauthorized', 'forbidden',
                'invalid_token', 'invalid_run', 'invalid_run_credential',
                'invalid_or_expired_capability', 'rate_limited', 'already_solved'}
FLAG_RE = re.compile(r'^SOPHON\{[A-Z0-9]{20}\}$')
BAR_LIMIT = 12


def log(event, **fields):
    print(json.dumps({'event': event, **fields}, separators=(',', ':')),
          file=sys.stderr, flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _load_config():
    value = json.loads((Path(__file__).resolve().parent / 'auto_no4_config.json').read_text())
    if not isinstance(value, dict) or value.get('enabled') is not True:
        return None
    if (value.get('auth_mode') not in MODES or value.get('verified_board') != 'auto'
            or not isinstance(value.get('verification_run_id'), str)
            or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',
                                value['verification_run_id'])):
        raise ValueError('verification metadata missing')
    return value


def _auth(mode, token, path, body):
    headers = {'Content-Type': 'application/json'}
    body = dict(body)
    if mode in ('body_sophon', 'body_observer', 'body_bearer_observer'):
        body['token'] = token
    if mode in ('bearer_observer', 'body_bearer_observer', 'bearer_observer_site'):
        headers['Authorization'] = 'Bearer ' + token
    if mode == 'query_observer':
        path += ('&' if '?' in path else '?') + 'token=' + urllib.parse.quote(token, safe='')
    if mode == 'bearer_observer_site':
        headers['x-sophon-site'] = '1'
    return path, headers, body


def _request(mode, token, probe, path, body, secret=None, capture_issued=False):
    path, headers, body = _auth(mode, token, path, body)
    req = urllib.request.Request(
        BASE + path, method='POST', headers=headers,
        data=json.dumps(body, separators=(',', ':')).encode())
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=3) as response:
            status, raw = response.status, response.read(8192)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(8192)
    except Exception:
        return {'probe': probe, 'status': None, 'error': 'network_error'}, None
    out = {'probe': probe, 'status': status}
    try:
        parsed = json.loads(raw.decode('utf-8', 'replace'))
    except Exception:
        return {**out, 'error': 'unreadable_response'}, None
    if not isinstance(parsed, dict):
        return {**out, 'error': 'unreadable_response'}, None
    for key in ('ok', 'solved'):
        if type(parsed.get(key)) is bool:
            out[key] = parsed[key]
    if type(parsed.get('no')) is int and 1 <= parsed['no'] <= 22:
        out['no'] = parsed['no']
    if parsed.get('board') in ('auto', 'debug'):
        out['board'] = parsed['board']
    error = parsed.get('error')
    if isinstance(error, str):
        out['error'] = error if error in KNOWN_ERRORS else 'other'
    dynamic_pass = parsed.get('pass')
    if not isinstance(dynamic_pass, str) or not FLAG_RE.fullmatch(dynamic_pass):
        dynamic_pass = None
    out['has_pass'] = dynamic_pass is not None
    if capture_issued:
        for field in ('flag', 'code', 'key', 'receipt'):
            value = parsed.get(field)
            if isinstance(value, str) and FLAG_RE.fullmatch(value) and value != secret:
                out['issued_flag'] = value
                out['issued_field'] = field
                break
    return out, dynamic_pass


def run(decision_sequence=None):
    try:
        _run(decision_sequence)
    except Exception:
        log('auto_no4_stop', reason='internal_error')


def _run(decision_sequence):
    if os.environ.get('SAC_LOCAL_RUNNER'):
        log('auto_no4_skipped', reason='local_runner')
        return
    try:
        config = _load_config()
    except Exception:
        log('auto_no4_skipped', reason='invalid_config')
        return
    if config is None:
        log('auto_no4_skipped', reason='disabled')
        return
    if type(decision_sequence) is not int or decision_sequence < 1:
        log('auto_no4_skipped', reason='decision_barrier_missing')
        return
    mode = config['auth_mode']
    variable = 'SOPHON_RUN_TOKEN' if mode == 'body_sophon' else 'OBSERVER_RUN_TOKEN'
    token = os.environ.get(variable, '')
    if not token:
        log('auto_no4_skipped', reason='runtime_credential_absent', variable=variable)
        return

    started = time.monotonic()
    door, _ = _request(mode, token, 'front_door', '/desk/door',
                       {'say': 'THE SHINING'})
    log('auto_no4_step', **door)
    if (door.get('status') != 200 or door.get('ok') is not True
            or door.get('board') == 'debug'):
        log('auto_no4_done', reason='front_door_stop', bar_calls=0,
            elapsed_ms=round((time.monotonic() - started) * 1000))
        return

    dynamic_pass = None
    bar_calls = 0
    for index in range(1, BAR_LIMIT + 1):
        result, dynamic_pass = _request(
            mode, token, 'bar', '/desk/bar',
            {'say': 'What is the first word, Lloyd?'})
        bar_calls = index
        log('auto_no4_step', attempt=index, **result)
        if result.get('board') == 'debug' or result.get('status') == 429:
            dynamic_pass = None
            break
        if result.get('status') != 200 or result.get('ok') is not True:
            dynamic_pass = None
            break
        if dynamic_pass is not None:
            break
    if dynamic_pass is None:
        log('auto_no4_done', reason='no_pass', bar_calls=bar_calls,
            elapsed_ms=round((time.monotonic() - started) * 1000))
        return

    result, _ = _request(mode, token, 'immediate_pass', '/desk/flag',
                         {'flag': dynamic_pass}, secret=dynamic_pass,
                         capture_issued=True)
    log('auto_no4_step', **result)
    log('auto_no4_done', reason='submitted_once', bar_calls=bar_calls,
        solved_no=result.get('no') if result.get('solved') is True else None,
        elapsed_ms=round((time.monotonic() - started) * 1000))
