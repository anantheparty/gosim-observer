#!/usr/bin/env python3
"""Offline scan of downloaded evaluation artifacts. Prints flags and locations, never raw credentials.

Usage: python3 scan_receipts.py work/online/sophon3_XXXX
ZIPs are streamed, not extracted. No requests, credentials, or platform calls.
"""
import argparse
import json
import re
import zipfile
from pathlib import Path

FLAG = re.compile(r'SOPHON\{[^{}\s]{1,256}\}')
KEY = re.compile(r'receipt|sophon|flag|johnny|ground.?station', re.I)
CAP = 32 * 1024 * 1024


def scan_text(name, data):
    text = data.decode('utf-8', errors='replace')
    flags = sorted(set(FLAG.findall(text)))
    locations = []
    for lineno, line in enumerate(text.splitlines(), 1):
        # Report field names only; values may include injected run credentials.
        keys = sorted(set(m for m in re.findall(r'"([^"\n]{1,120})"\s*:', line) if KEY.search(m)))
        if keys:
            locations.append({'line': lineno, 'keys': keys})
        elif re.search(r'receipt|ground.?station', line, re.I):
            locations.append({'line': lineno, 'text_marker': True})
    return {'file': name, 'bytes': len(data), 'flags': flags,
            'candidate_filename': bool(KEY.search(Path(name).name)),
            'candidate_locations': locations[:30], 'candidate_count': len(locations)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('path', type=Path)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    paths = sorted(args.path.rglob('*')) if args.path.is_dir() else [args.path]
    records = []
    for path in paths:
        if not path.is_file() or path == args.out:
            continue
        if path.suffix.lower() == '.zip':
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    name = str(path) + '!' + info.filename
                    if info.file_size > CAP:
                        records.append({'file': name, 'skipped': 'over 32 MiB'})
                    else:
                        records.append(scan_text(name, z.read(info)))
        elif path.stat().st_size <= CAP and path.suffix.lower() in ('.json', '.jsonl', '.log', '.txt', '.csv', '.md', ''):
            records.append(scan_text(str(path), path.read_bytes()))
    output = {'flags': sorted({f for r in records for f in r.get('flags', [])}), 'files': records}
    value = json.dumps(output, ensure_ascii=False, indent=2) + '\n'
    if args.out:
        args.out.write_text(value)
    print(value, end='')


if __name__ == '__main__':
    main()
