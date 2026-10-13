#!/usr/bin/env python3
"""Bit-for-bit equivalence of the Rust kernel (kern_rs, libkern.so) and the C kernel (agent/kern.c) on random
inputs shaped like the agent's calls, plus a speed comparison on one large case.

usage: python3 test_equiv.py [TRIALS] [SEED]      (build first: cargo build --release)
Exit code 0 only if every output of every call is identical (floats compared as raw bits)."""
import ctypes, math, sys, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
C_LIB = HERE.parent / 'agent' / 'libkern_linux_x86_64.so'
R_LIB = HERE / 'target' / 'release' / 'libkern.so'
P, I, D = ctypes.c_void_p, ctypes.c_int, ctypes.c_double


def load(path):
    lib = ctypes.CDLL(str(path))
    lib.eval_centers.argtypes = [I, P, P, I, P, I, P, P, I, D, D, D, P, P, P, P]
    lib.assign_center.argtypes = [D, D, I, P, I, P, I, D, D, D, I, I, P, P]
    lib.offset_consistency.argtypes = [I, P, P, D, D, I, P, P, P, I, D, P]
    lib.eval_groups.argtypes = [I, P, P, P, P, P, I, P, I, P, P, I, D, D, D, D, P, P, D, P, P, P, P]
    for f in (lib.eval_centers, lib.assign_center, lib.offset_consistency, lib.eval_groups):
        f.restype = None
    return lib


def ptr(a):
    return a.ctypes.data if a is not None else None


def horizon(alt, az):
    a, z = np.radians(alt), np.radians(az)
    return np.ascontiguousarray(np.stack([np.cos(a) * np.cos(z), np.cos(a) * np.sin(z), np.sin(a)], axis=-1))


def same(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if a.dtype == np.float64:
        return a.shape == b.shape and np.array_equal(a.view(np.uint64), b.view(np.uint64))
    return np.array_equal(a, b)


def case(rng):
    """One random field: geometry, target pool, value table and candidate centres."""
    side = int(rng.choice([1, 2, 3, 4, 5, 7, 10, 12]))
    pitch = float(rng.uniform(0.05, 0.6))
    half = side * pitch / 2.0
    calt0 = float(rng.choice([rng.uniform(15, 85), rng.uniform(85, 89.999), 90.0 - 1e-9]))
    caz0 = float(rng.choice([rng.uniform(0, 360), 0.0, 359.9999, 180.0]))
    np_ = int(rng.choice([0, 1, 7, 60, 400, 2500]))
    spread = half * float(rng.uniform(0.6, 1.6))
    alt = np.clip(calt0 + rng.uniform(-spread, spread, np_), -5, 90)
    az = (caz0 + rng.uniform(-spread, spread, np_) / max(math.cos(math.radians(min(calt0, 89.0))), 0.02)) % 360
    tv = horizon(alt, az)
    if np_ and rng.random() < 0.3:                      # some targets far away
        k = rng.integers(0, np_, max(1, np_ // 5))
        tv[k] = horizon(rng.uniform(-30, 90, len(k)), rng.uniform(0, 360, len(k)))
    nt = 20
    tgrid = np.ascontiguousarray(np.geomspace(60, 3600, nt))
    val = rng.uniform(0, 40, (np_, nt, 3)).astype(np.float32)
    if rng.random() < 0.5:                               # coarse values: many exact ties
        val = (np.round(val * 2) / 2).astype(np.float32)
    val[rng.random(val.shape) < 0.15] = 0.0
    val[rng.random(val.shape) < 0.10] = -np.inf
    val = np.ascontiguousarray(val)
    cos_r = math.cos(math.radians(half * math.sqrt(2) * float(rng.uniform(0.9, 1.3))))
    margin_min = float(rng.choice([-1e9, 0.0, 0.003 * pitch, 0.02 * pitch, 0.12 * pitch]))
    nc = int(rng.choice([0, 1, 9, 120]))
    calt = np.ascontiguousarray(np.clip(calt0 + rng.uniform(-half, half, nc), 0, 90))
    caz = np.ascontiguousarray((caz0 + rng.uniform(-half, half, nc)) % 360)
    return dict(side=side, pitch=pitch, tv=tv, val=val, tgrid=tgrid, cos_r=cos_r, margin_min=margin_min,
                calt=calt, caz=caz, nt=nt)


def run_eval_centers(lib, c):
    nc = len(c['calt'])
    out = [np.zeros(nc), np.zeros(nc, np.int32), np.zeros(nc, np.int32), np.zeros(nc)]
    lib.eval_centers(nc, ptr(c['calt']), ptr(c['caz']), len(c['tv']), ptr(c['tv']), c['nt'], ptr(c['val']),
                     ptr(c['tgrid']), c['side'], c['pitch'], c['margin_min'], c['cos_r'], *[ptr(o) for o in out])
    return out


def run_assign(lib, c, k, t, p):
    F = c['side'] ** 2
    out = [np.zeros(F, np.int32), np.zeros(F)]
    lib.assign_center(float(c['calt'][k]), float(c['caz'][k]), len(c['tv']), ptr(c['tv']), c['nt'], ptr(c['val']),
                      c['side'], c['pitch'], c['margin_min'], c['cos_r'], int(t), int(p), *[ptr(o) for o in out])
    return out


def run_offsets(lib, c, rng):
    no = int(rng.choice([1, 25, 169]))
    oalt = np.ascontiguousarray(rng.uniform(-0.6, 0.6, no))
    oaz = np.ascontiguousarray(rng.uniform(-0.6, 0.6, no))
    na = len(c['tv'])
    fib = np.ascontiguousarray(rng.integers(-1, c['side'] ** 2, na).astype(np.int32))
    hit = np.ascontiguousarray(rng.integers(0, 2, na).astype(np.int32))
    calt = float(c['calt'][0]) if len(c['calt']) else 45.0
    caz = float(c['caz'][0]) if len(c['caz']) else 10.0
    return no, oalt, oaz, calt, caz, fib, hit


def run_groups(lib, c, groups, use_z):
    tv, nc = c['tv'], len(c['calt'])
    ng = len(groups['gstart'])
    out = [np.zeros(nc), np.zeros(nc, np.int32), np.zeros(nc, np.int32), np.zeros(nc)]
    zo = groups['zo'] if use_z else None
    zs = groups['zs'] if use_z else None
    lib.eval_groups(ng, ptr(groups['gstart']), ptr(groups['gend']), ptr(groups['gu']), ptr(c['calt']), ptr(c['caz']),
                    len(tv), ptr(tv), c['nt'], ptr(c['val']), ptr(c['tgrid']), c['side'], c['pitch'], c['margin_min'],
                    c['cos_r'], groups['cos_sub'], ptr(zo), ptr(zs), groups['th_sub'], *[ptr(o) for o in out])
    return out


def make_groups(c, rng):
    nc = len(c['calt'])
    cuts = np.sort(rng.integers(0, nc + 1, int(rng.integers(1, 6)))) if nc else np.array([], int)
    edges = np.unique(np.concatenate([[0], cuts, [nc]]))
    gstart = np.ascontiguousarray(edges[:-1].astype(np.int32))
    gend = np.ascontiguousarray(edges[1:].astype(np.int32))
    gu = np.ascontiguousarray(horizon(c['calt'][gstart], c['caz'][gstart]) if len(gstart) else np.zeros((0, 3)))
    th = math.radians(float(rng.uniform(0.5, 6.0)))
    z = c['tv'][:, 2] if len(c['tv']) else np.zeros(0)
    zo = np.ascontiguousarray(np.argsort(z, kind='stable').astype(np.int32))
    zs = np.ascontiguousarray(z[zo])
    return dict(gstart=gstart, gend=gend, gu=gu, cos_sub=math.cos(th), th_sub=th, zo=zo, zs=zs)


def main():
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 20261013
    rng = np.random.default_rng(seed)
    C, R = load(C_LIB), load(R_LIB)
    n = {'eval_centers': 0, 'assign_center': 0, 'offset_consistency': 0, 'eval_groups': 0, 'centres': 0, 'cells': 0}
    bad = []
    for i in range(trials):
        c = case(rng)
        a, b = run_eval_centers(C, c), run_eval_centers(R, c)
        n['eval_centers'] += 1; n['centres'] += len(c['calt'])
        if not all(same(x, y) for x, y in zip(a, b)):
            bad.append(('eval_centers', i))
        for k in range(min(3, len(c['calt']))):
            t, p = (int(a[1][k]), int(a[2][k])) if rng.random() < 0.7 else (int(rng.integers(0, c['nt'])), int(rng.integers(0, 3)))
            x, y = run_assign(C, c, k, t, p), run_assign(R, c, k, t, p)
            n['assign_center'] += 1; n['cells'] += c['side'] ** 2
            if not all(same(u, v) for u, v in zip(x, y)):
                bad.append(('assign_center', i, k))
        no, oalt, oaz, calt, caz, fib, hit = run_offsets(None, c, rng)
        outs = []
        for lib in (C, R):
            o = np.zeros(no, np.int32)
            lib.offset_consistency(no, ptr(oalt), ptr(oaz), calt, caz, len(c['tv']), ptr(c['tv']), ptr(fib), ptr(hit),
                                   c['side'], c['pitch'], ptr(o))
            outs.append(o)
        n['offset_consistency'] += 1
        if not same(*outs):
            bad.append(('offset_consistency', i))
        g = make_groups(c, rng)
        for use_z in (False, True):
            x, y = run_groups(C, c, g, use_z), run_groups(R, c, g, use_z)
            n['eval_groups'] += 1
            if not all(same(u, v) for u, v in zip(x, y)):
                bad.append(('eval_groups', i, use_z))
            # eval_groups must also agree with eval_centers on each group's neighbourhood (C semantics)
    print('calls compared:', n)
    print('mismatches:', len(bad), bad[:10])

    # speed on one large case, roughly the agent's biggest search step
    rng = np.random.default_rng(7)
    side, pitch = 10, 0.22
    calt0, caz0, half = 60.0, 140.0, 1.1
    alt = calt0 + rng.uniform(-4, 4, 20000)
    az = caz0 + rng.uniform(-8, 8, 20000)
    tv = horizon(alt, az)
    val = np.ascontiguousarray(rng.uniform(0, 40, (20000, 20, 3)).astype(np.float32))
    big = dict(side=side, pitch=pitch, tv=tv, val=val, tgrid=np.ascontiguousarray(np.geomspace(60, 3600, 20)),
               cos_r=math.cos(math.radians(half * 1.5)), margin_min=0.003 * pitch,
               calt=np.ascontiguousarray(calt0 + rng.uniform(-3, 3, 400)), caz=np.ascontiguousarray(caz0 + rng.uniform(-6, 6, 400)), nt=20)
    gb = make_groups(big, rng)
    for name, lib in (('C   ', C), ('Rust', R)):
        best = 1e9
        for _ in range(5):
            t0 = time.perf_counter(); run_groups(lib, big, gb, True); best = min(best, time.perf_counter() - t0)
        print('%s eval_groups 400 centres x 20000 targets: %.1f ms (best of 5)' % (name, best * 1e3))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
