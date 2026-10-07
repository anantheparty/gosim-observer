import sys, time, math
sys.path.insert(0, '/home/shu/kamico/observer/work/pkgs/c45')
import numpy as np
from guider_log import GuiderLog
from llm_strategist import DutyReader
from astro import parse_utc, moon_state
import policy
OFF = 8
class P: pass
p = P(); p.lat, p.lon, p.nights, p.log_off_s = 30.0, 120.0, [], OFF * 3600.0
ev = lambda kind, nd: policy.Policy._sun_event(p, kind, nd)
F = lambda t: time.strftime('%m-%d %H:%M', time.gmtime(t + OFF * 3600))
for nd in ((2026, 10, 26), (2026, 10, 28), (2026, 11, 2), (2026, 11, 9)):
    r, s = ev('moonrise', nd), ev('moonset', nd)
    il = moon_state((r or s or 0.0), p.lat, p.lon)[1] if (r or s) else None
    print('night', nd, 'moonrise', F(r) if r else None, 'moonset', F(s) if s else None, 'illum', None if il is None else round(il, 2))
ISS = '2026-10-26T04:00:00Z'
cases = [
 (['【立希】10/28 那晚，月亮升起后一小时，工程组动导星相机，到点就报修。'], ('moonrise', (2026, 10, 28), 60)),
 (['[Rikki] Night of 10/29: the guider camera is serviced 30 minutes before moonset; report it then.'], ('moonset', (2026, 10, 29), -30)),
 (['【祥子】10月30日の夜、月の出から二時間後にガイダーカメラを触ります。時間になったら報告。'], ('moonrise', (2026, 10, 30), 120)),
 (['[Rikki] Guider camera work at MJD 61342.5625 — report the fault then.'], ('mjd', 61342.5625, 0)),
 (['【立希】导星相机作业时间：JD 2461343.0 ，到点报修。'], ('jd', 2461343.0, 0)),
]
def one(c):
    lines, (kind, ref, sh) = c
    iss = parse_utc(ISS)
    g = GuiderLog(OFF, None, None); g.sun_cb = ev
    g.read('\n'.join(lines), iss)
    d = DutyReader(wall_cap=600.0)
    res = d.read(lines, {}, time.strftime('%Y-%m-%d %H:%M (%A)', time.gmtime(iss + OFF * 3600)), OFF,
                 g.known_summary(iss, F), real_left=3000.0, issued=iss)
    g.add_llm(res, iss, lines=lines) if res else None
    got = sorted(F(x['t']) + ' ' + x['st'] for x in g.cands.values() if not x['void'])
    if kind in ('moonrise', 'moonset'):
        want = F(ev(kind, ref) + sh * 60)
    elif kind == 'mjd':
        want = F((ref - 40587.0) * 86400.0)
    else:
        want = F((ref - 2440587.5) * 86400.0)
    rel = [(f.get('relative_to'), f.get('julian'), f.get('shift_minutes')) for f in (res or {}).get('fault_starts', [])]
    return want, got, rel
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(5) as ex:
    for want, got, rel in ex.map(one, cases):
        print('WANT', want, 'GOT', got, 'OK' if any(x.startswith(want[:11]) or abs(int(x[6:8])*60+int(x[9:11]) - int(want[6:8])*60-int(want[9:11])) <= 2 for x in got) else 'MISS', '|', rel)
