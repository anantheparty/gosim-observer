"""Fixed first GPU comparison; requires root-accepted portable data and source lock.

Run with the isolated Windows interpreter. No L4 bundle is transported here.
It performs actual fitting only when explicitly invoked after root acceptance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


SELECTION_CANDIDATES = (
    "native_control", "public_gain_per_second",
    "public_terminal_components_one_step", "flat_pair_ridge", "structured", "flat",
)
MODEL_SELECTION_CONTRACT = "validation_regret_then_predeclared_simplicity_order"


def select_method(comparison):
    """Compare realized decision return; ranking units need not match."""
    for name in SELECTION_CANDIDATES:
        require(name in comparison, "Missing comparison method: " + name)
        regret = comparison[name]["teacher_regret_mean"]
        require(isinstance(regret, (int, float)) and math.isfinite(regret),
                "Nonfinite validation teacher regret: " + name)
    return min(SELECTION_CANDIDATES,
               key=lambda name: (comparison[name]["teacher_regret_mean"],
                                 SELECTION_CANDIDATES.index(name)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True, help="Extracted fit_validation only")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--source-lock-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), "Refuse to overwrite a previous fit or its reports")
    require(sha(args.source_lock) == args.source_lock_sha256, "Unreviewed source lock")
    lock = json.loads(args.source_lock.read_text())
    require(lock.get("schema") == "structured-student-comparison-source-lock-v1", "Unknown source lock schema")
    required = {"research/structured_student_features.py", "research/structured_student_model.py",
                "research/structured_student_runtime.py", "research/structured_student_train.py",
                "research/structured_student_audit.py"}
    require(set(lock["files"]) == required, "Complete five-module training source contract required")
    require(all(sha(args.project / name) == value for name, value in lock["files"].items()), "Training source drift")
    require(lock["comparison_runner_sha256"] == sha(Path(__file__)), "Comparison runner drift")
    require(lock["selection_contract"] == "teacher_regret_mean_then_raw_advantage_mae", "Unreviewed selection amendment")
    require(lock["model_selection_contract"] == MODEL_SELECTION_CONTRACT,
            "Unreviewed cross-method selection contract")
    require(lock["model_selection_candidates"] == list(SELECTION_CANDIDATES),
            "Cross-method candidates or simplicity order drifted")
    require(sha(args.manifest) == args.manifest_sha256, "Unreviewed accepted manifest")
    require(args.manifest.resolve().parent == args.bundle.resolve(), "Accepted manifest must resolve its original relative files inside the fitting bundle")
    manifest = json.loads(args.manifest.read_text())
    require(manifest.get("accepted") is True and bool(manifest.get("acceptance_note")), "Root acceptance is missing")
    require(manifest.get("accepted_candidate_manifest_sha256") == sha(args.bundle / "candidate_manifest.json"), "Acceptance belongs to a different portable candidate manifest")
    require(all(record["card"] in ("L1", "L2", "L3") for record in manifest["groups"]), "L4 must not enter the fitting workspace")
    require(manifest["groups"] == json.loads((args.bundle / "candidate_manifest.json").read_text())["groups"], "Root acceptance may not silently subset candidate states/actions")
    file_lock = json.loads((args.bundle / "files_sha256.json").read_text())
    require(file_lock["schema"] == "portable-dataset-file-lock-v1", "Unknown portable file lock")
    bundle_root = args.bundle.resolve()
    for relative, digest in file_lock["files"].items():
        path = args.bundle / relative
        require(not path.is_symlink() and bundle_root in path.resolve().parents, "Portable file escapes its fitting bundle")
        require(sha(path) == digest, "Portable dataset bytes drifted: " + relative)
    require(not (args.bundle / "sealed_test").exists(), "Do not unpack the sealed test bundle into the fitting workspace")
    sys.path.insert(0, str(args.project.resolve()))
    import numpy as np
    import torch
    from research.structured_student_train import train
    require(torch.__version__ == "2.7.1+cu128" and np.__version__ == "2.2.6", "Isolated audited CUDA/NumPy versions required")
    require(torch.cuda.is_available(), "Actual CUDA is required; no CPU fallback")
    require(torch.cuda.get_device_capability() == (12, 0), "Expected the owned Blackwell PRO6000")
    args.out.mkdir(parents=True)
    started = time.monotonic()
    device = dict(torch=torch.__version__, numpy=np.__version__, device=torch.cuda.get_device_name(0),
                  capability=list(torch.cuda.get_device_capability()), total_memory_bytes=torch.cuda.get_device_properties(0).total_memory)
    reports = {}
    for model in ("structured", "flat"):
        destination = args.out / model
        train(argparse.Namespace(manifest=args.manifest, out=destination, model=model, device="cuda",
                                 epochs=200, patience=30, learning_rate=1e-3, weight_decay=1e-2,
                                 cpu_threads=1, seed=20261004))
        report = json.loads((destination / "training_report.json").read_text())
        expected_parameters = 6598 if model == "structured" else 6507
        require(report["parameters"] == expected_parameters, "Parameter-matched model contract drift")
        require(report["full_season_policy_score_evaluated"] is False and report["calibration"]["deployment_calibrated"] is False, "Training unexpectedly authorized deployment")
        with np.load(destination / "student_numpy.npz", allow_pickle=False) as arrays:
            exported = json.loads(str(arrays["config_json"]))
            require(exported["metadata"]["deployment_calibrated"] is False, "Student export unexpectedly authorizes deployment")
        reports[model] = report
    require(all(sha(args.project / name) == value for name, value in lock["files"].items()), "Training source changed during fitting")
    require(sha(args.manifest) == args.manifest_sha256, "Accepted dataset changed during fitting")
    comparison = dict(reports["structured"]["baseline_comparisons"])
    comparison["flat"] = reports["flat"]["baseline_comparisons"]["flat"]
    # Checkpoints compare predictions in identical raw-return units. Cross-method
    # ranking includes both public baselines and uses a fixed simplicity tie-break.
    selected = select_method(comparison)
    summary = dict(schema="structured-student-fixed-gpu-comparison-v1", completed_utc=datetime.now(timezone.utc).isoformat(),
                   manifest_sha256=args.manifest_sha256, source_lock_sha256=args.source_lock_sha256,
                   device=device, elapsed_seconds=time.monotonic() - started,
                   cuda_peak_allocated_bytes=torch.cuda.max_memory_allocated(), models=["structured", "flat"],
                   exact_parameters=dict(structured=6598, flat=6507), seed=20261004, epochs_cap=200,
                   patience=30, learning_rate=1e-3, weight_decay=1e-2,
                   checkpoint_selection_contract=lock["selection_contract"],
                   model_selection_contract=lock["model_selection_contract"],
                   selection_candidates=list(SELECTION_CANDIDATES),
                   validation_comparison=comparison, research_selected=selected,
                   actual_training_completed=True, l4_label_files_opened=0,
                   deployment_calibrated=False, full_season_policy_score_evaluated=False,
                   claim="Finite one-world single-state teacher comparison, not whole-season performance or hidden-card generalization.")
    (args.out / "comparison_report.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
