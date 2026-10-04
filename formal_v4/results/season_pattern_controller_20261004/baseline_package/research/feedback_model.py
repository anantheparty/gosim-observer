"""Infer effective weather from public v4 exposure feedback.

The input H is the exposure-averaged lunar_factor / airmass**beta.
C = transparency * sky_quality / (seeing * q0), E = instrument efficiency.
No truth files, random seeds or unpublished messages are used by this module.
The factor bounds are unconditional; fitted factors assume no directional event
and approximately constant C/E during an exposure.
"""
from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np


def fit_feedback(
    hits_or_scores: Sequence,
    weights: Sequence[float],
    flux: Sequence[float],
    duration: float,
    geometric_H: Sequence[float],
    declared_program: str,
    scoring: Mapping,
    prior_C: float = 1.0,
    prior_E: float = 0.95,
    *,
    grid_c: int = 129,
    grid_e: int = 65,
) -> dict:
    """Fit all hit scores jointly; arrays must have the same target ordering.

    hits_or_scores is either [score,...] or [{target_id,score},...].
    Returned factor_estimates/lower/upper/matches retain that ordering. A low
    residual does not prove C and E are separately identifiable; observed_Z is
    normally much better determined than either component. Call on each exposure,
    not on running_total or highest historical scores.
    """
    records = list(hits_or_scores)
    scores = np.asarray([x.get("score", 0.0) if isinstance(x, Mapping) else x
                         for x in records], dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    f = np.asarray(flux, dtype=np.float64)
    h = np.asarray(geometric_H, dtype=np.float64)
    if not (scores.shape == w.shape == f.shape == h.shape) or scores.ndim != 1:
        raise ValueError("feedback inputs must be one-dimensional and have equal lengths")
    if duration <= 0 or np.any(w <= 0) or np.any(f <= 0) or np.any(h <= 0):
        raise ValueError("duration, weights, flux and geometric_H must be positive")
    program = scoring.get("program", {})
    multipliers = program.get("multipliers", {"DARK": 1.2, "BRIGHT": 1.12, "BACKUP": 1.06})
    match_mult = float(multipliers.get(declared_program, 1.0))
    mismatch_mult = float(program.get("mismatch_multiplier", 1.0))
    bands = program.get("bands", {})
    dark = float(bands.get("DARK", 0.65))
    bright = float(bands.get("BRIGHT", 0.40))
    f0t0 = float(scoring.get("flux_zero_point", 0.5)) * float(
        scoring.get("exposure_zero_point_seconds", 900))
    normalized = np.maximum(0.0, scores / w)
    # Public score is rounded to six decimals. Retain that uncertainty in bounds.
    rounding = 0.500001e-6 / w
    lower = np.minimum(1.0, np.maximum(0.0, normalized - rounding)
                       / max(match_mult, mismatch_mult))
    upper = np.minimum(1.0, (normalized + rounding)
                       / min(match_mult, mismatch_mult))
    prior_c = float(np.clip(prior_C, 0.02, 5.0))
    prior_e = float(np.clip(prior_E, 0.025, 1.0))
    if len(scores) == 0 or np.all(scores <= 5.1e-7):
        return {"C": prior_c, "E": prior_e, "observed_Z": 0.0,
                "factor_estimates": [0.0] * len(scores),
                "factor_lower": lower.tolist(), "factor_upper": upper.tolist(),
                "quality_estimates": [0.0] * len(scores),
                "program_matches": [False] * len(scores), "loss": 0.0,
                "saturated_count": 0, "unsaturated_count": 0,
                "closed_evidence": bool(len(scores)), "informative": False,
                "outlier_count": 0}

    # C crosses an actual-band boundary at threshold/H. Include both sides so
    # narrow band-consistency intervals cannot disappear between coarse nodes.
    c_values = np.geomspace(0.035, 4.0, max(17, int(grid_c)))
    boundaries = np.concatenate((dark / h, bright / h))
    c_values = np.unique(np.concatenate((c_values, [prior_c],
                         boundaries * (1.0 - 1e-7), boundaries * (1.0 + 1e-7))))
    c_values = c_values[(c_values >= 0.025) & (c_values <= 5.0)]
    e_values = np.unique(np.concatenate((np.geomspace(0.03, 1.0, max(17, int(grid_e))),
                                        [prior_e, 0.95, 1.0])))
    c = np.repeat(c_values, len(e_values))
    e = np.tile(e_values, len(c_values))
    band_q = c[:, None] * h
    actual = np.where(band_q >= dark, 0, np.where(band_q >= bright, 1, 2))
    declared = {"DARK": 0, "BRIGHT": 1, "BACKUP": 2}.get(declared_program)
    matched = actual == declared
    mult = np.where(matched, match_mult, mismatch_mult)
    a = f * float(duration) * h / f0t0
    sigma = 0.012 + 0.025 * normalized

    def objective(cc, ee, mm):
        factors = np.minimum(1.0, cc[:, None] * ee[:, None] * a)
        predicted = factors * mm
        residual = (predicted - normalized) / sigma
        # Directional losses can hit a subset of fibres. Clipping makes those
        # observations bounded outliers instead of dragging the entire sky down.
        loss = np.mean(np.minimum(residual * residual, 16.0), axis=1)
        loss += 0.025 * ((np.log(cc / prior_c) / 0.30) ** 2
                        + (np.log(ee / prior_e) / 0.35) ** 2)
        return loss, factors, residual

    loss, factors, residual = objective(c, e, mult)
    idx = int(np.argmin(loss))
    chosen_c, chosen_e = float(c[idx]), float(e[idx])

    # In one fixed band pattern the unsaturated observations give Z=C*E
    # algebraically. This removes grid quantization from Q and raw factors.
    selected_mult = mult[idx]
    provisional_factor = normalized / selected_mult
    usable = (provisional_factor > 0.0) & (provisional_factor < 0.985)
    if np.any(usable):
        z_samples = provisional_factor[usable] / a[usable]
        z = float(np.median(z_samples))
        refined_e = float(np.clip(z / chosen_c, 0.03, 1.0))
        refined_loss, refined_factors, refined_resid = objective(
            np.asarray([chosen_c]), np.asarray([refined_e]), selected_mult[None, :])
        if float(refined_loss[0]) <= float(loss[idx]) + 1e-8:
            chosen_e = refined_e
            selected_loss = float(refined_loss[0])
            selected_resid = refined_resid[0]
        else:
            selected_loss = float(loss[idx])
            selected_resid = residual[idx]
    else:
        selected_loss = float(loss[idx])
        selected_resid = residual[idx]

    # The selected multiplier gives each target's measured completion, including
    # directional outliers. Never replace a measured low score with a site model.
    factor_est = np.minimum(1.0, normalized / selected_mult)
    saturated = provisional_factor >= 0.985
    return {"C": chosen_c, "E": chosen_e, "observed_Z": chosen_c * chosen_e,
            "factor_estimates": factor_est.tolist(),
            "factor_lower": lower.tolist(), "factor_upper": upper.tolist(),
            "quality_estimates": (chosen_c * chosen_e * h).tolist(),
            "program_matches": matched[idx].tolist(), "loss": selected_loss,
            "saturated_count": int(np.count_nonzero(saturated)),
            "unsaturated_count": int(np.count_nonzero(usable)),
            "closed_evidence": False, "informative": bool(np.any(usable)),
            "outlier_count": int(np.count_nonzero(np.abs(selected_resid) > 3.0))}


def ar_prior(previous_C: float, previous_E: float, elapsed_slots: float,
             seasonal_C: float = 1.0, *, new_night: bool = False) -> tuple[float, float]:
    """Reference-generator AR mean reversion; retain persistent efficiency faults.

    C is only an approximate scalar sufficient statistic of the three clipped AR
    fields. A correct report should reset E externally; an earthquake changes E
    externally and must not be diagnosed as a fault from this function alone.
    """
    phi = 0.82 if new_night else 0.88 ** max(0.0, float(elapsed_slots))
    return (math.exp(phi * math.log(max(0.02, previous_C))
                     + (1.0 - phi) * math.log(max(0.02, seasonal_C))),
            min(1.0, max(0.025, float(previous_E))))


def seasonal_quality(day_of_year: int, q0: float = 0.68) -> tuple[float, float]:
    """Reference weather prior, not a claim about every competition card."""
    phase = math.sin(2.0 * math.pi * (int(day_of_year) - 210) / 365.2425)
    c = (0.88 - 0.07 * phase) * (1.0 - 0.12 * phase) / ((1.10 + 0.15 * phase) * q0)
    return c, 0.95
