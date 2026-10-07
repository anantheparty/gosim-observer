"""Sequential duty-log replay with ONE persistent DutyReader (standing rules carried across sections), as in a run.
Prints per-section counts and the model-kept rules; at the end the due / probe schedule vs. the parser-only one."""
import sys, json, copy, re, time
PKG = sys.argv[3] if len(sys.argv) > 3 else '/home/shu/kamico/observer/work/pkgs/c43'
sys.path.insert(0, PKG)
from guider_log import GuiderLog, prep
from log_reader import decode_english, _INVIS, _FW
from llm_strategist import DutyReader
from astro import parse_utc
world, OFF = sys.argv[1], float(sys.argv[2])
msgs = [json.loads(l) for l in open('/home/shu/kamico/observer/work/runs/g38/%s/messages.jsonl' % world)]
g = GuiderLog(OFF, None, None)
p0 = GuiderLog(OFF, None, None)
d = DutyReader(wall_cap=2700.0, max_calls=400)
loc = lambda t: time.strftime('%m/%d %H:%M', time.gmtime(t + OFF * 3600))
tot = {}
for m in msgs:
    text = m.get('reason') or ''
    if not text.strip():
        continue
    iss = parse_utc(m['issued_at_utc'])
    g.read(text, iss); p0.read(text, iss)
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()][:400]
    hints = {}
    for i, raw in enumerate(lines):
        r0 = raw.translate(_INVIS).translate(_FW); e = prep(raw)
        if decode_english(r0) != r0 or re.findall(r'\d{1,2}:\d{2}', e) != re.findall(r'\d{1,2}:\d{2}', r0):
            hints[str(i)] = re.sub(r'^\s*【[^】]{1,8}】', '', e)[:300]
    known = g.known_summary(iss, loc)
    nr0 = len(d.mrules)
    res = d.read(lines, hints, time.strftime('%Y-%m-%d %H:%M (%A)', time.gmtime(iss + OFF * 3600)), OFF, known,
                 real_left=3000.0, issued=iss)
    if not res:
        print('NONE', time.strftime('%m-%dT%H:%M', time.gmtime(iss)), flush=True); continue
    n = g.add_llm(res, iss, lines=lines)
    for k, x in n.items(): tot[k] = tot.get(k, 0) + x
    newr = d.mrules[nr0:] if len(d.mrules) >= nr0 else d.mrules
    print(time.strftime('%m-%dT%H:%M', time.gmtime(iss)), n, 'rules+%d' % max(0, len(d.mrules) - nr0), flush=True)
print('TOTAL', tot, 'calls', d.calls, 'ok', d.ok, 'failed', d.failed, 'wall', round(d.wall))
print('MODEL RULES (last 12):')
for r in d.mrules: print('   ', r[:150])
print('REGEX RULES:', len(d.rules))
due = sorted(c['t'] for c in g.due()); due0 = sorted(c['t'] for c in p0.due())
pr = sorted((c['t'], c['st']) for c in g.probes())
print('DUE', len(due), 'parser-only DUE', len(due0), 'PROBES', len(pr), 'llm', sum(1 for _, s in pr if s == 'llm'),
      'alt', sum(1 for _, s in pr if s == 'alt'))
json.dump({'due': due, 'due0': due0, 'probes': pr, 'sectors': [list(x[:3]) for x in getattr(g, 'sector_closures', [])]},
          open('/tmp/seqrep/%s_%s.json' % (world, PKG.rstrip('/').split('/')[-1]), 'w'), default=list)
