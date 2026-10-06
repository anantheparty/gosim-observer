#!/usr/bin/env python3
"""seasonfit.py DIR... : per-night median log(observation quality) from high-altitude, moon-down observations of an
online result ZIP (or a local run dir), and a least-squares fit log q = a + b*sin(2*pi*(doy - phi)/365.2425) over phi."""
import sys, os, io, csv, json, math, zipfile, collections
sys.path.insert(0, '/home/shu/kamico/observer/work/pkgs/c28b')
import astro
import numpy as np

def rows(path, name):
    if path.endswith('.zip'):
        z = zipfile.ZipFile(path)
        nm = [i.filename for i in z.infolist() if i.filename.endswith(name)][0]
        return list(csv.DictReader(io.TextIOWrapper(z.open(nm))))
    return list(csv.DictReader(open(os.path.join(path, name))))

def site_of(path):
    # the agent log of our own policy prints the site at start; fall back to known card sites
    return None

def fit(path, lat, lon, label):
    dec = {r['observe_index']: r for r in rows(path, 'decisions.csv') if r['action'] == 'observe'}
    per = collections.defaultdict(list)
    for r in rows(path, 'observations.csv'):
        if r['valid'] != 'true':
            continue
        d = dec.get(r['observe_index'])
        if not d or float(d['alt_deg']) < 65:
            continue
        q = float(r['quality'])
        if q <= 0.02:
            continue
        t = astro.parse_utc(d['start_utc']) + 0.5 * float(d['duration_seconds'])
        ms = astro.moon_state(t, lat, lon)
        malt = ms[2]
        if malt > -5:
            continue
        per[d['start_utc'][:10]].append(math.log(q))
    days, vals = [], []
    for k, v in sorted(per.items()):
        if len(v) >= 3:
            doy = astro.time.gmtime(astro.parse_utc(k + 'T00:00:00Z')).tm_yday if hasattr(astro, 'time') else None
            import time as _t
            doy = _t.gmtime(astro.parse_utc(k + 'T12:00:00Z')).tm_yday
            days.append(doy); vals.append(float(np.median(v)))
    days, vals = np.array(days, float), np.array(vals)
    if len(days) < 20:
        print(label, 'too few nights', len(days)); return
    best = None
    for phi in range(0, 365, 5):
        s = np.sin(2 * math.pi * (days - phi) / 365.2425)
        A = np.vstack([np.ones_like(s), s]).T
        coef, res, *_ = np.linalg.lstsq(A, vals, rcond=None)
        r = float(np.sum((A @ coef - vals) ** 2))
        if best is None or r < best[0]:
            best = (r, phi, coef)
    r, phi, (a, b) = best
    # express as the phase where log q is LOWEST (b*sin max with b<0) like the generator (worst at phi+91 when b<0)
    print(f'{label}: nights {len(days)} doy {int(days.min())}-{int(days.max())} fit a {a:+.3f} b {b:+.3f} phi {phi} '
          f'-> worst doy {int((phi + (91 if b < 0 else -91)) % 365)} | prior: worst doy 301, b -0.34')

if __name__ == '__main__':
    for spec in sys.argv[1:]:
        path, lat, lon, label = spec.split(',')
        fit(path, float(lat), float(lon), label)
