"""GuiderLog-compatible reader for evalreader.py that replays dumped model answers (llmadapter.py with DUTY_DUMP)
instead of asking the model: the same answers converted by another guider_log (DUTY_PKG), or with the c40
window-shift fallback switched off (NOFIX=1), so two conversions can be compared on identical model output."""
import json, os, sys
PKG = os.environ.get('DUTY_PKG', '/home/shu/kamico/observer/work/pkgs/c40')
DUMP = os.environ['DUTY_DUMP']
NOFIX = os.environ.get('NOFIX') == '1'
sys.path.insert(0, PKG)
from guider_log import GuiderLog

ANS = {}
for _l in open(DUMP):
    _j = json.loads(_l)
    ANS[round(_j['issued'])] = _j['res']


class Replay(GuiderLog):
    def __init__(self, utc_offset_hours=0.0, **kw):
        super().__init__(utc_offset_hours)
        if NOFIX:
            self._rel_shift = lambda f, lines: 0
        self.llm_stats = {}

    def read(self, text, issued):
        super().read(text, issued)
        lines = [l.strip() for l in (text or '').split('\n') if l.strip()][:400]
        res = ANS.get(round(issued))
        if lines and res:
            n = self.add_llm(res, issued, lines=lines)
            for k, v in n.items():
                self.llm_stats[k] = self.llm_stats.get(k, 0) + v
        return 1

    def due(self):
        return sorted((c for c in self.cands.values() if not c['void'] and c['st'] in ('official', 'llm')),
                      key=lambda c: c['t'])

    def probes(self):
        return sorted((c for c in self.cands.values() if not c['void'] and c['st'] == 'alt'), key=lambda c: c['t'])
