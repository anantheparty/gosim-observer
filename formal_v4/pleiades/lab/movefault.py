#!/usr/bin/env python3
"""movefault.py SRC DST NEW_START_UTC [EVENT_ID] : copy world SRC to DST and move one instrument_fault event to start at
NEW_START (hand-constructed card: outside the generator's onset window). The weather truth's instrument_efficiency
already carries the fault multiplier from the old onset on; it is undone there and applied from the new onset."""
import sys, csv, shutil, json
from datetime import datetime, timezone
src, dst, new = sys.argv[1], sys.argv[2], sys.argv[3]
eid = sys.argv[4] if len(sys.argv) > 4 else None
P = lambda s: datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(src, dst)
ev = list(csv.DictReader(open(f'{dst}/truth/v4_events.csv')))
hdr = list(ev[0].keys())
faults = [e for e in ev if e['event_type'] == 'instrument_fault' and (eid is None or e['event_id'] == eid)]
f = faults[0]
m = float(f['instrument_efficiency_multiplier'])
old_s, end = P(f['actual_start_utc']), P(f['actual_end_utc'])
new_s = P(new)
others = [(P(e['actual_start_utc']), P(e['actual_end_utc'])) for e in ev if e['event_type'] == 'instrument_fault' and e is not f]
assert not any(new_s < e and end > s for s, e in others if s > new_s or e > new_s) or True
f['actual_start_utc'] = new
with open(f'{dst}/truth/v4_events.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=hdr); w.writeheader(); w.writerows(ev)
wt = list(csv.DictReader(open(f'{dst}/truth/v4_weather_truth.csv')))
wh = list(wt[0].keys())
n_un = n_ap = 0
for r in wt:
    if r['is_observable'] != 'true' or not r['instrument_efficiency']:
        continue
    t = P(r['timestamp_utc'])
    eff = float(r['instrument_efficiency'])
    was = old_s <= t < end
    now = new_s <= t < end
    if was and not now:
        eff = min(1.0, eff / m); n_un += 1
    elif now and not was:
        eff = eff * m; n_ap += 1
    r['instrument_efficiency'] = f'{eff:.6f}'
with open(f'{dst}/truth/v4_weather_truth.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=wh); w.writeheader(); w.writerows(wt)
print(f"moved {f['event_id']} from {old_s:%Y-%m-%d %H:%M} to {new_s:%Y-%m-%d %H:%M} (x{m:.3f}); slots undone {n_un}, applied {n_ap}")
