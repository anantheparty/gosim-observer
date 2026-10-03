#!/usr/bin/env python3
"""Independent GPU boosted-tree control for the action-critic feature/teacher.

Three declared depths test whether threshold tables fit this teacher better than
a ReLU model. Only L1/L2 fit and L3 selects; no L4 evaluation. CPU deployment can
use the exported JSON arrays without the training library.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np


def predict_trees(x, model):
    result = np.full(len(x), model['base_score'], np.float32)
    for tree in model['trees']:
        nodes = np.zeros(len(x), np.int32)
        active = np.ones(len(x), bool)
        while active.any():
            rows = np.flatnonzero(active)
            current = nodes[rows]
            left = tree['left'][current]
            leaves = left < 0
            result[rows[leaves]] += tree['value'][current[leaves]]
            active[rows[leaves]] = False
            rows = rows[~leaves]
            current = current[~leaves]
            if len(rows):
                f = tree['feature'][current]
                take_left = x[rows, f] < tree['value'][current]
                nodes[rows] = np.where(take_left, tree['left'][current], tree['right'][current])
    return result


def export_trees(booster, features):
    config = json.loads(booster.save_config())
    base = config['learner']['learner_model_param']['base_score']
    base = float(json.loads(base)[0] if base.startswith('[') else base)
    trees = []
    for raw in booster.get_dump(dump_format='json'):
        root = json.loads(raw)
        pending, nodes = [root], {}
        while pending:
            node = pending.pop()
            nodes[node['nodeid']] = node
            pending.extend(node.get('children', []))
        size = max(nodes) + 1
        left = np.full(size, -1, np.int32)
        right = np.full(size, -1, np.int32)
        feature = np.zeros(size, np.int32)
        value = np.zeros(size, np.float32)
        for i, node in nodes.items():
            if 'leaf' in node:
                value[i] = node['leaf']
            else:
                left[i], right[i] = node['yes'], node['no']
                name = node['split']
                feature[i] = int(name[1:]) if name.startswith('f') else features.index(name)
                value[i] = node['split_condition']
        trees.append({'left': left, 'right': right, 'feature': feature, 'value': value})
    return {'base_score': base, 'trees': trees}


def metrics(pred, y, group):
    regrets, chosen = [], []
    for g in np.unique(group):
        ix = np.flatnonzero(group == g)
        chosen.append(float(y[ix[np.argmax(pred[ix])]]))
        regrets.append(float(y[ix].max()) - chosen[-1])
    return {'states': len(chosen), 'mean_terminal_regret': float(np.mean(regrets)),
            'selected_mean_delta': float(np.mean(chosen)), 'delta_MSE': float(np.mean((pred - y) ** 2))}


def main(directory, site):
    if site:
        sys.path.insert(0, site)
    import xgboost as xgb

    directory = Path(directory)
    d = np.load(directory / 'dataset.npz')
    x = np.asarray(d['x'], np.float32)
    y = np.asarray(d['y'] * d['duration_seconds'], np.float32)
    fit, val = d['card'] < 2, d['card'] == 2
    assert fit.any() and val.any()
    train = xgb.DMatrix(x[fit], label=y[fit])
    validation = xgb.DMatrix(x[val], label=y[val])
    features = [f'f{i}' for i in range(x.shape[1])]
    start = time.perf_counter()
    history, best = [], float('inf')
    for depth in (2, 4, 6):
        params = {'device': 'cuda', 'tree_method': 'hist', 'objective': 'reg:squarederror',
                  'max_depth': depth, 'eta': .04, 'min_child_weight': 8, 'seed': 261003,
                  'subsample': 1., 'colsample_bytree': 1., 'nthread': 2}
        begin = time.perf_counter()
        booster = xgb.train(params, train, num_boost_round=600)
        selected_config = json.loads(booster.save_config())
        assert selected_config['learner']['generic_param']['device'].startswith('cuda')
        pred = booster.predict(validation)
        result = metrics(pred, y[val], d['group'][val])
        model = export_trees(booster, features)
        native = predict_trees(x[val], model)
        error = float(np.max(np.abs(pred - native)))
        if error > 5e-4:
            raise AssertionError(('JSON CPU GPU prediction', error))
        record = {'depth': depth, 'rounds': 600, 'seconds': time.perf_counter() - begin,
                  'validation': result, 'CPU_export_forward_max_error': error}
        history.append(record)
        print(json.dumps(record), flush=True)
        if result['mean_terminal_regret'] < best:
            best = result['mean_terminal_regret']
            booster.save_model(directory / 'tree_model.ubj')
            serial = {'base_score': model['base_score'],
                      'trees': [{k: v.tolist() for k, v in t.items()} for t in model['trees']]}
            (directory / 'tree_model.json').write_text(json.dumps(serial, separators=(',', ':')))
            selected = depth
    # Zero-advantage trace choice is an explicit conditional teacher comparator.
    baseline = metrics(np.where(np.abs(y[val]) < 1e-5, 1., 0.), y[val], d['group'][val])
    summary = {'status': 'complete', 'xgboost_version': xgb.__version__, 'device': 'cuda',
               'target': 'raw_terminal_delta', 'training_cards': ['L1', 'L2'], 'selection_card': 'L3',
               'L4_used': False, 'declared_depths': [2, 4, 6], 'rounds_each': 600,
               'selected_depth': selected, 'history': history, 'zero_delta_teacher_comparator': baseline,
               'seconds': time.perf_counter() - start,
               'dataset_sha256': hashlib.sha256((directory / 'dataset.npz').read_bytes()).hexdigest(),
               'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'adoption_gate': 'must beat actual public-policy baseline in complete heldout season; conditional metric alone insufficient'}
    (directory / 'tree_training.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('directory')
    p.add_argument('--site')
    a = p.parse_args()
    main(a.directory, a.site)
