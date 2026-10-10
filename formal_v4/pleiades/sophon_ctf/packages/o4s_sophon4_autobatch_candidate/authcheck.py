"""Disabled-by-default, bounded submission of independently verified CTF flags.

Enable only after this exact auth mode has been verified to credit the auto board.
No credentials are embedded, printed, hashed, persisted, or sent off BASE.
"""
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://vdiemcofukuxglqsmlyz.supabase.co/functions/v1/sophon'
MODES = {'body_sophon', 'body_observer', 'bearer_observer', 'query_observer',
         'body_bearer_observer', 'bearer_observer_site'}
ERRORS = {'closed', 'wrong_answer', 'locked', 'unauthorized', 'forbidden',
          'invalid_token', 'invalid_run_credential', 'rate_limited',
          'invalid_or_expired_capability', 'already_solved'}
PER_REQUEST_SECONDS = 4.0
BATCH_SECONDS = 90.0
PAUSE_SECONDS = 0.25


def log(event, **fields):
    print(json.dumps({'event': event, **fields}, separators=(',', ':')),
          file=sys.stderr, flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _load():
    here = Path(__file__).resolve().parent
    config = json.loads((here / 'autobatch_config.json').read_text())
    if not isinstance(config, dict) or config.get('enabled') is not True:
        return None, None
    if (config.get('auth_mode') not in MODES or config.get('verified_board') != 'auto'
            or not isinstance(config.get('verification_run_id'), str)
            or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',
                                config['verification_run_id'])):
        raise ValueError('Verification metadata missing')
    flags = json.loads((here / 'flags.json').read_text())
    if not isinstance(flags, list) or len(flags) != 21:
        raise ValueError('Unexpected flag count')
    numbers, values = [], []
    for item in flags:
        if (not isinstance(item, dict) or set(item) != {'no', 'flag'}
                or type(item['no']) is not int or not isinstance(item['flag'], str)
                or not re.fullmatch(r'SOPHON\{[A-Z0-9]{20}\}', item['flag'])):
            raise ValueError('Invalid flag list')
        numbers.append(item['no'])
        values.append(item['flag'])
    if numbers != [n for n in range(1, 23) if n != 4] or len(set(values)) != 21:
        raise ValueError('Flag list must exclude No4 and put No22 last')
    verified = config.get('verified_nos')
    if (not isinstance(verified, list) or not verified
            or any(type(no) is not int or no not in numbers for no in verified)
            or len(set(verified)) != len(verified)):
        raise ValueError('Confirmed auto flag numbers required')
    return config, flags


def _request(mode, token, flag, timeout):
    path, body, headers = '/desk/flag', {'flag': flag}, {'Content-Type': 'application/json'}
    if mode in ('body_sophon', 'body_observer', 'body_bearer_observer'):
        body['token'] = token
    if mode in ('bearer_observer', 'body_bearer_observer', 'bearer_observer_site'):
        headers['Authorization'] = 'Bearer ' + token
    if mode == 'query_observer':
        path += '?token=' + urllib.parse.quote(token, safe='')
    if mode == 'bearer_observer_site':
        headers['x-sophon-site'] = '1'
    request = urllib.request.Request(BASE + path, method='POST', headers=headers,
        data=json.dumps(body, separators=(',', ':')).encode())
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as reply:
            status, raw = reply.status, reply.read(8192)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(8192)
    except Exception:
        return {'status': None, 'error': 'network_error'}
    out = {'status': status}
    try:
        value = json.loads(raw)
    except Exception:
        return {**out, 'error': 'unreadable_response'}
    if not isinstance(value, dict):
        return {**out, 'error': 'unreadable_response'}
    # No raw body, response keys, unknown strings, exception messages or URLs.
    for key in ('ok', 'solved'):
        if type(value.get(key)) is bool:
            out[key] = value[key]
    if type(value.get('no')) is int and 1 <= value['no'] <= 22:
        out['no'] = value['no']
    if value.get('board') in ('auto', 'debug'):
        out['board'] = value['board']
    if 'error' in value:
        error = value['error']
        out['error'] = error if isinstance(error, str) and error in ERRORS else 'other'
    return out


def _bounded_post(mode, token, flag, seconds):
    done, result = threading.Event(), []

    def worker():
        try:
            result.append(_request(mode, token, flag, min(3.0, seconds)))
        except Exception:
            result.append({'status': None, 'error': 'request_error'})
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    if not done.wait(seconds):
        # Outcome is unknown. Stop the batch; never retry or start another worker.
        return {'status': None, 'error': 'hard_timeout'}
    return result[0]


def run(decision_sequence=None):
    try:
        _run(decision_sequence)
    except Exception:
        # Keep the observing agent alive without printing the exception or locals.
        log('autobatch_stop', reason='internal_error')


def _run(decision_sequence):
    if os.environ.get('SAC_LOCAL_RUNNER'):
        log('autobatch_skipped', reason='local_runner')
        return
    try:
        config, flags = _load()
    except Exception:
        log('autobatch_skipped', reason='invalid_config')
        return
    if config is None:
        log('autobatch_skipped', reason='disabled')
        return
    if type(decision_sequence) is not int or decision_sequence < 1:
        log('autobatch_skipped', reason='decision_barrier_missing')
        return
    verified = set(config['verified_nos'])
    flags = [item for item in flags if item['no'] not in verified]
    if not flags:
        log('autobatch_skipped', reason='all_verified', skipped_count=len(verified))
        return
    mode = config['auth_mode']
    variable = 'SOPHON_RUN_TOKEN' if mode == 'body_sophon' else 'OBSERVER_RUN_TOKEN'
    token = os.environ.get(variable, '')
    if not token:
        log('autobatch_skipped', reason='runtime_credential_absent', variable=variable)
        return
    start, attempted, solved = time.monotonic(), 0, 0
    log('autobatch_start', auth_mode=mode, count=len(flags), skipped_count=len(verified),
        decision_sequence=decision_sequence)
    stop = 'complete'
    for item in flags:
        left = start + BATCH_SECONDS - time.monotonic()
        if left <= 0:
            stop = 'batch_deadline'
            break
        out = _bounded_post(mode, token, item['flag'], min(PER_REQUEST_SECONDS, left))
        attempted += 1
        log('autobatch_item', requested_no=item['no'], **out)
        status, error = out.get('status'), out.get('error')
        if error == 'already_solved':
            # Do not infer team-wide auto state from a duplicate response. The
            # verified_nos configuration is the sole source of skip decisions.
            stop = 'already_solved_stop'
            break
        if (status is None or status == 429 or status in (401, 403, 404)
                or isinstance(status, int) and status >= 500
                or error in ('closed', 'unauthorized', 'forbidden', 'invalid_token',
                             'invalid_run_credential', 'invalid_or_expired_capability')
                or out.get('board') == 'debug'):
            stop = 'response_stop'
            break
        if status != 200 and not (status == 422 and error in ('wrong_answer', 'locked')):
            stop = 'unexpected_response'
            break
        if status == 200 and (out.get('solved') is not True or out.get('no') != item['no']):
            stop = 'unconfirmed_submission'
            break
        solved += int(status == 200 and out.get('solved') is True)
        if attempted < len(flags):
            time.sleep(min(PAUSE_SECONDS, max(0, start + BATCH_SECONDS - time.monotonic())))
    log('autobatch_done', attempted=attempted, solved=solved, reason=stop,
        elapsed_ms=round((time.monotonic() - start) * 1000))
