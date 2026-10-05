#!/usr/bin/env python3
"""Event-mix robustness worlds: gen_weird.py plus EVENT_PATCH, a JSON object of dotted weather-config keys
(e.g. {"instrument_fault.count": 5, "weather_events.conditions.rainy.count": 18}) applied after the reference
(or stress) weather config is loaded. The same NAME/TYPE/SEED/MONTH_SHIFT without a patch gives the twin world
with the reference event mix (same catalogue, site, season and base weather streams).
usage: gen_event.py NAME TYPE(A|B|C|D) SEED MONTH_SHIFT"""
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
for key, val in json.loads(E('EVENT_PATCH') or '{}').items():
    node = weather
    parts = key.split('.')
    for p in parts[:-1]:
        node = node[p]
    if parts[-1] not in node:
        raise KeyError(key)
    node[parts[-1]] = val
spec = Path('/home/shu/kamico/observer/work/hspec') / name
if spec.exists():
    shutil.rmtree(spec)
spec.mkdir(parents=True)
(spec / 'card.json').write_text(json.dumps({'name': name, 'card_id': name, 'scenario_slug': name, 'phase': 'local',
                                             'stress': stress, 'wallclock_seconds': 900}))
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
print('built', root, typ, start, end, nights, 'comps', ncomp, cat['footprint']['component_centers'])
