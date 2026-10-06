"""Offline test of the language-model fallback: which v5 log lines the parser leaves unread, and what the model
extracts from them (should be nothing, as the parser already covers every fault entry)."""
import glob, json, sys, zipfile, time, os
sys.path.insert(0, sys.argv[1])
from log_reader import LogReader, quote_in
from datetime import datetime, timezone, timedelta
ep = lambda s: datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
call = len(sys.argv) > 2 and sys.argv[2] == 'call'
if call:
    import llm_strategist
    an = llm_strategist.LogAnalyst(max_calls=200)
    print('enabled', an.enabled, an.client.model)
OFFS = {'a': -4.0, 'b': 2.0, 'c': -10.0, 'd': -9.0}
for zf in sorted(glob.glob('/home/shu/kamico/observer/work/online/c28b_49fd/*/result.zip')):
    z = zipfile.ZipFile(zf)
    nm = lambda s: [n for n in z.namelist() if n.endswith(s)][0]
    sc = json.loads(z.read(nm('workflow_result.json')))['scenario']
    if not sc.endswith('-v5'):
        continue
    off = OFFS[sc.split('-')[1][0]]
    lr = LogReader(off)
    n_txt = n_calls = 0
    jobs = []
    for l in z.read(nm('messages.jsonl')).decode().splitlines():
        if '"observation_request"' not in l:
            continue
        m = json.loads(l)
        if len(m.get('reason') or '') <= 30:
            continue
        n_txt += 1
        iss = ep(m['issued_at_utc'])
        lr.read(m['reason'], iss)
        if lr.last_unread:
            n_calls += 1
            loc = datetime.fromtimestamp(iss + off * 3600, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
            jobs.append((m['request_id'], list(lr.last_unread), loc))
    print(f'== {sc}: texts {n_txt}, model calls {n_calls}')
    for key, lines, loc in jobs[:3]:
        for ln in lines[:4]:
            print('   unread:', ln[:130])
    if call:
        for key, lines, loc in jobs:
            an.submit(key, lines, loc)
        t0 = time.time()
        got = {}
        while len(got) < len(jobs) and time.time() - t0 < 600:
            for k, items in an.results():
                got[k] = items
            time.sleep(1)
        for key, lines, loc in jobs:
            items = got.get(key)
            if items:
                for it in items:
                    print(f'   MODEL {key} {loc}: {it} quote_ok={quote_in(it["quote"], lines)}')
        print(f'   answered {len(got)}/{len(jobs)} calls {an.calls} ok {an.ok} failed {an.failed}')
