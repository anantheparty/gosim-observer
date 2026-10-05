#!/usr/bin/env python3
"""waste.py RUN_DIR WORLD_DIR : fibre-time partition (useful / saturated / superseded / empty) and dark-time use."""
import csv, json, sys
from collections import defaultdict
from datetime import datetime, timezone
import numpy as np

def pt(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()

run, world = sys.argv[1], sys.argv[2]
sc = json.load(open(f'{world}/config/v4_score_config.json'))
fc = json.load(open(f'{world}/config/v4_fiber_config.json'))
F = fc['field']['n_fibers']
f0t0 = sc['flux_zero_point'] * sc['exposure_zero_point_seconds']
tg = {r['target_id']: r for r in csv.DictReader(open(f'{world}/public/targets.csv'))}
dec = [d for d in csv.DictReader(open(f'{run}/decisions.csv'))]
obsd = [d for d in dec if d['action'] == 'observe']
T = {int(d['observe_index']): float(d['duration_seconds']) for d in obsd}
nassg = {int(d['observe_index']): int(d['assigned_count']) for d in obsd}
obs = [o for o in csv.DictReader(open(f'{run}/observations.csv')) if o['valid'] == 'true']
best = {}
for o in obs:
    s = float(o['score']); t = o['target_id']
    if t not in best or s > best[t][0]:
        best[t] = (s, int(o['observation_id']))
use = sat = sup = 0.0
for o in obs:
    k = int(o['observe_index']); t = o['target_id']; Tk = T[k]
    f = float(tg[t]['feature_flux']); q = float(o['quality'])
    graw = f * Tk * q / f0t0
    if best[t][1] != int(o['observation_id']):
        sup += Tk
    elif graw > 1:
        use += Tk / graw; sat += Tk - Tk / graw
    else:
        use += Tk
empty = sum((F - nassg[k]) * T[k] for k in T)
tot = F * sum(T.values())
print(f'fibre-time: useful {use/tot:.3f} saturated {sat/tot:.3f} superseded {sup/tot:.3f} empty {empty/tot:.3f}  (exp h {sum(T.values())/3600:.0f})')
# dark time use
cal = list(csv.DictReader(open(f'{world}/public/v4_night_calendar.csv')))
dark = sum(pt(c['observing_end_utc']) - pt(c['observing_start_utc']) for c in cal)
ns = np.array([pt(c['observing_start_utc']) for c in cal]); ne = np.array([pt(c['observing_end_utc']) for c in cal])
inwait = 0.0
for d in dec:
    if d['action'] != 'wait':
        continue
    a, b = pt(d['start_utc']), pt(d['end_utc'])
    inwait += float(np.sum(np.maximum(0, np.minimum(b, ne) - np.maximum(a, ns))))
print(f'dark h {dark/3600:.0f}  exposure {sum(T.values())/dark:.3f}  wait-in-night {inwait/dark:.3f}  nights {len(cal)}')
# per-third fill and duration
ks = sorted(T)
for i, part in enumerate(np.array_split(np.array(ks), 3)):
    print(f'  third {i}: n {len(part)} fill {np.mean([nassg[k] for k in part])/F:.3f} meanT {np.mean([T[k] for k in part]):.0f}')
# value left: incomplete targets by class
left = defaultdict(float); mx = defaultdict(float)
for t, r in tg.items():
    w = float(r['science_weight']); c = r['target_class']
    mx[c] += 1.2 * w
    left[c] += 1.2 * w - best.get(t, (0,))[0]
print('left by class', {c: round(left[c]) for c in sorted(left)}, 'of', {c: round(mx[c]) for c in sorted(mx)})
fl = defaultdict(list)
for t, r in tg.items():
    fl[r['target_class']].append(float(r['feature_flux']))
print('flux median by class', {c: round(float(np.median(v)), 3) for c, v in sorted(fl.items())}, ' Tsat@Q=1 med', {c: round(f0t0 / float(np.median(v))) for c, v in sorted(fl.items())})
