"""Write one continuous celestial M, then wait through the season.

Only public initialization and snapshots are used. No network or credentials.
"""
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

DEG = math.pi / 180.0


def epoch(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def utc(value):
    return datetime.fromtimestamp(round(value), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def lst(t, longitude):
    return (280.46061837 + 360.98564736629 * (t / 86400.0 + 2440587.5 - 2451545.0) + longitude) % 360


def altaz(ra, dec, t, latitude, longitude):
    hour = ((lst(t, longitude) - ra + 180) % 360 - 180) * DEG
    la, de = latitude * DEG, dec * DEG
    z = math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(hour)
    alt = math.asin(max(-1, min(1, z)))
    az = math.atan2(-math.sin(hour) * math.cos(de),
                    math.sin(de) * math.cos(la) - math.cos(de) * math.sin(la) * math.cos(hour))
    return alt / DEG, (az / DEG) % 360


def log(event, **fields):
    print(json.dumps({'event': event, **fields}, separators=(',', ':'), allow_nan=False),
          file=sys.stderr, flush=True)


class Policy:
    def __init__(self, init):
        cfg = json.loads(Path(__file__).with_name('probe_config.json').read_text())
        self.lat = float(init['site']['latitude_deg'])
        self.lon = float(init['site']['longitude_deg'])
        self.min_alt = float(init['site'].get('minimum_altitude_deg', 30))
        exposure = init['instrument']['exposure']
        self.duration = int(exposure['min_duration_seconds'])
        self.end = epoch(init['survey']['end_utc'])
        self.nights = [(epoch(n['observing_start_utc']), epoch(n['observing_end_utc']))
                       for n in init['survey']['nights']]
        vertices = [(-1, -1), (-1, 1), (0, -1), (1, 1), (1, -1)]
        n = int(cfg['samples_per_stroke'])
        self.points = [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
                       for a, b in zip(vertices, vertices[1:]) for i in range(n)] + [vertices[-1]]
        self.radius = float(cfg['half_size_deg'])
        self.center = None
        self.index = 0
        self.pending = None
        self.completed = False
        log('skywrite_init', letter='M', points=len(self.points), duration_seconds=self.duration,
            half_size_deg=self.radius, horizon_minimum=self.min_alt)

    def wait(self, t):
        return {'action': 'wait', 'until_utc': utc(min(self.end, t))}

    def decide(self, snap):
        now = epoch(snap['now_utc'])
        if self.pending is not None:
            result = snap.get('last_result') or {}
            if result.get('action') == 'observe':
                self.index += 1
                log('skywrite_completed_point', point=self.pending, observe_index=result.get('observe_index'))
            else:
                log('skywrite_point_not_observed', point=self.pending, action=result.get('action'))
            self.pending = None
        if self.index >= len(self.points):
            if not self.completed:
                log('skywrite_complete', letter='M', points=self.index, time=utc(now))
                self.completed = True
            return self.wait(self.end)
        window = next(((a, b) for a, b in self.nights if a <= now < b), None)
        if window is None:
            return self.wait(next((a for a, b in self.nights if a > now), self.end))
        if now + self.duration > window[1]:
            return self.wait(next((a for a, b in self.nights if a > now), self.end))
        notices = (snap.get('latest_bulletin') or {}).get('notices') or []
        if any(n.get('event_kind') in ('rain', 'storm', 'tornado') and n.get('direction') in (None, 'ALL')
               for n in notices):
            return self.wait(min(window[1], now + 900))
        if self.center is None:
            span = len(self.points) * self.duration
            if now + span + 60 > window[1]:
                return self.wait(next((a for a, b in self.nights if a > now), self.end))
            center_ra = max(20.0, min(340.0, lst(now + span / 2, self.lon)))
            center_dec = max(-55.0, min(55.0, self.lat + (25 if self.lat <= 0 else -25)))
            self.center = center_ra, center_dec
            log('skywrite_center', ra_deg=center_ra, dec_deg=center_dec, at_utc=utc(now))
        x, y = self.points[self.index]
        ra0, dec0 = self.center
        ra = (ra0 + self.radius * x / math.cos(dec0 * DEG)) % 360
        dec = dec0 + self.radius * y
        alt, az = altaz(ra, dec, now, self.lat, self.lon)
        end_alt, _ = altaz(ra, dec, now + self.duration, self.lat, self.lon)
        if min(alt, end_alt) < self.min_alt + 1:
            return self.wait(min(window[1], now + 300))
        self.pending = self.index
        log('skywrite_point', point=self.index, x=x, y=y, ra_deg=ra, dec_deg=dec,
            alt_deg=alt, az_deg=az, at_utc=utc(now))
        return {'action': 'observe', 'pointing': {'alt_deg': alt, 'az_deg': az},
                'assignments': {}, 'duration_seconds': self.duration, 'program': 'BACKUP',
                'decision_source': 'sophon4-redrum-M', 'reason': 'Write M in the sky, point %d' % self.index}
