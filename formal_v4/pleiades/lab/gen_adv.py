#!/usr/bin/env python3
"""Adversarial worlds (round 2): gen_event.py plus SCORE_PATCH / FIBER_PATCH / CAT_PATCH (dotted keys of the score,
fibre and catalogue configs), REQ (card.json observation_requests settings), STRESS_ROWS (explicit rows of
v4_stress_events.csv, enables stress) and TARGET_EDIT (python expression applied to each targets.csv row r with
rng = random.Random(seed), after generation). Without any of them the world equals gen_event.py's.
Event-mix robustness worlds: gen_weird.py plus EVENT_PATCH, a JSON object of dotted weather-config keys
(e.g. {"instrument_fault.count": 5, "weather_events.conditions.rainy.count": 18}) applied after the reference
(or stress) weather config is loaded. The same NAME/TYPE/SEED/MONTH_SHIFT without a patch gives the twin world
with the reference event mix (same catalogue, site, season and base weather streams).
usage: gen_adv.py NAME TYPE(A|B|C|D) SEED MONTH_SHIFT"""
import os
import sys, json, random, datetime, shutil
from pathlib import Path
sys.path.insert(0, '/home/shu/kamico/observer/hackathon-survey26')
from challenge.v4_bundle import build_spec_bundle
name, typ, seed, shift = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
REF = Path('/home/shu/kamico/observer/hackathon-survey26/challenge/reference/v4')
FC = Path('/home/shu/kamico/observer/gosim-observer/formal_v4/formal_cards') / typ / typ.lower()
rng = random.Random(seed)
fiber = json.loads((FC / 'config/v4_fiber_config.json').read_text())
score = json.loads((FC / 'config/v4_score_config.json').read_text())
site = fiber['site']
E = os.environ.get
if E('WEIRD_LAT'): site['latitude_deg'] = float(E('WEIRD_LAT'))
if E('WEIRD_LON'): site['longitude_deg'] = float(E('WEIRD_LON')); site['utc_offset_hours'] = round(float(E('WEIRD_LON')) / 15.0)
if E('WEIRD_NFIB'): fiber['field']['n_fibers'] = int(E('WEIRD_NFIB'))
if E('WEIRD_AREA'): fiber['field']['fiber_area_deg2'] = float(E('WEIRD_AREA'))
if E('WEIRD_GAP'): fiber['field']['gap_deg'] = float(E('WEIRD_GAP'))
if E('WEIRD_TMIN'): fiber['exposure']['min_duration_seconds'] = int(E('WEIRD_TMIN'))
if E('WEIRD_TMAX'): fiber['exposure']['max_duration_seconds'] = int(E('WEIRD_TMAX'))
cal = (FC / 'public/v4_night_calendar.csv').read_text().splitlines()[1:]
first = datetime.date.fromisoformat(cal[0].split(',')[1]); nights = int(E('WEIRD_NIGHTS') or len(cal))
start = (first.replace(day=1) + datetime.timedelta(days=31 * shift)).replace(day=1)
if E('WEIRD_START'):
    start = datetime.date.fromisoformat(E('WEIRD_START'))
end = start + datetime.timedelta(days=nights)
n_targets = int(E('WEIRD_NT') or {'A': 30000, 'B': 50000, 'C': 30000, 'D': 30000}[typ])
area = {'A': 6000.0, 'B': 8000.0, 'C': 4150.0, 'D': 6100.0}[typ]
cat = json.loads((REF / 'v4_catalog_config.json').read_text())
cat['seed'] = seed
cat['site'] = dict(site)
cat['footprint']['total_area_deg2'] = area
lat = site['latitude_deg']
ncomp = rng.choice([2, 2, 3])
w = [rng.uniform(0.5, 1.5) for _ in range(ncomp)]
cat['footprint']['n_components'] = ncomp
cat['footprint']['component_area_weights'] = [round(x / sum(w), 3) for x in w]
cat['footprint']['component_area_weights'][-1] = round(1 - sum(cat['footprint']['component_area_weights'][:-1]), 3)
_mid = start + datetime.timedelta(days=nights // 2)
_sun_ra = (280.46 + 0.9856474 * ((_mid - datetime.date(2000, 1, 1)).days + 0.5)) % 360.0
_anti = (_sun_ra + 180.0) % 360.0
_span = 200.0 if ncomp == 2 else 230.0
def _centres():
    return [[round((_anti - _span / 2 + (k + 0.5) * _span / ncomp + rng.uniform(-6, 6)) % 360, 1), round(max(-75, min(75, lat + rng.uniform(-28, 28))), 1)] for k in range(ncomp)]
cat['footprint']['component_centers'] = _centres()
cat['footprint']['harmonic_amplitude_ranges'] = cat['footprint']['harmonic_amplitude_ranges'][:3]
cat['targets']['total_count'] = n_targets
import csv as _csv, statistics as _st
_fl = {}
for _r in _csv.DictReader(open(FC / 'public/targets.csv')):
    _fl.setdefault(_r['target_class'], []).append(float(_r['feature_flux']))
for c, m in cat['targets']['models'].items():
    base = _st.median(_fl[c]) if c in _fl else m['flux_median']
    m['flux_median'] = round(base * rng.uniform(0.8, 1.25), 3)
cat['observability'].update(start_date=start.isoformat(), end_date=end.isoformat())
stress = (typ == 'D') if not E('WEIRD_STRESS') else E('WEIRD_STRESS') == '1'
weather = json.loads((REF / ('v4_weather_stress_config.json' if stress else 'v4_weather_config.json')).read_text())
weather['seed'] = seed + 7
weather['site'] = dict(site)
weather['survey'].update(start_date=start.isoformat(), end_date=end.isoformat())
def _patch(cfg, env):
    for key, val in json.loads(E(env) or '{}').items():
        add = key.startswith('+')
        key = key.lstrip('+')
        node = cfg
        parts = key.split('.')
        for p in parts[:-1]:
            node = node[p]
        if parts[-1] not in node and not add:
            raise KeyError(key)
        node[parts[-1]] = val
_patch(weather, 'EVENT_PATCH')
_patch(score, 'SCORE_PATCH')
_patch(fiber, 'FIBER_PATCH')
_patch(cat, 'CAT_PATCH')
spec = Path('/home/shu/kamico/observer/work/hspec') / name
if spec.exists():
    shutil.rmtree(spec)
spec.mkdir(parents=True)
_card = {'name': name, 'card_id': name, 'scenario_slug': name, 'phase': 'local', 'stress': stress,
         'wallclock_seconds': int(E('WALL') or 900)}
if E('REQ'):
    _card['observation_requests'] = json.loads(E('REQ'))
(spec / 'card.json').write_text(json.dumps(_card))
(spec / 'v4_catalog_config.json').write_text(json.dumps(cat, indent=1))
(spec / 'v4_weather_config.json').write_text(json.dumps(weather, indent=1))
(spec / 'v4_fiber_config.json').write_text(json.dumps(fiber, indent=1))
(spec / 'v4_score_config.json').write_text(json.dumps(score, indent=1))
root = Path('/home/shu/kamico/observer/work/worlds') / name
for attempt in range(30):
    if root.exists():
        shutil.rmtree(root)
    try:
        build_spec_bundle(root, spec)
        break
    except RuntimeError as exc:
        print('retry', attempt, str(exc)[:80])
        cat['footprint']['component_centers'] = _centres()
        cat['seed'] = cat['seed'] + 1000
        (spec / 'v4_catalog_config.json').write_text(json.dumps(cat, indent=1))
else:
    sys.exit(f'build failed after 30 attempts: {name}')
print('built', root, typ, start, end, nights, 'comps', ncomp, cat['footprint']['component_centers'])

import csv
if E('STRESS_ROWS'):
    rows = json.loads(E('STRESS_ROWS'))
    cols = ['event_id', 'event_type', 'trigger_mode', 'trigger_ref', 'window_start_fraction', 'window_end_fraction',
            'window_max_fraction', 'alt_offset_rad', 'az_offset_rad']
    with open(root / 'truth/v4_stress_events.csv', 'w', newline='') as f:
        wr = csv.writer(f, lineterminator='\n')
        wr.writerow(cols)
        for k, r in enumerate(rows):
            wr.writerow([r.get(c, f'V4ST{k + 1:04d}' if c == 'event_id' else '') for c in cols])
    scp = root / 'config/v4_scenario.json'
    sc = json.loads(scp.read_text())
    sc['stress'] = {'enabled': True, 'stress_events_csv': '../truth/v4_stress_events.csv'}
    scp.write_text(json.dumps(sc, indent=2, sort_keys=True))
    print('stress rows', rows)
if E('TARGET_EDIT'):
    tp = root / 'public/targets.csv'
    with open(tp) as f:
        rd = csv.DictReader(f)
        cols, rows = rd.fieldnames, list(rd)
    trng = random.Random(seed)
    for r in rows:
        exec(E('TARGET_EDIT'), {'r': r, 'rng': trng, 'math': __import__('math')})
    with open(tp, 'w', newline='') as f:
        wr = csv.DictWriter(f, fieldnames=cols, lineterminator='\n')
        wr.writeheader()
        wr.writerows(rows)
    print('targets edited', len(rows))

if E('TARGET_ADD'):
    tp = root / 'public/targets.csv'
    with open(tp) as f:
        rd = csv.DictReader(f)
        cols, rows = rd.fieldnames, list(rd)
    for r in json.loads(E('TARGET_ADD')):
        rows.append({c: str(r.get(c, '')) for c in cols})
    with open(tp, 'w', newline='') as f:
        wr = csv.DictWriter(f, fieldnames=cols, lineterminator='\n')
        wr.writeheader()
        wr.writerows(rows)
    print('targets added', len(json.loads(E('TARGET_ADD'))))
if E('REQ_V5'):
    # A1-D1-like request streams: groups {count, ntargets[], min, reward, window[days lo, hi]} issued at random
    # times inside observing windows; targets above the altitude limit (+5 deg) at issue time, 30 min later or at
    # the deadline (bounded by the night end). Appended to the generator's own stream.
    sys.path.insert(0, '/home/shu/kamico/observer/work/pkgs/c25')
    import astro as _astro
    spec = json.loads(E('REQ_V5'))
    rp = root / 'truth/v4_observation_requests.jsonl'
    reqs = [json.loads(l) for l in rp.read_text().splitlines() if l.strip()] if rp.exists() else []
    thr = score['observation_requests']['completion_factor_threshold']
    _nc = list(csv.DictReader(open(root / 'public/v4_night_calendar.csv')))
    _tg = [r for r in csv.DictReader(open(root / 'public/targets.csv')) if r['required'].lower() != 'true']
    qr = random.Random(seed + 77)
    qr.shuffle(_tg)
    _minalt = cat['observability']['minimum_altitude_deg']
    _la, _lo = site['latitude_deg'], site['longitude_deg']
    _used = {t for r in reqs for t in r['target_ids']}
    k = len(reqs)
    for g in spec['groups']:
        for _ in range(int(g['count'])):
            n = qr.choice(_nc)
            a_, b_ = _astro.parse_utc(n['observing_start_utc']), _astro.parse_utc(n['observing_end_utc'])
            t_iss = a_ + qr.uniform(0.0, max(0.0, b_ - a_ - 3600.0))
            lo_, hi_ = g.get('window', [0.12, 2.0])
            t_dl = t_iss + qr.uniform(lo_, hi_) * 86400.0
            t_dl = min(t_dl, _astro.parse_utc(_nc[-1]['observing_end_utc']))
            if t_dl <= t_iss + 600.0:
                t_iss = max(_astro.parse_utc(_nc[0]['observing_start_utc']), t_dl - 3 * 3600.0)
            nt = qr.choice(g['ntargets'])
            sel = []
            for r in _tg:
                if r['target_id'] in _used:
                    continue
                ra_, de_ = float(r['ra_deg']), float(r['dec_deg'])
                if max(_astro.alt_scalar(ra_, de_, t, _la, _lo) for t in (t_iss, t_iss + 1800.0, min(t_dl, b_))) >= _minalt + 5.0:
                    sel.append(r['target_id'])
                    _used.add(r['target_id'])
                    if len(sel) == nt:
                        break
            if not sel:
                continue
            k += 1
            reqs.append({'schema_version': 'v4-observation-request-v1', 'record_type': 'observation_request',
                         'request_id': f'V4RQ{k:04d}', 'issued_at_utc': _astro.fmt_utc(t_iss), 'deadline_utc': _astro.fmt_utc(t_dl),
                         'target_ids': sel, 'minimum_completed': max(1, min(int(g['min']), len(sel))),
                         'completion_factor_threshold': thr, 'completion_reward': float(g['reward']),
                         'reason': g.get('reason', 'follow-up')})
    reqs.sort(key=lambda r: r['issued_at_utc'])
    rp.write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in reqs))
    print('requests now', len(reqs), 'rewarded', sum(1 for r in reqs if r['completion_reward'] > 0))
if E('REQ_ADD'):
    rp = root / 'truth/v4_observation_requests.jsonl'
    reqs = [json.loads(l) for l in rp.read_text().splitlines() if l.strip()] if rp.exists() else []
    thr = score['observation_requests']['completion_factor_threshold']
    for k, r in enumerate(json.loads(E('REQ_ADD'))):
        reqs.append({'schema_version': 'v4-observation-request-v1', 'record_type': 'observation_request',
                     'request_id': r.get('request_id', f'V4RQX{k + 1:03d}'), 'issued_at_utc': r['issued_at_utc'],
                     'deadline_utc': r['deadline_utc'], 'target_ids': r['target_ids'],
                     'minimum_completed': int(r.get('minimum_completed', len(r['target_ids']))),
                     'completion_factor_threshold': thr, 'completion_reward': float(r['completion_reward']),
                     'reason': r.get('reason', 'time-critical follow-up')})
    reqs.sort(key=lambda r: r['issued_at_utc'])
    rp.write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in reqs))
    print('requests now', len(reqs))
