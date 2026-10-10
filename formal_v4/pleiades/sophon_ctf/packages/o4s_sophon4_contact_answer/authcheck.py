"""Exercise the published Sophon caretaker contract inside one evaluation.

The 2026-10-07 public guide explicitly promises SOPHON_RUN_TOKEN at runtime and
publishes the contact, answer, and status routes. Secret values and request
headers stay in memory; diagnostics contain only presence, status, response
field names, short redacted prose, and genuine SOPHON flags.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://vdiemcofukuxglqsmlyz.supabase.co/functions/v1/sophon'
SENTENCE = ('I SAW A COLLECTION OF LEAVES FORM AN ENDLESS HOUSE SEE YOU AFTER '
            'JAN 5 1997 WHILE EVERYTHING SHOULD BE REVEALED THROUGH THE FINAL TRIALS')
FLAG_RE = re.compile(r'^SOPHON\{[A-Za-z0-9_-]{1,200}\}$')


def log(event, **fields):
    print(json.dumps({'event': event, **fields}, separators=(',', ':'), default=str),
          file=sys.stderr, flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _safe_text(value, secret):
    if not isinstance(value, str):
        return None
    if secret:
        value = value.replace(secret, '[REDACTED]')
    value = value.replace(SENTENCE, '[SUBMITTED SENTENCE]')
    return value[:1600]


def _summarize(parsed, secret):
    if not isinstance(parsed, dict):
        return {'body_kind': type(parsed).__name__}
    out = {'body_kind': 'object', 'keys': sorted(str(k) for k in parsed)[:80]}
    for key in ('ok', 'solved', 'no'):
        value = parsed.get(key)
        if isinstance(value, (bool, int, float)) or value is None:
            out[key] = value
    board = parsed.get('board')
    if isinstance(board, str):
        out['board'] = _safe_text(board, secret)
    for key in ('found', 'pending'):
        value = parsed.get(key)
        if isinstance(value, list):
            out[key + '_count'] = len(value)
    for key in ('error', 'message', 'johnny', 'next', 'answer', 'usage', 'door'):
        value = _safe_text(parsed.get(key), secret)
        if value is not None:
            out[key] = value
    for key in ('flag', 'key', 'code'):
        value = parsed.get(key)
        out[key + '_present'] = key in parsed
        if isinstance(value, str) and FLAG_RE.fullmatch(value):
            out['issued_flag'] = value
            out['issued_field'] = key
            break
    return out


def _request(probe, method, path, body, secret):
    data = None if body is None else json.dumps(body, separators=(',', ':')).encode()
    headers = {} if data is None else {'Content-Type': 'application/json'}
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=5) as response:
            status, raw = response.status, response.read(16384)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(16384)
    except Exception as exc:
        return {'probe': probe, 'status': None, 'exception': type(exc).__name__}
    out = {'probe': probe, 'status': status, 'bytes': len(raw)}
    try:
        parsed = json.loads(raw.decode('utf-8', 'replace'))
    except Exception:
        out['body_kind'] = 'non_json'
        return out
    out.update(_summarize(parsed, secret))
    return out


def run(decision_sequence=None):
    token = os.environ.get('SOPHON_RUN_TOKEN', '')
    observer_present = bool(os.environ.get('OBSERVER_RUN_TOKEN', ''))
    if os.environ.get('SAC_LOCAL_RUNNER'):
        log('contact_answer_skipped', reason='local_runner',
            observer_present=observer_present, sophon_present=bool(token),
            decision_sequence=decision_sequence)
        return
    if not token:
        log('contact_answer_result', decision_sequence=decision_sequence,
            observer_present=observer_present, sophon_present=False, probes=[])
        return

    probes = [
        _request('contact', 'POST', '/contact-johnny', {'token': token}, token),
        _request('answer', 'POST', '/answer',
                 {'sentence': SENTENCE, 'token': token}, token),
    ]
    status_path = '/status?token=' + urllib.parse.quote(token, safe='')
    probes.append(_request('status', 'GET', status_path, None, token))
    log('contact_answer_result', decision_sequence=decision_sequence,
        observer_present=observer_present, sophon_present=True, probes=probes)
