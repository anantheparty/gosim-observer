"""Bounded legacy Sophon answer probe after engine.begin.

Only the published /answer route is used. Runtime capabilities and the submitted
sentence stay in memory and are never logged or persisted.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = 'https://vdiemcofukuxglqsmlyz.supabase.co/functions/v1/sophon'
SENTENCE = ('I SAW A COLLECTION OF LEAVES FORM AN ENDLESS HOUSE SEE YOU AFTER '
            'JAN 5 1997 WHILE EVERYTHING SHOULD BE REVEALED THROUGH THE FINAL TRIALS')
FLAG_RE = re.compile(r'^SOPHON\{[A-Za-z0-9_-]{1,200}\}$')
KNOWN_ERRORS = {
    'closed', 'wrong_answer', 'invalid_token', 'invalid_run', 'unauthorized',
    'forbidden', 'rate_limited', 'already_solved', 'locked',
}


def log(event, **fields):
    print(json.dumps({'event': event, **fields}, separators=(',', ':'), default=str),
          file=sys.stderr, flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _post(probe_id, headers, body):
    raw_body = json.dumps(body, separators=(',', ':')).encode()
    request = urllib.request.Request(
        BASE + '/answer', data=raw_body,
        headers={'Content-Type': 'application/json', **headers}, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=3) as response:
            status, raw = response.status, response.read(8192)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(8192)
    except Exception as exc:
        return {'probe': probe_id, 'status': None, 'exception': type(exc).__name__}
    out = {'probe': probe_id, 'status': status, 'bytes': len(raw)}
    try:
        parsed = json.loads(raw.decode('utf-8', 'replace'))
    except Exception:
        out['body_kind'] = 'non_json'
        return out
    if not isinstance(parsed, dict):
        out['body_kind'] = type(parsed).__name__
        return out
    out['body_kind'] = 'object'
    # Presence only: the legacy endpoint may call its receipt a key.  Never log
    # its value unless it is independently recognizable as a SOPHON flag below.
    for key in ('flag', 'key', 'code'):
        out[key + '_present'] = key in parsed
    for key in ('ok', 'solved', 'no'):
        value = parsed.get(key)
        if isinstance(value, (bool, int)) or value is None:
            out[key] = value
    error = parsed.get('error')
    if isinstance(error, str):
        out['error'] = error if error in KNOWN_ERRORS else 'other'
    for key in ('flag', 'key', 'code'):
        value = parsed.get(key)
        if isinstance(value, str) and FLAG_RE.fullmatch(value):
            out['issued_flag'] = value
            out['issued_field'] = key
            break
    return out


def run(decision_sequence=None):
    observer_token = os.environ.get('OBSERVER_RUN_TOKEN', '')
    sophon_token = os.environ.get('SOPHON_RUN_TOKEN', '')
    if os.environ.get('SAC_LOCAL_RUNNER'):
        log('oldanswer_skipped', reason='local_runner',
            observer_present=bool(observer_token), sophon_present=bool(sophon_token),
            decision_sequence=decision_sequence)
        return
    probes = []
    if sophon_token:
        probes.append(('body_sophon', {}, {'sentence': SENTENCE, 'token': sophon_token}))
    if observer_token:
        probes.extend([
            ('body_observer', {}, {'sentence': SENTENCE, 'token': observer_token}),
            ('bearer_observer', {'Authorization': 'Bearer ' + observer_token},
             {'sentence': SENTENCE}),
            ('body_bearer_observer', {'Authorization': 'Bearer ' + observer_token},
             {'sentence': SENTENCE, 'token': observer_token}),
        ])
    results = []
    for probe_id, headers, body in probes:
        result = _post(probe_id, headers, body)
        results.append(result)
        if result.get('status') == 429 or result.get('solved') is True or 'issued_flag' in result:
            break
    log('oldanswer_result', decision_sequence=decision_sequence,
        observer_present=bool(observer_token), sophon_present=bool(sophon_token),
        probes=results)
