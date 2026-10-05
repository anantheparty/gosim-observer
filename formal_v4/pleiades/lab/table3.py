"""table3.py prefix-filter variants... : compact per-world totals (local runs/ + rruns/)"""
import json, sys, glob, collections
wf = sys.argv[1]
names = sys.argv[2:]
data = {}
for n in names:
    for base in ('runs', 'rruns'):
        for f in glob.glob(f'/home/shu/kamico/observer/work/{base}/{n}/{wf}*/summary.json'):
            data.setdefault(n, {})[f.split('/')[-2]] = json.load(open(f))['total']
worlds = sorted({w for n in data for w in data[n]})
print('%-14s' % '' + ''.join('%8s' % w for w in worlds) + '    mean  n')
base = None
for n in names:
    r = data.get(n, {})
    vals = [r.get(w) for w in worlds]
    got = [v for v in vals if v is not None]
    print('%-14s' % n[:14] + ''.join('%8.0f' % v if v is not None else '%8s' % '-' for v in vals) + '  %7.0f %2d' % (sum(got) / len(got) if got else 0, len(got)))
