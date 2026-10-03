"""Build a separate integration from the actual submitted request ZIP."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

BASE = Path(__file__).resolve().parents[1]
SOURCE = Path("/Users/kamico/Downloads/observer_request_exact_cache.zip")
EXPECTED = "e55becb74bbf2a707aeb893fb054a857610312c81d815181a28bfcf5e5ff092a"
OUT = BASE / "results/request_geometry_integration_20261004"
NATIVE = BASE / "runs/geometry_native_20261003/release"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    assert sha(SOURCE.read_bytes()) == EXPECTED
    OUT.mkdir(exist_ok=True)
    control, candidate = OUT / "control_package", OUT / "geometry_package"
    assert not control.exists() and not candidate.exists(), "Preserve existing experiment"
    control.mkdir()
    candidate.mkdir()
    with zipfile.ZipFile(SOURCE) as archive:
        for name in archive.namelist():
            if name.endswith("/"):
                continue
            assert not Path(name).is_absolute() and ".." not in Path(name).parts
            data = archive.read(name)
            for folder in (control, candidate):
                path = folder / name
                path.parent.mkdir(exist_ok=True, parents=True)
                path.write_bytes(data)
    additions = [
        "research/candidate_geometry_sweep.py", "research/geometry_native.py",
        "research/geometry_native_darwin_arm64.dylib", "research/geometry_native_linux_x86_64.so",
    ]
    for name in additions:
        assert not (candidate / name).exists()
        (candidate / name).write_bytes((NATIVE / name).read_bytes())
    for name in ("research/agent_request_geometry.py", "research/request_geometry_planner.py"):
        (candidate / name).write_bytes((BASE / name).read_bytes())
        additions.append(name)
    config = json.loads((candidate / "observer.project.json").read_text())
    config["run"] = ["python3", "-u", "-m", "research.agent_request_geometry"]
    (candidate / "observer.project.json").write_text(json.dumps(config, indent=2) + "\n")
    manifest = {str(p.relative_to(candidate)): sha(p.read_bytes())
                for p in sorted(candidate.rglob("*"))
                if p.is_file() and p.name != "build_manifest.json"}
    (candidate / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    hashes = lambda folder: {str(p.relative_to(folder)): sha(p.read_bytes()) for p in sorted(folder.rglob("*")) if p.is_file()}
    original, modified = hashes(control), hashes(candidate)
    changed = ["observer.project.json", "build_manifest.json"]
    unchanged = [name for name in original if name not in changed]
    assert all(original[name] == modified[name] for name in unchanged)
    receipt = {
        "schema": "request-native-geometry-composition-source-v1",
        "source_zip_sha256": EXPECTED,
        "control": original, "geometry": modified,
        "unchanged_original_files": unchanged,
        "added_files": additions,
        "changed_original_files": changed,
        "policy_parameters_changed": False,
        "terrain_feedback_preserved": True,
        "request_columns_dp_cache_preserved": True,
        "status": "built-not-season-tested",
    }
    (OUT / "source_lock.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"control_files": len(original), "geometry_files": len(modified), "status": receipt["status"]}))


if __name__ == "__main__":
    main()
