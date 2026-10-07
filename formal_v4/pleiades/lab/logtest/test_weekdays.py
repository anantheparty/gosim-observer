# c48: weekdays written without a date ("Friday 21:45", "星期六夜里一点二十"); c47's model picked the past week 9/15; real model calls, 3 runs each

import sys, time, json
PKG = sys.argv[1] if len(sys.argv) > 1 else '/home/shu/kamico/observer/work/pkgs/c48'
sys.path.insert(0, PKG)
from guider_log import GuiderLog
from llm_strategist import DutyReader
from astro import parse_utc
OFF = 8
F = lambda t: time.strftime('%m-%d %H:%M', time.gmtime(t + OFF * 3600))
iss = parse_utc('2026-10-26T04:00:00Z')   # Monday 10/26 12:00 local
cases = [(['[Saki] Thursday night, 2 a.m. (i.e. early Friday): guider camera power cycle, report it.'], '10-30 02:00'),
         (['【立希】周四晚上 23:30 动导星相机，算故障。'], '10-29 23:30'),
         (['[Rikki] Guider camera firmware update on Wednesday at 22:10, file a fault.'], '10-28 22:10'),
         (['【祥子】星期六夜里一点二十导星相机重启，要报修。'], '11-01 01:20'),
         (['[Saki] Friday 21:45 — guider swap, counts as a fault.'], '10-30 21:45')]
def one(c):
    lines, want = c
    g = GuiderLog(OFF, None, None)
    g.read('\n'.join(lines), iss)
    d = DutyReader(wall_cap=600.0)
    res = d.read(lines, {}, time.strftime('%Y-%m-%d %H:%M (%A)', time.gmtime(iss + OFF * 3600)), OFF, g.known_summary(iss, F), real_left=3000.0, issued=iss)
    n = g.add_llm(res, iss, lines=lines) if res else None
    got = sorted(F(x['t']) for x in g.cands.values() if not x['void'])
    fs = [(f.get('date'), f.get('night')) for f in (res or {}).get('fault_starts', [])]
    return want, want in got, got, fs
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(15) as ex:
    rs = list(ex.map(one, [c for c in cases for _ in range(3)]))
ok = sum(r[1] for r in rs)
for r in rs:
    print(r)
print('OK', ok, '/', len(rs))
