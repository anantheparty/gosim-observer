#!/usr/bin/env python3
"""addlog.py SRC DST SPEC.json : copy world SRC to DST and add log-carrying observation requests (handover-log
test cards like A1-D1). SPEC: [{"issued": "YYYY-MM-DDTHH:MM:SSZ", "text": "line1\\nline2 ..."}, ...]. Each becomes a
zero-reward request on one target of the first existing request, so it changes nothing but the messages."""
import json, shutil, sys
from datetime import datetime, timedelta, timezone
src, dst, spec = sys.argv[1], sys.argv[2], json.load(open(sys.argv[3]))
P = lambda s: datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
F = lambda d: d.strftime('%Y-%m-%dT%H:%M:%SZ')
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(src, dst)
path = f'{dst}/truth/v4_observation_requests.jsonl'
rows = [json.loads(l) for l in open(path) if l.strip()]
tmpl = rows[0]
for k, s in enumerate(spec):
    r = dict(tmpl)
    r['request_id'] = f'V4LG{k + 1:04d}'
    r['issued_at_utc'] = s['issued']
    r['deadline_utc'] = F(P(s['issued']) + timedelta(days=1))
    r['target_ids'] = tmpl['target_ids'][:1]
    r['minimum_completed'] = 1
    r['completion_reward'] = 0.0
    r['reason'] = s['text']
    rows.append(r)
rows.sort(key=lambda r: r['issued_at_utc'])
with open(path, 'w') as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + '\n')
print(f'{dst}: {len(spec)} log requests added ({len(rows)} requests)')
