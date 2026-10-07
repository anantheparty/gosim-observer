# c48: 下周X / 这周X / 上周X / "Next Monday" / weekday = today; real model calls, 3 runs each

import sys, time, json
PKG = sys.argv[1] if len(sys.argv) > 1 else '/home/shu/kamico/observer/work/pkgs/c48'
sys.path.insert(0, PKG)
from guider_log import GuiderLog
from llm_strategist import DutyReader
from astro import parse_utc
OFF = 8
F = lambda t: time.strftime('%m-%d %H:%M', time.gmtime(t + OFF * 3600))
MON = parse_utc('2026-10-26T04:00:00Z')   # Monday 10/26 12:00 local
FRI = parse_utc('2026-10-23T04:00:00Z')   # Friday 10/23
SUN = parse_utc('2026-10-25T04:00:00Z')   # Sunday 10/25
WED = parse_utc('2026-10-28T04:00:00Z')   # Wednesday 10/28
cases = [(MON, ['【立希】下周一晚上 23:45 动导星相机，算故障，到点报修。'], ['11-02 23:45']),
         (FRI, ['【立希】下周二晚上 21:15 导星相机重启，算故障。'], ['10-27 21:15']),
         (SUN, ['【祥子】下周日晚上 23:30 导星相机换线，报修。'], ['11-01 23:30']),
         (WED, ['【灯】这周日晚上 22:15 动导星相机，要报。'], ['11-01 22:15']),
         (MON, ['【立希】上周四 23:00 那次导星相机故障已经报过了，不用管。', '【立希】周四晚上 23:00 导星相机还要再动一次，报修。'], ['10-29 23:00']),
         (MON, ['[Rikki] Next Monday at 22:30 the guider camera gets new firmware; file a fault.'], ['11-02 22:30']),
         (MON, ['【祥子】周一晚上 23:10（就是今晚）动导星相机，算故障。'], ['10-26 23:10'])]
def one(c):
    iss, lines, want = c
    g = GuiderLog(OFF, None, None)
    g.read('\n'.join(lines), iss)
    d = DutyReader(wall_cap=600.0)
    res = d.read(lines, {}, time.strftime('%Y-%m-%d %H:%M (%A)', time.gmtime(iss + OFF * 3600)), OFF, g.known_summary(iss, F), real_left=3000.0, issued=iss)
    n = g.add_llm(res, iss, lines=lines) if res else None
    got = sorted(F(x['t']) for x in g.cands.values() if not x['void'] and x['t'] > iss)
    return lines[-1][:24], want, sorted(want) == got, got
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(21) as ex:
    rs = list(ex.map(one, [c for c in cases for _ in range(3)]))
for r in rs:
    print(r)
print('OK', sum(r[2] for r in rs), '/', len(rs))
