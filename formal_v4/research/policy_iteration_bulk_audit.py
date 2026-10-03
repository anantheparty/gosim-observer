"""Bulk audit using the canonical full natural READY control for each card.

No teacher or frozen harness modifications. Failed and absent cases remain
visible; a label is valid only after the whole declared available inventory
passes complete-season gates. Terminal factors are not learning inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile

from policy_iteration_audit import actions, sha
from policy_iteration_gate import EXPECTED


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def public_snapshot_hash(snapshot):
    return canonical_hash({k:v for k,v in snapshot.items() if k!="wallclock"})


def public_capture_hash(capture):
    value={k:v for k,v in capture.items() if k not in ("case","selected_action")}
    value["snapshot"]={k:v for k,v in value.get("snapshot",{}).items() if k!="wallclock"}
    return canonical_hash(value)


def canonical_ready(out, card, source_sha):
    directory=out/"natural_control"/card/"rank_0064"/"control"
    gate=json.loads((directory/"gate_result.json").read_text())
    score=json.loads((directory/"score_report.json").read_text())
    valid=bool(gate.get("teacher_valid") and gate.get("ready_score_match")
        and gate.get("ready_all_actions_match") and gate.get("ready_score_components_match")
        and gate.get("source_unchanged_after") and gate.get("source_lock_sha256")==source_sha
        and gate.get("total")==EXPECTED[card] and score.get("total")==EXPECTED[card]
        and score.get("components")==gate.get("components"))
    return directory,gate,valid


def validate_bulk_lock(out, reviewed_sha):
    path=out/"bulk_source_lock.json";lock=json.loads(path.read_text())
    plan_path=out/"bulk_plan.json";plan=json.loads(plan_path.read_text())
    sources=sha(path)==reviewed_sha and sha(out/"source_lock.json")==lock["frozen_teacher_source_lock_sha256"] and all(sha(Path(p))==value for p,value in lock["files"].items())
    inputs=sha(plan_path)==lock["plan_sha256"] and all(sha(Path(g["prefix_path"]))==g["prefix_sha256"] for g in plan["groups"])
    for card,value in lock["public_inputs"].items():
        directory=out/"natural_control"/card/"rank_0064/control"
        inputs=inputs and sha(Path(value["initial_path"]))==value["initial_sha256"] and all(sha(directory/name)==value[key] for name,key in
            (("gate_result.json","canonical_gate_sha256"),("actions.jsonl","canonical_actions_sha256"),("score_report.json","canonical_score_sha256"),("public_prefix.jsonl","public_trace_sha256")))
    return dict(source_files_unchanged=sources,full_inputs_unchanged=inputs)


def archive_case(directory,destination):
    """Idempotent verified archive; manifest excludes its own bytes."""
    if not destination.exists():
        members={str(p.relative_to(directory)):sha(p) for p in sorted(directory.rglob("*")) if p.is_file() and p.name!="archive_members_bulk.json"}
        (directory/"archive_members_bulk.json").write_text(json.dumps(dict(schema="teacher-episode-member-lock-v2",members=members),indent=2)+"\n")
        with tarfile.open(destination,"w:gz",compresslevel=6) as archive:
            for path in sorted(directory.rglob("*")):
                if path.is_file():archive.add(path,arcname=str(path.relative_to(directory)),recursive=False)
    assert destination.stat().st_size<90*1024*1024, "Archive exceeds 90MiB; raw retained"
    with tarfile.open(destination,"r:gz") as archive:
        members=json.loads(archive.extractfile("archive_members_bulk.json").read())["members"]
        assert all(hashlib.sha256(archive.extractfile(name).read()).hexdigest()==value for name,value in members.items())
        current={str(p.relative_to(directory)):sha(p) for p in sorted(directory.rglob("*")) if p.is_file() and p.name!="archive_members_bulk.json"}
        assert current==members, "Existing archive differs from current raw case; refusing reuse"
    return dict(path=str(destination),bytes=destination.stat().st_size,sha256=sha(destination),member_count=len(members)+1)


def archive_group_cases(out,item,phase="bulk"):
    group=out/phase/item["card"]/f"rank_{item['rank']:04d}"
    destination=out/"archives";destination.mkdir(exist_ok=True)
    records=[]
    for directory in sorted(group.iterdir()):
        if not directory.is_dir() or directory.name not in ("control","field","short","long","program"):continue
        try:
            records.append(archive_case(directory,destination/f"{phase}_{item['card']}_rank{item['rank']}_{directory.name}.tar.gz"))
        except Exception as exc:records.append(dict(case=directory.name,archive_failed=repr(exc),raw_retained=str(directory)))
    return records


def audit_group(out, item, phase="bulk", archive=True, reviewed_lock_sha=None):
    card,rank=item["card"],item["rank"]
    group=out/phase/card/f"rank_{rank:04d}"
    source_sha=sha(out/"source_lock.json")
    natural,ngate,natural_valid=canonical_ready(out,card,source_sha)
    availability_path=group/"availability.json"
    availability=json.loads(availability_path.read_text()) if availability_path.exists() else {}
    expected=availability.get("available_cases",["control"])
    directories=[p for p in sorted(group.iterdir()) if p.is_dir() and p.name in ("control","field","short","long","program")]
    results={p.name:json.loads((p/"gate_result.json").read_text()) for p in directories if (p/"gate_result.json").exists()}
    control=results.get("control",{})
    ccap=control.get("capture",{})
    ctr=actions(group/"control/actions.jsonl") if (group/"control/actions.jsonl").exists() else []
    native=actions(natural/"actions.jsonl")
    prefix=Path(item["prefix_path"])
    prefix_rows=actions(prefix)
    prefix_valid=sha(prefix)==item["prefix_sha256"] and all(int(row["rank"])<rank for row in prefix_rows)
    available_unique=len(expected)==len(set(expected)) and len(set(availability.get("action_hashes",{}).values()))==len(expected)
    inventory=set(results)==set(expected) and set(p.name for p in directories)==set(expected)
    frozen_valid=bool(availability.get("frozen_before_terminal") and availability.get("control_was_running")
        and availability.get("source_lock_sha256")==source_sha and availability.get("planned_group_id")==item["group_id"]
        and availability.get("cut_snapshot_sha256")==item["cut_snapshot_sha256"]
        and availability.get("capture_sha256")==sha(group/"control/public_capture/capture.json")
        and availability.get("feature_blob_sha256")==ccap.get("feature_blob_sha256")) if ccap else False
    marker_names=("observations.csv","decisions.csv","messages.jsonl","score_report.json","workflow_result.json","gate_result.json","terminal_target_labels.json")
    frozen_valid=frozen_valid and set(availability.get("terminal_files_absent",[]))==set(marker_names) and all(
        (group/"control"/name).exists() and (group/"control"/name).stat().st_mtime_ns>availability.get("frozen_at_wall_ns",float("inf")) for name in marker_names)
    all_action_inventory=bool(ccap) and set(ccap.get("actions",{}))==set(expected) and all(
        canonical_hash(ccap["actions"][case])==availability.get("action_hashes",{}).get(case) for case in expected)
    submitted=True
    for case,result in results.items():
        path=group/case/"actions.jsonl"
        stream=actions(path) if path.exists() else []
        cut=item["row_index"]
        submitted=submitted and len(stream)>cut and stream[:cut]==native[:cut] and canonical_hash(stream[cut])==availability.get("action_hashes",{}).get(case)
    gates=dict(control_exists=bool(control),control_protocol=bool(control.get("protocol_passed")),
        control_ready_score=bool(control.get("ready_score_match")),control_ready_all_actions=bool(control.get("ready_all_actions_match")),
        canonical_natural_ready_source_valid=natural_valid,canonical_natural_rank64=True,
        accelerated_control_identical_actions=bool(ctr) and ctr==native,
        complete_declared_inventory=inventory,distinct_declared_action_inventory=available_unique,
        availability_frozen_before_terminal=frozen_valid,availability_matches_actual_public_candidates=all_action_inventory,
        strict_past_public_prefix=prefix_valid,
        all_sources_unchanged=bool(results) and all(r.get("source_unchanged_after") and r.get("source_lock_sha256")==source_sha for r in results.values()),
        all_protocol_complete=bool(results) and all(r.get("protocol_passed") for r in results.values()),
        all_teacher_valid=bool(results) and all(r.get("teacher_valid") for r in results.values()),
        all_one_capture=bool(results) and all(r.get("capture_count")==1 for r in results.values()),
        all_post_feedback=bool(results) and all(r.get("post_feedback") for r in results.values()),
        all_same_public_prefix=bool(results) and all(r.get("capture",{}).get("prefix_sha256")==item["reached_prefix_action_sha256"] for r in results.values()),
        all_same_public_state_features=bool(results) and all(r.get("capture",{}).get("feature_blob_sha256")==ccap.get("feature_blob_sha256") for r in results.values()),
        all_same_complete_public_capture=bool(results) and all(public_capture_hash(r.get("capture",{}))==public_capture_hash(ccap) for r in results.values()),
        all_gate_identity_matches_plan=bool(results) and all(r.get("card")==card and r.get("rank")==rank and r.get("case")==case and r.get("phase")==phase for case,r in results.items()),
        all_same_predeclared_cut=bool(results) and all(public_snapshot_hash(r.get("capture",{}).get("snapshot",{}))==item["cut_snapshot_sha256"] for r in results.values()),
        all_selected_predeclared_actions=bool(results) and all(canonical_hash(r.get("capture",{}).get("selected_action",{}))==availability.get("action_hashes",{}).get(case) for case,r in results.items()),
        all_submitted_prefix_and_cut_actions=bool(results) and submitted,
        all_natural_suffix=bool(results) and all(r.get("suffix_mode")=="natural_native_teacher" and r.get("participant_summary",{}).get("forced_suffix") is False for r in results.values()),
        no_participant_truth_mount=bool(results) and all(r.get("participant_has_truth_mount") is False for r in results.values()))
    lock_evidence=validate_bulk_lock(out,reviewed_lock_sha)
    gates.update(lock_evidence)
    passed=all(gates.values())
    labels=[]
    for case in expected:
        if case=="control":continue
        result=results.get(case,{})
        branch=actions(group/case/"actions.jsonl") if (group/case/"actions.jsonl").exists() else []
        labels.append(dict(case=case,valid_full_season_pair=passed,
            advantage=result["total"]-control["total"] if passed else None,
            baseline_total=control.get("total"),branch_total=result.get("total"),
            component_delta={k:result["components"][k]-control["components"][k] for k in control["components"]} if passed else None,
            action_pair=[ccap.get("baseline_action"),result.get("capture",{}).get("selected_action")],
            aligned_action_divergences=sum(a!=b for a,b in zip(ctr,branch)),action_count_delta=len(branch)-len(ctr),
            baseline_observe_count=control.get("counts",{}).get("observe_actions"),branch_observe_count=result.get("counts",{}).get("observe_actions"),
            invalidations=result.get("invalidations"),observation_requests=result.get("observation_requests"),
            counts=result.get("counts"),uniformity_bands=result.get("uniformity_bands"),
            world_label="one_realized_future_world_MC_return"))
    summary=dict(schema="policy-iteration-full-season-pair-audit-v2",card=card,rank=rank,group_id=item["group_id"],
        split=item["split"],gates=gates,passed=passed,labels=labels,available_cases=expected,baseline_total=control.get("total"),
        trainable=passed and len(expected)>1,trainable_reason="complete_available_full_season_pairs" if passed and len(expected)>1 else ("control_only_no_distinct_alternative" if passed else "group_gate_failure"),
        absent_cases=availability.get("absent_cases",[]),availability_path=str(availability_path),availability_sha256=sha(availability_path) if availability_path.exists() else None,
        canonical_natural_reference=dict(rank=64,gate_sha256=sha(natural/"gate_result.json"),actions_sha256=sha(natural/"actions.jsonl")),
        sign_counts=dict(positive=sum(x["advantage"]>1e-6 for x in labels if x["advantage"] is not None),
            negative=sum(x["advantage"]<-1e-6 for x in labels if x["advantage"] is not None),tie=sum(abs(x["advantage"])<=1e-6 for x in labels if x["advantage"] is not None)),
        heldout_unit="whole_state_group/card",sparse_zeros_preserved=True,
        auxiliary_labels="unused; raw rounded terminal factors retained; any later threshold auxiliary must mask 0.5 +/- 0.5e-6",
        archive=[])
    if archive:
        summary["archive"]=archive_group_cases(out,item,phase)
        summary["archive_complete"]=len(summary["archive"])==len(directories) and all(not record.get("archive_failed") for record in summary["archive"])
    else:summary["archive_complete"]=False
    gates["all_started_cases_archived"]=summary["archive_complete"]
    summary["passed"]=all(gates.values())
    if not summary["passed"]:
        summary["trainable"]=False;summary["trainable_reason"]="group_gate_or_archive_failure"
        for label in labels:
            label["valid_full_season_pair"]=False;label["advantage"]=None;label["component_delta"]=None
        summary["raw_sign_counts"]=summary["sign_counts"];summary["sign_counts"]=dict(positive=0,negative=0,tie=0)
    (group/"pair_audit.json").write_text(json.dumps(summary,indent=2)+"\n")
    return summary


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--plan",type=Path,required=True)
    ap.add_argument("--group",required=True)
    ap.add_argument("--reviewed-lock-sha256",required=True)
    args=ap.parse_args()
    item=next(x for x in json.loads(args.plan.read_text())["groups"] if x["group_id"]==args.group)
    result=audit_group(args.out,item,reviewed_lock_sha=args.reviewed_lock_sha256)
    print(json.dumps({k:result[k] for k in ("group_id","passed","gates","sign_counts")}))


if __name__=="__main__":
    main()
