# c48: past events named by a bare weekday ("周五晚上…掉过一次，已经报修了") must not become future faults; real model calls, 3 runs each

import sys, time, json
PKG = sys.argv[1] if len(sys.argv) > 1 else '/home/shu/kamico/observer/work/pkgs/c48'
sys.path.insert(0, PKG)
from guider_log import GuiderLog
from llm_strategist import DutyReader
from astro import parse_utc
OFF = 8
F = lambda t: time.strftime('%m-%d %H:%M', time.gmtime(t + OFF * 3600))
MON = parse_utc('2026-10-26T04:00:00Z')   # Monday 10/26 12:00 local
cases = [(MON, ['【立希】周五晚上 23:00 导星相机掉过一次，已经报修了，现在好了。'], []),
         (MON, ['[Rikki] Saturday night the guider camera dropped out at 01:20; it was reported and fixed.'], []),
         (MON, ['【祥子】周六夜里那次停机之后一切正常。', '【祥子】周三晚上 22:40 导星相机要换线，算故障。'], ['10-28 22:40'])]
def one(c):
    iss, lines, want = c
    g = GuiderLog(OFF, None, None)
    g.read('\n'.join(lines), iss)
    d = DutyReader(wall_cap=600.0)
    res = d.read(lines, {}, time.strftime('%Y-%m-%d %H:%M (%A)', time.gmtime(iss + OFF * 3600)), OFF, g.known_summary(iss, F), real_left=3000.0, issued=iss)
    n = g.add_llm(res, iss, lines=lines) if res else None
    got = sorted(F(x['t']) for x in g.cands.values() if not x['void'] and x['t'] > iss)
    return lines[0][:24], want, sorted(want) == got, got
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(9) as ex:
    rs = list(ex.map(one, [c for c in cases for _ in range(3)]))
for r in rs:
    print(r)
print('OK', sum(r[2] for r in rs), '/', len(rs))
