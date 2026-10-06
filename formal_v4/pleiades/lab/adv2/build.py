#!/usr/bin/env python3
"""build.py [NAMES...] : generate battery worlds with gen_adv.py in parallel (logs in adv2/logs)."""
import os, sys, subprocess
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from battery import W
os.makedirs('/home/shu/kamico/observer/work/adv2/logs', exist_ok=True)
names = sys.argv[1:] or list(W)
def one(n):
    (t, s, m), env = W[n]
    e = dict(os.environ, **env)
    with open(f'/home/shu/kamico/observer/work/adv2/logs/build_{n}.log', 'w') as lf:
        r = subprocess.run([sys.executable, '/home/shu/kamico/observer/work/gen_adv.py', n, t, str(s), str(m)],
                           stdout=lf, stderr=subprocess.STDOUT, env=e, cwd='/home/shu/kamico/observer/work')
    return n, r.returncode
with ThreadPoolExecutor(int(os.environ.get('NPAR', '10'))) as ex:
    for n, rc in ex.map(one, names):
        print(n, 'ok' if rc == 0 else f'FAIL rc={rc}', flush=True)
