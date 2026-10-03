#!/usr/bin/env python3
"""Freeze one source and run production vs NN hook on official whole seasons."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/"results/cold_neural_value_20261003"
OFFICIAL=BASE/"upstream/gosim-observer-examples"

def prepare():
    project=OUT/"production_frozen"
    project.mkdir(parents=True,exist_ok=True)
    paths=list(BASE.glob("*.py"))+list((BASE/"research").glob("*.py"))
    paths += [p for p in (OFFICIAL/"python").rglob("*.py") if "__pycache__" not in p.parts]
    manifest={}
    for source in paths:
        relative=source.relative_to(BASE);dest=project/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        data=source.read_bytes();dest.write_bytes(data)
        manifest[str(relative)]=hashlib.sha256(data).hexdigest()
    data=(OUT/"model.npz").read_bytes()
    (project/"research/cold_neural_model.npz").write_bytes(data)
    manifest["research/cold_neural_model.npz"]=hashlib.sha256(data).hexdigest()
    cfg={"neural_continuation_strength":.3}
    cfgpath=BASE/"policy_config.json"
    if cfgpath.exists():cfg={**json.loads(cfgpath.read_text()),**cfg}
    data=(json.dumps(cfg,indent=2)+"\n").encode();(project/"policy_config.json").write_bytes(data)
    manifest["policy_config.json"]=hashlib.sha256(data).hexdigest()
    (OUT/"production_manifest.json").write_text(json.dumps({"utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
        "files_sha256":manifest,"config":cfg,"remote_included":False,"model_training_cards":["L1","L2"],
        "validation":"L3","heldout":"L4","model_reason":"integration probe; preliminary compressed teacher"},indent=2))
    return project

def run(project,mode,card):
    output=OUT/f"production_pair/{mode}/{card}";output.mkdir(parents=True,exist_ok=True)
    entry="agent.py" if mode=="baseline" else "research/agent_cold_neural_direct.py"
    command=[sys.executable,str(OFFICIAL/"runner/run_local.py"),"--card",str(OFFICIAL/"local-cards"/card),
        "--agent",shlex.join([sys.executable,"-u",entry]),"--agent-cwd",str(project),"--wallclock","900",
        "--out",str(output),"--quiet","--inherit-env"]
    environment={**os.environ,"OPENBLAS_NUM_THREADS":"1","OMP_NUM_THREADS":"1","MKL_NUM_THREADS":"1"}
    started=time.monotonic()
    print(json.dumps({"event":"start","mode":mode,"card":card}),flush=True)
    with (output/"driver.log").open("w") as h:
        p=subprocess.run(command,stdout=h,stderr=subprocess.STDOUT,env=environment,timeout=1020)
    report=json.loads((output/"score_report.json").read_text()) if (output/"score_report.json").exists() else {}
    result={"mode":mode,"card":card,"exit_code":p.returncode,"seconds":time.monotonic()-started,
        "score":report.get("total"),"components":report.get("components"),"counts":report.get("counts"),
        "termination":report.get("termination")}
    print(json.dumps(result),flush=True)
    return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--cards",nargs="+",default=["L3"])
    ap.add_argument("--reuse",action="store_true");a=ap.parse_args()
    project=OUT/"production_frozen" if a.reuse else prepare()
    results=[]
    with ThreadPoolExecutor(max_workers=2) as ex:
        for card in a.cards:
            futures=[ex.submit(run,project,m,card) for m in ["baseline","neural"]]
            for f in as_completed(futures):
                results.append(f.result());(OUT/"production_pair_summary.json").write_text(json.dumps(results,indent=2))

if __name__=="__main__":main()
