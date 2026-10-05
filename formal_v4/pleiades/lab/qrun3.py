#!/usr/bin/env python3
"""qrun3.py JOBFILE LIMIT : launch jobs "NAME<TAB>WORLD<TAB>PKGDIR<TAB>PARAMS_JSON[<TAB>WEIGHT]" while the machine-wide
weight of running harness processes (cores each uses; default 1, marked on the command line as --env QW=w) stays
within LIMIT (several queues can share one limit). Skips runs with summary.json or a live process.
Env: QBASE, QPY, CF (clock factor, default 0.9)."""
import os, re, sys, subprocess, time
jf, limit = sys.argv[1], int(sys.argv[2])
base = os.environ.get('QBASE', '/home/shu/kamico/observer/work')
py = os.environ.get('QPY', sys.executable)
cf = os.environ.get('CF', '0.9')
def running():
    r = subprocess.run(['pgrep', '-fa', 'harness.py --card'], capture_output=True, text=True).stdout
    return [l for l in r.splitlines() if 'pgrep' not in l]
def weight(lines):
    tot = 0
    for l in lines:
        m = re.search(r'--env QW=(\d+)', l)
        tot += int(m.group(1)) if m else 1
    return tot
jobs = [l.rstrip('\n').split('\t') for l in open(jf) if l.strip() and not l.startswith('#')]
procs = []
for job in jobs:
    name, world, pkg, par = job[:4]
    w = int(job[4]) if len(job) > 4 and job[4].strip() else 1
    out = f'{base}/runs/{name}/{world}'
    if os.path.exists(f'{out}/summary.json'):
        continue
    while True:
        live = running()
        if any(f'--out {out} ' in l or l.endswith(f'--out {out}') for l in live):
            break
        if weight(live) + w <= limit:
            os.makedirs(out, exist_ok=True)
            env = dict(os.environ, OBS2_PARAMS=par)
            lf = open(f'{out}/log.txt', 'w')
            procs.append(subprocess.Popen([py, f'{base}/harness.py', '--card', world, '--agent-dir', pkg, '--factory',
                                           'harness_entry:make', '--env', f'QW={w}', '--out', out, '--clock-factor', cf],
                                          stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=base, start_new_session=True))
            time.sleep(1.0)
            break
        time.sleep(10)
for p in procs:
    p.wait()
print('done', len(jobs), flush=True)
