#!/usr/bin/env python3
"""Grouped validation of nonlinear order proxies on public practice traces.

The proxies only rank candidate first-visit orders. They do not replace the
exact fixed-order dynamic program or the official local scorer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.stats import pearsonr, spearmanr
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor

from surrogate_order_search import load_traces, order_features, TILE_INDEX


def encode(orders):
    n = len(orders)
    seq = np.array([[TILE_INDEX[t] for t in order] for order in orders], dtype=np.int16)
    ranks = np.empty((n, 64), dtype=np.int16)
    ranks[np.arange(n)[:, None], seq] = np.arange(64, dtype=np.int16)
    spline = sparse.csr_matrix(order_features(orders)[:, :-1], dtype=np.float64)
    ia, ib = np.triu_indices(64, k=1)
    precedence = sparse.csr_matrix((ranks[:, ia] < ranks[:, ib]).astype(np.float64))
    rows = np.repeat(np.arange(n), 63)
    adjacency = sparse.csr_matrix(
        (np.ones(n * 63, np.float64),
         (rows, (seq[:, :-1] * 64 + seq[:, 1:]).ravel())),
        shape=(n, 64 * 64),
    )
    pair = sparse.hstack([spline, precedence * 0.25, adjacency * 2.0], format="csr")
    return ranks, spline, pair


def statistics(y, p):
    if len(y) < 3 or np.std(y) < 1e-9 or np.std(p) < 1e-9:
        return {"n": len(y), "pearson": None, "spearman": None, "mae": float(np.mean(abs(y-p)))}
    return {
        "n": len(y),
        "pearson": float(pearsonr(y, p).statistic),
        "spearman": float(spearmanr(y, p).statistic),
        "mae": float(np.mean(np.abs(y-p))),
        "top10_true_mean": float(y[np.argsort(-p)[:min(10,len(y))]].mean()),
        "best_true": float(y.max()),
    }


def fit_predict(name, x_train, y_train, x_test):
    if name == "ridge_pair":
        model = Ridge(alpha=300.0, solver="lsqr", tol=1e-5, fit_intercept=False)
    elif name == "ridge_spline":
        model = Ridge(alpha=200.0, solver="lsqr", tol=1e-5, fit_intercept=False)
    elif name == "gbdt_rank":
        model = HistGradientBoostingRegressor(
            max_iter=350, learning_rate=.05, max_leaf_nodes=15,
            min_samples_leaf=30, l2_regularization=20.0,
            max_depth=6, early_stopping=False, random_state=29462026,
        )
    else:
        raise ValueError(name)
    if name.startswith("ridge_"):
        center = float(np.mean(y_train))
        model.fit(x_train, y_train-center)
        return model.predict(x_test)+center
    model.fit(x_train, y_train)
    return model.predict(x_test)


def local_crossfit(global_pair, global_y, local_pair, local_ranks,
                   local_y, local_seed):
    """Assess whether 40 local exact scores can calibrate a new neighborhood."""
    global_prediction = fit_predict("ridge_pair", global_pair, global_y, local_pair)
    footrule = np.abs(local_ranks[:, None, :] - local_ranks[None, :, :]).sum(axis=2)
    positive = footrule[footrule > 0]
    width = float(np.median(positive))
    kernel = np.exp(-footrule / width)
    weighted = np.empty(len(local_y), np.float64)
    radial = np.empty(len(local_y), np.float64)
    for fold in range(3):
        train = local_seed % 3 != fold
        test = ~train
        x_joint = sparse.vstack((global_pair, local_pair[train]), format="csr")
        y_joint = np.concatenate((global_y, local_y[train]))
        weights = np.concatenate((np.ones(len(global_y)),
                                  np.full(int(train.sum()), 20.0)))
        center_joint = float(np.average(y_joint, weights=weights))
        model = Ridge(alpha=300.0, solver="lsqr", tol=1e-5,
                      fit_intercept=False)
        model.fit(x_joint, y_joint-center_joint, sample_weight=weights)
        weighted[test] = model.predict(local_pair[test])+center_joint
        residual = local_y[train] - global_prediction[train]
        gram = kernel[np.ix_(train, train)] + 0.3 * np.eye(int(train.sum()))
        center = float(residual.mean())
        coeff = np.linalg.solve(gram, residual - center)
        radial[test] = global_prediction[test] + center + kernel[np.ix_(test, train)] @ coeff
    high = local_y >= 21000.0
    return {
        "weighted_pair_ridge": {"all":statistics(local_y, weighted),
                                "above_21000":statistics(local_y[high],weighted[high])},
        "rbf_footrule_residual": {"all":statistics(local_y, radial),
                                  "above_21000":statistics(local_y[high],radial[high])},
        "median_pair_footrule":width,
    }


def run(args):
    orders, y, family, trace_rows = load_traces(args.traces)
    ranks, spline, pair = encode(orders)
    features = {"ridge_pair": pair, "ridge_spline": spline, "gbdt_rank": ranks}
    frozen = json.loads(args.frozen_orders.read_text())["constructed_orders"]
    exact_by_seed = {row["seed"]:row["score"] for row in json.loads(args.frozen_scores.read_text())["results"] if "score" in row}
    frozen = [row for row in frozen if row["seed"] in exact_by_seed]
    test_orders = [tuple(row["first_order"]) for row in frozen]
    y_frozen = np.array([exact_by_seed[row["seed"]] for row in frozen], np.float64)
    test_ranks, test_spline, test_pair = encode(test_orders)
    tests = {"ridge_pair": test_pair, "ridge_spline": test_spline, "gbdt_rank": test_ranks}
    report = {"trace_rows":trace_rows, "unique_orders":len(orders), "family_counts":
              {f:int(sum(family==f)) for f in np.unique(family)}, "frozen_n":len(frozen), "models":{}}
    local_seed = np.array([row["seed"] for row in frozen],dtype=np.int64)
    for name, x in features.items():
        family_results={}
        for f in np.unique(family):
            te = family == f
            prediction=fit_predict(name,x[~te],y[~te],x[te])
            high = y[te] >= np.quantile(y[te], .9)
            family_results[f] = {
                "all": statistics(y[te],prediction),
                "top_truth_decile": statistics(y[te][high],prediction[high]),
            }
        frozen_prediction = fit_predict(name,x,y,tests[name])
        near_top = y_frozen >= 21000.0
        report["models"][name] = {
            "family_holdout":family_results,
            "frozen":statistics(y_frozen,frozen_prediction),
            "frozen_above_21000":statistics(y_frozen[near_top],frozen_prediction[near_top]),
            "frozen_selected_seed_score": [
                {"seed":frozen[i]["seed"], "score":float(y_frozen[i]),
                 "prediction":float(frozen_prediction[i])}
                for i in np.argsort(-frozen_prediction)[:10]
            ],
        }
        print(name, json.dumps(report["models"][name]["frozen"], ensure_ascii=False), flush=True)
    report["local_calibration_threefold"] = local_crossfit(
        pair, y, test_pair, test_ranks, y_frozen, local_seed)
    print("local_calibration",json.dumps(report["local_calibration_threefold"],ensure_ascii=False),flush=True)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"out":str(args.out),"unique_orders":len(orders)},ensure_ascii=False),flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces",type=Path,default=Path("results/practice_order_training.npz"))
    parser.add_argument("--frozen-orders",type=Path,default=Path("results/practice_order_frozen_proposals.json"))
    parser.add_argument("--frozen-scores",type=Path,default=Path("results/practice_order_frozen_scores.json"))
    parser.add_argument("--out",type=Path,default=Path("results/practice_pairwise_surrogate_study.json"))
    run(parser.parse_args())
