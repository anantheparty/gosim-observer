"""GuiderLog-compatible reader for evalreader.py: the c32 agent's duty-log reading = deterministic parser plus the
language-model reader (llm_strategist.DutyReader, merged with guider_log.add_llm). due() lists the stated jobs and
the model's confirmed times (the agent reports the latter once a short exposure confirms the throughput drop)."""
import json, os, re, sys, time
DUMP = os.environ.get('DUTY_DUMP')
PKG = os.environ.get('DUTY_PKG', '/home/shu/kamico/observer/work/pkgs/c32')
sys.path.insert(0, PKG)
from guider_log import GuiderLog, prep
from llm_strategist import DutyReader
from log_reader import decode_english, _INVIS, _FW
TM = re.compile(r'\d{1,2}:\d{2}')


class Merged(GuiderLog):
    def __init__(self, utc_offset_hours=0.0, model_only=False, **kw):
        super().__init__(utc_offset_hours)
        self.rd = DutyReader(model=os.environ.get('DUTY_MODEL') or None, wall_cap=1e9, max_calls=10 ** 6)
        self.model_only = bool(model_only)
        self.llm_stats = {}

    def read(self, text, issued):
        if not self.model_only:
            super().read(text, issued)
        lines = [l.strip() for l in (text or '').split('\n') if l.strip()][:400]
        if not lines:
            return 0
        hints = {}
        for i, raw in enumerate(lines):
            r0 = raw.translate(_INVIS).translate(_FW)
            e = prep(raw)
            if decode_english(r0) != r0 or TM.findall(e) != TM.findall(r0):
                hints[str(i)] = re.sub(r'^\s*【[^】]{1,8}】', '', e)[:300]
        off = self.off * 3600.0
        fmt = lambda t: time.strftime('%m/%d %H:%M', time.gmtime(t + off))
        args = (lines, hints, time.strftime('%Y-%m-%d %H:%M (%A)', time.gmtime(issued + off)), self.off,
                self.known_summary(issued, fmt))
        try:
            res = self.rd.read(*args, issued=issued)
        except TypeError:
            res = self.rd.read(*args)
        if DUMP:
            with open(DUMP, 'a') as fh:
                fh.write(json.dumps({'issued': issued, 'res': res}, ensure_ascii=False) + '\n')
        if res:
            try:
                n = self.add_llm(res, issued, lines=lines)
            except TypeError:
                n = self.add_llm(res, issued)
            for k, v in n.items():
                self.llm_stats[k] = self.llm_stats.get(k, 0) + v
        return 1

    def due(self):
        return sorted((c for c in self.cands.values() if not c['void'] and c['st'] in ('official', 'llm')),
                      key=lambda c: c['t'])

    def probes(self):
        return sorted((c for c in self.cands.values() if not c['void'] and c['st'] == 'alt'), key=lambda c: c['t'])
