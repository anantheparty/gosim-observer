#!/usr/bin/env python3
"""Build a minimal private submission; public card truth never enters the ZIP."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
FILES = ["agent.py", "policy.py", "observer.project.json", "requirements.txt", "remote_planner.py",
         "research/geometry.py", "research/feedback_model.py", "research/spatial_candidates.py",
         "research/belief_clock.py", "research/efficiency_bounds.py",
         "research/remote_budget.py",
         "research/pointing_calibration.py", "ATTRIBUTION.md"]
CPU_ENTRIES = {
    "cpu-phase": ("research.agent_cpu_phase_direct", [
        "research/cpu_phase_candidates.py", "research/agent_cpu_phase_direct.py"]),
    "request-cpu-phase": ("research.agent_request_cpu_direct", [
        "research/cpu_phase_candidates.py", "research/agent_request_cpu_direct.py",
        "research/request_deadline_common.py", "research/request_deadline_cpu.py",
        "research/request_mask_dp.py"]),
}
MODEL_ENTRY = ("research.agent_model_gpu", ["research/cpu_phase_candidates.py",
               "research/agent_model_gpu.py", "research/model_gpu_transport.py"])
MODEL_ENTRIES = {
    "model-gpu": MODEL_ENTRY,
    "request-model-gpu": ("research.agent_request_distributed", MODEL_ENTRY[1] + [
        "research/agent_request_distributed.py", "research/request_remote_planner.py",
        "research/request_deadline_common.py", "research/request_mask_dp.py",
        "research/request_future_field.py", "research/terrain_policy.py",
        "research/terrain_version_space.py"]),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--remote-config")
    parser.add_argument("--policy-config")
    parser.add_argument("--planner", choices=("default", *CPU_ENTRIES, *MODEL_ENTRIES), default="default")
    args = parser.parse_args()
    if args.planner != "default" and args.remote_config:
        parser.error("This entry does not accept a private remote configuration")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        extra = MODEL_ENTRIES.get(args.planner) or CPU_ENTRIES.get(args.planner)
        for name in FILES + (extra[1] if extra else []):
            path = ROOT / name
            if path.exists():
                data = path.read_bytes()
                if name == "observer.project.json" and extra:
                    project = json.loads(data)
                    project["run"] = ["python3", "-u", "-m", extra[0]]
                    data = (json.dumps(project, indent=2) + "\n").encode()
                archive.writestr(name, data)
                manifest[name] = hashlib.sha256(data).hexdigest()
            elif extra and name in extra[1]:
                raise FileNotFoundError(path)
        if args.remote_config:
            archive.write(args.remote_config, "remote_runtime.json")
            manifest["remote_runtime.json"] = "separate ephemeral service credential"
        elif args.planner in MODEL_ENTRIES:
            data = (json.dumps({"enable_search": True, "health_timeout_seconds": 12,
                               "initialize_timeout_seconds": 75,
                               "timeout_seconds": 10}, sort_keys=True) + "\n").encode()
            archive.writestr("remote_runtime.json", data)
            manifest["remote_runtime.json"] = hashlib.sha256(data).hexdigest()
        if args.policy_config:
            archive.write(args.policy_config, "policy_config.json")
            manifest["policy_config.json"] = hashlib.sha256(Path(args.policy_config).read_bytes()).hexdigest()
        archive.writestr("build_manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
    print(json.dumps({"path": str(out), "bytes": out.stat().st_size,
                      "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "files": len(manifest)}))


if __name__ == "__main__":
    main()
