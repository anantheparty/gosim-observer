"""LLM strategist: the season-planning layer of the observer agent.

Division of labour
------------------
A language model (any OpenAI-compatible chat endpoint; DeepSeek by default) plans the season, and the
numerical optimiser in policy.py turns that plan into every pointing, fibre assignment, exposure time and
program.  The model works at three stages:

1. Mission analysis (data parsing / natural-language understanding).  At initialisation it reads the task
   card -- the free-text site and instrument descriptions, the scoring rules, and catalogue, visibility and
   capacity statistics computed by the agent -- and returns a structured mission profile.
2. Task planning.  From that profile it chooses the season strategy for the required targets
   (one of STRATEGIES).
3. Plan adaptation.  Whenever the weekly weather forecast arrives it reviews the forecast, the Moon and the
   survey's progress (required targets at risk, requests, instrument faults, time budget) and keeps or
   changes the strategy for the coming week.

Safety
------
* Model calls run on one background thread and never block a decision: the optimiser always works with the
  strategy in force (the rule-based default until the first answer arrives).
* Answers are validated against a whitelist of strategies; anything else is ignored.
* Every attempt has a timeout and every question a deadline; HTTP 429/5xx, timeouts and network errors are
  retried with exponential backoff and jitter, honouring Retry-After (the hidden final runs the three
  repeats of a card on one key at the same time).  A run makes at most `max_calls` requests, and no request
  starts close to the card's real-time cap.
* Without a key, with OBSERVER_MODEL_DISABLED=1, or when the service is unreachable, the agent keeps the
  rule-based default strategy: a run never depends on the model being available.

Configuration (environment): OPENAI_API_KEY (or DEEPSEEK_API_KEY), OPENAI_BASE_URL (default
https://api.deepseek.com), OPENAI_MODEL (default deepseek-flash).  OBS_LLM_MOCK=1 answers every question
locally with the rule-based default (offline tests of this code path).  Standard library only.
"""
from __future__ import annotations

import json
import math
import queue
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = 'https://api.deepseek.com'
DEFAULT_MODEL = 'deepseek-flash'

# Season strategies for the required targets: the policy parameters each one sets.  Both were validated on
# simulated cards (docs: formal_v4/pleiades/README_ZH.md); 'seasonal' is the rule-based default.
STRATEGIES = {
    'seasonal': {'req_moon': 1, 'req_moon_urg': 1},
    'standard': {'req_moon': 0, 'req_moon_urg': 0},
}
DEFAULT_STRATEGY = 'seasonal'
OVERLOAD_RATIO = 5.0   # rule-based fallback: 'standard' when demand/supply of telescope time exceeds this

STRATEGY_TEXT = {
    'seasonal': ('Required targets are prioritised by the expected number of remaining hours in which ONE '
                 'maximum-length exposure would complete them, counting the Moon, airmass, the seasonal sky '
                 'quality and the night-to-night weather scatter. Faint required targets that only complete in '
                 'rare dark, clear windows are pushed into those windows; bright ones are not rushed. Measured on '
                 'simulated cards: better on time-rich and moderately over-subscribed surveys (demand up to a few '
                 'times the dark time).'),
    'standard': ('Required targets are prioritised by the remaining hours they spend high in the sky, like every '
                 'other target; their completion bonus counts only hours with good enough sky for them. Measured on '
                 'simulated cards: better when the survey is grossly over-subscribed (demand above about 5 times '
                 'the dark time), where most required targets cannot be done anyway and spending the scarce time '
                 'on the hardest ones completes fewer of them.'),
}

SYSTEM_PROMPT = (
    'You are the season strategist of an autonomous telescope survey with a fibre-fed multi-object '
    'spectrograph. A numerical optimiser makes every pointing, fibre assignment and exposure decision; you '
    'decide the season-level strategy it follows. Scoring: each target scores its best single exposure; a '
    'required target whose best completion factor stays below the threshold costs a fixed penalty at the end '
    'of the season; timed observation requests pay a reward when completed before their deadline; '
    'instrument-fault reports are rewarded when correct and penalised when false. Reason from the numbers you '
    'are given. Reply with one JSON object only, no markdown.')

_JSON_OBJECT = re.compile(r'\{.*\}', re.S)


def _emit(obj):
    try:
        sys.stderr.write(json.dumps(obj, separators=(',', ':'), default=str) + '\n')
        sys.stderr.flush()
    except Exception:
        pass


def _parse_json(text):
    text = (text or '').strip()
    try:
        out = json.loads(text)
    except ValueError:
        m = _JSON_OBJECT.search(text)
        if not m:
            return None
        try:
            out = json.loads(m.group(0))
        except ValueError:
            return None
    return out if isinstance(out, dict) else None


class _Retryable(Exception):
    def __init__(self, reason, retry_after=None):
        super().__init__(reason)
        self.retry_after = retry_after


class _Fatal(Exception):
    """Authentication or request errors that another attempt will not fix."""


class ChatClient:
    """Minimal OpenAI-compatible /chat/completions client (urllib honours HTTPS_PROXY set by the platform)."""

    def __init__(self):
        self.key = (os.environ.get('OPENAI_API_KEY') or os.environ.get('DEEPSEEK_API_KEY') or '').strip()
        self.base_url = (os.environ.get('OPENAI_BASE_URL') or DEFAULT_BASE_URL).strip().rstrip('/')
        self.model = (os.environ.get('OPENAI_MODEL') or DEFAULT_MODEL).strip()
        self.json_mode = True

    def _post(self, body, timeout):
        req = urllib.request.Request(self.base_url + '/chat/completions', data=json.dumps(body).encode('utf-8'),
                                     headers={'Authorization': 'Bearer ' + self.key,
                                              'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                ra = None
                try:
                    ra = max(0.0, float(e.headers.get('Retry-After')))
                except (TypeError, ValueError):
                    pass
                raise _Retryable(f'http {e.code}', ra) from None
            if e.code == 400 and ('response_format' in body or 'temperature' in body):
                # Judge the request that actually failed: another in-flight
                # timeout worker may already have switched self.json_mode off.
                self.json_mode = False
                raise _Retryable('http 400 (json mode off)', 0.0) from None
            raise _Fatal(f'http {e.code}') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise _Retryable(type(e).__name__) from None

    def ask(self, system, user, attempt_timeout, deadline, max_attempts=3, max_tokens=4000):
        """One question; returns (answer dict or None, info dict)."""
        info = {'attempts': 0}
        for k in range(max_attempts):
            left = deadline - time.monotonic()
            if left < 2.0:
                info['error'] = 'deadline'
                break
            body = {'model': self.model, 'max_tokens': int(max_tokens),
                    'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
            if self.json_mode:
                body['temperature'] = 0
                body['response_format'] = {'type': 'json_object'}
            if getattr(self, 'extra', None) and self.json_mode:
                body.update(self.extra)
            info['attempts'] = k + 1
            try:
                out = self._post(body, min(attempt_timeout, left))
                msg = (out.get('choices') or [{}])[0].get('message') or {}
                info['usage'] = (out.get('usage') or {}).get('total_tokens')
                ans = _parse_json(msg.get('content'))
                if ans is not None:
                    return ans, info
                info['error'] = 'unparsable answer'
            except _Fatal as e:
                info['error'] = str(e)
                info['fatal'] = True
                break
            except _Retryable as e:
                info['error'] = str(e)
                pause = e.retry_after if e.retry_after is not None else min(20.0, 2.0 ** k + random.uniform(0, 1.5))
                if time.monotonic() + pause + 2.0 >= deadline:
                    break
                time.sleep(pause)
            except Exception as e:  # never let a malformed response escape
                info['error'] = type(e).__name__
        return None, info


class Strategist:
    """Season strategist: asynchronous planning questions to the model, validated into a strategy name."""

    def __init__(self, enabled=True, max_calls=64, wall_reserve=300.0, attempt_timeout=30.0, question_deadline=75.0):
        self.client = ChatClient()
        self.mock = os.environ.get('OBS_LLM_MOCK') == '1'
        self.enabled = bool(enabled) and (self.mock or (bool(self.client.key) and
                                                         os.environ.get('OBSERVER_MODEL_DISABLED') != '1'))
        self.strategy = DEFAULT_STRATEGY      # read by the policy before each planning step
        self.rule_strategy = DEFAULT_STRATEGY  # rule-based choice, in force until the model answers
        self.source = 'default'               # 'default' (rules) or 'llm'
        self.profile = None                   # mission profile from the analysis stage
        self.history = []
        self.calls = self.ok = self.failed = 0
        self.max_calls, self.wall_reserve = int(max_calls), float(wall_reserve)
        self.attempt_timeout, self.question_deadline = float(attempt_timeout), float(question_deadline)
        self._cv = threading.Condition()
        self._jobs = {}
        self._thread = None
        self._dead = False

    # ------------------------------------------------------------------ main-thread API
    def set_rule_default(self, demand_over_supply):
        """Rule-based strategy from the capacity ratio (used until, or instead of, the model's answer)."""
        try:
            r = float(demand_over_supply)
        except (TypeError, ValueError):
            return
        self.rule_strategy = 'standard' if r > OVERLOAD_RATIO else DEFAULT_STRATEGY
        if self.source == 'default':
            self.strategy = self.rule_strategy

    def submit(self, stage, brief, wall_left=None):
        """Queue a question ('mission' or 'weekly'); a newer question of the same stage replaces a waiting one."""
        if not self.enabled or self._dead:
            return
        start_by = None
        if wall_left is not None:
            try:
                start_by = time.monotonic() + float(wall_left) - self.wall_reserve
            except (TypeError, ValueError):
                start_by = None
        with self._cv:
            self._jobs[stage] = (brief, start_by)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name='llm-strategist', daemon=True)
                self._thread.start()
            self._cv.notify()

    def summary(self):
        return {'enabled': self.enabled, 'mock': self.mock, 'model': self.client.model, 'calls': self.calls,
                'ok': self.ok, 'failed': self.failed, 'strategy': self.strategy, 'source': self.source,
                'regime': (self.profile or {}).get('regime'), 'history': self.history[-12:]}

    # ------------------------------------------------------------------ worker thread
    def _run(self):
        while True:
            with self._cv:
                while not self._jobs:
                    self._cv.wait()
                stage = 'mission' if 'mission' in self._jobs else next(iter(self._jobs))
                brief, start_by = self._jobs.pop(stage)
            try:
                self._ask(stage, brief, start_by)
            except Exception as e:  # the worker must never die silently in a way that matters
                _emit({'event': 'llm', 'stage': stage, 'ok': False, 'error': type(e).__name__})

    def _ask(self, stage, brief, start_by):
        if self._dead or self.calls >= self.max_calls:
            return
        if start_by is not None and time.monotonic() > start_by:
            _emit({'event': 'llm', 'stage': stage, 'ok': False, 'error': 'skipped near the real-time cap'})
            return
        self.calls += 1
        t0 = time.monotonic()
        if self.mock:
            answer, info = {'required_strategy': self.rule_strategy, 'rationale': 'mock'}, {'attempts': 0}
            if stage == 'mission':
                answer['profile'] = {'regime': 'unknown'}
        else:
            user = self._question(stage, brief)
            answer, info = self.client.ask(SYSTEM_PROMPT, user, self.attempt_timeout,
                                           t0 + self.question_deadline)
            if info.get('fatal'):
                # one rejected question keeps the rule-based strategy for this review; five end the model reviews
                self._fatal_n = getattr(self, '_fatal_n', 0) + 1
                if self._fatal_n >= 5:
                    self._dead = True
        dt = round(time.monotonic() - t0, 2)
        choice = answer.get('required_strategy') if isinstance(answer, dict) else None
        if isinstance(choice, str):
            choice = choice.strip().lower()
        if choice not in STRATEGIES:
            self.failed += 1
            _emit({'event': 'llm', 'stage': stage, 'ok': False, 'latency': dt,
                   'error': info.get('error', 'invalid strategy'), 'strategy': self.strategy})
            self.history.append([stage, brief.get('date'), None, False])
            return
        if stage == 'mission' and isinstance(answer.get('profile'), dict):
            prof = answer['profile']
            self.profile = {'regime': str(prof.get('regime', ''))[:24],
                            'summary': str(prof.get('summary', ''))[:160],
                            'risks': [str(r)[:80] for r in (prof.get('main_risks') or [])[:3]]}
        self.ok += 1
        changed = choice != self.strategy
        self.strategy = choice
        self.source = 'llm'
        rationale = str(answer.get('rationale', ''))[:300]
        self.history.append([stage, brief.get('date'), choice, True])
        _emit({'event': 'llm', 'stage': stage, 'ok': True, 'latency': dt, 'attempts': info.get('attempts'),
               'tokens': info.get('usage'), 'strategy': choice, 'changed': changed, 'rationale': rationale,
               'profile': self.profile if stage == 'mission' else None})

    def _question(self, stage, brief):
        if stage == 'mission':
            task = ('Mission analysis and season planning. (1) Read the task card below -- including the free-text '
                    'site and instrument descriptions -- and summarise the mission as a profile: is the survey '
                    'capacity-limited (more exposure time demanded than the dark time available), balanced, or '
                    'time-rich? What are the main risks for the score? (2) Choose the season strategy for the '
                    'required targets from "strategies".')
            reply = {'profile': {'regime': 'capacity_limited | balanced | time_rich',
                                 'summary': '<= 25 words', 'main_risks': ['<= 3 short items']},
                     'required_strategy': ' | '.join(STRATEGIES), 'rationale': '<= 40 words'}
        else:
            task = ('Weekly plan review. A new 7-night weather forecast has arrived. Given the forecast, the Moon, '
                    'the mission profile and the progress so far, keep or change the season strategy for the '
                    'required targets for the coming week.')
            reply = {'required_strategy': ' | '.join(STRATEGIES), 'rationale': '<= 40 words'}
            brief = dict(brief, mission_profile=self.profile, current_strategy=self.strategy)
        return json.dumps({'task': task, 'strategies': STRATEGY_TEXT, 'input': brief, 'reply_format': reply},
                          separators=(',', ':'), default=str)


LOG_SYSTEM_PROMPT = (
    'You read the free-text handover log of an observatory night shift. Lines may be Chinese, Japanese or English; '
    'English lines may be Caesar-shifted by the day of the month; times may be hummed in solfege (do=1 re=2 mi=3 '
    'fa=4 sol=5 la=6 si=7, 高音do=8, 高音re=9, 休止=0, so "re : fa sol" is 2:45) or written in Chinese numerals. '
    'Find ONLY instrument-fault items: (a) "planned": engineering work announced for a given local date and time, '
    'after which the instrument efficiency or throughput will drop (not because of the sky); (b) "occurred": a '
    'confirmed sudden throughput drop that is neither weather nor an earthquake, together with a request to call '
    'engineering or file a ticket. Ignore rumours, other observatories, conditional guesses ("if it ever drops, it is '
    'probably ..."), weather, terrain, earthquakes, and scheduled full stops or shutdowns (those are closures). '
    'Most logs contain no such item: then reply {"faults": []}. Reply with JSON only.')


class LogAnalyst:
    """Language-model reader for handover-log lines the deterministic parser (log_reader.py) did not recognise:
    asynchronous, at most max_calls questions, answers checked by the caller (quote must occur in the log)."""

    def __init__(self, max_calls=40, attempt_timeout=30.0, question_deadline=60.0):
        self.client = ChatClient()
        self.enabled = (bool(self.client.key) and os.environ.get('OBSERVER_MODEL_DISABLED') != '1'
                        and os.environ.get('OBS_LLM_MOCK') != '1')
        self.max_calls = int(max_calls)
        self.attempt_timeout, self.question_deadline = float(attempt_timeout), float(question_deadline)
        self.calls = self.ok = self.failed = 0
        self._cv = threading.Condition()
        self._q = []
        self._out = []
        self._thread = None
        self._dead = False

    def submit(self, key, lines, issued_local):
        if not self.enabled or self._dead:
            return False
        with self._cv:
            if self.calls + len(self._q) >= self.max_calls:
                return False
            self._q.append((key, lines, issued_local))
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name='llm-log', daemon=True)
                self._thread.start()
            self._cv.notify()
        return True

    def results(self):
        with self._cv:
            out, self._out = self._out, []
        return out

    def _run(self):
        while True:
            with self._cv:
                while not self._q:
                    self._cv.wait()
                key, lines, issued_local = self._q.pop(0)
            try:
                self._ask(key, lines, issued_local)
            except Exception as e:
                _emit({'event': 'llm', 'stage': 'log', 'ok': False, 'error': type(e).__name__})

    def _ask(self, key, lines, issued_local):
        if self._dead or self.calls >= self.max_calls:
            return
        self.calls += 1
        t0 = time.monotonic()
        user = json.dumps({'task': 'Extract the instrument-fault items from these handover-log lines.',
                           'log_written_local_time': issued_local, 'log_lines': lines,
                           'reply_format': {'faults': [{'kind': 'planned | occurred',
                                                        'local_date': 'M/D, or empty if not given',
                                                        'local_time': 'H:MM (24 h, local), or empty if not given',
                                                        'quote': 'the words of the log line that state it (copy)'}]}},
                          ensure_ascii=False, separators=(',', ':'))
        answer, info = self.client.ask(LOG_SYSTEM_PROMPT, user, self.attempt_timeout, t0 + self.question_deadline)
        if info.get('fatal'):
            self._dead = True
        dt = round(time.monotonic() - t0, 2)
        items = answer.get('faults') if isinstance(answer, dict) else None
        if not isinstance(items, list):
            self.failed += 1
            _emit({'event': 'llm', 'stage': 'log', 'ok': False, 'latency': dt, 'error': info.get('error', 'bad answer')})
            return
        self.ok += 1
        out = []
        for f in items[:6]:
            if isinstance(f, dict):
                out.append({'kind': str(f.get('kind', '')).strip().lower(), 'date': str(f.get('local_date') or '')[:12],
                            'time': str(f.get('local_time') or '')[:12], 'quote': str(f.get('quote') or '')[:80]})
        with self._cv:
            self._out.append((key, out))
        _emit({'event': 'llm', 'stage': 'log', 'ok': True, 'latency': dt, 'n': len(out), 'tokens': info.get('usage')})


DUTY_SYSTEM_PROMPT = (
    'You are the operations analyst of an autonomous survey telescope. Each time a new section of the night-shift '
    'duty log arrives you read it and extract the operational schedule the telescope agent must act on. The agent can '
    'only observe, wait, or file an instrument-fault report. A fault report is correct only while an instrument fault '
    'is active, and a correct report repairs it; a report while no fault is active is a false report and costs points. '
    'Frames taken while a fault is active or during a test window are lost.\n'
    'The log is written by several staff members, some careless, and its format changes: free text, tables, '
    'multi-line work orders. Lines may be Chinese, Japanese or English. Expect code words; English lines encrypted '
    'with a Caesar shift or ROT13 (decoded hints are given where we could decode them; otherwise decode them '
    'yourself with the key the log states); times hummed in solfege (do=1 re=2 mi=3 fa=4 sol=5 la=6 si=7, 高音do=8, '
    '高音re=9, 休止=0, so "re : fa sol" is 2:45) or written in words, Chinese numerals (一刻 = :15, 三刻 = :45, 半 = '
    ':30), 12-hour clock (9:30 p.m. = 21:30), "2130 hours", "21h30"; times on other clocks (UTC, Tokyo = UTC+9, any '
    'UTC+N / UTC-N, ISO 8601 with an offset such as 2026-10-01T15:30:00-10:00 = clock UTC-10); corrections ("X is '
    'wrong, it is Y"); cancellations and withdrawn tickets; postponements ("planned for X, postponed by an hour and a '
    'half"); times relative to other items ("two hours after the first test window of the night of 10/6 ends", '
    '"60 minutes after calibration ticket C001-09 ends", "15 minutes earlier by the clock than the 2/23 job", '
    '"two hours after sunset", "an hour before dawn", "an hour after moonrise", "half an hour after the launch window '
    'closes"); Julian dates ("MJD 61341.875", "JD 2461342.375": copy them into `julian`, do not convert); '
    'conditional plans ("if it rains that night, one day later at the same time"); and rumours or uncertain '
    'recollections (questions, "I heard", gossip, unsigned drafts, "unconfirmed", "don\'t take it seriously"). When '
    'the log defines which kinds of work cause instrument faults and which only void frames, follow its '
    'definitions, whatever the equipment is called.\n'
    'DO NOT convert times between clocks and DO NOT do time arithmetic yourself: report each time exactly as written '
    '(as a 24-hour HH:MM) with its date, the clock it is on, the signed number of minutes the log says to add or '
    'subtract, and what it is relative to. The agent does the arithmetic. Dates: give the calendar date M/D written '
    'with the time. Dates written relative to the handover day or as weekdays (今天, 明天, 后天, 昨天, 交接当天之后第 3 '
    '天 = D+3, "next Tuesday", 周二) are looked up in `calendar` (D+0 = the handover day); copy the M/D listed there. '
    'When the log only names the night (the night of 10/4, 10/4 当晚) give that date in `night` and leave `date` '
    'empty; the agent moves after-midnight times to the next calendar day. Also copy the date and the time exactly '
    'as written (after decoding) into date_text and time_text; the agent re-reads them. A time given only relative '
    'to another item (N minutes after a test window or a calibration ticket ends, later or earlier than another '
    'job) must be given with relative_to and shift_minutes and an empty time; never work it out yourself.\n'
    'Extract:\n'
    '1. fault_starts: every moment at which equipment work or a failure puts the instrument into a fault state that '
    'should be reported (for example "engineering will work on the guider camera at 21:30; frames are void until '
    'someone reports it", or "efficiency will drop from 3:15 because of engineering work, not the sky"). status: '
    '"confirmed" (stated or approved as fact), "conditional" (depends on weather or another condition; give it), '
    '"uncertain" (rumour, question, unconfirmed, draft, pending verification), "cancelled" or "wrong" (a time the log '
    'withdraws, strikes out or says is mistaken). For a postponement give the ORIGINAL written time with status '
    '"confirmed" and shift_minutes = the delay, and also the original time alone with status "cancelled". For "X is '
    'wrong, it is Y" give X as "wrong" and Y as "confirmed".\n'
    '2. lost_windows: windows in which frames are lost or wasted but which are NOT instrument faults and must NOT be '
    'reported (flat-lamp, mirror-cover, arc-lamp, bias, dark or other calibration tests and similar), one item per '
    'window, with the label the log gives it (ticket number, name or ordinal) so that times relative to it can name '
    'it in relative_to.label.\n'
    '3. closures: scheduled full stops or dome-closed windows, and windows in which one direction of the sky is '
    'affected (for example closed for strong wind or a launch window; follow the code words the log defines), with '
    'the direction as written ("all" for the whole site or dome) and its effect: "closed" if nothing can be '
    'observed there, "degraded" if it stays open with reduced efficiency, "observable" if the log says to observe '
    'as usual (same fields as lost_windows plus direction and effect).\n'
    '4. active_faults: statements that a fault has ALREADY happened and is still unrepaired (throughput dropped and '
    'has not recovered, not the sky, call engineering or file a ticket).\n'
    '5. standing_rules: lines of THIS section that later sections will rely on, copied as written (after decoding): '
    'definitions of code words and what they mean, which kinds of work cause instrument faults and which only void '
    'frames, whose entries are reliable or to be ignored, cipher keys, conventions for dates, clocks or labels. Not '
    'events, observations or schedule items (nothing with a date or a time of day); at most 6.\n'
    'Not faults: warnings that something may fail later or advice to watch the throughput (precursors); weather, '
    'including code words the log defines for weather; scheduled stops or shutdowns, even for work on the same '
    'equipment (those are closures). Standing rules and code words defined in earlier sections are given as '
    'context; apply them to this section, but take items only from log_lines (a standing rule is never an item).\n'
    'Use only the log. Do not invent items; a section may contain none of some kinds. Reply with one JSON object only.')

_WHEN = {'date_text': 'the date exactly as written for this item, e.g. "10/5（周一）", "后天（星期六）", '
                      '"15 October 2026", "10/4 当晚"; empty if none',
         'date': 'M/D calendar date written with the time (from `calendar` if relative or a weekday); empty if '
                 'none or if only the night is named',
         'night': 'M/D only if the log names the night instead of the calendar date, else empty'}
DUTY_REPLY_FORMAT = {
    'fault_starts': [dict(_WHEN, **{
        'time_text': 'the time exactly as written, e.g. "quarter to eleven p.m.", "二十三点三刻", "2130 hours"; '
                     'empty if the time is only relative',
        'time': 'HH:MM 24 h as written (empty if the time is only relative)',
        'clock': 'local | UTC | UTC+N | UTC-N (the clock the written time is on)',
        'shift_minutes': 'signed minutes to add (postponement, later/earlier than a reference); 0 if none',
        'julian': 'the Julian date exactly as written when the time is given as one ("MJD 61341.875", '
                  '"JD 2461342.375"), else empty',
        'relative_to': {'kind': 'none | window_end | window_start | closure_end | closure_start | job | sunset | '
                                'sunrise | dusk | dawn | moonrise | moonset (window = a lost-data test window; closure = '
                                'a stop, dome-closed, wind or launch window; dusk = end of evening twilight, 天黑; dawn = '
                                'start of morning twilight, 天亮; moonrise 月出, moonset 月落)',
                        'label': 'label of the referenced window or closure as written (ticket number or name), else '
                                 'empty',
                        'date': 'M/D of the night (window, closure, sunset, dusk, dawn, sunrise, moonrise, moonset) or '
                                'of the referenced job',
                        'index': 'which window (or closure) of that night, 1 = first'},
        'status': 'confirmed | conditional | uncertain | cancelled | wrong',
        'condition': 'only for conditional', 'quote': 'a few words copied from the line'})],
    'lost_windows': [dict(_WHEN, **{
        'label': 'ticket number, name or ordinal the log uses for this window, else empty',
        'start': 'HH:MM', 'end_date': 'M/D written with the end time if it differs, else empty', 'end': 'HH:MM',
        'clock': 'local | UTC | UTC+N | UTC-N', 'what': 'short', 'quote': 'a few words'})],
    'closures': [dict(_WHEN, **{'label': 'name if any, else empty', 'start': 'HH:MM', 'end_date': 'M/D or empty',
                                'end': 'HH:MM', 'clock': 'local | UTC | UTC+N | UTC-N',
                                'direction': 'compass range as written, e.g. "SE-SW" for 东南到西南一带, "N-E"; '
                                             '"all" for the whole site or dome',
                                'effect': 'closed | degraded | observable',
                                'quote': 'a few words'})],
    'active_faults': [{'date': 'M/D or empty', 'time': 'HH:MM or empty', 'clock': 'local | UTC | UTC+N | UTC-N',
                       'quote': 'a few words'}],
    'standing_rules': ['a definition or convention line of this section, as written']}


def duty_calendar(issued, utc_offset, before=7, after=21):
    """Bounded local calendar; malformed anchors cannot interrupt the rule reader."""
    import datetime as _dt
    try:
        if isinstance(issued, bool) or isinstance(utc_offset, bool):
            return []
        stamp, offset = float(issued), float(utc_offset)
        if not math.isfinite(stamp) or not math.isfinite(offset) or abs(offset) > 14:
            return []
        d0 = _dt.datetime.fromtimestamp(stamp + offset * 3600.0, tz=_dt.timezone.utc).date()
        before, after = min(60, max(0, int(before))), min(60, max(0, int(after)))
    except (TypeError, ValueError, OverflowError, OSError):
        return []
    rel = {-2: ' 前天', -1: ' 昨天', 0: ' 今天 handover day', 1: ' 明天', 2: ' 后天'}
    out = []
    for k in range(-before, after + 1):
        try:
            d = d0 + _dt.timedelta(days=k)
        except OverflowError:
            continue
        out.append('D%+d %d/%d %s 周%s%s' % (k, d.month, d.day, d.strftime('%a'), '一二三四五六日'[d.weekday()],
                                            rel.get(k, '')))
    return out


class DutyReader:
    """Language-model reader of the duty log, asked synchronously when a log section arrives (waiting for the
    model does not count against the CPU budget). Returns the operational schedule it extracted; the caller checks
    it against the deterministic parser and confirms fault times on the data before reporting."""

    def __init__(self, max_calls=150, attempt_timeout=75.0, question_deadline=120.0, wall_cap=2700.0, model=None):
        self.client = ChatClient()
        self.client.extra = {'thinking': {'type': 'disabled'}}     # a reasoning model would spend minutes per section
        if model:
            self.client.model = model
        self.enabled = (bool(self.client.key) and os.environ.get('OBSERVER_MODEL_DISABLED') != '1'
                        and os.environ.get('OBS_LLM_MOCK') != '1')
        self.max_calls = int(max_calls)
        self.attempt_timeout, self.question_deadline = float(attempt_timeout), float(question_deadline)
        self.wall_cap = float(wall_cap)
        self.calls = self.ok = self.failed = 0
        self.wall = 0.0
        self.dead = False
        self.t_start = time.monotonic()
        self.rules = []          # lines that define code words, keys or standing rules (kept for later sections)
        self._rule_keys = set()
        self.mrules = []         # the same, as the model marked them (any wording, any language)

    _RULE = re.compile(r'＝|从今天起|從今天起|记好|記好|规矩再讲|規矩再講|规矩不变|規矩不變|交接时请注意|交接時請注意|'
                       r'code ?words?|from now on|standing rule', re.I)
    _NOT_RULE = re.compile(r'英文按约定凯撒|老规矩，凯撒|シーザー暗号|加密了|凯撒，偏移|凯撒过了|凱撒')

    def _remember_rules(self, lines, hints):
        if not isinstance(lines, list):
            return
        hints = hints if isinstance(hints, dict) else {}

        def key(txt):
            return re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]+', '', txt.replace('報', '报').replace('後', '后'))

        for i, ln in enumerate(lines[:400]):
            if not isinstance(ln, str):
                continue
            txt = hints.get(str(i)) or ln
            if not isinstance(txt, str):
                continue
            if len(txt) < 400 and self._RULE.search(ln) and not self._NOT_RULE.search(ln):
                k = key(txt)
                self.rules = [rule for rule in self.rules if key(rule) != k]
                self.rules.append(txt)
                self.rules = self.rules[-12:]
        self._rule_keys = {key(rule) for rule in self.rules}

    _EVENT_LIKE = re.compile(r'\d{1,2}\s*[:：]\s*\d{2}|\d{1,2}\s*/\s*\d{1,2}|\d{1,2}\s*[点點時时]|[点點]半|'
                             r'[〇零一二两兩三四五六七八九十]{1,3}\s*[点點時]|\d{1,2}\s*(?:a\.?m\.?|p\.?m\.?|h\b|hours?\b)|'
                             r'\b(?:yesterday|today|tonight|tomorrow)\b|今天|今晚|昨天|昨晚|明天|明晚|后天|後天|今夜|昨夜|明日', re.I)

    @staticmethod
    def _rkey(txt):
        return re.sub(r'[^\u4e00-\u9fff\u3040-\u30ffA-Za-z0-9]+', '', txt.replace('報', '报').replace('後', '后')).lower()

    def _remember_model_rules(self, rules, lines, hints):
        """Definitions the model marked in this section (code words, which work is a fault, cipher keys, whom to
        trust) are kept for later sections when they are found in the section's text and name no date or time."""
        if not isinstance(rules, list):
            return
        src = ''.join(self._rkey(x) for x in lines if isinstance(x, str))
        if isinstance(hints, dict):
            src += ''.join(self._rkey(v) for v in hints.values() if isinstance(v, str))
        for r in rules[:6]:
            if not isinstance(r, str):
                continue
            r = r.strip()[:300]
            k = self._rkey(r)
            if len(k) < 6 or self._EVENT_LIKE.search(r):
                continue              # a dated or timed line is an event, not a rule (the known schedule carries it)
            grams = {k[i:i + 3] for i in range(len(k) - 2)}
            if not grams or sum(1 for g in grams if g in src) < 0.6 * len(grams):
                continue              # not in this section (a paraphrase or an invention)
            kept = [x for x in getattr(self, 'mrules', []) if self._rkey(x) != k]
            self.mrules = (kept + [r])[-12:]

    def standing_rules(self):
        out, seen = [], set()
        for x in list(getattr(self, 'rules', []))[-12:] + list(getattr(self, 'mrules', []))[-12:]:
            k = self._rkey(x)
            if k and k not in seen:
                seen.add(k)
                out.append(x)
        return out

    def usable(self, real_left=None):
        if not self.enabled or self.dead or self.calls >= self.max_calls or self.wall >= self.wall_cap:
            return False
        return real_left is None or real_left > self.question_deadline + 120.0

    def read(self, lines, hints, local_now, utc_offset, known, real_left=None, issued=None, chunk_chars=12000):
        """Read up to four bounded overlapping chunks; flag lost coverage before a strict merge."""
        if not isinstance(lines, list) or not lines or not self.usable(real_left):
            return None
        t0 = time.monotonic()
        if isinstance(chunk_chars, bool) or not isinstance(chunk_chars, int):
            chunk_chars = 12000
        budget = min(12000, max(256, chunk_chars))
        complete = len(lines) <= 400
        entries = []
        for i, ln in enumerate(lines[:400]):
            if not isinstance(ln, str):
                complete = False
                continue
            if len(ln) >= budget:
                complete = False
            entries.append((i, ln[:budget - 1]))
        if not entries:
            return None
        safe_hints = {}
        if isinstance(hints, dict):
            for count, (key, value) in enumerate(hints.items()):
                if count >= 400:
                    break
                if isinstance(key, int) and not isinstance(key, bool) and 0 <= key < 400:
                    key = str(key)
                if isinstance(key, str) and re.fullmatch(r'[0-9]{1,3}', key) and isinstance(value, str):
                    safe_hints[int(key)] = value[:12000]
        cal = duty_calendar(issued, utc_offset) if issued is not None else None
        keys = ('fault_starts', 'lost_windows', 'closures', 'active_faults')
        out, lo, n = None, 0, len(entries)
        for _ in range(4):
            if lo >= n:
                break
            hi, size = lo, 0
            while hi < n and size + len(entries[hi][1]) + 1 <= budget:
                size += len(entries[hi][1]) + 1
                hi += 1
            sub = {str(j): safe_hints[i] for j, (i, _) in enumerate(entries[lo:hi]) if i in safe_hints}
            remaining = None if real_left is None else real_left - (time.monotonic() - t0)
            res = self._read1([ln for _, ln in entries[lo:hi]], sub, local_now, utc_offset, known, remaining, cal)
            if res is None:
                complete = False
            else:
                complete = complete and res.get('_complete', False)
                if out is None:
                    out = {k: [] for k in keys}
                for k in keys:
                    out[k].extend(res[k])
            if hi >= n:
                lo = n
                break
            lo = max(lo + 1, hi - 6)
        if out is not None:
            out['_complete'] = bool(complete and lo >= n)
        return out

    def _read1(self, lines, hints, local_now, utc_offset, known, real_left, cal):
        if not self.usable(real_left):
            return None
        self.calls += 1
        t0 = time.monotonic()
        site = {'utc_offset_hours': utc_offset, 'local_time_now': local_now}
        payload = {'task': 'Extract the operational schedule from this new duty-log section.',
                   'site': site,
                   'standing_rules_from_earlier_sections': self.standing_rules(),
                   'known_schedule_from_earlier_sections': known,
                   'log_lines': lines,
                   'decoded_hints': hints,
                   'reply_format': DUTY_REPLY_FORMAT}
        if cal:
            payload['calendar'] = cal
        user = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        self._remember_rules(lines, hints)
        deadline = t0 + min(self.question_deadline, max(0.0, self.wall_cap - self.wall))
        # urllib's socket timeout is not a total response deadline (a trickling
        # body can keep resetting it). Bound the synchronous caller as well.
        result = queue.Queue(maxsize=1)
        client, attempt_timeout = self.client, self.attempt_timeout

        def ask_bounded():
            try:
                answer, info = client.ask(DUTY_SYSTEM_PROMPT, user, attempt_timeout, deadline,
                                          max_attempts=4, max_tokens=8000)
                result.put((answer, info if isinstance(info, dict) else {}))
            except Exception as exc:
                result.put((None, {'error': type(exc).__name__}))

        try:
            worker = threading.Thread(target=ask_bounded, daemon=True, name='duty-reader')
            worker.start()
            answer, info = result.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            # a slow answer (the service streams keep-alive blank lines while it queues the request) is a failure
            # like any other (four in a row end the model reading); so is leaving three questions unfinished
            # The current worker can finish between Queue.get timing out and
            # this handler. Count live threads consistently, including that one.
            hung = [w for w in [*getattr(self, '_hung', []), worker] if w.is_alive()]
            self._hung = hung
            answer, info = None, {'error': 'hard deadline', 'fatal': len(hung) >= 6}
        except Exception as exc:
            answer, info = None, {'error': type(exc).__name__}
        dt = time.monotonic() - t0
        self.wall += dt
        if info.get('fatal') and 'hard deadline' in str(info.get('error')):
            self.dead = True            # six questions are still hanging: stop opening new ones
        # any other error (even an HTTP 4xx) only costs this section: the parser reads it alone, the next
        # section asks the model again; only a long run of failures ends the model reading for the season
        out = self._clean(answer)
        if out is None:
            self.failed += 1
            self.fail_run = getattr(self, 'fail_run', 0) + 1
            if self.fail_run >= 8:
                self.dead = True        # the service keeps failing: the deterministic reader carries on alone
            _emit({'event': 'llm', 'stage': 'duty', 'ok': False, 'latency': round(dt, 2),
                   'error': info.get('error', 'bad answer'), 'dead': self.dead})
            return None
        self.fail_run = 0
        self.ok += 1
        try:
            # an item quoting a standing rule of an earlier section rather than this section is that rule, re-read
            rk = [self._rkey(x) for x in self.standing_rules()]
            if rk:
                src = ''.join(self._rkey(x) for x in lines if isinstance(x, str))
                if isinstance(hints, dict):
                    src += ''.join(self._rkey(v) for v in hints.values() if isinstance(v, str))
                for k in ('fault_starts', 'lost_windows', 'closures', 'active_faults'):
                    keep = []
                    for it in out[k]:
                        q = self._rkey(it.get('quote')) if isinstance(it.get('quote'), str) else ''
                        if len(q) >= 4 and q not in src and any(q in r for r in rk):
                            continue
                        keep.append(it)
                    out[k] = keep
            self._remember_model_rules(out.get('standing_rules'), lines, hints)
        except Exception:
            pass
        _emit({'event': 'llm', 'stage': 'duty', 'ok': True, 'latency': round(dt, 2), 'tokens': info.get('usage'),
               'n': [len(out[k]) for k in ('fault_starts', 'lost_windows', 'closures', 'active_faults')],
               'rules': len(getattr(self, 'mrules', []))})
        return out

    @staticmethod
    def _clean(answer):
        keys = ('fault_starts', 'lost_windows', 'closures', 'active_faults')
        if not isinstance(answer, dict) or not any(k in answer for k in keys):
            return None
        out = {}
        complete = all(isinstance(answer.get(k), list) for k in keys)
        allowed = ('date', 'time', 'clock', 'shift_minutes', 'status', 'condition', 'quote',
                   'night', 'start_date', 'start', 'end', 'what', 'date_text', 'time_text', 'label', 'end_date',
                   'direction', 'effect', 'julian')

        def scalar(value, limit):
            if isinstance(value, str):
                return value[:limit]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return '__invalid__'
            if isinstance(value, int) and value.bit_length() > 512:
                return '__invalid__'
            if isinstance(value, float) and not math.isfinite(value):
                return '__invalid__'
            return str(value)[:limit]

        for k in ('fault_starts', 'lost_windows', 'closures', 'active_faults'):
            v = answer.get(k)
            items = []
            if isinstance(v, list):
                if len(v) > 120:
                    complete = False
                for it in v[:120]:
                    if isinstance(it, dict):
                        d = {kk: scalar(it[kk], 160) for kk in allowed if kk in it}
                        if 'quote' in it and not isinstance(it['quote'], str):
                            d['quote'] = ''
                        if 'relative_to' in it:
                            rel = it['relative_to']
                            if isinstance(rel, dict):
                                d['relative_to'] = {kk: scalar(rel[kk], 40) for kk in ('kind', 'date', 'index', 'label') if kk in rel}
                            elif rel is not None:
                                d['relative_to'] = '__invalid__'
                        if d:
                            items.append(d)
                            if any(value == '__invalid__' for value in d.values() if isinstance(value, str)):
                                complete = False
                        else:
                            complete = False
                    else:
                        complete = False
            out[k] = items
        sr = answer.get('standing_rules')
        out['standing_rules'] = [x[:300] for x in sr[:6] if isinstance(x, str)] if isinstance(sr, list) else []
        out['_complete'] = complete
        return out
