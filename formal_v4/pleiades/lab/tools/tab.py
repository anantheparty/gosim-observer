#!/usr/bin/env python3
"""tab.py RUN... : table of total scores (runs/ or rruns/) per world, with means over common worlds and delta vs the first run."""
import json, os, sys, glob
base = '/home/shu/kamico/observer/work'
runs = sys.argv[1:]
res = {}
for r in runs:
    d = {}
    for root in ('runs', 'rruns'):
        for f in glob.glob(f'{base}/{root}/{r}/*/summary.json'):
            w = f.split('/')[-2]
            try:
                s = json.load(open(f))
                d[w] = (s['total'], s.get('termination'), s.get('wall'))
            except Exception:
                pass
    res[r] = d
worlds = sorted(set().union(*[set(d) for d in res.values()]))
print('world   ' + ' '.join(f'{r[:12]:>12}' for r in runs))
for w in worlds:
    row = []
    for r in runs:
        v = res[r].get(w)
        row.append(f'{v[0]:12.0f}' + ('*' if v and v[1] != 'survey_complete' else ' ') if v else ' ' * 13)
    print(f'{w:7} ' + ''.join(row))
common = [w for w in worlds if all(w in res[r] for r in runs)]
if common and len(runs) > 1:
    b = runs[0]
    for r in runs[1:]:
        ds = [res[r][w][0] - res[b][w][0] for w in common]
        up = sum(x > 0 for x in ds)
        print(f'{r} - {b}: mean {sum(ds)/len(ds):+.1f} over {len(common)} ({up} up)')
        for pre in sorted(set(w[:2] for w in common)):
            dd = [res[r][w][0] - res[b][w][0] for w in common if w.startswith(pre)]
            print(f'   {pre}: {sum(dd)/len(dd):+.1f} (n={len(dd)})')
