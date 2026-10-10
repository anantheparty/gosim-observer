#!/usr/bin/env python3
"""Offline 20 base-32 symbols -> four 5x5 glyphs hypothesis. No network."""
import collections
import itertools
import json
from pathlib import Path

ROOT = Path('/home/shu/kamico/observer')
BASE = ROOT / 'work/sophon_desk'
records = [json.loads(s) for s in (BASE / 'desk_calls.jsonl').read_text().splitlines()]
code = json.loads(records[24]['reply'])['pass'].removeprefix('SOPHON{').removesuffix('}')
agent = json.loads((ROOT / 'work/online/sophon3_2d79/179e0a27-f9d8-4207-b36b-daa402e0c987/agent_log.json').read_text())
font = {}
for line in agent['log'].splitlines():
    if 'sophon_glyph' not in line:
        continue
    try:
        obj = json.loads(line[line.index('{'):])
    except (ValueError, TypeError):
        continue
    night = obj.get('night')
    if obj.get('event') == 'sophon_glyph' and isinstance(night, int) and 3 <= night <= 12:
        font['THESHINING'[night - 3]] = tuple(obj['rows'])
reverse_font = {v: k for k, v in font.items()}
alphabets = {'public_invite_alphabet': 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789',
             'sorted_alphabet': '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'}


def orient(rows, rotation, mirror):
    out = list(rows)
    if mirror:
        out = [row[::-1] for row in out]
    for _ in range(rotation):
        out = [''.join(col) for col in zip(*out[::-1])]
    return tuple(out)


def decode(text, alphabet, layout, offset, rotation, mirror, invert):
    rows = [format((alphabet.index(ch) + offset) % 32, '05b').translate(
        str.maketrans('01', '#.' if invert else '.#')) for ch in text]
    tiles = ([rows[k:k + 5] for k in range(0, 20, 5)] if layout == 'consecutive'
             else [[rows[y * 4 + x] for y in range(5)] for x in range(4)])
    return [orient(tile, rotation, mirror) for tile in tiles]


# Positive controls use observed glyphs and both supported layouts.
for alphabet in alphabets.values():
    for layout in ('consecutive', 'interleaved_rows'):
        tiles = [font[c] for c in 'SIGN']
        rows = ([r for tile in tiles for r in tile] if layout == 'consecutive'
                else [tiles[x][y] for y in range(5) for x in range(4)])
        encoded = ''.join(alphabet[int(r.translate(str.maketrans('.#', '01')), 2)] for r in rows)
        assert ''.join(reverse_font.get(t, '?') for t in decode(encoded, alphabet, layout, 0, 0, False, False)) == 'SIGN'

best = -1
examples = []
fully_readable = []
tested = 0
for (name, alphabet), layout, offset, rotation, mirror, invert in itertools.product(
        alphabets.items(), ('consecutive', 'interleaved_rows'), range(32), range(4), (False, True), (False, True)):
    tiles = decode(code, alphabet, layout, offset, rotation, mirror, invert)
    text = ''.join(reverse_font.get(tile, '?') for tile in tiles)
    count = 4 - text.count('?')
    tested += 1
    entry = {'alphabet': name, 'layout': layout, 'offset': offset, 'rotation': rotation,
             'mirror': mirror, 'invert': invert, 'exact_observed_glyphs': text, 'tiles': tiles}
    if count == 4:
        fully_readable.append(entry)
    if count > best:
        best, examples = count, [entry]
    elif count == best and len(examples) < 4:
        examples.append(entry)

report = {'hypothesis': '20 symbols of 5 bits encode four 5x5 glyphs',
          'source': 'desk_calls.jsonl L25 reply.pass; online observed THESHINING glyphs',
          'font': font, 'symbol_multiplicities': sorted(collections.Counter(code).values(), reverse=True),
          'tested': tested, 'positive_controls': 4, 'max_exact_observed_glyphs_in_one_decode': best,
          'fully_readable': fully_readable, 'examples': examples,
          'limit': 'No inference about unknown alphabets, fonts, arbitrary permutations, or cryptographic encodings.'}
(BASE / 'validation/pass_grid_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: report[k] for k in ['tested', 'positive_controls', 'max_exact_observed_glyphs_in_one_decode', 'fully_readable']}))
