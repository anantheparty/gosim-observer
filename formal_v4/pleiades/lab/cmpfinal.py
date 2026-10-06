#!/usr/bin/env python3
"""cmpfinal.py : final c27 (remote rruns/v5f) against the references on the same machine with the 1800 s cap
(rruns/v5c26, rruns/v5c26cap) and the uncapped regression runs (rruns/c25, runs/c25u, runs/c25)."""
import json, os


def s(p):
    f = p + '/summary.json'
    return json.load(open(f)) if os.path.exists(f) else None


def levels(p):
    f = p + '/log.txt'
    out = []
    if os.path.exists(f):
        for line in open(f):
            if '"eng_level"' in line:
                e = json.loads(line)
                out.append((e['t'][5:10], e['level']))
    return out


for w in ('V5B', 'V5B2', 'V5D', 'V5C2', 'FB1', 'FB2', 'FB4', 'HN2', 'HF4'):
    f = s(f'rruns/v5f/{w}')
    row = f'{w:5s} '
    if f:
        row += f"c27f {f['total']:8.0f} {'CUT' if f.get('wall_expired') else 'ok '} wall {f['wall']:5.0f} req {f['observation_request_reward']:5.0f} miss {f['required_missing']:3d}"
    else:
        row += 'c27f -'
    for tag, p in (('c26cap', f'rruns/v5c26cap/{w}'), ('c26V5', f'rruns/v5c26/{w}'), ('c26V5L', f'runs/v5c26/{w}'),
                   ('c25R', f'rruns/c25/{w}'), ('c26L', f'runs/c25u/{w}'), ('c25L', f'runs/c25/{w}')):
        r = s(p)
        if r:
            row += f" | {tag} {r['total']:.0f}{'(CUT)' if r.get('wall_expired') else ''}"
            if f:
                row += f" d {f['total'] - r['total']:+.0f}"
    print(row)
    lv = levels(f'rruns/v5f/{w}')
    if lv:
        print('       levels', lv[:12])
