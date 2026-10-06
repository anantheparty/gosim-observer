#!/usr/bin/env python3
"""cmp29.py DIR [DIR ...] : per-card totals/components of online result dirs (work/online/<name>) side by side, then the
fault reports (time, why, correct) of the first dir's A1-D1 runs."""
import glob, json, sys, zipfile


def load(d):
    out = {}
    for zf in glob.glob(f'/home/shu/kamico/observer/work/online/{d}/*/result.zip'):
        z = zipfile.ZipFile(zf)
        nm = lambda s: [n for n in z.namelist() if n.endswith(s)][0]
        sc = json.loads(z.read(nm('workflow_result.json')))['scenario']
        sr = json.loads(z.read(nm('score_report.json')))
        log = z.read(nm('agent.log')).decode('utf-8', 'ignore').splitlines()
        out[sc] = (sr, log)
    return out


dirs = sys.argv[1:]
data = [load(d) for d in dirs]
cards = ['v4-a', 'v4-b', 'v4-c', 'v4-d', 'v4-a1-v5', 'v4-b1-v5', 'v4-c1-v5', 'v4-d1-v5']
print(f"{'card':10s}" + ''.join(f'{d[:14]:>16s}' for d in dirs))
for c in cards:
    row = f'{c:10s}'
    for k, dd in enumerate(data):
        if c in dd:
            sr = dd[c][0]
            row += f"{sr['total']:16.1f}"
        else:
            row += f"{'-':>16s}"
    print(row)
for c in cards:
    parts = []
    for d, dd in zip(dirs, data):
        if c in dd:
            cp = dd[c][0]['components']
            parts.append(f"{d[:8]} sci {cp['sum_best_scores']:.0f} rep {cp['report_settlement']:.0f} req {cp['observation_request_reward']:.0f}")
    print(f'  {c:10s} ' + ' | '.join(parts))
first = data[0]
for c in cards[4:]:
    if c not in first:
        continue
    log = first[c][1]
    reps = []
    for l in log:
        if '"event":"report"' in l or '"event":"report_result"' in l or '"event":"log_fault"' in l:
            try:
                j = json.loads(l)
            except ValueError:
                continue
            if j['event'] == 'report':
                reps.append(f"{j['t'][5:16]}{'L' if j.get('why') == 'log' else 'B'}")
            elif j['event'] == 'report_result':
                reps[-1] += '+' if j.get('correct') else '-'
    llm = sum(1 for l in log if '"stage":"log"' in l)
    print(f'{dirs[0]} {c} reports (L=log B=belief, +/- correct): {" ".join(reps)}  log-llm calls {llm}')
