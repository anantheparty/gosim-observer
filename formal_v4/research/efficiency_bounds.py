"""Conservative efficiency evidence from public, rounded exposure scores.

An upper bound below the normal efficiency floor proves a scoring-efficiency
anomaly only when directional effects and earthquakes have been excluded. It
does not itself prove that report_fault will repair the anomaly.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def infer_efficiency_upper(
    hits: Sequence,
    weights: Sequence[float],
    flux: Sequence[float],
    duration: float,
    program: str,
    scoring: Mapping,
    *,
    normal_lower: float = 0.90,
) -> dict:
    """Return E_upper, per_target_upper, strong_count and witness_count.

    Inputs retain the same target order. hits accepts score numbers or public
    {target_id,score} records. E_upper=None means no guaranteed unsaturated,
    program-matched witness. Only DARK and BRIGHT have a positive band lower bound.
    The score rounding interval is +/-0.500001e-6 in original score units.
    """
    records = list(hits)
    if not (len(records) == len(weights) == len(flux)):
        raise ValueError("hits, weights and flux must have equal lengths")
    if not math.isfinite(float(duration)) or float(duration) <= 0:
        raise ValueError("duration must be positive and finite")
    settings = scoring.get("program", {})
    multipliers = settings.get("multipliers", {"DARK": 1.20, "BRIGHT": 1.12, "BACKUP": 1.06})
    multiplier = float(multipliers.get(program, 1.0))
    mismatch = float(settings.get("mismatch_multiplier", 1.0))
    threshold = float(settings.get("bands", {}).get(program, {"DARK": .65, "BRIGHT": .40}.get(program, 0)))
    f0t0 = float(scoring.get("flux_zero_point", .5)) * float(scoring.get("exposure_zero_point_seconds", 900))
    per_target: list[float | None] = []
    matched_unsaturated: list[str | None] = []
    if program not in ("DARK", "BRIGHT") or threshold <= 0 or multiplier <= mismatch:
        return {"E_upper": None, "per_target_upper": [None] * len(records),
                "strong_count": 0, "witness_count": 0, "witness_target_ids": []}
    for hit, weight, feature_flux in zip(records, weights, flux):
        score = float(hit.get("score", 0.0) if isinstance(hit, Mapping) else hit)
        weight, feature_flux = float(weight), float(feature_flux)
        if not (math.isfinite(score) and math.isfinite(weight) and math.isfinite(feature_flux)) or weight <= 0 or feature_flux <= 0:
            per_target.append(None)
            continue
        y_lower = max(0.0, score - .500001e-6) / weight
        y_upper = max(0.0, score + .500001e-6) / weight
        # A mismatched program cannot produce y>mismatch, even when g saturates.
        # An upper endpoint below multiplier also rules out saturation.
        if y_lower <= mismatch or y_upper >= multiplier:
            per_target.append(None)
            continue
        g_upper = y_upper / multiplier
        q_upper = g_upper * f0t0 / (feature_flux * float(duration))
        bound = q_upper / threshold
        per_target.append(bound)
        matched_unsaturated.append(str(hit.get("target_id")) if isinstance(hit, Mapping) and "target_id" in hit else None)
    available = [bound for bound in per_target if bound is not None]
    return {"E_upper": min(available) if available else None,
            "per_target_upper": per_target,
            "strong_count": sum(bound < float(normal_lower) for bound in available),
            "witness_count": len(available),
            "witness_target_ids": [target for target in matched_unsaturated if target is not None]}
