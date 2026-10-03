#!/usr/bin/env python3
"""Strict same-prefix and complete-season gates for one program-only teacher."""
import collections
import csv
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "results/objective_graph_20261004"
PAIR = OUT / "program_pair"
OLD = BASE / "results/geometry_native_20261003/protocol_phase_control/L2"
PLAN = json.loads((OUT/"program_predeclared_plan.json").read_text())


def actions(path):
    return [json.loads(s) for s in path.read_text().splitlines() if s]


def terminal_targets(path):
    scores, factors = collections.defaultdict(float), collections.defaultdict(float)
    for hit in csv.DictReader(path.open()):
        if hit["valid"] == "true":
            target = hit["target_id"]
            scores[target] = max(scores[target], float(hit["score"]))
            factors[target] = max(factors[target], float(hit["factor"]))
    return scores, factors


def log_records(path):
    result = []
    for line in path.read_text().splitlines():
        try:
            record = json.loads(line)
            if isinstance(record, dict):
                result.append(record)
        except json.JSONDecodeError:
            pass
    return result


if __name__ == "__main__":
    original = actions(OLD/"actions.jsonl")
    control = actions(PAIR/"control/L2/actions.jsonl")
    backup = actions(PAIR/"backup/L2/actions.jsonl")
    control_score = json.loads((PAIR/"control/L2/score_report.json").read_text())
    backup_score = json.loads((PAIR/"backup/L2/score_report.json").read_text())
    intervention_index = next(i for i, a in enumerate(original)
                              if a == PLAN["action"])
    expected_backup = {**PLAN["action"], "program": "BACKUP"}
    gates = dict(control_total_matches_original=control_score["total"] == PLAN["original_control_total"],
                 control_all_actions_match_original=control == original,
                 identical_prefix=control[:intervention_index] == backup[:intervention_index] == original[:intervention_index],
                 original_action_matches=control[intervention_index] == PLAN["action"],
                 only_program_changed=backup[intervention_index] == expected_backup)
    logs = {case:log_records(PAIR/case/"L2/agent.log") for case in ("control", "backup")}
    for case in ("control", "backup"):
        workflow = json.loads((PAIR/case/"L2/workflow_result.json").read_text())
        gates[f"{case}_complete"] = workflow["termination_reason"] == "survey_complete"
        gates[f"{case}_no_traceback"] = "Traceback" not in (PAIR/case/"L2/agent.log").read_text()
        gates[f"{case}_intervened_and_ingested"] = any(r.get("probe_done") and r.get("probe_post_feedback") for r in logs[case])
    cs, cf = terminal_targets(PAIR/"control/L2/observations.csv")
    bs, bf = terminal_targets(PAIR/"backup/L2/observations.csv")
    targets = sorted(set(cs)|set(bs))
    deltas = [dict(target=t, control_score=cs[t], backup_score=bs[t],
                   signed_science_delta=bs[t]-cs[t], control_factor=cf[t], backup_factor=bf[t])
              for t in targets if abs(cs[t]-bs[t]) > 1e-6 or (cf[t]>=.5)!=(bf[t]>=.5)]
    result = dict(all_gates_passed=all(gates.values()), gates=gates,
                  label_is_causal_behavior_policy_teacher=all(gates.values()),
                  truth_selected_single_L2_intervention=True, online_strategy=False,
                  total_delta=backup_score["total"]-control_score["total"],
                  control_total=control_score["total"], backup_total=backup_score["total"],
                  control_components=control_score["components"], backup_components=backup_score["components"],
                  control_counts=control_score["counts"], backup_counts=backup_score["counts"],
                  checkpoints={case:[r for r in logs[case] if r.get("event", "").startswith("program_probe")]
                               for case in logs},
                  terminal_target_deltas=deltas,
                  artifact_sha256={f"{case}/{name}":hashlib.sha256((PAIR/case/"L2"/name).read_bytes()).hexdigest()
                                   for case in logs for name in ("actions.jsonl", "observations.csv", "score_report.json")})
    (OUT/"program_pair_causal_audit.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ("all_gates_passed", "gates", "total_delta", "control_total", "backup_total",
                                         "control_components", "backup_components", "checkpoints")}, indent=2))
    if not result["all_gates_passed"]:
        raise SystemExit("Program-only teacher gates failed; do not treat score delta as causal evidence")
