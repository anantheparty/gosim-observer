#!/usr/bin/env python3
"""Freeze a v4 project and benchmark public cards with the official local runner.

Example:
  python3 formal_v4/research/benchmark_suite.py --label cpu_trial --cards L2 L3 L4 \
    --config '{"duration_safety":1.1,"anchor_count":24,"planning_budget_seconds":0.22}'

Snapshots/raw logs go under ignored runs/<label>; compact reports go under
results/<label>. No remoteconfig or .env is copied. Existing snapshots require
--reuse-snapshot and are verified against their recorded source hashes.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = ROOT / "upstream" / "gosim-observer-examples"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def read_config(value: str | None) -> dict:
    if value is None:
        return {}
    data = json.loads(value if value.lstrip().startswith("{") else Path(value).read_text())
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object or the path to one")
    return data


def freeze_project(label: str, config: dict, reuse: bool) -> tuple[Path, dict]:
    run = ROOT / "runs" / label
    project = run / "agent_project"
    manifest_path = run / "build_manifest.json"
    if project.exists():
        if not reuse:
            raise ValueError("snapshot already exists; use a new label or --reuse-snapshot")
        manifest = json.loads(manifest_path.read_text())
        for relative, expected in manifest["project_files_sha256"].items():
            if sha256((project / relative).read_bytes()) != expected:
                raise ValueError(f"frozen source changed: {relative}")
        if config and any(manifest["policy_config"].get(key) != value for key, value in config.items()):
            raise ValueError("requested config differs from the existing frozen snapshot")
        if any((project / name).exists() for name in
               (".env", "remoteconfig.json", "remote_config.json", "remote_runtime.json")):
            raise ValueError("CPU snapshot contains external credentials or remote configuration")
        return project, manifest
    if reuse:
        raise ValueError("--reuse-snapshot requested but no snapshot exists")
    project.mkdir(parents=True)
    sources = list(ROOT.glob("*.py")) + list((ROOT / "research").glob("*.py"))
    sources += [ROOT / name for name in ("observer.project.json", "requirements.txt", "ATTRIBUTION.md")
                if (ROOT / name).exists()]
    # The local reference imports official modules from this relative path.
    sources += [p for p in (OFFICIAL / "python").rglob("*.py") if "__pycache__" not in p.parts]
    source_hashes = {}
    for source in sorted(sources):
        relative = source.relative_to(ROOT)
        data = source.read_bytes()
        destination = project / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        source_hashes[str(relative)] = sha256(data)
    current_config = ROOT / "policy_config.json"
    merged = json.loads(current_config.read_text()) if current_config.exists() else {}
    merged.update(config)
    data = (json.dumps(merged, sort_keys=True, indent=2) + "\n").encode()
    (project / "policy_config.json").write_bytes(data)
    source_hashes["policy_config.json"] = sha256(data)
    manifest = {
        "label": label, "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        "policy_config": merged, "project_files_sha256": source_hashes,
        "remoteconfig_included": False, "python_executable": sys.executable,
    }
    write_json(manifest_path, manifest)
    return project, manifest


def run_card(card: str, project: Path, run_root: Path, result_root: Path,
             agent_kind: str, wallclock: float, overwrite: bool) -> dict:
    raw = run_root / card
    output = result_root / card
    if output.exists() and not overwrite:
        raise ValueError(f"result already exists for {card}; use a new label or --overwrite-results")
    raw.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    card_path = OFFICIAL / "local-cards" / card
    entry = {"current": "agent.py", "reference": "research/reference_agent.py",
             "rolling": "research/rolling_lp_agent.py"}[agent_kind]
    # run_local shlex-splits --agent itself; JSON-style double quoting is safe for
    # this command string because it is not evaluated by a shell.
    agent_command = f'{json.dumps(sys.executable)} -u {entry}'
    command = [sys.executable, str(OFFICIAL / "runner" / "run_local.py"),
               "--card", str(card_path), "--agent", agent_command,
               "--agent-cwd", str(project), "--wallclock", str(wallclock),
               "--out", str(raw), "--quiet"]
    started = time.monotonic()
    process_error = None
    try:
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                                   timeout=wallclock + 120)
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except Exception as error:
        process_error = f"{type(error).__name__}: {error}"
        stdout = stderr = ""
        exit_code = None
        if isinstance(error, subprocess.TimeoutExpired):
            stdout = error.stdout or ""
            stderr = error.stderr or ""
            stdout = stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout
            stderr = stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr
    (raw / "runner_stdout.json").write_text(stdout)
    (raw / "runner_stderr.log").write_text(stderr)
    summary = None
    try:
        summary = json.loads(stdout)
    except (ValueError, TypeError):
        if process_error is None:
            process_error = "runner did not produce a JSON summary"
    agent_log = raw / "agent.log"
    log_lines = agent_log.read_text(errors="replace").splitlines() if agent_log.exists() else []
    error_lines = [line for line in log_lines
                   if any(marker in line.lower() for marker in
                          ("traceback", "exception", "invalid action", "planner error", "falling back"))]
    reports = []
    message_path = raw / "messages.jsonl"
    if message_path.exists():
        for line in message_path.read_text().splitlines():
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("record_type") == "report_result":
                reports.append({key: message.get(key) for key in
                                ("issued_at_utc", "correct", "repaired", "score_delta")})
    negative = [r for r in reports if float(r.get("score_delta") or 0.0) < 0.0]
    record = {
        "card": card, "agent_kind": agent_kind, "exit_code": exit_code,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "wallclock_budget_seconds": wallclock, "summary": summary,
        "process_error": process_error, "agent_error_log_lines": error_lines[:20],
        "report_results": reports, "report_penalty_count": len(negative),
        "report_penalty_sum": sum(float(r["score_delta"]) for r in negative),
        "raw_outputs": str(raw),
    }
    for name in ("score_report.json", "workflow_result.json"):
        if (raw / name).exists():
            shutil.copy2(raw / name, output / name)
    record["completed_cleanly"] = (exit_code == 0 and process_error is None and not error_lines
                                   and (summary or {}).get("termination_reason") == "survey_complete")
    write_json(output / "summary.json", record)
    score = (summary or {}).get("total")
    print(json.dumps({"card": card, "score": score,
                      "termination_reason": (summary or {}).get("termination_reason"),
                      "report_penalty_count": len(negative), "exit_code": exit_code}, sort_keys=True), flush=True)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True)
    parser.add_argument("--config", help="JSON object or path to a JSON object")
    parser.add_argument("--cards", nargs="+", default=["L1", "L2", "L3", "L4"])
    parser.add_argument("--agent", choices=("current", "reference", "rolling"), default="current")
    parser.add_argument("--wallclock", type=float, default=900.0)
    parser.add_argument("--max-parallel", type=int, default=2)
    parser.add_argument("--reuse-snapshot", action="store_true")
    parser.add_argument("--overwrite-results", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}", args.label):
        parser.error("label must be a simple directory name")
    if not 1 <= args.max_parallel <= 2 or not 0 < args.wallclock <= 900:
        parser.error("use 1–2 parallel cards and a wallclock budget in (0,900]")
    if len(set(args.cards)) != len(args.cards):
        parser.error("cards must be unique")
    for card in args.cards:
        if not re.fullmatch(r"L[1-4]", card):
            parser.error("this suite accepts public local cards L1–L4 only")
    project, build = freeze_project(args.label, read_config(args.config), args.reuse_snapshot)
    run_root, result_root = ROOT / "runs" / args.label, ROOT / "results" / args.label
    metadata = dict(build)
    metadata.update(agent_kind=args.agent, cards=args.cards, max_parallel=args.max_parallel,
                    wallclock_budget_seconds=args.wallclock)
    metadata["engine_files_sha256"] = {str(p.relative_to(OFFICIAL)): sha256(p.read_bytes())
                                        for p in sorted((OFFICIAL / "runner").rglob("*.py"))}
    metadata["runtime_environment"] = {"python": sys.version, "platform": sys.platform,
                                       "cpu_count": os.cpu_count()}
    try:
        import numpy as np
        metadata["runtime_environment"]["numpy"] = np.__version__
    except ImportError:
        metadata["runtime_environment"]["numpy"] = None
    write_json(result_root / "build_manifest.json", metadata)
    print(json.dumps({"label": args.label, "snapshot": str(project),
                      "cards": args.cards, "agent": args.agent}, sort_keys=True), flush=True)
    records = {}
    with ThreadPoolExecutor(max_workers=args.max_parallel) as pool:
        pending = {pool.submit(run_card, card, project, run_root, result_root,
                               args.agent, args.wallclock, args.overwrite_results): card for card in args.cards}
        for task in as_completed(pending):
            card = pending[task]
            try:
                records[card] = task.result()
            except Exception as error:
                records[card] = {"card": card, "completed_cleanly": False,
                                 "process_error": f"{type(error).__name__}: {error}"}
                write_json(result_root / card / "summary.json", records[card])
            scores = [(r.get("summary") or {}).get("total") for r in records.values()]
            available = [score for score in scores if isinstance(score, (int, float))]
            write_json(result_root / "suite_summary.json", {
                "label": args.label, "agent_kind": args.agent, "cards_requested": args.cards,
                "cards_finished": len(records), "cards": records,
                "mean_available_score": sum(available) / len(available) if available else None,
                "all_completed_cleanly": len(records) == len(args.cards)
                                         and all(r.get("completed_cleanly") for r in records.values()),
            })
    return 0 if all(r.get("completed_cleanly") for r in records.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
