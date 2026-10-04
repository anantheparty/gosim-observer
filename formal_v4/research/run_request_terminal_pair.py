"""Actual RequestCache and terminal-report L3 pair, each in a 2-CPU/2-GiB participant."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid

IMAGE = "python@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016"


def hashes(folder):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def run(args, variant, card, slot):
    folder = args.experiment / ("control_package" if variant == "control" else "full_wrapper_package")
    expected = args.lock["control" if variant == "control" else "full_wrapper"]
    assert hashes(folder) == expected
    output = args.experiment / "seasons" / variant / card
    output.mkdir(parents=True, exist_ok=False)
    name = "request-terminal-" + variant + "-" + card.lower() + "-" + uuid.uuid4().hex[:12]
    owner = uuid.uuid4().hex
    cores = f"{16 + 2*slot},{17 + 2*slot}"
    entry = "research.agent_request_exact_cache" if variant == "control" else None
    command = ["docker", "run", "--rm", "-i", "--name", name,
               "--label", "gosim.experiment=request-terminal-20261004", "--label", "gosim.owner=" + owner,
               "--user", "1000:1000", "--cpus", "2", "--cpuset-cpus", cores,
               "--memory", "2048m", "--memory-swap", "2048m", "--pids-limit", "128",
               "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only",
               "--tmpfs", "/tmp:rw,nosuid,size=256m", "--network", "none", "--log-driver", "none",
               "--mount", f"type=bind,src={folder},dst=/workspace,readonly",
               "--mount", f"type=bind,src={args.dependencies},dst=/deps,readonly",
               "--workdir", "/workspace", "--env", "PYTHONPATH=/deps", "--env", "PYTHONDONTWRITEBYTECODE=1",
               "--env", "OPENBLAS_NUM_THREADS=1", "--env", "OMP_NUM_THREADS=1", "--env", "MKL_NUM_THREADS=1",
               IMAGE, "python3", "-u", *(["-m", entry] if entry is not None else ["wrapper.py"])]
    runner = [sys.executable, str(args.kit / "runner/run_local.py"),
              "--card", str(args.kit / "local-cards" / card), "--agent", shlex.join(command),
              "--agent-cwd", str(folder), "--wallclock", "900", "--out", str(output), "--quiet"]
    begin = time.monotonic()
    print(json.dumps({"event": "start", "variant": variant, "card": card, "cpus": cores, "name": name}), flush=True)
    timed_out = False
    with (output / "driver.log").open("w") as log:
        try:
            completion = subprocess.run(runner, stdout=log, stderr=subprocess.STDOUT, timeout=980)
            exit_code = completion.returncode
        except subprocess.TimeoutExpired:
            timed_out, exit_code = True, None
        finally:
            inspected = subprocess.run(["docker", "inspect", name], capture_output=True, text=True)
            if inspected.returncode == 0:
                metadata = json.loads(inspected.stdout)[0]
                assert metadata["Config"]["Labels"].get("gosim.owner") == owner
                subprocess.run(["docker", "rm", "-f", name], check=True, stdout=log, stderr=log)
    assert hashes(folder) == expected
    def read(name):
        path = output / name
        return json.loads(path.read_text()) if path.exists() else {}
    workflow, score = read("workflow_result.json"), read("score_report.json")
    stderr = (output / "agent.log").read_text() if (output / "agent.log").exists() else ""
    complete = workflow.get("termination_reason") == "survey_complete"
    accounted = workflow.get("accounted_wallclock_seconds")
    receipt = {
        "variant": variant, "card": card, "source_lock_verified": True,
        "container_image": IMAGE, "cpus": cores, "memory_bytes": 2147483648,
        "participant_mounts": ["read-only package", "read-only numpy dependencies"],
        "participant_truth_mount": False, "network": "none", "wallclock_limit": 900,
        "exit_code": exit_code, "runner_timed_out": timed_out,
        "termination": workflow.get("termination_reason"),
        "total": score.get("total"), "components": score.get("components"), "counts": score.get("counts"),
        "accounted_seconds": accounted, "agent_seconds": workflow.get("agent_wallclock_seconds"),
        "host_seconds": time.monotonic() - begin, "traceback": "Traceback" in stderr,
        "container_cleaned": subprocess.run(["docker", "inspect", name], capture_output=True).returncode != 0,
        "outputs_sha256": hashes(output), "source_sha256": expected,
    }
    receipt["protocol_passed"] = (exit_code == 0 and not timed_out and complete and accounted is not None
                                  and accounted <= 900 and not receipt["traceback"] and receipt["container_cleaned"])
    (output / "gate_result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in ("variant", "card", "protocol_passed", "total", "termination", "accounted_seconds")}), flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--dependencies", type=Path, required=True)
    args = parser.parse_args()
    for key in ("experiment", "kit", "dependencies"):
        setattr(args, key, getattr(args, key).resolve())
    args.lock = json.loads((args.experiment / "source_lock.json").read_text())
    results = []
    work = [(variant, card) for variant in ("control", "terminal") for card in ("L3",)]
    with ThreadPoolExecutor(max_workers=len(work)) as executor:
        futures = [executor.submit(run, args, variant, card, slot) for slot, (variant, card) in enumerate(work)]
        for future in as_completed(futures):
            results.append(future.result())
            summary = {"schema": "actual-request-terminal-L3-comparison-v1", "completed": len(results), "expected": len(work), "results": results}
            (args.experiment / "comparison_progress.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
