#!/usr/bin/env python3
"""Offline desk-response inventory; writes aliases, never raw flags or credentials."""
import collections
import hashlib
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / 'validation/no4_full_evidence.json'
FLAG = re.compile(r'SOPHON\{[^}]*\}')
SECRET_KEY = re.compile(r'^(?:token|.*_token|authorization|headers|password|credential|api_?key)$', re.I)


def decode(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {'_raw_text': value}
    return value


def walk(value, path=''):
    if isinstance(value, dict):
        for key, val in value.items():
            yield path + '/' + str(key), val
            if not SECRET_KEY.fullmatch(str(key)):
                yield from walk(val, path + '/' + str(key))
    elif isinstance(value, list):
        for i, val in enumerate(value):
            yield path + '/' + str(i), val
            yield from walk(val, path + '/' + str(i))


def flags(value):
    if isinstance(value, str):
        yield from FLAG.findall(value)
    for path, val in walk(value):
        if isinstance(val, str) and not SECRET_KEY.fullmatch(path.rsplit('/', 1)[-1]):
            yield from FLAG.findall(val)


source_bytes = (BASE / 'desk_calls.jsonl').read_bytes()
rows = []
for line, raw in enumerate(source_bytes.decode().splitlines(), 1):
    obj = json.loads(raw)
    obj['line'] = line
    obj['reply'] = decode(obj['reply'])
    obj['body'] = decode(obj['body'])
    rows.append(obj)
house = [json.loads(v) for v in (BASE / 'house_map.jsonl').read_text().splitlines()]
rooms = json.loads((BASE / 'rooms.json').read_text())
boards = json.loads((BASE / 'boards_now.json').read_text())
hand_path = BASE.parent / 'online/sophon_flags.log'
hand = []
accepted = {}
accepted_sources = collections.defaultdict(list)
for row in rows:
    reply = row['reply']
    if isinstance(reply, dict) and reply.get('solved') and isinstance(reply.get('no'), int):
        for value in flags(row['body']):
            accepted[value] = reply['no']
            accepted_sources[reply['no']].append({'source': 'desk_calls.jsonl', 'line': row['line'], 't': row['t']})
for line, raw in enumerate(hand_path.read_text().splitlines(), 1):
    match = re.search(r'->\s+(\d{3})\s+(\{.*\})', raw)
    state = {'source': 'work/online/sophon_flags.log', 'line': line}
    stamp = re.search(r'2026-\d\d-\d\dT\d\d:\d\d:\d\dZ', raw)
    if stamp:
        state['t'] = stamp.group()
    if match:
        reply = json.loads(match[2])
        state.update(http_status=int(match[1]), reply=reply)
        if reply.get('solved') and isinstance(reply.get('no'), int):
            for value in FLAG.findall(raw):
                accepted[value] = reply['no']
                accepted_sources[reply['no']].append({k: v for k, v in state.items() if k != 'reply'})
    else:
        http = re.search(r'\b(200|403|422|429|500)\b', raw)
        if http:
            state['http_status'] = int(http.group())
        state['parsed_success_reply'] = False
    state['flag_strings'] = FLAG.findall(raw)
    hand.append(state)

fake_passes = {v for row in rows if isinstance(row['reply'], dict)
               for v in flags(row['reply'].get('pass'))}
aliases = {value: 'FLAG_NO_' + str(no) for value, no in accepted.items()}
aliases.update({value: 'FAKE_PASS_' + str(i + 1) for i, value in enumerate(sorted(fake_passes))})
aliases['SOPHON{...}'] = 'FLAG_FORMAT_PLACEHOLDER'


def alias(value):
    if value not in aliases:
        aliases[value] = 'UNMAPPED_FLAG_' + str(1 + sum(v.startswith('UNMAPPED_') for v in aliases.values()))
    return aliases[value]


def clean(value):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if SECRET_KEY.fullmatch(str(k)) else clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str):
        value = FLAG.sub(lambda m: '[' + alias(m.group()) + ']', value)
        value = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED]', value)
        value = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9_.-]+', r'\1[REDACTED]', value)
    return value


catalogue = collections.defaultdict(list)


def record_flags(value, context, prefix):
    for path, val in walk(value):
        if isinstance(val, str) and not SECRET_KEY.fullmatch(path.rsplit('/', 1)[-1]):
            for found in FLAG.findall(val):
                catalogue[alias(found)].append({**context, 'field': prefix + path})


field_inventory = collections.defaultdict(list)
schemas = collections.defaultdict(list)
extra_timeline = []
desk_states = []
receipts = collections.defaultdict(list)
bar_schema = collections.defaultdict(list)
for row in rows:
    context = {k: row[k] for k in ('line', 't', 'method', 'path', 'status')}
    reply = row['reply']
    record_flags(reply, {'source': 'desk_calls.jsonl', **context}, '/reply')
    record_flags(row['body'], {'source': 'desk_calls.jsonl', **context}, '/body')
    if not isinstance(reply, dict):
        continue
    for path, val in walk(reply):
        normalized = re.sub(r'/\d+(?=/|$)', '/[]', path)
        field_inventory[normalized].append({'line': row['line'], 't': row['t']})
    schemas[','.join(sorted(reply))].append(row['line'])
    extras = {k: v for k, v in reply.items() if k not in ('ok', 'johnny', 'message')}
    if extras:
        extra_timeline.append({**context, 'fields': clean(extras)})
    if '/desk/bar' in row['path']:
        bar_schema[','.join(sorted(reply))].append(row['line'])
    if 'found' in reply:
        desk_states.append({**context, 'board': reply.get('board'), 'found': reply['found'],
                            'missing': sorted(set(range(1, 23)) - {v['no'] for v in reply['found']}),
                            'next_present': 'next' in reply, 'next': reply.get('next'),
                            'pending': clean(reply.get('pending')), 'doors': clean(reply.get('doors'))})
    for record in reply.get('checked', []):
        receipts[record['run_id']].append({**context, **clean(record)})

for line, row in enumerate(house, 1):
    record_flags(row, {'source': 'house_map.jsonl', 'line': line, 'room': row['room']}, '')
record_flags(rooms, {'source': 'rooms.json'}, '')
for row in hand:
    for value in row.pop('flag_strings'):
        catalogue[alias(value)].append({**{k: v for k, v in row.items() if k != 'reply'}, 'field': '/submitted_flag'})

last_found = desk_states[-1]['found']
at_to_flag = {r['at']: r for r in last_found}
board_mapping = []
for row in boards['sophon_board']:
    found = at_to_flag.get(row['solved_at'])
    board_mapping.append({'display_flag': row['flag'], 'board': row['board'], 'solved_at': row['solved_at'],
                          'desk_no': found['no'] if found else None, 'name': found['name'] if found else None,
                          'join_basis': 'exact solved_at == found.at' if found else 'unmatched'})

special_house = []
room_ids = {row['room'] for row in house}
targets = set()
for line, row in enumerate(house, 1):
    reply = row['reply']
    targets.update(reply.get('doors', {}).values())
    extra = {k: v for k, v in reply.items() if k not in ('ok', 'johnny', 'message', 'room', 'doors', 'moves')}
    if extra:
        special_house.append({'line': line, 'room': row['room'], 'extra': clean(extra),
                              'text': clean(reply.get('message'))})
special_rooms = {k: clean(v) for k, v in rooms.items() if set(v) - {'status', 'ok', 'johnny', 'message'}}

unknown_returned = []
for name, appearances in catalogue.items():
    if name.startswith('UNMAPPED_'):
        returned = [v for v in appearances if v.get('field', '').startswith('/reply')]
        if returned:
            unknown_returned.append({'alias': name, 'appearances': returned})

noteworthy = []
for row in rows:
    reply = row['reply']
    if not isinstance(reply, dict):
        continue
    singletons = [k for k in reply if len(field_inventory['/' + k]) == 1]
    if singletons or 'flag' in reply or reply.get('error') == 'fooled':
        noteworthy.append({**{k: row[k] for k in ('line', 't', 'method', 'path', 'status')},
                           'singleton_fields': singletons, 'reply': clean(reply)})

route_contracts = []
for row in rows:
    seen = set()
    for field, value in walk(row['reply']):
        if isinstance(value, str) and re.search(r'\b(?:GET|POST) /desk(?:/|\b)', value):
            if value in seen:
                continue
            seen.add(value)
            route_contracts.append({**{k: row[k] for k in ('line', 't', 'method', 'path')},
                                    'field': field, 'text': clean(value)})

out = {
    'scope': {'source': 'work/sophon_desk/desk_calls.jsonl', 'sha256': hashlib.sha256(source_bytes).hexdigest(),
              'lines': len(rows), 'first_t': rows[0]['t'], 'last_t': rows[-1]['t'],
              'offline_only': True, 'raw_flags_and_credentials_written': False},
    'latest_state': desk_states[-1],
    'summary': {'accepted_numbers': sorted(accepted_sources), 'accepted_number_count': len(accepted_sources),
                'reply_flag_occurrences': len(field_inventory['/flag']),
                'pass_occurrences': len(field_inventory['/pass']),
                'usage_field_occurrences': len(field_inventory.get('/usage', [])),
                'unmapped_returned_flag_aliases': unknown_returned,
                'flag_catalogue_size_including_placeholders_and_rejected_guesses': len(catalogue)},
    'field_inventory': {k: {'occurrences': len(v), 'first': v[0], 'last': v[-1],
                             'lines': sorted({r['line'] for r in v})} for k, v in sorted(field_inventory.items())},
    'reply_schemas': [{'fields': k.split(','), 'count': len(v), 'lines': v} for k, v in sorted(schemas.items())],
    'extra_fields_timeline': extra_timeline,
    'noteworthy_full_responses': noteworthy,
    'route_contract_timeline': route_contracts,
    'bar_reply_schemas': [{'fields': k.split(','), 'count': len(v), 'lines': v} for k, v in sorted(bar_schema.items())],
    'flag_catalogue_aliases': dict(catalogue),
    'accepted_sources': dict(accepted_sources),
    'hand_in_log': clean(hand),
    'desk_state_timeline': desk_states,
    'receipts_by_run': dict(receipts),
    'boards_mapping_by_timestamp': board_mapping,
    'board_label_implementation': {
        'source': 'hackathon-survey26/supabase/migrations/20261006000000_sophon_boards.sql',
        'line': 41,
        'rule': "'F' || dense_rank() over (partition by board order by min(at), no)",
        'meaning': 'Display labels rank puzzles by earliest solve within each board, not by puzzle no.'},
    'house': {'response_count': len(house), 'unique_rooms': len(room_ids),
              'unread_exit_targets': sorted(targets - room_ids), 'special_fields': special_house},
    'rooms': {'cached_numbers': sorted(rooms), 'additional_fields': special_rooms,
              'room_217_cache_present': '217' in rooms},
    'conclusions': [
        'The latest desk found list is authoritative for puzzle numbers; board F labels are not puzzle no values.',
        'Every flag-shaped string actually returned by the audited desk/house responses is mapped to an accepted number, a known fake pass, or the format placeholder.',
        'No.4 is absent from accepted desk and hand-in records.' if 4 not in accepted_sources else 'No.4 is present in accepted records.',
        'One occurrence does not establish an implementation-level one-shot trigger; the pass was seen once and later rejected as fooled.',
        'A missing usage field does not mean there are no usage instructions: contracts also occur in answer, door, go, next, visit, more, checkout, and message.'
    ],
}
assert not unknown_returned
serialized = json.dumps(clean(out), ensure_ascii=False, indent=2) + '\n'
assert not FLAG.search(serialized)
assert not re.search(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', serialized)
OUT.write_text(serialized)
print(json.dumps({'output': str(OUT), 'summary': out['summary'], 'latest_missing': out['latest_state']['missing'],
                  'schema_count': len(schemas), 'receipt_run_count': len(receipts),
                  'bar_schemas': [{k: v for k, v in r.items() if k != 'lines'} for r in out['bar_reply_schemas']]}, ensure_ascii=False))
