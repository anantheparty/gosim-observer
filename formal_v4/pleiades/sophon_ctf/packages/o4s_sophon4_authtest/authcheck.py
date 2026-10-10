"""Read-only check: does the Sophon function accept this run's own credential?

Two GETs to the organizer's Sophon function on the platform host (taken from OBSERVER_API_URL): status?token= and
/desk with the run credential as Bearer. Logs only HTTP status, top-level keys, 'board', 'error' and a short,
token-redacted 'johnny' text. The credential value is never logged, written or sent anywhere else.
"""
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request


def log(event, **fields):
    print(json.dumps({'event': event, **fields}, separators=(',', ':'), default=str), file=sys.stderr, flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(url, token, headers):
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with opener.open(req, timeout=8) as r:
            status, raw = r.status, r.read(20000)
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read(20000)
    except Exception as e:  # network errors: log the type only
        return {'status': None, 'exception': type(e).__name__}
    text = raw.decode('utf-8', 'replace').replace(token, '[run-credential]')
    out = {'status': status, 'bytes': len(raw)}
    try:
        body = json.loads(text)
    except Exception:
        out['text'] = text[:160]
        return out
    if isinstance(body, dict):
        out['keys'] = sorted(body)[:20]
        for k in ('board', 'error', 'ok', 'next'):
            if k in body:
                out[k] = body[k] if not isinstance(body[k], (dict, list)) else '<%s>' % type(body[k]).__name__
        if isinstance(body.get('johnny'), str):
            out['johnny'] = body['johnny'][:160]
        if isinstance(body.get('found'), list):
            out['found_count'] = len(body['found'])
    return out


def run():
    token = os.environ.get('OBSERVER_RUN_TOKEN', '')
    api = os.environ.get('OBSERVER_API_URL', '')
    if not token or not api or os.environ.get('SAC_LOCAL_RUNNER'):
        log('authcheck_skipped', token_present=bool(token), api_present=bool(api))
        return
    parts = urllib.parse.urlsplit(api)
    base = '%s://%s/functions/v1/sophon' % (parts.scheme, parts.netloc)
    log('authcheck_host', host=parts.netloc)
    results = {}
    results['status_query'] = _get(base + '/status?token=' + urllib.parse.quote(token, safe=''), token, {})
    results['desk_bearer'] = _get(base + '/desk', token, {'Authorization': 'Bearer ' + token})
    log('authcheck_result', **results)


def start():
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t
