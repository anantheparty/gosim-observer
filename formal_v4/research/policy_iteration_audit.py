"""Audit complete teacher branches, pair labels, and restoreable raw archives."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import tarfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def actions(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def episode_archive(directory, destination):
    members = {str(p.relative_to(directory)):sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}
    manifest = directory/"archive_members.json"
    manifest.write_text(json.dumps(dict(schema="teacher-episode-member-lock-v1",members=members),indent=2)+"\n")
    with tarfile.open(destination,"w:gz",compresslevel=6) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.add(path,arcname=str(path.relative_to(directory)),recursive=False)
    assert destination.stat().st_size < 90*1024*1024, "Episode exceeds archive-size gate"
    with tarfile.open(destination,"r:gz") as archive:
        for name,expected in members.items():
            assert hashlib.sha256(archive.extractfile(name).read()).hexdigest()==expected
    return dict(path=str(destination),bytes=destination.stat().st_size,sha256=sha(destination),member_count=len(members)+1)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--card",default="L1")
    ap.add_argument("--rank",type=int,default=64)
    ap.add_argument("--phase",default="pilot")
    ap.add_argument("--archive",action="store_true")
    args=ap.parse_args()
    group=args.out/args.phase/args.card/f"rank_{args.rank:04d}"
    directories=[p for p in sorted(group.iterdir()) if p.is_dir() and (p/"gate_result.json").exists()]
    results={p.name:json.loads((p/"gate_result.json").read_text()) for p in directories}
    natural=args.out/"natural_control"/args.card/f"rank_{args.rank:04d}"/"control"
    control=results.get("control",{})
    ccap=control.get("capture",{})
    native=actions(natural/"actions.jsonl") if (natural/"actions.jsonl").exists() else []
    ctr=actions(group/"control/actions.jsonl") if (group/"control/actions.jsonl").exists() else []
    gates=dict(control_exists=bool(control),control_protocol=bool(control.get("protocol_passed")),
        control_ready_score=bool(control.get("ready_score_match")),
        control_ready_all_actions=bool(control.get("ready_all_actions_match")),
        accelerated_control_identical_actions=ctr==native,
        all_sources_unchanged=all(r.get("source_unchanged_after") for r in results.values()),
        all_protocol_complete=all(r.get("protocol_passed") for r in results.values()),
        all_one_capture=all(r.get("capture_count")==1 for r in results.values()),
        all_post_feedback=all(r.get("post_feedback") for r in results.values()),
        all_same_public_prefix=all(r.get("capture",{}).get("prefix_sha256")==ccap.get("prefix_sha256") for r in results.values()),
        all_same_public_state_features=all(r.get("capture",{}).get("feature_blob_sha256")==ccap.get("feature_blob_sha256") for r in results.values()),
        all_natural_suffix=all(r.get("suffix_mode")=="natural_native_teacher" and
            r.get("participant_summary",{}).get("forced_suffix") is False for r in results.values()),
        no_participant_truth_mount=all(r.get("participant_has_truth_mount") is False for r in results.values()))
    labels=[]
    baseline_target=json.loads((group/"control/terminal_target_labels.json").read_text()) if control else {}
    for case,result in results.items():
        if case=="control":continue
        branch=actions(group/case/"actions.jsonl")
        cap=result.get("capture",{})
        comparable=gates["all_same_public_prefix"] and gates["all_same_public_state_features"] and result.get("protocol_passed") and control.get("protocol_passed")
        label=dict(case=case,valid_full_season_pair=bool(comparable),advantage=result.get("total",0)-control.get("total",0) if comparable else None,
            baseline_total=control.get("total"),branch_total=result.get("total"),
            component_delta={k:result["components"][k]-control["components"][k] for k in control.get("components",{})} if comparable else None,
            action_pair=[ccap.get("baseline_action"),cap.get("selected_action")],
            aligned_action_divergences=sum(a!=b for a,b in zip(ctr,branch)),action_count_delta=len(branch)-len(ctr),
            branch_observe_count=result.get("counts",{}).get("observe_actions"),
            baseline_observe_count=control.get("counts",{}).get("observe_actions"),
            invalidations=result.get("invalidations"),world_label="one_realized_future_world_MC_return")
        labels.append(label)
        terminal=json.loads((group/case/"terminal_target_labels.json").read_text())
        ids=sorted(set(baseline_target)|set(terminal))
        target_labels={}
        for target in ids:
            old=baseline_target.get(target,{})
            new=terminal.get(target,{})
            target_labels[target]=dict(science_delta=new.get("best_score",0)-old.get("best_score",0),
                threshold_delta=int(new.get("max_factor",0)>=.5)-int(old.get("max_factor",0)>=.5),
                valid_hit_delta=new.get("valid_hits",0)-old.get("valid_hits",0),
                invalid_hit_delta=new.get("invalid_hits",0)-old.get("invalid_hits",0))
        (group/case/"pair_target_aux_labels.json").write_text(json.dumps(target_labels,separators=(",",":"))+"\n")
    summary=dict(schema="policy-iteration-full-season-pair-audit-v1",card=args.card,rank=args.rank,gates=gates,
        passed=all(gates.values()),labels=labels,sign_counts=dict(positive=sum(x["advantage"]>1e-6 for x in labels if x["advantage"] is not None),
            negative=sum(x["advantage"]<-1e-6 for x in labels if x["advantage"] is not None),
            tie=sum(abs(x["advantage"])<=1e-6 for x in labels if x["advantage"] is not None)),
        sparse_zeros_preserved=True,heldout_unit="whole_state_group/card",archive=[])
    if args.archive:
        archive_dir=args.out/"archives";archive_dir.mkdir(exist_ok=True)
        for directory in directories:
            summary["archive"].append(episode_archive(directory,archive_dir/f"{args.phase}_{args.card}_rank{args.rank}_{directory.name}.tar.gz"))
    (group/"pair_audit.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(dict(passed=summary["passed"],gates=gates,sign_counts=summary["sign_counts"],labels=[{k:x[k] for k in ("case","advantage","aligned_action_divergences","action_count_delta")} for x in labels]),indent=2))


if __name__=="__main__":
    main()
