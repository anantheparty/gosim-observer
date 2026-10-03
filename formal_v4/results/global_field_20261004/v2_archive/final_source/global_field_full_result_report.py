"""Archive-only summary of completed official ledgers; no participant changes."""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / 'results/global_field_20261004/v2'

def read(p):
    return json.loads(p.read_text())

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def action_record(p):
    actions = [json.loads(x) for x in (p / 'actions.jsonl').read_text().splitlines()]
    with (p / 'decisions.csv').open() as f:
        decisions = list(csv.DictReader(f))
    with (p / 'observations.csv').open() as f:
        observations = list(csv.DictReader(f))
    return actions, decisions, observations

def first_fork(a, b):
    i = next(i for i, (x, y) in enumerate(zip(a[0], b[0])) if x != y)
    result = {'action_index': i, 'same_prior_actions': i}
    for name, ledger in (('control', a), ('search', b)):
        action = ledger[0][i]
        decision = ledger[1][i]
        obs_index = int(decision['observe_index'])
        best = {}
        gain = Decimal(0)
        rows = []
        for r in ledger[2]:
            oi = int(r['observe_index'])
            if oi > obs_index:
                break
            if r['valid'] != 'true':
                continue
            score = Decimal(r['score'])
            previous = best.get(r['target_id'], Decimal(0))
            delta = max(score - previous, Decimal(0))
            best[r['target_id']] = max(score, previous)
            if oi == obs_index:
                gain += delta
                rows.append(r)
        result[name] = {'action': action, 'decision': decision,
                        'rounded_csv_science_gain': str(gain), 'observations': rows}
    return result

if __name__ == '__main__':
    control_path = OUT / 'protocol/control/L1'
    search_path = OUT / 'protocol/search/L1'
    c = read(control_path / 'gate_result.json')
    s = read(search_path / 'gate_result.json')
    n = read(OUT / 'ready_native_reference/L1/gate_result.json')
    old_phase = OUT / 'ready_phase_reference/L1/actions.jsonl'
    ledgers = {name: action_record(path) for name, path in
               (('control', control_path), ('search', search_path))}
    with (BASE / 'upstream/gosim-observer-examples/local-cards/L1/public/targets.csv').open() as f:
        required = [r['target_id'] for r in csv.DictReader(f) if r['required'].lower() in ('true', '1')]
    metrics = {}
    for name, ledger in ledgers.items():
        observed = [r for r in ledger[1] if r['action'] == 'observe']
        metrics[name] = {
            'all_observe_valid': all(r['valid'] == 'true' for r in observed),
            'all_assigned_hit': all(r['assigned_count'] == r['hit_count'] for r in observed),
            'actions_sha256': sha((control_path if name == 'control' else search_path) / 'actions.jsonl'),
            'complete_actions': len(ledger[0]),
            'observe_actions': len(observed),
            'duration_60': sum(int(r['duration_seconds']) == 60 for r in observed),
            'observe_seconds': sum(int(r['duration_seconds']) for r in observed),
            'assigned_count': sum(int(r['assigned_count']) for r in observed),
            'hit_count': sum(int(r['hit_count']) for r in observed),
        }
        max_factor = {}
        for r in ledger[2]:
            if r['valid'] == 'true':
                max_factor[r['target_id']] = max(max_factor.get(r['target_id'], 0.0), float(r['factor']))
        metrics[name]['required_missing_rounded_csv'] = {
            tid: max_factor.get(tid, 0.0) for tid in required if max_factor.get(tid, 0.0) < 0.5}
        score = read((control_path if name == 'control' else search_path) / 'score_report.json')
        metrics[name]['requests'] = [{
            'request_id': q['request_id'], 'completed': q['completed'],
            'completed_count': q['completed_count'], 'minimum_completed': q['minimum_completed'],
            'uncompleted_target_ids': [tid for tid in q['target_ids'] if tid not in q['completed_target_ids']],
        } for q in score['observation_requests']]
    summary = {
        'decision': 'reject_v2_no_score_improvement',
        'full_official_season': True,
        'search_minus_control': str(Decimal(str(s['total'])) - Decimal(str(c['total']))),
        'search_minus_ready_native': str(Decimal(str(s['total'])) - Decimal(str(n['observed_score']))),
        'component_deltas': {k: str(Decimal(str(s['components'][k])) - Decimal(str(c['components'][k])))
                             for k in c['components']},
        'same_control_actions_as_ready_phase': sha(old_phase) == sha(control_path / 'actions.jsonl'),
        'metrics': metrics,
        'global_search_profile': s['participant_summary']['global'],
        'root_pool_fraction': s['participant_summary']['global']['root_pool_entries'] /
                              s['participant_summary']['global']['root_full_entries'],
        'first_real_action_fork': first_fork(ledgers['control'], ledgers['search']),
        'pid': 554406,
        'started_utc': '2026-10-03T16:45:00.744447+00:00',
        'completed_file_mtime_utc': '2026-10-03T16:55:17.871082466+00:00',
        'source_lock_sha256': sha(OUT / 'source_lock.json'),
        'cpp_sha256': sha(BASE / 'research/global_field_search_v2.cpp'),
        'no_L2_launch': 'Predeclared gate requires complete L1 score improvement; gate failed.',
        'native_reference_note': 'The historical expected-score flag is false; this comparison uses its actual complete official score and resource ledger.',
    }
    (OUT / 'full_result_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: summary[k] for k in ('decision', 'search_minus_control', 'search_minus_ready_native',
                                             'same_control_actions_as_ready_phase', 'metrics')}, indent=2))
