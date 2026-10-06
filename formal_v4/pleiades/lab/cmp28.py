#!/usr/bin/env python3
"""cmp28.py BASE NEW [WORLDS...] : per-world totals of two local/remote run sets (runs/ and rruns/)."""
import json, os, sys
base, new = sys.argv[1], sys.argv[2]
roots = ('runs', 'rruns')
def load(name, w):
    for r in roots:
        f = f'{r}/{name}/{w}/summary.json'
        if os.path.exists(f):
            return json.load(open(f))
    return None
worlds = sys.argv[3:] or sorted({w for r in roots for n in (base, new) if os.path.isdir(f'{r}/{n}') for w in os.listdir(f'{r}/{n}')})
ds = []
for w in worlds:
    a, b = load(base, w), load(new, w)
    if not a or not b:
        continue
    d = b['total'] - a['total']
    ds.append(d)
    print(f"{w:6s} {a['total']:9.0f} {b['total']:9.0f} d {d:+7.0f}  sci {b['sum_best_scores'] - a['sum_best_scores']:+6.0f} "
          f"req {b['observation_request_reward'] - a['observation_request_reward']:+5.0f} miss {a['required_missing']}->{b['required_missing']} "
          f"wall {a['wall']:.0f}/{b['wall']:.0f} pol {a['policy_cpu']:.0f}/{b['policy_cpu']:.0f}{' CUT' if b.get('wall_expired') else ''}")
if ds:
    ds.sort()
    print(f'n {len(ds)} mean {sum(ds) / len(ds):+.1f} median {ds[len(ds) // 2]:+.1f} up {sum(d > 0 for d in ds)} down {sum(d < 0 for d in ds)}')
