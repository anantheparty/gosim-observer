#!/usr/bin/env python3
"""Bounded deterministic production do(wait) full-continuation teacher.

Unmodified public local evaluator; no practice truth. Fixed full candidate
enumeration removes wall-clock stopping variability. This is a behavior-policy
causal probe, not an optimum certificate or NN score demonstration.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/"results/cold_neural_value_20261003"
RUNS=BASE/"runs/cold_neural_value_20261003"
FROZEN=RUNS/"production_frozen"
OFFICIAL=BASE/"upstream/gosim-observer-examples"

def worker(card,skip):
    sys.path.insert(0,str(FROZEN));sys.path.insert(0,str(OFFICIAL))
    from runner.challenge.v4_workflow import V4Workflow
    from runner.challenge.v4_runner import run_scenario
    from research.spatial_candidates import SpatialPlanner
    import policy
    import numpy as np
    class DeterministicPlanner(SpatialPlanner):
        def choose(self,snapshot,scores,factors,env_estimate=None,active_requests=None):
            env=dict(env_estimate or {});env["planning_budget_seconds"]=30.
            return super().choose(snapshot,scores,factors,env,active_requests)
    policy.SpatialPlanner=DeterministicPlanner
    case="control" if skip<0 else f"skip_{skip}"
    raw=RUNS/f"counterfactual/{case}/{card}";raw.mkdir(parents=True,exist_ok=True)
    initial=V4Workflow(OFFICIAL/"local-cards"/card).initialize_payload(900)
    p=policy.Policy(initial)
    if p.remote is not None:raise ValueError("causal teacher must use CPU-only frozen policy")
    captures={};prefix=hashlib.sha256();skipped=False;calls=0;begin=time.monotonic()
    def decide(snapshot):
        nonlocal skipped,calls
        # The public callback state and full candidate pool are identical before
        # intervention. Policy feedback/ledger/model is restored by natural replay.
        action=p.decide(snapshot);a=snapshot["observe_action_index"]
        if action.get("action")=="observe" and a in [100,700] and str(a) not in captures:
            captures[str(a)]={"prefix_sha256":prefix.hexdigest(),"now_utc":snapshot["now_utc"],
                "baseline_action":action,"snapshot":snapshot,"scores_sum":float(p.scores.sum()),
                "required_unfinished":int((p.planner.required&(p.factor_lower<.5)).sum())}
            np.savez_compressed(raw/f"state_{a}.npz",scores=p.scores,factor_lower=p.factor_lower,
                factors=p.factors,quality_belief=np.array([p.C,p.E]))
        if action.get("action")=="observe" and a==skip and not skipped:
            duration=action["duration_seconds"]
            action={"action":"wait","duration_seconds":duration};p.pending=None
            p.planner.last_prediction={};skipped=True
        prefix.update((json.dumps(action,sort_keys=True,separators=(",",":"))+"\n").encode())
        calls+=1
        if calls%250==0:
            print(json.dumps({"event":"progress","case":case,"card":card,"calls":calls,
                "observe":a,"sim_time":snapshot["now_utc"],"seconds":time.monotonic()-begin}),flush=True)
        return action
    report=run_scenario(OFFICIAL/"local-cards"/card/"config/v4_scenario.json",lambda _:decide,raw)
    record={"case":case,"card":card,"skip_observe_index":skip,"seconds":time.monotonic()-begin,
        "pid":os.getpid(),"captures":captures,"total":report["total"],"components":report["components"],
        "counts":report["counts"],"termination":report["termination"],"policy_summary":p.summary(),
        "raw_directory":str(raw),"whole_candidate_enumeration":True}
    (OUT/f"counterfactual_{case}_{card}.json").write_text(json.dumps(record,indent=2))
    print(json.dumps({k:record[k] for k in ["case","card","total","seconds","termination"]}),flush=True)

def run_case(card,skip):
    case="control" if skip<0 else f"skip_{skip}";log=OUT/f"counterfactual_{case}_{card}.log"
    env={**os.environ,"OPENBLAS_NUM_THREADS":"1","OMP_NUM_THREADS":"1","MKL_NUM_THREADS":"1"}
    with log.open("w") as h:
        proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),"--worker","--card",card,"--skip",str(skip)],
            stdout=h,stderr=subprocess.STDOUT,env=env)
        print(json.dumps({"event":"launched","case":case,"card":card,"pid":proc.pid,"timeout_seconds":900}),flush=True)
        try:code=proc.wait(timeout=900)
        except subprocess.TimeoutExpired:proc.kill();proc.wait();code=-9
    return {"case":case,"card":card,"pid":proc.pid,"exit_code":code}

def driver(card):
    OUT.mkdir(parents=True,exist_ok=True)
    plan={"started_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"driver_pid":os.getpid(),
        "card":card,"cases":["control","skip_100","skip_700"],"per_process_timeout_seconds":900,
        "max_parallel":2,"wallclock_upper_bound_seconds":1800,
        "source_manifest":str(OUT/"production_manifest.json"),
        "intervention":"replace one actual production exposure by equal-duration wait, then complete same policy",
        "causal_limit":"only same-policy do(wait); deterministic candidate enumeration differs from runtime-cut production"}
    (OUT/"counterfactual_plan.json").write_text(json.dumps(plan,indent=2))
    results=[]
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures=[ex.submit(run_case,card,s) for s in [-1,100,700]]
        for f in as_completed(futures):
            results.append(f.result());(OUT/"counterfactual_status.json").write_text(json.dumps(results,indent=2))
    controlpath=OUT/f"counterfactual_control_{card}.json"
    if controlpath.exists():
        control=json.loads(controlpath.read_text());labels=[]
        for skip in [100,700]:
            path=OUT/f"counterfactual_skip_{skip}_{card}.json"
            if not path.exists():continue
            branch=json.loads(path.read_text());key=str(skip)
            valid=key in branch["captures"] and key in control["captures"] and \
                branch["captures"][key]["prefix_sha256"]==control["captures"][key]["prefix_sha256"]
            labels.append({"card":card,"skip":skip,"same_prefix":valid,
                "causal_advantage_observe_over_wait":control["total"]-branch["total"] if valid else None,
                "control_total":control["total"],"branch_total":branch["total"],
                "control_components":control["components"],"branch_components":branch["components"]})
        (OUT/"counterfactual_labels.json").write_text(json.dumps(labels,indent=2))
        print(json.dumps(labels),flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--worker",action="store_true")
    ap.add_argument("--card",choices=["L1","L2"],default="L1");ap.add_argument("--skip",type=int,default=-1)
    a=ap.parse_args()
    if a.worker:worker(a.card,a.skip)
    else:driver(a.card)

if __name__=="__main__":main()
