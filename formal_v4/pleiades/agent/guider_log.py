"""Guider-camera schedule from the handover log (cards where the engineering crew works on the guider camera many
times a season).  Each piece of work starts an instrument fault at the announced moment: the throughput first drops
to about a third and after an hour to almost nothing, and it stays there until a fault report repairs it.  The log
also lists flat-lamp / mirror-cover tests (three windows a night): frames taken then are lost, but they are no fault
and a report there is a false report.

The log states every job several times (Chinese notice, Japanese, Caesar-shifted English, a UTC or Tokyo-time or
other-zone restatement, a sung solfege time, "再念一遍") and mixes in distractors: rumours, a colleague's misremembered
times (questions), corrections ("X 不对，是 Y"), cancellations, postponements ("原定 X，推迟一个半小时"), jobs relative
to the night's first flat-lamp window or to another day's job ("比 1/18 那次晚一小时十五分"), and rain postponements
("要是那晚下雨就顺延一天").  This module keeps a candidate table keyed by the UTC minute:
  official  -- stated as a fact (any language / zone);  void -- cancelled, corrected away or postponed from;
  unsure    -- rumour or a question;                    alt  -- the rain-postponed alternative of an official job.
`due()` gives the jobs to report; `probes()` the moments worth a short look (unsure / alternatives).
Deterministic, standard library only.
"""
from __future__ import annotations

import bisect
import math
import re
from datetime import datetime, timedelta, timezone

from log_reader import normalise, decode_english, _INVIS, DATE, TIME
try:
    from when_text import date_from_text, time_from_text
except Exception:          # pragma: no cover - the model's own numbers are used instead
    date_from_text = time_from_text = None

GUIDER = re.compile(r'[导導]星相[机機]|[导導]星カメラ|ガイダー|ガイドカメラ|guider|guide camera', re.I)
FLAT = re.compile(r'平[场場]|[镜鏡][盖蓋]|フラット|flat[- ]?lamp|flat test|test window|flat', re.I)
UNSURE = re.compile(r'听说|聽說|听說|聽说|传言|傳言|有人[说說]|没确认|沒确认|沒確認|没確認|未确认|未確認|[别別][当當]真|先[别別]信|'
                    r'[别別]急[着著]信|噂|うわさ|rumou?r|unconfirmed|not confirmed|hearsay|i heard|heard that|'
                    r'[？?]|吗|嗎|对吧|對吧|是不是|莫非|难道|難道|来着|來著|会不会|會不會|我记得|我記得|好像|大概|也许|也許|'
                    r'吧|呢|かな|だっけ|でしょうか|maybe|perhaps|i think|isn\'t it|right\?')
CANCEL = re.compile(r'取消|不动了|不動了|不会动|不會動|不动，|不動，|不动。|不動。|中止|キャンセル|cancel|called off|scrapped|'
                    r'will not happen|won\'t happen|is off\b')
POSTPONE = re.compile(r'推迟|推遲|延后|延後|postpone|pushed back|delayed by|moved back|繰り下げ|遅らせ|延期|遅れ')
RAIN = re.compile(r'下雨|雨天|雨の|rains?\b|rainy')
CORR = re.compile(r'不对|不對|有误|有誤|记错|記錯|记岔|記岔|是错的|是錯的|弄错|弄錯|记混|記混|搞错|搞錯|订正|訂正|更正|'
                  r'wrong|mistaken|mistake|間違|誤り|correction')
STOP = re.compile(r'停机|停機|全停|关顶|關頂|shut ?down|停止|设备停|設備停')
REL_FLAT = re.compile(r'第\s*([一二三四1-4])\s*段|test window (?:no\.?|number|#)\s*([1-4])\b|(first|second|third) (?:flat|test) window|'
                      r'window (?:no\.?|number|#)\s*([1-4])\b|([1-4一二三])つ目')
_ORD = {'一': 1, '二': 2, '三': 3, '四': 4, '1': 1, '2': 2, '3': 3, '4': 4, 'first': 1, 'second': 2, 'third': 3}
SAME = re.compile(r'相同|同一[时時][间間刻]|同じ時刻|same (?:local |clock )?(?:clock )?time')
EARLY = re.compile(r'早\s*(?=[\d零〇一二两兩三四五六七八九十半])|earlier')
LATE = re.compile(r'晚\s*(?=[\d零〇一二两兩三四五六七八九十半])|later')
TZ_OFF = re.compile(r'UTC\s*([+\-−－])\s*(\d{1,2})(?::?(\d{2}))?', re.I)
TZ_TOKYO = re.compile(r'东京|東京|tokyo|日本時間|日本时间|JST', re.I)
TZ_UTC = re.compile(r'UTC|GMT|格林', re.I)
LOCAL_WORD = re.compile(r'本地|当地|當地|local|現地', re.I)
_JP_HM = re.compile(r'(\d{1,2})\s*時\s*(\d{1,2})\s*分')
_JP_HALF = re.compile(r'(\d{1,2})\s*時\s*半')
_JP_H = re.compile(r'(\d{1,2})\s*時(?![\d間])')
_EN_ON = re.compile(r'(\d{1,2}):(\d{2})(?:[^\d/:]|UTC\s*[+\-−]\s*\d{1,2}){0,40}?\bon\s+(?:the\s+)?(\d{1,2})/(\d{1,2})', re.I)

_CN_D = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '兩': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
_EN_N = {'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8,
         'nine': 9, 'ten': 10, 'fifteen': 15, 'twenty': 20, 'thirty': 30, 'forty': 40, 'forty-five': 45, 'fifty': 50}


def _cn_int(s):
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s in ('半',):
        return None
    if '十' in s:
        a, b = s.split('十', 1)
        return (_CN_D.get(a, 1) if a else 1) * 10 + (_CN_D.get(b, 0) if b else 0)
    v = 0
    for ch in s:
        if ch not in _CN_D:
            return None
        v = v * 10 + _CN_D[ch]
    return v


_NUM_CN = r'[零〇一二两兩三四五六七八九十\d]+'
_DUR_PATS = [
    # (regex, kind): a 'X个半小时'  b 'X小时Y分'  c '半小时'  d 'Y分钟'  e 'X and a half hours'  f 'X hours (and Y minutes)'
    (re.compile(r'(' + _NUM_CN + r')\s*(?:个|個)?半\s*(?:小[时時]|钟头|鐘頭|時間)'), 'a'),
    (re.compile(r'(' + _NUM_CN + r')\s*(?:个|個)?\s*(?:小[时時]|钟头|鐘頭|時間)(?:\s*(' + _NUM_CN + r')\s*分(?:[钟鐘])?)?'), 'b'),
    (re.compile(r'半\s*(?:个|個)?\s*(?:小[时時]|钟头|鐘頭|時間)'), 'c'),
    (re.compile(r'(' + _NUM_CN + r')\s*分(?:[钟鐘]|間)?'), 'd'),
    (re.compile(r'\b(an?|one|two|three|four|five|\d+)\s+and\s+a\s+half\s+hours?', re.I), 'e'),
    (re.compile(r'\b(an?|one|two|three|four|five|six|\d+)\s+hours?(?:\s*(?:and\s+)?(a half|\d+|fifteen|thirty|forty-five|'
                r'twenty|forty|fifty|ten)\s*(?:minutes?|mins?)?)?', re.I), 'f'),
    (re.compile(r'\bhalf an hour\b', re.I), 'c'),
    (re.compile(r'\b(\d+|fifteen|thirty|forty-five|twenty|forty|fifty|ten)\s*(?:minutes?|mins?)\b', re.I), 'd'),
]


def _en_or_cn(g):
    g = g.strip().lower()
    if g.isdigit():
        return int(g)
    if g in _EN_N:
        return _EN_N[g]
    return _cn_int(g)


def duration_minutes(text):
    """Earliest duration in the text, in minutes ('一个半小时' 90, '两小时四十五分' 165, 'two and a half hours' 150,
    'an hour and 15 minutes' 75, 'half an hour' 30)."""
    best = None
    for rx, kind in _DUR_PATS:
        for m in rx.finditer(text):
            v = None
            if kind == 'a':
                h = _en_or_cn(m.group(1))
                v = None if h is None else int(round((h + 0.5) * 60))
            elif kind == 'b':
                h = _en_or_cn(m.group(1))
                mi = _en_or_cn(m.group(2)) if m.group(2) else 0
                v = None if h is None or mi is None else h * 60 + mi
            elif kind == 'c':
                v = 30
            elif kind == 'd':
                v = _en_or_cn(m.group(1))
            elif kind == 'e':
                h = _en_or_cn(m.group(1))
                v = None if h is None else int(round((h + 0.5) * 60))
            elif kind == 'f':
                h = _en_or_cn(m.group(1))
                mi = 0
                if m.group(2):
                    g = m.group(2).lower()
                    mi = 30 if g == 'a half' else _en_or_cn(g)
                v = None if h is None or mi is None else h * 60 + mi
            if v is None or v <= 0 or v > 12 * 60:
                continue
            key = (m.start(), -(m.end() - m.start()))
            if best is None or key < best[0]:
                best = (key, v)
            break
    return None if best is None else best[1]


def prep(raw):
    """Normalised entry (kaomoji, full width, solfege, Chinese numeral times, Caesar English, Japanese 時/分)."""
    e = normalise(decode_english(raw.translate(_INVIS)))
    e = _JP_HM.sub(lambda m: f'{int(m.group(1))}:{int(m.group(2)):02d}', e)
    e = _JP_HALF.sub(lambda m: f'{int(m.group(1))}:30', e)
    e = _JP_H.sub(lambda m: f'{int(m.group(1))}:00', e)
    e = re.sub(r'(\d{1,2})/(\d{1,2})の', r'\1/\2 ', e)
    return e


def date_time_pairs(e):
    """(month, day, hour, minute, pos) for each date with its time ('10/5(周一)1:00', '1:30 on 10/9')."""
    out = []
    used_t, used_d = set(), set()
    for m in _EN_ON.finditer(e):
        out.append((int(m.group(3)), int(m.group(4)), int(m.group(1)), int(m.group(2)), m.start()))
        used_t.add(m.start(1))
        used_d.add(m.start(3))
    dates = [d for d in DATE.finditer(e)]
    times = [t for t in TIME.finditer(e) if t.start() not in used_t]
    for i, d in enumerate(dates):
        if d.start() in used_d:
            continue
        nxt_d = dates[i + 1].start() if i + 1 < len(dates) else len(e)
        cand = [t for t in times if d.end() <= t.start() < min(nxt_d, d.end() + 60)]
        if cand:
            t = cand[0]
            out.append((int(d.group(1)), int(d.group(2)), int(t.group(1)), int(t.group(2)), d.start()))
    out.sort(key=lambda x: x[4])
    return out


class GuiderLog:
    def __init__(self, utc_offset_hours=0.0, season_start=None, season_end=None):
        self.off = float(utc_offset_hours or 0.0)
        self.t0, self.t1 = season_start, season_end
        self.cands = {}           # minute key -> {'t', 'st': official|unsure|alt, 'void', 'src', 'seen', 'date'}
        self.flats = {}           # (start, end) -> night date (y, m, d)
        self.flat_nights = {}     # night date -> sorted [(start, end)]
        self.rel_flat = []        # pending: (night date, minutes, seen, src)
        self.rel_other = []       # pending: (target date, ref date, minutes signed, seen, src)
        self.rain = []            # official jobs that move a day later if it rains that night
        self.n_lines = 0
        self.unparsed = []
        self.seen_txt = set()
        self.active = False       # the log announced guider-camera work at all
        self.ver = 0              # bumped on every change of the tables (query caches)
        self._cache = {}

    # ------------------------------------------------------------------ time helpers
    def _year_for(self, mo, da, issued):
        loc = datetime.fromtimestamp(issued + self.off * 3600.0, tz=timezone.utc)
        best = None
        for y in (loc.year - 1, loc.year, loc.year + 1):
            try:
                c = datetime(y, mo, da, tzinfo=timezone.utc)
            except ValueError:
                continue
            if best is None or abs((c - loc).total_seconds()) < abs((best - loc).total_seconds()):
                best = c
        return best

    def _utc(self, mo, da, hh, mi, tz, issued):
        if not (1 <= mo <= 12 and 1 <= da <= 31 and 0 <= hh <= 24 and 0 <= mi <= 59):
            return None
        base = self._year_for(mo, da, issued)
        if base is None:
            return None
        return (base + timedelta(hours=hh, minutes=mi)).timestamp() - tz * 3600.0

    def _tz(self, e, pos=0):
        m = TZ_OFF.search(e)
        if m:
            h = int(m.group(2)) + (int(m.group(3)) / 60.0 if m.group(3) else 0.0)
            return -h if m.group(1) in '-−－' else h
        if TZ_TOKYO.search(e):
            return 9.0
        if TZ_UTC.search(e) and not re.search(r'不是\s*UTC|not UTC', e, re.I):
            return 0.0
        return self.off

    def _night_date(self, mo, da, issued):
        b = self._year_for(mo, da, issued)
        return None if b is None else (b.year, b.month, b.day)

    # ------------------------------------------------------------------ table
    def _key(self, t):
        return int(round(t / 60.0))

    def _add(self, t, st, seen, src, date=None):
        if t is None:
            return
        self.ver += 1
        if self.t1 is not None and t > self.t1 + 86400:
            return
        k = self._key(t)
        c = self.cands.get(k)
        if c is None:
            self.cands[k] = {'t': float(k * 60), 'st': st, 'void': False, 'src': src[:100], 'seen': seen, 'n': 1,
                             'date': date, 'last': seen}
            return
        c['n'] += 1
        c['last'] = seen
        rank = {'unsure': 0, 'llm': 1, 'alt': 1, 'official': 2}
        if rank[st] > rank[c['st']]:
            c['st'] = st
            c['src'] = src[:100]
        if date and not c.get('date'):
            c['date'] = date

    def _void(self, t, why):
        if t is None:
            return
        self.ver += 1
        k = self._key(t)
        for kk in (k - 1, k, k + 1):
            c = self.cands.get(kk)
            if c is not None:
                c['void'] = why
        if k not in self.cands:
            self.cands[k] = {'t': float(k * 60), 'st': 'unsure', 'void': why, 'src': '', 'seen': 0.0, 'n': 0,
                             'date': None}

    # ------------------------------------------------------------------ reading
    def read(self, text, issued):
        """One request's log text (UTC epoch `issued`). Returns the number of guider / flat lines read."""
        n = 0
        for raw in (text or '').split('\n'):
            raw = raw.strip()
            if not raw or raw in self.seen_txt:
                continue
            self.seen_txt.add(raw)
            self.n_lines += 1
            e = prep(raw)
            sp = re.match(r'\s*【([^】]{1,8})】', e)
            body = e[sp.end():] if sp else e
            try:
                if self._line(body, issued, raw):
                    n += 1
            except Exception:
                self.unparsed.append(raw[:200])
        self._resolve(issued)
        return n

    def _line(self, e, issued, raw):
        low = e.lower()
        g = GUIDER.search(e)
        if g:
            self.active = True
        if FLAT.search(e) and not (g and REL_FLAT.search(e)):
            if g and not re.search(r'平[场場][灯燈]?[^，。]{0,6}(测试|測試)|フラット試験|flat-lamp tests?', e, re.I):
                pass        # a guider line that only mentions "the flat-lamp windows are not faults"
            else:
                return self._flat_line(e, issued, raw)
        if not g:
            return False
        if STOP.search(e) and not re.search(r'报修|報修|故障|report', e, re.I):
            return False                      # a scheduled stop for a guider swap (a closure, not a fault)
        pairs = date_time_pairs(e)
        tz = self._tz(e)
        rf = REL_FLAT.search(e)
        if rf:
            d = DATE.search(e)
            ordv = next((g for g in rf.groups() if g), '1')
            nth = _ORD.get(ordv.lower(), 1)
            txt = (e[:d.start()] + ' ' + e[d.end():]) if d else e
            txt = txt.replace(rf.group(0), ' ')
            mins = duration_minutes(txt)
            if d and mins is not None:
                nd = self._night_date(int(d.group(1)), int(d.group(2)), issued)
                self.rel_flat.append((nd, nth, mins, issued, raw))
                return True
            self.unparsed.append(raw[:200])
            return False
        dates = list(DATE.finditer(e))
        if SAME.search(e) or (len(dates) >= 2 and not pairs and re.search(r'比|than|より', e)):
            if len(dates) >= 2:
                tgt = self._night_date(int(dates[0].group(1)), int(dates[0].group(2)), issued)
                ref = self._night_date(int(dates[1].group(1)), int(dates[1].group(2)), issued)
                if SAME.search(e):
                    sgn_m = 0
                else:
                    mins = duration_minutes(e[dates[0].end():dates[1].start()] + ' ' + e[dates[1].end():])
                    if mins is None:
                        self.unparsed.append(raw[:200])
                        return False
                    after = e[dates[0].end():]
                    me, ml = EARLY.search(after), LATE.search(after)
                    if me is None and ml is None:
                        self.unparsed.append(raw[:200])
                        return False
                    sgn = -1 if me is not None and (ml is None or me.start() < ml.start()) else 1
                    sgn_m = sgn * mins
                self.rel_other.append((tgt, ref, sgn_m, issued, raw))
                return True
        if not pairs:
            if re.search(r'\d{1,2}:\d{2}', e) or DATE.search(e):
                self.unparsed.append(raw[:200])
            return False
        if CANCEL.search(low):
            for (mo, da, hh, mi, _) in pairs:
                self._void(self._utc(mo, da, hh, mi, tz, issued), 'cancel')
            return True
        if POSTPONE.search(low) and not RAIN.search(low):
            mins = duration_minutes(e[pairs[0][4]:]) or duration_minutes(e)
            mo, da, hh, mi, _ = pairs[0]
            t = self._utc(mo, da, hh, mi, tz, issued)
            if t is not None and mins is not None:
                self._void(t, 'postponed')
                self._add(t + mins * 60.0, 'official', issued, raw, date=(mo, da))
                return True
            self.unparsed.append(raw[:200])
            return False
        if RAIN.search(low) and re.search(r'顺延|順延|一天|postpone|next day|a day later|翌日', low):
            mo, da, hh, mi, _ = pairs[0]
            t = self._utc(mo, da, hh, mi, tz, issued)
            if t is not None:
                # done on that day unless it rains then: probe both days, the throughput tells which one it was
                self.rain.append(t)
                self._add(t, 'alt', issued, raw, date=(mo, da))
                self._add(t + 86400.0, 'alt', issued, raw)
            return True
        if CORR.search(low) and len(pairs) >= 2:
            for (mo, da, hh, mi, _) in pairs[:-1]:
                self._void(self._utc(mo, da, hh, mi, tz, issued), 'wrong')
            mo, da, hh, mi, _ = pairs[-1]
            self._add(self._utc(mo, da, hh, mi, tz, issued), 'official', issued, raw, date=(mo, da))
            return True
        if UNSURE.search(low):
            for (mo, da, hh, mi, _) in pairs:
                self._add(self._utc(mo, da, hh, mi, tz, issued), 'unsure', issued, raw)
            return True
        for (mo, da, hh, mi, _) in pairs[:1]:
            self._add(self._utc(mo, da, hh, mi, tz, issued), 'official', issued, raw, date=(mo, da))
        return True

    def _flat_line(self, e, issued, raw):
        d = DATE.search(e)
        if not d:
            return False
        nd = self._night_date(int(d.group(1)), int(d.group(2)), issued)
        if nd is None:
            return False
        tz = self._tz(e)
        rest = e[d.end():]
        rng = re.findall(r'(\d{1,2}):(\d{2})\s*(?:到|至|–|—|-|〜|~|～|から|to|until|till)\s*(\d{1,2}):(\d{2})', rest)
        if not rng:
            self.unparsed.append(raw[:200])
            return False
        base = datetime(nd[0], nd[1], nd[2], tzinfo=timezone.utc)
        out = []
        for h1, m1, h2, m2 in rng:
            h1, m1, h2, m2 = int(h1), int(m1), int(h2), int(m2)
            a = base + timedelta(days=1 if h1 < 12 else 0, hours=h1, minutes=m1)
            b = base + timedelta(days=1 if h2 < 12 else 0, hours=h2, minutes=m2)
            if b <= a:
                b += timedelta(days=1)
            ta, tb = a.timestamp() - tz * 3600.0, b.timestamp() - tz * 3600.0
            if tb - ta > 4 * 3600:
                continue
            out.append((ta, tb))
            self.flats[(ta, tb)] = nd
        if out:
            lst = sorted(set(self.flat_nights.get(nd, []) + out))
            self.flat_nights[nd] = lst
            self.ver += 1
        return bool(out)

    def _resolve(self, issued):
        keep = []
        for nd, nth, mins, seen, raw in self.rel_flat:
            w = self.flat_nights.get(nd)
            if w and len(w) >= nth:
                self._add(w[nth - 1][1] + mins * 60.0, 'official', seen, raw)
            elif issued - seen < 3 * 86400:
                keep.append((nd, nth, mins, seen, raw))
        self.rel_flat = keep
        keep = []
        for tgt, ref, sm, seen, raw in self.rel_other:
            refs = []
            for c in self.cands.values():
                if c['st'] != 'official' or c['void']:
                    continue
                lt = datetime.fromtimestamp(c['t'] + self.off * 3600.0, tz=timezone.utc)
                if (lt.year, lt.month, lt.day) == tuple(ref):
                    refs.append(c)
            if refs:
                c = max(refs, key=lambda c: c['t'])        # "the 2/23 one above": that day's latest job
                lt = datetime.fromtimestamp(c['t'] + self.off * 3600.0, tz=timezone.utc)
                base = datetime(tgt[0], tgt[1], tgt[2], tzinfo=timezone.utc)
                t = (base + timedelta(hours=lt.hour, minutes=lt.minute + sm)).timestamp() - self.off * 3600.0
                self._add(t, 'alt', seen, raw, date=(tgt[1], tgt[2]))
            elif issued - seen < 3 * 86400:
                keep.append((tgt, ref, sm, seen, raw))
        self.rel_other = keep

    def _tz_of(self, c):
        return self.off

    # ------------------------------------------------------------------ language-model schedule
    def _clock(self, clock):
        """Hours east of UTC of a clock named by the model ('local', 'UTC', 'UTC+9', 'Tokyo', 'UTC-13')."""
        if clock is None or clock == '':
            return self.off
        if not isinstance(clock, str) or len(clock) > 160:
            return None
        c = clock.strip()
        m = TZ_OFF.search(c)
        if m:
            h = int(m.group(2)) + (int(m.group(3)) / 60.0 if m.group(3) else 0.0)
            if h > 14 or (m.group(3) and int(m.group(3)) >= 60) or m.end() < len(c) and c[m.end()].isdigit():
                return None
            return -h if m.group(1) in '-−－' else h
        if TZ_TOKYO.fullmatch(c):
            return 9.0
        if re.fullmatch(r'UTC|GMT|世界时|協定世界時', c, re.I):
            return 0.0
        return self.off if re.fullmatch(r'local(?: time)?|本地|本站|当地|當地|現地', c, re.I) else None

    @staticmethod
    def _md(v):
        if not isinstance(v, str) or len(v) > 32:
            return None
        m = re.fullmatch(r'\s*(\d{1,2})\s*/\s*(\d{1,2})\s*', v)
        if m:
            mo, da = map(int, m.groups())
            try:
                datetime(2000, mo, da)  # permit Feb 29; _year_for checks the actual year
                return mo, da
            except ValueError:
                pass
        return None

    @staticmethod
    def _hm(v):
        if not isinstance(v, str) or len(v) > 32:
            return None
        m = re.fullmatch(r'\s*(\d{1,2})\s*:\s*(\d{2})\s*', v)
        if m:
            hh, mi = map(int, m.groups())
            if (0 <= hh < 24 and 0 <= mi < 60) or (hh, mi) == (24, 0):
                return hh, mi
        return None

    @staticmethod
    def _int(v, default=0):
        if v is None or v == '':
            return default
        if isinstance(v, bool) or not isinstance(v, (str, int, float)):
            return None
        if isinstance(v, str) and len(v) > 64 or isinstance(v, int) and v.bit_length() > 32:
            return None
        try:
            value = float(v)
            return int(value) if math.isfinite(value) and value.is_integer() else None
        except (TypeError, ValueError, OverflowError):
            return None

    def _night_windows(self, nd):
        if not isinstance(nd, tuple) or len(nd) != 3 or not all(type(x) is int for x in nd):
            return []
        rule = sorted(set(self.flat_nights.get(nd, [])))
        out = list(rule)
        for w in sorted(set(getattr(self, '_llm_nights', {}).get(nd, []))):
            # a model window that repeats one the parser or the model already gave (even a minute off) would
            # shift "the second test window" references: keep only genuinely additional windows
            if not any(x < w[1] and w[0] < y for (x, y) in out):
                out.append(w)
        return sorted(out)

    @staticmethod
    def _label(v):
        if not isinstance(v, str) or len(v) > 160:
            return ''
        k = re.sub(r'[\s\-‐－—_·.#№:：/()（）\[\]【】「」"\'“”]+', '', str(v or '')).upper()
        return k if 2 <= len(k) <= 40 else ''

    def _label_window(self, label, issued):
        """The one window registered under this label near `issued` (None if unknown or ambiguous)."""
        k = self._label(label)
        if not k:
            return None
        hits = {(a, b) for (a, b, seen) in getattr(self, '_labels', {}).get(k, []) if abs(a - issued) < 14 * 86400}
        return next(iter(hits)) if len(hits) == 1 else None

    _NIGHT_W = re.compile(r'当晚|當晚|那晚|那天晚上|晚上|夜|night|evening|tonight', re.I)

    def _d0(self, issued):
        return datetime.fromtimestamp(issued + self.off * 3600.0, tz=timezone.utc).date()

    def _date_of(self, f, issued, key='date'):
        """(month, day) of an item: the verbatim date_text read by code when possible, else the model's M/D."""
        if not isinstance(f, dict):
            return None
        md = self._md(f.get(key))
        txt = f.get('date_text')
        if date_from_text is not None and isinstance(txt, str) and txt.strip():
            try:
                c = date_from_text(txt, self._d0(issued))
            except Exception:
                c = None
            if c is not None:
                if md is not None and c != md:
                    self.llm_fix = getattr(self, 'llm_fix', 0) + 1
                return c
        return md

    def _time_of(self, f, key='time', text_key='time_text'):
        if not isinstance(f, dict):
            return None
        hm = self._hm(f.get(key))
        txt = f.get(text_key)
        if time_from_text is not None and isinstance(txt, str) and txt.strip():
            try:
                c = time_from_text(txt)
            except Exception:
                c = None
            if c is not None:
                if hm is not None and c != hm:
                    self.llm_fix = getattr(self, 'llm_fix', 0) + 1
                return c
        return hm

    @staticmethod
    def _src_line(quote, lines):
        """Prefer a unique complete quote; ambiguous short prefixes give no evidence."""
        if not isinstance(quote, str) or not isinstance(lines, list) or len(quote) > 4096:
            return None
        q = re.sub(r'\s+', '', quote)
        if len(q) < 4:
            return None
        source = [(ln, re.sub(r'\s+', '', ln)) for ln in lines[:400]
                  if isinstance(ln, str) and len(ln) <= 12000]
        hits = {ln for ln, normalized in source if q in normalized}
        if len(hits) == 1:
            return next(iter(hits))
        if hits:
            return None
        hits = {ln for ln, normalized in source if q[:16] in normalized and q[-16:] in normalized}
        return next(iter(hits)) if len(hits) == 1 else None

    def _when(self, f, hm, tz, issued, lines=None):
        """UTC epoch of an as-written time: calendar date `date`, or `night` (after-midnight times on the next day)."""
        if not isinstance(f, dict) or not isinstance(hm, tuple) or len(hm) != 2 or tz is None:
            return None
        if not all(type(x) is int for x in hm) or not (0 <= hm[0] < 24 and 0 <= hm[1] < 60 or hm == (24, 0)):
            return None
        if isinstance(tz, bool) or not isinstance(tz, (int, float)) or not math.isfinite(tz) or abs(tz) > 14:
            return None
        txt = f.get('date_text') if isinstance(f.get('date_text'), str) else ''
        nm = self._md(f.get('night'))
        md = self._date_of(f, issued)
        night = nm is not None and (md is None or (md == nm and self._NIGHT_W.search(txt)))
        if night and hm[0] < 12 and lines:
            src = self._src_line(f.get('quote'), lines)
            if src is not None and not self._NIGHT_W.search(src):
                night, md = False, md or nm          # the line gives a calendar date, not a night
        if not night:
            if md is None:
                return None
            return self._utc(md[0], md[1], hm[0], hm[1], tz, issued)
        t = self._utc(nm[0], nm[1], hm[0], hm[1], tz, issued)
        return None if t is None else t + (86400.0 if hm[0] < 12 else 0.0)

    _REL_CJK = re.compile(r'(?:结束|結束|跑完|完了|完成|完毕|完畢|收尾|收工|收束|完事|告一段落|做完|弄完|搞完|终了|終了|'
                          r'終わ(?:って|った)?|开始|開始|始ま(?:って|った)?)\s*(以后|以後|之后|之後|后|後|から|あと|之前|以前|前)')
    _REL_EN = re.compile(r'\b(after|before)\b', re.I)

    def _rel_shift(self, f, lines):
        """Minutes the source line puts between a test window and the job ("第一段平场灯测试结束以后，隔一小时": 60,
        "two hours after the first test window ends": 120), read by code when the model named the window but gave
        no shift; 0 when the line states none."""
        src = self._src_line(f.get('quote'), lines)
        if src is None:
            src = f.get('quote') if isinstance(f.get('quote'), str) else ''
        if not src or len(src) > 4000:
            return 0
        try:
            e = prep(src)
        except Exception:
            return 0
        e = re.sub(r'\d{1,2}:\d{2}', ' ', DATE.sub(' ', e))
        m = self._REL_CJK.search(e)
        if m:
            seg = re.split(r'[。；;！!\n]', e[m.end():m.end() + 40])[0]
            sgn = -1 if '前' in m.group(1) else 1
        else:
            m = self._REL_EN.search(e)
            if m is None:
                return 0
            seg = re.split(r'[。；;!\n]|\.\s', e[max(0, m.start() - 40):m.start()])[-1]
            sgn = -1 if m.group(1).lower() == 'before' else 1
        dm = re.search(r'(\d+[.,]\d+)\s*(?:hours?|hrs?\b|h\b|小[时時]|钟头|鐘頭|時間)', seg, re.I)
        mins = int(round(float(dm.group(1).replace(',', '.')) * 60)) if dm else duration_minutes(seg)
        if mins is None or not (0 < mins <= 12 * 60):
            return 0
        self.llm_fix = getattr(self, 'llm_fix', 0) + 1
        return sgn * mins

    def llm_time(self, f, issued, lines=None):
        """UTC epoch of a model fault item from its as-written parts (the model does no clock arithmetic)."""
        if not isinstance(f, dict):
            return None
        rel = f.get('relative_to')
        if rel is None:
            rel = {}
        if not isinstance(rel, dict):
            return None
        kind = rel.get('kind', 'none')
        if not isinstance(kind, str):
            return None
        kind = kind.strip().lower()
        if kind not in ('none', 'window_end', 'window_start', 'job'):
            return None
        shift = self._int(f.get('shift_minutes'), 0)
        if shift is None or abs(shift) > 24 * 60:
            return None
        if kind in ('window_end', 'window_start'):
            w = self._label_window(rel.get('label'), issued)
            if w is None:
                md = self._md(rel.get('date')) or self._md(f.get('night')) or self._md(f.get('date'))
                if md is None:
                    return None
                nd = self._night_date(md[0], md[1], issued)
                wins = self._night_windows(nd)
                idx = self._int(rel.get('index'), 1)
                if idx is None or idx < 1 or not wins or len(wins) < idx:
                    return None
                w = wins[idx - 1]
            base = w[1] if kind == 'window_end' else w[0]
            if shift == 0:
                shift = self._rel_shift(f, lines)
            return base + shift * 60.0
        if kind == 'job':
            ref, tgt = self._md(rel.get('date')), self._md(f.get('date')) or self._md(f.get('night'))
            if ref is None or tgt is None:
                return None
            refs = []
            for c in self.cands.values():
                if c['void'] or c['st'] not in ('official', 'llm', 'alt'):
                    continue
                lt = datetime.fromtimestamp(c['t'] + self.off * 3600.0, tz=timezone.utc)
                if (lt.month, lt.day) == ref:
                    refs.append(c)
            if not refs:
                return None
            c = max(refs, key=lambda c: c['t'])
            lt = datetime.fromtimestamp(c['t'] + self.off * 3600.0, tz=timezone.utc)
            t = self._utc(tgt[0], tgt[1], lt.hour, lt.minute, self.off, issued)
            return None if t is None else t + shift * 60.0
        hm = self._time_of(f)
        if hm is None:
            return None
        t = self._when(f, hm, self._clock(f.get('clock')), issued, lines)
        return None if t is None else t + shift * 60.0

    def llm_window(self, w, issued, lines=None):
        """(start, end, local night date) of a model window: calendar `date` (+ `end_date`) or `night` semantics."""
        if not isinstance(w, dict):
            return None
        a, b = self._hm(w.get('start')), self._hm(w.get('end'))
        if a is None or b is None:
            return None
        tz = self._clock(w.get('clock'))
        if tz is None:
            return None
        md = self._date_of(w, issued) or self._md(w.get('start_date'))
        if md is not None and self._md(w.get('night')) is not None and self._NIGHT_W.search(w.get('date_text') if isinstance(w.get('date_text'), str) else ''):
            src = self._src_line(w.get('quote'), lines)
            if src is None or self._NIGHT_W.search(src):
                md = None             # "10/4 当晚 01:15": a night, not a calendar date
        if md is not None:
            ta = self._utc(md[0], md[1], a[0], a[1], tz, issued)
            if ta is None:
                return None
            ed = self._md(w.get('end_date'))
            if w.get('end_date') not in (None, '') and ed is None:
                return None
            tb = self._utc(ed[0], ed[1], b[0], b[1], tz, issued) if ed is not None else None
            if ed is not None and tb is None:
                return None
            if tb is None:
                tb = ta + ((b[0] * 60 + b[1]) - (a[0] * 60 + a[1])) * 60.0
                if tb <= ta:
                    tb += 86400.0
        else:
            nm = self._md(w.get('night'))
            if nm is None:
                return None
            nd = self._night_date(nm[0], nm[1], issued)
            if nd is None:
                return None
            base = datetime(nd[0], nd[1], nd[2], tzinfo=timezone.utc)
            ta = base + timedelta(days=1 if a[0] < 12 else 0, hours=a[0], minutes=a[1])
            tb = base + timedelta(days=1 if b[0] < 12 else 0, hours=b[0], minutes=b[1])
            if tb <= ta:
                tb += timedelta(days=1)
            ta, tb = ta.timestamp() - tz * 3600.0, tb.timestamp() - tz * 3600.0
        if not (0.0 < tb - ta <= 4 * 3600.0):
            return None
        lt = datetime.fromtimestamp(ta + self.off * 3600.0, tz=timezone.utc)
        if lt.hour < 12:
            lt -= timedelta(days=1)
        return ta, tb, (lt.year, lt.month, lt.day)

    def known_summary(self, issued, fmt):
        """Schedule known so far near `issued` (site-local strings) for the model's relative references."""
        jobs = [fmt(c['t']) + (' (stated)' if c['st'] == 'official' else ' (to be checked)')
                for c in self.due() + self.probes() if abs(c['t'] - issued) < 4 * 86400][-40:]
        names = {}
        for k, lst in getattr(self, '_labels', {}).items():
            for (a, b, seen) in lst:
                names[(a, b)] = k
        wins = [fmt(a) + '-' + fmt(b)[-5:] + (' [' + names[(a, b)] + ']' if (a, b) in names else '')
                for (a, b) in self._flat_arr() if abs(a - issued) < 3 * 86400][-30:]
        return {'fault_starts': jobs, 'lost_windows': wins}

    def add_llm(self, res, issued, horizon=12 * 86400.0, strict=True, lines=None):
        """Merge a language-model answer: times it agrees on are marked, new confirmed / conditional times become
        probes (reported only if the throughput drops), stated times it withdraws become probes, new lost-data
        windows and closures are waited out like the flat-lamp tests, active faults are probed now."""
        if not hasattr(self, '_llm_nights'):
            self._llm_nights = {}
        n = {'agree': 0, 'new': 0, 'withdrawn': 0, 'win': 0, 'active': 0, 'bad': 0}
        keys = ('fault_starts', 'lost_windows', 'closures', 'active_faults')
        if not isinstance(res, dict) or not any(k in res for k in keys):
            n['bad'] = 1
            return n
        upper = min(issued + horizon, self.t1 if self.t1 is not None else float('inf'))
        strict = strict and res.get('_complete', True) is True
        prepared = {}
        for key in keys:
            values = res.get(key, [])
            if not isinstance(values, list):
                n['bad'] += 1
                strict = False
                values = []
            if len(values) > 480:
                strict = False
            prepared[key] = []
            for value in values[:480]:
                if isinstance(value, dict):
                    prepared[key].append(value)
                else:
                    n['bad'] += 1
                    strict = False
        self.ver += 1
        if not hasattr(self, '_labels'):
            self._labels = {}
        groups = {}       # A midnight roll is scoped to one quoted source line.
        for w in prepared['lost_windows']:      # closures (rain, maintenance) are left to the weather logic
            if not isinstance(w, dict):
                continue
            roll = False
            hm0 = self._hm(w.get('start'))
            src = self._src_line(w.get('quote'), lines)
            if src is not None and hm0 is not None and self._md(w.get('date')) is not None and not self._md(w.get('night')):
                g = groups.setdefault((self._md(w.get('date')), self._clock(w.get('clock')), src),
                                      [hm0[0] >= 12, False])
                if hm0[0] >= 12:
                    g[1] = True
                elif g[0] and g[1]:
                    roll = True       # a night's list running past midnight: "10/1: 23:45-0:00, 1:30-1:45"
            r = self.llm_window(w, issued, lines)
            if r is None:
                n['bad'] += 1
                continue
            a, b, nd = r
            if roll and self._md(w.get('end_date')) is None:
                a, b = a + 86400.0, b + 86400.0
                lt = datetime.fromtimestamp(a + self.off * 3600.0 - 12 * 3600.0, tz=timezone.utc)
                nd = (lt.year, lt.month, lt.day)
            if not (issued - 86400 <= a < upper):
                continue
            b = min(b, upper)
            same = [(x, y) for (x, y) in self.flats if x < b and a < y]
            if not same:
                pn = self.flat_nights.get(nd, [])
                day_off = any(abs(abs(x - a) - 86400.0) < 61 and abs(abs(y - b) - 86400.0) < 61
                              for (x, y) in self.flats if self.flats[(x, y)] != 'llm')
                if len(pn) >= 2 or day_off:
                    n['bad'] += 1      # the parser read that night's list (or this is a day-shifted copy)
                    continue
            self._llm_nights.setdefault(nd, set()).add((a, b))
            k = self._label(w.get('label'))
            if k:
                ab = min(same, key=lambda xy: abs(xy[0] - a)) if same else (a, b)
                lst = self._labels.setdefault(k, [])
                if not any(e[:2] == ab for e in lst):
                    lst.append((ab[0], ab[1], issued))
                    del lst[:-8]
            if same:
                continue
            self.flats[(a, b)] = 'llm'
            n['win'] += 1
        items = []
        for f in prepared['fault_starts']:
            if not isinstance(f, dict):
                continue
            t = self.llm_time(f, issued, lines)
            if t is None:
                n['bad'] += 1
                strict = False
                continue
            if not (issued - 2 * 86400 <= t < upper):
                continue
            status = f.get('status')
            if not isinstance(status, str):
                n['bad'] += 1
                strict = False
                continue
            status = status.strip().lower()
            if status not in ('confirmed', 'conditional', 'cancelled', 'wrong', 'rumour', 'rumor', 'uncertain'):
                strict = False
            items.append((t, status, f))
        confirmed = set()
        for (t, st, f) in items:               # confirmations first: a slip in a withdrawal cannot undo them
            if st not in ('confirmed', 'conditional'):
                continue
            self.active = True
            k = self._key(t)
            confirmed.update(range(k - 2, k + 3))
            near = [self.cands[kk] for kk in (k - 2, k - 1, k, k + 1, k + 2) if kk in self.cands]
            live = [c for c in near if not c['void'] and c['st'] in ('official', 'alt', 'llm')]
            if live:
                for c in live:
                    if st == 'confirmed':
                        c['llm_ok'] = True
                        if c.get('dg') and c['st'] == 'alt':
                            c['st'], c['dg'] = 'official', False     # confirmed after all: report on time
                n['agree'] += 1
            elif not any(c['void'] for c in near):
                quote = f.get('quote') if isinstance(f.get('quote'), str) else ''
                self._add(t, 'llm', issued, 'LLM: ' + quote[:80])
                candidate = self.cands.get(self._key(t))
                if candidate is not None:
                    candidate['llm_ok'] = st == 'confirmed'
                    n['new'] += 1
        if strict:
            # a time the parser takes as stated but the model, reading the same section, does not confirm
            # (rumour, condition, withdrawal, or a different reading): confirm it on the data before reporting
            for c in self.cands.values():
                if c['st'] == 'official' and not c['void'] and not c.get('llm_ok') and c.get('last') == issued \
                        and issued - 86400 <= c['t'] <= issued + horizon:
                    c['st'], c['dg'] = 'alt', True
                    n['unconfirmed'] = n.get('unconfirmed', 0) + 1
        for (t, st, f) in items:
            if st not in ('cancelled', 'wrong'):
                continue
            k = self._key(t)
            if k in confirmed:
                continue
            for kk in (k - 2, k - 1, k, k + 1, k + 2):
                c = self.cands.get(kk)
                if c is not None and c['st'] == 'official' and not c['void']:
                    c['llm_ok'], c['dg'] = False, True
                    c['st'] = 'alt'          # the parser and the model disagree: look before reporting
                    n['withdrawn'] += 1
        for f in prepared['active_faults']:
            if not isinstance(f.get('quote'), str) or not f['quote'].strip():
                n['bad'] += 1
                continue
            tz = self._clock(f.get('clock'))
            if tz is None:
                n['bad'] += 1
                continue
            md, hm = self._md(f.get('date')), self._hm(f.get('time'))
            t = None
            if md is not None and hm is not None:
                t = self._utc(md[0], md[1], hm[0], hm[1], tz, issued)
            t = issued if t is None or t > issued + 1800 or t < issued - 2 * 86400 else t
            k = self._key(t)
            if max(t, issued) >= upper:
                continue
            if not any(kk in self.cands and not self.cands[kk]['void'] for kk in range(k - 30, k + 31)):
                self._add(max(t, issued), 'llm', issued, 'LLM active: ' + str(f.get('quote', ''))[:80])
                self.active = True
                n['active'] += 1
        return n

    # ------------------------------------------------------------------ queries
    def _cached(self, key, fn):
        c = self._cache.get(key)
        if c is None or c[0] != self.ver:
            c = (self.ver, fn())
            self._cache[key] = c
        return c[1]

    def due(self):
        """Official, not voided jobs (sorted by time)."""
        return self._cached('due', lambda: sorted((c for c in self.cands.values() if c['st'] == 'official' and not c['void']),
                                                  key=lambda c: c['t']))

    def probes(self):
        """Jobs whose day or time is uncertain (rain postponement, relative to another day's job): probe them.
        Rumours and questioned times are not probed (none turned out real on A1-D1)."""
        return self._cached('probes', lambda: sorted((c for c in self.cands.values()
                                                      if c['st'] in ('alt', 'llm') and not c['void']),
                                                     key=lambda c: c['t']))

    def _flat_arr(self):
        return self._cached('flats', lambda: sorted(self.flats))

    @property
    def busy(self):
        """Many guider jobs or flat-lamp tests: the near-zero check and the uncapped belief reports apply."""
        return bool(self.flats) or sum(1 for c in self.cands.values() if not c['void'] and c['st'] != 'unsure') >= 8

    def night_known(self, t):
        """The flat-lamp windows of the night containing t were announced."""
        lt = datetime.fromtimestamp(t + self.off * 3600.0, tz=timezone.utc)
        if lt.hour < 12:
            lt -= timedelta(days=1)
        return (lt.year, lt.month, lt.day) in self.flat_nights

    def in_flat(self, t, margin=0.0):
        arr = self._flat_arr()
        i = bisect.bisect_right(arr, (t + margin, float('inf')))
        for (a, b) in arr[max(0, i - 3):i + 1]:
            if a - margin <= t < b + margin:
                return (a, b)
        return None

    def next_flat_start(self, t):
        arr = self._flat_arr()
        i = bisect.bisect_right(arr, (t, float('inf')))
        return arr[i][0] if i < len(arr) else None

    def overlaps_flat(self, a, b):
        arr = self._flat_arr()
        i = bisect.bisect_left(arr, (a - 4 * 3600.0, 0.0))
        for (x, y) in arr[i:]:
            if x >= b:
                break
            if x < b and a < y:
                return True
        return False
