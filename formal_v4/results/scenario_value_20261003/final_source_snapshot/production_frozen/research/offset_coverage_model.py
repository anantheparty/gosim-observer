"""CPU proof pilot: RNG word offsets for every Python sample(n,3) pool size.

For n<=21 Python uses the shrinking-pool branch. For n>21, it accepts the
first three distinct k-bit words below n. Third-smallest prefix thresholds
give all feasible finish offsets without enumerating billions of pool sizes.
No GPU, card matching, or unknown seed scan is performed here.
"""
from __future__ import annotations

import hashlib
import random


def derived_seed(seed,hashed=True):
    return int.from_bytes(hashlib.sha256(f"{int(seed)}:v4.catalog".encode()).digest()[:16],'big') if hashed else int(seed)


def possible_offsets(seed,*,hashed=True,max_words=227,max_pool_bits=32):
    """All sample(3) offsets for n=3..2**max_pool_bits-1, subject to max_words.

    Returns exact offset/witness intervals and unfinished pool bands. If a band
    is unfinished, the prefix is insufficient; it is not a no-match certificate.
    An overflow can be continued with more CPython MT words on the CPU.
    """
    key = derived_seed(seed,hashed)
    rng = random.Random(key)
    words = [rng.getrandbits(32) for _ in range(max_words)]
    witnesses,unfinished = [],[]
    for n in range(3,min(21,2**max_pool_bits-1)+1):
        p = 0
        failure = False
        for i in range(3):
            bits = (n-i).bit_length()
            while True:
                if p>=len(words):
                    failure = True
                    break
                v = words[p]>>(32-bits)
                p += 1
                if v<n-i:
                    break
            if failure:
                break
        if failure:
            unfinished.append({'branch':'pool','pool_min':n,'pool_max':n})
        else:
            witnesses.append({'offset_words':p,'branch':'pool','pool_min':n,'pool_max':n})
    for bits in range(5,max_pool_bits+1):
        lo,hi = max(22,1<<(bits-1)),(1<<bits)-1
        if lo>hi:
            continue
        if bits>32:
            raise ValueError('this proof pilot models one MT word per randbelow attempt (pool_bits<=32)')
        best = [1<<32]*3
        for position,word in enumerate(words,1):
            old = best[2]
            v = word>>(32-bits)
            if v not in best and v<best[2]:
                best = sorted(best+[v])[:3]
            if best[2]<old:
                a,b = max(lo,best[2]+1),min(hi,old)
                if a<=b:
                    witnesses.append({'offset_words':position,'branch':'selected_set',
                                      'pool_bits':bits,'pool_min':a,'pool_max':b})
            if best[2]<lo:
                break
        if best[2]>=lo:
            unfinished.append({'branch':'selected_set','pool_bits':bits,
                               'pool_min':lo,'pool_max':min(hi,best[2])})
    return {'offsets':sorted({row['offset_words'] for row in witnesses}),
            'witness_intervals':witnesses,'unfinished_pool_bands':unfinished,
            'max_words':max_words,'pool_range':[3,(1<<max_pool_bits)-1]}


class CountingRandom(random.Random):
    def __init__(self,seed):
        self.words = 0
        super().__init__(seed)

    def getrandbits(self,k):
        self.words += (k+31)//32
        return super().getrandbits(k)


def check(seed,*,hashed=True,max_pool_bits=32):
    evidence = possible_offsets(seed,hashed=hashed,max_pool_bits=max_pool_bits)
    values = set(range(3,2049))
    for row in evidence['witness_intervals']:
        values.update((row['pool_min'],row['pool_max']))
    comparisons = 0
    for n in sorted(values):
        if n>=(1<<max_pool_bits):
            continue
        rng = CountingRandom(derived_seed(seed,hashed))
        rng.sample(range(n),3)
        predicted = {row['offset_words'] for row in evidence['witness_intervals']
                     if row['pool_min']<=n<=row['pool_max']}
        if predicted!={rng.words}:
            raise AssertionError({'seed':seed,'pool':n,'expected':rng.words,'predicted':predicted})
        comparisons += 1
    return {**evidence,'python_comparisons':comparisons,'sampled_offset_max':max(evidence['offsets'])}


if __name__=='__main__':
    import json,time
    rng = random.Random(20261003)
    seeds = [0,1,5021,2**32-1]+[rng.randrange(2**32) for _ in range(36)]
    begin = time.perf_counter()
    checks = [check(seed) for seed in seeds]
    result = {'public_synthetic_seed_count':len(seeds),
              'pool_size_comparisons':sum(c['python_comparisons'] for c in checks),
              'all_exact':True,'unfinished_bands':sum(len(c['unfinished_pool_bands']) for c in checks),
              'mean_offset_count':sum(len(c['offsets']) for c in checks)/len(checks),
              'max_offset_count':max(len(c['offsets']) for c in checks),
              'max_consumed_offset':max(c['sampled_offset_max'] for c in checks),
              'elapsed_seconds':time.perf_counter()-begin}
    print(json.dumps(result))
