"""Run guider_log.GuiderLog over the logs of a result zip (or a dumped v6 log) and print the schedule."""
import sys, json, zipfile, glob, re
from datetime import datetime, timezone
PKG = sys.argv[1] if len(sys.argv) > 1 else '/home/shu/kamico/observer/work/pkgs/c31'
sys.path.insert(0, PKG)
from guider_log import GuiderLog
OFF = {'v4-a1-v5': -4, 'v4-b1-v5': 2, 'v4-c1-v5': -10, 'v4-d1-v5': -9}
def P(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
def F(t, off=0):
    return datetime.fromtimestamp(t + off * 3600, tz=timezone.utc).strftime('%m-%d %H:%M')
def run(zpath, verbose=True):
    z = zipfile.ZipFile(zpath)
    g = lambda s: z.read([n for n in z.namelist() if n.endswith(s)][0]).decode('utf-8', 'ignore')
    sc = json.loads(g('score_report.json'))['scenario']
    if sc not in OFF:
        return None
    off = OFF[sc]
    msgs = [json.loads(l) for l in g('messages.jsonl').splitlines()]
    gl = GuiderLog(off)
    for m in msgs:
        if m.get('record_type') == 'observation_request' and len(m.get('reason') or '') > 30:
            gl.read(m['reason'], P(m['issued_at_utc']))
    reps = [(P(m['issued_at_utc']), m['correct']) for m in msgs if m.get('record_type') == 'report_result']
    if verbose:
        print('=====', sc, 'jobs', len(gl.due()), 'probes', len(gl.probes()), 'flats', len(gl.flats), 'void',
              sum(1 for c in gl.cands.values() if c['void']), 'unparsed', len(gl.unparsed), 'pending rel', len(gl.rel_flat), len(gl.rel_other))
    return sc, off, gl, reps
if __name__ == '__main__':
    for zp in sys.argv[2:]:
        r = run(zp)
        if r is None:
            continue
        sc, off, gl, reps = r
        for c in gl.due():
            print('  JOB  %s UTC  (local %s)  n=%d  %s' % (F(c['t']), F(c['t'], off), c['n'], c['src'][:70]))
        for c in gl.probes():
            print('  PROBE %s %s UTC (local %s) %s' % (c['st'], F(c['t']), F(c['t'], off), c['src'][:60]))
        for u in gl.unparsed[:30]:
            print('  UNPARSED', u[:160])
