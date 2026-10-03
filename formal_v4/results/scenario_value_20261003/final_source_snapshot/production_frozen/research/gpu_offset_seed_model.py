"""CUDA small-batch pilot for the exact all-pool RNG-offset model.

No full-space scan is exposed by this script. Matches use public phase signatures;
unfinished prefix models are explicitly completed on CPU before any certification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import time

import numpy as np
from numba import cuda,float64,uint32,uint64

from gpu_seed_throughput import _derive,_init_mt,_early_word,_phase,TWO_PI
from gpu_public_seed_scan import _append,_distance,phase_error,phase_rng
from offset_coverage_model import possible_offsets,derived_seed


@cuda.jit(device=True,inline=True)
def _cached_word(mt,cache,p):
    return cache[p] if p<32 else _early_word(mt,p)


@cuda.jit(device=True)
def _pool_offset(mt,cache,n,limit):
    p = 0
    for i in range(3):
        value = n-i
        bits,v = 0,value
        while v:
            bits += 1
            v >>= 1
        while True:
            if p>=limit:
                return -1
            candidate = _cached_word(mt,cache,p)>>(32-bits)
            p += 1
            if candidate<value:
                break
    return p


@cuda.jit(device=True,inline=True)
def _remember(mask,offset):
    mask[offset//32] |= uint32(1)<<uint32(offset%32)


@cuda.jit(device=True)
def _all_pool_mask(mt,cache,mask,prefix_limit):
    for i in range(7):mask[i] = 0
    fallback = False
    for n in range(3,22):
        offset = _pool_offset(mt,cache,n,prefix_limit)
        if offset<0 or offset>197:
            fallback = True
        else:
            _remember(mask,offset)
    for bits in range(5,33):
        lower = uint64(1)<<uint64(bits-1)
        if lower<22:lower = uint64(22)
        upper = (uint64(1)<<uint64(bits))-uint64(1)
        b1,b2,b3 = uint64(0x100000000),uint64(0x100000000),uint64(0x100000000)
        finished = False
        for j in range(prefix_limit):
            old = b3
            value = uint64(_cached_word(mt,cache,j)>>(32-bits))
            if value<b1:
                b3,b2,b1 = b2,b1,value
            elif value!=b1 and value<b2:
                b3,b2 = b2,value
            elif value!=b1 and value!=b2 and value<b3:
                b3 = value
            if b3<old:
                a,b = max(lower,b3+uint64(1)),min(upper,old)
                if a<=b:
                    offset = j+1
                    if offset>197:
                        fallback = True
                    else:
                        _remember(mask,offset)
            if b3<lower:
                finished = True
                break
        if not finished:fallback = True
    return fallback


@cuda.jit
def offset_sets_batch(seeds,hashed,masks,fallbacks):
    index = cuda.grid(1)
    if index>=seeds.size:return
    seed = seeds[index]
    h = cuda.local.array(8,dtype=uint32)
    mt = cuda.local.array(624,dtype=uint32)
    cache = cuda.local.array(32,dtype=uint32)
    mask = cuda.local.array(7,dtype=uint32)
    if hashed:
        _derive(seed,h)
    else:
        for i in range(8):h[i] = 0
        h[3] = uint32(seed)
    _init_mt(h,mt)
    for i in range(32):cache[i] = _early_word(mt,i)
    fallbacks[index] = _all_pool_mask(mt,cache,mask,227)
    for i in range(7):masks[index,i] = mask[i]


@cuda.jit
def offset_batch(start,count,hashed,targets,tolerance,prefix_limit,matches,fallbacks,counters):
    index = cuda.grid(1)
    if index>=count:return
    seed = uint64(start)+uint64(index)
    h = cuda.local.array(8,dtype=uint32)
    mt = cuda.local.array(624,dtype=uint32)
    cache = cuda.local.array(32,dtype=uint32)
    mask = cuda.local.array(7,dtype=uint32)
    phases = cuda.local.array(9,dtype=float64)
    if hashed:
        _derive(seed,h)
    else:
        for i in range(8):h[i] = 0
        h[3] = uint32(seed)
    _init_mt(h,mt)
    for i in range(32):cache[i] = _early_word(mt,i)
    fallback = _all_pool_mask(mt,cache,mask,prefix_limit)
    if fallback:
        _append(seed,0,0,fallbacks,counters,1)
    for offset in range(3,198):
        if not (mask[offset//32] & (uint32(1)<<uint32(offset%32))):
            continue
        first = _phase(mt,offset)
        cards = 0
        for card in range(targets.shape[0]):
            if _distance(first,targets[card,0])<=tolerance:
                cards |= 1<<card
        if cards==0:continue
        p = offset
        for component in range(3):
            for harmonic in range(3):
                phases[component*3+harmonic] = _phase(mt,p)
                p += 2
            p += 6
        for card in range(targets.shape[0]):
            if cards & (1<<card):
                good = True
                for j in range(9):
                    if _distance(phases[j],targets[card,j])>tolerance:
                        good = False
                        break
                if good:_append(seed,offset,card,matches,counters,0)


def phases_at_offset(seed,offset,hashed):
    rng = random.Random(derived_seed(seed,hashed))
    for _ in range(offset):rng.getrandbits(32)
    phases = []
    for _ in range(3):
        phases.extend(rng.uniform(0,TWO_PI) for _ in range(3))
        for _ in range(3):rng.random()
    return phases,rng


def complete_offsets(seed,hashed):
    limit = 227
    while True:
        evidence = possible_offsets(seed,hashed=hashed,max_words=limit)
        if not evidence['unfinished_pool_bands']:return evidence
        limit *= 2
        if limit>2**20:
            raise RuntimeError('CPU fallback model unfinished; batch must not be certified')


class OffsetScanner:
    def __init__(self,signatures,hashed=True,tolerance=1e-4,prefix_limit=227):
        self.signatures = signatures
        self.hashed,self.tolerance,self.prefix_limit = bool(hashed),float(tolerance),int(prefix_limit)
        if not 1<=self.prefix_limit<=227:raise ValueError('prefix_limit must be in 1..227')
        self.targets = cuda.to_device(np.asarray(signatures,dtype=np.float64))
        self.matches = cuda.device_array((256,3),dtype=np.uint64)
        self.fallbacks = cuda.device_array((1024,3),dtype=np.uint64)
        self.counters = cuda.to_device(np.zeros(2,dtype=np.int32))
        self.zeros = np.zeros(2,dtype=np.int32)

    def run(self,start,count):
        begin = time.perf_counter()
        self.counters.copy_to_device(self.zeros)
        a,b = cuda.event(timing=True),cuda.event(timing=True)
        a.record()
        offset_batch[(int(count)+63)//64,64](np.uint64(start),int(count),self.hashed,self.targets,
                                            self.tolerance,self.prefix_limit,self.matches,self.fallbacks,self.counters)
        b.record();b.synchronize()
        counters = self.counters.copy_to_host()
        if counters[0]>len(self.matches) or counters[1]>len(self.fallbacks):
            raise RuntimeError('output overflow: batch NOT certified; rerun smaller batch')
        matches = set(tuple(map(int,row)) for row in self.matches[:int(counters[0])].copy_to_host()) if counters[0] else set()
        fallback_seeds = set(int(row[0]) for row in self.fallbacks[:int(counters[1])].copy_to_host()) if counters[1] else set()
        for seed in fallback_seeds:
            evidence = complete_offsets(seed,self.hashed)
            for offset in evidence['offsets']:
                phases,_ = phases_at_offset(seed,offset,self.hashed)
                for card,signature in enumerate(self.signatures):
                    if phase_error(phases,signature)<=self.tolerance:matches.add((seed,offset,card))
        return {'matches':sorted(matches),'fallback_seed_count':len(fallback_seeds),
                'kernel_seconds':a.elapsed_time(b)/1000,'end_to_end_seconds':time.perf_counter()-begin}


def controls():
    records = []
    for hashed in (True,False):
        known = [(5021,7),(1234567,16),(2**32-1,4)]
        signatures = [phase_rng(seed,pool,hashed)[0] for seed,pool in known]
        for limit in (227,4):
            scanner = OffsetScanner(signatures,hashed,tolerance=1e-10,prefix_limit=limit)
            scanner.run(0,1)
            for seed,pool in known:
                start = max(0,seed-4);count = min(9,2**32-start)
                output = scanner.run(start,count)
                expected = set()
                for candidate in range(start,start+count):
                    for offset in complete_offsets(candidate,hashed)['offsets']:
                        phases,_ = phases_at_offset(candidate,offset,hashed)
                        for card,signature in enumerate(signatures):
                            if phase_error(phases,signature)<=1e-10:expected.add((candidate,offset,card))
                if sorted(expected)!=output['matches']:
                    raise AssertionError({'hashed':hashed,'prefix_limit':limit,'seed':seed,'expected':sorted(expected),'actual':output})
                if limit==4 and output['fallback_seed_count']==0:
                    raise AssertionError('forced fallback control did not exercise fallback')
                records.append({'hashed':hashed,'prefix_limit':limit,'known_seed':seed,
                                'exact_cpu_candidate_set':True,**output})
    return records


def offset_set_controls(count=256):
    rng = random.Random(20261003)
    seeds = np.array([0,1,5021,2**32-1]+[rng.randrange(2**32) for _ in range(count-4)],dtype=np.uint64)
    device_seeds = cuda.to_device(seeds)
    masks,fallbacks = cuda.device_array((count,7),dtype=np.uint32),cuda.device_array(count,dtype=np.uint8)
    for hashed in (True,False):
        offset_sets_batch[(count+63)//64,64](device_seeds,hashed,masks,fallbacks)
        host_masks,host_fallbacks = masks.copy_to_host(),fallbacks.copy_to_host()
        for row,seed in enumerate(seeds):
            evidence = possible_offsets(int(seed),hashed=hashed,max_words=227)
            expected = {offset for offset in evidence['offsets'] if offset<=197}
            actual = {offset for offset in range(3,198) if int(host_masks[row,offset//32])&(1<<(offset%32))}
            expected_fallback = bool(evidence['unfinished_pool_bands'] or any(offset>197 for offset in evidence['offsets']))
            if expected!=actual or expected_fallback!=bool(host_fallbacks[row]):
                raise AssertionError({'seed':int(seed),'hashed':hashed,'expected':sorted(expected),'actual':sorted(actual)})
    return {'public_synthetic_seeds':count,'models':2,'all_offset_sets_exact':True,'fallback_flags_exact':True}


def benchmark(args):
    payload = json.loads(Path(args.fingerprints).read_text())
    signatures = [card['phases_rad'] for card in payload['cards']]
    result = {'schema':'public-offset-cuda-pilot-v1','scope':'positive controls and short batches; no full-space search',
              'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'fingerprint_sha256':hashlib.sha256(Path(args.fingerprints).read_bytes()).hexdigest(),
              'pool_range':[3,2**32-1],'offset_set_controls':offset_set_controls(),
              'positive_controls':controls(),'benchmarks':[]}
    scanner = OffsetScanner(signatures)
    scanner.run(0,1)
    for batch in (256,4096,65536,262144):
        if batch>args.max_batch:break
        outputs = []
        for _ in range(5):
            output = scanner.run(0,batch)
            outputs.append(output)
            time.sleep(.002)
        kernel = statistics.median(o['kernel_seconds'] for o in outputs)
        end_to_end = statistics.median(o['end_to_end_seconds'] for o in outputs)
        record = {'batch':batch,'median_kernel_seconds':kernel,
                  'max_kernel_seconds':max(o['kernel_seconds'] for o in outputs),
                  'median_end_to_end_seconds':end_to_end,
                  'projected_32bit_seconds_including_2ms_yield':2**32/batch*(end_to_end+.002),
                  'fallback_seed_count':sum(o['fallback_seed_count'] for o in outputs),
                  'matches':outputs[-1]['matches']}
        result['benchmarks'].append(record)
        print(json.dumps(record),flush=True)
        if max(o['kernel_seconds'] for o in outputs)>.03:break
    Path(args.out).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'controls_passed':len(result['positive_controls']),'out':args.out}),flush=True)
    return result


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fingerprints',required=True)
    parser.add_argument('--out',default='gpu_offset_seed_model_result.json')
    parser.add_argument('--max-batch',type=int,default=262144)
    benchmark(parser.parse_args())
