#!/usr/bin/env python3
"""reptime.py WORLD RUN... : per run, false/correct reports and delay (h) from each true fault start to its report."""
import csv, json, sys
from datetime import datetime, timezone
def pt(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
world = sys.argv[1]
faults = sorted(pt(e['actual_start_utc']) for e in csv.DictReader(open(f'{world}/truth/v4_events.csv')) if e['event_type'] == 'instrument_fault')
for run in sys.argv[2:]:
    reps = []
    for line in open(f'{run}/log.txt'):
        if '"report_result"' in line:
            try:
                d = json.loads(line); reps.append((pt(d['t']), bool(d['correct'])))
            except Exception:
                pass
    corr = [t for t, c in reps if c]
    delays = []
    for k, f in enumerate(faults):
        nxt = faults[k + 1] if k + 1 < len(faults) else 1e18
        c = [t for t in corr if f <= t < nxt]
        delays.append(round((c[0] - f) / 3600, 1) if c else None)
    print(f'{run:40s} false {sum(1 for _, c in reps if not c)} correct {len(corr)} delays_h {delays}')
