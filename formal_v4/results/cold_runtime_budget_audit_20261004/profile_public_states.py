"""Short kernel comparison, reconstructed output-prefix ledgers, frozen public Q.

These are not recorded online decision times or exact reconstructed belief states.
No simulator, truth file, teacher label, network or full-season search is used.
"""
import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
import csv
import json
import math
import platform
import sys
import time
from pathlib import Path
import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
OLD = OUT / 'source_request_cache'
NATIVE = ROOT / 'formal_v4/runs/geometry_native_20261003/release'
sys.path.insert(0, str(OLD))
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
import research
research.__path__.append(str(NATIVE / 'research'))
from research.candidate_geometry_sweep import CandidateGeometryPlanner
from research.request_exact_cache import ExactRequestCacheMixin
from research.request_remote_planner import RequestRemotePlanner

class CombinedRequestNativePlanner(ExactRequestCacheMixin, RequestRemotePlanner, CandidateGeometryPlanner):
    """Same object owns REQ, terrain, cache, prediction and clipping state.

    Explicit dispatch skips CPUPhase.choose and RequestDeadline.choose, avoiding
    recursive request planning and dual phase/native refinement. Offline only.
    """
    def _choose_baseline(self, snapshot, scores, factors, env, active_requests):
        if self.distributed_transport is not None and self.distributed_transport.enabled:
            raise ValueError('this check is for disabled transport only')
        if self.tmax < self._distributed_normal_tmax:
            self.distributed_counts['forced_cpu_crops'] += 1
        started = time.perf_counter()
        try:
            return CandidateGeometryPlanner.choose(self, snapshot, scores, factors, env, active_requests)
        finally:
            spent = time.perf_counter() - started
            self.distributed_counts['cpu_baselines'] += 1
            self.distributed_counts['cpu_baseline_seconds'] += spent
            if self.distributed_budget is not None:
                self.distributed_budget.record_cpu(spent)

def initial(card):
    p = ROOT / f'formal_v4/practice_cards/{card}/{card}'
    cfg = json.loads((p / 'config/v4_scenario.json').read_text())
    fiber = json.loads((p / 'config/v4_fiber_config.json').read_text())
    score = json.loads((p / 'config/v4_score_config.json').read_text())
    targets = list(csv.reader((p / 'public/targets.csv').open()))
    nights = list(csv.DictReader((p / 'public/v4_night_calendar.csv').open()))
    side = math.isqrt(fiber['field']['n_fibers'])
    glass = math.sqrt(fiber['field']['fiber_area_deg2'])
    pitch = glass + fiber['field']['gap_deg']
    return {'site': {**cfg['site'], 'minimum_altitude_deg': cfg['minimum_altitude_deg']},
        'survey': {'start_utc': nights[0]['observing_start_utc'], 'end_utc': nights[-1]['observing_end_utc'], 'slot_seconds': 900, 'nights': nights},
        'instrument': {**fiber['field'], 'grid_side': side, 'glass_side_deg': round(glass, 6), 'pitch_deg': round(pitch, 6), 'fov_side_deg': round(side*pitch, 6), 'exposure': fiber['exposure']},
        'scoring': score, 'targets': {'columns': targets[0], 'rows': targets[1:]}, 'limits': {'global_wallclock_seconds': 900}}

rows = []
config = json.loads((OLD / 'policy_config.json').read_text())
start_all = time.perf_counter()
for card in ['alpha', 'beta', 'gamma', 'delta']:
    init = initial(card)
    cpu, native = CPUPhaseSpatialPlanner(init), CandidateGeometryPlanner(init)
    run = ROOT / f'formal_v4/results/cloud_request_cache_{card}_20261003'
    decisions = [r for r in csv.DictReader((run / 'decisions.csv').open()) if r['action'] == 'observe']
    observations = list(csv.DictReader((run / 'observations.csv').open()))
    for fraction in [0, .2, .4, .6, .8, .98]:
        ordinal = round(fraction * (len(decisions)-1))
        record = decisions[ordinal]
        scores, factors = np.zeros(cpu.n), np.zeros(cpu.n)
        # Includes already emitted feedback even if a later actual audit invalidated
        # it. The purpose is workload shape, not claiming exact policy-state replay.
        for o in observations:
            if int(o['observe_index']) >= int(record['observe_index']): break
            i = cpu.index[o['target_id']]
            scores[i] = max(scores[i], float(o['score']))
            factors[i] = max(factors[i], float(o['factor']))
        env = {**config, 'quality_scale': .55, 'program_band_quality_scale': .55/.95,
            'use_bulletin_directional_prior': False, 'target_quality_scale': np.ones(cpu.n)}
        snapshot = {'now_utc': record['start_utc'], 'wallclock': {'remaining_seconds': 900}}
        for name, planner in [('cpu_phase', cpu), ('native', native)]:
            started = time.perf_counter()
            action = planner.choose(snapshot, scores, factors, env, [])
            rows.append({'card': card, 'fraction': fraction, 'observe_ordinal': ordinal,
                'now_utc': record['start_utc'], 'kernel': name, 'elapsed_seconds': time.perf_counter()-started,
                'stats': planner.stats, 'action': action})
    if card == 'alpha':
        combined = CombinedRequestNativePlanner(init)
        action = combined.choose({'now_utc': decisions[0]['start_utc']}, np.zeros(cpu.n), np.zeros(cpu.n),
            {**env, 'request_dp_mode': 'bypass'}, [])
        assert action['action'] == 'observe'
        assert combined.distributed_counts['cpu_baselines'] == 1
        assert combined.cpu_phase_summary['choose_calls'] == 0
        assert combined.geometry_summary['calls'] == 1
        before = combined.distributed_counts['forced_cpu_crops']
        combined.tmax = 120
        cropped = combined.choose({'now_utc': decisions[0]['start_utc']}, np.zeros(cpu.n), np.zeros(cpu.n),
            {**env, 'request_dp_mode': 'bypass'}, [])
        assert cropped['duration_seconds'] <= 120
        assert combined.distributed_counts['forced_cpu_crops'] == before+1
        (OUT / 'combination_contract_check.json').write_text(json.dumps({'passed': True,
            'mro': [c.__name__ for c in type(combined).__mro__], 'distributed': combined.distributed_counts,
            'cpu_phase': combined.cpu_phase_summary, 'native': combined.geometry_summary,
            'cropped_duration': cropped['duration_seconds'], 'scope': 'empty request bypass and mutable tmax propagation; no full policy score gate'}, indent=2))

def summary(items):
    values = np.array([r['elapsed_seconds'] for r in items])
    return {'n': len(values), 'mean': float(values.mean()), 'p50': float(np.quantile(values,.5)),
        'p90': float(np.quantile(values,.9)), 'p95': float(np.quantile(values,.95)), 'max': float(values.max())}
result = {'total_profile_seconds': time.perf_counter()-start_all, 'scope': __doc__, 'rows': rows,
    'runtime': {'python': sys.version, 'numpy': np.__version__, 'system': platform.system(),
        'machine': platform.machine(), 'thread_env': 'BLAS/OMP/MKL=1 set before numpy import by profile script'},
    'overall': {k:summary([r for r in rows if r['kernel']==k]) for k in ['cpu_phase','native']},
    'early': {k:summary([r for r in rows if r['kernel']==k and r['fraction']<=.2]) for k in ['cpu_phase','native']},
    'late': {k:summary([r for r in rows if r['kernel']==k and r['fraction']>=.8]) for k in ['cpu_phase','native']}}
(OUT / 'public_state_profile.json').write_text(json.dumps(result, indent=2))
print(json.dumps({k:v for k,v in result.items() if k not in ['rows','scope']},indent=2))
