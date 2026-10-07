# c47/c48: lost-data windows, closures and faults written relative to the handover (c48: "现在起…先关一个小时" starts at the handover); real model calls, 3 runs

import sys, time
PKG = sys.argv[1] if len(sys.argv) > 1 else '/home/shu/kamico/observer/work/pkgs/c48'
sys.path.insert(0, PKG)
from guider_log import GuiderLog
from llm_strategist import DutyReader
from astro import parse_utc
import policy
OFF = 8
class P: pass
p = P(); p.lat, p.lon, p.nights, p.log_off_s = 30.0, 120.0, [], OFF * 3600.0
ev = lambda kind, nd: policy.Policy._sun_event(p, kind, nd)
F = lambda t: time.strftime('%m-%d %H:%M', time.gmtime(t + OFF * 3600))
ISS = '2026-10-26T12:30:00Z'   # local 20:30
lines = ['【立希】交接后一小时开始平场灯测试，做 20 分钟，期间数据作废，不用报修。',
         '【祥子】从现在起两个半小时后，西北方向风大要关，关两个小时。', '【灯】现在起东南方向也风大，先关一个小时再说。',
         '[Rikki] Ninety minutes from now the guider camera will be power-cycled; that counts as a fault, report it.']
iss = parse_utc(ISS)
print('WANT also closure SE', F(iss), '+60m'); print('WANT window', F(iss + 3600), '+20m | closure NW', F(iss + 9000), '+120m | fault', F(iss + 5400))
for run in range(3):
    g = GuiderLog(OFF, None, None); g.sun_cb = ev
    g.read('\n'.join(lines), iss)
    d = DutyReader(wall_cap=600.0)
    res = d.read(lines, {}, time.strftime('%Y-%m-%d %H:%M (%A)', time.gmtime(iss + OFF * 3600)), OFF, g.known_summary(iss, F), real_left=3000.0, issued=iss)
    n = g.add_llm(res, iss, lines=lines) if res else None
    wins = sorted((F(a), round((b - a) / 60)) for (a, b) in g.flats)
    secs = [(F(a), round((b - a) / 60), ds) for (a, b, ds, s) in getattr(g, 'sector_closures', [])]
    faults = sorted(F(x['t']) + ' ' + x['st'] for x in g.cands.values() if not x['void'])
    raw = [(w.get('relative_to'), w.get('shift_minutes'), w.get('duration_minutes')) for w in (res or {}).get('lost_windows', []) + (res or {}).get('closures', [])]
    print('RUN', run, 'windows', wins, 'sectors', secs, 'faults', faults, 'n', {k: v for k, v in (n or {}).items() if v}, raw)
