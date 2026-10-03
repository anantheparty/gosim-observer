#!/usr/bin/env python3
"""Synthetic information/settlement gates only; never opens any card truth.

The abstract packages omit telescope geometry and weather integration. They
validate genome compression and terminal labels, not a formal score gain.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evolutionary_policy_core import (
    Branch, Leaf, PublicFeatures, decide, nodes, phenotype, reduce_tree, stumps,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "upstream/gosim-observer-examples/runner"))
from challenge.v4_scorer import (
    BestLedger, observation_request_status, required_penalty,
    settle_observation_requests, uniformity_penalty,
)

OUT = ROOT / "results/evolutionary_policy_20261004"
START = datetime(2026, 10, 4, tzinfo=timezone.utc)
CFG = {
    "required": {"penalty_per_missing": 50., "observed_factor_threshold": .5},
    "uniformity": {"weight": 200., "ra_band_width_deg": 10.,
                   "observed_factor_threshold": .5},
}
TARGETS = [
    {"target_id": "r", "required": True, "ra_deg": 2., "science_weight": 1.},
    {"target_id": "q1", "required": False, "ra_deg": 3., "science_weight": 1.},
    {"target_id": "q2", "required": False, "ra_deg": 4., "science_weight": 1.},
]
REQUEST = {
    "request_id": "rq", "issued_at_utc": START,
    "deadline_utc": START + timedelta(seconds=180),
    "target_ids": ["q1", "q2"], "minimum_completed": 2,
    "completion_factor_threshold": .5, "completion_reward": 100.,
}


def settle(ledger: BestLedger) -> dict:
    science = sum(score for factor, score in ledger.best().values())
    missing, required_cost = required_penalty(TARGETS, ledger.max_factors(), CFG)
    ratios, uniform = uniformity_penalty(TARGETS, ledger.max_factors(), CFG)
    requests, reward = settle_observation_requests([REQUEST], ledger)
    return {"total": science - required_cost - uniform + reward,
            "science": science, "required_missing": missing,
            "required_cost": required_cost, "uniformity_cost": uniform,
            "request_reward": reward, "request_count": requests[0]["completed_count"]}


def record(ledger, rank, target, factor, multiplier=1., start=None, end=None):
    start = start or START + timedelta(seconds=rank * 60)
    end = end or start + timedelta(seconds=60)
    ledger.record(rank, target, factor, factor * multiplier, start, end)


def main():
    cpu = time.process_time()
    # 6,087 depth<=2 raw syntactic trees, with exact phenotype enumeration.
    family = stumps()
    trees = family + [Branch(p, yes, no)
                      for p in ("request_surplus", "required_scarce", "feedback_drop", "resynced")
                      for yes in family for no in family]
    reduced = [reduce_tree(tree) for tree in trees]
    assert all(phenotype(before) == phenotype(after)
               for before, after in zip(trees, reduced))
    unique = len({phenotype(tree) for tree in trees})

    # Latent states are deliberately external to the policy API. Changing all
    # hidden factors for the same public features cannot change the operator.
    operator_map = []
    genome = Branch("request_surplus", Leaf("request_bundle"),
                    Branch("required_scarce", Leaf("scarce_required"), Leaf("native")))
    for surplus in (False, True):
        public = PublicFeatures(surplus, True, False, False)
        choices = []
        for hidden in ({"quality": .1, "future_request": None},
                       {"quality": 1., "future_request": {"reward": 1000}}):
            choices.append(decide(genome, public))
        assert choices[0] == choices[1]
        operator_map.append({"request_surplus": surplus, "choice": choices[0]})

    # Official settlement exposes the k-of-n complementarity and required cost.
    control, challenger = BestLedger(), BestLedger()
    record(control, 0, "r", .5)
    record(control, 1, "q2", .5)
    record(challenger, 0, "q1", .5)
    record(challenger, 1, "q2", .5)
    base, alt = settle(control), settle(challenger)
    assert alt["request_reward"] == 100 and base["request_reward"] == 0
    assert alt["required_missing"] == base["required_missing"] + 1
    assert alt["total"] - base["total"] == 50

    # Exposures before release or straddling deadline do not contribute quota.
    window = BestLedger()
    record(window, 0, "q1", 1., start=START-timedelta(seconds=60), end=START)
    record(window, 1, "q2", 1., start=START+timedelta(seconds=150),
           end=START+timedelta(seconds=210))
    assert observation_request_status(REQUEST, window)["completed_count"] == 0

    # Independent score/factor ledgers: higher score can have lower factor.
    distinct = BestLedger()
    record(distinct, 0, "r", .55, 1.)
    record(distinct, 1, "r", .49, 1.2)
    assert distinct.best()["r"][0] == .49
    assert distinct.max_factors()["r"] == .55
    assert required_penalty(TARGETS, distinct.max_factors(), CFG)[0] == 0
    distinct.invalidate_window(0, 1, "synthetic_loss")
    assert required_penalty(TARGETS, distinct.max_factors(), CFG)[0] == 1

    # Returned scores only yield an interval when match status is hidden.
    returned_score = .49 * 1.2
    lower, upper = returned_score / 1.2, min(1., returned_score)
    assert lower < .5 <= upper

    result = {
        "scope": "synthetic abstraction gates; no physical runtime policy or formal gain",
        "card_truth_opened": False, "full_seasons": 0, "ssh_jobs": 0,
        "policy_predicates": 4, "package_operators": 3, "binary_feature_states": 16,
        "raw_depth_le_2_trees": len(trees), "unique_exact_abstract_behaviors": unique,
        "phenotype_reduction_fraction": 1-unique/len(trees),
        "canonical_reduction_preserves_all_declared_behaviors": True,
        "mean_nodes_before": sum(map(nodes, trees))/len(trees),
        "mean_nodes_after": sum(map(nodes, reduced))/len(trees),
        "latent_twins": operator_map,
        "synthetic_terminal_coupling": {"control": base, "challenger": alt,
                                        "delta": alt["total"]-base["total"]},
        "request_window_gate": True, "separate_score_factor_ledger_gate": True,
        "resync_invalidation_gate": True,
        "ambiguous_factor_interval": {"score": returned_score, "lower": lower,
                                      "upper": upper, "threshold_status": "unknown"},
        "cpu_seconds": time.process_time()-cpu,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "synthetic_probe.json").write_text(json.dumps(result, indent=2)+"\n")
    manifest = {"status": "SYNTHETIC_GATES_ONLY_NO_FORMAL_SCORE_CLAIM",
                "sources": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in [Path(__file__), Path(__file__).with_name("evolutionary_policy_core.py"),
                                         ROOT/"upstream/gosim-observer-examples/runner/challenge/v4_scorer.py"]},
                "result": "synthetic_probe.json"}
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
