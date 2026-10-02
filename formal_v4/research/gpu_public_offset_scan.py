"""Resumable public phase scan using exact sample-pool offset intervals.

Only public catalogue signatures are read. Every checkpoint certifies all pools
3..2**32-1 under the selected catalogue RNG model, including CPU fallbacks.
This does not assume that master-seed entropy is 32 bits.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import statistics
import time

from numba import cuda

from gpu_offset_seed_model import OffsetScanner,complete_offsets,controls,offset_set_controls,phases_at_offset
from gpu_public_seed_scan import CLASSES,phase_error,write_atomic


def validate(seed,offset,card,hashed,tolerance):
    phases,rng = phases_at_offset(seed,offset,hashed)
    error = phase_error(phases,card['phases_rad'])
    if error>tolerance:raise AssertionError('GPU candidate differs from exact CPU phase result')
    roster = [name for name in CLASSES for _ in range(card['class_counts'].get(name,0))]
    rng.shuffle(roster)
    required = set(rng.sample(range(len(roster)),len(card['required_indices'])))
    evidence = complete_offsets(seed,hashed)
    witnesses = [row for row in evidence['witness_intervals'] if row['offset_words']==offset]
    if not witnesses:raise AssertionError('phase candidate offset lacks any legal pool witness')
    classes_match = roster==card['target_classes']
    required_match = required==set(card['required_indices'])
    return {'card':card['name'],'seed':int(seed),'offset_words':int(offset),
            'mode':'sha256-v1' if hashed else 'legacy','phase_error_rad':error,
            'pool_witness_intervals':witnesses,'all_target_classes_exact':classes_match,
            'all_required_flags_exact':required_match,
            'public_catalog_signature_match':classes_match and required_match}


def run(args):
    fingerprints = Path(args.fingerprints)
    cards = json.loads(fingerprints.read_text())['cards']
    if not 1<=len(cards)<=16 or any(len(card['phases_rad'])!=9 for card in cards):
        raise ValueError('need 1..16 public cards, each with exactly nine phases')
    start,stop = int(args.start),2**32 if args.full32 else int(args.stop)
    if not 0<=start<stop<=2**32:raise ValueError('range must lie inside [0,2**32)')
    if not 1<=args.batch<=2**20:raise ValueError('batch must be 1..2**20')
    hashed = args.mode=='sha256-v1'
    checkpoint = Path(args.checkpoint)
    stop_file = Path(args.stop_file) if args.stop_file else checkpoint.parent/'STOP_PUBLIC_OFFSET_SCAN'
    sources = ('gpu_public_offset_scan.py','gpu_offset_seed_model.py','offset_coverage_model.py',
               'gpu_public_seed_scan.py','gpu_seed_throughput.py')
    identity = {'mode':args.mode,'start':start,'stop_exclusive':stop,
                'pool_range':[3,2**32-1],'phase_tolerance_rad':args.tolerance,
                'fingerprint_sha256':hashlib.sha256(fingerprints.read_bytes()).hexdigest(),
                'source_sha256':{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                 for name in sources}}
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state['identity']!=identity:raise ValueError('checkpoint model, range or source hash changed')
    else:
        state = {'schema':'public-catalog-offset-scan-v1','identity':identity,
                 'completed_until':start,'searched_seed_count':0,'batches':0,'fallback_seeds':0,
                 'phase_candidates':[],'public_signature_matches':[],'elapsed_seconds':0.,
                 'status':'initializing','created_utc':datetime.now(timezone.utc).isoformat()}
    if state['completed_until']>=stop:
        print(json.dumps({'event':'already_complete','checkpoint':str(checkpoint)}),flush=True)
        return state
    state['offset_set_controls'] = offset_set_controls()
    state['positive_controls'] = controls()
    scanner = OffsetScanner([card['phases_rad'] for card in cards],hashed,args.tolerance)
    scanner.run(0,1)
    state.update(status='running',device=str(cuda.get_current_device()),batch_size=args.batch,
                 yield_seconds=args.yield_seconds,stop_file=str(stop_file))
    write_atomic(checkpoint,state)
    print(json.dumps({'event':'controls_passed','model':args.mode,
                      'offset_set_controls':state['offset_set_controls'],
                      'phase_controls':len(state['positive_controls']),
                      'start':state['completed_until'],'stop':stop}),flush=True)
    began = last_checkpoint = time.perf_counter()
    prior_elapsed = state['elapsed_seconds']
    current = resumed = state['completed_until']
    kernels,ends = [],[]
    while current<stop:
        if stop_file.exists():
            state['status']='paused_stop_file';break
        if time.perf_counter()-began>=args.max_seconds:
            state['status']='paused_wallclock_budget';break
        count = min(state['batch_size'],stop-current)
        try:
            output = scanner.run(current,count)
        except RuntimeError as error:
            if 'output overflow' not in str(error) or count<=1:raise
            state['batch_size'] = max(1,count//2)
            print(json.dumps({'event':'rerun_smaller_overflow','at':current,
                              'next_batch':state['batch_size']}),flush=True)
            continue
        kernels.append(output['kernel_seconds']);ends.append(output['end_to_end_seconds'])
        for seed,offset,card_index in output['matches']:
            validated = validate(seed,offset,cards[card_index],hashed,args.tolerance)
            state['phase_candidates'].append(validated)
            if validated['public_catalog_signature_match']:
                state['public_signature_matches'].append(validated)
                print(json.dumps({'event':'public_signature_match',**validated}),flush=True)
        # CPU completion and candidate verification precede certification of this range.
        current += count
        state['completed_until'] = current
        state['searched_seed_count'] += count
        state['batches'] += 1
        state['fallback_seeds'] += output['fallback_seed_count']
        elapsed = time.perf_counter()-began
        state['elapsed_seconds'] = prior_elapsed+elapsed
        state['median_kernel_seconds'] = statistics.median(kernels[-128:])
        state['max_kernel_seconds'] = max(kernels)
        state['median_batch_end_to_end_seconds'] = statistics.median(ends[-128:])
        state['seed_per_second_including_yield'] = (current-resumed)/max(elapsed,1e-9)
        state['remaining_seconds_estimate'] = (stop-current)/state['seed_per_second_including_yield']
        if output['kernel_seconds']>.03 and state['batch_size']>256:
            state['batch_size'] = max(256,state['batch_size']//2)
        if elapsed>5 and current-resumed>2**21 and state['remaining_seconds_estimate']>3600:
            state['status']='paused_unfeasible_throughput';break
        if time.perf_counter()-last_checkpoint>=args.checkpoint_seconds or output['matches']:
            write_atomic(checkpoint,state)
            print(json.dumps({'event':'progress','completed_until':current,'stop':stop,
                              'elapsed_seconds':round(state['elapsed_seconds'],3),
                              'remaining_seconds':round(state['remaining_seconds_estimate'],3),
                              'median_kernel_ms':round(state['median_kernel_seconds']*1000,3),
                              'max_kernel_ms':round(state['max_kernel_seconds']*1000,3),
                              'batch_size':state['batch_size'],'fallback_seeds':state['fallback_seeds'],
                              'phase_candidates':len(state['phase_candidates']),
                              'public_signature_matches':len(state['public_signature_matches'])}),flush=True)
            last_checkpoint = time.perf_counter()
        if args.yield_seconds:time.sleep(args.yield_seconds)
    if current>=stop:state['status']='complete'
    state['elapsed_seconds'] = prior_elapsed+time.perf_counter()-began
    state['updated_utc'] = datetime.now(timezone.utc).isoformat()
    write_atomic(checkpoint,state)
    print(json.dumps({'event':state['status'],'completed_until':current,
                      'elapsed_seconds':state['elapsed_seconds'],
                      'phase_candidates':len(state['phase_candidates']),
                      'public_signature_matches':len(state['public_signature_matches'])}),flush=True)
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
    parser.add_argument('--max-seconds',type=float,default=1200.)
    parser.add_argument('--tolerance',type=float,default=1e-4)
    parser.add_argument('--stop-file')
    run(parser.parse_args())
