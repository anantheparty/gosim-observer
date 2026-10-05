#!/usr/bin/env python3
"""eqtest.py CARD PKGDIR NDEC PARAMS_JSON OUT [CF] : run the first NDEC decisions of a card (harness engine, charged
min(cpu, wall) x CF, default CF 0.01 = ample budget), write every action as JSON lines to OUT and print timing."""
import json, os, sys, time
card, pkg, ndec, params, outf = sys.argv[1:6]
cf = float(sys.argv[6]) if len(sys.argv) > 6 else 0.01
ndec = int(ndec)
os.environ['OBS2_PARAMS'] = params
sys.argv = sys.argv[:1]
sys.path.insert(0, '/home/shu/kamico/observer/work')
import harness  # noqa
from pathlib import Path
sys.path.insert(0, pkg); os.chdir(pkg)
import importlib
mod = importlib.import_module('harness_entry')
cpu = {'t': 0.0, 'n': 0, 'cpu': 0.0, 'wall': 0.0}
wf = harness.V4Workflow(harness.card_dir(card), clock=lambda: cpu['t'] * cf)
holder = {}
fo = open(outf, 'w')
def initialize(payload):
    holder['p'] = mod.make(payload)
def decide(message, limit):
    if cpu['n'] >= ndec:
        raise TimeoutError()
    message['payload'].setdefault('wallclock', {})['speed_factor'] = round(1.0 / cf, 4)
    t = time.process_time(); w = time.perf_counter()
    try:
        action = holder['p'].decide(message['payload'])
    finally:
        dc, dw = time.process_time() - t, time.perf_counter() - w
        cpu['t'] += min(dc, dw); cpu['cpu'] += dc; cpu['wall'] += dw
        cpu['n'] += 1
    fo.write(json.dumps(action, sort_keys=True) + '\n')
    return {'protocol_version': harness.PROTO, 'message_type': 'decision_response',
            'decision_sequence': message['decision_sequence'], **action}
out = Path('/tmp/eq_out_%d' % os.getpid()); out.mkdir(exist_ok=True)
try:
    wf.run(decide, out, wallclock_seconds=900, initialize=initialize)
except Exception as e:
    print('run ended', type(e).__name__)
fo.close()
pol = holder.get('p')
print(json.dumps({'summary_ratio': getattr(pol, '_charge_ratio', None), 'decisions': cpu['n'], 'charged': round(cpu['t'], 2), 'cpu': round(cpu['cpu'], 2), 'wall': round(cpu['wall'], 2)}))
