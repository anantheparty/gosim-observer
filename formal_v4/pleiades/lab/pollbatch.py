#!/usr/bin/env python3
"""pollbatch.py BATCH : wait until every run of an online batch is final, then print the card scores and A-D mean."""
import sys, time, json
sys.path.insert(0, '/home/shu/kamico/observer/gosim-observer/formal_v4/platform_tools')
from gosim_platform import Client
NAMES = {'30d456db': 'A', '297bf82f': 'B', '6fb9c640': 'C', '5dd4610e': 'D',
         'fdba57e1': 'A1', '4372426d': 'B1', '40503eba': 'C1', '2ec2be31': 'D1'}
bid = sys.argv[1]
c = Client(); c.login()
while True:
    try:
        rows = c.table('observer_runs', f'select=scenario_id,status,score,error&batch_id=eq.{bid}') or []
    except Exception as e:
        print('poll error', e, flush=True); time.sleep(60)
        try:
            c = Client(); c.login()
        except Exception as e2:
            print('login error', e2, flush=True)
        continue
    fin = [r for r in rows if r['status'] in ('scored', 'failed', 'cancelled', 'void', 'error')]
    try:
        bst = (c.table('observer_batches', f'select=status&id=eq.{bid}') or [{}])[0].get('status')
    except Exception:
        bst = None
    if (rows and len(fin) == len(rows) and len(rows) >= 8) or bst in ('scored', 'failed', 'cancelled'):
        print('batch status', bst, flush=True)
        break
    time.sleep(90)
sc = {NAMES.get(r['scenario_id'][:8], r['scenario_id'][:8]): (r['status'], r['score'], r.get('error')) for r in rows}
for k in ('A', 'B', 'C', 'D', 'A1', 'B1', 'C1', 'D1'):
    print(k, sc.get(k))
ad = [sc[k][1] for k in ('A', 'B', 'C', 'D') if k in sc and sc[k][1] is not None]
if len(ad) == 4:
    print('A-D mean %.6f' % (sum(ad) / 4))
