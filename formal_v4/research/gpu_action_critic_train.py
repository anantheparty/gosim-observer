#!/usr/bin/env python3
"""Owned-CUDA action critic from fixed-continuation terminal interventions.

The teacher, not the NN, computes official final-score counterfactuals. Features
are public/revealed state. L1/L2 fit; L3 selects a checkpoint; L4 is never fitted
or used for selection. Exported prediction is RAW terminal score advantage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def numpy_predict(x, model):
    x = np.asarray((x - model['xmean']) / model['xscale'], dtype=np.float32)
    h = np.maximum(0, np.einsum('ij,jk->ik', x, model['w1'], optimize=False) + model['b1'])
    z = np.einsum('ij,j->i', h, model['w2'], optimize=False) + model['b2']
    return z * model['yscale'] + model['ymean']


def ranking_metrics(pred, target, groups):
    regrets, correct, gains = [], [], []
    for group in np.unique(groups):
        ix = np.flatnonzero(groups == group)
        selected = int(ix[np.argmax(pred[ix])])
        optimal = float(target[ix].max())
        regret = optimal - float(target[selected])
        regrets.append(regret)
        correct.append(regret <= 1e-6)
        gains.append(float(target[selected]))
    return {'states': len(regrets), 'mean_terminal_regret': float(np.mean(regrets)),
            'median_terminal_regret': float(np.median(regrets)),
            'p90_terminal_regret': float(np.quantile(regrets, .9)),
            'optimal_state_fraction': float(np.mean(correct)),
            'selected_mean_terminal_delta': float(np.mean(gains)),
            'raw_delta_MSE': float(np.mean((pred - target) ** 2))}


def power_snapshot():
    try:
        p = subprocess.run(['nvidia-smi', '--query-gpu=name,power.draw,power.limit,memory.used,utilization.gpu',
                            '--format=csv,noheader'], capture_output=True, text=True, timeout=3)
        return {'returncode': p.returncode, 'value': p.stdout.strip()}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'unavailable': type(e).__name__}


def train(directory, steps=6000, batch=512, width=64):
    from numba import cuda

    directory = Path(directory)
    data = np.load(directory / 'dataset.npz')
    x = np.asarray(data['x'], dtype=np.float32)
    # Teacher stores score advantage per occupied second. Learning/ranking uses
    # actual final-score advantage: duration is a feature, never a post hoc bias.
    raw = np.asarray(data['y'] * data['duration_seconds'], dtype=np.float32)
    cards = data['card']
    group = data['group']
    training = cards < 2
    validation = cards == 2
    assert training.any() and validation.any() and batch % 32 == 0
    assert np.isfinite(x).all() and np.isfinite(raw).all()
    assert all(len(np.unique(cards[group == g])) == 1 for g in np.unique(group))
    # Neither test labels nor test features influence preprocessing.
    mean = x[training].mean(axis=0)
    scale = np.maximum(x[training].std(axis=0), .01)
    ymean = float(raw[training].mean())
    yscale = max(float(raw[training].std()), .1)
    xx = np.ascontiguousarray((x - mean) / scale, dtype=np.float32)
    yy = np.asarray((raw - ymean) / yscale, dtype=np.float32)
    train_groups = np.unique(group[training])
    members = {int(g): np.flatnonzero(training & (group == g)).astype(np.int32) for g in train_groups}
    rng = np.random.default_rng(261003)
    features = x.shape[1]
    w1 = np.asarray(rng.normal(0, math.sqrt(2 / features), (features + 1, width)), np.float32)
    w1[-1] = 0
    w2 = np.asarray(rng.normal(0, math.sqrt(1 / width), width + 1), np.float32)
    w2[-1] = 0
    dx, dy = cuda.to_device(xx), cuda.to_device(yy)
    d1, d2 = cuda.to_device(w1), cuda.to_device(w2)
    m1, v1 = cuda.to_device(np.zeros_like(w1)), cuda.to_device(np.zeros_like(w1))
    m2, v2 = cuda.to_device(np.zeros_like(w2)), cuda.to_device(np.zeros_like(w2))
    ids = cuda.to_device(np.zeros(batch, np.int32))
    hidden = cuda.device_array((batch, width), np.float32)
    out, delta = cuda.device_array(batch, np.float32), cuda.device_array(batch, np.float32)
    dh = cuda.device_array((batch, width), np.float32)

    @cuda.jit
    def activate(x, rows, w, h):
        i, j = cuda.grid(2)
        if i < h.shape[0] and j < h.shape[1]:
            total = w[x.shape[1], j]
            for f in range(x.shape[1]):
                total += x[rows[i], f] * w[f, j]
            h[i, j] = max(0, total)

    @cuda.jit
    def predict(h, w, o):
        i = cuda.grid(1)
        if i < o.size:
            z = w[h.shape[1]]
            for j in range(h.shape[1]):
                z += h[i, j] * w[j]
            o[i] = z

    @cuda.jit
    def loss_delta(rows, y, o, delta):
        i = cuda.grid(1)
        if i < o.size:
            error = o[i] - y[rows[i]]
            paired = o[i ^ 1] - y[rows[i ^ 1]]
            # Paired rows share the same pre-action state. Huber on their value
            # difference learns ranking without treating between-state scales
            # as preference. Pair terms are counted twice, hence factor .5.
            absolute = max(-1., min(1., error))
            relative = max(-1., min(1., error - paired))
            delta[i] = (absolute + .5 * relative) / o.size

    @cuda.jit
    def hidden_delta(h, delta, w, dh):
        i, j = cuda.grid(2)
        if i < dh.shape[0] and j < dh.shape[1]:
            dh[i, j] = delta[i] * w[j] if h[i, j] > 0 else 0

    @cuda.jit
    def update1(x, rows, dh, w, m, v, step, lr):
        f, j = cuda.grid(2)
        if f < w.shape[0] and j < w.shape[1]:
            gradient = 0.
            for i in range(dh.shape[0]):
                gradient += dh[i, j] * (1 if f == x.shape[1] else x[rows[i], f])
            gradient = max(-10., min(10., gradient))
            m[f, j] = .9 * m[f, j] + .1 * gradient
            v[f, j] = .999 * v[f, j] + .001 * gradient * gradient
            w[f, j] -= lr * (m[f, j] / (1 - .9 ** step)) / (math.sqrt(v[f, j] / (1 - .999 ** step)) + 1e-8)

    @cuda.jit
    def update2(h, delta, w, m, v, step, lr):
        j = cuda.grid(1)
        if j < w.size:
            gradient = 0.
            for i in range(delta.size):
                gradient += delta[i] * (1 if j == h.shape[1] else h[i, j])
            gradient = max(-10., min(10., gradient))
            m[j] = .9 * m[j] + .1 * gradient
            v[j] = .999 * v[j] + .001 * gradient * gradient
            w[j] -= lr * (m[j] / (1 - .9 ** step)) / (math.sqrt(v[j] / (1 - .999 ** step)) + 1e-8)

    start = time.perf_counter()
    before = power_snapshot()
    history, best, best_step = [], math.inf, None
    for step in range(1, steps + 1):
        # Each pair is within one state; multiple states per batch reduce
        # correlated gradients and equal-state sampling prevents large pools
        # receiving an accidental sample-count advantage.
        selected = rng.choice(train_groups, 16)
        rows = np.concatenate([rng.choice(members[int(g)], batch // 16) for g in selected]).astype(np.int32)
        ids.copy_to_device(rows)
        activate[((batch + 15) // 16, (width + 7) // 8), (16, 8)](dx, ids, d1, hidden)
        predict[(batch + 127) // 128, 128](hidden, d2, out)
        loss_delta[(batch + 127) // 128, 128](ids, dy, out, delta)
        hidden_delta[((batch + 15) // 16, (width + 7) // 8), (16, 8)](hidden, delta, d2, dh)
        update1[((features + 8) // 8, (width + 7) // 8), (8, 8)](dx, ids, dh, d1, m1, v1, step, .001)
        update2[(width + 64) // 64, 64](hidden, delta, d2, m2, v2, step, .001)
        if step % 1000 == 0 or step == steps:
            cuda.synchronize()
            ww1, ww2 = d1.copy_to_host(), d2.copy_to_host()
            model = {'w1': ww1[:-1], 'b1': ww1[-1], 'w2': ww2[:-1], 'b2': ww2[-1],
                     'xmean': mean, 'xscale': scale, 'ymean': np.float32(ymean), 'yscale': np.float32(yscale)}
            activate[((batch + 15) // 16, (width + 7) // 8), (16, 8)](dx, ids, d1, hidden)
            predict[(batch + 127) // 128, 128](hidden, d2, out)
            error = float(np.max(np.abs(out.copy_to_host() * yscale + ymean - numpy_predict(x[rows], model))))
            if error > max(1e-4, yscale * 2e-5):
                raise AssertionError(('CUDA_CPU_raw_delta_forward_error', error))
            val = numpy_predict(x[validation], model)
            metrics = ranking_metrics(val, raw[validation], group[validation])
            record = {'step': step, 'elapsed_seconds': time.perf_counter() - start,
                      'CUDA_CPU_forward_max_error': error, 'validation': metrics}
            history.append(record)
            if metrics['mean_terminal_regret'] < best:
                best, best_step = metrics['mean_terminal_regret'], step
                np.savez_compressed(directory / 'model.npz', **model)
            record['selected_checkpoint_step'] = best_step
            progress = {'status': 'complete' if step == steps else 'running', 'seed': 261003,
                        'device': str(cuda.get_current_device().name), 'width': width, 'steps': steps, 'batch': batch,
                        'training_rows': int(training.sum()), 'validation_rows': int(validation.sum()),
                        'training_states': len(train_groups), 'validation_states': len(np.unique(group[validation])),
                        'target_kind': 'raw_terminal_delta', 'selection': 'minimum L3 mean within-state terminal regret',
                        'L4_used_for_fit_or_selection': False,
                        'objective': 'standardized raw delta Huber plus 0.25 within-state pair difference Huber',
                        'selected_checkpoint_step': best_step, 'history': history, 'power_before': before,
                        'power_latest': power_snapshot(), 'elapsed_seconds': time.perf_counter() - start,
                        'dataset_sha256': sha(directory / 'dataset.npz'), 'source_sha256': sha(__file__)}
            (directory / 'training.json').write_text(json.dumps(progress, indent=2) + '\n')
            print(json.dumps(record), flush=True)
if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('directory')
    p.add_argument('--steps', type=int, default=6000)
    p.add_argument('--batch', type=int, default=512)
    p.add_argument('--width', type=int, default=64)
    a = p.parse_args()
    train(a.directory, a.steps, a.batch, a.width)
