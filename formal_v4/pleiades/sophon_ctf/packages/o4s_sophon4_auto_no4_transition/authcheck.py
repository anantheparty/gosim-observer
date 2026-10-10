"""Disabled fresh-auto test for the decoy-pass -> genuine-pass transition.

This module is enabled only after a current evaluation proves the dedicated
SOPHON_RUN_TOKEN desk contract. It never falls back to the observer token and
never logs runtime capabilities, dynamic room identifiers, or flag values.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://vdiemcofukuxglqsmlyz.supabase.co/functions/v1/sophon'
SENTENCE = ('I SAW A COLLECTION OF LEAVES FORM AN ENDLESS HOUSE SEE YOU AFTER '
            'JAN 5 1997 WHILE EVERYTHING SHOULD BE REVEALED THROUGH THE FINAL TRIALS')
HOUSE_LINE = 'Whoever finds and publishes this work shall be entitled to all proceeds.'
FLAG_RE = re.compile(r'^SOPHON\{[A-Z0-9]{20}\}$')
ROOM_RE = re.compile(r'^[a-z0-9]{1,64}$')
BAR_LIMIT = 12
HOUSE_VISIT_LIMIT = 160
ORDINAL = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4}
KNOWN_ERRORS = {'closed', 'wrong_answer', 'locked', 'unauthorized', 'forbidden',
                'invalid_token', 'invalid_run', 'invalid_run_credential',
                'invalid_or_expired_capability', 'rate_limited', 'already_solved',
                'fooled', 'not_inside'}


def log(event, **fields):
    print(json.dumps({'event': event, **fields}, separators=(',', ':')),
          file=sys.stderr, flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _load_config():
    path = Path(__file__).resolve().parent / 'auto_no4_config.json'
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get('enabled') is not True:
        return None
    run_id = value.get('verification_run_id')
    if (value.get('auth_mode') != 'sophon_token' or
            value.get('verified_board') != 'auto' or
            not isinstance(run_id, str) or
            not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',
                             run_id)):
        raise ValueError('verification metadata missing')
    return value


def _summary(probe, status, parsed):
    out = {'probe': probe, 'status': status}
    if not isinstance(parsed, dict):
        out['body_kind'] = type(parsed).__name__
        return out
    out['keys'] = sorted(str(k) for k in parsed)[:60]
    for key in ('ok', 'solved'):
        if type(parsed.get(key)) is bool:
            out[key] = parsed[key]
    if type(parsed.get('no')) is int and 1 <= parsed['no'] <= 22:
        out['no'] = parsed['no']
    if parsed.get('board') in ('auto', 'debug'):
        out['board'] = parsed['board']
    error = parsed.get('error')
    if isinstance(error, str):
        out['error'] = error if error in KNOWN_ERRORS else 'other'
    found = parsed.get('found')
    if isinstance(found, list):
        out['found_numbers'] = sorted(
            x['no'] for x in found if isinstance(x, dict) and
            type(x.get('no')) is int and 1 <= x['no'] <= 22)
    out['has_pass'] = isinstance(parsed.get('pass'), str) and bool(
        FLAG_RE.fullmatch(parsed['pass']))
    out['has_flag'] = isinstance(parsed.get('flag'), str) and bool(
        FLAG_RE.fullmatch(parsed['flag']))
    return out


def _request(token, probe, method, path, body=None):
    if method == 'GET':
        separator = '&' if '?' in path else '?'
        path += separator + 'token=' + urllib.parse.quote(token, safe='')
        data, headers = None, {}
    else:
        body = dict(body or {})
        body['token'] = token
        data = json.dumps(body, separators=(',', ':')).encode()
        headers = {'Content-Type': 'application/json'}
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=5) as response:
            status, raw = response.status, response.read(16384)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(16384)
    except Exception:
        return {'probe': probe, 'status': None, 'error': 'network_error'}, None
    try:
        parsed = json.loads(raw.decode('utf-8', 'replace'))
    except Exception:
        return {'probe': probe, 'status': status, 'error': 'unreadable_response'}, None
    return _summary(probe, status, parsed), parsed if isinstance(parsed, dict) else None


def _flag(parsed, fields=('flag', 'pass', 'code', 'receipt')):
    if not isinstance(parsed, dict):
        return None
    for field in fields:
        value = parsed.get(field)
        if isinstance(value, str) and FLAG_RE.fullmatch(value):
            return value
    return None


def _flags(parsed, fields=('flag', 'pass', 'code', 'receipt')):
    """Return distinct issued codes in field order; values remain in memory only."""
    if not isinstance(parsed, dict):
        return []
    values = []
    for field in fields:
        value = parsed.get(field)
        if (isinstance(value, str) and FLAG_RE.fullmatch(value) and
                value not in values):
            values.append(value)
    return values


def _submit_issued(token, parsed, submitted_codes, probe):
    """Submit only codes issued by the live response; report a confirmed No.4.

    This deliberately accepts a normal flag field as well as secondary pass /
    code / receipt fields.  The values are discovered during the run rather
    than copied from the debug board.  Only a code whose desk reply identifies
    it as No.4 is written to the diagnostic log.
    """
    follow_codes = []
    for index, issued in enumerate(_flags(parsed), 1):
        if issued in submitted_codes:
            continue
        result, reply = _request(token, probe, 'POST', '/desk/flag',
                                 {'flag': issued})
        submitted_codes.add(issued)
        log('auto_no4_transition_step', issued_index=index, **result)
        if result.get('solved') is True and result.get('no') == 4:
            log('auto_no4_issued', issued_flag=issued)
            return True, []
        follow_codes.extend(value for value in _flags(reply)
                            if value not in submitted_codes and
                            value not in follow_codes)
    return False, follow_codes


def _remember_237(words, parsed):
    if not isinstance(parsed, dict) or not isinstance(parsed.get('johnny'), str):
        return
    for quote in re.findall(r'"([^"]+)"', parsed['johnny']):
        if '237' not in quote:
            continue
        match = (re.search(r'word number ([1-4]) is ([A-Z]+)', quote) or
                 re.search(r'the (first|second|third|fourth) '
                           r'(?:word|one) is ([A-Z]+)', quote))
        if not match:
            continue
        index = int(match.group(1)) if match.group(1).isdigit() else ORDINAL[match.group(1)]
        words[index] = match.group(2)


def _accepted(result):
    return result.get('status') == 200 and result.get('ok') is True


def run(decision_sequence=None):
    try:
        _run(decision_sequence)
    except Exception:
        log('auto_no4_transition_stop', reason='internal_error')


def _run(decision_sequence):
    if os.environ.get('SAC_LOCAL_RUNNER'):
        log('auto_no4_transition_skipped', reason='local_runner')
        return
    try:
        config = _load_config()
    except Exception:
        log('auto_no4_transition_skipped', reason='invalid_config')
        return
    if config is None:
        log('auto_no4_transition_skipped', reason='disabled')
        return
    if type(decision_sequence) is not int or decision_sequence < 1:
        log('auto_no4_transition_skipped', reason='decision_barrier_missing')
        return
    token = os.environ.get('SOPHON_RUN_TOKEN', '')
    if not token:
        log('auto_no4_transition_skipped', reason='sophon_credential_absent')
        return

    started = time.monotonic()
    result, _ = _request(token, 'contact', 'POST', '/contact-johnny')
    log('auto_no4_transition_step', **result)
    if not _accepted(result):
        log('auto_no4_transition_done', reason='contact_stop')
        return
    result, _ = _request(token, 'answer', 'POST', '/answer', {'sentence': SENTENCE})
    log('auto_no4_transition_step', **result)
    if not _accepted(result):
        log('auto_no4_transition_done', reason='answer_stop')
        return
    result, _ = _request(token, 'auto_root_before', 'GET', '/desk')
    log('auto_no4_transition_step', **result)
    if not _accepted(result) or result.get('board') != 'auto':
        log('auto_no4_transition_done', reason='auto_board_not_verified')
        return

    result, _ = _request(token, 'front_door', 'POST', '/desk/door',
                         {'say': 'THE SHINING'})
    log('auto_no4_transition_step', **result)
    if not _accepted(result):
        log('auto_no4_transition_done', reason='front_door_stop')
        return

    words, decoy, fooled = {}, None, False
    for attempt in range(1, BAR_LIMIT + 1):
        result, parsed = _request(token, 'bar', 'POST', '/desk/bar',
                                  {'say': 'What is the first word, Lloyd?'})
        _remember_237(words, parsed)
        log('auto_no4_transition_step', attempt=attempt,
            known_word_slots=sorted(words), **result)
        if not _accepted(result):
            log('auto_no4_transition_done', reason='bar_stop', bar_calls=attempt)
            return
        candidate = _flag(parsed, ('pass',))
        if decoy is None and candidate is not None:
            decoy = candidate
            submitted, decoy_reply = _request(token, 'decoy_submit', 'POST',
                                              '/desk/flag', {'flag': decoy})
            log('auto_no4_transition_step', **submitted)
            if submitted.get('solved') is True and submitted.get('no') == 4:
                log('auto_no4_issued', issued_flag=decoy)
                log('auto_no4_transition_done', reason='decoy_solved_no4',
                    bar_calls=attempt)
                return
            if submitted.get('error') != 'fooled':
                log('auto_no4_transition_done', reason='unexpected_decoy_result',
                    bar_calls=attempt)
                return
            # A conditional receipt may accompany the fooled response.  The
            # decoy itself is excluded from re-submission.
            solved_no4, _ = _submit_issued(token, decoy_reply, {decoy},
                                           'decoy_receipt_submit')
            if solved_no4:
                log('auto_no4_transition_done', reason='decoy_receipt_solved_no4',
                    bar_calls=attempt)
                return
            fooled = True
        if decoy is not None and set(words) == {1, 2, 3, 4}:
            break
    if not fooled or set(words) != {1, 2, 3, 4}:
        log('auto_no4_transition_done', reason='fresh_bar_sequence_incomplete',
            known_word_slots=sorted(words))
        return

    door_path = '/desk/door/' + '-'.join(words[i] for i in range(1, 5))
    result, parsed = _request(token, 'four_word_door', 'GET', door_path)
    log('auto_no4_transition_step', **result)
    if not _accepted(result):
        log('auto_no4_transition_done', reason='four_word_door_stop')
        return
    submitted_codes = {decoy}
    solved_no4, follow_codes = _submit_issued(
        token, parsed, submitted_codes, 'door_issued_submit')
    if solved_no4:
        log('auto_no4_transition_done', reason='door_transition_solved_no4')
        return

    result, parsed = _request(token, 'house_line', 'POST', '/desk/house',
                              {'line': HOUSE_LINE})
    log('auto_no4_transition_step', **result)
    if not _accepted(result):
        log('auto_no4_transition_done', reason='house_line_stop')
        return
    solved_no4, more_codes = _submit_issued(
        token, parsed, submitted_codes, 'house_issued_submit')
    follow_codes.extend(value for value in more_codes if value not in follow_codes)
    if solved_no4:
        log('auto_no4_transition_done', reason='house_transition_solved_no4')
        return
    result, parsed = _request(token, 'house_enter', 'POST', '/desk/house/enter')
    log('auto_no4_transition_step', **result)
    room = parsed.get('room') if isinstance(parsed, dict) else None
    if not _accepted(result) or not isinstance(room, str) or not ROOM_RE.fullmatch(room):
        log('auto_no4_transition_done', reason='house_enter_stop')
        return

    # Each entry creates a different labelled graph.  Crawl only room ids the
    # current response disclosed; direct room GETs are the published movement
    # contract and the server allows the full 124-room map to be explored.
    # Values stay in memory and are never logged.
    pending, queued, visited = [room], {room}, set()
    genuine_codes = []
    visits = 0
    while pending and visits < HOUSE_VISIT_LIMIT:
        room = pending.pop(0)
        queued.discard(room)
        if room in visited:
            continue
        visited.add(room)
        visits += 1
        result, parsed = _request(token, 'house_room', 'GET',
                                  '/desk/house/room/' + room)
        log('auto_no4_transition_step', house_visit=visits,
            rooms_seen=len(visited), rooms_queued=len(pending), **result)
        if not _accepted(result) or not isinstance(parsed, dict):
            log('auto_no4_transition_done', reason='house_crawl_stop',
                house_visit=visits)
            return
        genuine_codes = [value for value in _flags(parsed) if value != decoy]
        if genuine_codes:
            break
        doors = parsed.get('doors')
        if isinstance(doors, dict):
            for next_room in doors.values():
                if (isinstance(next_room, str) and ROOM_RE.fullmatch(next_room) and
                        next_room not in visited and next_room not in queued):
                    pending.append(next_room)
                    queued.add(next_room)
    if not genuine_codes:
        log('auto_no4_transition_done', reason='genuine_pass_missing',
            house_visits=visits, frontier_remaining=len(pending))
        return

    solved_no4, more_codes = _submit_issued(
        token, parsed, submitted_codes, 'genuine_submit')
    follow_codes.extend(value for value in more_codes if value not in follow_codes)
    if solved_no4:
        log('auto_no4_transition_done', reason='genuine_transition_solved_no4',
            house_visits=visits)
        return
    # One bounded response-following level: accept a newly issued transition
    # receipt, but never recurse or enumerate guessed variants.
    for index, issued in enumerate(follow_codes, 1):
        follow, _ = _request(token, 'transition_receipt_submit', 'POST',
                             '/desk/flag', {'flag': issued})
        log('auto_no4_transition_step', receipt_index=index, **follow)
        if follow.get('solved') is True and follow.get('no') == 4:
            log('auto_no4_issued', issued_flag=issued)
            log('auto_no4_transition_done', reason='receipt_solved_no4',
                house_visits=visits)
            return

    final, _ = _request(token, 'auto_root_after', 'GET', '/desk')
    log('auto_no4_transition_step', **final)
    log('auto_no4_transition_done', reason='transition_complete',
        house_visits=visits,
        elapsed_ms=round((time.monotonic() - started) * 1000))
