# c47: fault times written relative to the handover ("两小时后", "90 minutes from now") and a 12-hour clock whose evening is only in the context ("今晚十一点一刻"); real model calls

import sys, time
PKG = sys.argv[1] if len(sys.argv) > 1 else '/home/shu/kamico/observer/work/pkgs/c48'
sys.path.insert(0, PKG)
from guider_log import GuiderLog
from llm_strategist import DutyReader
from astro import parse_utc
OFF = 8
F = lambda t: time.strftime('%m-%d %H:%M', time.gmtime(t + OFF * 3600))
ISS = '2026-10-26T12:30:00Z'   # local 10/26 20:30
cases = [
 (['【立希】两小时后工程组动导星相机，到点报修。'], '10-26 22:30'),
 (['[Rikki] Engineering will touch the guider camera 90 minutes from now; report it then.'], '10-26 22:00'),
 (['【祥子】交接后再过三个半小时，导星相机要换，换了就报修。'], '10-27 00:00'),
 (['【立希】今晚十一点一刻动导星相机。'], '10-26 23:15'),
]
iss = parse_utc(ISS)
def one(c):
    lines, want = c
    g = GuiderLog(OFF, None, None)
    g.read('\n'.join(lines), iss)
    d = DutyReader(wall_cap=600.0)
    res = d.read(lines, {}, time.strftime('%Y-%m-%d %H:%M (%A)', time.gmtime(iss + OFF * 3600)), OFF, g.known_summary(iss, F), real_left=3000.0, issued=iss)
    n = g.add_llm(res, iss, lines=lines) if res else None
    got = sorted(F(x['t']) + ' ' + x['st'] for x in g.cands.values() if not x['void'])
    items = [(f.get('time'), f.get('relative_to', {}).get('kind'), f.get('shift_minutes')) for f in (res or {}).get('fault_starts', [])]
    return want, got, items, {k: v for k, v in (n or {}).items() if v}
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(4) as ex:
    for want, got, items, n in ex.map(one, cases):
        print('WANT', want, 'GOT', got, 'OK' if any(x.startswith(want) for x in got) else 'MISS', items, n)
