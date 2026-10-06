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
            if e.code == 400 and self.json_mode:
                # some endpoints reject response_format / temperature: retry once in plain mode
                self.json_mode = False
                raise _Retryable('http 400 (json mode off)', 0.0) from None
            raise _Fatal(f'http {e.code}') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise _Retryable(type(e).__name__) from None

    def ask(self, system, user, attempt_timeout, deadline, max_attempts=3):
        """One question; returns (answer dict or None, info dict)."""
        info = {'attempts': 0}
        for k in range(max_attempts):
            left = deadline - time.monotonic()
            if left < 2.0:
                info['error'] = 'deadline'
                break
            body = {'model': self.model, 'max_tokens': 4000,
                    'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
            if self.json_mode:
                body['temperature'] = 0
                body['response_format'] = {'type': 'json_object'}
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
