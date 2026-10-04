"""Short real RequestCache entry checks and a public-only recorded-tail audit.

No card/scenario is loaded. Observation CSV projection discards factor, quality,
program multiplier, fiber labels and validity labels at the input boundary.
Recorded-trajectory checks replay actions as fixtures; they do not claim a new
whole-season RequestCache policy replay or a measured score gain.
"""
from __future__ import annotations
import collections
import copy
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
KIT = ROOT/'formal_v4/upstream/gosim-observer-examples'
REFERENCE = ROOT/'formal_v4/results/request_geometry_integration_20261004/seasons/control'
sys.dont_write_bytecode = True
sys.path.insert(0, str(KIT/'runner'))
from challenge.v4_workflow import V4Workflow
from challenge.v4_runner import normalize_action

spec = importlib.util.spec_from_file_location('request_terminal_guard', HERE/'terminal_report_agent.py')
guard_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard_module)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def selected_csv(path, fields):
    with path.open(newline='') as handle:
        reader = csv.reader(handle)
        header = next(reader)
        projection = [(field, header.index(field)) for field in fields]
        return [{field: row[index] for field, index in projection} for row in reader]


def reconstruct(card):
    initial_path = ROOT/f'formal_v4/results/policy_iteration_20261004/{card}_initialize_public.json'
    initial = json.loads(initial_path.read_text())
    directory = REFERENCE/card
    actions = read_jsonl(directory/'actions.jsonl')
    messages = read_jsonl(directory/'messages.jsonl')
    decisions = selected_csv(directory/'decisions.csv', ['observe_index', 'action', 'start_utc',
                              'end_utc', 'duration_seconds', 'program', 'assigned_count', 'hit_count'])
    feedback = collections.defaultdict(list)
    for row in selected_csv(directory/'observations.csv', ['observe_index', 'target_id', 'score']):
        feedback[int(row['observe_index'])].append({'target_id': row['target_id'], 'score': float(row['score'])})
    d_cursor = m_cursor = rank = reports = delivered_reports = 0
    now = initial['survey']['start_utc']
    last_result = latest_bulletin = latest_forecast = None
    public_scores = {}
    snapshots = []
    rows_seen = []
    for action in actions:
        new = []
        while m_cursor < len(messages) and messages[m_cursor]['issued_at_utc'] <= now:
            message = messages[m_cursor]
            # A result at this same UTC follows its report's round trip.
            if message['record_type'] == 'report_result' and delivered_reports >= reports:
                break
            m_cursor += 1
            new.append(copy.deepcopy(message))
            if message['record_type'] == 'report_result':
                delivered_reports += 1
            elif message['record_type'] == 'bulletin':
                latest_bulletin = message
            elif message['record_type'] == 'forecast':
                latest_forecast = message
            elif message['record_type'] == 'state_resync':
                public_scores = {r['target_id']: r['best_score'] for r in message['best_scores']}
        snapshot = {'now_utc': now, 'survey_end_utc': initial['survey']['end_utc'],
                    'observe_action_index': rank, 'running_total': round(sum(public_scores.values()), 6),
                    'latest_bulletin': copy.deepcopy(latest_bulletin),
                    'latest_forecast': copy.deepcopy(latest_forecast),
                    'active_requests': [], 'new_messages': new, 'last_result': copy.deepcopy(last_result),
                    'wallclock': {'elapsed_seconds': 0., 'remaining_seconds': 900.}}
        snapshots.append(snapshot)
        row = decisions[d_cursor]
        assert row['action'] == action['action'] and row['start_utc'] == now, (card, d_cursor, action, row)
        rows_seen.append(row)
        if action['action'] == 'observe':
            assert int(row['observe_index']) == rank
            assert int(row['duration_seconds']) == action['duration_seconds']
            last_result = {'action': 'observe', 'observe_index': rank,
                           'assigned_count': int(row['assigned_count']), 'hit_count': int(row['hit_count']),
                           'hits': feedback[rank]}
            assert len(last_result['hits']) == int(row['hit_count'])
            for hit in feedback[rank]:
                public_scores[hit['target_id']] = max(public_scores.get(hit['target_id'], 0.), hit['score'])
            rank += 1
        elif action['action'] == 'report':
            result = next(m for m in messages[m_cursor:] if m['record_type'] == 'report_result')
            assert result['issued_at_utc'] == now
            last_result = {'action': 'report', **{key: result[key] for key in ('correct', 'repaired', 'score_delta')}}
            reports += 1
        else:
            assert action['action'] == 'wait'
            last_result = {'action': 'wait'}
            if 'until_utc' in action:
                until = min(action['until_utc'], initial['survey']['end_utc'])
                while decisions[d_cursor]['end_utc'] < until:
                    assert decisions[d_cursor]['action'] == 'wait'
                    assert decisions[d_cursor+1]['start_utc'] == decisions[d_cursor]['end_utc']
                    d_cursor += 1
                row = decisions[d_cursor]
                assert row['action'] == 'wait' and row['end_utc'] == until
        now = row['end_utc']
        d_cursor += 1
    assert d_cursor == len(decisions) and now == initial['survey']['end_utc']
    assert m_cursor <= len(messages)
    metadata = {'card': card, 'actions': len(actions), 'terminal_start': snapshots[-1]['now_utc'],
                'terminal_end': now, 'terminal_kind': actions[-1]['action'],
                'last_feedback_rank': (snapshots[-1].get('last_result') or {}).get('observe_index'),
                'terminal_action_rank': snapshots[-1]['observe_action_index'],
                'includes_terminal_observation_feedback': False,
                'projected_observation_fields': ['observe_index', 'target_id', 'score'],
                'recoverable_fields': ['initialize verbatim', 'actions verbatim', 'now_utc from executed decision start',
                                      'observe rank from executed observe rows', 'last_result score/hit counts',
                                      'delivered messages with report round-trip ordering', 'latest bulletin/forecast',
                                      'running_total from rounded public score ledger and resync best_scores'],
                'unrecoverable_fields': ['original wallclock elapsed/remaining',
                                         'active_requests completed_target_ids before settlement',
                                         'any original snapshot fields outside the documented v4 runner contract'],
                'substituted_fields': {'wallclock': 'fixed 0/900 for equal-input prefix checks',
                                       'active_requests': 'empty fixture; prefix precedes first request publication'},
                'sources': {str(path): sha(path) for path in [initial_path, directory/'actions.jsonl',
                           directory/'decisions.csv', directory/'observations.csv', directory/'messages.jsonl']}}
    return initial, snapshots, actions, metadata


def entry_prefix(card, initial, snapshots, recorded):
    count = 3
    selected = snapshots[:count]
    assert all(not any(m['record_type'].startswith('observation_request') for m in s['new_messages']) for s in selected)
    messages = [V4Workflow.initialize_message(initial)]
    messages += [V4Workflow.request_message(i, {k: v for k, v in s.items() if k != 'wallclock'}, 0., 900.)
                 for i, s in enumerate(selected, 1)]
    messages.append({'protocol_version': 'participant-agent-protocol-v4', 'message_type': 'finish',
                     'payload': {'schema_version': 'v4-finish-v1', 'termination_reason': 'prefix_check',
                                 'decisions': count, 'observe_actions': count}})
    protocol = ''.join(json.dumps(m, separators=(',', ':'))+'\n' for m in messages)
    output = HERE/'public_entry'/card
    output.mkdir(parents=True, exist_ok=True)
    (output/'public_input.jsonl').write_text(protocol)
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'OPENBLAS_NUM_THREADS': '1',
           'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'PYTHONHASHSEED': '0'}
    env.pop('PYTHONPATH', None)
    variants = {}
    for name, package, command, enabled in [
        ('control', 'control_package', ['-m', 'research.agent_request_exact_cache'], None),
        ('wrapper_disabled', 'full_wrapper_package', ['wrapper.py'], '0'),
        ('wrapper_enabled', 'full_wrapper_package', ['wrapper.py'], '1')]:
        current_env = {**env}
        if enabled is not None:
            current_env['REQUEST_TERMINAL_REPORT_ENABLE'] = enabled
        started = time.perf_counter()
        run = subprocess.run([sys.executable, '-u', *command], cwd=HERE/package, env=current_env,
                             input=protocol, text=True, capture_output=True, timeout=60)
        (output/(name+'.stdout.jsonl')).write_text(run.stdout)
        (output/(name+'.stderr.jsonl')).write_text(run.stderr)
        assert run.returncode == 0 and 'Traceback' not in run.stderr, (name, run.returncode, run.stderr)
        responses = [json.loads(line) for line in run.stdout.splitlines()]
        assert len(responses) == count
        actions = [V4Workflow.action_from_response(r, i) for i, r in enumerate(responses, 1)]
        summaries = [json.loads(line) for line in run.stderr.splitlines() if line.startswith('{')]
        summary = summaries[-1]
        assert summary['request_exact_cache_class'] == 'ExactCachedRequestRemotePlanner'
        assert summary['remote_check']['transport'] == 'offline-request-exact-cache'
        assert summary['remote_calls'] == 0 and summary['decisions'] == count
        if enabled is not None:
            terminal = summary['terminal_report']
            assert terminal['enabled'] == (enabled == '1') and terminal['inserted_reports'] == 0
            assert terminal['events'] == []
        variants[name] = {'exit_code': run.returncode, 'elapsed_seconds': time.perf_counter()-started,
                          'responses': responses, 'actions': actions, 'summary': summary}
    base = variants['control']
    assert all(v['responses'] == base['responses'] for v in variants.values())
    result = {'passed': True, 'decisions_per_variant': count, 'actual_RequestCache_feedbacks': count-1,
              'same_input_response_parity': True, 'original_recorded_action_parity':
              [a == b for a, b in zip(base['actions'], recorded[:count])], 'variants': variants,
              'entire_original_trajectory_policy_parity_claimed': False}
    write_json(output/'result.json', result)
    return result


def tail_audit(card, initial, snapshots, actions):
    guard = guard_module.TerminalReportGuard(initial, enabled=True)
    replay = []
    for i, (snapshot, action) in enumerate(zip(snapshots, actions)):
        guard.ingest(snapshot)
        proposal = guard.propose(snapshot, action)
        replay.append(proposal)
        guard.sent(snapshot, proposal)
        if proposal != action:
            assert i == len(actions)-1 and proposal == {'action': 'report'}
            ack = copy.deepcopy(snapshot)
            ack['last_result'] = {'action': 'report', 'correct': False, 'repaired': False, 'score_delta': 0.}
            ack['new_messages'] = [{'record_type': 'report_result', 'issued_at_utc': ack['now_utc'],
                                    'correct': False, 'repaired': False, 'score_delta': 0.}]
            guard.ingest(ack)
            released = guard.release(ack)
            assert released == action
            replay.append(released)
            guard.sent(ack, released)
    assert guard.fired and replay[:-2] + replay[-1:] == actions
    result = {'passed': True, 'card': card, 'uses_actual_RequestCache_public_trajectory': True,
              'recorded_action_fixture_count': len(actions), 'inserted_reports': 1,
              'report_removed_actions_equal_recorded_control': True,
              'entire_original_trajectory_policy_parity_claimed': False,
              'terminal_report_outcome': 'synthetic false acknowledgement only; no actual outcome measured',
              'gate': guard.summary()['events'][0], 'summary': guard.summary()}
    (HERE/f'{card}_recorded_guard_actions.jsonl').write_text(''.join(json.dumps(a, sort_keys=True)+'\n' for a in replay))
    write_json(HERE/f'{card}_public_terminal_audit.json', result)
    return result


def main():
    results = {}
    for card in ('L1', 'L2'):
        initial, snapshots, actions, metadata = reconstruct(card)
        write_json(HERE/f'{card}_public_reconstruction.json', metadata)
        (HERE/f'{card}_public_recorded_trajectory.jsonl').write_text(''.join(json.dumps(
            {'snapshot': s, 'recorded_action': a}, sort_keys=True)+'\n' for s, a in zip(snapshots, actions)))
        results[card] = {'reconstruction': metadata, 'entry': entry_prefix(card, initial, snapshots, actions),
                         'guard_tail_audit': tail_audit(card, initial, snapshots, actions)}
    import numpy
    result = {'schema': 'request-terminal-adaptation-public-checks-v1', 'passed': True,
              'cards': results, 'platform': platform.platform(), 'python': sys.version,
              'numpy': numpy.__version__, 'seasons_launched': 0, 'ssh_calls': 0, 'gpu_calls': 0,
              'reads_weather_truth': False, 'reads_teacher_labels': False,
              'reads_raw_factor_quality_program_multiplier': False,
              'actual_score_delta_measured': False}
    write_json(HERE/'public_checks.json', result)
    print(json.dumps({'passed': True, 'same_input_entry_variants': 6, 'actual_feedbacks': 4,
                      'recorded_guard_actions': {c: results[c]['reconstruction']['actions'] for c in results},
                      'original_recorded_prefix_matches': {c: results[c]['entry']['original_recorded_action_parity'] for c in results},
                      'terminal_gates': {c: {k: results[c]['guard_tail_audit']['gate'][k] for k in
                                         ('terminal_kind', 'free_reports_remaining', 'worst_jain_harm',
                                          'conditional_correct_gain_lower')} for c in results},
                      'actual_score_delta_measured': False}))


if __name__ == '__main__':
    main()
