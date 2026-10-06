#!/usr/bin/env python3
"""replay.py VARIANT DUMP [PKG] [--model-only] [--fn] : re-run the merge of dumped model answers (no API calls).

DUMP is the DUTY_DUMP jsonl written by llmadapter.py ({issued, res} per section, cards in A1..D1 order).
Prints the evalreader row per card and in total; --fn lists every missed fault with its original source line."""
import json, os, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True
import evalreader
from variants import epoch

args = [a for a in sys.argv[1:] if not a.startswith('--')]
flags = {a for a in sys.argv[1:] if a.startswith('--')}
variant, dump = args[0], args[1]
pkg = args[2] if len(args) > 2 else '/home/shu/kamico/observer/work/pkgs/c33'
sys.path.insert(0, pkg)
from guider_log import GuiderLog

answers = {}
for line in open(dump):
    d = json.loads(line)
    answers.setdefault(d['issued'], []).append(d['res'])
MODEL_ONLY = '--model-only' in flags
ITEMS = []


class Replay(GuiderLog):
    def __init__(self, utc_offset_hours=0.0):
        super().__init__(utc_offset_hours)
        self.stats = {}

    def read(self, text, issued):
        if not MODEL_ONLY:
            super().read(text, issued)
        lst = answers.get(issued)
        if lst:
            res = lst.pop(0)
            if res:
                lines = [l.strip() for l in (text or '').split('\n') if l.strip()]
                for f in res.get('fault_starts', []):
                    try:
                        ITEMS.append((self.llm_time(f, issued, lines), issued, f))
                    except Exception as e:
                        ITEMS.append((None, issued, f))
                for k, v in self.add_llm(res, issued, lines=lines).items():
                    self.stats[k] = self.stats.get(k, 0) + v
        return 1

    def due(self):
        return sorted((c for c in self.cands.values() if not c['void'] and c['st'] in ('official', 'llm')),
                      key=lambda c: c['t'])

    def probes(self):
        return sorted((c for c in self.cands.values() if not c['void'] and c['st'] == 'alt'), key=lambda c: c['t'])


root = HERE / 'variants' / variant
cards = []
for card in ('A1', 'B1', 'C1', 'D1'):
    if not (root / f'{card}.log.txt').exists():
        continue
    holder = {}

    class Keep(Replay):
        def __init__(self, utc_offset_hours=0.0):
            super().__init__(utc_offset_hours)
            holder['r'] = self
    r = evalreader.evaluate_card(root, card, Keep, {}, 120.0)
    truth = json.loads((root / f'{card}.truth.json').read_text())
    rd = holder['r']
    allc = evalreader.times(rd.due()) + evalreader.times(rd.probes())
    m, _, miss = evalreader.match(sorted(set(allc)), evalreader.times(truth['faults_utc']), 120.0)
    r['any_tp'], r['any_fn'] = len(m), len(miss)
    cards.append(r)
    CARD_ITEMS = list(ITEMS)
    evalreader.print_row(f'{variant}:{card}', r)
    print('   anyR %.1f%% (%d/%d) reported-or-probed' % (100.0 * r['any_tp'] / max(1, r['any_tp'] + r['any_fn']), r['any_tp'], r['any_tp'] + r['any_fn']))
    if '--fn' in flags:
        truth = json.loads((root / f'{card}.truth.json').read_text())
        src = {}
        for ch in truth['source_changes']:
            for c in ch['candidates']:
                src.setdefault(c['t'], c['source'])
        off = truth['utc_offset_hours'] * 3600
        fp = list(r['fault_fp_epoch'])
        for t in r['fault_fn_epoch']:
            near = [x for x in fp if abs(x - t) < 3 * 86400]
            dd = ' '.join('%+.2fh' % ((x - t) / 3600) for x in sorted(near, key=lambda x: abs(x - t))[:2])
            print('   FN', time.strftime('%m/%d %H:%M', time.gmtime(t + off)), '| nearFP', dd, '|', src.get(t, '?')[:110])
            for (tc, iss, f) in ITEMS:
                if tc is not None and 0 < abs(tc - t) < 30 * 3600 and abs(iss - t) < 12 * 86400:
                    g = {k: v for k, v in f.items() if v not in ('', None, {}, '0', 0)}
                    print('        LLM %+.2fh' % ((tc - t) / 3600), json.dumps(g, ensure_ascii=False)[:260])
if cards:
    evalreader.print_row(f'{variant}:ALL', evalreader.aggregate(cards))
    at, af = sum(c['any_tp'] for c in cards), sum(c['any_fn'] for c in cards)
    print('%s:ANY %.1f %d/%d' % (variant, 100.0 * at / max(1, at + af), at, at + af))
