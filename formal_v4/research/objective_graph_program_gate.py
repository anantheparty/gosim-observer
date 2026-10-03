#!/usr/bin/env python3
"""Parallel two-core program-only causal continuation teacher on the official runner."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

IMAGE = "python@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016"


def run(case, cpus, args):
    output = args.out / case / "L2"
    output.mkdir(parents=True, exist_ok=True)
    container = ["docker", "run", "--rm", "--interactive", "--user", "1000:1000",
                 "--name", f"objective-graph-program-{case}", "--cpus", "2", "--cpuset-cpus", cpus,
                 "--memory", "2048m", "--memory-swap", "2048m", "--pids-limit", "128",
                 "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only",
                 "--tmpfs", "/tmp:rw,nosuid,size=256m", "--network", "none", "--log-driver", "none",
                 "--mount", f"type=bind,src={args.project.resolve()},dst=/workspace,readonly",
                 "--mount", f"type=bind,src={args.dependencies.resolve()},dst=/deps,readonly",
                 "--workdir", "/workspace", "--env", "PYTHONPATH=/deps",
                 "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "OPENBLAS_NUM_THREADS=1",
                 "--env", "OMP_NUM_THREADS=1", "--env", "MKL_NUM_THREADS=1",
                 "--env", f"OBJECTIVE_GRAPH_CASE={case}", IMAGE, "python3", "-u", "-m",
                 "research.objective_graph_program_agent"]
    command = [sys.executable, str(args.kit / "runner/run_local.py"), "--card",
               str(args.kit / "local-cards/L2"), "--agent", shlex.join(container), "--agent-cwd",
               str(args.project), "--wallclock", "900", "--out", str(output), "--quiet"]
    started = time.monotonic()
    print(json.dumps(dict(event="launch", case=case, cpus=cpus)), flush=True)
    with (output / "driver.log").open("w") as log:
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=980)
    score_path = output / "score_report.json"
    result = dict(case=case, cpus=cpus, exit_code=completed.returncode,
                  seconds=time.monotonic()-started, score_report=json.loads(score_path.read_text()) if score_path.exists() else None,
                  agent_log=(output / "agent.log").read_text() if (output / "agent.log").exists() else "")
    (output / "probe_result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(event="done", case=case, total=(result["score_report"] or {}).get("total"),
                          seconds=result["seconds"])), flush=True)
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--dependencies", type=Path, required=True)
    ap.add_argument("--kit", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source = {str(p.relative_to(args.project)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(args.project.rglob("*")) if p.is_file()}
    (args.out / "source_lock.json").write_text(json.dumps(source, indent=2, sort_keys=True) + "\n")
    results = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        jobs = [ex.submit(run, case, cpus, args) for case, cpus in (("control", "4,5"), ("backup", "6,7"))]
        for job in as_completed(jobs):
            results.append(job.result())
            (args.out / "pair_summary.json").write_text(json.dumps(results, indent=2) + "\n")
