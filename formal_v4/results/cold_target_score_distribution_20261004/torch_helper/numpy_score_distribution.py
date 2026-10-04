"""NumPy-only inference for exports from score_distribution_model.py."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np

NUM_KNOTS = 65
NUM_BANDS = 3
NUM_LOGITS = 195
SCORE_KNOTS = np.linspace(0.0, 1.0, NUM_KNOTS, dtype=np.float32)


def _array(name: str, value: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    value = np.asarray(value)
    if value.dtype != np.float32:
        raise TypeError(f"{name} must have dtype float32, got {value.dtype}")
    if value.shape != shape:
        raise ValueError(f"{name}: expected shape {shape}, got {value.shape}")
    return value


class NumpyJointScoreDistributionModel:
    def __init__(self, source: str | Path | Mapping[str, np.ndarray]) -> None:
        if isinstance(source, (str, Path)):
            with np.load(source, allow_pickle=False) as archive:
                self.weights = {key: archive[key].copy() for key in archive.files}
        else:
            self.weights = {key: np.asarray(value).copy() for key, value in source.items()}
        if int(self.weights["export_format_version"]) != 1:
            raise ValueError("unsupported model export format")
        self.context_mode = str(self.weights["context_mode"].item())
        if self.context_mode not in ("fullhistory", "current-public-only"):
            raise ValueError("invalid exported context mode")
        if not np.array_equal(self.weights["score_knots"], SCORE_KNOTS):
            raise ValueError("export must use the fixed 65 knots in [0,1]")

    def _linear(self, value: np.ndarray, prefix: str) -> np.ndarray:
        weight = self.weights[prefix + ".weight"]
        bias = self.weights[prefix + ".bias"]
        # Direct float32 contraction is portable across BLAS implementations.
        return np.einsum("...i,oi->...o", value, weight, optimize=False) + bias

    def _mlp(self, value: np.ndarray, prefix: str) -> np.ndarray:
        value = np.maximum(self._linear(value, prefix + ".0"), np.float32(0))
        return np.maximum(self._linear(value, prefix + ".2"), np.float32(0))

    def forward(
        self,
        ht: np.ndarray | None,
        hn: np.ndarray | None,
        hm: np.ndarray | None,
        cn: np.ndarray,
        cm: np.ndarray,
        q: np.ndarray,
    ) -> np.ndarray:
        q = np.asarray(q)
        if q.ndim != 3:
            raise ValueError("q must have shape [B,Q,51]")
        batch, queries = q.shape[:2]
        q = _array("q", q, (batch, queries, 51))
        cn = _array("cn", cn, (batch, 129))
        cm = _array("cm", cm, (batch, 16))
        current = np.concatenate((cn, cm), axis=-1)
        if self.context_mode == "fullhistory":
            ht = _array("ht", ht, (batch, 8, 16, 24))
            hn = _array("hn", hn, (batch, 8, 129))
            hm = _array("hm", hm, (batch, 8, 16))
            present = ht[..., 23] > 0
            encoded = self._mlp(np.where(present[..., None], ht, np.float32(0)), "token_encoder")
            count = present.sum(axis=2, keepdims=True).clip(min=1).astype(np.float32)
            mean = (encoded * present[..., None]).sum(axis=2) / count
            maximum = np.where(present[..., None], encoded, -np.inf).max(axis=2)
            maximum = np.where(present.any(axis=2)[..., None], maximum, np.float32(0))
            exposure = np.concatenate((mean, maximum, hn, hm), axis=-1)
            context_input = np.concatenate((exposure.reshape(batch, -1), current), axis=-1)
        else:
            context_input = current
        context = self._mlp(context_input, "context_encoder")
        context = np.broadcast_to(context[:, None, :], (batch, queries, 32))
        combined = np.concatenate((context, q), axis=-1)
        hidden = np.maximum(self._linear(combined, "query_head.0"), np.float32(0))
        return self._linear(hidden, "query_head.2").astype(np.float32, copy=False)

    def joint_pmf(
        self,
        ht: np.ndarray | None,
        hn: np.ndarray | None,
        hm: np.ndarray | None,
        cn: np.ndarray,
        cm: np.ndarray,
        q: np.ndarray,
        temperature: float = 1.0,
    ) -> np.ndarray:
        return logits_to_joint_pmf(self.forward(ht, hn, hm, cn, cm, q), temperature)


def logits_to_joint_pmf(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    logits = np.asarray(logits)
    if logits.dtype != np.float32 or logits.shape[-1] != NUM_LOGITS:
        raise ValueError("logits must be float32 with last dimension 195")
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and strictly positive")
    scaled = logits / np.float32(temperature)
    shifted = scaled - scaled.max(axis=-1, keepdims=True)
    probability = np.exp(shifted)
    probability /= probability.sum(axis=-1, keepdims=True)
    return probability.reshape(*logits.shape[:-1], NUM_BANDS, NUM_KNOTS)


def pmf_statistics(pmf: np.ndarray, hinge_threshold: float = 0.0) -> dict[str, np.ndarray]:
    pmf = np.asarray(pmf)
    if pmf.dtype != np.float32 or pmf.shape[-2:] != (NUM_BANDS, NUM_KNOTS):
        raise ValueError("pmf must be float32 with trailing dimensions [3,65]")
    if not np.isfinite(hinge_threshold):
        raise ValueError("hinge_threshold must be finite")
    band_probability = pmf.sum(axis=-1)
    first_moment = (pmf * SCORE_KNOTS).sum(axis=-1)
    hinge_by_band = (pmf * np.maximum(SCORE_KNOTS - np.float32(hinge_threshold), np.float32(0))).sum(axis=-1)
    denominator = np.maximum(band_probability, np.finfo(np.float32).tiny)
    return {
        "band_probability": band_probability,
        "mu_b": first_moment,
        "joint_first_moment_by_band": first_moment,
        "conditional_mean_b": first_moment / denominator,
        "mean": first_moment.sum(axis=-1),
        "hinge_by_band": hinge_by_band,
        "conditional_hinge_by_band": hinge_by_band / denominator,
        "hinge": hinge_by_band.sum(axis=-1),
    }
