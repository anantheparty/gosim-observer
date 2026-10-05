#!/usr/bin/env python3
"""reqfeas.py RUN_DIR WORLD_DIR : oracle feasibility of the required targets a run missed.

For each missed required target: the best completion factor any single exposure of length
<= max_duration could have reached over the season (truth weather, lunar factor, airmass;
terrain/directional events and faults ignored -> an upper bound), the number of nights with a
window reaching g >= 0.5, and what the run did (observations, best g).
"""
import csv, json, sys, math
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, '/home/shu/kamico/observer/hackathon-survey26')
from challenge.v4_scorer import lunar_quality_factor  # noqa: E402
from challenge.tile_geometry_simulator import _normalized_airmass  # noqa: E402

def pt(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)

run, world = sys.argv[1], sys.argv[2]
verbose = len(sys.argv) > 3
sc = json.load(open(f'{world}/config/v4_score_config.json'))
scen = json.load(open(f'{world}/config/v4_scenario.json'))
fc = json.load(open(f'{world}/config/v4_fiber_config.json'))
site = fc['site']
lat, lon = math.radians(site['latitude_deg']), site['longitude_deg']
min_alt = float(scen.get('minimum_altitude_deg', 30.0))
tmax = int(fc['exposure']['max_duration_seconds'])
f0t0 = sc['flux_zero_point'] * sc['exposure_zero_point_seconds']
beta = float(sc['airmass_exponent']); q0 = float(sc['q0'])
thr = 0.5
tg = {r['target_id']: r for r in csv.DictReader(open(f'{world}/public/targets.csv'))}
req = [t for t, r in tg.items() if r.get('required', '').lower() == 'true']
best = {}; nobs = {}
for o in csv.DictReader(open(f'{run}/observations.csv')):
    if o['valid'] != 'true':
        continue
    best[o['target_id']] = max(best.get(o['target_id'], 0.0), float(o['factor']))
    nobs[o['target_id']] = nobs.get(o['target_id'], 0) + 1
miss = [t for t in req if best.get(t, 0.0) < thr]

slots = list(csv.DictReader(open(f'{world}/truth/v4_weather_truth.csv')))
# zero-score / force-close events (terrain sectors, closures) as (start, end, az0, az1, alt0, alt1)
zev = []
for e in csv.DictReader(open(f'{world}/truth/v4_events.csv')):
    if e.get('zero_score') == 'true' or e.get('force_close') == 'true':
        a0 = float(e['azimuth_start_deg']) if e.get('azimuth_start_deg') else 0.0
        a1 = float(e['azimuth_end_deg']) if e.get('azimuth_end_deg') else 360.0
        h0 = float(e['min_altitude_deg']) if e.get('min_altitude_deg') else -90.0
        h1 = float(e['max_altitude_deg']) if e.get('max_altitude_deg') else 90.0
        allsky = e.get('scope_type', '') not in ('HORIZON_SECTOR', 'SECTOR', 'DIRECTIONAL')
        zev.append((pt(e['actual_start_utc']).timestamp(), pt(e['actual_end_utc']).timestamp(), a0, a1, h0, h1, allsky))
# 120 s samples over observable slots
st, qs, night = [], [], []
for s in slots:
    t0 = pt(s['timestamp_utc']); d = int(float(s['duration_seconds']))
    ok = s['is_observable'] == 'true'
    base = (float(s['instrument_efficiency']) * float(s['transparency']) * float(s['sky_quality']) / float(s['seeing_arcsec'])) if ok else 0.0
    for k in range(0, d, 120):
        st.append(t0 + timedelta(seconds=k + 60)); qs.append(base); night.append(s['night_id'])
qs = np.array(qs); night = np.array(night)
ts = np.array([x.timestamp() for x in st])
# local sidereal time (deg)
jd = ts / 86400.0 + 2440587.5
gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360.0
lst = np.radians((gmst + lon) % 360.0)
npc = tmax // 120
print(f'{world.split("/")[-1]}: required {len(req)} missed {len(miss)}')
nfeas = 0
for t in miss:
    r = tg[t]; f = float(r['feature_flux'])
    ra, dec = math.radians(float(r['ra_deg'])), math.radians(float(r['dec_deg']))
    ha = lst - ra
    alt = np.degrees(np.arcsin(np.sin(lat) * np.sin(dec) + np.cos(lat) * np.cos(dec) * np.cos(ha)))
    az = np.degrees(np.arctan2(-np.cos(dec) * np.sin(ha), np.sin(dec) * np.cos(lat) - np.cos(dec) * np.sin(lat) * np.cos(ha))) % 360.0
    blocked = np.zeros(len(ts), dtype=bool)
    for (e0, e1, a0, a1, h0, h1, allsky) in zev:
        inside_t = (ts >= e0) & (ts < e1)
        if allsky:
            blocked |= inside_t
            continue
        inaz = ((az - a0) % 360.0) <= ((a1 - a0) % 360.0)
        blocked |= inside_t & inaz & (alt >= h0) & (alt <= h1)
    up = alt >= min_alt
    am = np.array([_normalized_airmass(a) if a > 0 else 1e9 for a in alt])
    cand = np.flatnonzero(up & (qs > 0))
    lun = np.ones(len(ts))
    for i in cand:
        lun[i] = lunar_quality_factor(float(r['ra_deg']), float(r['dec_deg']), st[i], site, sc)
    q = np.where(up & ~blocked, qs * lun / am ** beta / q0, 0.0)
    # exposure windows of npc consecutive samples, contiguous in time and fully above the limit
    gbest, nights_ok = 0.0, set()
    wins = []
    contiguous = np.diff(ts) <= 121
    for i in cand:
        j = i + npc
        if j > len(ts) or not np.all(contiguous[i:j - 1]) or not np.all(up[i:j]):
            continue
        g = min(1.0, f * tmax * q[i:j].mean() / f0t0)
        gbest = max(gbest, g)
        if g >= thr:
            nights_ok.add(night[i])
            if verbose: wins.append((st[i].strftime('%m-%d %H:%M'), round(g, 2)))
    nfeas += gbest >= thr
    print(f'  {t} {r["target_class"]} flux {f:.4f} dec {float(r["dec_deg"]):6.1f} | run best {best.get(t, 0):.3f} nobs {nobs.get(t, 0)} '
          f'| oracle gmax {gbest:.3f} nights_ok {len(nights_ok)}')
    if verbose and wins:
        byn = {}
        for w in wins: byn.setdefault(w[0][:5], []).append(w)
        print('     windows:', ' '.join(f"{d}[{v[0][0][6:]}-{v[-1][0][6:]} g{max(x[1] for x in v)}]" for d, v in sorted(byn.items())))
print(f'  feasible-but-missed {nfeas} of {len(miss)}')
