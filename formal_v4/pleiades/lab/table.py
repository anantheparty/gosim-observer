#!/usr/bin/env python3
"""Print a table of run summaries: rows = variants, cols = cards (+mean)."""
import json, sys, glob, os
from pathlib import Path

root = Path('/home/shu/kamico/observer/work/runs')
pats = sys.argv[1:] or ['*']
rows = {}
cards = set()
for pat in pats:
    for d in sorted(root.glob(pat)):
        if not d.is_dir():
            continue
        for c in sorted(d.iterdir()):
            s = c / 'summary.json'
            if s.exists():
                try:
                    j = json.load(open(s))
                except Exception:
                    continue
                rows.setdefault(d.name, {})[c.name] = j
                cards.add(c.name)
cards = sorted(cards)
print(f"{'variant':28s}" + ''.join(f'{c:>10s}' for c in cards) + f"{'mean':>10s}{'n':>3s}  req  cpu")
for v, r in rows.items():
    vals = [r[c]['total'] if c in r else None for c in cards]
    got = [x for x in vals if x is not None]
    mean = sum(got) / len(got) if got else 0
    req = sum(r[c].get('required_missing', 0) for c in r)
    cpu = max((r[c].get('policy_cpu', 0) for c in r), default=0)
    term = ''.join('!' for c in r if r[c].get('termination') not in ('survey_complete',))
    print(f'{v:28s}' + ''.join(f'{x:10.1f}' if x is not None else f"{'-':>10s}" for x in vals) + f'{mean:10.1f}{len(got):3d} {req:4d} {cpu:5.0f}{term}')
