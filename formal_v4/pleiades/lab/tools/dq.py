import csv, sys
import numpy as np
from collections import defaultdict
R, W = sys.argv[1], sys.argv[2]
tg = {r['target_id']: r for r in csv.DictReader(open(W + '/public/targets.csv'))}
dec = {int(d['observe_index']): d for d in csv.DictReader(open(R + '/decisions.csv')) if d['action'] == 'observe'}
ex = defaultdict(list); obs = defaultdict(list)
for o in csv.DictReader(open(R + '/observations.csv')):
    ex[int(o['observe_index'])].append(o)
    if o['valid'] == 'true':
        obs[o['target_id']].append((float(o['factor']), float(o['quality']), float(dec[int(o['observe_index'])]['duration_seconds'])))
rows = []
for t, r in tg.items():
    if r['target_class'] != 'QSO': continue
    f = float(r['feature_flux']); w = float(r['science_weight'])
    L = obs.get(t, [])
    bg = max([x[0] for x in L], default=0)
    if bg >= 0.999: continue
    rows.append((f, bg, max([x[1] for x in L], default=0), len(L), sum(1 for x in L if x[2] >= 3500), min(1, f * 3600 / 450), w))
a = np.array(rows)
print('incomplete QSOs', len(a), 'loss %.0f' % (np.sum((1 - a[:, 1]) * a[:, 6]) * 1.2), ' loss@Q1 %.0f' % (np.sum((1 - a[:, 5]) * a[:, 6]) * 1.2))
for lo, hi in ((0, .05), (.05, .1), (.1, .15), (.15, 1)):
    m = (a[:, 0] >= lo) & (a[:, 0] < hi)
    if m.sum(): print(f'  flux [{lo},{hi}) n {m.sum():4d} bestg {a[m,1].mean():.3f} bestQ {a[m,2].mean():.3f} att {a[m,3].mean():.1f} n3600 {a[m,4].mean():.1f} g@Q1 {a[m,5].mean():.3f}')
rec = []
for k, d in dec.items():
    L = ex.get(k, [])
    if not L: continue
    q = np.median([float(o['quality']) for o in L]); T = float(d['duration_seconds'])
    nf = sum(1 for o in L if tg[o['target_id']]['target_class'] == 'QSO' and float(tg[o['target_id']]['feature_flux']) < 0.15)
    nh = sum(1 for o in L if tg[o['target_id']]['target_class'] == 'QSO' and float(tg[o['target_id']]['feature_flux']) < 0.05)
    rec.append((k, q, T, len(L), nf, nh))
b0 = np.array(rec)
for i, part in enumerate(np.array_split(np.arange(len(b0)), 4)):
    b = b0[part]; hi = b[:, 1] > 1.1
    print(f'  q{i}: hours {b[:,2].sum()/3600:.0f} highQ {b[hi,2].sum()/3600:.0f} (faintQSO {b[hi & (b[:,4]>0),2].sum()/3600:.0f}) hopeless {b[(b[:,5]>0),2].sum()/3600:.0f}')
