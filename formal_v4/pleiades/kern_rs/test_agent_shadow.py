#!/usr/bin/env python3
"""Shadow check on real inputs: run the final agent (c48, C kernel) on a local card and send every kernel call
to the Rust kernel too, with the same inputs and separate output buffers; compare the outputs bit for bit.
The agent keeps using the C results, so the run itself is unchanged. This tests the kernels on the inputs the
agent really produces, independent of timing.

usage: test_agent_shadow.py CARD NDEC [CF]   (needs the lab harness: /home/shu/kamico/observer/work/harness.py)"""
import ctypes, json, os, sys, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_equiv as T  # noqa: E402  (library loading and argtypes)

card, ndec = sys.argv[1], int(sys.argv[2])
cf = float(sys.argv[3]) if len(sys.argv) > 3 else 0.01
os.environ.pop('OPENAI_API_KEY', None)
os.environ['OBS2_PARAMS'] = '{}'
sys.argv = sys.argv[:1]
sys.path.insert(0, '/home/shu/kamico/observer/work')
import harness  # noqa: E402

pkg = HERE.parent / 'agent'
sys.path.insert(0, str(pkg))
import harness_entry  # noqa: E402

C, R = T.load(T.C_LIB), T.load(T.R_LIB)
stats = {'eval_centers': 0, 'assign_center': 0, 'offset_consistency': 0, 'eval_groups': 0}
bad = []


def arr(addr, ctype, n):
    return np.ctypeslib.as_array((ctype * n).from_address(addr)).copy() if n > 0 else np.zeros(0)


def check(name, c_outs, r_outs, ctx):
    stats[name] += 1
    for a, b in zip(c_outs, r_outs):
        if not T.same(a, b):
            bad.append((name, ctx))
            return


class Shadow:
    """Stands in for the ctypes library inside the agent: C result for the agent, Rust result compared."""

    def eval_centers(self, nc, calt, caz, np_, tv, nt, val, tg, side, pitch, mm, cos_r, o_rate, o_t, o_p, o_tot):
        C.eval_centers(nc, calt, caz, np_, tv, nt, val, tg, side, pitch, mm, cos_r, o_rate, o_t, o_p, o_tot)
        r = [np.zeros(nc), np.zeros(nc, np.int32), np.zeros(nc, np.int32), np.zeros(nc)]
        R.eval_centers(nc, calt, caz, np_, tv, nt, val, tg, side, pitch, mm, cos_r, *[x.ctypes.data for x in r])
        c = [arr(o_rate, ctypes.c_double, nc), arr(o_t, ctypes.c_int32, nc).astype(np.int32),
             arr(o_p, ctypes.c_int32, nc).astype(np.int32), arr(o_tot, ctypes.c_double, nc)]
        check('eval_centers', c, r, (nc, np_))

    def assign_center(self, calt, caz, np_, tv, nt, val, side, pitch, mm, cos_r, t, p, o_t, o_v):
        C.assign_center(calt, caz, np_, tv, nt, val, side, pitch, mm, cos_r, t, p, o_t, o_v)
        F = side * side
        r = [np.zeros(F, np.int32), np.zeros(F)]
        R.assign_center(calt, caz, np_, tv, nt, val, side, pitch, mm, cos_r, t, p, *[x.ctypes.data for x in r])
        c = [arr(o_t, ctypes.c_int32, F).astype(np.int32), arr(o_v, ctypes.c_double, F)]
        check('assign_center', c, r, (calt, caz, t, p))

    def offset_consistency(self, no, oalt, oaz, calt, caz, na, tv, fib, hit, side, pitch, o_agree):
        C.offset_consistency(no, oalt, oaz, calt, caz, na, tv, fib, hit, side, pitch, o_agree)
        r = np.zeros(no, np.int32)
        R.offset_consistency(no, oalt, oaz, calt, caz, na, tv, fib, hit, side, pitch, r.ctypes.data)
        check('offset_consistency', [arr(o_agree, ctypes.c_int32, no).astype(np.int32)], [r], (no, na))

    def eval_groups(self, ng, gs, ge, gu, calt, caz, np_, tv, nt, val, tg, side, pitch, mm, cos_r, cos_sub,
                    zo, zs, th, o_rate, o_t, o_p, o_tot):
        C.eval_groups(ng, gs, ge, gu, calt, caz, np_, tv, nt, val, tg, side, pitch, mm, cos_r, cos_sub, zo, zs, th,
                      o_rate, o_t, o_p, o_tot)
        n = int(arr(ge, ctypes.c_int32, ng).max()) if ng > 0 else 0
        r = [np.zeros(n), np.zeros(n, np.int32), np.zeros(n, np.int32), np.zeros(n)]
        R.eval_groups(ng, gs, ge, gu, calt, caz, np_, tv, nt, val, tg, side, pitch, mm, cos_r, cos_sub, zo, zs, th,
                      *[x.ctypes.data for x in r])
        c = [arr(o_rate, ctypes.c_double, n), arr(o_t, ctypes.c_int32, n).astype(np.int32),
             arr(o_p, ctypes.c_int32, n).astype(np.int32), arr(o_tot, ctypes.c_double, n)]
        check('eval_groups', c, r, (ng, n, np_))


cpu = {'t': 0.0, 'n': 0}
wf = harness.V4Workflow(harness.card_dir(card), clock=lambda: cpu['t'] * cf)
holder = {}


def initialize(payload):
    pol = harness_entry.make(payload)
    assert pol.kern.lib is not None, 'C kernel not loaded'
    pol.kern.lib = Shadow()
    holder['p'] = pol


def decide(message, limit):
    if cpu['n'] >= ndec:
        raise TimeoutError()
    message['payload'].setdefault('wallclock', {})['speed_factor'] = round(1.0 / cf, 4)
    t = time.process_time()
    action = holder['p'].decide(message['payload'])
    cpu['t'] += time.process_time() - t
    cpu['n'] += 1
    return {'protocol_version': harness.PROTO, 'message_type': 'decision_response',
            'decision_sequence': message['decision_sequence'], **action}


out = Path('/tmp/kern_shadow_%d' % os.getpid())
out.mkdir(exist_ok=True)
try:
    wf.run(decide, out, wallclock_seconds=900, initialize=initialize)
except Exception as e:
    print('run ended', type(e).__name__)
print(json.dumps({'card': card, 'decisions': cpu['n'], 'calls': stats, 'mismatches': len(bad), 'first': bad[:3]}))
sys.exit(1 if bad else 0)
