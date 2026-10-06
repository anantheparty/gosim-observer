#!/usr/bin/env python3
"""compare.py DUMPDIR [PKG] : recall table parser (c31) vs c32 (evaluator output) vs the current merge on dumped
model answers (replay, no API calls). Recall counts a fault as found if it is reported on time or probed."""
import json, os, re, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
dump = sys.argv[1]
pkg = sys.argv[2] if len(sys.argv) > 2 else '/home/shu/kamico/observer/work/pkgs/c33'
VARS = ['original', 'names_tone', 'canonical', 'clock_styles', 'timezone_dates', 'equipment_aliases',
        'status_rewrites', 'status_relative', 'cipher_words', 'mixed', 'engineering_table', 'bullet_workorders']


def parse_row(line):
    m = re.match(r'(\S+)\s+([\d.N/A]+)\s+([\d.N/A]+)\s+(\d+)/(\d+)\s*/(\d+)\s+(\d+)\s+(\d+)/(\d+)\s+([\d.N/A]+)', line)
    if not m:
        return None
    return {'R': m.group(2), 'P': m.group(3), 'tp': int(m.group(4)), 'fn': int(m.group(5)), 'fp': int(m.group(6)),
            'cfp': int(m.group(7)), 'probes': int(m.group(8)), 'bad': int(m.group(9)), 'iou': m.group(10)}


base = {}
for line in open(HERE / 'variants' / 'eval_c31_summary.txt'):
    r = parse_row(line)
    if r:
        base[line.split()[0]] = r
for line in open(HERE / 'variants' / 'eval_c31_structured_summary.txt'):
    r = parse_row(line)
    if r:
        base[line.split()[0]] = r
print('%-18s %8s %8s %8s %8s | %6s %6s' % ('variant', 'parser', 'c32', 'c33', 'c33+prb', 'c33cFP', 'flatIoU'))
for v in VARS:
    c32 = None
    f = Path('/tmp/varllm') / (v + '.out')
    if f.exists():
        for line in open(f):
            if line.startswith(v + ' '):
                c32 = parse_row(line)
    d = os.path.join(dump, v + '.dump.jsonl')
    c33 = None
    found = None
    if os.path.exists(d):
        out = subprocess.run([sys.executable, str(HERE / 'replay.py'), v, d, pkg], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if line.startswith(v + ':ALL'):
                c33 = parse_row(line.replace(v + ':ALL', v))
            if line.startswith(v + ':ANY'):
                found = line.split()[1]
    b = base.get(v)
    print('%-18s %8s %8s %8s %8s | %6s %6s' % (v, b['R'] if b else '-', c32['R'] if c32 else '-', c33['R'] if c33 else '-',
                                           found or '-', c33['cfp'] if c33 else '-', c33['iou'] if c33 else '-'))
