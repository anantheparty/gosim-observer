"""One synthetic end-to-end portability check, not existing guard fixtures.

Build positive/negative/control-only/failed partitions, move the bundle, check
unaltered public bytes and false acceptance. No actual teacher products are read.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

import numpy as np

from research.policy_iteration_dataset import build, canonical_action, sha, write_json
from research.structured_student_audit import synthetic_public
from research.structured_student_features import COMPONENTS, SchemaError
from research.structured_student_train import AUDIT_SCHEMA, REQUIRED_V2_GATES, accepted_groups, card_split


def fixture():
    initial, base_capture, arrays = synthetic_public()
    checks = {}
    with tempfile.TemporaryDirectory(prefix="student-portable-synthetic-") as directory:
        root = Path(directory)
        out, participant, kit = root / "teacher", root / "participant", root / "kit"
        out.mkdir(); participant.mkdir(); kit.mkdir()
        (participant / "toy.py").write_text("# fabricated source witness\n")
        (kit / "toy.py").write_text("# fabricated evaluator witness\n")
        source = dict(schema="synthetic-only-source", all_ready_files_byte_identical=True,
                      participant={"toy.py":sha(participant / "toy.py")}, official={"toy.py":sha(kit / "toy.py")})
        write_json(out / "source_lock.json", source)
        source_sha = sha(out / "source_lock.json")
        groups, statuses, public_inputs = [], [], {}
        original_bytes = {}
        for card in ("L1", "L2", "L3", "L4"):
            gid = "synthetic_" + card
            cap = copy.deepcopy(base_capture)
            card_arrays = {key:value.copy() for key,value in arrays.items()}
            cap.update(rank=3, prefix_sha256="fabricated_public_prefix_" + card, case="control")
            cap["baseline_action"] = copy.deepcopy(cap["actions"]["control"])
            cap["selected_action"] = copy.deepcopy(cap["actions"]["control"])
            if card == "L3":
                cap["actions"] = {"control":cap["actions"]["control"]}
            if card == "L2":
                cap["actions"]["program"] = copy.deepcopy(cap["actions"]["control"])
                cap["actions"]["program"]["program"] = "BRIGHT"
                cap["candidate_predictions"]["program"] = copy.deepcopy(cap["candidate_predictions"]["control"])
                cap["candidate_utilities"]["program"] = None
                card_arrays["program_assignment"] = card_arrays["control_assignment"].copy()
            names = list(cap["actions"])
            init = copy.deepcopy(initial); init["task_card"] = {"card_id":card}
            init_path = out / (card + "_initialize_public.json")
            write_json(init_path, init)
            prefix = out / "bulk_prefixes" / (gid + ".jsonl")
            prefix.parent.mkdir(exist_ok=True)
            prefix.write_text("".join(json.dumps(dict(rank=r)) + "\n" for r in range(3)))
            item = dict(group_id=gid, card=card, rank=3, split=card_split(card), prefix_path=str(prefix),
                        prefix_sha256=sha(prefix), prefix_rows=3, reached_prefix_action_sha256=cap["prefix_sha256"],
                        cut_snapshot_sha256=canonical_action({k:v for k,v in cap["snapshot"].items() if k != "wallclock"}))
            groups.append(item)
            natural = out / "natural_control" / card / "rank_0064" / "control"
            natural.mkdir(parents=True)
            gate = dict(teacher_valid=True, ready_score_match=True, ready_all_actions_match=True,
                        ready_score_components_match=True, source_unchanged_after=True, source_lock_sha256=source_sha)
            write_json(natural / "gate_result.json", gate)
            for name in ("actions.jsonl", "score_report.json", "public_prefix.jsonl"):
                (natural / name).write_text("opaque synthetic bytes, intentionally not valid score JSON\n")
            public_inputs[card] = dict(initial_path=str(init_path), initial_sha256=sha(init_path),
                    **{key:sha(natural / name) for name,key in (("gate_result.json", "canonical_gate_sha256"),
                    ("actions.jsonl", "canonical_actions_sha256"), ("score_report.json", "canonical_score_sha256"),
                    ("public_prefix.jsonl", "public_trace_sha256"))})
            group = out / "bulk" / card / "rank_0003"
            capture_path = group / "control" / "public_capture" / "capture.json"
            features_path = capture_path.with_name("public_features.npz")
            capture_path.parent.mkdir(parents=True)
            np.savez_compressed(features_path, **card_arrays)
            cap["feature_blob_sha256"] = sha(features_path)
            # Compact ORIGINAL bytes differ from prettyprinted post-run copies.
            capture_path.write_text(json.dumps(cap, separators=(",", ":")))
            original_bytes[gid] = capture_path.read_bytes()
            snapshot = {k:v for k,v in cap["snapshot"].items() if k != "wallclock"}
            public_state = {k:v for k,v in cap.items() if k not in ("case", "selected_action")}; public_state["snapshot"] = snapshot
            absent = [dict(case="field", reason="synthetic candidate absent")]
            availability = dict(schema="policy-iteration-public-availability-v1", planned_group_id=gid, card=card, rank=3,
                    source_lock_sha256=source_sha, frozen_before_terminal=True, control_was_running=True,
                    available_cases=names, absent_cases=absent, action_hashes={n:canonical_action(a) for n,a in cap["actions"].items()},
                    capture_sha256=sha(capture_path), feature_blob_sha256=sha(features_path),
                    cut_snapshot_sha256=canonical_action(snapshot), public_capture_state_sha256=canonical_action(public_state))
            write_json(group / "availability.json", availability)
            advantages = dict(L1=2., L2=-3., L3=0., L4=1.)
            delta = advantages[card]
            sign_counts = dict(positive=int(card == "L1" or card == "L4"), negative=int(card == "L2"), tie=int(card == "L2"))
            archives = []
            for case in names:
                case_dir = group / case
                case_dir.mkdir(exist_ok=True)
                (case_dir / "score_report.json").write_text("opaque fabricated terminal product, never decoded\n")
                members = {str(p.relative_to(case_dir)):sha(p) for p in sorted(case_dir.rglob("*")) if p.is_file()}
                write_json(case_dir / "archive_members_bulk.json", dict(schema="teacher-episode-member-lock-v2", members=members))
                archive_path = out / "archives" / ("bulk_%s_rank3_%s.tar.gz" % (card, case))
                archive_path.parent.mkdir(exist_ok=True)
                with tarfile.open(archive_path, "w:gz") as archive:
                    for path in sorted(case_dir.rglob("*")):
                        if path.is_file(): archive.add(path, arcname=str(path.relative_to(case_dir)), recursive=False)
                archives.append(dict(path=str(archive_path), sha256=sha(archive_path), bytes=archive_path.stat().st_size, member_count=len(members)+1))
            audit = dict(schema=AUDIT_SCHEMA, passed=True, archive_complete=True, card=card, rank=3, group_id=gid,
                    split=card_split(card), baseline_total=100., trainable=len(names)>1,
                    trainable_reason="complete_available_full_season_pairs" if len(names)>1 else "control_only_no_distinct_alternative",
                    gates={**{name:True for name in REQUIRED_V2_GATES}, "all_started_cases_archived":True}, available_cases=names,
                    absent_cases=absent, availability_sha256=sha(group / "availability.json"), archive=archives, sign_counts=sign_counts,
                    labels=[dict(case=n, valid_full_season_pair=True, baseline_total=100., branch_total=100.+(0. if n == "program" else delta), advantage=0. if n == "program" else delta,
                    component_delta={c:(0. if n == "program" else delta) if i==0 else 0. for i,c in enumerate(COMPONENTS)},
                    action_pair=[cap["actions"]["control"], cap["actions"][n]]) for n in names if n != "control"])
            status = dict(group_id=gid, scheduled_cases=names, finished_cases=names, failed=[], audit_passed=True, archive_complete=True, sign_counts=sign_counts)
            if card == "L4":
                audit["passed"] = False; audit["gates"]["all_teacher_valid"] = False
                status["failed"] = [dict(stage="gate", reason="fabricated failed teacher group")]
                status["audit_passed"] = False
            write_json(group / "pair_audit.json", audit)
            statuses.append(status)
        plan = dict(source_lock_sha256=source_sha, groups=groups)
        write_json(out / "bulk_plan.json", plan)
        lock = dict(schema="policy-iteration-bulk-source-lock-v1", frozen_teacher_source_lock_sha256=source_sha,
                files={str(participant / "toy.py"):sha(participant / "toy.py")}, plan_sha256=sha(out / "bulk_plan.json"),
                prefixes={g["group_id"]:g["prefix_sha256"] for g in groups}, public_inputs=public_inputs)
        write_json(out / "bulk_source_lock.json", lock)
        write_json(out / "bulk_summary.json", dict(groups=statuses, lock_evidence=dict(source_files_unchanged=True, full_inputs_unchanged=True)))
        destination = root / "portable"
        build(argparse.Namespace(out=out, participant=participant, kit=kit, destination=destination,
                                 reviewed_lock_sha256=sha(out / "bulk_source_lock.json")))
        # Relocate the candidate tree: no original absolute raw-input path required.
        moved = root / "relocated_fit_validation"
        shutil.copytree(destination / "fit_validation", moved)
        manifest = json.loads((moved / "candidate_manifest.json").read_text())
        checks["candidate_stays_unaccepted"] = manifest["accepted"] is False
        checks["whole_card_fit_partition"] = [g["card"] for g in manifest["groups"]] == ["L1", "L2", "L3"]
        try: accepted_groups(moved / "candidate_manifest.json")
        except SchemaError: checks["candidate_cannot_trigger_fitting"] = True
        else: raise AssertionError("An unaccepted candidate was admitted")
        for record in manifest["groups"]:
            checks[record["group_id"] + "_capture_exact_after_move"] = (moved / record["capture"]).read_bytes() == original_bytes[record["group_id"]]
        outcomes = json.loads((moved / "outcome_inventory.json").read_text())["records"]
        checks["positive_and_negative_preserved"] = outcomes[0]["sign_counts"]["positive"] == 1 and outcomes[1]["sign_counts"]["negative"] == 1
        checks["tied_alternative_preserved"] = outcomes[1]["sign_counts"]["tie"] == 1 and "program" in outcomes[1]["available_cases"]
        checks["control_only_and_absent_preserved"] = outcomes[2]["trainable"] is False and bool(outcomes[2]["absent_cases"])
        test = json.loads((destination / "sealed_test" / "outcome_inventory.json").read_text())["records"]
        checks["failed_test_group_preserved_separately"] = len(test) == 1 and test[0]["admission"] == "excluded_explicitly" and bool(test[0]["failures"])
        checks["fitting_partition_contains_no_l4_files"] = not any("L4" in str(path.relative_to(moved)) for path in moved.rglob("*") if path.is_file())
        index = json.loads((destination / "bundle_index.json").read_text())
        checks["parent_index_exposes_no_l4_returns"] = not any(k in index for k in ("test_score", "test_sign_counts", "test_metrics"))
        checks["opaque_terminal_bytes_not_parsed"] = True  # Invalid score JSON successfully hash-verified.
        assert all(checks.values()), checks
    return dict(schema="portable-dataset-synthetic-e2e-v1", passed=True, checks=checks,
                synthetic_only=True, actual_teacher_label_files_read=0, optimization_steps=0, seasons_launched=0)


if __name__ == "__main__":
    result = fixture()
    write_json(Path(__file__).with_name("portable_bundle_fixture_result.json"), result)
    print(json.dumps(result, indent=2))
