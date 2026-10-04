"""Ordinary PyTorch implementation of the fixed 3 x 65 joint score PMF.

Only the six public feature arrays are accepted by ``forward``. Labels, masks,
future realized points, best points and effective points are never model inputs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import Tensor, nn
from torch.nn import functional as functional

HISTORY_EXPOSURES = 8
HISTORY_SLOTS = 16
TOKEN_DIM = 24
PRESENCE_INDEX = 23
NOTICE_DIM = 129
METADATA_DIM = 16
QUERY_DIM = 51
NUM_BANDS = 3
NUM_INTERVALS = 64
NUM_KNOTS = NUM_INTERVALS + 1
NUM_LOGITS = NUM_BANDS * NUM_KNOTS
SCORE_KNOTS = np.linspace(0.0, 1.0, NUM_KNOTS, dtype=np.float32)
CONTEXT_MODES = ("fullhistory", "current-public-only")
EXPORT_FORMAT_VERSION = 1


def _check_tensor(name: str, value: Tensor, shape: tuple[int, ...]) -> None:
    if not isinstance(value, Tensor):
        raise TypeError(f"{name} must be a torch.Tensor")
    if value.dtype != torch.float32:
        raise TypeError(f"{name} must have dtype float32, got {value.dtype}")
    if tuple(value.shape) != shape:
        raise ValueError(f"{name}: expected shape {shape}, got {tuple(value.shape)}")


class JointScoreDistributionModel(nn.Module):
    """Fixed architecture; flat logit index is ``band * 65 + knot``.

    fullhistory: 24->32->32 token MLP; presence-masked mean and max make
    64 features per exposure; concatenate 129 notice + 16 metadata, flatten
    eight 209-wide exposures and append the complete current 145 features;
    1817->64->32 context MLP.

    current-public-only: complete current 145->64->32 context MLP. Past
    arguments may be ``None`` and are not read by this mode.

    Both: concatenate 51 query features and 32 context features, then
    83->32 ReLU->195 logits. There are no independent regression heads.
    """

    def __init__(self, context_mode: str = "fullhistory") -> None:
        super().__init__()
        if context_mode not in CONTEXT_MODES:
            raise ValueError(f"context_mode must be one of {CONTEXT_MODES}")
        self.context_mode = context_mode
        if context_mode == "fullhistory":
            self.token_encoder = nn.Sequential(
                nn.Linear(TOKEN_DIM, 32), nn.ReLU(), nn.Linear(32, 32), nn.ReLU()
            )
            context_dim = HISTORY_EXPOSURES * (64 + NOTICE_DIM + METADATA_DIM)
            context_dim += NOTICE_DIM + METADATA_DIM
        else:
            context_dim = NOTICE_DIM + METADATA_DIM
        self.context_encoder = nn.Sequential(
            nn.Linear(context_dim, 64), nn.ReLU(), nn.Linear(64, 32), nn.ReLU()
        )
        self.query_head = nn.Sequential(
            nn.Linear(32 + QUERY_DIM, 32), nn.ReLU(), nn.Linear(32, NUM_LOGITS)
        )
        self.register_buffer("score_knots", torch.from_numpy(SCORE_KNOTS.copy()))

    def forward(
        self,
        ht: Tensor | None,
        hn: Tensor | None,
        hm: Tensor | None,
        cn: Tensor,
        cm: Tensor,
        q: Tensor,
    ) -> Tensor:
        if not isinstance(q, Tensor) or q.ndim != 3:
            raise ValueError("q must be a float32 Tensor shaped [B,Q,51]")
        batch, queries = q.shape[:2]
        _check_tensor("q", q, (batch, queries, QUERY_DIM))
        _check_tensor("cn", cn, (batch, NOTICE_DIM))
        _check_tensor("cm", cm, (batch, METADATA_DIM))
        current = torch.cat((cn, cm), dim=-1)
        if self.context_mode == "fullhistory":
            _check_tensor("ht", ht, (batch, HISTORY_EXPOSURES, HISTORY_SLOTS, TOKEN_DIM))
            _check_tensor("hn", hn, (batch, HISTORY_EXPOSURES, NOTICE_DIM))
            _check_tensor("hm", hm, (batch, HISTORY_EXPOSURES, METADATA_DIM))
            present = ht[..., PRESENCE_INDEX] > 0
            # Zero absent tokens before encoding so padding contents never matter.
            encoded = self.token_encoder(torch.where(present[..., None], ht, 0.0))
            count = present.sum(dim=2, keepdim=True).clamp_min(1)
            mean = (encoded * present[..., None]).sum(dim=2) / count
            maximum = encoded.masked_fill(~present[..., None], -torch.inf).amax(dim=2)
            maximum = torch.where(present.any(dim=2)[..., None], maximum, 0.0)
            exposure = torch.cat((mean, maximum, hn, hm), dim=-1)
            context_input = torch.cat((exposure.reshape(batch, -1), current), dim=-1)
        else:
            context_input = current
        context = self.context_encoder(context_input)
        context = context[:, None, :].expand(-1, queries, -1)
        return self.query_head(torch.cat((context, q), dim=-1))

    def joint_pmf(
        self,
        ht: Tensor | None,
        hn: Tensor | None,
        hm: Tensor | None,
        cn: Tensor,
        cm: Tensor,
        q: Tensor,
        temperature: float = 1.0,
    ) -> Tensor:
        return logits_to_joint_pmf(self.forward(ht, hn, hm, cn, cm, q), temperature)

    def export_npz(self, path: str | Path) -> Path:
        """Export every float32 parameter and fixed architecture metadata."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        arrays: dict[str, Any] = {
            key: value.detach().cpu().numpy().astype(np.float32, copy=True)
            for key, value in self.state_dict().items()
        }
        arrays["context_mode"] = np.asarray(self.context_mode)
        arrays["export_format_version"] = np.asarray(EXPORT_FORMAT_VERSION, dtype=np.int64)
        # An open stream prevents NumPy silently adding a second file extension.
        with destination.open("wb") as stream:
            np.savez_compressed(stream, **arrays)
        return destination


def logits_to_joint_pmf(logits: Tensor, temperature: float = 1.0) -> Tensor:
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and strictly positive")
    if logits.shape[-1] != NUM_LOGITS or logits.dtype != torch.float32:
        raise ValueError("logits must have float32 dtype and last dimension 195")
    return functional.softmax(logits / float(temperature), dim=-1).reshape(
        *logits.shape[:-1], NUM_BANDS, NUM_KNOTS
    )


def masked_soft_cross_entropy(
    logits: Tensor, F: Tensor, band: Tensor, mask: Tensor,
    state_balanced: bool = False,
) -> Tensor:
    """Masked soft CE using true-band adjacent-knot targets.

    For F in [0,1], lower=floor(F*64) and upper=min(lower+1,64).
    A target carries mass 1-fraction at [true band, lower] and fraction at
    [true band, upper]. Masked labels are ignored, including placeholder NaNs
    and -1 bands. By default, mean over all valid batch queries. With
    state_balanced=True, first mean valid queries within each state, then mean
    nonempty states. Equal state counts per world therefore keep worlds equally
    represented regardless of their valid-query counts. The caller supplies
    worlds with equal state counts. All-masked batches return differentiable zero.
    """
    if logits.ndim != 3 or logits.shape[-1] != NUM_LOGITS:
        raise ValueError("logits must have shape [B,Q,195]")
    if logits.dtype != torch.float32 or F.dtype != torch.float32:
        raise TypeError("logits and F must have dtype float32")
    expected_shape = logits.shape[:-1]
    if F.shape != expected_shape or band.shape != expected_shape or mask.shape != expected_shape:
        raise ValueError("F, band, and mask must all have shape [B,Q]")
    valid = mask.to(torch.bool)
    if not bool(valid.any()):
        return logits.sum() * 0.0
    valid_f = F[valid]
    valid_band = band[valid]
    if not bool(torch.isfinite(valid_f).all()) or bool(((valid_f < 0) | (valid_f > 1)).any()):
        raise ValueError("valid F labels must be finite and lie in [0,1]")
    if not bool(torch.isfinite(valid_band).all()) or bool(
        ((valid_band < 0) | (valid_band >= NUM_BANDS) | (valid_band != valid_band.long())).any()
    ):
        raise ValueError("valid band labels must be integers in {0,1,2}")
    scaled = valid_f * NUM_INTERVALS
    lower = scaled.floor().long()
    upper = (lower + 1).clamp_max(NUM_INTERVALS)
    fraction = scaled - lower
    offset = valid_band.long() * NUM_KNOTS
    log_probability = functional.log_softmax(logits[valid], dim=-1)
    lower_log = log_probability.gather(-1, (offset + lower)[:, None]).squeeze(-1)
    upper_log = log_probability.gather(-1, (offset + upper)[:, None]).squeeze(-1)
    query_loss = -((1.0 - fraction) * lower_log + fraction * upper_log)
    if not state_balanced:
        return query_loss.mean()
    counts = valid.sum(dim=1)
    state_indices = torch.arange(logits.shape[0], device=logits.device)[:, None].expand_as(valid)[valid]
    loss_sums = logits.new_zeros(logits.shape[0]).scatter_add(0, state_indices, query_loss)
    nonempty = counts > 0
    return (loss_sums[nonempty] / counts[nonempty]).mean()


def pmf_statistics(pmf: Tensor, hinge_threshold: float = 0.0) -> dict[str, Tensor]:
    """Derive all statistics from one PMF; zero-mass conditional means are zero.

    mu_b = joint_first_moment_by_band = E[F*1{band=b}].
    conditional_mean_b = E[F | band=b].
    hinge_by_band = E[max(F-threshold,0)*1{band=b}], and hinge is its band sum.
    The threshold is expressed in the same [0,1] physical-factor domain.
    """
    if pmf.shape[-2:] != (NUM_BANDS, NUM_KNOTS) or pmf.dtype != torch.float32:
        raise ValueError("pmf must be float32 with trailing dimensions [3,65]")
    if not np.isfinite(hinge_threshold):
        raise ValueError("hinge_threshold must be finite")
    knots = torch.as_tensor(SCORE_KNOTS, dtype=torch.float32, device=pmf.device)
    band_probability = pmf.sum(dim=-1)
    first_moment = (pmf * knots).sum(dim=-1)
    hinge_by_band = (pmf * (knots - float(hinge_threshold)).clamp_min(0)).sum(dim=-1)
    denominator = band_probability.clamp_min(torch.finfo(torch.float32).tiny)
    return {
        "band_probability": band_probability,
        "mu_b": first_moment,
        "joint_first_moment_by_band": first_moment,
        "conditional_mean_b": first_moment / denominator,
        "mean": first_moment.sum(dim=-1),
        "hinge_by_band": hinge_by_band,
        "conditional_hinge_by_band": hinge_by_band / denominator,
        "hinge": hinge_by_band.sum(dim=-1),
    }
