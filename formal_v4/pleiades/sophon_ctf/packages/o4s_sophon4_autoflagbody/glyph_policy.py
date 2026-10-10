"""Write REDRUM letters with the fibres: each exposure assigns targets only to the fibres of one 5x5 glyph.

Fibre f = row * side + col, row 0 = lowest altitude, col 0 = lowest azimuth (the convention in which the
Sophon's own glyphs read THESHINING). Glyph strings are printed top row first. Only public initialize and
snapshot data are used; no network, no model.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

from astro import DEG, fmt_utc, lst_deg, parse_utc
from probe_geometry import _classify_np, _shift

GLYPHS = {
    'E': ['#####', '#....', '####.', '#....', '#####'],   # exact glyph seen on the real card
    'M': ['#...#', '##.##', '#.#.#', '#...#', '#...#'],
    'U': ['#...#', '#...#', '#...#', '#...#', '.###.'],
    'R': ['####.', '#...#', '####.', '#..#.', '#...#'],
    'D': ['####.', '#...#', '#...#', '#...#', '####.'],
}


def log(event, **fields):
    print(json.dumps({'event': event, **fields}, separators=(',', ':'), default=str), file=sys.stderr, flush=True)


def fibres(rows, side, mirror=False):
    out = []
    for r, line in enumerate(rows):
        for c, ch in enumerate(line[::-1] if mirror else line):
            if ch == '#':
                out.append((side - 1 - r) * side + c)
    return sorted(out)


class Policy:
    def __init__(self, init):
        self.cfg = json.loads(Path(__file__).with_name('probe_config.json').read_text())
        site, ins, survey = init['site'], init['instrument'], init['survey']
        self.lat, self.lon = float(site['latitude_deg']), float(site['longitude_deg'])
        self.min_alt = float(site.get('minimum_altitude_deg', 30))
        self.side, self.pitch = int(ins['grid_side']), float(ins['pitch_deg'])
        self.glass = float(ins['glass_side_deg'])
        self.tmin = int(ins['exposure']['min_duration_seconds'])
        self.tmax = int(ins['exposure']['max_duration_seconds'])
        self.nights = [(parse_utc(n['observing_start_utc']), parse_utc(n['observing_end_utc'])) for n in survey['nights']]
        self.starts = np.array([a for a, b in self.nights])
        self.end = parse_utc(survey['end_utc'])
        cols = {c: i for i, c in enumerate(init['targets']['columns'])}
        rows = init['targets']['rows']
        self.ids = [str(r[cols['target_id']]) for r in rows]
        ra = np.array([float(r[cols['ra_deg']]) for r in rows])
        dec = np.array([float(r[cols['dec_deg']]) for r in rows])
        self.flux = np.array([float(r[cols['feature_flux']]) for r in rows])
        self.ra, self.sd, self.cd = ra, np.sin(dec * DEG), np.cos(dec * DEG)
        self.sl, self.cl = math.sin(self.lat * DEG), math.cos(self.lat * DEG)
        # One letter per night, like the Sophon's own writing: every exposure of that night uses only its fibres.
        self.plan = [(name, fibres(GLYPHS[name.rstrip('~')], self.side, name.endswith('~')))
                     for name in self.cfg['letters']]
        self.per_night = int(self.cfg['exposures_per_night'])
        self.night = None
        self.count = 0
        self.index = 0
        self.pending = None
        self.retries = 0
        self.written = []
        self.done_logged = False
        self.rng = np.random.default_rng(int(self.cfg.get('seed', 237)))
        self.margin = max(0.003, (self.pitch - self.glass) / 2 + 0.003)
        log('glyph_init', letters=[p[0] for p in self.plan], fibres={p[0]: p[1] for p in self.plan},
            side=self.side, pitch=self.pitch, glass=self.glass, targets=len(self.ids))

    def horizon(self, t):
        h = ((lst_deg(t, self.lon) - self.ra + 180) % 360 - 180) * DEG
        z = self.sl * self.sd + self.cl * self.cd * np.cos(h)
        y = -self.cd * np.sin(h)
        x = (self.sd - z * self.sl) / self.cl
        return np.column_stack((x, y, z)), np.arcsin(np.clip(z, -1, 1)) / DEG

    def wait(self, t):
        return {'action': 'wait', 'until_utc': fmt_utc(t)}

    def next_night(self, now):
        future = self.starts[self.starts > now]
        return float(future[0]) if len(future) else self.end

    def search(self, now, duration, want):
        tv, alt = self.horizon(now)
        _, end_alt = self.horizon(now + duration)
        pool = np.flatnonzero((alt >= self.min_alt + 3) & (end_alt >= self.min_alt + 3) & (self.flux > 0))
        if len(pool) < len(want):
            return None
        vectors = tv[pool]
        az_all = np.degrees(np.arctan2(tv[:, 1], tv[:, 0])) % 360
        anchors = self.rng.choice(pool, min(int(self.cfg['candidates']), len(pool)), replace=False)
        wanted = set(want)
        best = None
        for k, anchor in enumerate(anchors):
            fiber = want[k % len(want)]
            row, col = divmod(fiber, self.side)
            ca, cz = _shift(float(alt[anchor]), float(az_all[anchor]),
                            -(row - (self.side - 1) / 2) * self.pitch, -(col - (self.side - 1) / 2) * self.pitch)
            idx, cells, margins = _classify_np(ca, cz, vectors, self.side, self.pitch, self.margin,
                                               math.cos(self.side * self.pitch * DEG))
            chosen = {}
            for j, f, m in zip(idx, cells, margins):
                f = int(f)
                if f in wanted and (f not in chosen or m > chosen[f][1]):
                    chosen[f] = (int(pool[j]), float(m))
            if best is None or len(chosen) > len(best[2]):
                best = (ca, cz, chosen)
                if len(chosen) == len(want):
                    break
        return best

    def decide(self, snap):
        now = parse_utc(snap['now_utc'])
        if self.pending is not None:
            result = snap.get('last_result') or {}
            log('glyph_result', letter=self.pending, action=result.get('action'),
                observe_index=result.get('observe_index'), valid=result.get('valid'))
            self.pending = None
        night = int(np.searchsorted(self.starts, now, side='right')) - 1
        if night != self.night:
            if self.count:
                self.index += 1
            self.night, self.count, self.retries = night, 0, 0
        if self.index >= len(self.plan):
            if not self.done_logged:
                log('glyph_done', written=self.written)
                self.done_logged = True
            return self.wait(self.end)
        duration = int(max(self.tmin, min(self.tmax, int(self.cfg['exposure_seconds']))))
        if night < 0 or self.count >= self.per_night or now + duration + 60 > self.nights[night][1]:
            return self.wait(self.next_night(now))
        notices = (snap.get('latest_bulletin') or {}).get('notices') or []
        if any(n.get('event_kind') in ('rain', 'storm', 'tornado') and n.get('direction') in (None, 'ALL')
               for n in notices):
            return self.wait(min(self.nights[night][1], now + 900))
        name, want = self.plan[self.index]
        best = self.search(now, duration, want)
        complete = best is not None and len(best[2]) == len(want)
        if not complete:
            # Never a partial letter: try again a little later (the sky turns), next night if this one runs out.
            self.retries += 1
            log('glyph_retry', letter=name, covered=len(best[2]) if best else 0, need=len(want), at=fmt_utc(now))
            return self.wait(min(self.nights[night][1], now + 600))
        self.count += 1
        ca, cz, chosen = best
        assignments = {str(f): self.ids[i] for f, (i, _) in sorted(chosen.items())}
        self.pending = name
        self.written.append({'letter': name, 'fibres': sorted(chosen), 'complete': complete, 'at': fmt_utc(now)})
        log('glyph_write', letter=name, complete=complete, fibres=sorted(chosen), want=want,
            alt=ca, az=cz, at=fmt_utc(now), duration=duration)
        return {'action': 'observe', 'pointing': {'alt_deg': ca, 'az_deg': cz}, 'assignments': assignments,
                'duration_seconds': duration, 'program': 'DARK', 'decision_source': 'sophon4-redrum-glyph',
                'reason': 'REDRUM: write %s with the fibres' % name}
