"""Night-log reader: some cards deliver a free-text handover log in the 'reason' field of observation requests
(Chinese / Japanese / Caesar-shifted English, times sometimes sung in solfege). The log announces instrument
faults ("engineering will work on the guide camera at 3:15, efficiency will drop -- not the sky") and confirms
them afterwards ("throughput fell to half at 3:10, not the weather, call engineering"), often right when an
earthquake confuses the numbers. This module turns those entries into fault onsets (UTC) for the reporter.

Parsing is deterministic (no network, no delay): full-width characters, Chinese numeral times and solfege
times are normalised, Caesar-shifted English lines are decoded by the shift that yields the most English
words, and two entry forms are recognised:
  * planned:  a date and a time next to guide-camera work and an efficiency drop (onset = that time);
  * occurred: a throughput drop that is "not the sky" together with a request to call engineering or file a
    ticket (onset = now: the fault is active when the entry is read).
Rumours, neighbouring observatories, conditional warnings and scheduled full stops are ignored.
Times in the log are local (the site's utc_offset_hours) unless marked UTC.  Standard library only.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

_FW = str.maketrans('０１２３４５６７８９：／（）　', '0123456789:/() ')
_CN = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '兩': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8,
       '九': 9, '十': 10}
_SOL = [('高音do', '8'), ('高音re', '9'), ('休止', '0'), ('sol', '5'), ('do', '1'), ('re', '2'), ('mi', '3'),
        ('fa', '4'), ('la', '6'), ('si', '7')]
_SOL_TOK = r'(?:高音do|高音re|休止|sol|do|re|mi|fa|la|si)'
_SOL_TIME = re.compile(r'(?<![A-Za-z])(' + _SOL_TOK + r'(?:\s*' + _SOL_TOK + r')*)\s*:\s*(' + _SOL_TOK
                       + r'(?:\s*' + _SOL_TOK + r')*)(?![A-Za-z])')
_EN_WORDS = set('the of and to in is it at on for from after before until till by with not no all sky cloud clouds '
                'thin thick haze hazy rain wind windy close closed dome open engineer engineering engineers throughput '
                'efficiency guide camera call ticket local utc update latest whole under night tonight east west north '
                'south still observable observe observing drop dropped fell down half work will be since about around '
                'expect expected forecast long range mountain ridge degrees above below fine ok stop maintenance power '
                'neighbour neighbor rumour rumor ignore this that just now last morning evening'.split())

CALL = re.compile(r'叫工程[组組]|工程[组組]上来|工程[组組]上來|工程[组組]叫上|提[单單]|打那[个個][电電]话|打那[个個][电電]話|'
                  r'那[个個][电電][话話][该該]打|[该該]打那[个個]|叫一下工程|报修|報修|报故障|報故障|联系工程|聯繫工程|聯系工程|'
                  r'找工程|通知工程|叫人来修|叫人來修|エンジニアを呼|技術班を呼|チケット|修理を頼|call (the )?engineer|file a ticket|ticket|'
                  r'report the fault')
DROP = re.compile(r'吞吐|效率|往下|跳下去|跳了一下|跳了一截|掉到|降到|只剩|下降|掉下去|下滑|走低|突降|骤降|驟降|机器的事|機器的事|'
                  r'効率|スループット|落ち|下が|硬件|硬體|掉了|掉的|hardware|throughput|efficiency')
COND = re.compile(r'一掉就|万一|萬一|要是|如果|留意|别等着|別等著|撑不了|撐不了|可能就是|多半是|たら|れば|かもしれ|if |when ')
RUMOR = re.compile(r'有人[说說]|[别別][当當]真|先[别別]信|隔壁|隣|うわさ|噂|rumou?r|neighbo')
PLAN_SUBJ = re.compile(r'[导導]星相机|[导導]星相機|[导導]星カメラ|ガイドカメラ|guide camera|工程[组組]|工程班|技術班|エンジニア|'
                       r'engineering|engineers')
PLAN_DROP = re.compile(r'效率|吞吐|効率|スループット|throughput|efficiency')
NOT_SKY = re.compile(r'不是天|不关天|不關天|与天无|與天無|跟天没|跟天沒|不在天|别以为是天|別以為是天|不要算到天|别怪天|別怪天|'
                     r'并非天|並非天|不怪天|不是天气|不是天氣|空のせいでは|天気のせいでは|not the sky|not (the )?weather')
STOP = re.compile(r'停机|停機|全停|停止|别排|別排|关顶|關頂|shut ?down')
NEG = re.compile(r'不用叫|不必叫|别叫|別叫|不需要叫|不用提|不用打|没必要|沒必要|无需|無需|不要叫|先别叫|先別叫|恢复了|恢復了|'
                 r'已经恢复|已經恢復|已恢复|修好了|已经修|已經修|已修好|no need|don\'t call|recovered|back to normal')
FIX = re.compile(r'更正|纠正|糾正|以此为准|以此為準|以这个为准|以這個為準|有误|有誤|旧图|舊圖|改一下|改过|改過|最新|correct')
CANCEL = re.compile(r'取消|改期|推迟|推遲|延期|不动了|不動了|不来了|不來了|cancel|postpone')
FAULTISH = re.compile(r'[导導]星|ガイド|工程|效率|効率|吞吐|スループット|故障|报修|報修|提[单單]|throughput|efficiency|engineer|'
                      r'guide|fault|camera')
SKIP_NEW = re.compile(r'[导導]星相[机機]|[导導]星カメラ|ガイダー|ガイドカメラ|guider|guide camera|平[场場][灯燈]|[镜鏡][盖蓋]|'
                      r'フラット|flat[- ]lamp|test window', re.I)
_QSTRIP = re.compile(r'[\s，。、,.;；:：!！?？…()（）「」『』【】\-—~～*]+')


def quote_in(quote, lines):
    """A language-model quote (>= 4 characters after normalisation) occurs in one of the log lines."""
    q = _QSTRIP.sub('', normalise(str(quote or '')).lower())
    if len(q) < 4:
        return False
    return any(q in _QSTRIP.sub('', normalise(str(ln)).lower()) for ln in lines)


WEEKDAY = re.compile(r'(下[个個]?)?(?:周|週|星期|礼拜|禮拜)([一二三四五六日天])')
DATE = re.compile(r'(?<![\d.])(\d{1,2})/(\d{1,2})(?![\d/])')
TIME = re.compile(r'(?<![\d/])(\d{1,2}):(\d{2})(?!\d)')


def _cn_num(s):
    """Chinese numerals up to 59."""
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == '十':
        return 10
    if '十' in s:
        a, b = s.split('十', 1)
        return (_CN.get(a, 1) if a else 1) * 10 + (_CN.get(b, 0) if b else 0)
    v = 0
    for ch in s:
        if ch not in _CN:
            return None
        v = v * 10 + _CN[ch]
    return v


_CN_TIME = re.compile(r'([零〇一二两兩三四五六七八九十\d]{1,3})[点點]\s*(整|半|一刻|三刻|([零〇一二三四五六七八九十\d]{1,3})分?)?')


_INVIS = dict.fromkeys(map(ord, '\u200b\u200c\u200d\u2060\ufeff\u00ad'), None)


# kaomoji are dropped into the middle of words and numbers ("1:(^_^)00", "12,( ´∀｀)000 ft"): a bracket group without
# any letter, digit, CJK character or colon (so "(周三)", "(UTC)" and "(按谱子：re : fa sol)" stay)
_KAOMOJI = re.compile(r'[ヽ┐╰٩]?\((?:[^()A-Za-z0-9:\u3040-\u30ff\u4e00-\u9fff]|[ーﾟﾉ・])*\)[ﾉ┌╯۶ノ]?|m\(_ _\)m')


def normalise(text):
    t = _KAOMOJI.sub('', text.translate(_INVIS).translate(_FW))

    def sol(m):
        def dig(g):
            out = ''
            rest = g.replace(' ', '')
            while rest:
                for k, v in _SOL:
                    if rest.startswith(k):
                        out += v
                        rest = rest[len(k):]
                        break
                else:
                    return None
            return out
        a, b = dig(m.group(1)), dig(m.group(2))
        return f'{a}:{b}' if a is not None and b is not None else m.group(0)
    t = _SOL_TIME.sub(sol, t)

    def cn(m):
        h = _cn_num(m.group(1))
        if h is None or h > 24:
            return m.group(0)
        mod = m.group(2) or ''
        if m.group(1) == '一' and not mod and m.start() > 0 and t[m.start() - 1] in '了有低高慢快多少好差些稍出头頭':
            return m.group(0)       # "低了一点" = a little lower
        if mod == '整' or mod == '':
            mi = 0
        elif mod == '半':
            mi = 30
        elif mod == '一刻':
            mi = 15
        elif mod == '三刻':
            mi = 45
        else:
            mi = _cn_num(m.group(3))
            if mi is None or mi > 59:
                return m.group(0)
        pre = t[max(0, m.start() - 3):m.start()]
        if h == 12 and re.search(r'半夜|午夜|夜里|夜裡|凌晨|深夜', pre):
            h = 0               # "半夜十二点" = midnight
        elif 6 <= h < 12 and re.search(r'晚上|傍晚|下午|夜里|夜裡', pre):
            h += 12             # "晚上十点" = 22:00
        return f'{h}:{mi:02d}'
    t0 = t
    t = _CN_TIME.sub(lambda m: cn(m), t0)
    return _MD.sub(lambda m: f'{m.group(1)}/{m.group(2)} ', t)


_MD = re.compile(r'(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号號]')


def caesar(s, k):
    out = []
    for ch in s:
        if 'a' <= ch <= 'z':
            out.append(chr((ord(ch) - 97 - k) % 26 + 97))
        elif 'A' <= ch <= 'Z':
            out.append(chr((ord(ch) - 65 - k) % 26 + 65))
        else:
            out.append(ch)
    return ''.join(out)


def decode_english(entry):
    """Caesar-shifted English (the shift is the day of the month it was written): the shift with most words."""
    letters = sum(ch.isascii() and ch.isalpha() for ch in entry)
    if letters < 12 or letters < 0.5 * sum(not ch.isspace() for ch in entry):
        return entry
    best, best_n = entry, sum(w in _EN_WORDS for w in re.findall(r'[a-z]+', entry.lower()))
    for k in range(1, 26):
        d = caesar(entry, k)
        n = sum(w in _EN_WORDS for w in re.findall(r'[a-z]+', d.lower()))
        if n > best_n:
            best, best_n = d, n
    return best


class LogReader:
    def __init__(self, utc_offset_hours=0.0, season_start=None, season_end=None):
        self.off = float(utc_offset_hours or 0.0) * 3600.0
        self.t0, self.t1 = season_start, season_end
        self.events = []          # [{'t': onset UTC epoch or None, 'kind': 'planned'|'occurred', 'src', 'seen'}]
        self.cancelled = []       # planned events withdrawn by a later entry
        self.n_msgs = self.n_entries = 0
        self._seen_txt = set()
        self.skip_new = False

    def _local(self, t):
        return datetime.fromtimestamp(t + self.off, tz=timezone.utc)

    def _pick_time(self, entry, after=0, before=None):
        times = [m for m in TIME.finditer(entry) if m.start() >= after and (before is None or m.start() < before)]
        if not times:
            return None
        m = times[0]
        hh, mm = int(m.group(1)), int(m.group(2))
        if hh > 24 or mm > 59:
            return None
        utc = 'UTC' in entry.upper()[max(0, m.start() - 14): m.end() + 14]
        return hh, mm, utc

    def _planned_onset(self, entry, issued):
        """Local date + time of announced work -> UTC epoch (a date picks the nearest year; no date -> the next such
        time, a day later for 'tomorrow night')."""
        d = DATE.search(entry)
        p = self._pick_time(entry, d.end() if d else 0) or (self._pick_time(entry) if d else None)
        if p is None:
            return None
        hh, mm, utc = p
        off = 0.0 if utc else self.off
        loc = self._local(issued) if not utc else datetime.fromtimestamp(issued, tz=timezone.utc)
        if d:
            mo, da = int(d.group(1)), int(d.group(2))
            if not (1 <= mo <= 12 and 1 <= da <= 31):
                return None
            cands = []
            for y in (loc.year - 1, loc.year, loc.year + 1):
                try:
                    cands.append(datetime(y, mo, da, tzinfo=timezone.utc))
                except ValueError:
                    pass
            if not cands:
                return None
            base = min(cands, key=lambda c: abs((c - loc).total_seconds()))
            t_loc = base + timedelta(hours=hh % 24, minutes=mm) + (timedelta(days=1) if hh == 24 else timedelta(0))
            return t_loc.timestamp() - off
        base = datetime(loc.year, loc.month, loc.day, tzinfo=timezone.utc)
        wd = WEEKDAY.search(entry)
        if wd:
            # "(下)周四 2:00": that weekday in this week (or the next one if already past) / in the next week
            target = '一二三四五六日天'.index(wd.group(2)) % 7
            ahead = (target - loc.weekday()) % 7
            if wd.group(1):
                ahead = target - loc.weekday() + 7
            t = (base + timedelta(days=ahead, hours=hh % 24, minutes=mm)).timestamp() - off
            return t if t >= issued - 6 * 3600 else t + 7 * 86400.0
        t = (base + timedelta(hours=hh % 24, minutes=mm)).timestamp() - off
        while t < issued - 2 * 3600:
            t += 86400.0
        if re.search(r'明晚|明天|明日|tomorrow', entry, re.I):
            t += 86400.0
        elif re.search(r'后天|後天|day after', entry, re.I):
            t += 2 * 86400.0
        return t

    def _occurred_onset(self, entry, issued):
        """'Throughput fell at 3:10' -> the most recent such local time before the entry was issued (or None)."""
        dm = DROP.search(entry)
        p = self._pick_time(entry, 0, dm.start() if dm else None) or self._pick_time(entry)
        if p is None:
            return None
        hh, mm, utc = p
        off = 0.0 if utc else self.off
        loc = self._local(issued) if not utc else datetime.fromtimestamp(issued, tz=timezone.utc)
        base = datetime(loc.year, loc.month, loc.day, tzinfo=timezone.utc)
        t = (base + timedelta(hours=hh % 24, minutes=mm)).timestamp() - off
        while t > issued + 1800:
            t -= 86400.0
        if issued - t > 40 * 3600:
            return None
        return t

    def onset_from_parts(self, kind, date_str, time_str, issued, quote=''):
        """UTC onset from a local 'M/D' date and 'H:MM' time (None if unusable); without a date the quote's weekday
        or relative words ('明晚') decide the day."""
        tm = TIME.search(normalise(str(time_str or '')))
        if not tm:
            return None
        d = DATE.search(normalise(str(date_str or '')))
        rel = ''
        if not d:
            q = normalise(str(quote or ''))
            w = WEEKDAY.search(q)
            rel = (w.group(0) + ' ') if w else ' '.join(re.findall(r'明晚|明天|明日|后天|後天|tomorrow', q, re.I)) + ' '
        s = (f'{d.group(1)}/{d.group(2)} ' if d else rel) + f'{tm.group(1)}:{tm.group(2)}'
        if kind == 'planned':
            return self._planned_onset(s, issued)
        return self._occurred_onset(s, issued)

    def read(self, text, issued):
        """Parse one request's log text issued at `issued` (UTC epoch); returns the new events."""
        self.n_msgs += 1
        new = []
        self.last_unread = []     # fault-ish lines nothing below recognised (for the language-model fallback)
        for raw in (text or '').split('\n'):
            raw = raw.strip()
            if not raw or raw in self._seen_txt:
                continue
            self._seen_txt.add(raw)
            self.n_entries += 1
            e = normalise(decode_english(raw.translate(_INVIS)))
            low = e.lower()
            n_before = len(new)
            if RUMOR.search(low):
                continue
            if self.skip_new and SKIP_NEW.search(e):
                continue          # guider-camera jobs and flat-lamp tests: guider_log.GuiderLog reads them
            self._classify(e, low, raw, issued, new)
            if len(new) == n_before and FAULTISH.search(low) and not STOP.search(low):
                self.last_unread.append(e[:300])
        return self._commit(new)

    def _classify(self, e, low, raw, issued, new):
        """One normalised entry: append a planned or occurred fault event to `new`."""
        plan_like = ((PLAN_SUBJ.search(low) or NOT_SKY.search(low)) and PLAN_DROP.search(low) and not STOP.search(low)
                     and TIME.search(e)
                     # "if throughput ever drops, it is probably the camera": a guess, unless dated engineering work
                     and (not COND.search(low) or (DATE.search(e) and re.search(r'工程|engineer', low))))
        if plan_like and CANCEL.search(low) and not CALL.search(low):
            # announced work withdrawn or moved: drop pending planned events near the date mentioned
            t = self._planned_onset(e, issued) if not re.search(r'不动了|不動了|cancel', low) else None
            for ev in self.events:
                if ev['kind'] == 'planned' and not ev.get('void') and ev['t'] > issued - 3600 and (
                        t is None or abs(ev['t'] - t) < 4 * 86400):
                    ev['void'] = True
                    self.cancelled.append(ev)
            if t is None:
                return
        if plan_like and not CALL.search(low) and not NEG.search(low):
            t = self._planned_onset(e, issued)
            if t is not None and issued - 6 * 3600 <= t <= issued + 20 * 86400:
                if FIX.search(low):
                    # a correction supersedes recent planned events within a few days of it
                    for ev in self.events:
                        if (ev['kind'] == 'planned' and not ev.get('void') and issued - ev['seen'] < 3 * 86400
                                and abs(ev['t'] - t) < 3 * 86400 and abs(ev['t'] - t) > 1800):
                            ev['void'] = True
                            self.cancelled.append(ev)
                new.append({'t': t, 'kind': 'planned', 'src': raw[:120], 'seen': issued})
            return
        if CALL.search(low) and DROP.search(low) and not COND.search(low) and not NEG.search(low):
            new.append({'t': self._occurred_onset(e, issued), 'kind': 'occurred', 'src': raw[:120], 'seen': issued})

    def _commit(self, new):
        if any(ev['kind'] == 'occurred' and ev['t'] is not None for ev in new):
            # an untimed confirmation next to a timed one in the same note is the same fault
            new = [ev for ev in new if ev['kind'] != 'occurred' or ev['t'] is not None]
        out = []
        for ev in new:
            if self.t1 is not None and ev['t'] is not None and ev['t'] > self.t1:
                continue
            if ev['t'] is not None and any(abs(ev['t'] - o['t']) < 2 * 3600 and ev['kind'] == o['kind']
                                           and not o.get('void') for o in self.events if o['t'] is not None):
                continue
            self.events.append(ev)
            out.append(ev)
        return out
