"""Consistency of the parsed guider schedule with the report outcomes of a run (correct = a fault was active)."""
import sys, glob
sys.path.insert(0, '/home/shu/kamico/observer/work/logtest')
import gtest
def check(z, show=True):
    r = gtest.run(z, verbose=False)
    if r is None:
        return None
    sc, off, gl, reps = r
    jobs = [c['t'] for c in gl.due()]
    probes = [c['t'] for c in gl.probes()]
    last_ok = -1e18
    bad = []
    for t, ok in reps:
        # unrepaired official jobs before t
        pend = [j for j in jobs if last_ok < j <= t]
        pp = [j for j in probes if last_ok < j <= t]
        if ok and not pend:
            bad.append(('correct but no job', gtest.F(t, off), 'probes' if pp else ''))
        if not ok and pend:
            bad.append(('false but job pending', gtest.F(t, off), [gtest.F(j, off) for j in pend]))
        if ok:
            last_ok = t
    if show:
        print('=====', sc, 'reports', len(reps), 'correct', sum(1 for _, o in reps if o), 'inconsistent', len(bad))
        for b in bad:
            print('   ', b)
    return bad
if __name__ == '__main__':
    for z in sys.argv[2:]:
        check(z)
