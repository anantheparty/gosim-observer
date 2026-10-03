"""Infer a fixed actual-minus-command alt/az offset from public v4 hit history.

Only membership in ``hits`` is used, including hits whose score is zero. Missing
targets provide geometry evidence only if they remain above the public altitude
limit throughout the executed exposure. A deterministic adaptive grid fits exact
gnomonic hit predicates; its uncertainty is numerical, not an optimality proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Mapping, Sequence

import numpy as np

SIDEREAL_DEG_PER_SECOND = 360.98564736629 / 86400.0
REFERENCE_PRIOR_HALF_DEG = math.degrees(0.002)


def _utc(value: str | datetime) -> datetime:
    return (datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str) else value).astimezone(timezone.utc)


def _lst(moment: datetime, longitude: float) -> float:
    days = moment.timestamp() / 86400.0 + 2440587.5 - 2451545.0
    return (280.46061837 + 360.98564736629 * days + longitude) % 360.0


def _altaz(ra: float, dec: float, moment: datetime, latitude: float, longitude: float):
    hour = math.radians((_lst(moment, longitude) - ra + 180.0) % 360.0 - 180.0)
    lat, dec = math.radians(latitude), math.radians(dec)
    altitude = math.asin(max(-1.0, min(1.0, math.sin(lat) * math.sin(dec)
                                         + math.cos(lat) * math.cos(dec) * math.cos(hour))))
    denominator = max(1e-12, math.cos(altitude))
    sin_az = -math.sin(hour) * math.cos(dec) / denominator
    cos_az = ((math.sin(dec) - math.sin(altitude) * math.sin(lat))
              / (denominator * max(1e-12, math.cos(lat))))
    return math.degrees(altitude), math.degrees(math.atan2(sin_az, cos_az)) % 360.0


def _minimum_altitude(ra: float, dec: float, start: datetime, end: datetime,
                      latitude: float, longitude: float) -> float:
    minimum = min(_altaz(ra, dec, start, latitude, longitude)[0],
                  _altaz(ra, dec, end, latitude, longitude)[0])
    hour = (_lst(start, longitude) - ra) % 360.0
    swept = SIDEREAL_DEG_PER_SECOND * (end - start).total_seconds()
    if (180.0 - hour) % 360.0 <= swept:
        lat, declination = math.radians(latitude), math.radians(dec)
        lower = math.sin(lat) * math.sin(declination) - math.cos(lat) * math.cos(declination)
        minimum = min(minimum, math.degrees(math.asin(max(-1.0, min(1.0, lower)))))
    return minimum


@dataclass(frozen=True)
class _Evidence:
    command_alt: float
    command_az: float
    target_vector: tuple[float, float, float]
    fiber: int
    hit: bool


class PointingCalibrator:
    """Estimate `(delta_alt_deg, delta_az_deg, concentration_confidence)`.

    ``now_utc`` passed to ``update`` is the **exposure start**, not the time at
    which its result arrives. ``action`` must be the actually sent action after
    any previous compensation. ``hits`` is the complete public hit list for it;
    passing ``None`` skips an unavailable result instead of inventing misses.

    The default uniform prior is the published reference generator's ±0.002 rad
    per coordinate. It expands on contradictory evidence up to ``max_prior_deg``.
    Confidence measures concentration of a grid of consistent hypotheses. It is
    not a calibrated probability or a certificate that the true bias lies inside.
    """

    def __init__(self, init_payload: Mapping, *,
                 prior_half_range_deg: float | tuple[float, float] = REFERENCE_PRIOR_HALF_DEG,
                 grid_side: int = 81, min_step_deg: float = 0.0001,
                 max_prior_deg: float = 1.0):
        site, instrument = init_payload["site"], init_payload["instrument"]
        self.latitude = float(site["latitude_deg"])
        self.longitude = float(site["longitude_deg"])
        self.minimum_altitude = float(site.get("minimum_altitude_deg", 30.0))
        self.side = int(instrument["grid_side"])
        self.n_fibers = int(instrument["n_fibers"])
        # Derive from the unrounded public area/gap when available. Rounded
        # glass/pitch fields can change classification at a shared seam.
        self.glass = (math.sqrt(float(instrument["fiber_area_deg2"]))
                      if "fiber_area_deg2" in instrument else float(instrument["glass_side_deg"]))
        self.gap = float(instrument.get("gap_deg", 0.0))
        self.pitch = (self.glass + self.gap if "fiber_area_deg2" in instrument
                      else float(instrument["pitch_deg"]))
        self.fov = self.side * self.pitch
        if self.side * self.side != self.n_fibers or self.glass <= 0 or self.gap < 0:
            raise ValueError("invalid public fiber grid")
        if grid_side < 5 or min_step_deg <= 0 or max_prior_deg <= 0:
            raise ValueError("invalid calibration grid")
        self.grid_side = int(grid_side) | 1
        self.min_step_deg = float(min_step_deg)
        self.max_prior_deg = float(max_prior_deg)
        prior = ((float(prior_half_range_deg),) * 2 if isinstance(prior_half_range_deg, (int, float))
                 else tuple(float(x) for x in prior_half_range_deg))
        if len(prior) != 2 or any(x <= 0 for x in prior):
            raise ValueError("prior half-ranges must be positive")
        self.prior = np.array(prior, dtype=float)
        self.max_prior_deg = max(self.max_prior_deg, float(self.prior.max()))
        survey = init_payload.get("survey", {})
        self.survey_end = _utc(survey["end_utc"]) if survey.get("end_utc") else None
        self.nights = [(_utc(n["observing_start_utc"]), _utc(n["observing_end_utc"]))
                       for n in survey.get("nights", [])]
        target_table = init_payload.get("targets", {})
        columns = {name: index for index, name in enumerate(target_table.get("columns", []))}
        self.targets = {
            str(row[columns["target_id"]]): (float(row[columns["ra_deg"]]), float(row[columns["dec_deg"]]))
            for row in target_table.get("rows", [])
        }
        self.history: list[_Evidence] = []
        self.exposures = 0
        self.skipped_altitude = 0
        self.skipped_metadata = 0
        self.refinements = 0
        self.expansions = 0
        self._estimate = (0.0, 0.0, 0.0)
        self._diagnostics: dict = {}
        self._set_grid(-self.prior, self.prior)
        self._summarize()

    @property
    def estimate(self) -> tuple[float, float, float]:
        return self._estimate

    @property
    def diagnostics(self) -> dict:
        return dict(self._diagnostics)

    def _set_grid(self, lo: np.ndarray, hi: np.ndarray) -> None:
        self.lo, self.hi = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
        axes = []
        for lower, upper in zip(self.lo, self.hi):
            count = min(self.grid_side, max(2, int(math.ceil((upper - lower) / self.min_step_deg)) + 1))
            axes.append(np.linspace(lower, upper, count))
        a, z = np.meshgrid(*axes, indexing="ij")
        self.delta_alt, self.delta_az = a.ravel(), z.ravel()
        self.step = np.array([axis[1] - axis[0] for axis in axes])
        self.mismatches = np.zeros(self.delta_alt.size, dtype=np.int32)
        for evidence in self.history:
            self.mismatches += self._predicted_hits(evidence) != evidence.hit

    def _predicted_hits(self, evidence: _Evidence) -> np.ndarray:
        alt = np.deg2rad(evidence.command_alt + self.delta_alt)
        az = np.deg2rad(evidence.command_az + self.delta_az)
        sa, ca, sz, cz = np.sin(alt), np.cos(alt), np.sin(az), np.cos(az)
        x, y, z = evidence.target_vector
        radial = x * cz + y * sz
        depth = radial * ca + z * sa
        safe_depth = np.where(depth > 0.0, depth, 1.0)
        north = np.rad2deg((-radial * sa + z * ca) / safe_depth)
        east = np.rad2deg((-x * sz + y * cz) / safe_depth)
        middle = self.side / 2.0
        row = np.clip(np.floor(north / self.pitch + middle), 0, self.side - 1).astype(int)
        col = np.clip(np.floor(east / self.pitch + middle), 0, self.side - 1).astype(int)
        valid = ((depth > 0.0) & (alt >= 0.0) & (alt <= math.pi / 2)
                 & (np.abs(north) <= self.fov / 2) & (np.abs(east) <= self.fov / 2)
                 & (row * self.side + col == evidence.fiber))
        if self.gap > 0.0:
            center_north = (row - (self.side - 1) / 2) * self.pitch
            center_east = (col - (self.side - 1) / 2) * self.pitch
            valid &= ((np.abs(north - center_north) <= self.glass / 2)
                      & (np.abs(east - center_east) <= self.glass / 2))
        return valid

    def _adapt_grid(self) -> None:
        # Include one whole old cell beyond each surviving grid point. This
        # reduces lattice truncation; it does not certify continuous coverage.
        minimum = int(self.mismatches.min())
        best = self.mismatches == minimum
        lows = np.array([self.delta_alt[best].min(), self.delta_az[best].min()])
        highs = np.array([self.delta_alt[best].max(), self.delta_az[best].max()])
        lo = np.maximum(-self.prior, lows - 2 * self.step)
        hi = np.minimum(self.prior, highs + 2 * self.step)
        span = self.hi - self.lo
        if np.any(hi - lo < 0.8 * span) and np.max(self.step) > self.min_step_deg * 1.01:
            self._set_grid(lo, hi)
            self.refinements += 1
        # Inconsistent observations can mean a finer grid is needed or the
        # actual card used a wider prior. Expand instead of forcing certainty.
        if int(self.mismatches.min()) > 0 and np.any(self.prior < self.max_prior_deg):
            self.prior = np.minimum(self.max_prior_deg, self.prior * 2)
            self._set_grid(-self.prior, self.prior)
            self.expansions += 1

    def _summarize(self) -> None:
        minimum = int(self.mismatches.min())
        best = self.mismatches == minimum
        points = np.column_stack((self.delta_alt[best], self.delta_az[best]))
        center = points.mean(axis=0)
        # The average of disconnected feasible regions need not be feasible.
        # Return a surviving hypothesis nearest that average, never the average.
        chosen = points[np.argmin(np.sum((points - center) ** 2, axis=1))]
        radius = float(np.quantile(np.max(np.abs(points - chosen), axis=1), 0.95)
                       + np.max(self.step) / 2)
        concentration = math.exp(-radius / max(1e-12, self.glass / 4))
        confidence = (concentration * min(1.0, len(self.history) / 24)
                      if minimum == 0 else 0.0)
        self._estimate = (float(chosen[0]), float(chosen[1]), float(confidence))
        self._diagnostics = {
            "constraints": len(self.history), "exposures": self.exposures,
            "skipped_altitude": self.skipped_altitude, "skipped_metadata": self.skipped_metadata,
            "minimum_mismatches": minimum, "consistent_grid_points": int(best.sum()) if minimum == 0 else 0,
            "uncertainty_radius_95_deg": radius, "grid_step_deg": [float(x) for x in self.step],
            "support_bounds_deg": [[float(points[:, i].min()), float(points[:, i].max())] for i in range(2)],
            "prior_half_range_deg": [float(x) for x in self.prior],
            "refinements": self.refinements, "expansions": self.expansions,
        }

    def update(self, action: Mapping, now_utc: str | datetime,
               hits: Sequence[Mapping | str] | Mapping | None,
               target_metadata: Mapping[str, Mapping | tuple[float, float]] | None = None
               ) -> tuple[float, float, float]:
        if action.get("action") != "observe" or hits is None:
            return self.estimate
        if isinstance(hits, Mapping):
            hits = hits.get("hits")
            if hits is None:
                return self.estimate
        hit_ids = {str(hit.get("target_id")) if isinstance(hit, Mapping) else str(hit) for hit in hits}
        start = _utc(now_utc)
        end = start + timedelta(seconds=int(action["duration_seconds"]))
        if self.survey_end:
            end = min(end, self.survey_end)
        for night_start, night_end in self.nights:
            if night_start <= start < night_end:
                end = min(end, night_end)
                break
        if end <= start:
            return self.estimate
        command = action["pointing"]
        metadata = target_metadata or {}
        added = []
        for fiber, target_id in action["assignments"].items():
            target_id, fiber = str(target_id), int(fiber)
            if not 0 <= fiber < self.n_fibers:
                raise ValueError("assignment fiber outside public grid")
            coordinates = metadata.get(target_id, self.targets.get(target_id))
            if coordinates is None:
                self.skipped_metadata += 1
                continue
            if isinstance(coordinates, Mapping):
                ra, dec = float(coordinates["ra_deg"]), float(coordinates["dec_deg"])
            else:
                ra, dec = map(float, coordinates)
            eligible = _minimum_altitude(ra, dec, start, end, self.latitude, self.longitude) >= self.minimum_altitude
            if not eligible and target_id not in hit_ids:
                self.skipped_altitude += 1
                continue
            alt_deg, az_deg = _altaz(ra, dec, start, self.latitude, self.longitude)
            alt, az = math.radians(alt_deg), math.radians(az_deg)
            vector = (math.cos(alt) * math.cos(az), math.cos(alt) * math.sin(az), math.sin(alt))
            added.append(_Evidence(float(command["alt_deg"]), float(command["az_deg"]),
                                   vector, fiber, target_id in hit_ids))
        self.exposures += 1
        for evidence in added:
            self.history.append(evidence)
            self.mismatches += self._predicted_hits(evidence) != evidence.hit
        if added:
            self._adapt_grid()
        self._summarize()
        return self.estimate
