#!/usr/bin/env python3
"""prof.py CARD PKGDIR NDEC [SKIP] : cProfile the policy's decide() for decisions SKIP..SKIP+NDEC of a card
(harness engine, clock factor 0.65), then stop the run. Prints the top functions by total time."""
import cProfile, pstats, io, os, sys, time
sys.argv, args = sys.argv[:1], sys.argv[1:]
card, pkg, ndec = args[0], args[1], int(args[2])
if len(args) > 4: os.environ["OBS2_PARAMS"] = args[4]
skip = int(args[3]) if len(args) > 3 else 0
sys.path.insert(0, '/home/shu/kamico/observer/work')
import harness  # noqa
from pathlib import Path
sys.path.insert(0, pkg); os.chdir(pkg)
import importlib
mod = importlib.import_module('harness_entry')
cpu = {'t': 0.0, 'n': 0}
wf = harness.V4Workflow(harness.card_dir(card), clock=lambda: cpu['t'] * 0.65)
holder = {}
prof = cProfile.Profile()
def initialize(payload):
    holder['p'] = mod.make(payload)
def decide(message, limit):
    if cpu['n'] >= skip + ndec:
        raise TimeoutError()
    t = time.process_time()
    on = cpu['n'] >= skip
    if on:
        prof.enable()
    try:
        action = holder['p'].decide(message['payload'])
    finally:
        if on:
            prof.disable()
        cpu['t'] += time.process_time() - t
        cpu['n'] += 1
    return {'protocol_version': harness.PROTO, 'message_type': 'decision_response',
            'decision_sequence': message['decision_sequence'], **action}
out = Path('/tmp/prof_out'); out.mkdir(exist_ok=True)
t0 = time.time()
try:
    wf.run(decide, out, wallclock_seconds=900, initialize=initialize)
except Exception as e:
    print('run ended', type(e).__name__)
print('decisions', cpu['n'], 'cpu', round(cpu['t'], 2), 'wall', round(time.time() - t0, 1))
s = io.StringIO()
ps = pstats.Stats(prof, stream=s).sort_stats('tottime')
ps.print_stats(25)
print(s.getvalue()[:6000])
