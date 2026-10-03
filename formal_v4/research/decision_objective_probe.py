"""Synthetic action-value checkpoint counterexample; no teacher labels opened."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from research.structured_student_train import group_metrics


def main():
    # The very harmful action is never chosen by either model. More accurate
    # prediction of it can nevertheless dominate the numerical MAE criterion.
    labels = np.zeros((3, 6), np.float32)
    labels[:, 0] = [0, -100, 1]
    labels[:, 1] = labels[:, 0]
    group = dict(labels=labels, features=SimpleNamespace(actions=[
        SimpleNamespace(name=n) for n in ("control", "harmful", "profitable")]))
    predictions = {"smaller_MAE": np.array([0, -99, -1]),
                   "better_decision": np.array([0, -95, 1])}
    metrics = {k: group_metrics([group], [p]) for k, p in predictions.items()}
    assert metrics["smaller_MAE"]["raw_advantage_mae"] < metrics["better_decision"]["raw_advantage_mae"]
    assert metrics["smaller_MAE"]["selected_teacher_advantage_mean"] == 0
    assert metrics["better_decision"]["selected_teacher_advantage_mean"] == 1
    assert metrics["smaller_MAE"]["teacher_regret_mean"] == 1
    assert metrics["better_decision"]["teacher_regret_mean"] == 0
    # With the same held-out candidate sets, regret = fixed oracle value minus
    # selected return. Thus minimizing mean regret maximizes selected return.
    result = dict(schema="synthetic-decision-objective-counterexample-v1",
                  labels=labels[:, 0].tolist(), predictions={k:v.tolist() for k,v in predictions.items()},
                  metrics=metrics, actual_teacher_label_files_read=0,
                  training_executed=False, deployment_score_claim=False,
                  scope="Synthetic single-state selection; no causal-world expectation or whole-season claim",
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  trainer_sha256=hashlib.sha256((PROJECT/"research/structured_student_train.py").read_bytes()).hexdigest())
    out = PROJECT/"results/decision_objective_20261004"
    out.mkdir(parents=True, exist_ok=True)
    (out/"counterexample.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:metrics[k] for k in predictions}))


if __name__ == "__main__":
    main()
