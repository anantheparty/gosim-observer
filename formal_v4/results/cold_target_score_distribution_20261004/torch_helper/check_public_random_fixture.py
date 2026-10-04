"""CPU consistency checks using fresh public random inputs; never trains.

Run with python check_public_random_fixture.py. If Torch is unavailable, the
script emits a clear skipped report; retain this source for the GPU runtime.
All temporary exports and the default report live alongside this script.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def random_public_inputs(seed: int = 949200, batch: int = 3, queries: int = 320) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    arrays = {
        "ht": rng.normal(0, 0.4, (batch, 8, 16, 24)).astype(np.float32),
        "hn": rng.normal(0, 0.4, (batch, 8, 129)).astype(np.float32),
        "hm": rng.normal(0, 0.4, (batch, 8, 16)).astype(np.float32),
        "cn": rng.normal(0, 0.4, (batch, 129)).astype(np.float32),
        "cm": rng.normal(0, 0.4, (batch, 16)).astype(np.float32),
        "q": rng.normal(0, 0.4, (batch, queries, 51)).astype(np.float32),
    }
    arrays["ht"][..., 23] = (rng.random((batch, 8, 16)) > 0.35).astype(np.float32)
    arrays["ht"][0, 0, :, 23] = 0  # Fully empty exposure exercises masked max.
    arrays["ht"][1, :, :, 23] = 0  # Fully empty history exercises every pool.
    return arrays


def _maxerr(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.max(np.abs(left - right)))


def run_checks(tolerance: float = 1e-5) -> dict[str, object]:
    if importlib.util.find_spec("torch") is None:
        return {"status": "skipped", "reason": "Torch unavailable; no dependencies installed", "trained": False}
    import torch
    try:
        from .score_distribution_model import (
            JointScoreDistributionModel, logits_to_joint_pmf as torch_pmf,
            masked_soft_cross_entropy, pmf_statistics as torch_stats,
        )
        from .numpy_score_distribution import (
            NumpyJointScoreDistributionModel, logits_to_joint_pmf as numpy_pmf,
            pmf_statistics as numpy_stats,
        )
    except ImportError:
        from score_distribution_model import (
            JointScoreDistributionModel, logits_to_joint_pmf as torch_pmf,
            masked_soft_cross_entropy, pmf_statistics as torch_stats,
        )
        from numpy_score_distribution import (
            NumpyJointScoreDistributionModel, logits_to_joint_pmf as numpy_pmf,
            pmf_statistics as numpy_stats,
        )
    torch.set_num_threads(1)
    torch.manual_seed(949200)
    arrays = random_public_inputs()
    names = ("ht", "hn", "hm", "cn", "cm", "q")
    args_numpy = [arrays[key] for key in names]
    args_torch = [torch.from_numpy(value) for value in args_numpy]
    modes: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="public_fixture_", dir=HERE) as temporary:
        for mode in ("fullhistory", "current-public-only"):
            model = JointScoreDistributionModel(mode).eval()
            with torch.inference_mode():
                logits_torch = model(*args_torch)
            numpy_model = NumpyJointScoreDistributionModel(model.export_npz(Path(temporary) / (mode + ".npz")))
            logits_numpy = numpy_model.forward(*args_numpy)
            errors = {"logits": _maxerr(logits_torch.numpy(), logits_numpy)}
            assert logits_numpy.shape == (3, 320, 195)
            assert logits_numpy.dtype == np.float32 and np.isfinite(logits_numpy).all()
            for temperature in (0.7, 1.0, 1.9):
                probability_torch = torch_pmf(logits_torch, temperature)
                probability_numpy = numpy_pmf(logits_numpy, temperature)
                errors[f"pmf_T{temperature}"] = _maxerr(probability_torch.numpy(), probability_numpy)
                assert np.max(np.abs(probability_numpy.sum(axis=(-1, -2)) - 1)) < tolerance
                stats_torch = torch_stats(probability_torch, hinge_threshold=0.37)
                stats_numpy = numpy_stats(probability_numpy, hinge_threshold=0.37)
                for key in stats_torch:
                    errors[f"{key}_T{temperature}"] = _maxerr(stats_torch[key].numpy(), stats_numpy[key])
            changed = {key: value.copy() for key, value in arrays.items()}
            if mode == "fullhistory":
                absent = changed["ht"][..., 23] == 0
                changed["ht"][..., :23][absent] = np.float32(12345)
                padding_error = _maxerr(logits_numpy, numpy_model.forward(*(changed[key] for key in names)))
                assert padding_error == 0, "absent-token contents affected pooled features"
                with torch.inference_mode():
                    changed_torch = model(*(torch.from_numpy(changed[key]) for key in names))
                assert torch.equal(logits_torch, changed_torch)
                errors["padding_invariance"] = padding_error
            else:
                changed["ht"][:] = 12345
                changed["hn"][:] = 12345
                changed["hm"][:] = 12345
                history_error = _maxerr(logits_numpy, numpy_model.forward(*(changed[key] for key in names)))
                no_history = numpy_model.forward(None, None, None, arrays["cn"], arrays["cm"], arrays["q"])
                assert history_error == 0 and np.array_equal(logits_numpy, no_history)
                with torch.inference_mode():
                    no_history_torch = model(None, None, None, *args_torch[3:])
                assert torch.equal(logits_torch, no_history_torch)
                errors["history_invariance"] = history_error
            assert max(errors.values()) < tolerance, errors
            modes[mode] = {
                "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
                "output_shape": list(logits_numpy.shape), "max_errors": errors,
                "overall_maxerr": max(errors.values()),
            }
    # Explicit true-band, adjacent-knot and mask checks, without optimizer use.
    raw = torch.zeros((1, 4, 195), dtype=torch.float32)
    raw[0, 0, 65 + 10] = 1.2
    raw[0, 0, 65 + 11] = -0.4
    target = torch.tensor([[10.25 / 64, 0, 1, float("nan")]], dtype=torch.float32)
    band = torch.tensor([[1, 0, 2, -1]], dtype=torch.int64)
    mask = torch.tensor([[True, True, True, False]])
    logs = torch.log_softmax(raw, dim=-1)
    expected_loss = -(0.75 * logs[0, 0, 75] + 0.25 * logs[0, 0, 76] + logs[0, 1, 0] + logs[0, 2, 194]) / 3
    actual_loss = masked_soft_cross_entropy(raw, target, band, mask)
    loss_error = abs(float(expected_loss - actual_loss))
    assert loss_error < 1e-6
    assert float(masked_soft_cross_entropy(raw, target, band, torch.zeros_like(mask))) == 0
    # Unequal valid-query counts must give equal weight to each nonempty state.
    balanced_raw = torch.zeros((3, 4, 195), dtype=torch.float32)
    balanced_raw[0, 0, 0] = 3.0
    balanced_raw.requires_grad_(True)
    balanced_mask = torch.tensor([[True, False, False, False],
                                  [True, True, True, False],
                                  [False, False, False, False]])
    balanced_target = torch.zeros((3, 4), dtype=torch.float32)
    balanced_target[2] = float("nan")
    balanced_band = torch.zeros((3, 4), dtype=torch.long)
    balanced_band[2] = -1
    balanced_logs = torch.log_softmax(balanced_raw, dim=-1)
    state_zero_ce = -balanced_logs[0, 0, 0]
    state_one_ce = -balanced_logs[1, :3, 0].mean()
    expected_balanced = (state_zero_ce + state_one_ce) / 2
    actual_balanced = masked_soft_cross_entropy(
        balanced_raw, balanced_target, balanced_band, balanced_mask, state_balanced=True
    )
    balanced_loss_error = abs(float(expected_balanced - actual_balanced))
    assert balanced_loss_error < 1e-6
    actual_gradient = torch.autograd.grad(actual_balanced, balanced_raw)[0]
    expected_gradient = torch.zeros_like(balanced_raw)
    expected_gradient[0, 0] = balanced_logs[0, 0].detach().exp() / 2
    expected_gradient[0, 0, 0] -= 1 / 2
    expected_gradient[1, :3] = balanced_logs[1, :3].detach().exp() / 6
    expected_gradient[1, :3, 0] -= 1 / 6
    gradient_error = float((actual_gradient - expected_gradient).abs().max())
    assert gradient_error < 1e-7
    actual_query_mean = masked_soft_cross_entropy(
        balanced_raw, balanced_target, balanced_band, balanced_mask
    )
    assert abs(float(actual_query_mean - (state_zero_ce + 3 * state_one_ce) / 4)) < 1e-6
    assert abs(float(actual_balanced - actual_query_mean)) > 0.1
    assert float(masked_soft_cross_entropy(
        balanced_raw, balanced_target, balanced_band, torch.zeros_like(balanced_mask), state_balanced=True
    )) == 0
    fixture_pmf = np.zeros((1, 1, 3, 65), dtype=np.float32)
    fixture_pmf[0, 0, 0, 16] = 0.25
    fixture_pmf[0, 0, 2, 48] = 0.75
    derived = numpy_stats(fixture_pmf, hinge_threshold=0.5)
    assert np.array_equal(derived["mu_b"], np.array([[[0.0625, 0, 0.5625]]], dtype=np.float32))
    assert np.array_equal(derived["conditional_mean_b"], np.array([[[0.25, 0, 0.75]]], dtype=np.float32))
    assert float(derived["hinge"][0, 0]) == 0.1875
    torch_derived = torch_stats(torch.from_numpy(fixture_pmf), hinge_threshold=0.5)
    assert all(np.array_equal(value, torch_derived[key].numpy()) for key, value in derived.items())
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(HERE.glob("*.py"))
    }
    return {
        "status": "passed", "trained": False, "device": "cpu", "public_fixture_seed": 949200,
        "torch_version": torch.__version__, "numpy_version": np.__version__,
        "tolerance": tolerance, "modes": modes, "loss_maxerr": loss_error,
        "state_balanced_loss_maxerr": balanced_loss_error,
        "state_balanced_gradient_maxerr": gradient_error,
        "mu_b_definition": "E[F * 1{band=b}]", "source_sha256": hashes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=HERE / "public_fixture_results.json")
    args = parser.parse_args()
    result = run_checks()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
