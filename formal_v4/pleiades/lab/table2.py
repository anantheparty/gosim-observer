"""table2.py name1 name2 ... : per-world totals for local (runs/) and remote-fetched (rruns/) runs, with means per card class."""
import json, sys, os, glob, collections
names = sys.argv[1:]
rows = collections.OrderedDict()
for n in names:
    for base in ('runs', 'rruns'):
        for f in glob.glob(f'/home/shu/kamico/observer/work/{base}/{n}/*/summary.json'):
            w = f.split('/')[-2]
            d = json.load(open(f))
            rows.setdefault(n, {})[w] = d
worlds = sorted({w for n in rows for w in rows[n]})
print('%-22s' % 'variant' + ''.join('%9s' % w for w in worlds) + '   meanA    meanB    meanC    meanD')
for n in names:
    r = rows.get(n, {})
    line = '%-22s' % n
    cls = collections.defaultdict(list)
    for w in worlds:
        if w in r:
            line += '%9.0f' % r[w]['total']
            cls[w[:2]].append(r[w]['total'])
        else:
            line += '%9s' % '-'
    for c in ('FA', 'FB', 'FC', 'FD'):
        v = cls.get(c)
        line += '%9.0f' % (sum(v) / len(v)) if v and len(v) == 4 else '%9s' % '-'
    print(line)
