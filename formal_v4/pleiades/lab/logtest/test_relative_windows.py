import sys, time
PKG = sys.argv[1] if len(sys.argv) > 1 else '/home/shu/kamico/observer/work/pkgs/c46'
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
ISS = '2026-10-26T04:00:00Z'
lines = ['【立希】10/28 那晚天黑后一小时开始第一段平场灯测试，做 20 分钟。',
         '【祥子】10/28 夜里第二段平场灯测试在月亮升起后半小时开始，持续 15 分钟。',
         '【祥子】10/28 夜里第二段平场灯测试结束后再过 40 分钟动导星相机，到点报修。',
         '【立希】10/29 23:50 开始做镜盖测试，持续 25 分钟，测试不用报修。',
         '[Rikki] On the night of 10/30 the flat-lamp test starts 90 minutes after sunset and runs until 21:40.',
         '【立希】10/31 天黑后两小时起西北方向风大要关，关三个小时。']
dusk28 = ev('dusk', (2026, 10, 28)); mr28 = ev('moonrise', (2026, 10, 28)); ss30 = ev('sunset', (2026, 10, 30)); dusk31 = ev('dusk', (2026, 10, 31))
print('anchors: dusk28', F(dusk28), 'moonrise28', F(mr28), 'sunset30', F(ss30), 'dusk31', F(dusk31))
print('WANT windows:', F(dusk28 + 3600), '+20m |', F(mr28 + 1800), '+15m | 10-29 23:50 +25m |', F(ss30 + 5400), '-> 21:40 | closure NW', F(dusk31 + 7200), '+3h')
print('WANT fault:', F(mr28 + 1800 + 900 + 2400))
iss = parse_utc(ISS)
for run in range(3):
    g = GuiderLog(OFF, None, None); g.sun_cb = ev
    g.read('\n'.join(lines), iss)
    d = DutyReader(wall_cap=600.0)
    res = d.read(lines, {}, time.strftime('%Y-%m-%d %H:%M (%A)', time.gmtime(iss + OFF * 3600)), OFF, g.known_summary(iss, F), real_left=3000.0, issued=iss)
    n = g.add_llm(res, iss, lines=lines) if res else None
    wins = sorted((F(a), round((b - a) / 60)) for (a, b) in g.flats)
    secs = [(F(a), round((b - a) / 60), ds) for (a, b, ds, s) in getattr(g, 'sector_closures', [])]
    faults = sorted(F(x['t']) + ' ' + x['st'] for x in g.cands.values() if not x['void'])
    print('RUN', run, 'windows', wins, 'sectors', secs, 'faults', faults, 'n', {k: v for k, v in (n or {}).items() if v})
