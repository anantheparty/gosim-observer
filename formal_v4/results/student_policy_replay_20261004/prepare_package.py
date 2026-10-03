"""Prepare a new frozen-source student overlay; never run an episode or fit."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

NATIVE_MANIFEST_SHA256 = "88a307956ab7e6bcccab4fa59bad30c98f6d475855686ff40a3b0bc1cbaca5a2"
STUDENT_FILES = {
    "research/structured_student_features.py": "ac5a6a09fc9cd559ad32559a0281ef71b2b25df13c91351c2d5efb6c918f0db0",
    "research/structured_student_model.py": "612132459874a6869c76c18c21746c045f7235f47bcb64e444b3aebe3f887542",
    "research/structured_student_runtime.py": "5b62f375e6746055814eaa81eee8f2ada596565a883ecf2f75ffc0e3450ffc35",
    "research/structured_student_train.py": "933e40c2e5399067f34a7d9ff67c7e8d0d3d28a852f1a4ba68c84b6f11249585",
    "research/structured_student_audit.py": "0a256dfc1f7f8901403af4da827872e0332a447016469e86f86bdae61779baed",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(root, destination, comparison_lock_sha256, model=None, model_sha256=None):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError("Package destination must not already exist")
    native = root / "runs/geometry_native_20261003/release"
    native_manifest = native / "build_manifest.json"
    if sha(native_manifest) != NATIVE_MANIFEST_SHA256:
        raise ValueError("Frozen native manifest differs")
    native_hashes = json.loads(native_manifest.read_text())
    actual_files = {str(path.relative_to(native)) for path in native.rglob("*") if path.is_file() and "__pycache__" not in path.parts}
    if actual_files != set(native_hashes) | {"build_manifest.json"} or len(actual_files) != 20:
        raise ValueError("Frozen native release inventory differs from exactly 20 files")
    for name, expected in native_hashes.items():
        if sha(native / name) != expected:
            raise ValueError("Frozen native source drift: " + name)
    lock = root / "results/structured_student_dataset_20261004/comparison_source_lock.json"
    if sha(lock) != comparison_lock_sha256:
        raise ValueError("Reviewed comparison source-lock SHA differs")
    if json.loads(lock.read_text())["files"] != STUDENT_FILES:
        raise ValueError("Reviewed comparison five-module source inventory differs")
    for name, expected in STUDENT_FILES.items():
        if sha(root / name) != expected:
            raise ValueError("Locked student source drift: " + name)
    if bool(model) != bool(model_sha256) or (model and sha(model) != model_sha256):
        raise ValueError("Optional model requires its matching reviewed SHA256")
    destination.mkdir(parents=True)
    for name in sorted(actual_files):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(native / name, target)
    for name in (*STUDENT_FILES, "research/student_policy_agent.py"):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    if model:
        (destination / "student_model").mkdir()
        shutil.copyfile(model, destination / "student_model/model.npz")
    receipt = dict(schema="student-policy-overlay-source-lock-v1", native_release_files=20,
                   native_manifest_sha256=NATIVE_MANIFEST_SHA256, comparison_source_lock_sha256=comparison_lock_sha256,
                   files={str(path.relative_to(destination)): sha(path) for path in sorted(destination.rglob("*")) if path.is_file()},
                   runtime_entry=["python3", "-u", "-m", "research.student_policy_agent"], model_sha256=model_sha256,
                   default_mode="control", deployment_calibrated=False, cloud_deployment_authorized=False,
                   teacher_label_files_read=0, seasons_launched=0, optimization_steps=0,
                   observer_project_bytes_preserved=True)
    (destination / "student_policy_package_lock.json").write_text(json.dumps(receipt, indent=2)+"\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--comparison-lock-sha256", required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--model-sha256")
    args = parser.parse_args()
    result = prepare(args.root, args.destination, args.comparison_lock_sha256, args.model, args.model_sha256)
    print(json.dumps(dict(destination=str(args.destination.resolve()), **{key: result[key] for key in
                          ("schema", "native_release_files", "comparison_source_lock_sha256", "model_sha256", "seasons_launched", "deployment_calibrated")})))


if __name__ == "__main__":
    main()
