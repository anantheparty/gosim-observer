#!/usr/bin/env python3
"""Summarize a local run: score components, fill rate, durations, g distribution, program match."""
import csv, json, sys
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np

EX = Path('/home/shu/kamico/observer/gosim-observer/formal_v4/upstream/gosim-observer-examples')


def card_dir(card):
    p = Path(card)
    return p if p.is_dir() else EX / 'local-cards' / card


def main(run_dir, card):
    run = Path(run_dir)
    rep = json.load(open(run / 'score_report.json'))
    targets = {r['target_id']: r for r in csv.DictReader(open(card_dir(card) / 'public/targets.csv'))}
    dec = list(csv.DictReader(open(run / 'decisions.csv')))
    obs = list(csv.DictReader(open(run / 'observations.csv')))
    wf = json.load(open(run / 'workflow_result.json')) if (run / 'workflow_result.json').exists() else {}
    print('TOTAL', rep['total'], rep['components'])
    print('counts', rep['counts'], 'termination', rep['termination'])
    observes = [d for d in dec if d['action'] == 'observe']
    waits = [d for d in dec if d['action'] == 'wait']
    dur = np.array([float(d['duration_seconds']) for d in observes])
    hits = np.array([int(d['hit_count']) for d in observes])
    assigned = np.array([int(d['assigned_count']) for d in observes])
    print(f'observes {len(observes)} total_exp_h {dur.sum()/3600:.1f} mean_dur {dur.mean():.0f} med {np.median(dur):.0f}')
    print(f'wait rows {len(waits)} wait_h {sum(float(d["duration_seconds"]) for d in waits)/3600:.1f}')
    print(f'assigned mean {assigned.mean():.2f} hits mean {hits.mean():.2f} hit/assigned {hits.sum()/max(1,assigned.sum()):.3f}')
    # first-observation (new target) per exposure
    seen = set(); new_per = defaultdict(int); score_by_obs = defaultdict(float)
    best = {}
    for o in obs:
        if o['valid'] != 'true':
            continue
        t = o['target_id']; s = float(o['score'])
        k = int(o['observe_index'])
        if t not in seen:
            new_per[k] += 1; seen.add(t)
    newc = np.array([new_per.get(int(d['observe_index']), 0) for d in observes])
    print(f'new targets per exposure mean {newc.mean():.2f}; first-third {newc[:len(newc)//3].mean():.2f} mid {newc[len(newc)//3:2*len(newc)//3].mean():.2f} last {newc[2*len(newc)//3:].mean():.2f}')
    # best factor per target
    bf = defaultdict(float); bs = defaultdict(float); bm = {}
    for o in obs:
        if o['valid'] != 'true':
            continue
        t = o['target_id']
        bf[t] = max(bf[t], float(o['factor']))
        if float(o['score']) >= bs[t]:
            bs[t] = float(o['score']); bm[t] = float(o['prog_mult'])
    cls_stats = defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])
    for t, r in targets.items():
        c = r['target_class']; w = float(r['science_weight'])
        cs = cls_stats[c]
        cs[0] += 1
        if t in bf:
            cs[1] += 1; cs[2] += bf[t]; cs[3] += bs[t]
        cs[4] += w * 1.2
    print('class  n  observed  mean_g(obs)  score  max(1.2w)')
    for c, (n, no, g, s, mx) in sorted(cls_stats.items()):
        print(f'  {c:5s} {n:5d} {no:5d} {g/max(1,no):.3f} {s:8.1f} {mx:8.1f}')
    mult = Counter(round(v, 2) for v in bm.values())
    print('prog mult of best:', dict(mult))
    req = [t for t, r in targets.items() if r['required'] == 'true']
    req_missing = [t for t in req if bf.get(t, 0) < 0.5]
    print('required', len(req), 'missing', len(req_missing), 'never observed', sum(1 for t in req_missing if t not in bf))
    for t in req_missing[:30]:
        r = targets[t]
        print('   miss', t, r['target_class'], 'flux', r['feature_flux'], 'dec', r['dec_deg'], 'ra', r['ra_deg'], 'bestg', round(bf.get(t, 0), 3))
    g = np.array(list(bf.values()))
    print('g hist (observed targets):', np.histogram(g, bins=[0, .25, .5, .75, .95, 1.01])[0].tolist())
    if wf:
        print('workflow', {k: wf.get(k) for k in ('termination_reason', 'elapsed_seconds', 'accounted_seconds', 'wallclock') if k in wf})


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
