"""Sophon2-style fibre evidence; bounded documented Johnny contact, no model calls."""
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request

JOHNNY_URL = 'https://vdiemcofukuxglqsmlyz.supabase.co/functions/v1/sophon/contact-johnny'


def safe(value):
    if isinstance(value, dict):
        return {str(k): ('[redacted]' if any(x in str(k).lower() for x in
                ('token', 'authorization', 'api_key', 'password', 'secret')) else safe(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [safe(v) for v in value[:100]]
    if isinstance(value, str):
        value = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[redacted-jwt]', value)
        token = os.environ.get('SOPHON_RUN_TOKEN', '')
        return value.replace(token, '[redacted]') if token else value
    return value


def log(event, **data):
    print(json.dumps(safe(dict(event=event, **data)), ensure_ascii=False,
                     separators=(',', ':'), allow_nan=False), file=sys.stderr, flush=True)


class Probe:
    def __init__(self, pol, cfg):
        self.pol = pol
        self.current = None
        self.votes = {}
        self.strict = {}
        self.flashes = 0
        self.calls = 0
        self.jobs = []
        self.closed = False
        self.enabled = bool(cfg.get('johnny_enabled', True)) and not bool(os.getenv('SAC_LOCAL_RUNNER'))
        self.credential = os.getenv('SOPHON_RUN_TOKEN', '') if self.enabled else ''
        log('sophon_init', network_allowed=self.enabled, credential_present=bool(self.credential),
            nights=len(pol.nights), targets=len(pol.ids), fibers=pol.nfib)
        self.contact('initialize')

    def contact(self, why):
        if not self.enabled or not self.credential:
            if self.calls == 0:
                log('johnny_skip', reason='local runner / disabled / credential absent')
            return
        if self.calls >= 2:
            return
        self.calls += 1
        def worker():
            try:
                req = urllib.request.Request(JOHNNY_URL,
                    data=json.dumps({'token': self.credential}).encode(),
                    headers={'Content-Type': 'application/json'}, method='POST')
                # Never redirect the run credential to another host/path.
                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, *args, **kwargs):
                        return None
                opener = urllib.request.build_opener(NoRedirect())
                try:
                    response = opener.open(req, timeout=8)
                except urllib.error.HTTPError as exc:
                    response = exc
                with response:
                    body = response.read(24000).decode('utf-8', errors='replace')
                    try:
                        body = json.loads(body)
                    except ValueError:
                        pass
                    log('johnny_response', when=why, status=response.code, body=body)
            except Exception as exc:
                log('johnny_error', when=why, kind=type(exc).__name__)
        job = threading.Thread(target=worker, daemon=True)
        self.jobs.append(job)
        job.start()

    def on_snap(self, snap):
        known = {'bulletin', 'forecast', 'observation_request', 'request_result', 'report_result', 'state_resync'}
        for message in snap.get('new_messages') or []:
            if isinstance(message, dict) and (message.get('record_type') not in known or
                    re.search(r'receipt|sophon\{|johnny|ground.station', json.dumps(message), re.I)):
                log('sophon_message', value=message)
        for key, value in snap.items():
            if re.search(r'receipt|sophon|flag', key, re.I):
                log('sophon_snapshot_extra', key=key, value=value)

    def on_result(self, pending, result):
        if not pending or pending.get('dive') or result.get('action') != 'observe':
            return
        night = pending['night']
        if night != self.current:
            self.glyph(self.current)
            self.current = night
        rows = []
        for hit in result.get('hits', []):
            target = hit.get('target_id')
            if target not in pending['by_target']:
                continue
            i, fiber = pending['by_target'][target]
            score = float(hit.get('score') or 0)
            if score <= 0:
                continue
            ratio = score / max(1e-15, float(self.pol.w[i]) * self.pol.max_mult)
            rows.append((fiber, target, ratio))
        flashed = [r for r in rows if r[2] > 1.00001]
        if flashed:
            if night not in self.strict:
                self.strict[night] = pending['time']
                self.votes[night] = {}
            self.flashes += len(flashed)
            log('sophon_flash', night=night, time=pending['time'], duration=pending['duration'],
                observations=[{'fiber': f, 'target_id': t, 'ratio': round(v, 5)} for f, t, v in flashed])
        # Only positive returns after observed onset vote. Closed/blocked zeroes are unknown.
        if night in self.strict:
            votes = self.votes.setdefault(night, {})
            for fiber, _, ratio in rows:
                n, yes = votes.get(fiber, (0, 0))
                votes[fiber] = (n + 1, yes + int(ratio > 1.00001))

    def glyph(self, night):
        if night is None or night not in self.strict:
            return
        votes = self.votes.get(night, {})
        rows = []
        for row in reversed(range(self.pol.side)):
            line = ''
            for col in range(self.pol.side):
                n, yes = votes.get(row * self.pol.side + col, (0, 0))
                line += '?' if n < 2 else ('#' if yes >= n / 2 else '.')
            rows.append(line)
        log('sophon_glyph', night=night, onset_seen=self.strict[night], rows=rows,
            votes={str(f): list(v) for f, v in votes.items()})

    def final(self):
        if self.closed:
            return
        self.closed = True
        self.glyph(self.current)
        log('sophon_summary', flash_rows=self.flashes, flash_nights=sorted(self.strict), johnny_calls=self.calls)
        for job in self.jobs:
            job.join(timeout=0.2)
