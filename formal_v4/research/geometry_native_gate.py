#!/usr/bin/env python3
"""Official full JSONL seasons with isolated resource-limited participant.

The trusted local runner and its practice-card simulator remain on the host.
Only the release and pinned NumPy wheels are mounted into each participant.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parents[1]
IMAGE = "python@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016"
EXPECTED = dict(L1="6378.655366", L2="6808.224288", L3="5912.762510", L4="6078.613462")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(card, args, slot):
    project, dependencies, kit = args.project.resolve(), args.dependencies.resolve(), args.kit.resolve()
    output = args.out / card
    output.mkdir(parents=True, exist_ok=True)
    cpus = f"{slot * 2},{slot * 2 + 1}"
    container = ["docker", "run", "--rm", "--interactive", "--user", "1000:1000",
                 "--name", f"{args.container_prefix}-{card.lower()}", "--cpus", "2", "--cpuset-cpus", cpus,
                 "--memory", "2048m", "--memory-swap", "2048m", "--pids-limit", "128",
                 "--cap-drop=ALL", "--security-opt=no-new-privileges", "--ulimit", "nofile=512:512",
                 "--ulimit", "fsize=268435456:268435456", "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=256m",
                 "--network", "none", "--log-driver", "none",
                 "--mount", f"type=bind,src={project},dst=/workspace,readonly",
                 "--mount", f"type=bind,src={dependencies},dst=/deps,readonly",
                 "--workdir", "/workspace", "--env", "PYTHONPATH=/deps", "--env", "PYTHONDONTWRITEBYTECODE=1",
                 "--env", "OPENBLAS_NUM_THREADS=1", "--env", "OMP_NUM_THREADS=1", "--env", "MKL_NUM_THREADS=1",
                 IMAGE, "python3", "-u", "-m", args.entry]
    command = [sys.executable, str(kit / "runner/run_local.py"), "--card", str(kit / "local-cards" / card),
               "--agent", shlex.join(container), "--agent-cwd", str(project), "--wallclock", "900",
               "--out", str(output), "--quiet"]
    begin = time.monotonic()
    print(json.dumps(dict(event="start", card=card, cpus=cpus)), flush=True)
    with (output / "driver.log").open("w") as log:
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=980)
    workflow_path, score_path = output / "workflow_result.json", output / "score_report.json"
    workflow = json.loads(workflow_path.read_text()) if workflow_path.exists() else {}
    score = json.loads(score_path.read_text()) if score_path.exists() else {}
    agent_log = (output / "agent.log").read_text() if (output / "agent.log").exists() else ""
    observed = score.get("total")
    expected_score = args.expected_scores[card]
    exact = observed is not None and Decimal(str(observed)) == Decimal(str(expected_score))
    result = dict(card=card, exit_code=completed.returncode, host_seconds=time.monotonic() - begin,
                  observed_score=observed, expected_score=expected_score, exact_score_match=exact,
                  termination=workflow.get("termination_reason"), agent_seconds=workflow.get("agent_wallclock_seconds"),
                  accounted_seconds=workflow.get("accounted_wallclock_seconds"), counts=score.get("counts"),
                  components=score.get("components"), traceback_in_agent_log="Traceback" in agent_log,
                  command=command, container_image=IMAGE, participant_mounts=[str(project), str(dependencies)],
                  participant_has_card_truth_mount=False)
    result["protocol_resource_passed"] = completed.returncode == 0 and result["termination"] == "survey_complete" and not result["traceback_in_agent_log"] and result["accounted_seconds"] < 900
    result["passed"] = result["protocol_resource_passed"]
    result["source_sha256"] = {str(p.relative_to(project)): sha(p) for p in sorted(project.rglob("*")) if p.is_file()}
    result["output_sha256"] = {name: sha(output / name) for name in
                               ("actions.jsonl", "decisions.csv", "observations.csv", "score_report.json", "workflow_result.json") if (output / name).is_file()}
    (output / "gate_result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("card", "passed", "observed_score", "expected_score", "termination", "accounted_seconds", "host_seconds")}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cards", nargs="+", choices=tuple(EXPECTED), default=["L2", "L4"])
    parser.add_argument("--project", type=Path, default=BASE / "runs/geometry_native_20261003/release")
    parser.add_argument("--dependencies", type=Path, default=BASE / ".deps")
    parser.add_argument("--kit", type=Path, default=BASE / "upstream/gosim-observer-examples")
    parser.add_argument("--out", type=Path, default=BASE / "results/geometry_native_20261003/protocol_gate")
    parser.add_argument("--cpu-slot-offset", type=int, default=0, help="Offset each two-core slot for concurrent independent suites")
    parser.add_argument("--entry", default="research.agent_geometry_native")
    parser.add_argument("--container-prefix", default="geometry-native-gate")
    parser.add_argument("--expected-scores", type=Path)
    parser.add_argument("--jobs", type=int, choices=(1, 2, 3, 4), default=2)
    args = parser.parse_args()
    args.expected_scores = json.loads(args.expected_scores.read_text()) if args.expected_scores else EXPECTED
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    # At most four participant containers; each uses two distinct CPU cores.
    for offset in range(0, len(args.cards), args.jobs):
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = [executor.submit(run, card, args, slot + args.cpu_slot_offset) for slot, card in enumerate(args.cards[offset:offset + args.jobs])]
            for future in as_completed(futures):
                results.append(future.result())
                (args.out / "summary.json").write_text(json.dumps(dict(all_passed=all(r["passed"] for r in results),
                    expected_cards=args.cards, completed_cards=len(results), results=results), indent=2) + "\n")


if __name__ == "__main__":
    main()
