"""Review actual strongest RequestCache pair; no participant or truth execution."""
import csv
import hashlib
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('terminal_audit', ROOT / 'formal_v4/results/cold_policy_breakthrough_20261004/run_protocol.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
read = lambda p: json.loads(p.read_text())
lines = lambda p: [json.loads(s) for s in p.read_text().splitlines()]
folders = {v: BASE / 'seasons' / v / 'L3' for v in ('control', 'terminal')}
gates = {}
for v, folder in folders.items():
    receipt = read(folder / 'gate_result.json')
    gates[v + '_protocol_passed'] = receipt['protocol_passed']
    gates[v + '_all_output_hashes_match'] = all(hashlib.sha256((folder / n).read_bytes()).hexdigest() == h for n, h in receipt['outputs_sha256'].items())
    gates[v + '_frozen_actor_sources'] = receipt['source_sha256'] == read(BASE / 'source_lock.json')['control' if v == 'control' else 'full_wrapper']
control, intervention = folders['control'], folders['terminal']
scores = {v: read(f / 'score_report.json') for v, f in folders.items()}
records = []
for line in (intervention / 'agent.log').read_text().splitlines():
    try:
        record = json.loads(line)
    except ValueError:
        continue
    if isinstance(record, dict): records.append(record)
summary = [r for r in records if 'terminal_report' in r][-1]
terminal = summary['terminal_report']
parity, detail = audit.action_parity(lines(intervention / 'actions.jsonl'), lines(control / 'actions.jsonl'), 1, terminal)
gates.update(parity)
gates['terminal_events_match_summary'] = [r for r in records if str(r.get('event', '')).startswith('terminal_report_')] == terminal['events']
frozen = detail['frozen']
old_messages = lines(control / 'messages.jsonl')
new_messages = lines(intervention / 'messages.jsonl')
inserted = [m for m in new_messages if m.get('record_type') == 'report_result' and m.get('issued_at_utc') == frozen['now_utc']]
gates['one_official_report_result'] = len(inserted) == 1
gates['other_public_messages_unchanged'] = [m for m in new_messages if m not in inserted] == old_messages
gates['old_invalidation_plan_unchanged'] = scores['control']['invalidations'] == scores['terminal']['invalidations']
rows = {v: list(csv.DictReader((f / 'decisions.csv').open())) for v, f in folders.items()}
position = next(i for i, row in enumerate(rows['terminal']) if row['action'] == 'report' and row['start_utc'] == frozen['now_utc'])
gates['report_precedes_final_committed_decision'] = position == len(rows['control']) - 1
filtered = rows['terminal'][:position] + rows['terminal'][position + 1:]
normalize = lambda seq: [{k: value for k, value in row.items() if k != 'decision_id'} for row in seq]
gates['all_original_decision_fields_unchanged'] = normalize(filtered) == normalize(rows['control'])
report_row = rows['terminal'][position]
gates['report_does_not_advance_time'] = report_row['start_utc'] == report_row['end_utc'] == frozen['now_utc'] and report_row['duration_seconds'] == '0'
delta = {k: float(Decimal(str(value)) - Decimal(str(scores['control']['components'][k]))) for k, value in scores['terminal']['components'].items()}
total_delta = float(Decimal(str(scores['terminal']['total'])) - Decimal(str(scores['control']['total'])))
gates['science_required_request_not_reduced'] = all(delta[k] >= 0 for k in ['sum_best_scores', 'required_penalty', 'observation_request_reward'])
gates['observations_and_observe_rank_unchanged'] = all(scores['control']['counts'][k] == scores['terminal']['counts'][k] for k in ['observations', 'observe_actions', 'targets_observed', 'invalidated_observations'])
gates['actual_gain_exceeds_public_bound'] = total_delta + 2e-6 >= frozen['conditional_correct_gain_lower']
gates['official_report_matches_guard'] = inserted[0]['correct'] == terminal['terminal_correct'] and inserted[0]['score_delta'] == delta['report_settlement'] == terminal['terminal_score_delta']
flow = read(intervention / 'workflow_result.json')
gates['decision_requests_accounted'] = flow['decision_requests'] == summary['decisions'] + terminal['inserted_reports']
result = {'schema': 'root-actual-request-terminal-pair-review-v1', 'passed': all(gates.values()), 'gates': gates, 'card': 'L3', 'control_total': scores['control']['total'], 'terminal_total': scores['terminal']['total'], 'actual_full_season_delta': total_delta, 'component_delta': delta, 'action_intervention_audit': detail, 'formal_online_gain': None, 'source_lock_sha256': hashlib.sha256((BASE / 'source_lock.json').read_bytes()).hexdigest(), 'local_run_limits': {'cpu': 2, 'memory_gib': 2, 'wallclock_seconds': 900}}
(BASE / 'ROOT_ACTUAL_RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k: result[k] for k in ['passed', 'control_total', 'terminal_total', 'actual_full_season_delta', 'component_delta']}))
print(json.dumps({'failed_gates': [k for k, value in gates.items() if not value]}))
