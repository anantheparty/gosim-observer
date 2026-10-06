#!/usr/bin/env python3
"""mkguider.py SRC DST RESULT_ZIP : local test world of the guider-camera cards (A1-D1 after 2026-10-06).
Copies world SRC, removes its baked instrument faults, adds the duty-log requests of an online result zip (same card
family: same site and season), adds the guider faults the log announces (event ids V4GF*, applied dynamically by the
patched engine in work/engine_g: x0.3 for an hour then x0.005 until repaired) and bakes the flat-lamp windows
(x0.005, no fault) into the weather truth."""
import csv, json, shutil, sys, zipfile
from datetime import datetime, timedelta, timezone
sys.path.insert(0, '/home/shu/kamico/observer/work/pkgs/c31')
from guider_log import GuiderLog
src, dst, zpath = sys.argv[1], sys.argv[2], sys.argv[3]
P = lambda s: datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
F = lambda d: d.strftime('%Y-%m-%dT%H:%M:%SZ')
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(src, dst)
z = zipfile.ZipFile(zpath)
g = lambda s: z.read([n for n in z.namelist() if n.endswith(s)][0]).decode('utf-8', 'ignore')
msgs = [json.loads(l) for l in g('messages.jsonl').splitlines()]
logs = [m for m in msgs if m.get('record_type') == 'observation_request' and float(m.get('completion_reward') or 0) == 0
        and len(m.get('reason') or '') > 30]
scen = json.load(open(f'{dst}/config/v4_scenario.json'))
off = float(scen['site'].get('utc_offset_hours', 0.0))
gl = GuiderLog(off)
for m in logs:
    gl.read(m['reason'], P(m['issued_at_utc']).timestamp())
# 1. undo baked faults
ev = list(csv.DictReader(open(f'{dst}/truth/v4_events.csv')))
hdr = list(ev[0].keys())
wt = list(csv.DictReader(open(f'{dst}/truth/v4_weather_truth.csv')))
wh = list(wt[0].keys())
old = [e for e in ev if e['event_type'] == 'instrument_fault']
for f in old:
    m = float(f['instrument_efficiency_multiplier'])
    a, b = P(f['actual_start_utc']), P(f['actual_end_utc'])
    for r in wt:
        if r['is_observable'] != 'true' or not r['instrument_efficiency']:
            continue
        t = P(r['timestamp_utc'])
        if a <= t < b and m > 0:
            r['instrument_efficiency'] = f"{min(1.0, float(r['instrument_efficiency']) / m):.6f}"
ev = [e for e in ev if e['event_type'] != 'instrument_fault']
# 2. guider faults: stated jobs, rain-postponed jobs on their first day, relative jobs
season_end = max(P(r['timestamp_utc']) for r in wt) + timedelta(hours=1)
times = sorted({c['t'] for c in gl.due()} | {c['t'] for c in gl.probes() if c['st'] == 'alt' and c['t'] not in [x + 86400 for x in gl.rain]})
times = [t for t in times if P(wt[0]['timestamp_utc']).timestamp() <= t < season_end.timestamp()]
for k, t in enumerate(times):
    end = times[k + 1] if k + 1 < len(times) else season_end.timestamp()
    row = {h: '' for h in hdr}
    row.update({'event_id': f'V4GF{k + 1:04d}', 'event_type': 'instrument_fault',
                'actual_start_utc': F(datetime.fromtimestamp(t, tz=timezone.utc)),
                'actual_end_utc': F(datetime.fromtimestamp(end, tz=timezone.utc)), 'scope_type': 'ALL',
                'severity': '1.000000', 'force_close': 'false', 'zero_score': 'false', 'seeing_multiplier': '1.000000',
                'transparency_multiplier': '1.000000', 'sky_quality_multiplier': '1.000000',
                'instrument_efficiency_multiplier': '0.300000'})
    ev.append(row)
with open(f'{dst}/truth/v4_events.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=hdr); w.writeheader(); w.writerows(ev)
# 3. flat-lamp windows baked into the slots (the windows sit on the 15-minute grid)
nflat = 0
for r in wt:
    if r['is_observable'] != 'true' or not r['instrument_efficiency']:
        continue
    t = P(r['timestamp_utc']).timestamp()
    if gl.in_flat(t + 1.0):
        r['instrument_efficiency'] = f"{float(r['instrument_efficiency']) * 0.005:.6f}"
        nflat += 1
with open(f'{dst}/truth/v4_weather_truth.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=wh); w.writeheader(); w.writerows(wt)
# 4. the log requests
path = f'{dst}/truth/v4_observation_requests.jsonl'
rows = [json.loads(l) for l in open(path) if l.strip()]
tmpl = rows[0]
for k, m in enumerate(logs):
    r = dict(tmpl)
    r['request_id'] = f'V4LG{k + 1:04d}'
    r['issued_at_utc'] = m['issued_at_utc']
    r['deadline_utc'] = F(P(m['issued_at_utc']) + timedelta(days=1))
    r['target_ids'] = tmpl['target_ids'][:1]
    r['minimum_completed'] = 1
    r['completion_reward'] = 0.0
    r['reason'] = m['reason']
    rows.append(r)
rows.sort(key=lambda r: r['issued_at_utc'])
with open(path, 'w') as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + '\n')
print(f'{dst}: utc{off:+g}, removed {len(old)} faults, {len(times)} guider faults, {nflat} flat slots, {len(logs)} log requests')
