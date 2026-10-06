#!/usr/bin/env python3
"""anaonline.py <fetch dir> : summarise downloaded online runs (submit_tool.py fetch layout <dir>/<scenario id>/result.zip)."""
import csv, io, json, sys, zipfile, collections
from pathlib import Path

NAMES = {'30d456': 'A', '297bf8': 'B', '6fb9c6': 'C', '5dd461': 'D',
         'fdba57': 'A1', '437242': 'B1', '40503e': 'C1', '2ec2be': 'D1'}


def read(z, suffix):
    for n in z.namelist():
        if n.endswith('/' + suffix):
            return z.read(n).decode('utf-8', 'replace')
    return None


for d in sorted(Path(sys.argv[1]).iterdir()):
    rz = d / 'result.zip'
    if not rz.exists():
        continue
    name = NAMES.get(d.name[:6], d.name[:8])
    z = zipfile.ZipFile(rz)
    sr = json.loads(read(z, 'score_report.json') or '{}')
    wf = json.loads(read(z, 'workflow_result.json') or '{}')
    cm = sr.get('components', {}); ct = sr.get('counts', {})
    print(f"== {name} ({d.name[:8]}) total {sr.get('total', 0):.1f} sci {cm.get('sum_best_scores', 0):.0f} "
          f"req {cm.get('observation_request_reward')} rep {cm.get('report_settlement')} reqpen {cm.get('required_penalty')} "
          f"unif {cm.get('uniformity_penalty', 0):.1f} miss {ct.get('required_missing')} "
          f"rq {ct.get('observation_requests_completed')}/{ct.get('observation_requests_issued')} "
          f"inval {ct.get('invalidated_observations')} term {sr.get('termination', {}).get('reason')}")
    fc = wf.get('fair_clock', {})
    print(f"   clock charged {fc.get('charged_seconds')} cpu {fc.get('cpu_seconds')} wall {fc.get('run_wall_seconds')} "
          f"speed {fc.get('speed_factor')} decisions {wf.get('decision_requests')}")
    dec = list(csv.DictReader(io.StringIO(read(z, 'decisions.csv') or '')))
    obs = [r for r in dec if r['action'] == 'observe']
    if obs:
        asg = sum(int(r['assigned_count'] or 0) for r in obs); hit = sum(int(r['hit_count'] or 0) for r in obs)
        zero = sum(1 for r in obs if int(r['assigned_count'] or 0) > 0 and int(r['hit_count'] or 0) == 0)
        durs = collections.Counter(int(r['duration_seconds']) for r in obs)
        print(f"   observe {len(obs)} assigned {asg} hit {hit} ({hit / max(asg, 1):.3f}) zero-hit actions {zero} "
              f"first {obs[0]['start_utc']} last {obs[-1]['end_utc']} top durations {durs.most_common(4)}")
        acts = collections.Counter(r['action'] for r in dec)
        print(f"   actions {dict(acts)}")
    ob = list(csv.DictReader(io.StringIO(read(z, 'observations.csv') or '')))
    if ob:
        q = sorted(float(r['quality']) for r in ob)
        zq = sum(1 for x in q if x <= 0)
        print(f"   observations {len(ob)} quality p10 {q[len(q) // 10]:.3f} p50 {q[len(q) // 2]:.3f} p90 {q[9 * len(q) // 10]:.3f} "
              f"zero-quality {zq} ({zq / len(q):.2%})")
    kinds = collections.Counter(); first_t = {}
    for line in (read(z, 'messages.jsonl') or '').splitlines():
        try:
            m = json.loads(line)
        except Exception:
            continue
        for n in m.get('notices') or []:
            k = (m.get('record_type'), n.get('event_kind') or n.get('kind'), n.get('direction'))
            kinds[k] += 1
            first_t.setdefault(k, m.get('issued_at_utc'))
    if kinds:
        print('   notices', ', '.join(f"{k[0][:4]}:{k[1]}:{k[2]}={v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])[:24]))
    al = read(z, 'agent.log') or ''
    for key in ('offset_found', '"search"', 'safe_mode', 'Traceback', '"report"', '"llm"', 'terrain', '"nu"'):
        n = al.count(key)
        if n:
            print(f"   agent.log {key} x{n}")
