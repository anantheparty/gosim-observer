"""Review frozen artifacts and complete official results; never open card truth."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import zipfile


HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent
ARCHIVE = RESULTS / "cold_persistent_fault_control_20261004/candidate_package.zip"
EXPECTED_ZIP = "bd461164340f4adf490ace91003d49f7205a6ea631f712e9767f3527ec9549ba"
CONTROLS = {
    "L1": RESULTS / "request_geometry_integration_20261004/seasons/control/L1",
    "L2": RESULTS / "request_geometry_integration_20261004/seasons/control/L2",
    "L3": RESULTS / "request_terminal_pair_20261004/seasons/control/L3",
    "L4": RESULTS / "request_terminal_pair_20261004/seasons/control/L4",
}


def read(path):
    return json.loads(path.read_text())


def jsonlines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_hashes(directory, gate):
    return all(digest(directory / name) == value
               for name, value in gate["outputs_sha256"].items())


assert digest(ARCHIVE) == EXPECTED_ZIP
with zipfile.ZipFile(ARCHIVE) as archive:
    source_hashes = {name: hashlib.sha256(archive.read(name)).hexdigest()
                     for name in archive.namelist() if not name.endswith("/")}

reviews = {}
for card, control in CONTROLS.items():
    candidate = HERE / "seasons/fault" / card
    old_gate, new_gate = read(control / "gate_result.json"), read(candidate / "gate_result.json")
    old, new = read(control / "score_report.json"), read(candidate / "score_report.json")
    old_actions, new_actions = jsonlines(control / "actions.jsonl"), jsonlines(candidate / "actions.jsonl")
    events = []
    for line in (candidate / "agent.log").read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    guards = [event for event in events if event.get("event") == "persistent_diagnostic_report"]
    report_results = [message for message in jsonlines(candidate / "messages.jsonl")
                      if message.get("record_type") == "report_result"]
    first_difference = next((i for i, (a, b) in enumerate(zip(old_actions, new_actions)) if a != b), None)
    gates = {
        "original_and_candidate_protocol_complete": all(
            gate["protocol_passed"] and gate["termination"] == "survey_complete"
            and gate["accounted_seconds"] < 900 and not gate["traceback"]
            for gate in (old_gate, new_gate)),
        "all_raw_hashes": raw_hashes(control, old_gate) and raw_hashes(candidate, new_gate),
        "frozen_candidate_sources": new_gate["source_sha256"] == source_hashes,
        "original_source_bytes_except_run_manifests": all(
            new_gate["source_sha256"].get(name) == value
            for name, value in old_gate["source_sha256"].items()
            if name not in {"build_manifest.json", "observer.project.json"}),
        "same_scenario_hash": old["sha256"]["scenario"] == new["sha256"]["scenario"],
        "old_loss_plan_unchanged": old["invalidations"] == new["invalidations"],
        "required_and_request_components_unchanged": all(
            old["components"][name] == new["components"][name]
            for name in ("required_penalty", "observation_request_reward")),
        "participant_no_truth_mount_network_none": not new_gate["participant_truth_mount"]
            and new_gate["network"] == "none",
        "same_cpu_memory_budget": new_gate["memory_bytes"] == 2147483648
            and new_gate["wallclock_limit"] == 900,
    }
    if guards:
        gates["first_intervention_report_after_equal_public_prefix"] = (
            first_difference is not None and new_actions[first_difference].get("action") == "report")
        gates["every_guard_has_correct_official_response"] = all(any(
            result["issued_at_utc"] == guard["now_utc"]
            and result.get("correct") and result.get("repaired")
            for result in report_results) for guard in guards)
    else:
        gates["no_guard_all_actions_identical"] = old_actions == new_actions
        gates["no_guard_all_components_identical"] = old["components"] == new["components"]
    delta = {name: float(Decimal(str(value)) - Decimal(str(old["components"][name])))
             for name, value in new["components"].items()}
    total_delta = Decimal(str(new["total"])) - Decimal(str(old["total"]))
    gates["component_delta_sum_matches_total"] = abs(
        sum(Decimal(str(value)) for value in delta.values()) - total_delta) <= Decimal("0.000002")
    review = {
        "passed": all(gates.values()), "gates": gates,
        "control_directory": str(control.relative_to(RESULTS)),
        "control_total": old["total"], "candidate_total": new["total"],
        "actual_total_delta": float(total_delta), "component_delta": delta,
        "accounted_seconds": new_gate["accounted_seconds"],
        "first_divergence_actor_action_position": first_difference,
        "guard_reports": guards, "official_report_results": report_results,
    }
    (candidate / "ROOT_ACTUAL_RESULT.json").write_text(json.dumps(review, indent=2) + "\n")
    reviews[card] = review

mean_before = sum(Decimal(str(review["control_total"])) for review in reviews.values()) / 4
mean_after = sum(Decimal(str(review["candidate_total"])) for review in reviews.values()) / 4
result = {
    "schema": "root-four-complete-fault-source-and-result-review-v1",
    "source_zip_sha256": EXPECTED_ZIP,
    "cards": reviews,
    "actual_full_season": True, "formal_online_submission": False,
    "formal_online_gain": None,
    "all_reviews_passed": all(review["passed"] for review in reviews.values()),
    "local_same_card_mean_before": str(mean_before),
    "local_same_card_mean_after": str(mean_after),
    "local_same_card_mean_delta": str(mean_after - mean_before),
}
(HERE / "ROOT_FAULT_FOUR_CARD_RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"passed": result["all_reviews_passed"], "mean_delta": result["local_same_card_mean_delta"],
                  "card_deltas": {card: review["actual_total_delta"] for card, review in reviews.items()},
                  "failed": {card: [name for name, passed in review["gates"].items() if not passed]
                             for card, review in reviews.items()}}, indent=2))
assert result["all_reviews_passed"]
