#!/usr/bin/env python3
"""cmpruns.py WORLD RUN_A RUN_B : science score difference (B - A) by RA band and by season-hours group."""
import csv, json, sys, collections, io, contextlib
import numpy as np
sys.path.insert(0, '/home/shu/kamico/observer/gosim-observer/formal_v4/upstream/gosim-observer-examples/runner')
sys.path.insert(0, '/home/shu/kamico/observer/work/obs3')
from pathlib import Path
from challenge.v4_workflow import V4Workflow
import policy
world, ra_, rb_ = sys.argv[1], sys.argv[2], sys.argv[3]
with contextlib.redirect_stderr(io.StringIO()):
    P = policy.Policy(V4Workflow(Path(world)).initialize_payload(900), params={})
S = P.hours_suffix[0].astype(float)
def best(run):
    b = {}
    for o in csv.DictReader(open(f'{run}/observations.csv')):
        if o['valid'] == 'true':
            b[o['target_id']] = max(b.get(o['target_id'], 0.0), float(o['score']))
    return b
A, B = best(ra_), best(rb_)
tg = {r['target_id']: r for r in csv.DictReader(open(f'{world}/public/targets.csv'))}
byra = collections.defaultdict(lambda: [0.0, 0, 0]); bys = collections.defaultdict(lambda: [0.0, 0, 0]); bycl = collections.defaultdict(lambda: [0.0, 0, 0])
for i, t in enumerate(P.ids):
    d = B.get(t, 0.0) - A.get(t, 0.0)
    k = int(P.ra[i] // 30) * 30
    g = ['S<40', '40-160', '160-400', '>=400'][int(np.digitize(S[i], [40, 160, 400]))]
    c = tg[t]['target_class']
    for D, key in ((byra, k), (bys, g), (bycl, c)):
        D[key][0] += d; D[key][1] += (t in B) - (t in A)
print(f'total sci diff {sum(B.values()) - sum(A.values()):+.0f}  observed {len(A)} -> {len(B)}')
print(' RA:', '  '.join(f'{k}:{v[0]:+.0f}({v[1]:+d})' for k, v in sorted(byra.items())))
print(' S :', '  '.join(f'{k}:{v[0]:+.0f}({v[1]:+d})' for k, v in sorted(bys.items(), key=lambda x: ['S<40','40-160','160-400','>=400'].index(x[0]))))
print(' cls:', '  '.join(f'{k}:{v[0]:+.0f}({v[1]:+d})' for k, v in sorted(bycl.items())))
