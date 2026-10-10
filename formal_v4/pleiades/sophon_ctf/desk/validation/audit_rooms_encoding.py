#!/usr/bin/env python3
"""Bounded offline decoding audit, with composition-preserving null controls.

No network or API access. Writes only the requested JSON report.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
from itertools import permutations, product
import json
from pathlib import Path
import re
import time

import numpy as np

HERE = Path(__file__).resolve().parent
MAPS = np.array(list(permutations(range(4))), dtype=np.uint8)
DESCS = ["A wasps' nest on the windowsill.", "An empty room. The bed is made.",
         "Somebody's suitcase, never unpacked.", "Cold. The radiator is off."]


def templates():
    out = []
    for absent in [(217, 237), (217,), (237,), ()]:
        nums = [n for n in range(200, 241) if n not in absent]
        prefix = 'omit_' + '_'.join(map(str, absent)) if absent else 'include_both'
        orders = {'ascending': nums, 'descending': nums[::-1]}
        for p in (217, 237):
            low, high = [n for n in nums if n < p], [n for n in nums if n >= p]
            orders[f'rotate_at_{p}'] = high + low
            orders[f'reflect_before_{p}'] = low[::-1] + high
            orders[f'reflect_after_{p}'] = low + high[::-1]
            orders[f'outward_{p}_left_first'] = sorted(nums, key=lambda n: (abs(n-p), n))
            orders[f'outward_{p}_right_first'] = sorted(nums, key=lambda n: (abs(n-p), -n))
        orders['even_then_odd'] = sorted(nums, key=lambda n: (n % 2, n))
        orders['ones_then_tens'] = sorted(nums, key=lambda n: (n % 10, n // 10))
        if len(nums) == 40:
            for h, w in ((8, 5), (5, 8)):
                a = np.array(nums).reshape(h, w)
                orders[f'grid_{h}x{w}_columns'] = a.T.ravel().tolist()
                for phase in (0, 1):
                    b = a.copy()
                    b[phase::2] = b[phase::2, ::-1]
                    orders[f'grid_{h}x{w}_snake_{phase}'] = b.ravel().tolist()
        seen = set()
        for name, order in orders.items():
            if tuple(order) not in seen:
                out.append((prefix + '/' + name, order))
                seen.add(tuple(order))
    # Explicit exploratory family: all orders/orientations of the three runs
    # separated by the missing 217 and special 237, using ordinary rooms only.
    parts = [list(range(200, 217)), list(range(218, 237)), list(range(238, 241))]
    for perm in permutations(range(3)):
        for rev in product((0, 1), repeat=3):
            order = sum([(parts[i][::-1] if rev[i] else parts[i]) for i in perm], [])
            out.append(('segments/' + ''.join(map(str, perm)) + '/' + ''.join(map(str, rev)), order))
    unique = {}
    for name, order in out:
        unique.setdefault(tuple(order), name)
    return [(name, list(order)) for order, name in unique.items()]


def expanded(values, ts):
    bylen = defaultdict(list)
    meta = defaultdict(list)
    for name, order in ts:
        unknown = [n for n in (217, 237) if n in order]
        for fills in product(range(4), repeat=len(unknown)):
            val = values.copy()
            for n, fill in zip(unknown, fills):
                val[n-200] = fill
            q = val[np.array(order)-200]
            for mi, mapping in enumerate(MAPS):
                bylen[len(q)].append(mapping[q])
                meta[len(q)].append((name, dict(zip(unknown, fills)), mi))
    return {n: np.array(v, dtype=np.uint8) for n, v in bylen.items()}, meta


def ascii_audit(values, ts, detail=False):
    groups, meta = expanded(values, ts)
    total = all_print = all_alpha = 0
    best_ratio = 0.0
    candidates = {}
    for n, q in groups.items():
      encodings = {'interleaved': np.stack((q >> 1, q & 1), axis=2).reshape(len(q), n*2),
                   'two_planes': np.concatenate((q >> 1, q & 1), axis=1)}
      for encoding, bits in encodings.items():
        for off in range(8):
            count = (2*n-off)//8
            if count < 8:
                continue
            b = np.packbits(bits[:, off:off+count*8], axis=1)
            printable = ((b >= 32) & (b <= 126)).sum(axis=1)
            letters = (((b >= 65) & (b <= 90)) | ((b >= 97) & (b <= 122))).sum(axis=1)
            total += len(b)
            all_print += int((printable == count).sum())
            all_alpha += int((letters == count).sum())
            best_ratio = max(best_ratio, float(printable.max()/count))
            if detail:
                rank = printable/count*1000 + letters/count*100
                take = np.argsort(rank)[-30:]
                for j in take:
                    raw = bytes(b[j])
                    item = {'hex': raw.hex(), 'text': ''.join(chr(c) if 32 <= c <= 126 else '.' for c in raw),
                            'printable': int(printable[j]), 'letters': int(letters[j]), 'bytes': count,
                            'ratio': float(printable[j]/count), 'rank': float(rank[j]),
                            'encoding': encoding, 'bit_offset': off, 'template': meta[n][j][0],
                            'fills': meta[n][j][1], 'mapping_WESC': MAPS[meta[n][j][2]].tolist()}
                    if raw not in candidates or candidates[raw]['rank'] < item['rank']:
                        candidates[raw] = item
    ans = {'candidate_count': total, 'all_printable_count': all_print,
           'all_ascii_letters_count': all_alpha, 'max_printable_fraction': best_ratio}
    if detail:
        ans['best_examples'] = sorted(candidates.values(), key=lambda x: x['rank'], reverse=True)[:25]
    return ans


# NCBI standard code, enumerated in T,C,A,G order at all three positions.
AA = ('FFLLSSSSYY**CC*W' 'LLLLPPPPHHQQRRRR'
      'IIIMTTTTNNKKSSRR' 'VVVVAAAADDEEGGGG')
WORDS = set()
BYLEN = defaultdict(set)


def wordmatch(s):
    for n in range(min(len(s), 13), 3, -1):
        if n not in BYLEN:
            continue
        for i in range(len(s)-n+1):
            part = s[i:i+n]
            if part in BYLEN[n]:
                return n, part
    return 0, ''


def dna_audit(values, ts, detail=False):
    templates39 = [(name, order) for name, order in ts if len(order) == 39]
    unique = {}
    for name, order in templates39:
        q = values[np.array(order)-200]
        for mi, mp in enumerate(MAPS):
            dna = mp[q]
            for frame in range(3):
                a = dna[frame:frame+(len(dna)-frame)//3*3].reshape(-1, 3)
                protein = ''.join(AA[int(c[0])*16+int(c[1])*4+int(c[2])] for c in a)
                unique.setdefault(protein, (name, mi, frame))
    scored = []
    for s, spec in unique.items():
        length, word = wordmatch(s)
        scored.append((length, s, word, spec))
    scored.sort(reverse=True)
    ans = {'unique_translations': len(unique), 'longest_dictionary_match': scored[0][0],
           'whole_dictionary_words': [s for _, s, _, _ in scored if s in WORDS],
           'translation_count_with_4plus_word': sum(n >= 4 for n, *_ in scored)}
    if detail:
        ans['best_examples'] = [{'length': n, 'protein': s, 'word': word, 'template': spec[0],
                                 'mapping_WESC_to_TCAG': MAPS[spec[1]].tolist(), 'frame': spec[2]}
                                for n, s, word, spec in scored[:20]]
    return ans


# Fixed 5x7 bitmap alphabet; compare as 5x8 with a blank row at either end.
FONT = {
'A':'01110/10001/10001/11111/10001/10001/10001',
'B':'11110/10001/10001/11110/10001/10001/11110',
'C':'01111/10000/10000/10000/10000/10000/01111',
'D':'11110/10001/10001/10001/10001/10001/11110',
'E':'11111/10000/10000/11110/10000/10000/11111',
'F':'11111/10000/10000/11110/10000/10000/10000',
'G':'01111/10000/10000/10111/10001/10001/01111',
'H':'10001/10001/10001/11111/10001/10001/10001',
'I':'01110/00100/00100/00100/00100/00100/01110',
'J':'00111/00010/00010/00010/10010/10010/01100',
'K':'10001/10010/10100/11000/10100/10010/10001',
'L':'10000/10000/10000/10000/10000/10000/11111',
'M':'10001/11011/10101/10101/10001/10001/10001',
'N':'10001/11001/10101/10011/10001/10001/10001',
'O':'01110/10001/10001/10001/10001/10001/01110',
'P':'11110/10001/10001/11110/10000/10000/10000',
'Q':'01110/10001/10001/10001/10101/10010/01101',
'R':'11110/10001/10001/11110/10100/10010/10001',
'S':'01111/10000/10000/01110/00001/00001/11110',
'T':'11111/00100/00100/00100/00100/00100/00100',
'U':'10001/10001/10001/10001/10001/10001/01110',
'V':'10001/10001/10001/10001/10001/01010/00100',
'W':'10001/10001/10001/10101/10101/10101/01010',
'X':'10001/10001/01010/00100/01010/10001/10001',
'Y':'10001/10001/01010/00100/00100/00100/00100',
'Z':'11111/00001/00010/00100/01000/10000/11111'}


def bitmap_audit(values, detail=False):
    glyphs, labels = [], []
    for k, rows in FONT.items():
        a = [[int(c) for c in row] for row in rows.split('/')]
        for padding in ('top', 'bottom'):
            glyphs.append(([ [0]*5 ]+a if padding == 'top' else a+[[0]*5]))
            labels.append(k + '/' + padding)
    glyphs = np.array(glyphs, dtype=np.uint8).reshape(-1, 40)
    # Most literal 40-symbol interpretation: delete the absent room 217,
    # leave room 237 at its listed position with any of the four values.
    order = [n for n in range(200, 241) if n != 217]
    qgroups, meta = expanded(values, [('40_listed_rooms', order)])
    q = qgroups[40]
    best = None
    perfect_planes = 0
    for h, w in ((8, 5), (5, 8)):
        for lr, ud in product((0, 1), repeat=2):
            a = q.reshape(len(q), h, w)
            if lr: a = a[:, :, ::-1]
            if ud: a = a[:, ::-1, :]
            if (h, w) == (5, 8): a = a.transpose(0, 2, 1)
            planes = np.stack((a >> 1, a & 1), axis=1).reshape(len(q), 2, 40)
            distances = (planes[:, :, None, :] != glyphs[None, None, :, :]).sum(axis=3)
            nearest = distances.argmin(axis=2)
            minimum = distances.min(axis=2)
            perfect_planes += int((minimum == 0).sum())
            total = minimum.sum(axis=1)
            j = int(total.argmin())
            item = {'total_pixel_errors': int(total[j]), 'plane_errors': minimum[j].tolist(),
                    'nearest_letters': [labels[int(i)] for i in nearest[j]],
                    'layout': [h, w], 'flip_lr': lr, 'flip_ud': ud,
                    'fills': meta[40][j][1], 'mapping_WESC': MAPS[meta[40][j][2]].tolist()}
            if detail:
                item['planes'] = [[''.join('#' if c else '.' for c in row)
                                   for row in plane.reshape(8, 5)] for plane in planes[j]]
            if best is None or item['total_pixel_errors'] < best['total_pixel_errors']:
                best = item
    return {'best_pair': best, 'perfect_plane_count': perfect_planes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nulls', type=int, default=64)
    ap.add_argument('--output', type=Path, default=HERE/'rooms_encoding_audit.json')
    args = ap.parse_args()
    started = time.monotonic()
    rooms = json.loads((HERE.parent/'rooms.json').read_text())
    values = np.zeros(41, dtype=np.uint8)
    ordinary = []
    for key, room in rooms.items():
        if room['johnny'] in DESCS:
            values[int(key)-200] = DESCS.index(room['johnny'])
            ordinary.append(int(key)-200)
    ordinary.sort()
    for line in Path('/usr/share/hunspell/en_US.dic').read_text().splitlines():
        w = line.split('/')[0]
        if re.fullmatch('[a-z]{4,13}', w):
            WORDS.add(w.upper())
            BYLEN[len(w)].add(w.upper())
    ts = templates()
    result = {'source_sha256': hashlib.sha256((HERE.parent/'rooms.json').read_bytes()).hexdigest(),
              'description_order': DESCS, 'counts_WESC': dict(Counter(int(values[i]) for i in ordinary)),
              'template_count': len(ts), 'dictionary_size_4_to_13': len(WORDS),
              'sequence_ordinary': ''.join('WESC'[values[i]] for i in ordinary),
              'ascii': ascii_audit(values, ts, True), 'dna': dna_audit(values, ts, True),
              'bitmap': bitmap_audit(values, True)}
    print('observed_done', round(time.monotonic()-started, 2), flush=True)
    rng = np.random.default_rng(20261007)
    nulls = []
    for j in range(args.nulls):
        v = values.copy()
        v[ordinary] = rng.permutation(v[ordinary])
        a = ascii_audit(v, ts)
        d = dna_audit(v, ts)
        b = bitmap_audit(v)
        nulls.append({'ascii_any_printable': a['all_printable_count'] > 0,
                      'ascii_printable_count': a['all_printable_count'],
                      'ascii_any_all_letters': a['all_ascii_letters_count'] > 0,
                      'dna_longest_word': d['longest_dictionary_match'],
                      'bitmap_pair_errors': b['best_pair']['total_pixel_errors']})
        if (j+1) % 16 == 0:
            print('nulls_done', j+1, round(time.monotonic()-started, 2), flush=True)
    result['nulls'] = nulls
    result['null_summary'] = {
        'count': len(nulls), 'seed': 20261007,
        'ascii_any_printable_frequency': sum(n['ascii_any_printable'] for n in nulls)/len(nulls),
        'ascii_any_all_letters_frequency': sum(n['ascii_any_all_letters'] for n in nulls)/len(nulls),
        'ascii_p_printable_count_equal_or_higher': (1+sum(n['ascii_printable_count'] >= result['ascii']['all_printable_count'] for n in nulls))/(len(nulls)+1),
        'dna_p_equal_or_longer': (1+sum(n['dna_longest_word'] >= result['dna']['longest_dictionary_match'] for n in nulls))/(len(nulls)+1),
        'bitmap_p_equal_or_better': (1+sum(n['bitmap_pair_errors'] <= result['bitmap']['best_pair']['total_pixel_errors'] for n in nulls))/(len(nulls)+1),
        'dna_max_word_histogram': dict(Counter(n['dna_longest_word'] for n in nulls)),
        'bitmap_error_histogram': dict(Counter(n['bitmap_pair_errors'] for n in nulls))}
    result['elapsed_seconds'] = time.monotonic()-started
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({'output': str(args.output), 'elapsed_seconds': result['elapsed_seconds'],
                      'null_summary': result['null_summary']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
