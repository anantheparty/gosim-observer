#!/usr/bin/env python3
"""cmpv5.py : c26 vs c27 on the V5 (A1-D1-like) worlds, local (runs/) and remote (rruns/)."""
import json, os

WORLDS = ['V5A', 'V5B', 'V5B2', 'V5C', 'V5C2', 'V5D']


def load(base, ver, w):
    f = f'{base}/v5{ver}/{w}/summary.json'
    if not os.path.exists(f):
        return None
    return json.load(open(f))


def levels(base, w):
    f = f'{base}/v5c27/{w}/log.txt'
    out = []
    if os.path.exists(f):
        for line in open(f):
            if '"eng_level"' in line:
                e = json.loads(line)
                out.append((e['t'][:10], e['level']))
    return out


for base in ('runs', 'rruns'):
    print(f'== {base}')
    for w in WORLDS:
        a, b = load(base, 'c26', w), load(base, 'c27', w)
        row = f'{w:5s}'
        for tag, s in (('c26', a), ('c27', b)):
            if s is None:
                row += f' | {tag} -'
                continue
            row += (f" | {tag} {s['total']:8.0f} sci {s['sum_best_scores']:6.0f} req {s['observation_request_reward']:5.0f} "
                    f"miss {s['required_missing']:3d} {'CUT' if s.get('wall_expired') else 'ok '} wall {s['wall']:6.0f} pol {s['policy_cpu']:5.0f}")
        if a and b:
            row += f" | d {b['total'] - a['total']:+7.0f}"
        print(row)
        lv = levels(base, w)
        if lv:
            print('      levels', lv[:12])
