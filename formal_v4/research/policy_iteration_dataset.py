"""Freeze portable, UNACCEPTED datasets after a terminal causal-teacher batch.

This tool never launches seasons, fits a model, repairs an audit, or parses raw
terminal scores. Only the existing v2 auditor supplies supervised returns.
Run beside the original Rhodes1 inputs, before transporting the small bundles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile

from research.structured_student_features import COMPONENTS, SchemaError, build_public_features, canonical_action, load_public, sha
from research.structured_student_train import (
    AUDIT_SCHEMA, MANIFEST_SCHEMA, REQUIRED_V2_GATES, _availability_contract,
    _candidate_contract, _read_json, card_split,
)


def require(condition, message):
    if not condition:
        raise SchemaError(message)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def checked_copy(source, destination, expected=None):
    digest = sha(source)
    require(expected is None or expected == digest, "Source hash drift: " + str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)  # Preserve ORIGINAL capture/availability/audit bytes.
    require(sha(destination) == digest, "Copy hash drift: " + str(destination))
    return digest


def verify_lock(out, reviewed_sha, participant, kit):
    lock_path = out / "bulk_source_lock.json"
    require(sha(lock_path) == reviewed_sha, "Bulk source lock differs from root-reviewed SHA")
    lock = _read_json(lock_path)
    source = _read_json(out / "source_lock.json")
    plan = _read_json(out / "bulk_plan.json")
    require(lock["schema"] == "policy-iteration-bulk-source-lock-v1", "Unknown bulk lock schema")
    require(sha(out / "source_lock.json") == lock["frozen_teacher_source_lock_sha256"] == plan["source_lock_sha256"], "Teacher source lock drift")
    require(sha(out / "bulk_plan.json") == lock["plan_sha256"], "Frozen plan drift")
    require(all(sha(Path(path)) == value for path, value in lock["files"].items()), "Frozen launcher/auditor source drift")
    require(all(sha(participant / path) == value for path, value in source["participant"].items()), "Frozen participant source drift")
    require(all(sha(kit / path) == value for path, value in source["official"].items()), "Official evaluator source drift")
    require(source["all_ready_files_byte_identical"] is True, "Missing exact READY provenance")
    groups = plan["groups"]
    identities = [g["group_id"] for g in groups]
    require(len(identities) == len(set(identities)), "Duplicate predeclared group identity")
    require(set(lock["prefixes"]) == set(identities), "Prefix inventory differs from the whole frozen plan")
    for item in groups:
        require(item["split"] == card_split(item["card"]), "Frozen card split drift")
        require(sha(Path(item["prefix_path"])) == item["prefix_sha256"] == lock["prefixes"][item["group_id"]], "Frozen public prefix drift")
        rows = [_read_json_line(line) for line in Path(item["prefix_path"]).read_text().splitlines() if line.strip()]
        require(len(rows) == item["prefix_rows"] and all(int(r["rank"]) < item["rank"] for r in rows), "Prefix contains the cut or future action")
    for card, entry in lock["public_inputs"].items():
        require(sha(Path(entry["initial_path"])) == entry["initial_sha256"], "Public initialization drift")
        directory = out / "natural_control" / card / "rank_0064" / "control"
        for name, key in (("gate_result.json", "canonical_gate_sha256"), ("actions.jsonl", "canonical_actions_sha256"),
                          ("score_report.json", "canonical_score_sha256"), ("public_prefix.jsonl", "public_trace_sha256")):
            require(sha(directory / name) == entry[key], "Canonical READY input drift")
        # Hash score-report bytes; do not parse or relabel a terminal return here.
        gate = _read_json(directory / "gate_result.json")
        require(all(gate.get(key) is True for key in ("teacher_valid", "ready_score_match", "ready_all_actions_match",
                                                     "ready_score_components_match", "source_unchanged_after")), "Canonical natural READY gate failed")
        require(gate["source_lock_sha256"] == plan["source_lock_sha256"], "Canonical READY source identity drift")
    return lock, source, plan


def _read_json_line(line):
    # Reuse the guarded duplicate-key contract without creating temporary files.
    from research.structured_student_train import _unique_object
    return json.loads(line, object_pairs_hook=_unique_object)


def archive_receipt(record, raw_directory):
    """Verify every archived byte and its original raw file; never decode scores."""
    require(not record.get("archive_failed"), "Auditor reported incomplete episode archive")
    path = Path(record["path"])
    require(path.stat().st_size == record["bytes"] and sha(path) == record["sha256"], "Episode archive hash/size drift")
    with tarfile.open(path, "r:gz") as archive:
        entries = archive.getmembers()
        names = [entry.name for entry in entries]
        require(len(names) == len(set(names)) and all(entry.isfile() for entry in entries), "Ambiguous/nonregular archive members")
        require(all(not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts for n in names), "Unsafe archive member path")
        witness = json.loads(archive.extractfile("archive_members_bulk.json").read())
        require(witness["schema"] == "teacher-episode-member-lock-v2", "Wrong archive member schema")
        members = witness["members"]
        require(set(names) == set(members) | {"archive_members_bulk.json"}, "Archive member inventory drift")
        require(len(names) == record["member_count"], "Archive member count drift")
        for name, digest in members.items():
            # Terminal products are read as opaque bytes solely for SHA checking.
            require(hashlib.sha256(archive.extractfile(name).read()).hexdigest() == digest, "Archived episode member drift")
            require(sha(raw_directory / name) == digest, "Original episode differs from its audited archive")
        current = {str(p.relative_to(raw_directory)).replace("\\", "/") for p in raw_directory.rglob("*")
                   if p.is_file() and p.name != "archive_members_bulk.json"}
        require(current == set(members), "Raw episode inventory differs from archive")
    return dict(archive_basename=path.name, sha256=record["sha256"], bytes=record["bytes"], member_count=len(names),
                raw_members_sha256=canonical_action(members), all_members_and_originals_verified=True)


def validate_group(out, item, audit, lock, status):
    group = out / "bulk" / item["card"] / ("rank_%04d" % item["rank"])
    require(audit.get("schema") == AUDIT_SCHEMA and audit.get("passed") is True, "Whole group v2 audit did not pass")
    gates = audit.get("gates", {})
    require(REQUIRED_V2_GATES <= set(gates) and all(value is True for value in gates.values()), "Missing/failed v2 gate")
    require(audit.get("archive_complete") is True and gates.get("all_started_cases_archived") is True, "Complete episode archive gate missing")
    require(audit.get("group_id") == item["group_id"] and audit.get("card") == item["card"]
            and int(audit.get("rank", -1)) == item["rank"] and audit.get("split") == item["split"], "Audited identity differs from frozen plan")
    require(status.get("audit_passed") is True and status.get("archive_complete") is True and not status.get("failed"), "Terminal status contains an unresolved group failure")
    paths = dict(capture=group / "control" / "public_capture" / "capture.json",
                 public_features=group / "control" / "public_capture" / "public_features.npz",
                 public_initial=Path(lock["public_inputs"][item["card"]]["initial_path"]),
                 pair_audit=group / "pair_audit.json", availability=group / "availability.json")
    capture = _read_json(paths["capture"])
    initial, loaded_capture, arrays = load_public(paths["public_initial"], paths["capture"], paths["public_features"])
    public_features = build_public_features(initial, loaded_capture, arrays)
    require(capture == loaded_capture, "Public loader changed the source capture")
    require(initial["task_card"]["card_id"] == item["card"], "Public initialization card drift")
    require(capture["rank"] == item["rank"] and capture["prefix_sha256"] == item["reached_prefix_action_sha256"], "Public reached-state identity drift")
    require(canonical_action({k:v for k,v in capture["snapshot"].items() if k != "wallclock"}) == item["cut_snapshot_sha256"], "Public cut snapshot drift")
    names, labels, baseline, trainable = _candidate_contract(capture, audit)
    require([a.name for a in public_features.actions] == names, "Public feature adapter changed candidate inventory")
    availability = _read_json(paths["availability"])
    _availability_contract(availability, audit, capture, item, paths)
    require(availability["source_lock_sha256"] == lock["frozen_teacher_source_lock_sha256"], "Public availability source identity drift")
    require(set(status["scheduled_cases"]) == set(status["finished_cases"]) == set(names)
            and len(status["finished_cases"]) == len(names), "Terminal case inventory is incomplete/duplicated")
    signs = dict(positive=0, negative=0, tie=0)
    for name, label in labels.items():
        require(label.get("valid_full_season_pair") is True, "Invalid full continuation label")
        values = [label["component_delta"][k] for k in COMPONENTS]
        require(all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) for v in values), "Nonfinite component label")
        require(abs(sum(values) - label["advantage"]) <= 1e-5, "Auditor total/component label mismatch")
        value = label["advantage"]
        signs["positive" if value > 1e-6 else "negative" if value < -1e-6 else "tie"] += 1
    require(signs == audit["sign_counts"] == status["sign_counts"], "Auditor/terminal sign inventory mismatch")
    records = audit["archive"]
    require(len(records) == len(names), "Audited archive inventory incomplete")
    archives = {Path(record["path"]).name:record for record in records}
    require(len(archives) == len(names), "Duplicate episode archive record")
    receipts = []
    for name in names:
        basename = "bulk_%s_rank%d_%s.tar.gz" % (item["card"], item["rank"], name)
        require(basename in archives, "Wrong episode archive identity")
        receipts.append(dict(case=name, **archive_receipt(archives[basename], group / name)))
    return paths, dict(group_id=item["group_id"], card=item["card"], rank=item["rank"], split=item["split"],
                       trainable=trainable, trainable_reason=audit["trainable_reason"], available_cases=names,
                       absent_cases=audit.get("absent_cases", []), sign_counts=signs, archives=receipts)


def inventory(root):
    return {str(p.relative_to(root)).replace("\\", "/"):sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def bundle(root, destination):
    with tarfile.open(destination, "w:gz", compresslevel=6) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(root)), recursive=False)
    return dict(path=destination.name, bytes=destination.stat().st_size, sha256=sha(destination))


def build(args):
    require(not args.destination.exists(), "Destination already exists; refuse to rewrite evidence")
    # A progress file/lock does not prove completion. A terminal driver summary is mandatory.
    summary_path = args.out / "bulk_summary.json"
    summary = _read_json(summary_path)
    summary_sha256 = sha(summary_path)
    require(summary.get("lock_evidence") == dict(source_files_unchanged=True, full_inputs_unchanged=True), "Terminal source/input check failed")
    lock, source, plan = verify_lock(args.out, args.reviewed_lock_sha256, args.participant, args.kit)
    status_list = summary["groups"]
    status = {entry["group_id"]:entry for entry in status_list}
    require(len(status) == len(status_list) and set(status) == {g["group_id"] for g in plan["groups"]}, "Terminal summary does not cover the complete frozen plan")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="dataset_unaccepted_", dir=args.destination.parent))
    try:
        partition_records = {"fit_validation":[], "sealed_test":[]}
        outcome_records = {"fit_validation":[], "sealed_test":[]}
        raw_inputs = {}
        for partition in partition_records:
            root = staging / partition
            root.mkdir()
            for filename in ("bulk_source_lock.json", "source_lock.json", "bulk_plan.json"):
                checked_copy(args.out / filename, root / "provenance" / filename)
        for item in plan["groups"]:
            partition = "sealed_test" if item["card"] == "L4" else "fit_validation"
            root = staging / partition
            group = args.out / "bulk" / item["card"] / ("rank_%04d" % item["rank"])
            audit_path = group / "pair_audit.json"
            entry = dict(group_id=item["group_id"], card=item["card"], rank=item["rank"], split=item["split"],
                         accepted=False, failures=status[item["group_id"]].get("failed", []),
                         terminal_status=status[item["group_id"]])
            # Completed failed/absent groups remain explicit; there is no sign filtering.
            if audit_path.exists():
                audit = _read_json(audit_path)
                checked_copy(audit_path, root / "outcomes" / item["group_id"] / "pair_audit.json")
                entry["audit_sha256"] = sha(audit_path)
            else:
                audit = None
            try:
                require(audit is not None, "No whole-group audit; terminal failure/timeout retained")
                paths, verified = validate_group(args.out, item, audit, lock, status[item["group_id"]])
                relative = dict(capture="groups/%s/control/public_capture/capture.json" % item["group_id"],
                                public_features="groups/%s/control/public_capture/public_features.npz" % item["group_id"],
                                public_initial="public/%s_initialize_public.json" % item["card"],
                                pair_audit="groups/%s/pair_audit.json" % item["group_id"],
                                availability="groups/%s/availability.json" % item["group_id"])
                hashes = {name:checked_copy(path, root / relative[name]) for name, path in paths.items()}
                raw_inputs.update({str(path):hashes[name] for name, path in paths.items()})
                checked_copy(Path(item["prefix_path"]), root / "provenance" / "prefixes" / (item["group_id"] + ".jsonl"), item["prefix_sha256"])
                partition_records[partition].append(dict(group_id=item["group_id"], card=item["card"], **relative, sha256=hashes))
                entry.update(verified, admission="verified_candidate_pending_root_acceptance")
            except (SchemaError, FileNotFoundError, KeyError, TypeError, ValueError, tarfile.TarError) as exc:
                entry.update(admission="excluded_explicitly", exclusion_reason=str(exc))
                # Preserve availability even when its identity/integrity gate fails.
                if (group / "availability.json").exists():
                    checked_copy(group / "availability.json", root / "outcomes" / item["group_id"] / "availability.json")
                for path in sorted(group.rglob("episode_failure.json")):
                    checked_copy(path, root / "outcomes" / item["group_id"] / str(path.relative_to(group)))
            outcome_records[partition].append(entry)
        # Fail the whole build if the frozen sources, terminal driver record, or
        # any accepted raw public/audit input drifted while the archives were read.
        verify_lock(args.out, args.reviewed_lock_sha256, args.participant, args.kit)
        require(sha(summary_path) == summary_sha256 and all(sha(Path(path)) == value for path,value in raw_inputs.items()), "Raw batch inputs changed during portable build")
        for partition in partition_records:
            root = staging / partition
            manifest = dict(schema=MANIFEST_SCHEMA, accepted=False,
                            acceptance_note="UNACCEPTED portable candidates. Root review and explicit separately hash-locked acceptance are required before fitting.",
                            groups=partition_records[partition], reviewed_bulk_source_lock_sha256=args.reviewed_lock_sha256,
                            split_contract=dict(train_cards=["L1", "L2"], validation_card="L3", untouched_test_card="L4",
                                                unit="whole_state_group/card", partition=partition,
                                                sealed_test_never_transported_to_fitting_workspace=True,
                                                control_only="preserved; verified but never included in pair fitting"))
            write_json(root / "candidate_manifest.json", manifest)
            write_json(root / "outcome_inventory.json", dict(schema="causal-student-dataset-outcomes-v1", records=outcome_records[partition],
                       all_predeclared_groups_in_partition_recorded=True, no_sign_selection=True, accepted=False))
            write_json(root / "files_sha256.json", dict(schema="portable-dataset-file-lock-v1", files=inventory(root)))
        # Parent index reports no L4 outcomes/returns/signs, only its sealed bundle hash.
        receipts = {partition:bundle(staging / partition, staging / (partition + ".tar.gz")) for partition in partition_records}
        fit_records = outcome_records["fit_validation"]
        index = dict(schema="causal-student-portable-bundles-v1", accepted=False, prepared_source_sha256=sha(Path(__file__)),
                     reviewed_bulk_source_lock_sha256=args.reviewed_lock_sha256, terminal_summary_sha256=summary_sha256,
                     bundles=receipts, fit_validation_groups=len(partition_records["fit_validation"]),
                     fit_validation_trainable_groups=sum(r.get("trainable", False) for r in fit_records),
                     fit_validation_excluded=[dict(group_id=r["group_id"], reason=r["exclusion_reason"]) for r in fit_records if r["admission"] == "excluded_explicitly"],
                     sealed_test_predeclared_groups=sum(g["card"] == "L4" for g in plan["groups"]),
                     actual_training_started=False, raw_terminal_score_relabeling=False)
        write_json(staging / "bundle_index.json", index)
        staging.rename(args.destination)
        print(json.dumps(index, indent=2))
    except BaseException:
        # Preserve partial verification evidence rather than pretending the build passed.
        write_json(staging / "BUILD_FAILED.json", dict(accepted=False, raw_retained=True, destination=str(args.destination)))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Original terminal teacher output tree")
    parser.add_argument("--participant", type=Path, required=True, help="Frozen participant source directory")
    parser.add_argument("--kit", type=Path, required=True, help="Frozen official example/evaluator kit")
    parser.add_argument("--destination", type=Path, required=True, help="New portable output directory")
    parser.add_argument("--reviewed-lock-sha256", required=True)
    build(parser.parse_args())


if __name__ == "__main__":
    main()
