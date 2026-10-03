"""Offline fake-clock branch audit and historical-output budget evidence.

No official engine, hidden input, production mutation or new score evaluation.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile

import numpy as np

FORMAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FORMAL))
from pack_verified_portfolio import public_card
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
from research.spatial_candidates import SpatialPlanner

SHA = lambda raw: hashlib.sha256(raw).hexdigest()


class FakeClock:
    def __init__(self, step): self.step, self.calls = step, 0
    def __call__(self):
        value = self.calls*self.step
        self.calls += 1
        return value


def fake_clock_gate(cls, initial, env, step):
    original = time.perf_counter
    planner = cls(initial)
    clock = FakeClock(step)
    try:
        time.perf_counter = clock
        action = planner.choose({'now_utc': initial['survey']['start_utc']}, np.zeros(planner.n), np.zeros(planner.n), env, [])
    finally:
        time.perf_counter = original
    encoded = json.dumps(action, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return {'action_sha256': SHA(encoded.encode()), 'action': action,
            'clock_step_per_read': step, 'clock_reads': clock.calls,
            'base_candidate_evaluations': planner.stats.get('candidates'),
            'phase_exact_evaluations': planner.stats.get('phase_exact_evaluations'),
            'phase_candidate_count': planner.stats.get('phase_candidates')}


def source_conditions():
    found = []
    for name in ['policy.py', 'research/spatial_candidates.py', 'research/cpu_phase_candidates.py',
                 'research/request_deadline_common.py', 'research/request_remote_planner.py',
                 'research/gpu_phase_candidates.py', 'research/agent_model_gpu.py', 'research/remote_budget.py']:
        source = (FORMAL/name).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.While)): continue
            expression = ast.get_source_segment(source, node.test)
            if any(term in expression for term in ['perf_counter', 'remaining_seconds', 'remaining_seconds', 'fixed_workload', 'wall >', 'extra ', 'budget.allow', 'time_remaining']):
                found.append({'file': name, 'line': node.lineno, 'type': type(node).__name__, 'condition': expression})
    return found


def historical_run(stem, card):
    directory = FORMAL/f'results/{stem}_{card}_20261003'
    workflow = json.loads((directory/'workflow_result.json').read_text())
    actions = [json.loads(line) for line in (directory/'actions.jsonl').read_text().splitlines()]
    decisions = list(csv.DictReader((directory/'decisions.csv').open()))
    summary = None
    for line in (directory/'agent.log').read_text().splitlines():
        if line.startswith('{'):
            item = json.loads(line)
            if 'planning_seconds' in item: summary = item
    return {'card': card, 'route_archive': stem, 'total': workflow['score_report']['total'],
            'termination_reason': workflow['termination_reason'],
            'accounted_wallclock_seconds': workflow['accounted_wallclock_seconds'],
            'agent_wallclock_seconds': workflow['agent_wallclock_seconds'],
            'ignored_in_flight_response': workflow['ignored_in_flight_response'],
            'decision_requests': workflow['decision_requests'],
            'received_action_lines': len(actions), 'committed_decision_rows': len(decisions),
            'public_simulation_end_utc': decisions[-1]['end_utc'] if decisions else None,
            'finish_summary_present': summary is not None,
            'summary': summary,
            'per_decision_wallclock_present_in_actions': any('wallclock' in a for a in actions),
            'per_decision_wallclock_column_in_decisions': bool(decisions and 'wallclock' in decisions[0]),
            'output_sha256': {n: SHA((directory/n).read_bytes()) for n in ['actions.jsonl', 'decisions.csv', 'workflow_result.json', 'agent.log']}}


def main():
    dest = FORMAL/'results/search_budget_determinism_20261003'; dest.mkdir(exist_ok=True)
    with zipfile.ZipFile('/Users/kamico/Downloads/observer_phase_gpu.zip') as z:
        config = json.loads(z.read('policy_config.json'))
        phase_source_sha = SHA(z.read('research/cpu_phase_candidates.py'))
        spatial_source_sha = SHA(z.read('research/spatial_candidates.py'))
    assert phase_source_sha == SHA((FORMAL/'research/cpu_phase_candidates.py').read_bytes())
    assert spatial_source_sha == SHA((FORMAL/'research/spatial_candidates.py').read_bytes())
    gates = []
    for card in ['alpha', 'delta']:
        initial, public_hashes = public_card(card)
        env = {**config, 'quality_scale': .55, 'program_band_quality_scale': .55/.95}
        for label, cls, added in [('timed_base', SpatialPlanner, {}),
                                  ('fixed_CPU_phase', CPUPhaseSpatialPlanner, {'cpu_phase_fixed_workload': True})]:
            pair = [fake_clock_gate(cls, initial, {**env, **added}, step) for step in [0., 1.]]
            action_equal = pair[0]['action_sha256'] == pair[1]['action_sha256']
            count_equal = pair[0]['base_candidate_evaluations'] == pair[1]['base_candidate_evaluations']
            if label == 'fixed_CPU_phase':
                assert action_equal and count_equal
                assert pair[0]['phase_candidate_count'] == pair[1]['phase_candidate_count']
                assert pair[0]['phase_exact_evaluations'] == pair[1]['phase_exact_evaluations'] == 16
            else:
                assert not count_equal, 'fake-clock gate must actually trigger timed early exit'
            gates.append({'card': card, 'path': label, 'all_actions_equal': action_equal,
                          'base_candidate_count_equal': count_equal, 'public_input_hashes': public_hashes,
                          'runs': pair})
    old = json.loads((FORMAL/'results/cloud_phase_gpu_batch_20261003.json').read_text())
    new = json.loads((FORMAL/'results/cloud_request_gpu_batch_20261003.json').read_text())
    result = {'schema': 'search-budget-determinism-offline-audit-v1',
              'production_or_package_changes': False, 'new_evaluation_or_score': False,
              'fake_clock_scope': 'isolated process; fixed current public snapshot/zero ledger, time.perf_counter mocked only during choose',
              'fake_clock_gates': gates, 'source_clock_conditions': source_conditions(),
              'historical_runs': [historical_run(stem, card) for stem in ['cloud_phase_gpu', 'cloud_request_gpu'] for card in ['alpha', 'beta', 'gamma', 'delta']],
              'history_package_identity': {'phase_zip_sha256': old['submission_zip_sha256'],
                                          'request_zip_sha256': new['submission_zip_sha256'],
                                          'same_source_packages': old['submission_zip_sha256'] == new['submission_zip_sha256']},
              'source_sha256': {name: SHA((FORMAL/name).read_bytes()) for name in ['policy.py', 'research/spatial_candidates.py', 'research/cpu_phase_candidates.py', 'research/request_deadline_common.py', 'research/request_remote_planner.py', 'research/gpu_phase_candidates.py', 'research/search_budget_determinism_audit.py']}}
    (dest/'audit.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'fake_clock_gates_passed': len(gates), 'fixed_actions_same_at_different_clock_speeds': all(g['all_actions_equal'] for g in gates if g['path']=='fixed_CPU_phase'),
                      'timed_base_actions_changed': [g['card'] for g in gates if g['path']=='timed_base' and not g['all_actions_equal']],
                      'historical_runs': len(result['historical_runs']), 'same_historical_packages': result['history_package_identity']['same_source_packages']}))


if __name__ == '__main__': main()
