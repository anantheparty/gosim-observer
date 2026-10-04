"""Review completed strong-policy NN trials without opening card truth."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent
ZIP = RESULTS / "cold_sparse_science_runtime_20261004/report_sparse_combination_20261004/observer_report_sparse_exact_20261004.zip"
EXPECTED_ZIP = "fa7a8e7c8de173331a64e160e4df6f34710c9e59a37b199271c2444e5d46126b"


def read(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_raw(directory, gate):
    return all(digest(directory / name) == value
               for name, value in gate["outputs_sha256"].items())


assert digest(ZIP) == EXPECTED_ZIP
with zipfile.ZipFile(ZIP) as archive:
    source = {name: hashlib.sha256(archive.read(name)).hexdigest()
              for name in archive.namelist() if not name.endswith("/")}

job = read(HERE / "job.json")
assert digest(HERE / "source_lock.json") == job["source_lock_sha256"]
assert digest(HERE / "cases.json") == job["cases_sha256"]
assert source == read(HERE / "source_lock.json")["packages"]["candidate_package"]
reviews = {}
for card in ("L1", "L2", "L3"):
    old_dir = RESULTS / "strategy_reassessment_actual_20261004/seasons/fault" / card
    new_dir = HERE / "seasons/sparse_report" / card
    old_gate, new_gate = read(old_dir / "gate_result.json"), read(new_dir / "gate_result.json")
    old, new = read(old_dir / "score_report.json"), read(new_dir / "score_report.json")
    workflow = read(new_dir / "workflow_result.json")
    events = []
    for line in (new_dir / "agent.log").read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    inserted = [x for x in events if x.get("event") == "sparse_calibrated_report"]
    reports = [x for x in lines(new_dir / "messages.jsonl") if x.get("record_type") == "report_result"]
    summaries = [x["persistent_fault_control"] for x in events if "persistent_fault_control" in x]
    old_actions, new_actions = lines(old_dir / "actions.jsonl"), lines(new_dir / "actions.jsonl")
    first_difference = next((i for i, (a, b) in enumerate(zip(old_actions, new_actions)) if a != b), None)
    delta = {k: Decimal(str(v)) - Decimal(str(old["components"][k]))
             for k, v in new["components"].items()}
    total_delta = Decimal(str(new["total"])) - Decimal(str(old["total"]))
    gates = {
        "original_and_candidate_normal_complete": all(g["protocol_passed"] and g["termination"] == "survey_complete"
            and g["accounted_seconds"] <= 900 and not g["traceback"] for g in (old_gate, new_gate)),
        "all_raw_hashes": verify_raw(old_dir, old_gate) and verify_raw(new_dir, new_gate),
        "frozen_actor_sources": new_gate["source_sha256"] == source,
        "same_scenario": old["sha256"]["scenario"] == new["sha256"]["scenario"],
        "actor_no_truth_or_network": not new_gate["participant_truth_mount"] and new_gate["network"] == "none",
        "same_cpu_memory_wallclock_budget": new_gate["memory_bytes"] == 2147483648 and new_gate["wallclock_limit"] == 900,
        "official_workflow_matches_score": workflow["score_report"] == new,
        "component_sum_matches_total": abs(sum(Decimal(str(v)) for v in new["components"].values()) - Decimal(str(new["total"]))) <= Decimal("0.000002"),
        "component_delta_sum_matches_total": abs(sum(delta.values()) - total_delta) <= Decimal("0.000002"),
        "all_insertions_have_official_public_report_result": all(any(r["issued_at_utc"] == x["now_utc"] for r in reports) for x in inserted),
        "public_only_guard_receipt": bool(summaries) and not summaries[-1]["reads_truth"]
            and not summaries[-1]["reads_teacher_labels"] and summaries[-1]["sparse_report"]["public_only"],
    }
    # A negative reward is a valid algorithm result, not a failed protocol gate.
    if inserted:
        gates["first_action_difference_is_report_after_equal_prefix"] = first_difference is not None and new_actions[first_difference]["action"] == "report"
    review = {
        "passed": all(gates.values()), "gates": gates,
        "control": str(old_dir.relative_to(RESULTS)), "control_total": old["total"], "candidate_total": new["total"],
        "actual_total_delta": str(total_delta), "component_delta": {k: str(v) for k, v in delta.items()},
        "accounted_seconds": new_gate["accounted_seconds"], "count_delta": {k: new["counts"][k] - old["counts"][k] for k in new["counts"]},
        "required_and_request_components_unchanged": all(delta[k] == 0 for k in ("required_penalty", "observation_request_reward")),
        "loss_plan_unchanged": old["invalidations"] == new["invalidations"],
        "first_action_difference": first_difference, "inserted_reports": inserted,
        "official_report_results": reports, "public_guard_summary": summaries[-1] if summaries else None,
    }
    (new_dir / "ROOT_ACTUAL_RESULT.json").write_text(json.dumps(review, indent=2) + "\n")
    reviews[card] = review

mean_delta = sum(Decimal(r["actual_total_delta"]) for r in reviews.values()) / len(reviews)
result = {
    "schema": "root-three-complete-sparse-report-trial-result-v1", "source_zip_sha256": EXPECTED_ZIP,
    "all_reviews_passed": all(x["passed"] for x in reviews.values()), "cards": reviews,
    "local_same_card_mean_before": str(sum(Decimal(str(x["control_total"])) for x in reviews.values()) / 3),
    "local_same_card_mean_after": str(sum(Decimal(str(x["candidate_total"])) for x in reviews.values()) / 3),
    "local_same_card_mean_delta": str(mean_delta), "current_candidate_deploy": mean_delta > 0,
    "decision": "Reject current frozen candidate: negative three-card mean; do not use L4 to rescue this trial.",
    "actual_full_seasons": True, "formal_online_submission": False, "formal_online_gain": None,
}
(HERE / "ROOT_THREE_CARD_RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"passed": result["all_reviews_passed"], "mean_delta": str(mean_delta),
    "deltas": {c: r["actual_total_delta"] for c, r in reviews.items()},
    "failed": {c: [k for k, v in r["gates"].items() if not v] for c, r in reviews.items()}}, indent=2))
assert result["all_reviews_passed"]
