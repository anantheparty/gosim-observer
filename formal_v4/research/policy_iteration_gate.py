"""Full official protocol teacher; locked source and explicit prefix/suffix modes."""
from __future__ import annotations

import argparse
import base64
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

IMAGE = "python@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016"
EXPECTED = dict(L1=6362.021539,L2=6823.661561,L3=6004.504542,L4=5974.281941)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(project):
    return {str(p.relative_to(project)):sha(p) for p in sorted(project.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def run(case, slot, args):
    source = manifest(args.project)
    lock = json.loads((args.out/"source_lock.json").read_text())
    assert source == lock["participant"], "Participant source-lock drift"
    assert sha(Path(__file__).resolve()) == lock["harness_sha256"], "Teacher harness source-lock drift"
    assert all(sha(args.kit/name)==expected for name,expected in lock["official"].items()), "Official runner source-lock drift"
    output = args.out/args.phase/args.card/f"rank_{args.rank:04d}"/case
    output.mkdir(parents=True,exist_ok=True)
    public_capture=output/"public_capture"
    public_capture.mkdir(exist_ok=True)
    assert not any(public_capture.iterdir()), "Public capture output must start empty"
    public_capture.chmod(0o777)
    cpus = f"{slot*2},{slot*2+1}"
    container_name=f"policy-iteration-{args.phase}-{args.card.lower()}-{args.rank}-{case}"
    owner_label=sha(args.out/"source_lock.json")
    existing=subprocess.run(["docker","inspect",container_name],capture_output=True,text=True,timeout=15)
    assert existing.returncode != 0, "A prior container with this case name exists; refusing blind restart"
    container = ["docker","run","--rm","--interactive","--user","1000:1000",
        "--name",container_name,"--label",f"policy_iteration.source_lock={owner_label}",
        "--cpus","2","--cpuset-cpus",cpus,"--memory","2048m","--memory-swap","2048m",
        "--pids-limit","128","--cap-drop=ALL","--security-opt=no-new-privileges","--read-only",
        "--tmpfs","/tmp:rw,nosuid,size=256m","--network","none","--log-driver","none",
        "--mount",f"type=bind,src={args.project.resolve()},dst=/workspace,readonly",
        "--mount",f"type=bind,src={args.dependencies.resolve()},dst=/deps,readonly",
        "--mount",f"type=bind,src={public_capture.resolve()},dst=/capture",
        "--workdir","/workspace","--env","PYTHONPATH=/deps","--env","PYTHONDONTWRITEBYTECODE=1",
        "--env","POLICY_ITERATION_CAPTURE_DIR=/capture",
        "--env","OPENBLAS_NUM_THREADS=1","--env","OMP_NUM_THREADS=1","--env","MKL_NUM_THREADS=1",
        "--env",f"POLICY_ITERATION_CASE={case}","--env",f"POLICY_ITERATION_RANK={args.rank}"]
    if args.phase == "natural_control":
        container += ["--env","POLICY_ITERATION_TRACE=1"]
    if args.prefix:
        container += ["--mount",f"type=bind,src={args.prefix.resolve()},dst=/public_prefix.jsonl,readonly",
                      "--env","POLICY_ITERATION_PREFIX=/public_prefix.jsonl"]
    container += [IMAGE,"python3","-u","-m","research.policy_iteration_agent"]
    command = [sys.executable,str(args.kit/"runner/run_local.py"),"--card",str(args.kit/"local-cards"/args.card),
               "--agent",shlex.join(container),"--agent-cwd",str(args.project),"--wallclock","900",
               "--out",str(output),"--quiet"]
    begin=time.monotonic()
    cleanup=dict(name=container_name,checked=False,owned_cleanup=False)
    print(json.dumps(dict(event="launch",phase=args.phase,card=args.card,rank=args.rank,case=case,cpus=cpus)),flush=True)
    with (output/"driver.log").open("w") as log:
        try:
            completed=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=990)
            exit_code=completed.returncode
        except subprocess.TimeoutExpired:
            exit_code=-9
        finally:
            inspect=subprocess.run(["docker","inspect",container_name],capture_output=True,text=True,timeout=15)
            cleanup["checked"]=True
            cleanup["exists_after_driver"]=inspect.returncode==0
            if inspect.returncode==0:
                metadata=json.loads(inspect.stdout)[0]
                owned=metadata.get("Config",{}).get("Labels",{}).get("policy_iteration.source_lock")==owner_label
                cleanup.update(container_id=metadata.get("Id"),state=metadata.get("State",{}).get("Status"),owner_label_match=owned)
                assert owned, "Remaining container owner mismatch; refusing cleanup"
                removed=subprocess.run(["docker","rm","--force",container_name],capture_output=True,text=True,timeout=30)
                cleanup["owned_cleanup"]=removed.returncode==0
                recheck=subprocess.run(["docker","inspect",container_name],capture_output=True,text=True,timeout=15)
                cleanup["exists_after_cleanup"]=recheck.returncode==0
    score=json.loads((output/"score_report.json").read_text()) if (output/"score_report.json").exists() else {}
    workflow=json.loads((output/"workflow_result.json").read_text()) if (output/"workflow_result.json").exists() else {}
    log=(output/"agent.log").read_text() if (output/"agent.log").exists() else ""
    records=[]
    for line in log.splitlines():
        try:
            value=json.loads(line)
            if isinstance(value,dict):records.append(value)
        except ValueError:pass
    captures=[json.loads((public_capture/"capture.json").read_text())] if (public_capture/"capture.json").exists() else []
    capture=captures[0] if len(captures)==1 else {}
    if capture:
        blob=(public_capture/"public_features.npz").read_bytes()
        (output/"public_features.npz").write_bytes(blob)
        assert capture["feature_blob_sha256"]==hashlib.sha256(blob).hexdigest(), "Participant public feature output hash mismatch"
        (output/"capture.json").write_text(json.dumps(capture,indent=2)+"\n")
    traces=[json.loads(line) for line in (public_capture/"public_trace.jsonl").read_text().splitlines()] if (public_capture/"public_trace.jsonl").exists() else []
    if traces:
        (output/"public_prefix.jsonl").write_text("".join(json.dumps(r,separators=(",",":"))+"\n" for r in traces))
    summary=records[-1] if records else {}
    result=dict(case=case,phase=args.phase,card=args.card,rank=args.rank,total=score.get("total"),
        components=score.get("components"),counts=score.get("counts"),invalidations=score.get("invalidations"),
        observation_requests=score.get("observation_requests"),uniformity_bands=score.get("uniformity_bands"),
        termination=workflow.get("termination_reason"),exit_code=exit_code,seconds=time.monotonic()-begin,
        accounted_seconds=workflow.get("accounted_wallclock_seconds"),traceback="Traceback" in log,
        capture_count=len(captures),capture=capture,post_feedback=(public_capture/"post_feedback.json").exists(),
        participant_summary=summary,participant_has_truth_mount=False,source_lock_sha256=sha(args.out/"source_lock.json"),
        terminal_cleanup=cleanup,
        participant_input_mounts=[str(args.project.resolve()),str(args.dependencies.resolve())]+([str(args.prefix.resolve())] if args.prefix else []),
        participant_output_mount=dict(path=str(public_capture),destination="/capture",started_empty=True,
            provenance="Participant append-only reached public trace and cut features; official truth labels written outside this mount after termination",
            files={p.name:sha(p) for p in sorted(public_capture.iterdir()) if p.is_file()}),
        prefix_mode="forced_public_action_prediction_tape" if args.prefix else "natural_native_teacher",
        suffix_mode="natural_native_teacher",command=command)
    result["protocol_passed"]=exit_code==0 and result["termination"]=="survey_complete" and not result["traceback"]
    if case=="control":
        reference=args.reference/("protocol_gate_remaining" if args.card in ("L1","L3") else "protocol_gate_retry")/args.card
        if not reference.exists():
            reference=args.reference/"protocol_gate"/args.card
        result["ready_score_match"]=result["total"]==EXPECTED[args.card]
        if (reference/"actions.jsonl").exists() and (output/"actions.jsonl").exists():
            result["ready_all_actions_match"]=sha(reference/"actions.jsonl")==sha(output/"actions.jsonl")
            result["ready_score_components_match"]=score.get("components")==json.loads((reference/"score_report.json").read_text()).get("components")
    result["source_unchanged_after"]=manifest(args.project)==source
    result["teacher_valid"]=bool(result["protocol_passed"] and result["capture_count"]==1 and result["post_feedback"]
        and result["source_unchanged_after"] and (case!="control" or
            (result.get("ready_score_match") and result.get("ready_all_actions_match") and result.get("ready_score_components_match"))))
    # Truth factors belong exclusively to these terminal auxiliary labels.
    # They are never present in public_features.npz or participant mounts.
    terminal={}
    if (output/"observations.csv").exists():
        with (output/"observations.csv").open(newline="") as handle:
            for row in csv.DictReader(handle):
                item=terminal.setdefault(row["target_id"],dict(best_score=0.,max_factor=0.,valid_hits=0,invalid_hits=0))
                if row["valid"]=="true":
                    item["best_score"]=max(item["best_score"],float(row["score"]))
                    item["max_factor"]=max(item["max_factor"],float(row["factor"]))
                    item["valid_hits"]+=1
                else:
                    item["invalid_hits"]+=1
        (output/"terminal_target_labels.json").write_text(json.dumps(terminal,separators=(",",":"))+"\n")
    (output/"gate_result.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:result.get(k) for k in ("case","total","termination","seconds","protocol_passed","ready_score_match","ready_all_actions_match")}),flush=True)
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--project",type=Path,required=True)
    ap.add_argument("--dependencies",type=Path,required=True)
    ap.add_argument("--kit",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--reference",type=Path,required=True)
    ap.add_argument("--card",choices=list(EXPECTED),default="L1")
    ap.add_argument("--rank",type=int,default=64)
    ap.add_argument("--cases",nargs="+",default=["control"])
    ap.add_argument("--phase",default="natural_control")
    ap.add_argument("--prefix",type=Path)
    ap.add_argument("--jobs",type=int,default=4)
    ap.add_argument("--cpu-slot-offset",type=int,default=0)
    args=ap.parse_args()
    results=[]
    for first in range(0,len(args.cases),args.jobs):
        with ThreadPoolExecutor(max_workers=args.jobs) as ex:
            futures=[ex.submit(run,case,slot+args.cpu_slot_offset,args) for slot,case in enumerate(args.cases[first:first+args.jobs])]
            for future in as_completed(futures):
                results.append(future.result())
                (args.out/(args.phase+"_summary.json")).write_text(json.dumps(results,indent=2)+"\n")


if __name__=="__main__":
    main()
