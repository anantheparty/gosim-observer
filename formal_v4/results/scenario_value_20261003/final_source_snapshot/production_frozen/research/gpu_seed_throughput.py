"""Restricted CUDA positive controls and public-seed throughput pilot.

Never searches a task card or a large unknown range. Defaults: 256 public test
seeds and at most 32768 seeds per short throughput kernel. SHA256 derivation and
Python MT19937 consumption are checked against hashlib/random before timing.
Run on a CUDA host: python gpu_seed_throughput.py --out result.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

import numpy as np
from numba import cuda, uint32

SHA_K = np.asarray([
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
], dtype=np.uint32)
SHA_H = np.asarray([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                    0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19], dtype=np.uint32)
SUFFIX = np.frombuffer(b":v4.catalog", dtype=np.uint8).copy()
TWO_PI = 2.0 * math.pi
MAX_EARLY_WORDS = 227


@cuda.jit(device=True, inline=True)
def _ror(x, n):
    return uint32((uint32(x) >> n) | (uint32(x) << (32 - n)))


@cuda.jit(device=True)
def _derive(seed, h):
    """One-block SHA256('<nonnegative decimal uint32>:v4.catalog')."""
    constants = cuda.const.array_like(SHA_K)
    initial = cuda.const.array_like(SHA_H)
    suffix = cuda.const.array_like(SUFFIX)
    words = cuda.local.array(64, dtype=uint32)
    digits = cuda.local.array(10, dtype=uint32)
    for i in range(64):
        words[i] = 0
    count = 0
    value = seed
    if value == 0:
        digits[0] = 48
        count = 1
    else:
        while value:
            digits[count] = uint32(value % 10 + 48)
            value = value // 10
            count += 1
    for i in range(count):
        words[i // 4] |= uint32(digits[count - i - 1] << (24 - 8 * (i % 4)))
    for i in range(11):
        p = count + i
        words[p // 4] |= uint32(uint32(suffix[i]) << (24 - 8 * (p % 4)))
    length = count + 11
    words[length // 4] |= uint32(0x80 << (24 - 8 * (length % 4)))
    words[15] = uint32(length * 8)
    for i in range(16, 64):
        x, y = words[i - 15], words[i - 2]
        s0 = _ror(x, 7) ^ _ror(x, 18) ^ (x >> 3)
        s1 = _ror(y, 17) ^ _ror(y, 19) ^ (y >> 10)
        words[i] = uint32(words[i - 16] + s0 + words[i - 7] + s1)
    a,b,c,d = initial[0],initial[1],initial[2],initial[3]
    e,f,g,z = initial[4],initial[5],initial[6],initial[7]
    for i in range(64):
        s1 = _ror(e, 6) ^ _ror(e, 11) ^ _ror(e, 25)
        ch = (e & f) ^ (uint32(~e) & g)
        t1 = uint32(z + s1 + ch + constants[i] + words[i])
        s0 = _ror(a, 2) ^ _ror(a, 13) ^ _ror(a, 22)
        maj = (a & b) ^ (a & c) ^ (b & c)
        t2 = uint32(s0 + maj)
        z,g,f,e,d,c,b,a = g,f,e,uint32(d+t1),c,b,a,uint32(t1+t2)
    h[0],h[1],h[2],h[3] = uint32(initial[0]+a),uint32(initial[1]+b),uint32(initial[2]+c),uint32(initial[3]+d)
    h[4],h[5],h[6],h[7] = uint32(initial[4]+e),uint32(initial[5]+f),uint32(initial[6]+g),uint32(initial[7]+z)


@cuda.jit(device=True)
def _init_mt(h, mt):
    """CPython integer seed: little-endian uint32 key, init_by_array."""
    key = cuda.local.array(4, dtype=uint32)
    for j in range(4):
        key[j] = h[3 - j]
    key_length = 4
    while key_length > 1 and key[key_length - 1] == 0:
        key_length -= 1
    mt[0] = uint32(19650218)
    for i in range(1, 624):
        mt[i] = uint32(uint32(1812433253) * (mt[i-1] ^ (mt[i-1] >> 30)) + i)
    i, j = 1, 0
    for k in range(624):
        mt[i] = uint32((mt[i] ^ uint32((mt[i-1] ^ (mt[i-1] >> 30)) * uint32(1664525))) + key[j] + j)
        i += 1
        j += 1
        if i >= 624:
            mt[0] = mt[623]
            i = 1
        if j >= key_length:
            j = 0
    for k in range(623):
        mt[i] = uint32((mt[i] ^ uint32((mt[i-1] ^ (mt[i-1] >> 30)) * uint32(1566083941))) - i)
        i += 1
        if i >= 624:
            mt[0] = mt[623]
            i = 1
    mt[0] = uint32(0x80000000)


@cuda.jit(device=True, inline=True)
def _early_word(mt, p):
    """Exact initial twist word for p<227, without mutating the seed state."""
    y = uint32((mt[p] & uint32(0x80000000)) | (mt[p+1] & uint32(0x7fffffff)))
    x = uint32(mt[p+397] ^ (y >> 1) ^ (uint32(0x9908b0df) if y & 1 else uint32(0)))
    x ^= x >> 11
    x ^= uint32((x << 7) & uint32(0x9d2c5680))
    x ^= uint32((x << 15) & uint32(0xefc60000))
    x ^= x >> 18
    return uint32(x)


@cuda.jit(device=True)
def _sample_index(mt, pool, k):
    """Consumption of random.sample(range(pool),k), pool<=21 and k<=5.

    Selected pool values are irrelevant to the subsequent RNG position. Every
    rejection consumes one word; overflow is flagged, never silently discarded.
    """
    p = 0
    for i in range(k):
        n = pool - i
        bits, v = 0, n
        while v:
            bits += 1
            v >>= 1
        while True:
            if p >= MAX_EARLY_WORDS:
                return -1
            value = _early_word(mt, p) >> (32 - bits)
            p += 1
            if value < n:
                break
    return p


@cuda.jit(device=True, inline=True)
def _phase(mt, p):
    a = _early_word(mt, p) >> 5
    b = _early_word(mt, p+1) >> 6
    return ((float(a) * 67108864.0 + float(b)) / 9007199254740992.0) * TWO_PI


@cuda.jit
def positive_control(seeds, digest_words, raw_words, phases, overflow):
    i = cuda.grid(1)
    if i >= seeds.size:
        return
    h = cuda.local.array(8, dtype=uint32)
    mt = cuda.local.array(624, dtype=uint32)
    _derive(seeds[i], h)
    _init_mt(h, mt)
    for j in range(8):
        digest_words[i,j] = h[j]
    for j in range(64):
        raw_words[i,j] = _early_word(mt, j)
    for pool in range(2,17):
        components = 2 if pool == 2 else 3
        p = _sample_index(mt,pool,components)
        failure = p < 0
        for component in range(components):
            for harmonic in range(3):
                if p < 0 or p+1 >= MAX_EARLY_WORDS:
                    failure = True
                    phases[i,pool-2,component*3+harmonic] = math.nan
                else:
                    phases[i,pool-2,component*3+harmonic] = _phase(mt,p)
                    p += 2
            p += 6 # Three amplitude random() calls between components.
        overflow[i,pool-2] = 1 if failure else 0


@cuda.jit
def first_phase_batch(seeds, phases, overflow):
    i = cuda.grid(1)
    if i >= seeds.size:
        return
    h = cuda.local.array(8, dtype=uint32)
    mt = cuda.local.array(624, dtype=uint32)
    _derive(seeds[i],h)
    _init_mt(h,mt)
    for pool in range(3,17):
        p = _sample_index(mt,pool,3)
        if p < 0 or p+1 >= MAX_EARLY_WORDS:
            phases[i,pool-3] = math.nan
            overflow[i,pool-3] = 1
        else:
            phases[i,pool-3] = _phase(mt,p)
            overflow[i,pool-3] = 0


def cpu_expected(seed, pool):
    digest = hashlib.sha256(f"{int(seed)}:v4.catalog".encode()).digest()
    derived = int.from_bytes(digest[:16],"big")
    rng = random.Random(derived)
    words = [rng.getrandbits(32) for _ in range(64)]
    rng = random.Random(derived)
    components = min(pool,3)
    rng.sample(range(pool),components)
    phases = []
    for _ in range(components):
        phases.extend(rng.uniform(0,TWO_PI) for _ in range(3))
        for _ in range(3):
            rng.random()
    return np.frombuffer(digest,dtype='>u4').astype(np.uint32),words,phases


def run(out, *, controls=256, max_batch=32768):
    if not 1 <= controls <= 1024 or not 1 <= max_batch <= 32768:
        raise ValueError("restricted pilot limits: controls<=1024, max_batch<=32768")
    rng = random.Random(20261003)
    seed_values = [0,1,5021,20261001,2**32-1]
    seed_values += [rng.randrange(2**32) for _ in range(max(0,controls-len(seed_values)))]
    seeds = np.asarray(seed_values,dtype=np.uint64)
    n = len(seeds)
    ds = cuda.to_device(seeds)
    digests = cuda.device_array((n,8),dtype=np.uint32)
    words = cuda.device_array((n,64),dtype=np.uint32)
    phases = cuda.device_array((n,15,9),dtype=np.float64)
    overflow = cuda.device_array((n,15),dtype=np.uint8)
    started = time.perf_counter()
    positive_control[(n+63)//64,64](ds,digests,words,phases,overflow)
    cuda.synchronize()
    compile_control_seconds = time.perf_counter()-started
    digests,words,phases,overflow = [x.copy_to_host() for x in (digests,words,phases,overflow)]
    digest_mismatch = mt_mismatch = phase_mismatch = 0
    phase_error = 0.
    for i,seed in enumerate(seed_values):
        for pool in range(2,17):
            expected_digest,expected_words,expected_phases = cpu_expected(seed,pool)
            if pool == 2:
                digest_mismatch += int(not np.array_equal(digests[i],expected_digest))
                mt_mismatch += int(not np.array_equal(words[i],expected_words))
            actual = phases[i,pool-2,:len(expected_phases)]
            delta = float(np.max(np.abs(actual-np.asarray(expected_phases))))
            phase_error = max(phase_error,delta)
            phase_mismatch += int(delta > 2e-14 or not np.isfinite(delta))
    if digest_mismatch or mt_mismatch or phase_mismatch or np.any(overflow):
        raise AssertionError({'digest_mismatch':digest_mismatch,'mt_mismatch':mt_mismatch,
                              'phase_mismatch':phase_mismatch,'max_phase_error':phase_error,
                              'overflow':int(overflow.sum())})
    # Per-run seed list is public synthetic data, not task-card candidates.
    result = {'schema':'public-seed-cuda-throughput-v1','scope':'positive controls and small synthetic batches only',
              'python':sys.version,'device':str(cuda.get_current_device()),
              'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'controls':{'count':n,'known_demo_seed':5021,'pool_range':[2,16],
                          'sha256_full_digest_mismatches':digest_mismatch,'mt_first64_mismatches':mt_mismatch,
                          'all_component_phase_mismatches':phase_mismatch,'max_phase_error_rad':phase_error,
                          'overflow_count':int(overflow.sum()),'cold_compile_control_seconds':compile_control_seconds},
              'benchmarks':[]}
    if out:
        Path(out).write_text(json.dumps(result,indent=2)+'\n')
    for batch in (256,1024,4096,16384,32768):
        if batch > max_batch:
            break
        candidates = np.asarray([rng.randrange(2**32) for _ in range(batch)],dtype=np.uint64)
        d_candidates = cuda.to_device(candidates)
        d_phases = cuda.device_array((batch,14),dtype=np.float64)
        d_overflow = cuda.device_array((batch,14),dtype=np.uint8)
        # Compile with a one-thread batch; compilation does not run a long kernel.
        first_phase_batch[1,64](d_candidates[:1],d_phases[:1],d_overflow[:1])
        cuda.synchronize()
        trials = []
        gpu_trials = []
        for _ in range(5):
            begin_event, end_event = cuda.event(timing=True), cuda.event(timing=True)
            start = time.perf_counter()
            begin_event.record()
            first_phase_batch[(batch+63)//64,64](d_candidates,d_phases,d_overflow)
            end_event.record()
            end_event.synchronize()
            trials.append(time.perf_counter()-start)
            gpu_trials.append(begin_event.elapsed_time(end_event) / 1000)
        elapsed = statistics.median(trials)
        overflow_count = int(d_overflow.copy_to_host().sum())
        actual = d_phases.copy_to_host()
        if not np.all(np.isfinite(actual) & (actual >= 0) & (actual < TWO_PI)):
            raise AssertionError('invalid or unwritten phase outputs')
        check_count = min(batch,32)
        for i in np.linspace(0,batch-1,check_count,dtype=int):
            for pool in range(3,17):
                expected = cpu_expected(int(candidates[i]),pool)[2][0]
                if abs(actual[i,pool-3]-expected)>2e-14:
                    raise AssertionError('throughput kernel differs from control kernel')
        record = {'batch':batch,'pools_per_seed':14,'elapsed_seconds':elapsed,
                  'trial_seconds':trials,'min_seconds':min(trials),'max_seconds':max(trials),
                  'gpu_event_seconds':gpu_trials,'gpu_event_median_seconds':statistics.median(gpu_trials),
                  'seeds_per_second':batch/elapsed,'pool_checks_per_second':batch*14/elapsed,
                  'projected_32bit_seconds':2**32/(batch/elapsed),'overflow_count':overflow_count,
                  'cpu_checked_seed_count':check_count}
        result['benchmarks'].append(record)
        print(json.dumps(record),flush=True)
        if out:
            Path(out).write_text(json.dumps(result,indent=2)+'\n')
        # Stop before trying a batch that might occupy the GPU for over one second.
        if elapsed > .20:
            break
    def resource(value):
        return {str(k):int(v) for k,v in value.items()} if isinstance(value,dict) else int(value)
    result['cuda_kernel_resources'] = {
        'registers_per_thread':resource(first_phase_batch.get_regs_per_thread()),
        'local_bytes_per_thread':resource(first_phase_batch.get_local_mem_per_thread()),
        'shared_bytes_per_block':resource(first_phase_batch.get_shared_mem_per_block()),
    }
    result['limitations'] = ['32-bit master range is an assumption, not public generator entropy',
                            'throughput extrapolation excludes match filtering, CPU full-signature validation and contention',
                            'center pools beyond 16 or generator consumption changes are untested',
                            'at 227 consumed MT words, flagged candidates require exact CPU fallback',
                            'CUDA helper contains no task-card fingerprints and does not scan them']
    if out:
        Path(out).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'controls':result['controls'],'cuda_kernel_resources':result['cuda_kernel_resources']}),flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',default='gpu_seed_throughput_result.json')
    parser.add_argument('--controls',type=int,default=256)
    parser.add_argument('--max-batch',type=int,default=32768)
    args = parser.parse_args()
    run(args.out,controls=args.controls,max_batch=args.max_batch)
