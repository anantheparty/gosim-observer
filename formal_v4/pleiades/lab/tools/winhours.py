#!/usr/bin/env python3
"""winhours.py RUN WORLD : per 10-night window, available good hours of targets grouped by their season S,
and what the run observed (new targets) from each group."""
import csv, sys, collections, io, contextlib
import numpy as np
sys.path.insert(0, '/home/shu/kamico/observer/gosim-observer/formal_v4/upstream/gosim-observer-examples/runner')
sys.path.insert(0, '/home/shu/kamico/observer/work/obs3')
from pathlib import Path
from challenge.v4_workflow import V4Workflow
import policy
from astro import parse_utc
run, world = sys.argv[1], sys.argv[2]
with contextlib.redirect_stderr(io.StringIO()):
    P = policy.Policy(V4Workflow(Path(world)).initialize_payload(900), params={})
N = len(P.nights)
H = np.zeros((N, P.n), dtype=np.float32)
for k, (a, b) in enumerate(P.nights):
    H[k] = P._good_hours(a, b)
S = H.sum(axis=0)
grp = np.digitize(S, [40, 160, 400])   # 0: <40, 1: 40-160, 2: 160-400, 3: >=400
names = ['S<40', '40-160', '160-400', '>=400']
dec = {d['observe_index']: d for d in csv.DictReader(open(f'{run}/decisions.csv')) if d['action'] == 'observe'}
first = {}
for o in csv.DictReader(open(f'{run}/observations.csv')):
    if o['valid'] == 'true' and o['target_id'] not in first:
        first[o['target_id']] = parse_utc(dec[o['observe_index']]['start_utc'])
obs_night = np.full(P.n, -1)
for t, ts in first.items():
    i = P.index[t]; obs_night[i] = max(0, int(np.searchsorted(P.night_starts, ts, side='right')) - 1)
W = 10
print('targets per group', [int((grp == g).sum()) for g in range(4)], ' unobserved', [int(((grp == g) & (obs_night < 0)).sum()) for g in range(4)])
print('win   ' + ''.join(f'{n:>22s}' for n in names) + '   (avail target-hours / new targets observed)')
for k0 in range(0, N, W):
    hh = H[k0:k0 + W].sum(axis=0)
    row = []
    for g in range(4):
        m = grp == g
        nn = int(((obs_night >= k0) & (obs_night < k0 + W) & m).sum())
        row.append(f'{hh[m].sum():12.0f} / {nn:6d}')
    print(f'{k0:3d}  ' + '  '.join(row))
