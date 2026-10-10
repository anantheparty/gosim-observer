"""Bounded Sophon auth probe after the first decision request.

Only the organizer's fixed Sophon function is contacted. Runtime credentials stay in
memory and are never logged, persisted, parsed, hashed, or sent to another host.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://vdiemcofukuxglqsmlyz.supabase.co/functions/v1/sophon'
KNOWN_FLAG = 'SOPHON{TCB6TZD4JPXBQC8D3J6M}'  # already-solved sky receipt; auto proof only


def log(event, **fields):
    print(json.dumps({'event': event, **fields}, separators=(',', ':'), default=str),
          file=sys.stderr, flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _call(probe_id, method, path, token, headers=None, body=None):
    opener = urllib.request.build_opener(NoRedirect)
    raw_body = None if body is None else json.dumps(body, separators=(',', ':')).encode()
    request_headers = dict(headers or {})
    if raw_body is not None:
        request_headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(BASE + path, data=raw_body,
                                     headers=request_headers, method=method)
    try:
        with opener.open(request, timeout=3) as response:
            status, raw = response.status, response.read(8192)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(8192)
    except Exception as exc:
        return {'probe': probe_id, 'status': None, 'exception': type(exc).__name__}
    # Never log raw text. Parse in memory and emit a strict primitive whitelist.
    out = {'probe': probe_id, 'status': status, 'bytes': len(raw)}
    try:
        parsed = json.loads(raw.decode('utf-8', 'replace'))
    except Exception:
        out['body_kind'] = 'non_json'
        return out
    if not isinstance(parsed, dict):
        out['body_kind'] = type(parsed).__name__
        return out
    out['keys'] = sorted(str(key) for key in parsed)[:20]
    for key in ('board', 'error', 'ok', 'solved', 'no'):
        value = parsed.get(key)
        if isinstance(value, (str, bool, int)) or value is None:
            out[key] = value
    if isinstance(parsed.get('found'), list):
        out['found_count'] = len(parsed['found'])
    return out


def run(decision_sequence=None):
    observer_token = os.environ.get('OBSERVER_RUN_TOKEN', '')
    sophon_token = os.environ.get('SOPHON_RUN_TOKEN', '')
    if os.environ.get('SAC_LOCAL_RUNNER'):
        log('authcheck_skipped', reason='local_runner',
            observer_present=bool(observer_token), sophon_present=bool(sophon_token),
            decision_sequence=decision_sequence)
        return
    if not observer_token:
        log('authcheck_skipped', reason='observer_token_absent', observer_present=False,
            sophon_present=bool(sophon_token), decision_sequence=decision_sequence)
        return
    quoted = urllib.parse.quote(observer_token, safe='')
    probes = [
        ('desk_bearer', 'GET', '/desk', {'Authorization': 'Bearer ' + observer_token}),
        ('status_query', 'GET', '/status?token=' + quoted, {}),
        ('desk_none', 'GET', '/desk', {}),
        ('status_none', 'GET', '/status', {}),
        ('desk_query', 'GET', '/desk?token=' + quoted, {}),
        ('desk_bearer_site', 'GET', '/desk',
         {'Authorization': 'Bearer ' + observer_token, 'x-sophon-site': '1'}),
    ]
    results = []
    auto_mode = None
    for probe_id, method, path, headers in probes:
        result = _call(probe_id, method, path, observer_token, headers)
        results.append(result)
        if result.get('status') == 429:
            break
        if result.get('status') == 200 and result.get('board') == 'auto' and auto_mode is None:
            auto_mode = probe_id
    # Submit one already-known flag only after the service explicitly says this is auto.
    submission = None
    if auto_mode == 'desk_bearer':
        submission = _call('auto_flag_bearer', 'POST', '/desk/flag', observer_token,
                           {'Authorization': 'Bearer ' + observer_token},
                           {'flag': KNOWN_FLAG})
    elif auto_mode == 'desk_query':
        submission = _call('auto_flag_query', 'POST', '/desk/flag?token=' + quoted,
                           observer_token, {}, {'flag': KNOWN_FLAG})
    elif auto_mode == 'desk_bearer_site':
        submission = _call('auto_flag_bearer_site', 'POST', '/desk/flag', observer_token,
                           {'Authorization': 'Bearer ' + observer_token,
                            'x-sophon-site': '1'}, {'flag': KNOWN_FLAG})
    log('authcheck_result', decision_sequence=decision_sequence,
        observer_present=True, sophon_present=bool(sophon_token), probes=results,
        auto_mode=auto_mode, submission=submission)
