"""Full public request-window equality gates for research memoization only."""
from __future__ import annotations

import cProfile
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import pstats
import sys
import time

import numpy as np

FORMAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FORMAL))
from pack_verified_portfolio import public_card
from research.request_deadline_cpu import RequestCPUDeadlinePlanner
from research.request_exact_cache import ExactCachedRequestCPUPlanner
from research.request_mask_dp import solve_request_columns
from research.spatial_candidates import parse_utc
from research.terrain_version_space import TerrainVersionSpace


def clean(value):
    if isinstance(value, np.ndarray): return value.tolist()
    if isinstance(value, np.generic): return value.item()
    if hasattr(value, 'isoformat'): return value.isoformat()
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k != 'build_seconds'}
    if isinstance(value, (tuple, list)): return [clean(v) for v in value]
    return value


def canonical(info):
    converted = dict(info)
    converted['columns'] = [asdict(c) for c in info['columns']]
    return json.dumps(clean(converted), sort_keys=True, separators=(',', ':'), allow_nan=False)


def setup(card, request_index, published):
    payload, hashes = public_card(card)
    history = FORMAL/f'results/cloud_request_gpu_{card}_20261003'
    req = dict(json.loads((history/'score_report.json').read_text())['observation_requests'][request_index])
    now = parse_utc(req['issued_at_utc'])
    req['completed_target_ids'] = []
    req['completed_count'] = 0
    decisions = {r['observe_index']: r for r in csv.DictReader((history/'decisions.csv').open()) if r['action'] == 'observe'}
    scores, factors = {}, {}
    for row in csv.DictReader((history/'observations.csv').open()):
        if row['valid'] == 'true' and parse_utc(decisions[row['observe_index']]['end_utc']) <= now:
            tid = row['target_id']
            scores[tid] = max(scores.get(tid, 0), float(row['score']))
            factors[tid] = max(factors.get(tid, 0), float(row['factor']))
    messages = [json.loads(line) for line in (history/'messages.jsonl').read_text().splitlines()]
    messages = [r for r in messages if r.get('issued_at_utc') and parse_utc(r['issued_at_utc']) <= now]
    bulletin = next((r for r in reversed(messages) if r['record_type'] == 'bulletin'), {})
    forecast = next((r for r in reversed(messages) if r['record_type'] == 'forecast'), {})
    directions = [n['direction'] for r in messages for n in r.get('notices', []) if n.get('event_kind') == 'terrain_obstruction']
    env = {'quality_scale': .55, 'program_band_quality_scale': .55/.95, 'duration_safety': 1.1,
           'request_dp_price_anchors': 2, 'request_dp_step_seconds': 900}
    if published: env['request_dp_future_field_mode'] = 'published'
    snapshot = {'now_utc': now.isoformat(), 'latest_bulletin': bulletin, 'latest_forecast': forecast}
    return payload, hashes, req, now, scores, factors, directions, env, snapshot


def check_case(card, index, published, profile=False, changed_same_time=False):
    payload, hashes, req, now, scores, factors, directions, env, snapshot = setup(card, index, published)
    results, times, actions, plans, planners = [], [], [], [], []
    profile_rows = []
    for cls in [RequestCPUDeadlinePlanner, ExactCachedRequestCPUPlanner]:
        p = cls(payload)
        p.terrain_model = TerrainVersionSpace.reference_prior(directions, p.lat, p.lon)
        s, f = p._array(scores), p._array(factors)
        profiler = cProfile.Profile() if profile and cls == RequestCPUDeadlinePlanner else None
        if profiler: profiler.enable()
        started = time.perf_counter()
        info = p._build_pool(req, now, s, f, env, snapshot)
        times.append(time.perf_counter()-started)
        if profiler:
            profiler.disable()
            stats = pstats.Stats(profiler)
            profile_rows = [{'file': key[0], 'line': key[1], 'function': key[2],
                             'primitive_calls': vals[0], 'total_calls': vals[1],
                             'self_seconds': vals[2], 'cumulative_seconds': vals[3]}
                            for key, vals in sorted(stats.stats.items(), key=lambda item: -item[1][3])[:25]]
        results.append(canonical(info))
        plan = solve_request_columns(info['columns'], target_count=len(info['idx']), quorum=req['minimum_completed'], now=now.timestamp(), deadline=info['deadline'].timestamp())
        plans.append(clean(asdict(plan)))
        selected_actions = []
        for selected in plan.chosen_indices:
            col = info['columns'][selected]
            moment = __import__('datetime').datetime.fromtimestamp(col.start, __import__('datetime').timezone.utc)
            p._active_future_field = p._future_field(snapshot, env)
            selected_actions.append(p._request_action(col.tag, moment, info, s, f, env, 0))
            p._active_future_field = None
        actions.append(selected_actions)
        planners.append(p)
    rebuild = None
    if changed_same_time:
        changed_env = {**env, 'quality_scale': .79, 'program_band_quality_scale': .79/.95}
        rebuilt = []
        for p in planners:
            # A new public snapshot at the same timestamp, changed best-only
            # feedback, and a different frozen terrain posterior/clear map.
            p.terrain_model = TerrainVersionSpace.reference_prior([], p.lat, p.lon)
            s, f = p._array(scores)+.07, np.maximum(p._array(factors), .21)
            altered = p._build_pool(req, now, s, f, changed_env, snapshot)
            rebuilt.append(canonical(altered))
        assert rebuilt[0] == rebuilt[1], 'same-time changed-state rebuild differs'
        assert rebuilt[0] != results[0], 'changed-state gate was vacuous'
        rebuild = {'E_scale_before': env['quality_scale'], 'E_scale_after': changed_env['quality_scale'],
                   'new_terrain_families': [], 'old_terrain_families': directions,
                   'ledger_scores_added': .07, 'ledger_factor_floor': .21,
                   'all_columns_bitwise_equal': True, 'columns_changed_from_initial_build': True,
                   'pool_sha256': hashlib.sha256(rebuilt[0].encode()).hexdigest()}
    assert results[0] == results[1], 'column pool differs (includes every chosen target/prediction/cost/tie/order)'
    assert plans[0] == plans[1], 'DP result differs'
    assert actions[0] == actions[1], 'selected executable actions differ'
    # Every duration is still sampled on the original cuts and summed in order.
    assert not planners[1]._exact_midpoints and planners[1]._exact_midpoint_bytes == 0
    return {'card': card, 'request_id': req['request_id'], 'published': published,
            'public_input_hashes': hashes, 'target_count': len(payload['targets']['rows']),
            'columns': len(info['columns']), 'all_columns_bitwise_equal': True,
            'pool_sha256': hashlib.sha256(results[0].encode()).hexdigest(),
            'DP_bitwise_equal': True, 'selected_actions_bitwise_equal': True,
            'selected_actions': len(actions[0]), 'baseline_seconds': times[0],
            'cached_seconds': times[1], 'speedup': times[0]/times[1],
            'baseline_profiled': profile, 'cache_stats': planners[1].exact_cache_stats,
            'baseline_profile': profile_rows, 'changed_same_time_rebuild': rebuild}


if __name__ == '__main__':
    dest = FORMAL/'results/request_exact_cache_20261003'
    dest.mkdir(exist_ok=True)
    output = {'schema': 'request-exact-cache-full-public-window-gates-v1', 'cases': [],
              'production_files_changed': False, 'new_online_score_claimed': False}
    for card, index, published, profile, changed in [('delta', 0, False, False, False), ('delta', 0, True, False, False), ('gamma', 0, True, True, False), ('delta', 1, True, False, True)]:
        case = check_case(card, index, published, profile, changed)
        output['cases'].append(case)
        (dest/'checks.json').write_text(json.dumps(output, indent=2)+'\n')
        print(json.dumps({k: v for k, v in case.items() if k not in ('public_input_hashes', 'baseline_profile')}, ensure_ascii=False), flush=True)
