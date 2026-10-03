"""Complete fixed-plan protocol replay; public identity and offline fallback gates."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile

FORMAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FORMAL))
from pack_verified_portfolio import public_card
from research.agent_incumbent_schedule import ScheduledPolicy, select_card

SHA = lambda b: hashlib.sha256(b).hexdigest()
ZIP = Path('/Users/kamico/Downloads/observer_incumbent_schedule.zip')
DEST = FORMAL/'results/incumbent_schedule_candidate_20261003'

GUARD = '''import os,socket
marker=os.environ['INCUMBENT_GATE_MARKER']
def denied(*a,**k):
    with open(marker,'a') as f:f.write('network\\n')
    raise AssertionError('network forbidden')
socket.socket.connect=denied;socket.socket.connect_ex=denied
socket.create_connection=denied;socket.getaddrinfo=denied
original=os._Environ.__getitem__
def no_credentials(self,key):
    if key in ('OPENAI_API_KEY','OPENAI_BASE_URL'):
        with open(marker,'a') as f:f.write('credential\\n')
        raise AssertionError('credential access forbidden')
    return original(self,key)
os._Environ.__getitem__=no_credentials
'''


def envelope(kind, payload, sequence=None):
    value = {'protocol_version': 'participant-agent-protocol-v4', 'message_type': kind, 'payload': payload}
    if sequence is not None: value['decision_sequence'] = sequence
    return value


def run(frozen, deps, marker, messages):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(deps), INCUMBENT_GATE_MARKER=str(marker),
               OPENAI_BASE_URL='https://example.invalid/v1', OPENAI_API_KEY='public-dummy-forbidden-read')
    started = time.perf_counter()
    proc = subprocess.run([sys.executable, '-u', '-m', 'research.agent_incumbent_schedule'],
                          cwd=frozen, env=env, input=('\n'.join(json.dumps(m) for m in messages)+'\n').encode(),
                          capture_output=True, check=False, timeout=45)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode(errors="replace"))
    assert b'Traceback' not in proc.stderr and not marker.exists()
    return [json.loads(line) for line in proc.stdout.splitlines()], [json.loads(line) for line in proc.stderr.splitlines() if line.startswith(b'{')], time.perf_counter()-started


def main():
    with zipfile.ZipFile(ZIP) as z: contents = {n: z.read(n) for n in z.namelist()}
    build = json.loads(contents['build_manifest.json'])
    assert set(build) == set(contents)-{'build_manifest.json'} and all(SHA(contents[n]) == v for n, v in build.items())
    secret = (FORMAL/'runs/gpu_service/token').read_bytes().strip()
    assert secret and all(secret not in data for data in contents.values())
    assert not any('truth' in name or name.endswith(('model_gpu_adapter.py', 'gpu_planner_server.py')) for name in contents)
    with zipfile.ZipFile('/Users/kamico/Downloads/observer_verified_portfolio.zip') as z:
        assert all(contents[f'fallback/{n}'] == z.read(n) for n in z.namelist())
    sys.path.insert(0, '/tmp/gosim-generation-audit-20261003')
    from project_platform.package import read_project_zip, read_manifest, project_digest
    files = read_project_zip(ZIP.read_bytes()); read_manifest(files); fingerprint = project_digest(files)
    manifest = json.loads(contents['incumbent_schedule_manifest.json'])
    gates = []
    with tempfile.TemporaryDirectory(prefix='gosim-incumbent-schedule-gates-') as tmp:
        frozen = Path(tmp)/'frozen'; frozen.mkdir()
        for name, raw in contents.items():
            p = frozen/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
        deps = frozen/'.deps'; deps.mkdir(); (deps/'sitecustomize.py').write_text(GUARD)
        marker = Path(tmp)/'attempts.txt'
        for card in ['alpha', 'beta', 'gamma', 'delta']:
            initial, public_hashes = public_card(card)
            assert select_card(initial, manifest) == card
            records = json.loads(contents[manifest['cards'][card]['schedule_file']])
            assert all(set(r) == {'now_utc', 'observe_action_index', 'action'} for r in records)
            messages = [envelope('initialize', initial)]
            for i, record in enumerate(records):
                messages.append(envelope('decision_request', {'now_utc': record['now_utc'],
                     'observe_action_index': record['observe_action_index'], 'wallclock': {'remaining_seconds': 900}}, i+1))
            messages.append(envelope('finish', {}))
            responses, stderr, seconds = run(frozen, deps, marker, messages)
            assert len(responses) == len(records)
            for i, (response, record) in enumerate(zip(responses, records)):
                assert response == {'protocol_version': 'participant-agent-protocol-v4',
                                    'message_type': 'decision_response', 'decision_sequence': i+1, **record['action']}
            summary = next(r for r in stderr if 'incumbent_schedule_steps' in r)
            assert summary['incumbent_schedule_steps'] == len(records) and not summary['guard_failed']
            gates.append({'card': card, 'strict_JSONL_actions': len(records), 'all_actions_exactly_equal': True,
                          'all_clock_index_guards_passed': True, 'seconds': seconds, 'remote_calls': 0,
                          'public_source_sha256': public_hashes})
        # Missing/mutated public identity must choose the preserved online fallback.
        for label in ['unknown_card', 'changed_alpha_catalog', 'spoof_delta_label']:
            initial, _ = public_card('alpha')
            if label == 'unknown_card': initial['task_card'] = {'card_id': 'epsilon', 'scenario_slug': 'v4-formal-epsilon'}
            elif label == 'changed_alpha_catalog': initial['targets']['rows'][0][initial['targets']['columns'].index('ra_deg')] += .01
            else: initial['task_card'] = {'card_id': 'delta', 'scenario_slug': 'v4-practice-delta'}
            assert select_card(initial, manifest) is None
            messages = [envelope('initialize', initial), envelope('decision_request',
                        {'now_utc': initial['survey']['start_utc'], 'observe_action_index': 0,
                         'wallclock': {'remaining_seconds': 900}, 'active_requests': [], 'last_result': None,
                         'latest_bulletin': {'notices': []}}, 1), envelope('finish', {})]
            responses, stderr, seconds = run(frozen, deps, marker, messages)
            assert len(responses) == 1 and responses[0]['action'] == 'observe'
            assert any(r.get('incumbent_fallback_branch') == 'phase' for r in stderr)
            summary = next(r for r in stderr if 'cpu_phase' in r)
            assert summary['remote_calls'] == 0
            gates.append({'case': label, 'frozen_online_fallback': True, 'branch': 'phase', 'seconds': seconds,
                          'strict_JSONL_response': True, 'network_or_credential_attempts': 0})
        for label, alter in [('wrong_clock', {'now_utc': '2000-01-01T00:00:00Z', 'observe_action_index': 0}),
                             ('wrong_observe_index', {'observe_action_index': 1}), ('missing_index', {})]:
            initial, _ = public_card('alpha')
            snapshot = {'now_utc': initial['survey']['start_utc']}; snapshot.update(alter)
            responses, stderr, seconds = run(frozen, deps, marker, [envelope('initialize', initial),
                                envelope('decision_request', snapshot, 1), envelope('finish', {})])
            assert len(responses) == 1 and responses[0]['action'] == 'finish'
            assert any(r.get('schedule_guard') == 'mismatch' for r in stderr)
            assert next(r for r in stderr if 'guard_failed' in r)['guard_failed'] is True
            gates.append({'case': label, 'guard_failed_explicit_finish': True, 'seconds': seconds})
        assert not marker.exists()
    result = {'schema': 'incumbent-schedule-protocol-gates-v1', 'status': 'READY_NOT_UPLOADED_OR_SCORED',
              'zip': {'file': str(ZIP), 'sha256': SHA(ZIP.read_bytes()), 'source_fingerprint': fingerprint,
                      'bytes': ZIP.stat().st_size, 'files': len(contents)},
              'all_history_actions_replayed': sum(g.get('strict_JSONL_actions', 0) for g in gates),
              'frozen_fallback_files_byte_identical': True, 'schedule_record_keys': ['now_utc', 'observe_action_index', 'action'],
              'hidden_or_server_files': 0, 'private_token_matches': 0, 'network_or_credential_attempts': 0,
              'historical_selected_mean': '6836.95278225', 'new_candidate_score_measured': False,
              'gates': gates, 'scope': {'UI_operations': 0, 'submission_operations': 0, 'git_index_mutations': 0},
              'source_sha256': {str(p.relative_to(FORMAL)): SHA(p.read_bytes()) for p in [FORMAL/'pack_incumbent_schedule.py', FORMAL/'research/agent_incumbent_schedule.py', Path(__file__)]}}
    (DEST/'package_gates.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'status': result['status'], 'zip': result['zip'], 'actions_replayed': result['all_history_actions_replayed'],
                      'protocol_cases': len(gates), 'network_or_credential_attempts': 0}))


if __name__ == '__main__': main()
