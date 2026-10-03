"""Two public REQ snapshots: owned API, local DP, geometry and failure gate.

This is a single-step integration gate, not an official or whole-card score.
The fixture pre-accrues one accelerator budget credit for each chosen snapshot.
Credentials are read separately and never written, hashed or printed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def initial_public(card):
    sources = {}

    def read(name):
        path = card / name
        if 'truth' in path.parts:
            raise ValueError('hidden input forbidden')
        sources[name] = digest(path)
        return path.read_text()

    scenario = json.loads(read('config/v4_scenario.json'))
    fiber = json.loads(read('config/v4_fiber_config.json'))
    scoring = json.loads(read('config/v4_score_config.json'))
    targets = list(csv.DictReader(read('public/targets.csv').splitlines()))
    calendar = list(csv.DictReader(read('public/v4_night_calendar.csv').splitlines()))
    columns = list(targets[0])
    rows = [[row[k] if k in ('target_id', 'target_class') else
             row[k].lower() == 'true' if k == 'required' else float(row[k])
             for k in columns] for row in targets]
    nights = [{k: row[k] for k in ('night_id', 'night_date', 'observing_start_utc', 'observing_end_utc')}
              for row in calendar]
    field = fiber['field']
    side = math.isqrt(int(field['n_fibers']))
    glass = math.sqrt(float(field['fiber_area_deg2']))
    pitch = glass + float(field['gap_deg'])
    return {'schema_version': 'v4-initialize-v1', 'task_card': scenario['task_card'],
            'site': {**scenario['site'], 'minimum_altitude_deg': float(scenario['minimum_altitude_deg'])},
            'survey': {'start_utc': nights[0]['observing_start_utc'], 'end_utc': nights[-1]['observing_end_utc'],
                       'slot_seconds': 900, 'nights': nights},
            'instrument': {**field, 'grid_side': side, 'glass_side_deg': glass,
                           'pitch_deg': pitch, 'fov_side_deg': side * pitch, 'exposure': fiber['exposure']},
            'scoring': scoring, 'targets': {'columns': columns, 'rows': rows},
            'limits': scenario.get('limits', {})}, sources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--frozen-agent', required=True)
    parser.add_argument('--card', required=True)
    parser.add_argument('--messages', required=True, help='Own emitted public message log; no truth input')
    parser.add_argument('--runner', required=True)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    for key in ('OPENAI_BASE_URL', 'OPENAI_API_KEY'):
        os.environ.pop(key, None)
    sys.path.insert(0, str(Path(args.frozen_agent).resolve()))
    sys.path.insert(0, str(Path(args.runner).resolve()))
    import numpy as np
    from research.request_remote_planner import RequestRemotePlanner
    from research.model_gpu_transport import ModelGPUTransport
    from research.agent_model_gpu import ModelRemoteBudget
    from research.terrain_version_space import TerrainVersionSpace, altaz_at
    from research.terrain_policy import temporary_weather_scale
    from research.spatial_candidates import parse_utc
    from challenge.v4_fiber_map import FiberGrid

    initial, public_sources = initial_public(Path(args.card))
    records = [json.loads(line) for line in Path(args.messages).read_text().splitlines()]
    requests = [r for r in records if r.get('record_type') == 'observation_request'][:2]
    assert len(requests) == 2
    config = json.loads((Path(args.frozen_agent) / 'policy_config.json').read_text())
    planner = RequestRemotePlanner(initial)
    grid = FiberGrid(planner.glass ** 2, planner.pitch - planner.glass, planner.nfib)
    secret = Path(args.token_file).read_text().strip()
    client = ModelGPUTransport(initial, {'base_url': 'https://elevatia.cn/gosim-observer-gpu/v1',
                              'credential': secret, 'health_timeout_seconds': 6,
                              'initialize_timeout_seconds': 25, 'timeout_seconds': 10})
    budget = ModelRemoteBudget(client, cpu_default=.26)
    saved_remote = []

    class RecordingTransport:
        def __getattr__(self, name):
            return getattr(client, name)

        def choose(self, *values):
            import copy
            result = client.choose(*values)
            saved_remote.append(copy.deepcopy(result))
            return result

    transport = RecordingTransport()
    planner.attach_transport(transport, budget)
    result = {'type': 'public-single-step-integration-gate', 'whole_card_score': None,
              'hidden_inputs_read': False, 'credential_recorded': False,
              'budget_fixture': 'credit=1 before each snapshot; not a whole-survey quota simulation',
              'public_sources': public_sources, 'messages_sha256': digest(Path(args.messages)),
              'frozen_source_sha256': {name: digest(Path(args.frozen_agent) / name) for name in (
                  'policy.py', 'research/request_deadline_common.py', 'research/request_remote_planner.py',
                  'research/model_gpu_transport.py', 'research/agent_model_gpu.py', 'policy_config.json')},
              'conditional_quality_scale': .55, 'runs': []}

    def validate(action, prediction, now):
        if action is None:
            assert not prediction
            return {'action': None, 'assigned_targets': 0}
        if action['action'] == 'wait':
            assert parse_utc(action['until_utc']) >= now and not prediction
            return {'action': 'wait', 'assigned_targets': 0}
        assert action['action'] == 'observe'
        assert planner.tmin <= action['duration_seconds'] <= planner.tmax
        assert action['program'] in ('DARK', 'BRIGHT', 'BACKUP')
        point = action['pointing']
        assert 0 <= point['alt_deg'] <= 90 and 0 <= point['az_deg'] < 360
        assigned = action['assignments']
        assert len(set(assigned.values())) == len(assigned)
        assert set(prediction) == set(assigned.values())
        for fid, tid in assigned.items():
            i = planner.index[tid]
            hit = grid.classify_target(float(planner.ra[i]), float(planner.dec[i]), now,
                                      point['alt_deg'], point['az_deg'], planner.lat, planner.lon, 0, 0)
            assert hit.region == 'glass' and hit.fiber_id == int(fid)
            assert hit.alt_deg >= planner.min_alt - 1e-9
            assert prediction[tid]['index'] == i and prediction[tid]['fiber_id'] == int(fid)
            assert 0 <= prediction[tid]['factor'] <= 1
            assert all(math.isfinite(v) for v in prediction[tid].values() if isinstance(v, (int, float)))
        night_end = next(b for a, b in planner.nights if a <= now < b)
        assert action['duration_seconds'] <= (night_end - now).total_seconds()
        return {'action': 'observe', 'assigned_targets': len(assigned),
                'official_fiber_geometry_passed': True, 'prediction_identity_passed': True,
                'duration_and_night_passed': True}

    try:
        result['health'] = client.check()
        if result['health']['remote_check'] != 'ok':
            raise RuntimeError('owned endpoint health failed')
        for request in requests:
            now = parse_utc(request['issued_at_utc'])
            published = [r for r in records if r.get('issued_at_utc') and parse_utc(r['issued_at_utc']) <= now]
            bulletin = next(r for r in reversed(published) if r['record_type'] == 'bulletin')
            forecast = next(r for r in reversed(published) if r['record_type'] == 'forecast')
            initial_notices = [n for r in published if r.get('initial') for n in r.get('notices', [])
                               if n.get('event_kind') == 'terrain_obstruction']
            planner.terrain_model = TerrainVersionSpace.reference_prior(
                [n['direction'] for n in initial_notices], planner.lat, planner.lon)
            planner.terrain_empirical_blocks = []
            active = {**request, 'completed_target_ids': []}
            snapshot = {'now_utc': now.isoformat(), 'latest_bulletin': bulletin,
                        'latest_forecast': forecast, 'new_messages': [request], 'active_requests': [active],
                        'wallclock': {'remaining_seconds': 900}}
            alt, az = altaz_at(now.timestamp(), planner.ra, planner.dec, planner.lat, planner.lon)
            target_scale = planner.terrain_model.expected_clear_fraction(alt, az)
            target_scale *= temporary_weather_scale(bulletin.get('notices', []), now, alt, az)
            env = {**config, 'quality_scale': .55, 'program_band_quality_scale': .55 / .95,
                   'target_quality_scale': target_scale, 'use_bulletin_directional_prior': False,
                   'pointing_offset_alt_deg': 0., 'pointing_offset_az_deg': 0.}
            # This narrow integration fixture does not wait through earlier CPU
            # actions to accrue credit; production keeps the ordinary credit rule.
            budget.credit = 1.
            before = client.calls
            started = time.perf_counter()
            action = planner.choose(snapshot, np.zeros(planner.n), np.zeros(planner.n), env, [active])
            spent = time.perf_counter() - started
            assert client.calls == before + 1, 'fixture did not produce exactly one real GPU baseline'
            baseline = saved_remote[-1]
            baseline_gate = validate(baseline['action'], baseline.get('prediction', {}), now)
            final_gate = validate(action, planner.last_prediction, now)
            result['runs'].append({'request_id': request['request_id'], 'snapshot': snapshot,
                   'seconds': spent, 'real_gpu_choose_calls': client.calls - before,
                   'gpu_baseline_gate': baseline_gate, 'final_gate': final_gate,
                   'baseline_action': baseline['action'], 'final_action': action,
                   'backend_stats': baseline.get('stats', {}),
                   'request_dp': planner.request_dp_summary(), 'distributed': planner.distributed_summary()})
        # A local fault injection exercises the same exception boundary without
        # any third network choose or hidden data.
        class FailedTransport:
            enabled = True
            session = 'local-fault-fixture'
            config = {}
            last_initialization_seconds = last_decision_seconds = 0.
            last_failure_kind = 'decision'
            def choose(self, *unused):
                raise TimeoutError('local fault fixture')
        failed = FailedTransport()
        failed_budget = ModelRemoteBudget(failed, cpu_default=.26)
        failed_budget.credit = 1.
        planner.attach_transport(failed, failed_budget)
        before_cpu = planner.distributed_counts['cpu_baselines']
        before_failure = planner.distributed_counts['transport_failures']
        action = planner.choose(snapshot, np.zeros(planner.n), np.zeros(planner.n), env, [active])
        result['failure_gate'] = validate(action, planner.last_prediction, now)
        assert planner.distributed_counts['cpu_baselines'] > before_cpu
        assert planner.distributed_counts['transport_failures'] == before_failure + 1
        assert client.calls <= 2
        result['failure_fallback_passed'] = True
        result['real_gpu_choose_total'] = client.calls
    except Exception as exc:
        result['error_type'] = type(exc).__name__
        result['passed'] = False
    finally:
        client.close()
        result['close_invoked'] = True
        result['session_closed'] = client.session is None and client.connection is None
    result.setdefault('passed', True)
    result['helper_sha256'] = digest(Path(__file__))
    encoded = json.dumps(result, indent=2)
    assert secret not in encoded
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(encoded)
    print(json.dumps({'passed': result['passed'], 'error_type': result.get('error_type'),
                      'real_gpu_choose_total': result.get('real_gpu_choose_total', client.calls),
                      'close_invoked': result['close_invoked'], 'out': args.out}), flush=True)


if __name__ == '__main__':
    main()
