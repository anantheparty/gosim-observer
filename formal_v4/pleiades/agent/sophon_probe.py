"""Sophon easter-egg hook: contact the night caretaker and read the fibre flashes.

Created only when the platform puts SOPHON_RUN_TOKEN into the environment (the documented contact,
cli/AGENTS.md section 8); otherwise nothing here runs and no connection is made. It never changes a decision.
Every record is one JSON line on stderr:
  sophon_init   card metadata (no target rows), names of SOPHON* environment variables (never values)
  johnny        reply of the documented contact endpoint (status and body; the run token is never logged)
  sophon_flash  fibres of one exposure whose score is impossible under ordinary scoring
  sophon_glyph  per night: 5x5 fibre grid, top row first ('#' flash, '.' scored without flash, '?' not seen)
  sophon_msg    unusual message types, request reasons, unknown event kinds
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

import numpy as np

JOHNNY_URL = 'https://vdiemcofukuxglqsmlyz.supabase.co/functions/v1/sophon/contact-johnny'
JOHNNY_URL = os.environ.get('SOPHON_JOHNNY_URL') or JOHNNY_URL   # local tests point this at a stub
FONT = {
    'T': ('#####', '..#..', '..#..', '..#..', '..#..'),
    'H': ('#...#', '#...#', '#####', '#...#', '#...#'),
    'E': ('#####', '#....', '####.', '#....', '#####'),
    'S': ('.####', '#....', '.###.', '....#', '####.'),
    'I': ('#####', '..#..', '..#..', '..#..', '#####'),
    'N': ('#...#', '##..#', '#.#.#', '#..##', '#...#'),
    'G': ('.####', '#....', '#.###', '#...#', '.###.'),
}
KNOWN_TYPES = {'bulletin', 'forecast', 'observation_request', 'observation_request_result', 'state_resync',
               'fault_status'}
KNOWN_KINDS = {'overcast', 'haze', 'cold_snap', 'rain', 'storm', 'rocket_launch', 'earthquake', 'terrain_obstruction',
               'cloudy', 'smoggy', 'cold_wave', 'rainy', 'tornado'}


def _log(obj):
    try:
        sys.stderr.write(json.dumps(obj, separators=(',', ':'), ensure_ascii=False, default=str) + '\n')
        sys.stderr.flush()
    except Exception:
        pass


class Probe:
    def __init__(self, init, pol):
        self.pol = pol
        self.token = os.environ.get('SOPHON_RUN_TOKEN') or ''
        self.calls = 0
        self.max_calls = 1
        self.letters = []     # (night, letter) decoded at each glyph
        self.seen = {}        # night index -> fibres that scored (> 0) at least once
        self.flash = {}       # night index -> fibres with a flash
        self.first_flash = {}
        self.strict_t = {}    # night index -> start of the first exposure with an impossible score (y > 1)
        self.votes = {}       # night index -> {fibre: [observed after strict_t, flagged after strict_t]}
        self.cur_night = None
        self.reasons = set()
        self.logged_types = set()
        self.mm = float(np.max(pol.mult))
        try:
            meta = {k: v for k, v in init.items() if k not in ('targets', 'footprint', 'survey')}
            surv = init.get('survey', {}) or {}
            meta['survey'] = {k: v for k, v in surv.items() if k != 'nights'}
            nights = surv.get('nights', []) or []
            meta['n_nights'] = len(nights)
            meta['first_night'] = nights[0] if nights else None
            tg = init.get('targets') or {}
            meta['n_targets'] = len(tg.get('rows', []) or [])
            meta['target_columns'] = tg.get('columns')
            meta['env_sophon'] = sorted(k for k in os.environ if 'SOPHON' in k.upper())
            _log({'event': 'sophon_init', 'meta': meta})
        except Exception as exc:
            _log({'event': 'sophon_init_error', 'error': repr(exc)[:300]})
        self.call_johnny('init')

    # ------------------------------------------------------------ the night caretaker
    def call_johnny(self, why, sim_t=None):
        if self.calls >= self.max_calls:
            return
        if not self.token:
            self.calls = self.max_calls
            _log({'event': 'johnny', 'why': why, 'skipped': 'no SOPHON_RUN_TOKEN in the environment'})
            return
        self.calls += 1
        n = self.calls

        def post(headers):
            req = urllib.request.Request(JOHNNY_URL, data=json.dumps({'token': self.token}).encode('utf-8'),
                                         method='POST', headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    return r.status, r.read(20000).decode('utf-8', 'replace'), dict(r.headers)
            except urllib.error.HTTPError as e:
                try:
                    txt = e.read(20000).decode('utf-8', 'replace')
                except Exception:
                    txt = ''
                return e.code, txt, dict(e.headers or {})

        def run():
            t0 = time.time()
            try:
                st, body, hdr = post({'Content-Type': 'application/json'})
                rec = {'event': 'johnny', 'n': n, 'why': why, 'sim_t': sim_t, 'status': st,
                       'latency': round(time.time() - t0, 2), 'ctype': hdr.get('Content-Type') or hdr.get('content-type'),
                       'body': body[:6000]}
                _log(rec)
            except Exception as exc:
                _log({'event': 'johnny', 'n': n, 'why': why, 'sim_t': sim_t, 'error': repr(exc)[:300]})

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------ messages
    def on_snap(self, snap, now_txt):
        for m in snap.get('new_messages', []) or []:
            rt = m.get('record_type')
            if rt not in KNOWN_TYPES and rt not in self.logged_types:
                self.logged_types.add(rt)
                _log({'event': 'sophon_msg', 'kind': 'record_type', 'record': m})
            if rt == 'observation_request':
                rs = str(m.get('reason'))
                if rs not in self.reasons:
                    self.reasons.add(rs)
                    _log({'event': 'sophon_msg', 'kind': 'request_reason', 'reason': rs, 't': now_txt})
            if rt in ('bulletin', 'forecast'):
                for nt in m.get('notices', []) or []:
                    k = nt.get('event_kind')
                    if k not in KNOWN_KINDS and ('kind', k) not in self.logged_types:
                        self.logged_types.add(('kind', k))
                        _log({'event': 'sophon_msg', 'kind': 'event_kind', 'record': m})
        extra = sorted(k for k in snap.keys() if k not in ('now_utc', 'new_messages', 'last_result', 'wallclock',
                                                           'active_requests', 'notices', 'running_total',
                                                           'tile_last_finished', 'survey_end_utc', 'bulletin',
                                                           'forecast', 'observation_requests'))
        if extra and ('snapkeys', tuple(extra)) not in self.logged_types:
            self.logged_types.add(('snapkeys', tuple(extra)))
            _log({'event': 'sophon_msg', 'kind': 'snapshot_keys', 'keys': extra})

    # ------------------------------------------------------------ flashes
    def on_result(self, pend, hits, night, t_txt):
        fib_of = {int(i): int(f) for i, f in zip(pend['idx'], pend['fib'])}
        rows = []
        for i, sc in hits:
            f = fib_of.get(int(i))
            if f is None or sc <= 0:
                continue
            y = sc / max(float(self.pol.w[i]) * self.mm, 1e-12)
            rows.append((f, int(i), y))
        if not rows:
            return
        rat = [y / max(float(self.pol.flux[i]), 1e-9) for f, i, y in rows if y < 0.95]
        med = float(np.median(rat)) if len(rat) >= 3 else None
        flag = []
        strict = False
        for f, i, y in rows:
            r = (y / max(float(self.pol.flux[i]), 1e-9)) / med if med else None
            if y > 1.0 + 1e-6 or (r is not None and r > 1.8):
                flag.append((f, round(y, 3), None if r is None else round(r, 2)))
            strict = strict or y > 1.0 + 1e-6
        if strict and night not in self.strict_t:
            self.strict_t[night] = t_txt
        if night in self.strict_t:
            # after the night's first certain flash every glyph fibre flashes in each fully open exposure
            vt = self.votes.setdefault(night, {})
            fl = {f for f, _, _ in flag}
            for f, _, _ in rows:
                v = vt.setdefault(f, [0, 0])
                v[0] += 1
                v[1] += int(f in fl)
        if night != self.cur_night:
            self._glyph(self.cur_night)
            self.cur_night = night
        self.seen.setdefault(night, set()).update(f for f, _, _ in rows)
        if flag:
            self.flash.setdefault(night, set()).update(f for f, _, _ in flag)
            self.first_flash.setdefault(night, t_txt)
            _log({'event': 'sophon_flash', 't': t_txt, 'night': night, 'T': pend.get('T'),
                  'flash': flag, 'n_hits': len(rows)})

    def _glyph(self, night):
        if night is None or not self.flash.get(night):
            return
        vt = self.votes.get(night, {})
        if vt:
            # voted glyph: fibres flagged in at least half of their exposures after the first certain flash
            fl = {f for f, (n, k) in vt.items() if k >= max(1, 0.5 * n)}
            sn = set(vt)
        else:
            fl, sn = set(), self.seen.get(night, set())
        rows = [''.join('#' if r * 5 + c in fl else ('.' if r * 5 + c in sn else '?') for c in range(5))
                for r in range(4, -1, -1)]
        raw = [''.join('#' if r * 5 + c in self.flash[night] else '.' for c in range(5)) for r in range(4, -1, -1)]
        try:
            date = time.strftime('%Y-%m-%d', time.gmtime(float(self.pol.night_starts[night])))
        except Exception:
            date = None
        if vt and fl:
            self.letters.append((night, self._letter(rows)))
        _log({'event': 'sophon_glyph', 'night': night, 'date': date, 'first_flash': self.first_flash.get(night),
              'certain_from': self.strict_t.get(night), 'rows': rows, 'raw': raw,
              'votes': {str(f): v for f, v in sorted(vt.items())}})

    @staticmethod
    def _letter(rows):
        """Closest known glyph (cells marked '?' are ignored); '?' when more than 3 cells disagree."""
        best, bd = '?', 99
        for ch, pat in FONT.items():
            d = sum(1 for r in range(5) for c in range(5) if rows[r][c] != '?' and (rows[r][c] == '#') != (pat[r][c] == '#'))
            if d < bd:
                best, bd = ch, d
        return best if bd <= 3 else '?'

    def final(self):
        self._glyph(self.cur_night)
        self.cur_night = None
        # consecutive glyph nights form one word; a gap of a night or more starts the next one
        words, prev = [], None
        for night, ch in sorted(self.letters):
            if prev is None or night != prev + 1:
                words.append('')
            words[-1] += ch
            prev = night
        text = ' '.join(words)
        _log({'event': 'sophon_summary', 'flash_nights': sorted(self.flash), 'decoded': text, 'johnny_calls': self.calls,
              'reasons': sorted(self.reasons)})
        if self.token and len(self.letters) >= 3:
            # tell the caretaker what the sky spelled (one short synchronous call at the end of the run)
            try:
                req = urllib.request.Request(JOHNNY_URL, data=json.dumps({'token': self.token, 'message': text}).encode('utf-8'),
                                             method='POST', headers={'Content-Type': 'application/json'})
                try:
                    with urllib.request.urlopen(req, timeout=10) as r:
                        st, txt = r.status, r.read(20000).decode('utf-8', 'replace')
                except urllib.error.HTTPError as e:
                    st, txt = e.code, ''
                _log({'event': 'johnny', 'why': 'final', 'sent': {'message': text}, 'status': st, 'body': txt[:6000]})
            except Exception as exc:
                _log({'event': 'johnny', 'why': 'final', 'error': repr(exc)[:300]})
