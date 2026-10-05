#!/usr/bin/env python3
"""Poll one platform batch; print a line whenever a card's status/score changes; exit when the batch is terminal."""
import sys, time, json
sys.path.insert(0, '/home/shu/kamico/observer/gosim-observer/formal_v4/platform_tools')
from gosim_platform import Client

CARD = {'297bf8': 'B', '30d456': 'A', '5dd461': 'D', '6fb9c6': 'C', '34b81a': 'alpha', '9c4c37': 'delta', 'a62743': 'beta', 'd0aea5': 'gamma'}
batch = sys.argv[1]
poll = int(sys.argv[2]) if len(sys.argv) > 2 else 60
c = Client(); c.login()
seen = {}
fails = 0
while True:
    try:
        lst = c.portal('list'); fails = 0
    except Exception as e:  # transient error: retry, re-login occasionally
        fails += 1
        if fails % 5 == 0:
            try: c.login()
            except Exception: pass
        if fails > 60:
            print('watch: giving up after repeated errors', e, flush=True); sys.exit(1)
        time.sleep(poll); continue
    b = next((x for x in lst.get('batches') or [] if x['id'].startswith(batch)), None)
    if b is None:
        time.sleep(poll); continue
    for r in b.get('observer_runs') or []:
        sid = (r.get('scenario_id') or '')[:6]
        ss = r.get('score_summary') or {}
        key = (r.get('status'), r.get('score'))
        if seen.get(sid) != key:
            seen[sid] = key
            extra = ''
            if isinstance(ss, dict) and r.get('score') is not None:
                extra = f" req_miss={ss.get('required_missing')} term={ss.get('termination_reason')} acc={ss.get('accounted_wallclock_seconds')}"
            print(f"{CARD.get(sid, sid)}: {r.get('status')} score={r.get('score')}{extra}", flush=True)
    TERMINAL = ('scored', 'failed', 'cancelled', 'error', 'expired', 'completed', 'done', 'superseded')
    runs = b.get('observer_runs') or []
    if b.get('status') in TERMINAL or (runs and all(r.get('status') in TERMINAL for r in runs)):
        print(f"BATCH {batch} {b.get('status')} mean={b.get('score')}", flush=True)
        sys.exit(0)
    time.sleep(poll)
