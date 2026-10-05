#!/usr/bin/env python3
"""gainsplit.py RUN WORLD : per 1/6 of season: exposure hours, score gain from first observations vs repeats, fill."""
import csv, sys, collections
import numpy as np
run, world = sys.argv[1], sys.argv[2]
tg = {r['target_id']: r for r in csv.DictReader(open(f'{world}/public/targets.csv'))}
dec = [d for d in csv.DictReader(open(f'{run}/decisions.csv')) if d['action'] == 'observe']
obs = collections.defaultdict(list)
for o in csv.DictReader(open(f'{run}/observations.csv')):
    if o['valid'] == 'true':
        obs[o['observe_index']].append(o)
best = {}
K = 6; n = len(dec)
rows = [[0.0, 0.0, 0.0, 0, 0, 0, 0] for _ in range(K)]
for i, d in enumerate(dec):
    k = min(K - 1, i * K // n)
    r = rows[k]
    r[0] += float(d['duration_seconds']) / 3600
    r[6] += 1
    for o in obs.get(d['observe_index'], []):
        t = o['target_id']; s = float(o['score'])
        if t not in best:
            r[1] += s; r[3] += 1; best[t] = s
        else:
            gain = max(0.0, s - best[t]); r[2] += gain; r[4] += 1
            if gain > 0: r[5] += 1
            best[t] = max(best[t], s)
print('part  exp_h   new_gain  rep_gain  n_new  n_rep  rep_improved  gain/h  fill')
for k, r in enumerate(rows):
    print(f'{k}  {r[0]:7.1f} {r[1]:9.0f} {r[2]:9.0f} {r[3]:6d} {r[4]:6d} {r[5]:6d}  {(r[1]+r[2])/max(r[0],1e-9):7.1f} {(r[3]+r[4])/max(r[6],1):5.1f}')
