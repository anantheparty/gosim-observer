import contextlib, csv, json, os, sys, time
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch
ROOT = Path('/home/shu/kamico/observer')
PKG = ROOT / 'work/pkgs/sophon4_authtest'
KIT = ROOT / 'hackathon-survey26/archive/starter_kit_v4'
sys.path[:0] = [str(PKG), str(KIT)]
from glyph_policy import Policy, GLYPHS, fibres
from challenge.v4_workflow import V4Workflow, PROTOCOL_VERSION
out = Path('/tmp/glyph_local/out_auth'); out.mkdir(exist_ok=True)
state = {}
def initialize(payload): state['p'] = Policy(payload)
def decide(message, deadline):
    a = state['p'].decide(message['payload'])
    return dict(protocol_version=PROTOCOL_VERSION, message_type='decision_response', decision_sequence=message['decision_sequence'], **a)
t0 = time.monotonic()
with patch.dict(os.environ, {'SAC_LOCAL_RUNNER': '1'}), (out / 'agent.log').open('w') as log, contextlib.redirect_stderr(log):
    wf = V4Workflow(ROOT / 'work/sophon_desk/local/sophon-local').run(decide, out, initialize=initialize, wallclock_seconds=900)
print('termination', wf['termination_reason'], 'charged', wf['accounted_wallclock_seconds'], 'elapsed', round(time.monotonic() - t0, 1))
dec = list(csv.DictReader(open(out / 'decisions.csv')))
obs = list(csv.DictReader(open(out / 'observations.csv')))
byidx = defaultdict(list)
for o in obs: byidx[o['observe_index']].append(o)
w = state['p'].written
obsdec = [d for d in dec if d['action'] == 'observe']
print('observes', len(obsdec), 'written', len(w))
nights = {r['night_id']: r for r in csv.DictReader(open(ROOT / 'work/sophon_desk/local/sophon-local/public/v4_night_calendar.csv'))}
from datetime import datetime
def ts(x): return datetime.fromisoformat(x.replace('Z', '+00:00'))
pernight = defaultdict(lambda: {'fib': set(), 'n': 0, 'ok': 0, 'letters': set()})
for d, rec in zip(obsdec, w):
    rows = byidx.get(d['observe_index'], [])
    valid = sorted(int(o['fiber_id']) for o in rows if o['valid'] == 'true' and float(o['score'] or 0) > 0)
    letter = rec['letter']; want = fibres(GLYPHS[letter.rstrip('~')], 5, letter.endswith('~'))
    t = ts(d['start_utc'])
    nid = next(k for k, n in nights.items() if ts(n['observing_start_utc']) <= t < ts(n['observing_end_utc']))
    pn = pernight[nid]; pn['fib'] |= set(valid); pn['n'] += 1; pn['ok'] += valid == want; pn['letters'].add(letter)
for nid, pn in sorted(pernight.items()):
    (letter,) = pn['letters']
    want = fibres(GLYPHS[letter.rstrip('~')], 5, letter.endswith('~'))
    print(nid, letter.ljust(3), 'exposures', pn['n'], 'exact', pn['ok'], 'night-union==glyph' if sorted(pn['fib']) == want else 'night-union MISMATCH')
last = [d for d in dec][-3:]
print('last decisions', [(d['action'], d['start_utc'], d['end_utc']) for d in last])
