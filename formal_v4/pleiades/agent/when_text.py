"""Deterministic reading of a date or time the language model copied verbatim from the duty log.

The model finds and copies the words ("后天（星期六）", "15 October 2026", "quarter to eleven p.m.", "2130 hours");
these helpers turn the common forms into numbers so that the model never has to do calendar or clock arithmetic.
Anything not recognised returns None and the model's own M/D or HH:MM is used instead."""
from __future__ import annotations

import re
from datetime import date, timedelta

from log_reader import normalise, _INVIS

_EN_SMALL = ('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen '
             'seventeen eighteen nineteen').split()
_EN_TENS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50}
_EN_ORD = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5, 'sixth': 6, 'seventh': 7, 'eighth': 8,
           'ninth': 9, 'tenth': 10, 'eleventh': 11, 'twelfth': 12, 'thirteenth': 13, 'fourteenth': 14,
           'fifteenth': 15, 'sixteenth': 16, 'seventeenth': 17, 'eighteenth': 18, 'nineteenth': 19, 'twentieth': 20,
           'thirtieth': 30}
_WORD = {w: i for i, w in enumerate(_EN_SMALL)}
_WORD.update(_EN_TENS)
_WORD.update(_EN_ORD)
_MONTHS = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10,
           'nov': 11, 'dec': 12}
_MON = r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|' \
       r'oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?'
_NUMW = r'(\d{1,2}|[a-z]+(?:[- ][a-z]+)?)'
_CN_D = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '兩': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def _num(tok):
    """1-59 from digits, English words ('forty-five', 'twenty one', 'third') or Chinese numerals; else None."""
    if not isinstance(tok, str) or len(tok) > 64:
        return None
    s = tok.strip().lower().replace('–', '-')
    if not s:
        return None
    if re.fullmatch(r'[0-9]{1,2}', s):
        return int(s)
    if s in _WORD:
        return _WORD[s]
    parts = re.split(r'[- ]', s)
    if len(parts) == 2 and parts[0] in _EN_TENS and parts[1] in _WORD and _WORD[parts[1]] < 10:
        return _EN_TENS[parts[0]] + _WORD[parts[1]]
    if all(ch in _CN_D or ch == '十' for ch in s):
        if '十' in s:
            a, _, b = s.partition('十')
            return (_CN_D.get(a, 1) if a else 1) * 10 + (_CN_D.get(b, 0) if b else 0)
        if len(s) == 1:
            return _CN_D[s]
    return None


_REL = ((r'大后天|大後天|しあさって|明々後日', 3), (r'后天|後天|明後日|あさって|day after tomorrow', 2),
        (r'前天|一昨日|おととい|day before yesterday', -2), (r'明天|明日|tomorrow', 1),
        (r'昨天|昨日|昨晚|昨夜|yesterday', -1), (r'今天|今日|今晚|今夜|本日|today|tonight', 0))


def date_from_text(txt, d0):
    """(month, day) of an as-written date; relative words count from d0 (the handover day, a datetime.date)."""
    if not isinstance(txt, str) or not txt or len(txt) > 1024:
        return None
    e = normalise(txt.translate(_INVIS)).lower()
    m = re.search(r'(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})', e)
    if m:
        return _ok(int(m.group(2)), int(m.group(3)), int(m.group(1)))
    m = re.search(r'(\d{1,2})\s*月\s*(\d{1,2})\s*[日号號]', e)
    if m:
        return _ok(int(m.group(1)), int(m.group(2)))
    m = re.search(r'(?<![\d.:+-])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/:])', e)
    if m:
        return _ok(int(m.group(1)), int(m.group(2)))
    m = re.search(r'\b' + _MON + r'\s+(?:the\s+)?' + _NUMW + r'\b', e)
    if m:
        d = _num(m.group(2))
        if d is None:
            d = _num(m.group(2).split()[0].split('-')[0])
        if d is not None:
            return _ok(_MONTHS[m.group(1)[:3]], d)
    m = re.search(r'\b' + _NUMW + r'\s+(?:of\s+)?' + _MON + r'\b', e)
    if m:
        d = _num(m.group(1))
        if d is None:
            d = _num(m.group(1).split()[-1])
        if d is not None:
            return _ok(_MONTHS[m.group(2)[:3]], d)
    if not isinstance(d0, date):
        return None
    m = re.search(r'(?:之|以)?[后後]\s*第\s*([\d一二两三四五六七八九十]+)\s*[天日]', e) or \
        re.search(r'([\d一二两三四五六七八九十]+)\s*[天日]\s*(?:之|以)?[后後]', e) or \
        re.search(r'(\d+)\s*days?\s+(?:after|later|from)', e) or re.search(r'\bd\s*\+\s*(\d+)\b', e)
    if m:
        k = _num(m.group(1))
        if k is not None and 0 <= k <= 40:
            return _relative(d0, k)
    m = re.search(r'(?:之|以)?前\s*第\s*([\d一二两三四五六七八九十]+)\s*[天日]', e) or \
        re.search(r'([\d一二两三四五六七八九十]+)\s*days?\s+before', e)
    if m:
        k = _num(m.group(1))
        if k is not None and 0 <= k <= 40:
            return _relative(d0, -k)
    for pat, k in _REL:
        if re.search(pat, e):
            return _relative(d0, k)
    return None


def _ok(mo, da, year=2000):
    try:
        date(year, mo, da)
        return mo, da
    except (ValueError, TypeError, OverflowError):
        return None


def _relative(d0, days):
    try:
        d = d0 + timedelta(days=days)
        return d.month, d.day
    except (ValueError, TypeError, OverflowError):
        return None


_PM = r'(\bp\.?\s?m\.?\b|\bpm\b|in the (?:afternoon|evening)|午後|下午|晚上|傍晚)'
_AM = r'(\ba\.?\s?m\.?\b|\bam\b|in the morning|午前|上午|凌晨|早上|清晨|早晨)'


def time_from_text(txt):
    """(hour, minute) 24 h of an as-written time: H:MM (+ a.m./p.m./午後/晚上), '2130 hours', '21h30', English
    words ('quarter to eleven p.m.', 'half past ten', 'ten forty-five'), noon / midnight; else None."""
    if not isinstance(txt, str) or not txt or len(txt) > 1024:
        return None
    e = normalise(txt.translate(_INVIS)).lower().strip()
    pm, am = re.search(_PM, e), re.search(_AM, e)
    if pm and am:
        return None

    def ampm(h, mi):
        if not (0 <= h <= 24 and 0 <= mi <= 59):
            return None
        if h == 24:
            return (24, 0) if mi == 0 and not (am or pm) else None
        if pm and not am and h < 12:
            h += 12
        elif am and not pm and h == 12:
            h = 0
        return (h, mi)
    m = re.search(r'(?<![\d/+-])(\d{1,2})\s*[:：]\s*(\d{2})(?!\d)', e)
    if m:
        return ampm(int(m.group(1)), int(m.group(2)))
    m = re.search(r'(\d{1,2})\s*時\s*(\d{1,2})\s*分', e)
    if m:
        return ampm(int(m.group(1)), int(m.group(2)))
    m = re.search(r'(\d{1,2})\s*時\s*半', e)
    if m:
        return ampm(int(m.group(1)), 30)
    m = re.search(r'(\d{1,2})\s*時(?![\d間])', e)
    if m:
        return ampm(int(m.group(1)), 0)
    m = re.search(r'(?<!\d)(\d{2})(\d{2})\s*(?:hours|hrs|h\b)', e) or re.search(r'(?<!\d)(\d{1,2})\s*h\s*(\d{2})(?!\d)', e)
    if m:
        return ampm(int(m.group(1)), int(m.group(2)))
    if re.search(r'midnight|午夜|零点整', e):
        m = re.search(r'quarter to midnight', e)
        return (23, 45) if m else (0, 0)
    if re.search(r'\bnoon\b|正午|中午十二点', e):
        return (11, 45) if 'quarter to noon' in e else (12, 0)
    w = r'([a-z]+(?:-[a-z]+)?)'

    def before_hour(h, mi):
        target = ampm(h, 0)
        if target is None or not 0 < mi < 60:
            return None
        total = (target[0] * 60 - mi) % 1440
        return divmod(total, 60)
    m = re.search(r'quarter past ' + w, e) or re.search(r'quarter after ' + w, e)
    if m and _num(m.group(1)) is not None:
        return ampm(_num(m.group(1)), 15)
    m = re.search(r'half past ' + w, e)
    if m and _num(m.group(1)) is not None:
        return ampm(_num(m.group(1)), 30)
    m = re.search(r'quarter to ' + w, e)
    if m and _num(m.group(1)) is not None:
        return before_hour(_num(m.group(1)), 15)
    m = re.search(w + r' (?:minutes? )?past ' + w, e)
    if m and _num(m.group(1)) is not None and _num(m.group(2)) is not None:
        return ampm(_num(m.group(2)), _num(m.group(1)))
    m = re.search(w + r' (?:minutes? )?to ' + w, e)
    if m and _num(m.group(1)) is not None and _num(m.group(2)) is not None:
        return before_hour(_num(m.group(2)), _num(m.group(1)))
    m = re.search(w + r" o'?clock", e)
    if m and _num(m.group(1)) is not None:
        return ampm(_num(m.group(1)), 0)
    m = re.search(r'\b([a-z]+) ((?:twenty|thirty|forty|fifty)(?:-[a-z]+)?|ten|eleven|twelve|thirteen|fourteen|'
                  r'fifteen|sixteen|seventeen|eighteen|nineteen|oh [a-z]+)\b', e)
    if m and _num(m.group(1)) is not None and _num(m.group(1)) <= 24:
        mi = _num(m.group(2).replace('oh ', ''))
        if mi is not None and mi < 60:
            return ampm(_num(m.group(1)), mi)
    return None
