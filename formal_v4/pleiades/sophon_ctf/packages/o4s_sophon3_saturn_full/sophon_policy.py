"""Bounded coverage probe based on sophon2 geometry and fibre evidence.

Consumes public initialize/snapshots only. After the planet exposure, wait to season end.
"""
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from astro import DEG, SID, fmt_utc, lst_deg, parse_utc
from planet_ephem import altaz, planet, EL
from probe_geometry import _classify_np, _shift
from sophon_probe import Probe, log


class Policy:
    def __init__(self, init, params=None):
        self.cfg = json.loads(Path(__file__).with_name('probe_config.json').read_text())
        self.object = os.getenv('SOPHON_DIVE_OBJECT', self.cfg['dive_object']).lower()
        if self.object not in EL:
            self.object = 'jupiter'
        site, ins, survey = init['site'], init['instrument'], init['survey']
        self.lat, self.lon = float(site['latitude_deg']), float(site['longitude_deg'])
        self.side, self.nfib = int(ins['grid_side']), int(ins['n_fibers'])
        self.pitch, self.glass = float(ins['pitch_deg']), float(ins['glass_side_deg'])
        self.tmin = int(ins['exposure']['min_duration_seconds'])
        self.tmax = int(ins['exposure']['max_duration_seconds'])
        self.min_alt = float(site.get('minimum_altitude_deg', 30))
        self.nights = [(parse_utc(n['observing_start_utc']), parse_utc(n['observing_end_utc'])) for n in survey['nights']]
        self.starts = np.array([a for a, b in self.nights])
        self.end = parse_utc(survey['end_utc'])
        cols = {c: i for i, c in enumerate(init['targets']['columns'])}
        rows = init['targets']['rows']
        self.ids = [str(r[cols['target_id']]) for r in rows]
        self.ra = np.array([float(r[cols['ra_deg']]) for r in rows])
        self.dec = np.array([float(r[cols['dec_deg']]) for r in rows])
        self.flux = np.array([float(r[cols['feature_flux']]) for r in rows])
        self.w = np.array([float(r[cols['science_weight']]) for r in rows])
        self.sd, self.cd = np.sin(self.dec * DEG), np.cos(self.dec * DEG)
        self.sl, self.cl = math.sin(self.lat * DEG), math.cos(self.lat * DEG)
        sc = init['scoring']
        self.max_mult = max([1.0] + list(sc.get('program', {}).get('multipliers', {}).values()))
        self.pending = None
        self.dove = False
        self.decisions = 0
        self.observes = 0
        self.cover = {}
        self.rng = np.random.default_rng(303)
        self.probe = Probe(self, self.cfg)
        self.dive_t = self.find_dive(self.starts[0])
        self.emergency = False
        log('sophon_dive_plan', object=self.object, time=fmt_utc(self.dive_t) if self.dive_t else None,
            horizon_margin=self.cfg['horizon_margin_deg'])

    def position(self, t):
        dt = datetime.fromtimestamp(t, timezone.utc)
        return altaz(*planet(self.object, dt), dt, self.lat, self.lon)

    def find_dive(self, after, latest=True):
        windows = reversed(self.nights) if latest else iter(self.nights)
        for a, b in windows:
            lo, hi = max(a, after), min(b, self.end) - self.tmin - 60
            if hi < lo:
                continue
            ts = np.arange(hi, lo - 1, -300) if latest else np.arange(lo, hi + 1, 300)
            for t in ts:
                if self.position(float(t))[0] >= float(self.cfg['horizon_margin_deg']):
                    return float(t)
        return None

    def horizon(self, t):
        h = ((lst_deg(t, self.lon) - self.ra + 180) % 360 - 180) * DEG
        z = self.sl * self.sd + self.cl * self.cd * np.cos(h)
        y = -self.cd * np.sin(h)
        x = (self.sd - z * self.sl) / self.cl
        return np.column_stack((x, y, z)), np.arcsin(np.clip(z, -1, 1)) / DEG

    def wait(self, t):
        return {'action': 'wait', 'until_utc': fmt_utc(t)}

    def decide(self, snap):
        now = parse_utc(snap['now_utc'])
        self.decisions += 1
        self.probe.on_snap(snap)
        self.probe.on_result(self.pending, snap.get('last_result') or {})
        self.pending = None
        if self.dove:
            self.probe.final()
            # One wait-until is expanded inside the engine without further agent turns.
            # This also drains the season after an early, budget-triggered dive.
            return self.wait(self.end)
        remaining = float((snap.get('wallclock') or {}).get('remaining_seconds', 900))
        if remaining < 45 and not self.emergency:
            self.emergency = True
            self.dive_t = self.find_dive(now, latest=False)
            log('sophon_budget_reserve', remaining=remaining, dive_at=fmt_utc(self.dive_t) if self.dive_t else None)
        if self.dive_t is not None and now >= self.dive_t:
            alt, az = self.position(now)
            night = int(np.searchsorted(self.starts, now, side='right')) - 1
            if alt <= 0 or night < 0 or now + self.tmin > self.nights[night][1]:
                self.dive_t = self.find_dive(now + 1, latest=False)
                return self.wait(self.dive_t) if self.dive_t else {'action': 'finish'}
            self.dove = True
            self.probe.contact('before_final_dive')
            log('sophon_dive', object=self.object, time=fmt_utc(now), altitude=alt, azimuth=az)
            return {'action': 'observe', 'pointing': {'alt_deg': alt, 'az_deg': az},
                    'assignments': {}, 'duration_seconds': self.tmin, 'program': 'BACKUP',
                    'decision_source': 'sophon3-planet', 'reason': 'Deliberate final exposure: ' + self.object}
        if self.emergency and self.dive_t is not None:
            return self.wait(self.dive_t)
        night = int(np.searchsorted(self.starts, now, side='right')) - 1
        if night < 0 or now >= self.nights[night][1] - self.tmin:
            future = self.starts[self.starts > now]
            target = float(future[0]) if len(future) else self.end
            if self.dive_t is not None and now < self.dive_t < target:
                target = self.dive_t
            return self.wait(target) if target > now else {'action': 'finish'}
        stop = min(self.nights[night][1], self.dive_t if self.dive_t is not None else self.end)
        duration = int(min(self.tmax, self.cfg['exposure_seconds'], stop - now))
        if duration < self.tmin:
            return self.wait(stop)
        notices = (snap.get('latest_bulletin') or {}).get('notices', [])
        if any(n.get('event_kind') in ('rain', 'storm', 'tornado') and n.get('direction') in (None, 'ALL') for n in notices):
            return self.wait(min(stop, now + 900))
        tv, alt = self.horizon(now)
        _, end_alt = self.horizon(now + duration)
        pool = np.flatnonzero((alt >= self.min_alt + 2) & (end_alt >= self.min_alt + 2) & (self.flux > 0) & (self.w > 0))
        if not len(pool):
            return self.wait(min(stop, now + 900))
        max_pool = int(self.cfg['max_pool'])
        if len(pool) > max_pool:
            pool = self.rng.choice(pool, max_pool, replace=False)
        cov = self.cover.setdefault(night, np.zeros(self.nfib))
        votes = self.probe.votes.get(night, {})
        tested = np.array([votes.get(f, (0, 0))[0] for f in range(self.nfib)]) if night in self.probe.strict else cov
        # Exposure length and bright targets let boosted scores exceed the normal cap.
        bright = pool[self.flux[pool] * duration > 320]
        anchors = bright if len(bright) else pool
        ncenters = min(int(self.cfg['candidate_centers']), len(anchors))
        anchors = self.rng.choice(anchors, ncenters, replace=False)
        desired = np.argsort(tested + self.rng.random(self.nfib) * 0.01)
        best = None
        vectors = tv[pool]
        for k, anchor in enumerate(anchors):
            fiber = int(desired[k % len(desired)])
            row, col = divmod(fiber, self.side)
            az = math.degrees(math.atan2(tv[anchor, 1], tv[anchor, 0])) % 360
            ca, cz = _shift(float(alt[anchor]), az,
                -(row - (self.side - 1) / 2) * self.pitch,
                -(col - (self.side - 1) / 2) * self.pitch)
            idx, cells, margins = _classify_np(ca, cz, vectors, self.side, self.pitch,
                max(0.003, (self.pitch - self.glass) / 2 + 0.003), math.cos(self.side * self.pitch * DEG))
            chosen = {}
            for j, f in zip(idx, cells):
                i = int(pool[j]); f = int(f)
                if f not in chosen or self.flux[i] > self.flux[chosen[f]]:
                    chosen[f] = i
            value = sum((1 + 5 / (1 + tested[f])) * min(1, self.flux[i] * duration / 320)
                        for f, i in chosen.items())
            if best is None or value > best[0]:
                best = value, ca, cz, chosen
        if not best or not best[3]:
            return self.wait(min(stop, now + 900))
        _, ca, cz, chosen = best
        for f in chosen:
            cov[f] += 1
        assignments = {str(f): self.ids[i] for f, i in chosen.items()}
        self.pending = {'night': night, 'time': fmt_utc(now), 'duration': duration,
                        'by_target': {self.ids[i]: (i, f) for f, i in chosen.items()}}
        self.observes += 1
        return {'action': 'observe', 'pointing': {'alt_deg': ca, 'az_deg': cz},
                'assignments': assignments, 'duration_seconds': duration, 'program': 'DARK',
                'decision_source': 'sophon3-fiber-coverage'}

    def summary(self):
        self.probe.final()
        return {'observes': self.observes, 'decisions': self.decisions, 'dove': self.dove,
                'object': self.object, 'flash_rows': self.probe.flashes}
