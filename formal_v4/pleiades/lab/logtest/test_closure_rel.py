import sys, time, json
sys.path.insert(0, '/home/shu/kamico/observer/work/pkgs/c44')
from guider_log import GuiderLog
from llm_strategist import DutyReader
from astro import parse_utc
OFF = 8
F = lambda t: time.strftime('%m-%d %H:%M', time.gmtime(t + OFF * 3600))
cases = [
 ('2026-11-02T04:00:00Z', ['【立希】11/3 晚上 21:00 到 22:00 东边有发射窗口，那个方向封。',
                           '【祥子】发射窗口结束后半小时，工程组动导星相机，到点就报。'], '11-03 22:30'),
 ('2026-11-02T04:00:00Z', ['【灯】11/4 22:10-23:40 全站停机检修，关顶。',
                           '【祥子】11/4 那晚停机结束后 20 分钟，工程组再动一次导星相机，动了就报修。'], '11-05 00:00'),
 ('2026-11-02T04:00:00Z', ['[Taki] Launch window on the night of 11/5: 23:15-23:45 local, the south sector is closed.',
                           '[Sakiko] Engineering will touch the guider camera 40 minutes after the launch window closes; report it then.'], '11-06 00:25'),
 ('2026-11-02T04:00:00Z', ['【立希】11/6 夜里「门禁卡刷不开」，西北方向 20:30 到 23:30 关。',
                           '【祥子】西北那边关闭结束以后，隔一个小时动导星相机。'], '11-07 00:30'),
 ('2026-11-02T04:00:00Z', ['【祥子】11/3 晚上 21:30 工程组动导星相机，之后要报修。'], '11-03 21:30'),
]
def one(c):
    iso, lines, want = c
    iss = parse_utc(iso)
    g = GuiderLog(OFF, None, None)
    g.read('\n'.join(lines), iss)
    d = DutyReader(wall_cap=600.0)
    res = d.read(lines, {}, time.strftime('%Y-%m-%d %H:%M (%A)', time.gmtime(iss + OFF * 3600)), OFF,
                 g.known_summary(iss, F), real_left=3000.0, issued=iss)
    n = g.add_llm(res, iss, lines=lines) if res else None
    got = sorted(F(x['t']) + ' ' + x['st'] for x in g.cands.values() if not x['void'])
    rel = [f.get('relative_to') for f in (res or {}).get('fault_starts', [])]
    return want, got, n, rel
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(5) as ex:
    for want, got, n, rel in ex.map(one, cases):
        print('WANT', want, 'GOT', got, '|', rel)
