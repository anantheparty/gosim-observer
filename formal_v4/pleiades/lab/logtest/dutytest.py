"""Offline test of the language-model duty-log reader (llm_strategist.DutyReader) on dumped logs: feed the sections
in order, convert the model's as-written items with guider_log.GuiderLog.add_llm (an LLM-only schedule and a merged
parser+LLM schedule) and compare with the deterministic parser (consistent with 117 online report outcomes).
usage: dutytest.py PKG OUTDIR CARD[:LIMIT] ...   env LOGDIR (default work/logtest/v6), DUTY_MODEL"""
import sys, os, re, json, time, threading
from datetime import datetime, timedelta, timezone
PKG, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, PKG)
from llm_strategist import DutyReader
from guider_log import GuiderLog, prep
from log_reader import decode_english, _INVIS, _FW
OFF = {'A1': -4, 'B1': 2, 'C1': -10, 'D1': -9}
LOGDIR = os.environ.get('LOGDIR', '/home/shu/kamico/observer/work/logtest/v6')
os.makedirs(OUT, exist_ok=True)
P = lambda s: datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
TM = re.compile(r'\d{1,2}:\d{2}')

def sections(card):
    out, cur, iss = [], [], None
    for line in open(f'{LOGDIR}/{card}.log.txt', encoding='utf-8'):
        line = line.rstrip('\n')
        if line.startswith('#### issued '):
            if iss is not None:
                out.append((iss, cur))
            iss, cur = line.split('#### issued ')[1].strip(), []
        elif line.strip():
            cur.append(line)
    if iss is not None:
        out.append((iss, cur))
    return out

def hints_for(lines):
    h = {}
    for i, raw in enumerate(lines):
        r0 = raw.translate(_INVIS).translate(_FW)
        e = prep(raw)
        if decode_english(r0) != r0 or TM.findall(e) != TM.findall(r0):
            h[str(i)] = re.sub(r'^\s*【[^】]{1,8}】', '', e)[:300]
    return h

def F(t, off):
    return datetime.fromtimestamp(t + off * 3600, tz=timezone.utc).strftime('%m/%d %H:%M')

def run(card, limit):
    off = OFF[card]
    secs = sections(card)[:limit]
    rd = DutyReader(model=os.environ.get('DUTY_MODEL') or None)
    gp = GuiderLog(off)          # parser only (reference)
    gm = GuiderLog(off)          # parser + model (what the agent uses)
    gx = GuiderLog(off)          # model only
    raw, stats = [], {'agree': 0, 'new': 0, 'withdrawn': 0, 'win': 0, 'active': 0, 'bad': 0}
    for iss, lines in secs:
        t = P(iss)
        text = '\n'.join(lines)
        gp.read(text, t)
        gm.read(text, t)
        loc = datetime.fromtimestamp(t + off * 3600, tz=timezone.utc)
        known = gm.known_summary(t, lambda x: F(x, off))
        res = rd.read(lines, hints_for(lines), loc.strftime('%Y-%m-%d %H:%M (%A)'), off, known)
        raw.append({'issued': iss, 'answer': res})
        if not res:
            continue
        n = gm.add_llm(res, t)
        for k in stats:
            stats[k] += n.get(k, 0)
        gx.add_llm(res, t)
    json.dump({'card': card, 'raw': raw}, open(f'{OUT}/{card}.json', 'w'), ensure_ascii=False, indent=0)
    near = lambda x, arr: any(abs(x - y) <= 120 for y in arr)
    jobs = [c['t'] for c in gp.due()]
    alts = [c['t'] for c in gp.probes()]
    xs = [c['t'] for c in gx.probes() if c['st'] == 'llm']
    rec = sum(near(j, xs) for j in jobs)
    extra = [x for x in xs if not near(x, jobs + alts)]
    miss = [j for j in jobs if not near(j, xs)]
    fl = sorted(gp.flats)
    xw = sorted(gx.flats)
    w_hit = sum(any(a < y and x < b for (x, y) in xw) for (a, b) in fl)
    w_fp = [(x, y) for (x, y) in xw if not any(a < y and x < b for (a, b) in fl)]
    mprobe = [c for c in gm.probes() if c['st'] == 'llm']
    print(f'== {card}: sections {len(secs)} calls {rd.calls} ok {rd.ok} failed {rd.failed} mean latency {rd.wall / max(1, rd.calls):.1f}s\n'
          f'   model-only: recall {rec}/{len(jobs)} of parser jobs, {len(extra)} extra times; windows covered {w_hit}/{len(fl)}, {len(w_fp)} extra\n'
          f'   merged: {stats} -> stated jobs {len(gm.due())} (parser {len(jobs)}), model-only probes {len(mprobe)}', flush=True)
    for j in miss[:15]:
        print('   MISSED', F(j, off))
    for x in extra[:15]:
        c = [c for c in gx.cands.values() if abs(c['t'] - x) < 60]
        print('   EXTRA ', F(x, off), (c[0]['src'] if c else '')[:90])

args = sys.argv[3:]
th = []
for a in args:
    card, _, lim = a.partition(':')
    t = threading.Thread(target=run, args=(card, int(lim) if lim else 10 ** 6))
    t.start(); th.append(t)
for t in th:
    t.join()
