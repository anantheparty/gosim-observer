#!/usr/bin/env python3
"""Wait for a Rhodes1 broad search, then verify and collect its checkpoints."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKERS = ("window", "conflict", "diverse")


def active_sessions(run_id: str) -> list[str]:
    names = []
    for worker in WORKERS:
        name = f"gosim_broad_{worker}_{run_id}"
        result = subprocess.run(
            ["tmux", "has-session", "-t", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            names.append(name)
    return names


def write_state(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--grace-seconds", type=int, default=900)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    deadline = int((run_dir / "deadline_epoch.txt").read_text(encoding="utf-8"))
    state_path = run_dir / "finalize_state.json"
    limit = deadline + args.grace_seconds
    while True:
        active = active_sessions(run_dir.name)
        now = time.time()
        write_state(state_path, {
            "phase": "waiting", "checked_epoch": now,
            "deadline_epoch": deadline, "active_sessions": active,
        })
        if not active or now >= limit:
            break
        time.sleep(min(30.0, max(1.0, limit - now)))
    with (run_dir / "collector.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(
            [sys.executable, str(ROOT / "collect_broad_search.py"), str(run_dir)],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False,
        )
    status = {
        "phase": "collected" if result.returncode == 0 else "collector_failed",
        "collected_epoch": time.time(), "deadline_epoch": deadline,
        "worker_sessions_still_active": active,
        "collector_returncode": result.returncode,
    }
    if result.returncode == 0:
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        status["winner"] = {
            key: summary["winner"][key] for key in ("worker", "score", "sha256")
        }
    write_state(state_path, status)
    print(json.dumps(status, sort_keys=True), flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
