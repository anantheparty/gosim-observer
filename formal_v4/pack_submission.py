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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--remote-config")
    parser.add_argument("--policy-config")
    args = parser.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            path = ROOT / name
            if path.exists():
                archive.write(path, name)
                manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if args.remote_config:
            archive.write(args.remote_config, "remote_runtime.json")
            manifest["remote_runtime.json"] = "separate ephemeral service credential"
        if args.policy_config:
            archive.write(args.policy_config, "policy_config.json")
            manifest["policy_config.json"] = hashlib.sha256(Path(args.policy_config).read_bytes()).hexdigest()
        archive.writestr("build_manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
    print(json.dumps({"path": str(out), "bytes": out.stat().st_size,
                      "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "files": len(manifest)}))


if __name__ == "__main__":
    main()
