"""Checkpointed public-catalogue seed scan, with CUDA exact-phase filtering.

Uses only a prepared public phase/class/required fingerprint JSON. SHA256-v1 and
legacy consumption models are explicit hypotheses; neither asserts seed entropy.
Range is bounded by --start/--stop; --full32 explicitly selects [0,2**32).
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import time

import numpy as np
from numba import cuda, float64, uint32, uint64

from gpu_seed_throughput import _derive, _init_mt, _phase, _sample_index, MAX_EARLY_WORDS, TWO_PI

CLASSES = ("ELG", "BGS", "LRG", "QSO", "Star")


@cuda.jit(device=True, inline=True)
def _distance(a,b):
    delta = abs(a-b)
    return min(delta,TWO_PI-delta)


@cuda.jit(device=True, inline=True)
def _append(seed,pool,card,rows,count,index):
    position = cuda.atomic.add(count,index,1)
    if position < rows.shape[0]:
        rows[position,0],rows[position,1],rows[position,2] = seed,pool,card


@cuda.jit
def scan_batch(start,count,hashed,targets,tolerance,matches,overflows,counters):
    index = cuda.grid(1)
    if index >= count:
        return
    seed = uint64(start) + uint64(index)
    h = cuda.local.array(8,dtype=uint32)
    mt = cuda.local.array(624,dtype=uint32)
    values = cuda.local.array(9,dtype=float64)
    if hashed:
        _derive(seed,h)
    else:
        for j in range(8):
            h[j] = 0
        h[3] = uint32(seed)
    _init_mt(h,mt)
    for pool in range(3,17):
        p = _sample_index(mt,pool,3)
        if p < 0 or p+1 >= MAX_EARLY_WORDS:
            _append(seed,pool,0,overflows,counters,1)
            continue
        first_phase = _phase(mt,p)
        mask = 0
        for card in range(targets.shape[0]):
            if _distance(first_phase,targets[card,0]) <= tolerance:
                mask |= 1 << card
        if mask == 0:
            continue
        failed = False
        for component in range(3):
            for harmonic in range(3):
                if p+1 >= MAX_EARLY_WORDS:
                    failed = True
                elif not failed:
                    values[component*3+harmonic] = _phase(mt,p)
                    p += 2
            p += 6
        if failed:
            _append(seed,pool,0,overflows,counters,1)
            continue
        for card in range(targets.shape[0]):
            if mask & (1 << card):
                good = True
                for j in range(9):
                    if _distance(values[j],targets[card,j]) > tolerance:
                        good = False
                        break
                if good:
                    _append(seed,pool,card,matches,counters,0)


def phase_rng(seed,pool,hashed):
    if hashed:
        digest = hashlib.sha256(f"{int(seed)}:v4.catalog".encode()).digest()
        derived = int.from_bytes(digest[:16],"big")
    else:
        derived = int(seed)
    rng = random.Random(derived)
    rng.sample(range(pool),3)
    phases = []
    for _ in range(3):
        phases.extend(rng.uniform(0,TWO_PI) for _ in range(3))
        for _ in range(3):
            rng.random()
    return phases,rng


def phase_error(a,b):
    return max(abs((x-y+math.pi)%TWO_PI-math.pi) for x,y in zip(a,b))


class BatchScanner:
    def __init__(self,phases,hashed,tolerance=1e-4):
        self.hashed = bool(hashed)
        self.tolerance = float(tolerance)
        self.targets = cuda.to_device(np.asarray(phases,dtype=np.float64))
        self.matches = cuda.device_array((256,3),dtype=np.uint64)
        self.overflows = cuda.device_array((1024,3),dtype=np.uint64)
        self.counters = cuda.to_device(np.zeros(2,dtype=np.int32))
        self.zeros = np.zeros(2,dtype=np.int32)

    def run(self,start,count):
        begin = time.perf_counter()
        self.counters.copy_to_device(self.zeros)
        event_a,event_b = cuda.event(timing=True),cuda.event(timing=True)
        event_a.record()
        scan_batch[(int(count)+63)//64,64](np.uint64(start),int(count),self.hashed,
                                         self.targets,self.tolerance,self.matches,self.overflows,self.counters)
        event_b.record()
        event_b.synchronize()
        counters = self.counters.copy_to_host()
        if counters[0]>len(self.matches) or counters[1]>len(self.overflows):
            raise RuntimeError(f"batch output capacity exceeded; batch NOT checkpointed: {counters.tolist()}")
        matches = self.matches[:int(counters[0])].copy_to_host().tolist() if counters[0] else []
        overflows = self.overflows[:int(counters[1])].copy_to_host().tolist() if counters[1] else []
        return {'matches':matches,'overflows':overflows,
                'kernel_seconds':event_a.elapsed_time(event_b)/1000,
                'end_to_end_seconds':time.perf_counter()-begin}


def controls():
    results = []
    for hashed in (True,False):
        known = [(5021,7),(1234567,16),(2**32-1,4)]
        phases = [phase_rng(seed,pool,hashed)[0] for seed,pool in known]
        scanner = BatchScanner(phases,hashed,tolerance=1e-10)
        scanner.run(0,1) # Compile before any event-based control timing.
        for card,(seed,pool) in enumerate(known):
            start = max(0,seed-4)
            count = min(9,2**32-start)
            output = scanner.run(start,count)
            expected = []
            for candidate in range(start,start+count):
                for candidate_pool in range(3,17):
                    actual,_ = phase_rng(candidate,candidate_pool,hashed)
                    for target,signature in enumerate(phases):
                        if phase_error(actual,signature)<=1e-10:
                            expected.append([candidate,candidate_pool,target])
            if sorted(expected)!=sorted(output['matches']) or output['overflows']:
                raise AssertionError({'hashed':hashed,'known_seed':seed,'expected':expected,'actual':output})
            if [seed,pool,card] not in output['matches']:
                raise AssertionError('known public seed missing')
            results.append({'hashed':hashed,'known_seed':seed,'known_pool':pool,
                            'exact_cpu_candidate_set':True,'matches':len(expected),
                            'kernel_seconds':output['kernel_seconds']})
    return results


def validate(seed,pool,card,hashed,tolerance):
    phases,rng = phase_rng(seed,pool,hashed)
    error = phase_error(phases,card['phases_rad'])
    if error>tolerance:
        return None
    roster = [name for name in CLASSES for _ in range(card['class_counts'].get(name,0))]
    rng.shuffle(roster)
    predicted_required = set(rng.sample(range(len(roster)),len(card['required_indices'])))
    classes_match = roster==card['target_classes']
    required_match = predicted_required==set(card['required_indices'])
    return {'card':card['name'],'seed':int(seed),'pool':int(pool),
            'mode':'sha256-v1' if hashed else 'legacy','phase_error_rad':error,
            'all_target_classes_exact':classes_match,'all_required_flags_exact':required_match,
            'public_catalog_signature_match':classes_match and required_match}


def write_atomic(path,data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,indent=2)+'\n')
    temporary.replace(path)


def run(args):
    fingerprint_path = Path(args.fingerprints)
    payload = json.loads(fingerprint_path.read_text())
    cards = payload['cards']
    if not cards or len(cards)>16 or any(len(c['phases_rad'])!=9 for c in cards):
        raise ValueError('fingerprints must contain 1..16 public cards with exactly 9 phases')
    hashed = args.mode=='sha256-v1'
    start,stop = int(args.start),2**32 if args.full32 else int(args.stop)
    if not 0<=start<stop<=2**32 or not 1<=args.batch<=2**20:
        raise ValueError('range must lie inside [0,2**32), batch<=2**20')
    checkpoint = Path(args.checkpoint)
    stop_file = Path(args.stop_file) if args.stop_file else checkpoint.parent/'STOP_PUBLIC_SEED_SCAN'
    identity = {'mode':args.mode,'start':start,'stop_exclusive':stop,'pool_range':[3,16],
                'phase_tolerance_rad':args.tolerance,
                'fingerprint_sha256':hashlib.sha256(fingerprint_path.read_bytes()).hexdigest(),
                'scanner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'rng_helper_sha256':hashlib.sha256(Path(__file__).with_name('gpu_seed_throughput.py').read_bytes()).hexdigest()}
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state['identity']!=identity:
            raise ValueError('checkpoint model/range/hash differs; refusing to skip a changed-model range')
    else:
        state = {'schema':'public-catalog-seed-scan-v1','identity':identity,'completed_until':start,
                 'searched_seed_count':0,'batches':0,'overflow_pairs':0,'phase_candidates':[],
                 'public_signature_matches':[],'elapsed_seconds':0.,'status':'initializing',
                 'created_utc':datetime.now(timezone.utc).isoformat()}
    if state['completed_until']>=stop:
        print(json.dumps({'event':'already_complete','checkpoint':str(checkpoint)}),flush=True)
        return state
    state['positive_controls'] = controls()
    scanner = BatchScanner([c['phases_rad'] for c in cards],hashed,args.tolerance)
    # One-seed warmup excludes compilation from end-to-end throughput.
    scanner.run(0,1)
    state['status'] = 'running'
    state['device'] = str(cuda.get_current_device())
    state['batch_size'] = args.batch
    state['yield_seconds'] = args.yield_seconds
    write_atomic(checkpoint,state)
    print(json.dumps({'event':'controls_passed','controls':state['positive_controls'],
                      'start':state['completed_until'],'stop':stop}),flush=True)
    began = time.perf_counter()
    prior_elapsed = state['elapsed_seconds']
    last_checkpoint = began
    current_start = state['completed_until']
    kernels,ends = [],[]
    resumed_start = current_start
    while current_start<stop:
        if stop_file.exists():
            state['status'] = 'paused_stop_file'
            break
        if time.perf_counter()-began>=args.max_seconds:
            state['status'] = 'paused_wallclock_budget'
            break
        count = min(state['batch_size'],stop-current_start)
        output = scanner.run(current_start,count)
        kernels.append(output['kernel_seconds'])
        ends.append(output['end_to_end_seconds'])
        candidates = set(tuple(row) for row in output['matches'])
        # An explicitly flagged overflow is evaluated with unbounded CPython RNG.
        # No range is checkpointed until every fallback candidate is dealt with.
        for seed,pool,_ in output['overflows']:
            phases,_ = phase_rng(seed,pool,hashed)
            for card_index,card in enumerate(cards):
                if phase_error(phases,card['phases_rad'])<=args.tolerance:
                    candidates.add((seed,pool,card_index))
        for seed,pool,card_index in sorted(candidates):
            validated = validate(seed,pool,cards[card_index],hashed,args.tolerance)
            if validated is None:
                raise AssertionError('GPU candidate fails exact CPU phase validation')
            state['phase_candidates'].append(validated)
            if validated['public_catalog_signature_match']:
                state['public_signature_matches'].append(validated)
                print(json.dumps({'event':'public_signature_match',**validated}),flush=True)
        current_start += count
        state['completed_until'] = current_start
        state['searched_seed_count'] += count
        state['batches'] += 1
        state['overflow_pairs'] += len(output['overflows'])
        elapsed = time.perf_counter()-began
        state['elapsed_seconds'] = prior_elapsed+elapsed
        state['median_kernel_seconds'] = statistics.median(kernels[-128:])
        state['max_kernel_seconds'] = max(kernels)
        state['median_batch_end_to_end_seconds'] = statistics.median(ends[-128:])
        state['seed_per_second_including_yield'] = (current_start-resumed_start)/max(elapsed,1e-9)
        state['remaining_seconds_estimate'] = (stop-current_start)/state['seed_per_second_including_yield']
        if output['kernel_seconds']>.1:
            state['status'] = 'paused_kernel_too_long'
            break
        if elapsed>5 and (current_start-resumed_start)>2**21 and state['remaining_seconds_estimate']>3600:
            state['status'] = 'paused_unfeasible_end_to_end_throughput'
            break
        if time.perf_counter()-last_checkpoint>=args.checkpoint_seconds or candidates:
            write_atomic(checkpoint,state)
            print(json.dumps({'event':'progress','completed_until':current_start,'stop':stop,
                              'searched_seed_count':state['searched_seed_count'],
                              'elapsed_seconds':round(state['elapsed_seconds'],3),
                              'seed_per_second':round(state['seed_per_second_including_yield']),
                              'remaining_seconds':round(state['remaining_seconds_estimate'],3),
                              'median_kernel_ms':round(state['median_kernel_seconds']*1000,4),
                              'max_kernel_ms':round(state['max_kernel_seconds']*1000,4),
                              'matches':len(state['public_signature_matches']),
                              'overflow_pairs':state['overflow_pairs']}),flush=True)
            last_checkpoint = time.perf_counter()
        if args.yield_seconds:
            time.sleep(args.yield_seconds)
    if current_start>=stop:
        state['status'] = 'complete'
    state['elapsed_seconds'] = prior_elapsed+time.perf_counter()-began
    state['updated_utc'] = datetime.now(timezone.utc).isoformat()
    write_atomic(checkpoint,state)
    print(json.dumps({'event':'finished','status':state['status'],'searched_seed_count':state['searched_seed_count'],
                      'elapsed_seconds':state['elapsed_seconds'],'matches':state['public_signature_matches'],
                      'checkpoint':str(checkpoint)}),flush=True)
    return state


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fingerprints',required=True)
    parser.add_argument('--checkpoint',required=True)
    parser.add_argument('--mode',choices=('sha256-v1','legacy'),default='sha256-v1')
    parser.add_argument('--start',type=int,default=0)
    parser.add_argument('--stop',type=int,default=2**24)
    parser.add_argument('--full32',action='store_true')
    parser.add_argument('--batch',type=int,default=262144)
    parser.add_argument('--yield-seconds',type=float,default=.002)
    parser.add_argument('--checkpoint-seconds',type=float,default=5.)
    parser.add_argument('--max-seconds',type=float,default=3600.)
    parser.add_argument('--tolerance',type=float,default=1e-4)
    parser.add_argument('--stop-file',default=None)
    run(parser.parse_args())
