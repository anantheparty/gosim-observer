"""Independent, initial-state stochastic policy rollouts on generated three-night worlds.

Only generated prior worlds enter the chooser. The evaluation world is owned by
V4Workflow and communicates with the actor through participant-visible messages.
Future actions in every rollout are chosen by the unchanged frozen baseline B.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, os, resource, sys, time
from pathlib import Path

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'official'))
sys.path.insert(0, str(ROOT / 'baseline_package'))
import numpy as np
from challenge.v4_workflow import V4Workflow
from challenge import v4_bundle, v4_observation_requests
from sparse_exact import install
install()
import wrapper
from research.geometry import parse_utc, local_sidereal_deg
from research.spatial_candidates import PROGRAMS

BASE = wrapper.wrapped
SPEC = dict(catalog_seed=20261004731, prior_seeds=[77101, 77102, 77103],
            evaluation_seeds=[89101, 89102, 89103, 89104], candidates=3,
            horizon_nights=3, selector_invocations_per_world=1,
            first_state='initial public state, no observed scores',
            wait_seconds=900, wallclock_seconds=120,
            no_tuning_or_expansion=True)


def dump(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(value).hexdigest()


def canonical(snapshot):
    return {k: v for k, v in snapshot.items() if k not in ('wallclock', 'schema_version')}


def first_public(root):
    flow = V4Workflow(root)
    frame = {}
    def decide(message, deadline):
        frame.update(copy.deepcopy(message['payload']))
        return dict(protocol_version='participant-agent-protocol-v4',
                    message_type='decision_response', decision_sequence=message['decision_sequence'],
                    action='finish')
    flow.run(decide, ROOT/'public_probe'/root.name, wallclock_seconds=SPEC['wallclock_seconds'])
    return flow.initialize_payload(float(SPEC['wallclock_seconds'])), frame


def tuple_action(actor, candidate):
    p = actor.planner
    _, center, duration, program, chosen, fibers = candidate
    estimate = actor.calibrator.estimate if actor.calibrator else (0., 0.)
    action = dict(action='observe',
        pointing=dict(alt_deg=round(float(center[0])-float(estimate[0]), 7),
                      az_deg=round((float(center[1])-float(estimate[1])) % 360, 7)),
        assignments={str(int(f)):p.ids[int(i)] for i, f in zip(chosen, fibers)},
        duration_seconds=int(duration), program=PROGRAMS[int(program)])
    return action


def prediction_for(actor, action, now):
    p = actor.planner
    alt, az, _, _ = p._altaz(local_sidereal_deg(now, p.lon))
    q = p._public_quality(now, local_sidereal_deg(now, p.lon), alt)
    k = p._cpu_phase_frame[2]
    C = actor.pending['prior_C']; E = actor.pending['prior_E']
    band = np.where(q*C*p.q0 >= p.dark_threshold, 0,
                    np.where(q*C*p.q0 >= p.bright_threshold, 1, 2))
    quality = k*p.f0t0/np.maximum(p.flux, 1e-12)
    output = {}
    for f, target in action['assignments'].items():
        i = p.index[target]
        output[target] = dict(index=int(i), fiber_id=int(f),
            factor=min(1., float(k[i])*action['duration_seconds']),
            public_quality=float(q[i]), quality=float(quality[i]),
            directional_scale=float(quality[i]/max(1e-12, q[i]*C*E*p.q0)),
            predicted_band=PROGRAMS[int(band[i])], alt_deg=float(alt[i]), az_deg=float(az[i]))
    return output


def menu(initial, snapshot):
    actor = BASE(copy.deepcopy(initial))
    action = actor.decide(copy.deepcopy(snapshot))
    if action['action'] != 'observe' or snapshot.get('active_requests'):
        raise RuntimeError('Pilot requires initial observe with no active request')
    p = actor.planner
    candidates = sorted(p._cpu_phase_baseline_candidates, key=lambda x:-float(x[0]))
    base_targets = set(action['assignments'].values())
    alt = None
    for c in candidates:
        trial = tuple_action(actor, c)
        ids = set(trial['assignments'].values())
        overlap = len(base_targets & ids)/max(1, len(base_targets | ids))
        if digest(trial) != digest(action) and overlap < .5:
            alt = trial
            break
    if alt is None:
        raise RuntimeError('No diverse existing baseline field in fixed menu')
    return [copy.deepcopy(action), alt, dict(action='wait', duration_seconds=SPEC['wait_seconds'])]


def force(actor, snapshot, original, action):
    if digest(original) == digest(action):
        # Keep the original pending/prediction object bit for bit. A rollout of
        # the incumbent must be the baseline, including all inference updates.
        return copy.deepcopy(original)
    if action['action'] == 'observe':
        actor.pending['action'] = copy.deepcopy(action)
        actor.pending['prediction'] = prediction_for(actor, action, parse_utc(snapshot['now_utc']))
    else:
        actor.pending = None
    actor.persistent_guard.sent(snapshot, action)
    return copy.deepcopy(action)


def run_b(root, output, first=None, selector=None, expected_initial=None, expected_snapshot=None):
    flow = V4Workflow(root)
    holder = {}
    records = []
    def initialize(initial):
        if expected_initial is not None and digest(initial) != expected_initial:
            raise RuntimeError('Different public initial payload')
        holder['actor'] = BASE(initial)
    def decide(message, deadline):
        snapshot = message['payload']; actor = holder['actor']
        before = time.perf_counter()
        action = actor.decide(snapshot)
        if not holder.get('first_seen'):
            holder['first_seen'] = True
            if expected_snapshot is not None and digest(canonical(snapshot)) != expected_snapshot:
                raise RuntimeError('Different initial public history')
            replacement = first
            if selector is not None:
                replacement, receipt = selector(actor.initial, snapshot)
                holder['selector'] = receipt
            if replacement is not None:
                action = force(actor, snapshot, action, replacement)
        records.append(dict(now_utc=snapshot['now_utc'], observe_action_index=snapshot['observe_action_index'],
                            public_history_sha256=digest(canonical(snapshot)), action=copy.deepcopy(action),
                            actor_seconds=time.perf_counter()-before))
        return dict(protocol_version='participant-agent-protocol-v4', message_type='decision_response',
                    decision_sequence=message['decision_sequence'], **action)
    started=time.perf_counter(); cpu_started=time.process_time()
    result=flow.run(decide, output, initialize=initialize, wallclock_seconds=SPEC['wallclock_seconds'])
    receipt=dict(wall_seconds=time.perf_counter()-started, cpu_seconds=time.process_time()-cpu_started,
                 termination=result['termination_reason'], score=result['score_report'],
                 actor=holder['actor'].summary() if 'actor' in holder else None,
                 selector=holder.get('selector'), records=records)
    dump(output/'RECEIPT.json', receipt)
    return receipt


def generate():
    ref=ROOT/'official/challenge/reference/v4'
    configs={k:json.loads((ref/f'v4_{name}_config.json').read_text())
             for k,name in [('catalog','catalog'),('weather','weather'),('fiber','fiber'),('score','score')]}
    c=configs['catalog']; w=configs['weather']
    c.update(seed=SPEC['catalog_seed'], seed_derivation='sha256-v1')
    c['footprint'].update(total_area_deg2=240., n_components=2,
        component_area_weights=[.5,.5], component_centers=[[335.,-22.],[65.,-54.]],
        vertices_per_component=24, harmonic_amplitude_ranges=[.06,.04,.02], component_gap_deg=2.)
    c['targets'].update(total_count=192, n_cluster_centers=3, clustered_fraction=.25)
    c['observability'].update(start_date='2026-11-02',end_date='2026-11-05',minimum_window_seconds=900)
    w.update(seed_derivation='sha256-v1')
    w['survey'].update(start_date='2026-11-02',end_date='2026-11-05')
    for event in w['weather_events']['conditions'].values():event['count']=0
    for kind in ['rocket_launch','earthquake']:w[kind]['count']=0
    w['terrain_obstruction']['sector_count']=[0,0]
    w['instrument_fault']['count']=1
    w['stress_tests']['enabled']=False
    card=dict(name='Independent horizon pilot',card_id='horizon-initial-synthetic',
              scenario_slug='horizon-initial-synthetic',phase='synthetic-only',stress=False,
              wallclock_seconds=SPEC['wallclock_seconds'],
              observation_requests=dict(count=1,window_nights=1,targets_per_request=3,
                                        minimum_completion_fraction=2/3,include_required_targets=True))
    configs['card']=card
    dump(ROOT/'NONSEED_CONFIGS.json',configs)
    for role,seeds in [('prior',SPEC['prior_seeds']),('evaluation',SPEC['evaluation_seeds'])]:
        for seed in seeds:
            dest=ROOT/'worlds'/role/f'W{seed}'
            if dest.exists():continue
            spec=ROOT/'specs'/role/f'W{seed}'; spec.mkdir(parents=True,exist_ok=True)
            for key, filename in [('catalog','v4_catalog_config.json'),('weather','v4_weather_config.json'),
                                  ('fiber','v4_fiber_config.json'),('score','v4_score_config.json'),('card','card.json')]:
                cfg=copy.deepcopy(configs[key])
                if key=='weather':cfg['seed']=seed
                dump(spec/filename,cfg)
            v4_bundle.build_spec_bundle(dest,spec)
            # Requests have their own independent synthetic seed; matching catalog
            # seeds must not accidentally share an exact hidden request trajectory.
            score=configs['score']; fiber=configs['fiber']
            v4_observation_requests.generate_requests(seed=seed+700000,
                targets_csv=dest/'public/targets.csv',night_calendar_csv=dest/'public/v4_night_calendar.csv',
                slots_csv=dest/'truth/v4_slots.csv',site=c['site'],
                minimum_altitude_deg=c['observability']['minimum_altitude_deg'],
                output_path=dest/'truth/v4_observation_requests.jsonl',settings=card['observation_requests'],
                flux_zero_point=score['flux_zero_point'],exposure_zero_point_seconds=score['exposure_zero_point_seconds'],
                min_duration_seconds=fiber['exposure']['min_duration_seconds'],
                max_duration_seconds=fiber['exposure']['max_duration_seconds'])
    dump(ROOT/'GENERATED_WORLDS.json',dict(**SPEC,
        files={str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in (ROOT/'worlds').rglob('*') if p.is_file()}))


class InitialSelector:
    def __init__(self, prefix):self.prefix=Path(prefix);self.calls=0
    def __call__(self, initial, snapshot):
        started=time.perf_counter(); cpu_started=time.process_time(); self.calls+=1
        candidates=menu(initial,snapshot)
        initial_hash=digest(initial); snapshot_hash=digest(canonical(snapshot))
        values=[]; rollout_receipts=[]
        # Fixed candidate action is shared across every prior path. B has one
        # unchanged history-to-action mapping; no future path optimization occurs.
        for k,action in enumerate(candidates):
            row=[]
            for seed in SPEC['prior_seeds']:
                output=self.prefix/f'call{self.calls}'/f'C{k}'/f'W{seed}'
                result=run_b(ROOT/'worlds/prior'/f'W{seed}',output,first=action,
                             expected_initial=initial_hash,expected_snapshot=snapshot_hash)
                if result['termination']!='survey_complete':raise RuntimeError('Prior rollout incomplete')
                row.append(float(result['score']['total']))
                rollout_receipts.append(dict(candidate=k,prior_seed=seed,score=row[-1],
                    wall_seconds=result['wall_seconds'],cpu_seconds=result['cpu_seconds']))
            values.append(row)
        means=np.mean(values,axis=1)
        # Baseline incumbent wins exact ties; candidate and prior ordering frozen.
        winner=int(np.argmax(means))
        receipt=dict(candidates=candidates,prior_values=values,means=means.tolist(),winner=winner,
                     selector_wall_seconds=time.perf_counter()-started,
                     selector_cpu_seconds=time.process_time()-cpu_started,
                     initial_sha256=initial_hash,initial_history_sha256=snapshot_hash,
                     reads_evaluation_truth=False,prior_seeds=SPEC['prior_seeds'],
                     continuation_policy='unchanged B on participant-visible feedback',
                     rollouts=rollout_receipts)
        dump(self.prefix/f'call{self.calls}'/'SELECTOR_RECEIPT.json',receipt)
        return candidates[winner],receipt


def main():
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['generate','measure','choose','pilot'])
    args=a.parse_args()
    if args.mode=='generate':generate();return
    if args.mode=='measure':
        r=run_b(ROOT/'worlds/prior/W77101',ROOT/'measure/W77101')
        print(json.dumps({k:r[k] for k in ['wall_seconds','cpu_seconds','termination','score']}));return
    if args.mode=='choose':
        initial,snapshot=first_public(ROOT/'worlds/prior/W77101')
        action,receipt=InitialSelector(ROOT/'chooser_probe')(initial,snapshot)
        print(json.dumps(receipt));return
    pairs=[]
    for seed in SPEC['evaluation_seeds']:
        root=ROOT/'worlds/evaluation'/f'W{seed}'
        control=run_b(root,ROOT/'pilot'/f'W{seed}'/'B')
        proposed=run_b(root,ROOT/'pilot'/f'W{seed}'/'H',
                       selector=InitialSelector(ROOT/'pilot'/f'W{seed}'/'chooser'))
        pairs.append(dict(seed=seed,control=control['score'],horizon=proposed['score'],
                          delta=float(proposed['score']['total'])-float(control['score']['total']),
                          control_wall_seconds=control['wall_seconds'],horizon_wall_seconds=proposed['wall_seconds'],
                          control_cpu_seconds=control['cpu_seconds'],horizon_cpu_seconds=proposed['cpu_seconds'],
                          winner=proposed['selector']['winner'],
                          selector_cpu_seconds=proposed['selector']['selector_cpu_seconds'],
                          terminations=[control['termination'],proposed['termination']]))
        dump(ROOT/'PILOT_PROGRESS.json',pairs)
        print(json.dumps(pairs[-1]),flush=True)
    dump(ROOT/'PILOT_RESULT.json',dict(pairs=pairs,mean_delta=float(np.mean([p['delta'] for p in pairs])),
        total_process_cpu_seconds=sum(p['control_cpu_seconds']+p['horizon_cpu_seconds'] for p in pairs),
        resource_ru_maxrss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**SPEC))


if __name__=='__main__':main()
