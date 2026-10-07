import sys, time
sys.path.insert(0, '/home/shu/kamico/observer/work/pkgs/c44')
from guider_log import GuiderLog
from llm_strategist import DutyReader
from astro import parse_utc
OFF = 8
F = lambda t: time.strftime('%m-%d %H:%M', time.gmtime(t + OFF * 3600))
ISS = '2026-10-26T04:00:00Z'   # local 10/26 12:00 (Monday)
cases = [
 (['[립희] 10월 28일 밤 9시 30분에 엔지니어링 팀이 가이드 카메라 작업을 합니다. 그 시각이 되면 바로 고장 신고하세요.'], '10-28 21:30'),
 (["[Rikki] Le 28 octobre à 22 h 15, l'équipe technique intervient sur la caméra de guidage ; signalez la panne dès l'heure venue."], '10-28 22:15'),
 (['[Rikki] Am 29.10. um 23:40 Uhr arbeitet das Technikteam an der Leitkamera. Danach sofort Störung melden.'], '10-29 23:40'),
 (['[Rikki] El 29 de octubre a las nueve y cuarto de la noche, ingeniería tocará la cámara guía; reporten la avería a esa hora.'], '10-29 21:15'),
 (['[Рикки] 30 октября в 01:20 ночи инженеры будут работать с гид-камерой; сразу сообщите о неисправности.'], '10-30 01:20'),
 (['【立希】10月30日（金）の夜、二十二時四十五分にエンジニアがガイダーカメラを触ります。時間になったらすぐ報告。'], '10-30 22:45'),
 (['[Rikki] 2026-10-31T20:10:00+08:00 guider camera swap by engineering; file the fault report at that time.'], '10-31 20:10'),
 (['[Rikki] Next Wednesday (the 28th) at a quarter past eleven in the evening the guider camera gets serviced; report it then.'], '10-28 23:15'),
]
def one(c):
    lines, want = c
    iss = parse_utc(ISS)
    g = GuiderLog(OFF, None, None)
    g.read('\n'.join(lines), iss)
    parser = sorted(F(x['t']) + ' ' + x['st'] for x in g.cands.values() if not x['void'])
    d = DutyReader(wall_cap=600.0)
    res = d.read(lines, {}, time.strftime('%Y-%m-%d %H:%M (%A)', time.gmtime(iss + OFF * 3600)), OFF,
                 g.known_summary(iss, F), real_left=3000.0, issued=iss)
    n = g.add_llm(res, iss, lines=lines) if res else None
    got = sorted(F(x['t']) + ' ' + x['st'] for x in g.cands.values() if not x['void'])
    return want, parser, got
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(8) as ex:
    for want, parser, got in ex.map(one, cases):
        print('WANT', want, '| parser', parser, '| final', got, 'OK' if any(x.startswith(want) for x in got) else 'MISS')
