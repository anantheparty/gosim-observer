#!/usr/bin/env python3
"""lossdec.py RUN WORLD : decompose science loss (w*1.2 - best score) into unobserved / partial-g / program."""
import csv, json, sys, collections
import numpy as np
run, world = sys.argv[1], sys.argv[2]
sc = json.load(open(f'{world}/config/v4_score_config.json'))
mult = sc['program']['multipliers']; mm = sc['program']['mismatch_multiplier']
tg = {r['target_id']: r for r in csv.DictReader(open(f'{world}/public/targets.csv'))}
best = {}; bestg = {}; bestpm = {}; nobs = collections.Counter()
for o in csv.DictReader(open(f'{run}/observations.csv')):
    if o['valid'] != 'true': continue
    t = o['target_id']; s = float(o['score']); nobs[t] += 1
    bestg[t] = max(bestg.get(t, 0), float(o['factor']))
    if s >= best.get(t, -1): best[t] = s; bestpm[t] = float(o['prog_mult'])
mx = max(mult.values())
tot = sum(float(r['science_weight']) * mx for r in tg.values())
got = sum(best.values())
print(f'targets {len(tg)} observed {len(best)} max {tot:.0f} got {got:.0f} ({got/tot:.3f}) mult {mult} mismatch {mm}')
L = collections.defaultdict(float)
byra = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0, 0])
bycls = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0, 0])
for t, r in tg.items():
    w = float(r['science_weight']); ra = float(r['ra_deg'])
    k = int(ra // 30) * 30
    c = r['target_class']
    if t not in best:
        L['unobserved'] += w * mx; byra[k][0] += w * mx; byra[k][3] += 1; bycls[c][0] += w*mx; bycls[c][3] += 1
        continue
    g = bestg[t]; s = best[t]; pm = bestpm[t]
    # split: program loss (at achieved g) and g loss
    lp = w * g * (mx - pm); lg = w * mx * (1 - g)
    # s = w*g'*pm where best by score may differ from best g; approximate
    L['partial_g'] += lg; L['program'] += max(0.0, w * mx - s - lg)
    byra[k][1] += lg; byra[k][2] += max(0.0, w * mx - s - lg); byra[k][4] += 1
    bycls[c][1] += lg; bycls[c][2] += max(0.0, w*mx - s - lg); bycls[c][4] += 1
for k, v in L.items(): print(f'  {k:12s} {v:8.0f}')
print(' RA band   unobs_loss  partial  prog  n_unobs n_obs')
for k in sorted(byra): v = byra[k]; print(f'  {k:3d}-{k+30:3d} {v[0]:9.0f} {v[1]:8.0f} {v[2]:6.0f} {v[3]:6d} {v[4]:6d}')
print(' class  unobs_loss partial prog n_unobs n_obs')
for k in sorted(bycls): v = bycls[k]; print(f'  {k:5s} {v[0]:9.0f} {v[1]:8.0f} {v[2]:6.0f} {v[3]:6d} {v[4]:6d}')
# g distribution of observed
gs = np.array([bestg[t] for t in best])
print('best g quantiles', np.round(np.quantile(gs, [0.05, 0.1, 0.25, 0.5]), 3), 'frac g<1', round((gs < 0.999).mean(), 3))
pms = collections.Counter(bestpm.values()); print('best prog_mult', dict(pms))
