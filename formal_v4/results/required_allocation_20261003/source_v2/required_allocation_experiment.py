#!/usr/bin/env python3
"""Same-source complete official CPUPhase/reservation gates using public inputs."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
BASE = Path(__file__).resolve().parents[1]
FROZEN = BASE / 'runs/cold_neural_value_20261003/production_frozen'
OFFICIAL = BASE / 'upstream/gosim-observer-examples'
OUT = BASE / 'results/required_allocation_20261003'
sys.path.insert(0, str(FROZEN))
sys.path.insert(0, str(OFFICIAL))
from runner.challenge.v4_workflow import V4Workflow
from runner.challenge.v4_runner import run_scenario
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
import policy

spec = importlib.util.spec_from_file_location('research.required_allocation_calendar', BASE / 'research/required_allocation_calendar.py')
allocation = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = allocation
spec.loader.exec_module(allocation)

CONFIG = dict(favorable_scale=.85, hard_duration=1200, scarce_blocks=6, start_step=300, safety=1.12, early_cost=120.)


def manifest():
    files = [Path(__file__).resolve(), BASE / 'research/required_allocation_calendar.py'] + sorted(FROZEN.rglob('*.py'))
    return {str(p.relative_to(BASE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def run(card, mode, limit=None, label='v2'):
    policy.SpatialPlanner = (lambda initial: allocation.RequiredAllocationPlanner(initial, CONFIG)) if mode == 'allocation' else CPUPhaseSpatialPlanner
    initial = V4Workflow(OFFICIAL / 'local-cards' / card).initialize_payload(900)
    p = policy.Policy(initial)
    assert p.remote is None
    raw = OUT / label / mode / card
    raw.mkdir(parents=True, exist_ok=True)
    begin = time.perf_counter()
    calls = 0
    def decide(snapshot):
        nonlocal calls
        if limit is not None and int(snapshot.get('observe_action_index', 0)) >= limit:
            return dict(action='finish')
        action = p.decide(snapshot)
        calls += 1
        if calls % 150 == 0:
            print(json.dumps(dict(event='progress', pid=os.getpid(), card=card, mode=mode, calls=calls,
                                 observe=snapshot['observe_action_index'], now=snapshot['now_utc'], seconds=time.perf_counter() - begin)), flush=True)
        return action
    report = run_scenario(OFFICIAL / 'local-cards' / card / 'config/v4_scenario.json', lambda _: decide, raw)
    result = dict(card=card, mode=mode, pid=os.getpid(), seconds=time.perf_counter() - begin, total=report['total'],
                  components=report['components'], counts=report['counts'], termination=report['termination'],
                  policy_summary=p.summary(), phase_summary=p.planner.cpu_phase_summary, config=CONFIG, source_sha256=manifest())
    if mode == 'allocation':
        result['allocation_summary'] = p.planner.calendar.summary
        (raw / 'allocation_history.json').write_text(json.dumps(p.planner.calendar.history, indent=2))
    (raw / 'experiment_summary.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--card', choices=['L1', 'L2', 'L3', 'L4'], required=True)
    parser.add_argument('--mode', choices=['control', 'allocation'], required=True)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--label', default='v2')
    args = parser.parse_args()
    print(json.dumps(dict(event='start', pid=os.getpid(), card=args.card, mode=args.mode)), flush=True)
    run(args.card, args.mode, args.limit, args.label)
