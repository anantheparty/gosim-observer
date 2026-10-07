# c47: other phrasings (every two hours x3, 11.15pm, UTC, 周三晚十点半, seconds, 'Thursday night, 2 a.m.'); real model calls

import sys, time
PKG = sys.argv[1] if len(sys.argv) > 1 else '/home/shu/kamico/observer/work/pkgs/c48'
sys.path.insert(0, PKG)
from guider_log import GuiderLog
from llm_strategist import DutyReader
from astro import parse_utc
OFF = 8
F = lambda t: time.strftime('%m-%d %H:%M', time.gmtime(t + OFF * 3600))
ISS = '2026-10-26T04:00:00Z'   # local 10/26 12:00
cases = [
 (['【立希】10/28 晚上从 21:00 起每隔两小时重启一次导星相机，共三次，每次都算故障，到点报修。'], ['10-28 21:00', '10-28 23:00', '10-29 01:00']),
 (['【祥子】10/27 半夜十二点导星相机断电重启，算故障。'], ['10-28 00:00']),
 (['【立希】10/27 夜里零点半动导星相机，报修。'], ['10-28 00:30']),
 (['[Rikki] Guider camera swap on Oct 29 at 11.15pm, file a fault ticket.'], ['10-29 23:15']),
 (['[Rikki] Guider camera reboot 10/29 at 15:30 UTC — counts as a fault.'], ['10-29 23:30']),
 (['【立希】周三晚十点半导星相机固件升级，算故障要报。'], ['10-28 22:30']),
 (['【祥子】10/30 23:15:30 导星相机断开，报修。'], ['10-30 23:15']),
 (['[Saki] Thursday night, 2 a.m. (i.e. early Friday): guider camera power cycle, report it.'], ['10-30 02:00']),
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
    items = [(f.get('date_text'), f.get('time_text'), f.get('time'), f.get('clock'), f.get('relative_to', {}).get('kind'), f.get('shift_minutes')) for f in (res or {}).get('fault_starts', [])]
    return want, got, items, {k: v for k, v in (n or {}).items() if v}
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(8) as ex:
    for want, got, items, n in ex.map(one, cases):
        ok = all(any(x.startswith(w) for x in got) for w in want)
        print('WANT', want, 'GOT', got, 'OK' if ok else 'MISS', items, n)
