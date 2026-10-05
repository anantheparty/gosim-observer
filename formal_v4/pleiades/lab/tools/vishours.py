#!/usr/bin/env python3
"""vishours.py RUN WORLD : season good-altitude hours (policy's own S) for observed vs unobserved targets."""
import csv, json, sys, collections, os
import numpy as np
sys.path.insert(0, '/home/shu/kamico/observer/gosim-observer/formal_v4/upstream/gosim-observer-examples/runner')
sys.path.insert(0, '/home/shu/kamico/observer/work/obs3')
from pathlib import Path
from challenge.v4_workflow import V4Workflow
import policy
run, world = sys.argv[1], sys.argv[2]
wf = V4Workflow(Path(world))
payload = wf.initialize_payload(900)
P = policy.Policy(payload, params={})
S = P.hours_suffix[0].astype(float)
tg = list(csv.DictReader(open(f'{world}/public/targets.csv')))
best = {}
for o in csv.DictReader(open(f'{run}/observations.csv')):
    if o['valid'] == 'true':
        best[o['target_id']] = max(best.get(o['target_id'], 0), float(o['factor']))
ids = P.ids
byc = collections.defaultdict(lambda: ([], []))
for i, t in enumerate(ids):
    c = tg[i]['target_class'] if tg[i]['target_id'] == t else None
    byc[c][0 if t in best else 1].append(S[i])
print('S = season good-altitude hours (policy), quantiles 10/25/50/75')
for c, (o, u) in sorted(byc.items()):
    o, u = np.array(o), np.array(u)
    print(f' {c:5s} observed n={len(o):5d} S {np.round(np.quantile(o,[.1,.25,.5,.75]),1)} | unobserved n={len(u):5d} S {np.round(np.quantile(u,[.1,.25,.5,.75]),1) if len(u) else "-"}')
# unobserved count by S bucket
bins = [0, 5, 10, 20, 40, 80, 160, 1e9]
allS = np.array([S[i] for i in range(len(ids))]); obsd = np.array([ids[i] in best for i in range(len(ids))])
for a, b in zip(bins[:-1], bins[1:]):
    m = (allS >= a) & (allS < b)
    print(f'  S in [{a:4.0f},{b:5.0f}) n={m.sum():6d} unobserved {(~obsd[m]).sum():5d} ({(~obsd[m]).mean() if m.sum() else 0:.2f})')
