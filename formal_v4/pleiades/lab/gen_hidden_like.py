#!/usr/bin/env python3
"""Hidden-card-like worlds: A–D instrument/site/score configs, new targets/sky/season/weather.
usage: gen_hidden_like.py NAME TYPE(A|B|C|D) SEED MONTH_SHIFT"""
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
cal = (FC / 'public/v4_night_calendar.csv').read_text().splitlines()[1:]
first = datetime.date.fromisoformat(cal[0].split(',')[1]); nights = len(cal)
start = (first.replace(day=1) + datetime.timedelta(days=31 * shift)).replace(day=1)
end = start + datetime.timedelta(days=nights)
n_targets = {'A': 30000, 'B': 50000, 'C': 30000, 'D': 30000}[typ]
area = {'A': 6000.0, 'B': 8000.0, 'C': 4150.0, 'D': 6100.0}[typ]
cat = json.loads((REF / 'v4_catalog_config.json').read_text())
cat['seed'] = seed
cat['site'] = dict(site)
cat['footprint']['total_area_deg2'] = area
lat = site['latitude_deg']
ncomp = rng.choice([2, 3, 4])
w = [rng.uniform(0.5, 1.5) for _ in range(ncomp)]
cat['footprint']['n_components'] = ncomp
cat['footprint']['component_area_weights'] = [round(x / sum(w), 3) for x in w]
cat['footprint']['component_area_weights'][-1] = round(1 - sum(cat['footprint']['component_area_weights'][:-1]), 3)
ra0 = rng.uniform(0, 360)
cat['footprint']['component_centers'] = [[round((ra0 + k * 360.0 / ncomp + rng.uniform(-15, 15)) % 360, 1), round(max(-75, min(75, lat + rng.uniform(-30, 30))), 1)] for k in range(ncomp)]
cat['footprint']['harmonic_amplitude_ranges'] = cat['footprint']['harmonic_amplitude_ranges'][:3]
cat['targets']['total_count'] = n_targets
for c, m in cat['targets']['models'].items():
    m['flux_median'] = round(m['flux_median'] * rng.uniform(0.7, 1.5), 3)
cat['observability'].update(start_date=start.isoformat(), end_date=end.isoformat())
stress = typ == 'D'
weather = json.loads((REF / ('v4_weather_stress_config.json' if stress else 'v4_weather_config.json')).read_text())
weather['seed'] = seed + 7
weather['site'] = dict(site)
weather['survey'].update(start_date=start.isoformat(), end_date=end.isoformat())
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
        ra0 = rng.uniform(0, 360)
        cat['footprint']['component_centers'] = [[round((ra0 + k * 360.0 / ncomp + rng.uniform(-15, 15)) % 360, 1), round(max(-75, min(75, lat + rng.uniform(-30, 30))), 1)] for k in range(ncomp)]
        cat['seed'] = cat['seed'] + 1000
        (spec / 'v4_catalog_config.json').write_text(json.dumps(cat, indent=1))
print('built', root, typ, start, end, nights, 'comps', ncomp, cat['footprint']['component_centers'])
