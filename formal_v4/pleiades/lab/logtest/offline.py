"""Offline check of log_reader on the online A1-D1 result zips: parsed fault events vs our report actions."""
import glob, json, sys, zipfile
sys.path.insert(0, sys.argv[2] if len(sys.argv) > 2 else '/home/shu/kamico/observer/work/pkgs/c28d')
from log_reader import LogReader
from datetime import datetime, timezone

def ep(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()

def fm(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime('%m-%d %H:%M')

OFF = {"2ec2be31": 0, "40503eba": 0, "4372426d": 0, "fdba57e1": 0}
batch = sys.argv[1] if len(sys.argv) > 1 else 'c28b_49fd'
for d in OFF:
    zs = glob.glob(f'/home/shu/kamico/observer/work/online/{batch}/{d}*/result.zip')
    if not zs:
        print(d, 'no zip'); continue
    z = zipfile.ZipFile(zs[0])
    nm = lambda s: [n for n in z.namelist() if n.endswith(s)][0]
    wf = json.loads(z.read(nm('workflow_result.json')))
    sc = wf.get('scenario') or ''
    msgs = [json.loads(l) for l in z.read(nm('messages.jsonl')).decode().splitlines()]
    acts = [json.loads(l) for l in z.read(nm('actions.jsonl')).decode().splitlines()]
    # site offset from the scenario block if present, else from known cards
    card = sc
    off = {'a': -4.0, 'b': 2.0, 'c': -10.0, 'd': -9.0}[sc.split('-')[1][0]]
    lr = LogReader(off if off is not None else 0.0, None, None)
    evs = []
    lr.events_all = evs
    for m in msgs:
        if m.get('record_type') == 'observation_request' and len(m.get('reason') or '') > 30:
            evs += lr.read(m['reason'], ep(m['issued_at_utc']))
    dec = z.read(nm('decisions.csv')).decode().splitlines()
    reps = [l.split(',')[3] for l in dec[1:] if l.split(',')[2] == 'report']
    sr = json.loads(z.read(nm('score_report.json')))
    print(f'== {d} card={card} off={off} events={len(evs)} reports={len(reps)} settle={sr["components"].get("report_settlement")} total={sr["total"]:.1f}')
    for e in sorted(evs, key=lambda e: e['t'] if e['t'] else e['seen']):
        print(f"   {e['kind']:8s}{' VOID' if e.get('void') else ''} onset {fm(e['t']) if e['t'] else '   ?       '} seen {fm(e['seen'])} | {e['src'][:90]}")
    print('   REPORTS', ' '.join(r[5:16] for r in reps))
