"""Build a separate fixed-24 CPUPhase comparator; native ZIP is untouched."""
from pathlib import Path
import hashlib
import json
import zipfile
BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "results/geometry_native_20261003"
FROZEN = BASE / "runs/cold_neural_value_20261003/production_frozen"
PROJECT = BASE / "runs/geometry_native_20261003/phase_control"
sha = lambda b: hashlib.sha256(b).hexdigest()
core = ("agent.py", "policy.py", "policy_config.json", "research/geometry.py", "research/feedback_model.py",
        "research/spatial_candidates.py", "research/belief_clock.py", "research/efficiency_bounds.py",
        "research/remote_budget.py", "research/pointing_calibration.py", "research/cpu_phase_candidates.py")
contents = {name: (FROZEN / name).read_bytes() for name in core}
assert sha(contents["policy.py"]) == "e7ab68f3b647eb8c57c5e06b354c0e5ee480ca0501ee6d3891617dcd2d803531"
assert sha(contents["research/spatial_candidates.py"]) == "99b97b4a17c142ba7e74dc0fc9cbaad8e1ee98afdb0c3f10c056f2117fe2cf85"
assert sha(contents["research/cpu_phase_candidates.py"]) == "3d3b20745eff3979a3954ffcbaca129373930d278825b6c895b83883c3bae67e"
for name in ("requirements.txt", "ATTRIBUTION.md", "research/geometry_native_phase_control.py"):
    contents[name] = (BASE / name).read_bytes()
project = json.loads((BASE / "observer.project.json").read_text())
project["run"] = ["python3", "-u", "-m", "research.geometry_native_phase_control"]
contents["observer.project.json"] = (json.dumps(project, indent=2) + "\n").encode()
hashes = {name: sha(raw) for name, raw in sorted(contents.items())}
contents["build_manifest.json"] = (json.dumps(hashes, sort_keys=True, indent=2) + "\n").encode()
for name, raw in contents.items():
    p = PROJECT / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
assert sorted(str(p.relative_to(PROJECT)) for p in PROJECT.rglob("*") if p.is_file()) == sorted(contents)
zip_path = OUT / "observer_geometry_native_phase_control.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
    for name, raw in sorted(contents.items()):
        entry = zipfile.ZipInfo(name, date_time=(2026, 10, 3, 0, 0, 0)); entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o100644 << 16; archive.writestr(entry, raw)
historical = {card: str(json.loads((BASE / "results/candidate_geometry_20261003/phase_control" / card / "experiment_summary.json").read_text())["total"]) for card in ("L1", "L2", "L3", "L4")}
(OUT / "phase_control_expected.json").write_text(json.dumps(historical, indent=2) + "\n")
record = dict(mode="fixed24-cpu-phase-control", snapshot=str(PROJECT), files_sha256=hashes,
              zip=dict(path=str(zip_path), bytes=zip_path.stat().st_size, sha256=sha(zip_path.read_bytes())),
              same_frozen_controller=True, same_frozen_config=True, no_numba_or_remote=True,
              anchors="Policy default anchor_count=24; CPUPhase fixed workload caps at24 and ignores elapsed cutoff",
              historical_callback_scores=historical)
(OUT / "release_phase_control.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record["zip"]))
