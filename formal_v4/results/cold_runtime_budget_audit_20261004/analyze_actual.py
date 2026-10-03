"""Only public calendars and downloaded actual run output are read."""
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent

def dt(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))

cards = {}
for card in ['alpha', 'beta', 'gamma', 'delta']:
    p = ROOT / f'formal_v4/results/cloud_request_cache_{card}_20261003'
    workflow = json.loads((p / 'workflow_result.json').read_text())
    report = json.loads((p / 'score_report.json').read_text())
    manifest = json.loads((p / 'archive_manifest.json').read_text())
    actions = [json.loads(s) for s in (p / 'actions.jsonl').read_text().splitlines()]
    decisions = list(csv.DictReader((p / 'decisions.csv').open()))
    observations = list(csv.DictReader((p / 'observations.csv').open()))
    calendar = list(csv.DictReader((ROOT / f'formal_v4/practice_cards/{card}/{card}/public/v4_night_calendar.csv').open()))
    end = dt(decisions[-1]['end_utc'])
    night_seconds = sum((dt(x['observing_end_utc']) - dt(x['observing_start_utc'])).total_seconds() for x in calendar)
    remaining_seconds = sum(max(0, (dt(x['observing_end_utc']) - max(end, dt(x['observing_start_utc']))).total_seconds()) for x in calendar)
    messages = [json.loads(s) for s in (p / 'messages.jsonl').read_text().splitlines()]
    log_records = []
    for line in (p / 'agent.log').read_text().splitlines():
        if line.startswith('{'):
            log_records.append(json.loads(line))
    finish = next((r for r in log_records if 'planning_seconds' in r), None)
    per_night = []
    for night in calendar:
        a, b = dt(night['observing_start_utc']), dt(night['observing_end_utc'])
        ds = [r for r in decisions if a <= dt(r['start_utc']) < b]
        obs = [r for r in ds if r['action'] == 'observe']
        per_night.append({'night_id': night['night_id'], 'actions_recorded': len(ds), 'observes': len(obs),
            'exposure_seconds': sum(float(r['duration_seconds']) for r in obs),
            'mean_exposure_seconds': sum(float(r['duration_seconds']) for r in obs) / max(1, len(obs)),
            'end_utc': ds[-1]['end_utc'] if ds else None})
    cards[card] = {
        'file_hashes_verified': {name: hashlib.sha256((p / name).read_bytes()).hexdigest() == val for name, val in manifest['file_sha256'].items()},
        'workflow': {k: v for k, v in workflow.items() if k != 'score_report'},
        'total': report['total'], 'components': report['components'], 'counts': report['counts'],
        'protocol_action_counts': dict(Counter(x['action'] for x in actions)),
        'decision_row_counts': dict(Counter(x['action'] for x in decisions)),
        'message_counts': dict(Counter(x['record_type'] for x in messages)),
        'nights': len(calendar), 'observing_seconds': night_seconds, 'remaining_observing_seconds': remaining_seconds,
        'last_simulated_utc': decisions[-1]['end_utc'], 'progress_fraction': 1 - remaining_seconds / night_seconds,
        'agent_seconds_per_request_mean': workflow['agent_wallclock_seconds'] / workflow['decision_requests'],
        'platform_overhead_seconds': workflow['accounted_wallclock_seconds'] - workflow['agent_wallclock_seconds'],
        'finish_summary': finish, 'per_night': per_night,
        'per_step_elapsed_present': False,
    }
(OUT / 'actual_summary.json').write_text(json.dumps(cards, indent=2))
print(json.dumps({k: {a:b for a,b in v.items() if a not in ['finish_summary','per_night','file_hashes_verified','message_counts']} for k,v in cards.items()},indent=2))
