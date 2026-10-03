#!/usr/bin/env python3
"""Build an isolated, deterministic native geometry participant ZIP.

Uses explicit source allowlists; no research labels, card truth, archives,
credentials, remote configuration, compiled Python caches or compiler enter it.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import zipfile

BASE = Path(__file__).resolve().parents[1]
RESULTS = BASE / "results/geometry_native_20261003"
FROZEN = BASE / "runs/cold_neural_value_20261003/production_frozen"
SNAPSHOT = BASE / "results/candidate_geometry_20261003/source_snapshot/candidate_geometry_sweep.py"
FROZEN_FILES = ("agent.py", "policy.py", "policy_config.json", "research/geometry.py", "research/feedback_model.py",
                "research/spatial_candidates.py", "research/belief_clock.py", "research/efficiency_bounds.py",
                "research/remote_budget.py", "research/pointing_calibration.py")
EXPECTED_POLICY = "e7ab68f3b647eb8c57c5e06b354c0e5ee480ca0501ee6d3891617dcd2d803531"
EXPECTED_SPATIAL = "99b97b4a17c142ba7e74dc0fc9cbaad8e1ee98afdb0c3f10c056f2117fe2cf85"
EXPECTED_GEOMETRY = "3ebfb63c3477e3a4c8db8b38e70f4312233b0097bc0537d5ed33a13d447fbc18"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strip_reference_kernel(raw):
    """Use AST ranges to remove exactly Numba import and original sweep."""
    source = raw.decode()
    tree = ast.parse(source)
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "numba"]
    kernels = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "weighted_sweep"]
    assert len(imports) == len(kernels) == 1
    numba, kernel = imports[0], kernels[0]
    assert [alias.name for alias in numba.names] == ["njit"]
    start = min([kernel.lineno] + [node.lineno for node in kernel.decorator_list])
    lines = source.splitlines(keepends=True)
    del lines[start - 1:kernel.end_lineno]
    lines[numba.lineno - 1:numba.end_lineno] = ["from research.geometry_native import weighted_sweep\n"]
    result = "".join(lines).encode()
    expected = ast.parse(source)
    expected.body = [node for node in expected.body if not (isinstance(node, ast.FunctionDef) and node.name == "weighted_sweep")]
    expected.body[expected.body.index(next(node for node in expected.body if isinstance(node, ast.ImportFrom) and node.module == "numba"))] = ast.parse("from research.geometry_native import weighted_sweep").body[0]
    assert ast.dump(ast.parse(result), include_attributes=False) == ast.dump(expected, include_attributes=False)
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) and (
        (isinstance(node, ast.ImportFrom) and node.module == "numba") or
        (isinstance(node, ast.Import) and any(alias.name == "numba" for alias in node.names))) for node in ast.walk(ast.parse(result)))
    return result, dict(source_sha256=sha(raw), output_sha256=sha(result),
                        removed="Only from numba import njit and the decorated weighted_sweep definition",
                        remaining_module_ast_identical=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("/Users/kamico/Downloads/observer_geometry_native.zip"))
    parser.add_argument("--snapshot", type=Path, default=BASE / "runs/geometry_native_20261003/release")
    parser.add_argument("--mode", choices=("sweep", "union"), default="sweep")
    parser.add_argument("--geometry-source", type=Path)
    parser.add_argument("--union-source", type=Path, default=BASE / "research/candidate_geometry_union.py")
    parser.add_argument("--phase-source", type=Path, default=BASE / "research/cpu_phase_candidates.py")
    args = parser.parse_args()
    contents = {name: (FROZEN / name).read_bytes() for name in FROZEN_FILES}
    assert sha(contents["policy.py"]) == EXPECTED_POLICY
    assert sha(contents["research/spatial_candidates.py"]) == EXPECTED_SPATIAL
    geometry_source = args.geometry_source or (SNAPSHOT if args.mode == "sweep" else BASE / "research/candidate_geometry_sweep.py")
    geometry_raw = geometry_source.read_bytes()
    if args.mode == "sweep" and args.geometry_source is None:
        assert sha(geometry_raw) == EXPECTED_GEOMETRY
    contents["research/candidate_geometry_sweep.py"], transform = strip_reference_kernel(geometry_raw)
    for name in ("research/geometry_native.py", "research/agent_geometry_native.py", "ATTRIBUTION.md", "requirements.txt"):
        contents[name] = (BASE / name).read_bytes()
    contents["research/geometry_native_linux_x86_64.so"] = (RESULTS / "geometry_native_linux_x86_64.so").read_bytes()
    contents["research/geometry_native_darwin_arm64.dylib"] = (RESULTS / "geometry_native_darwin_arm64.dylib").read_bytes()
    if args.mode == "union":
        contents["research/candidate_geometry_union.py"] = args.union_source.read_bytes()
        contents["research/cpu_phase_candidates.py"] = args.phase_source.read_bytes()
    project = json.loads((BASE / "observer.project.json").read_text())
    project["run"] = ["python3", "-u", "-m", "research.agent_geometry_native"]
    project["environment"]["GEOMETRY_NATIVE_PLANNER"] = args.mode
    contents["observer.project.json"] = (json.dumps(project, indent=2) + "\n").encode()
    provenance = dict(schema="geometry-native-release-v1", mode=args.mode,
                      policy_sha256=EXPECTED_POLICY, spatial_sha256=EXPECTED_SPATIAL,
                      geometry_source=str(geometry_source.relative_to(BASE)) if geometry_source.is_relative_to(BASE) else str(geometry_source),
                      transformation=transform, protocol="participant-agent-protocol-v4",
                      no_secret_material=True, no_card_or_hidden_truth=True, no_numba_or_runtime_compiler=True,
                      allowlist=list(sorted(contents)), frozen_policy_config_sha256=sha(contents["policy_config.json"]))
    contents["geometry_native_provenance.json"] = (json.dumps(provenance, indent=2) + "\n").encode()
    hashes = {name: sha(raw) for name, raw in sorted(contents.items())}
    contents["build_manifest.json"] = (json.dumps(hashes, indent=2, sort_keys=True) + "\n").encode()
    assert not any(name.endswith((".csv", ".npz", ".npy", ".pyc")) or name == "remote_runtime.json" for name in contents)
    assert b"numpy==2.2.6" in contents["requirements.txt"]
    args.snapshot.mkdir(parents=True, exist_ok=True)
    for name, raw in contents.items():
        target = args.snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    assert sorted(str(p.relative_to(args.snapshot)) for p in args.snapshot.rglob("*") if p.is_file()) == sorted(contents), "Snapshot has extra files"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(contents.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 10, 3, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, raw)
    evidence = dict(**provenance, snapshot=str(args.snapshot), zip=dict(path=str(args.out), bytes=args.out.stat().st_size,
                    sha256=sha(args.out.read_bytes()), files=len(contents)), files_sha256=hashes)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"release_{args.mode}.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(dict(mode=args.mode, zip=evidence["zip"], remaining_module_ast_identical=True)), flush=True)


if __name__ == "__main__":
    main()
