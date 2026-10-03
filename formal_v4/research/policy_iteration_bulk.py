"""Predeclare public calendar cuts; run control-first frozen teacher branches.

`prepare` produces reviewable plan/prefix/source locks, without simulations.
`launch` requires the reviewed lock SHA explicitly; no automatic launch exists.
"""
from __future__ import annotations

import argparse
import csv
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time
import traceback

from policy_iteration_gate import run, sha
from policy_iteration_bulk_audit import audit_group, archive_group_cases, validate_bulk_lock, canonical_ready, canonical_hash, public_snapshot_hash, public_capture_hash

CASES=("control","field","short","long","program")
SPLIT=dict(L1="train",L2="train",L3="validation",L4="test")
TERMINAL_FILES=("observations.csv","decisions.csv","messages.jsonl","score_report.json","workflow_result.json","gate_result.json","terminal_target_labels.json")


def utc(value):
    return datetime.fromisoformat(value.replace("Z","+00:00"))


def write_json(path,value):
    temporary=path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(value,indent=2)+"\n")
    temporary.replace(path)


def public_observe_states(initial,rows):
    """Derive timestamps from reached public actions and public night limits."""
    now,end=utc(initial["survey"]["start_utc"]),utc(initial["survey"]["end_utc"])
    nights=[(utc(n["observing_start_utc"]),utc(n["observing_end_utc"])) for n in initial["survey"]["nights"]]
    prefix_hash=hashlib.sha256()
    states=[]
    for index,row in enumerate(rows):
        action=row["action"]
        kind=action.get("action")
        if kind=="observe":
            states.append(dict(row_index=index,rank=int(row["rank"]),now_utc=now.isoformat(),step=row["step"],
                cut_snapshot_sha256=row["snapshot_sha256"],reached_prefix_action_sha256=prefix_hash.hexdigest()))
            exposure_end=min(now+timedelta(seconds=action["duration_seconds"]),end)
            night=next(((a,b) for a,b in nights if a<=now<b),None)
            now=min(exposure_end,night[1]) if night else exposure_end
        elif kind=="wait":
            now=min(utc(action["until_utc"]) if "until_utc" in action else now+timedelta(seconds=action["duration_seconds"]),end)
        prefix_hash.update((json.dumps(action,sort_keys=True,separators=(",",":"))+"\n").encode())
    return states


def prepare(args):
    source_sha=sha(args.out/"source_lock.json")
    plan_path=args.out/"bulk_plan.json"
    assert not plan_path.exists(), "An existing predeclaration is immutable; use a separately reviewed revision"
    prefix_dir=args.out/"bulk_prefixes";prefix_dir.mkdir(exist_ok=True)
    groups,absent,shared=[],[],{}
    # Actual early and late accelerated controls fit a fixed prefix/capture cost
    # plus native suffix cost. Card scaling is based on complete natural walltime.
    early=403.74673504999327;late=79.59704329998931
    native_unit=(early-late)/((1-64/981)-(1-858/981))
    fixed=late-native_unit*(1-858/981)
    natural_l1=json.loads((args.out/"natural_control/L1/rank_0064/control/gate_result.json").read_text())["seconds"]
    for card in SPLIT:
        natural,gate,valid=canonical_ready(args.out,card,source_sha)
        assert valid, f"Canonical natural READY gate failed: {card}"
        init_path=args.out/(card+"_initialize_public.json")
        initial=json.loads(init_path.read_text())
        trace=natural/"public_prefix.jsonl"
        rows=[json.loads(line) for line in trace.read_text().splitlines()]
        states=public_observe_states(initial,rows)
        assert len(states)==gate["counts"]["observe_actions"]
        assert [s["rank"] for s in states]==list(range(len(states)))
        # Validation only: these three official columns are public action/time
        # metadata. No validity, score, factor, or future weather is used here.
        with (natural/"decisions.csv").open(newline="") as handle:
            public_decisions=[(int(row["observe_index"]),utc(row["start_utc"])) for row in csv.DictReader(handle) if row["action"]=="observe"]
        assert [(s["rank"],utc(s["now_utc"])) for s in states]==public_decisions, f"Public clock reconstruction mismatch: {card}"
        start,end=utc(initial["survey"]["start_utc"]),utc(initial["survey"]["end_utc"])
        shared[card]=dict(initial_path=str(init_path.resolve()),initial_sha256=sha(init_path),
            canonical_gate_sha256=sha(natural/"gate_result.json"),canonical_actions_sha256=sha(natural/"actions.jsonl"),
            canonical_score_sha256=sha(natural/"score_report.json"),
            public_trace_sha256=sha(trace),natural_wall_seconds=gate["seconds"],natural_observe_count=len(states))
        seen={}
        for stratum in range(16):
            quantile=(2*stratum+1)/32
            threshold=start+(end-start)*quantile
            selected=next((s for s in states if utc(s["now_utc"])>=threshold),None)
            base=dict(card=card,split=SPLIT[card],stratum=stratum,calendar_mid_quantile=quantile,threshold_utc=threshold.isoformat())
            if selected is None:
                absent.append(dict(**base,reason="no_reached_observe_state_at_or_after_threshold"));continue
            rank=selected["rank"]
            if rank in seen:
                absent.append(dict(**base,rank=rank,reason="duplicate_rank",same_group_id=seen[rank]));continue
            group_id=f"{card}_q{stratum:02d}_rank{rank:04d}"
            seen[rank]=group_id
            prefix_rows=[r for r in rows if int(r["rank"])<rank]
            prefix_path=prefix_dir/f"{group_id}.jsonl"
            assert not prefix_path.exists()
            prefix_path.write_text("".join(json.dumps(r,separators=(",",":"))+"\n" for r in prefix_rows))
            suffix_fraction=1-rank/len(states)
            scale=gate["seconds"]/natural_l1
            estimated_seconds=(fixed+native_unit*suffix_fraction)*scale
            groups.append(dict(**base,**selected,group_id=group_id,prefix_path=str(prefix_path.resolve()),
                prefix_sha256=sha(prefix_path),prefix_rows=len(prefix_rows),prefix_max_rank=max((r["rank"] for r in prefix_rows),default=None),
                forced_prefix_mode="strictly_past_public_actions_predictions_metadata",suffix_mode="fresh_natural_native_replanning",
                remaining_observe_fraction=suffix_fraction,estimated_case_wall_seconds=estimated_seconds))
    # Calendar strata are balanced across cards before moving to the next time bin.
    groups.sort(key=lambda g:(g["stratum"],g["card"]))
    upper_episodes=len(groups)*5
    worker_wall=sum(g["estimated_case_wall_seconds"]*5 for g in groups)
    plan=dict(schema="policy-iteration-bulk-predeclaration-v1",created_utc=datetime.now(timezone.utc).isoformat(),
        source_lock_sha256=source_sha,groups=groups,absent_strata=absent,shared_public_sidecars=shared,
        selection_rule="16 calendar mid-quantiles per card; first reached observe state at/after each threshold; deduplicate rank; never reward/label selected",
        candidate_rule="control first; freeze exact distinct current-public capture actions before terminal labels; execute all available alternatives only after exact READY control gate; record absent candidates",
        case_order=list(CASES),upper_state_groups=len(groups),upper_episodes=upper_episodes,
        upper_relative_labels=len(groups)*4,group_split_counts={split:sum(g["split"]==split for g in groups) for split in SPLIT.values()},
        label_semantics="one realized future world Monte Carlo continuation per group; not exact expected conditional return; pairs do not increase independent state count",
        training_limits="At most 32 training state groups; only a small structured or pairwise model pilot; no complex graph generalization claim",
        auxiliary_precision="unused; rounded CSV factors near 0.5 +/-0.5e-6 require masking if later used",
        feature_provenance="delivered public initialization/messages/feedback ledger and predictable geometry; shared catalog once; all actions in a group share one capture/NPZ",
        failure_rule="archive every started case and failure; no source/rank replacement or sign filtering; invalid group excluded from learning with explicit reason",
        resources=dict(jobs=8,physical_cpu_slots={str(i):f"{i*2},{i*2+1}" for i in range(8)},container_cpus=2,container_memory_mib=2048,
            idle_physical_cores="16..23",smt_used=False,gpu_teacher=False),
        budget=dict(measured_early_case_seconds=early,measured_late_control_seconds=late,fitted_fixed_seconds=fixed,
            fitted_suffix_seconds=native_unit,estimated_worker_wall_seconds=worker_wall,estimated_elapsed_seconds_at8workers=worker_wall/8,
            conservative_elapsed_seconds_at8workers=worker_wall*1.5/8+1200,max_elapsed_seconds=6*3600,
            deadline_semantics="Stop starting jobs at six hours; running drivers retain their 990-second timeout, followed by up to 60 seconds owned cleanup and host archive overhead",
            max_episode_timeout_seconds=990,estimate_caveat="Native replanning/action changes/card density can alter cost; use actual worker walltime, never divide by two CPU quota"))
    write_json(plan_path,plan)
    source_files=[Path(__file__).resolve(),Path(__file__).with_name("policy_iteration_bulk_audit.py").resolve(),
        Path(__file__).with_name("policy_iteration_gate.py").resolve(),Path(__file__).with_name("policy_iteration_audit.py").resolve()]
    lock=dict(schema="policy-iteration-bulk-source-lock-v1",frozen_teacher_source_lock_sha256=source_sha,
        files={str(p):sha(p) for p in source_files},plan_sha256=sha(plan_path),prefixes={g["group_id"]:g["prefix_sha256"] for g in groups},
        public_inputs=shared,resources=plan["resources"],requires_explicit_root_reviewed_sha=True)
    write_json(args.out/"bulk_source_lock.json",lock)
    print(json.dumps(dict(plan_sha256=sha(plan_path),bulk_source_lock_sha256=sha(args.out/"bulk_source_lock.json"),
        groups=len(groups),absent_strata=len(absent),budget=plan["budget"]),indent=2))


def freeze_availability(args,item,future):
    group=args.out/"bulk"/item["card"]/f"rank_{item['rank']:04d}"
    destination=group/"availability.json"
    if destination.exists():return json.loads(destination.read_text())
    control=group/"control"
    capture_path=control/"public_capture/capture.json"
    if not capture_path.exists():return None
    # These are existence checks only; the scheduling path never reads terminal labels.
    if future.done() or any((control/name).exists() for name in TERMINAL_FILES):return None
    try:
        raw=capture_path.read_bytes();capture=json.loads(raw)
    except (ValueError,OSError):return None  # Participant may still be completing its write.
    available=[case for case in CASES if case in capture["actions"]]
    assert "control" in available and set(available)==set(capture["actions"])
    hashes={case:canonical_hash(capture["actions"][case]) for case in available}
    assert len(set(hashes.values()))==len(hashes)
    blob_path=control/"public_capture/public_features.npz"
    if not blob_path.exists() or sha(blob_path)!=capture["feature_blob_sha256"]:return None
    if future.done() or any((control/name).exists() for name in TERMINAL_FILES):return None
    value=dict(schema="policy-iteration-public-availability-v1",planned_group_id=item["group_id"],card=item["card"],rank=item["rank"],
        frozen_at_utc=datetime.now(timezone.utc).isoformat(),source_lock_sha256=sha(args.out/"source_lock.json"),
        frozen_at_wall_ns=time.time_ns(),
        available_cases=available,absent_cases=[dict(case=case,reason=next((r["reason"] for r in capture.get("rejected",[]) if r["case"]==case),"unavailable_in_frozen_current_public_candidate_generator")) for case in CASES if case not in available],
        action_hashes=hashes,capture_sha256=hashlib.sha256(raw).hexdigest(),public_capture_state_sha256=public_capture_hash(capture),
        feature_blob_sha256=capture["feature_blob_sha256"],cut_snapshot_sha256=public_snapshot_hash(capture["snapshot"]),
        control_was_running=True,frozen_before_terminal=True,terminal_files_absent=list(TERMINAL_FILES),
        provenance="Read only current participant public output; before any terminal score/workflow/target label file exists")
    write_json(destination,value)
    assert not any((control/name).exists() for name in TERMINAL_FILES), "Terminal artifact appeared during public availability freeze; no alternative will be scheduled"
    return value


def launch(args):
    lock_path=args.out/"bulk_source_lock.json"
    assert sha(lock_path)==args.reviewed_lock_sha256, "Explicit reviewed bulk source-lock SHA is required"
    lock=json.loads(lock_path.read_text());plan_path=args.out/"bulk_plan.json";plan=json.loads(plan_path.read_text())
    assert sha(plan_path)==lock["plan_sha256"] and sha(args.out/"source_lock.json")==lock["frozen_teacher_source_lock_sha256"]
    assert all(sha(Path(p))==expected for p,expected in lock["files"].items())
    assert all(validate_bulk_lock(args.out,args.reviewed_lock_sha256).values())
    for card,shared in plan["shared_public_sidecars"].items():
        directory,_,valid=canonical_ready(args.out,card,plan["source_lock_sha256"])
        assert valid and sha(directory/"gate_result.json")==shared["canonical_gate_sha256"]
        assert sha(directory/"actions.jsonl")==shared["canonical_actions_sha256"]
        assert sha(directory/"score_report.json")==shared["canonical_score_sha256"]
        assert sha(directory/"public_prefix.jsonl")==shared["public_trace_sha256"]
        assert sha(Path(shared["initial_path"]))==shared["initial_sha256"]
    pending=deque((g,"control") for g in plan["groups"])
    status={g["group_id"]:dict(group_id=g["group_id"],scheduled_cases=["control"],finished_cases=[],failed=[],availability=None) for g in plan["groups"]}
    running={};free=deque(range(8));start=time.monotonic();stop_scheduling=False
    (args.out/"bulk").mkdir(exist_ok=True)
    assert not any((args.out/"bulk"/g["card"]/f"rank_{g['rank']:04d}").exists() for g in plan["groups"]), "Refusing blind restart of any existing group"
    assert not any((args.out/"archives").glob("bulk_*.tar.gz")), "Preexisting bulk archive would make outcome provenance ambiguous"
    write_json(args.out/"bulk_job.json",dict(start_utc=datetime.now(timezone.utc).isoformat(),pid=__import__("os").getpid(),
        reviewed_source_lock_sha256=args.reviewed_lock_sha256,resources=plan["resources"],max_elapsed_seconds=plan["budget"]["max_elapsed_seconds"]))
    with ThreadPoolExecutor(max_workers=8) as executor:
        while pending or running:
            if time.monotonic()-start>plan["budget"]["max_elapsed_seconds"]:stop_scheduling=True
            while pending and free and not stop_scheduling:
                item,case=pending.popleft();slot=free.popleft()
                assert sha(Path(item["prefix_path"]))==item["prefix_sha256"]
                if case!="control":
                    assert sha(args.out/"bulk"/item["card"]/f"rank_{item['rank']:04d}"/"availability.json")==status[item["group_id"]]["availability"]["sha256"]
                item_args=argparse.Namespace(**vars(args),card=item["card"],rank=item["rank"],phase="bulk",prefix=Path(item["prefix_path"]))
                future=executor.submit(run,case,slot,item_args)
                running[future]=(item,case,slot)
            for future,(item,case,slot) in list(running.items()):
                if case=="control" and status[item["group_id"]]["availability"] is None:
                    try:
                        value=freeze_availability(args,item,future)
                        if value:status[item["group_id"]]["availability"]=dict(sha256=sha(args.out/"bulk"/item["card"]/f"rank_{item['rank']:04d}"/"availability.json"),available_cases=value["available_cases"])
                    except Exception as exc:
                        status[item["group_id"]]["failed"].append(dict(stage="availability",error=repr(exc)))
                        status[item["group_id"]]["availability"]={"invalid":True}
            finished=wait(list(running),timeout=.1,return_when=FIRST_COMPLETED).done if running else set()
            for future in finished:
                item,case,slot=running.pop(future);free.append(slot);state=status[item["group_id"]]
                try:
                    result=future.result();valid=result.get("teacher_valid",False)
                except Exception as exc:
                    valid=False;state["failed"].append(dict(case=case,stage="episode",error=repr(exc),traceback=traceback.format_exc()))
                    failure_path=args.out/"bulk"/item["card"]/f"rank_{item['rank']:04d}"/case/"episode_failure.json"
                    failure_path.parent.mkdir(parents=True,exist_ok=True);write_json(failure_path,state["failed"][-1])
                state["finished_cases"].append(case)
                if not valid:state["failed"].append(dict(case=case,stage="gate",reason="full_teacher_or_READY_gate_failed"))
                if case=="control":
                    inventory=state["availability"]
                    if valid and inventory and not inventory.get("invalid"):
                        state["scheduled_cases"]=inventory["available_cases"]
                        pending.extend((item,alternative) for alternative in inventory["available_cases"] if alternative!="control")
                    else:
                        state["failed"].append(dict(stage="schedule",reason="control_gate_failed_or_no_preterminal_public_availability"))
                if set(state["finished_cases"])==set(state["scheduled_cases"]):
                    try:
                        if state["availability"] and not state["availability"].get("invalid"):
                            assert sha(args.out/"bulk"/item["card"]/f"rank_{item['rank']:04d}"/"availability.json")==state["availability"]["sha256"]
                        audit=audit_group(args.out,item,archive=True,reviewed_lock_sha=args.reviewed_lock_sha256)
                        state["audit_passed"]=audit["passed"];state["sign_counts"]=audit["sign_counts"];state["archive_complete"]=audit["archive_complete"]
                        if not audit["gates"]["source_files_unchanged"] or not audit["gates"]["full_inputs_unchanged"]:stop_scheduling=True
                    except Exception as exc:
                        state["failed"].append(dict(stage="audit_archive",error=repr(exc),traceback=traceback.format_exc()))
                        records=archive_group_cases(args.out,item)
                        state["fallback_archives"]=records;state["archive_complete"]=bool(records) and all(not r.get("archive_failed") for r in records)
                write_json(args.out/"bulk_progress.json",dict(elapsed_seconds=time.monotonic()-start,groups=list(status.values()),pending_jobs=len(pending),running_jobs=len(running),stop_scheduling=stop_scheduling))
            if stop_scheduling and not running:break
    for item,case in pending:status[item["group_id"]]["failed"].append(dict(case=case,stage="budget",reason="not_started_within_predeclared_wall_budget"))
    write_json(args.out/"bulk_summary.json",dict(elapsed_seconds=time.monotonic()-start,groups=list(status.values()),
        stop_scheduling=stop_scheduling,lock_evidence=validate_bulk_lock(args.out,args.reviewed_lock_sha256)))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("mode",choices=("prepare","launch"))
    for field in ("project","dependencies","kit","out","reference"):
        ap.add_argument("--"+field,type=Path,required=True)
    ap.add_argument("--reviewed-lock-sha256")
    args=ap.parse_args()
    if args.mode=="prepare":prepare(args)
    else:
        assert args.reviewed_lock_sha256
        launch(args)


if __name__=="__main__":
    main()
