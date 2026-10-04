"""Vectorized v4 pointing, fibre assignment and exposure optimizer.

No hidden inputs are read.  Public geometry is exact; the predicted weather
quality is supplied by the caller.  Space candidates are deliberately bounded,
while each candidate compares all three programs and target-derived exposure
breakpoints.  See SPATIAL_OPTIMIZER_ZH.md for what is exact and what is heuristic.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import numpy as np

DEG = math.pi / 180.0
SIDEREAL_SPEED = 360.98564736629 / 86400.0
PROGRAMS = ("DARK", "BRIGHT", "BACKUP")
DIRECTION_AZ = {"N": 0.0, "NE": 45.0, "E": 90.0, "SE": 135.0,
                "S": 180.0, "SW": 225.0, "W": 270.0, "NW": 315.0}


def parse_utc(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def local_sidereal(moment, longitude):
    days = moment.timestamp() / 86400.0 + 2440587.5 - 2451545.0
    return (280.46061837 + 360.98564736629 * days + longitude) % 360.0


def _wrap180(x):
    return (x + 180.0) % 360.0 - 180.0


def _sun_moon(moment):
    days = moment.timestamp() / 86400.0 + 2440587.5 - 2451545.0
    solar_mean = (280.460 + 0.9856474 * days) % 360.0
    anomaly = ((357.528 + 0.9856003 * days) % 360.0) * DEG
    solar_lon = (solar_mean + 1.915 * math.sin(anomaly) + .020 * math.sin(2 * anomaly)) * DEG
    obliquity = (23.439 - .0000004 * days) * DEG
    sun = np.array([math.cos(solar_lon), math.sin(solar_lon) * math.cos(obliquity),
                    math.sin(solar_lon) * math.sin(obliquity)])
    longitude = ((218.316 + 13.176396 * days) % 360.0) * DEG
    lunar_anomaly = ((134.963 + 13.064993 * days) % 360.0) * DEG
    argument_latitude = ((93.272 + 13.229350 * days) % 360.0) * DEG
    longitude += 6.289 * DEG * math.sin(lunar_anomaly)
    latitude = 5.128 * DEG * math.sin(argument_latitude)
    moon = np.array([math.cos(longitude) * math.cos(latitude),
                     math.sin(longitude) * math.cos(latitude) * math.cos(obliquity) - math.sin(latitude) * math.sin(obliquity),
                     math.sin(longitude) * math.cos(latitude) * math.sin(obliquity) + math.sin(latitude) * math.cos(obliquity)])
    return moon, (1.0 - float(sun @ moon)) / 2.0


def _shift_altaz(alt, az, north_offset, east_offset):
    a, z = alt * DEG, az * DEG
    p = np.array([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])
    north = np.array([-math.sin(a) * math.cos(z), -math.sin(a) * math.sin(z), math.cos(a)])
    east = np.array([-math.sin(z), math.cos(z), 0.0])
    p += north_offset * DEG * north + east_offset * DEG * east
    p /= np.linalg.norm(p)
    return math.asin(float(np.clip(p[2], -1, 1))) / DEG, math.atan2(p[1], p[0]) / DEG % 360.0


class SpatialPlanner:
    """Use ``choose(snapshot,best_scores,best_factors,env_estimate,requests)``.

    ``best_scores`` and ``best_factors`` accept arrays in public-catalogue order
    or dictionaries keyed by target id.  Factors must track maximum raw factor,
    independently of maximum program-multiplied score.  ``env_estimate`` accepts
    quality_scale, program_band_quality_scale, duration_safety (>=1),
    planning_budget_seconds, target_quality_scale (catalogue-order array), and
    pointing_offset_alt_deg/pointing_offset_az_deg (estimated actual-command).
    ``last_prediction`` is metadata for the caller's feedback filter, never sent
    in the action itself.
    """
    def __init__(self, initial_payload):
        self.init = initial_payload
        site = initial_payload["site"]
        self.lat = float(site["latitude_deg"])
        self.lon = float(site["longitude_deg"])
        self.min_alt = float(site.get("minimum_altitude_deg", 30.0))
        instrument = initial_payload["instrument"]
        self.nfib = int(instrument["n_fibers"])
        self.side = int(instrument.get("grid_side", math.isqrt(self.nfib)))
        self.glass = float(instrument.get("glass_side_deg", math.sqrt(float(instrument.get("fiber_area_deg2", .4)))))
        self.pitch = float(instrument.get("pitch_deg", self.glass + float(instrument.get("gap_deg", 0))))
        self.fov = float(instrument.get("fov_side_deg", self.side * self.pitch))
        exposure = instrument.get("exposure", {})
        self.tmin = int(exposure.get("min_duration_seconds", 60))
        self.tmax = int(exposure.get("max_duration_seconds", 3600))
        columns = initial_payload["targets"]["columns"]
        col = {name: k for k, name in enumerate(columns)}
        rows = initial_payload["targets"]["rows"]
        self.ids = [str(row[col["target_id"]]) for row in rows]
        self.index = {target: i for i, target in enumerate(self.ids)}
        self.ra = np.asarray([float(row[col["ra_deg"]]) for row in rows])
        self.dec = np.asarray([float(row[col["dec_deg"]]) for row in rows])
        self.flux = np.asarray([float(row[col["feature_flux"]]) for row in rows])
        self.weight = np.asarray([float(row[col["science_weight"]]) for row in rows])
        self.required = np.asarray([str(row[col["required"]]).lower() in ("true", "1") for row in rows], dtype=bool)
        self.n = len(self.ids)
        self.sin_dec, self.cos_dec = np.sin(self.dec * DEG), np.cos(self.dec * DEG)
        self.eq_vectors = np.column_stack((self.cos_dec * np.cos(self.ra * DEG), self.cos_dec * np.sin(self.ra * DEG), self.sin_dec))
        self.sin_lat, self.cos_lat = math.sin(self.lat * DEG), math.cos(self.lat * DEG)
        limit = (math.sin((self.min_alt + .04) * DEG) - self.sin_lat * self.sin_dec) / np.maximum(1e-12, self.cos_lat * self.cos_dec)
        self.hmax = np.arccos(np.clip(limit, -1, 1)) / DEG
        self.hmax[limit >= 1.0] = 0.0
        self.hmax[limit <= -1.0] = 180.0
        config = initial_payload.get("scoring", {})
        self.q0 = float(config.get("q0", .68))
        self.f0t0 = float(config.get("flux_zero_point", .5)) * float(config.get("exposure_zero_point_seconds", 900))
        self.airmass_exponent = float(config.get("airmass_exponent", .6))
        self.lunar = config.get("lunar_model", {})
        program = config.get("program", {})
        bands = program.get("bands", {})
        self.dark_threshold = float(bands.get("DARK", .65))
        self.bright_threshold = float(bands.get("BRIGHT", .4))
        multipliers = program.get("multipliers", {})
        self.multipliers = np.asarray([float(multipliers.get(p, d)) for p, d in zip(PROGRAMS, (1.2, 1.12, 1.06))])
        self.mismatch = float(program.get("mismatch_multiplier", 1))
        required = config.get("required", {})
        self.req_threshold = float(required.get("observed_factor_threshold", .5))
        self.req_penalty = float(required.get("penalty_per_missing", 50))
        uniformity = config.get("uniformity", {})
        self.uniform_threshold = float(uniformity.get("observed_factor_threshold", .5))
        self.uniform_weight = float(uniformity.get("weight", 200))
        width = float(uniformity.get("ra_band_width_deg", 10))
        self.ra_bands = np.floor(self.ra / width).astype(np.int32)
        self.band_sizes = np.bincount(self.ra_bands)
        self.nonempty_bands = int(np.count_nonzero(self.band_sizes))
        survey = initial_payload["survey"]
        self.nights = [(parse_utc(n["observing_start_utc"]), parse_utc(n["observing_end_utc"])) for n in survey["nights"]]
        self.last_night = np.full(self.n, -1, dtype=np.int32)
        self.night_visibility = np.zeros((len(self.nights), self.n), dtype=bool)
        for k, (start, end) in enumerate(self.nights):
            l0 = local_sidereal(start, self.lon)
            span = (end - start).total_seconds() * SIDEREAL_SPEED
            rising = (self.ra - self.hmax - l0) % 360.0
            overlap = np.maximum(0, np.minimum(span, rising + 2 * self.hmax) - rising)
            overlap += np.maximum(0, np.minimum(span, rising - 360.0 + 2 * self.hmax))
            overlap[self.hmax >= 180] = span
            usable = overlap >= self.tmin * SIDEREAL_SPEED
            self.night_visibility[k] = usable
            self.last_night[usable] = k
        self.future_nights = np.cumsum(self.night_visibility[::-1], axis=0)[::-1]
        # Equal-area-ish declination strips, used only to seed space candidates.
        band_dec = np.floor((self.dec + 90) / max(.8, self.fov / 2))
        center_dec = (band_dec + .5) * max(.8, self.fov / 2) - 90
        ncols = np.maximum(1, np.rint(360 * np.cos(center_dec * DEG) / max(.8, self.fov / 2)).astype(int))
        keys = band_dec.astype(np.int64) * 1000 + np.floor(self.ra / 360 * ncols).astype(np.int64)
        _, self.space_bins = np.unique(keys, return_inverse=True)
        self.bin_count = int(self.space_bins.max()) + 1 if self.n else 0
        self.last_prediction = {}
        self.stats = {}
        self.terrain_directions = set()

    def _array(self, values):
        if isinstance(values, dict):
            return np.fromiter((float(values.get(t, 0.0)) for t in self.ids), dtype=float, count=self.n)
        a = np.asarray(values, dtype=float)
        return a if a.shape == (self.n,) else np.zeros(self.n)

    def _altaz(self, lst):
        hour = _wrap180(lst - self.ra)
        sin_alt = self.sin_lat * self.sin_dec + self.cos_lat * self.cos_dec * np.cos(hour * DEG)
        alt = np.arcsin(np.clip(sin_alt, -1, 1)) / DEG
        cos_alt = np.maximum(1e-12, np.cos(alt * DEG))
        sin_az = -np.sin(hour * DEG) * self.cos_dec / cos_alt
        cos_az = (self.sin_dec - sin_alt * self.sin_lat) / (cos_alt * self.cos_lat)
        az = np.arctan2(sin_az, cos_az) / DEG % 360.0
        vectors = np.column_stack((cos_alt * np.cos(az * DEG), cos_alt * np.sin(az * DEG), sin_alt))
        return alt, az, hour, vectors

    def _public_quality(self, now, lst, alt):
        zenith = 90.0 - np.maximum(alt, 1.0)
        raw_airmass = 1 / (np.cos(zenith * DEG) + .50572 * (96.07995 - zenith) ** -1.6364)
        zenith_raw = 1 / (1 + .50572 * 96.07995 ** -1.6364)
        airmass = raw_airmass / zenith_raw
        moon, illumination = _sun_moon(now)
        moon_dec = math.asin(float(np.clip(moon[2], -1, 1)))
        moon_ra = math.atan2(moon[1], moon[0]) / DEG % 360.0
        moon_alt = math.asin(self.sin_lat * math.sin(moon_dec) + self.cos_lat * math.cos(moon_dec) * math.cos(_wrap180(lst - moon_ra) * DEG))
        lunar = np.ones(self.n)
        if moon_alt > 0:
            separation = np.arccos(np.clip(np.sum(self.eq_vectors * moon, axis=1), -1, 1)) / DEG
            penalty = float(self.lunar.get("maximum_penalty", .5)) * illumination * math.sin(moon_alt) ** float(self.lunar.get("altitude_exponent", 1))
            lunar -= penalty * np.exp(-separation / float(self.lunar.get("angular_decay_scale_deg", 40)))
        return np.clip(lunar, 0, 1) / (self.q0 * airmass ** self.airmass_exponent)

    def _classify(self, vectors, c_alt, c_az):
        a, z = c_alt * DEG, c_az * DEG
        center = np.array([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])
        north = np.array([-math.sin(a) * math.cos(z), -math.sin(a) * math.sin(z), math.cos(a)])
        east = np.array([-math.sin(z), math.cos(z), 0.0])
        depth = np.sum(vectors * center, axis=1)
        north_offset = (np.sum(vectors * north, axis=1)) / np.maximum(depth, 1e-12) / DEG
        east_offset = (np.sum(vectors * east, axis=1)) / np.maximum(depth, 1e-12) / DEG
        row = np.clip(np.floor(north_offset / self.pitch + self.side / 2).astype(np.int32), 0, self.side - 1)
        col = np.clip(np.floor(east_offset / self.pitch + self.side / 2).astype(np.int32), 0, self.side - 1)
        cn = (row - (self.side - 1) / 2) * self.pitch
        ce = (col - (self.side - 1) / 2) * self.pitch
        margin = self.glass / 2 - np.maximum(np.abs(north_offset - cn), np.abs(east_offset - ce))
        valid = (depth > 0) & (np.abs(north_offset) <= self.fov / 2) & (np.abs(east_offset) <= self.fov / 2) & (margin >= .008)
        return row * self.side + col, valid, margin

    def _request_terms(self, requests, now):
        reward = np.zeros(self.n)
        threshold = np.zeros(self.n)
        deadline = np.full(self.n, np.inf)
        prepared = []
        for req in requests or []:
            left = max(0, int(req.get("remaining_count", int(req.get("minimum_completed", 0)) - int(req.get("completed_count", 0)))))
            if not left:
                continue
            end = parse_utc(req["deadline_utc"])
            seconds = (end - now).total_seconds()
            if seconds < self.tmin:
                continue
            done = set(req.get("completed_target_ids", []))
            idx = np.asarray([self.index[t] for t in req.get("target_ids", []) if t in self.index and t not in done], dtype=int)
            if not len(idx):
                continue
            t = float(req.get("completion_factor_threshold", .5))
            bonus = float(req.get("completion_reward", 0)) / left
            # A proportional terminal reward is a rolling-planning shadow price.
            reward[idx] += bonus
            threshold[idx] = np.maximum(threshold[idx], t)
            deadline[idx] = np.minimum(deadline[idx], seconds)
            prepared.append((req, idx, left, t, seconds))
        return reward, threshold, deadline, prepared

    def choose(self, snapshot, best_scores, best_factors, env_estimate=None, active_requests=None):
        started = time.perf_counter()
        env = env_estimate or {}
        budget = max(.01, float(env.get("planning_budget_seconds", .095)))
        now = parse_utc(snapshot["now_utc"])
        current_night = next((k for k, (start, end) in enumerate(self.nights) if start <= now < end), None)
        if current_night is None:
            return None
        seconds_left = min(self.tmax, int((self.nights[current_night][1] - now).total_seconds()))
        if seconds_left < self.tmin:
            return None
        scores, factors = self._array(best_scores), self._array(best_factors)
        lst = local_sidereal(now, self.lon)
        alt, az, hour, vectors = self._altaz(lst)
        up = np.where(self.hmax >= 180, 1e9, (self.hmax - hour) / SIDEREAL_SPEED)
        up = np.maximum(0, up - 1)
        visible = (alt >= self.min_alt + .04) & (up >= self.tmin)
        public_quality = self._public_quality(now, lst, alt)
        quality_scale = max(.005, float(env.get("quality_scale", .55)))
        band_scale = max(.005, float(env.get("program_band_quality_scale", quality_scale / .95)))
        scale = np.full(self.n, quality_scale)
        directional_scale = np.ones(self.n)
        notices = (snapshot.get("latest_bulletin") or {}).get("notices", [])
        for message in snapshot.get("new_messages", []):
            if message.get("record_type") == "bulletin" and message.get("initial"):
                self.terrain_directions.update(n.get("direction") for n in message.get("notices", []) if n.get("event_kind") == "terrain_obstruction")
        if (snapshot.get("latest_bulletin") or {}).get("initial"):
            self.terrain_directions.update(n.get("direction") for n in notices if n.get("event_kind") == "terrain_obstruction")
        if env.get("use_bulletin_directional_prior", True):
            directional_notices = list(notices) + [{"event_kind": "terrain_obstruction", "direction": d} for d in self.terrain_directions]
            for notice in directional_notices:
                direction = notice.get("direction")
                if direction not in DIRECTION_AZ:
                    continue
                kind = notice.get("event_kind")
                near = np.abs(_wrap180(az - DIRECTION_AZ[direction])) <= 55.0
                limit, prior = (47.0, .25) if kind == "terrain_obstruction" else ((62.0, .35) if kind == "rocket_launch" else (73.0, .7))
                directional_scale[near & (alt < limit)] = np.minimum(directional_scale[near & (alt < limit)], prior)
        for direction, prior in env.get("directional_quality_scales", {}).items():
            if direction in DIRECTION_AZ:
                near = np.abs(_wrap180(az - DIRECTION_AZ[direction])) <= 60.0
                directional_scale[near & (alt < 75.0)] *= float(prior)
        scale *= directional_scale
        if env.get("target_quality_scale") is not None:
            scale *= np.asarray(env["target_quality_scale"], dtype=float)
        safety = max(1.0, float(env.get("duration_safety", 1.06)))
        quality = public_quality * scale
        k = self.flux * quality / max(1e-9, self.f0t0)
        actual_bands = np.where(public_quality * band_scale >= self.dark_threshold, 0,
                               np.where(public_quality * band_scale >= self.bright_threshold, 1, 2))
        multiplier = np.where(actual_bands[None, :] == np.arange(3)[:, None], self.multipliers[:, None], self.mismatch)
        req_missing = self.required & (factors + 1e-8 < self.req_threshold)
        req_reward, request_threshold, request_deadline, prepared_requests = self._request_terms(active_requests if active_requests is not None else snapshot.get("active_requests", []), now)
        focus_request = None
        if prepared_requests:
            req, request_idx, left, req_t, deadline = max(prepared_requests, key=lambda x: float(x[0].get("completion_reward", 0)) / x[2])
            membership = np.zeros(self.n, dtype=bool)
            membership[request_idx] = True
            focus_request = (membership, float(req.get("completion_reward", 0)), left, req_t, deadline)
        max_duration = np.minimum(up, seconds_left)
        reachable = np.minimum(1.0, k * max_duration / safety)
        science_potential = np.maximum(0, self.weight * reachable * np.max(multiplier, axis=0) - scores)
        eligible_req = req_missing & (reachable >= self.req_threshold)
        eligible_request = (req_reward > 0) & (reachable >= request_threshold)
        nights_left = np.maximum(1, self.future_nights[current_night])
        urgency = 1 + .8 / nights_left + .3 * np.maximum(hour, 0) / np.maximum(self.hmax, 1)
        priority = science_potential * np.minimum(1, k * 900)
        priority += eligible_req * self.req_penalty * np.minimum(1, k * 900 / self.req_threshold)
        priority += eligible_request * req_reward * np.minimum(1, k * 900 / np.maximum(request_threshold, .01))
        priority *= urgency * visible
        positive = np.flatnonzero(priority > 1e-10)
        if not len(positive):
            return None
        # Smooth uniformity pressure from the exact Jain-index derivative.
        completed = factors >= self.uniform_threshold
        band_completed = np.bincount(self.ra_bands, weights=completed, minlength=len(self.band_sizes))
        proportions = np.divide(band_completed, self.band_sizes, out=np.zeros_like(band_completed), where=self.band_sizes > 0)
        s, v = float(proportions.sum()), float(proportions @ proportions)
        uniform_bonus = np.zeros(self.n)
        if v > 0:
            gradient = (2 * s / (self.nonempty_bands * v) - 2 * s * s * proportions / (self.nonempty_bands * v * v))
            grad_per_target = np.divide(gradient, self.band_sizes, out=np.zeros_like(gradient), where=self.band_sizes > 0)
            progress_scale = min(1.0, float(completed.mean()) / .2)
            uniform_bonus = self.uniform_weight * progress_scale * grad_per_target[self.ra_bands]
        # Dense-bin seeds plus individual priorities avoid isolated-bright-star bias.
        bin_values = np.bincount(self.space_bins, weights=priority, minlength=self.bin_count)
        top_bins = np.argsort(bin_values)[-min(24, self.bin_count):][::-1]
        seeds = []
        for b in top_bins:
            members = np.flatnonzero((self.space_bins == b) & (priority > 0))
            if len(members):
                seeds.append(int(members[np.argmax(priority[members])]))
        seeds.extend(int(i) for i in positive[np.argsort(priority[positive])[-12:][::-1]])
        anchors = []
        cosine_separation = math.cos(max(.3, self.fov * .35) * DEG)
        for i in seeds:
            if all(float(self.eq_vectors[i] @ self.eq_vectors[j]) < cosine_separation for j in anchors):
                anchors.append(i)
            if len(anchors) >= int(env.get("anchor_count", 8)):
                break
        fiber_positions = np.arange(self.nfib)
        if self.nfib > 25:
            selected = np.unique(np.rint(np.linspace(0, self.side - 1, 5)).astype(int))
            fiber_positions = np.asarray([r * self.side + c for r in selected for c in selected])
        best = None
        evaluated = 0
        radius_cosine = math.cos((self.fov * math.sqrt(2) + .3) * DEG)
        for anchor in anchors:
            pool = np.flatnonzero(visible & (np.sum(self.eq_vectors * self.eq_vectors[anchor], axis=1) >= radius_cosine) & (priority > 0))
            for f in fiber_positions:
                if best is not None and time.perf_counter() - started > budget:
                    break
                row, col = divmod(int(f), self.side)
                dn, de = (row - (self.side - 1) / 2) * self.pitch, (col - (self.side - 1) / 2) * self.pitch
                center = _shift_altaz(float(alt[anchor]), float(az[anchor]), -dn, -de)
                if not 0.0 <= center[0] <= 90.0:
                    continue
                candidate = self._evaluate(center, pool, vectors, up, k, scores, factors, multiplier, req_missing,
                                           req_reward, request_threshold, request_deadline, uniform_bonus, urgency,
                                           seconds_left, safety, focus_request)
                evaluated += 1
                if candidate and (best is None or candidate[0] > best[0]):
                    best = candidate
            if best is not None and time.perf_counter() - started > budget:
                break
        # Refine the strongest pointing at two spatial resolutions when budget permits.
        if best is not None:
            refine_pool = np.flatnonzero(visible & (priority > 0))
            for fraction in (.22, .08):
                base = best[1]
                for dn, de in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                    if time.perf_counter() - started > budget:
                        break
                    center = _shift_altaz(*base, dn * self.pitch * fraction, de * self.pitch * fraction)
                    a, z = center[0] * DEG, center[1] * DEG
                    cvec = np.array([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])
                    pool = refine_pool[(np.sum(vectors[refine_pool] * cvec, axis=1)) >= math.cos(self.fov * DEG)]
                    candidate = self._evaluate(center, pool, vectors, up, k, scores, factors, multiplier, req_missing,
                                               req_reward, request_threshold, request_deadline, uniform_bonus, urgency,
                                               seconds_left, safety, focus_request)
                    evaluated += 1
                    if candidate and candidate[0] > best[0]:
                        best = candidate
        self.stats = {"planning_seconds": time.perf_counter() - started, "candidates": evaluated,
                      "visible_useful": len(positive), "anchors": len(anchors)}
        if best is None:
            self.last_prediction = {}
            return None
        _, center, duration, program, chosen, fibers = best
        offset_alt = float(env.get("pointing_offset_alt_deg", 0.0))
        offset_az = float(env.get("pointing_offset_az_deg", 0.0))
        cmd_alt = center[0] - offset_alt
        if not 0 <= cmd_alt <= 90:
            return None
        self.last_prediction = {self.ids[int(i)]: {"index": int(i), "fiber_id": int(f), "factor": min(1., float(k[i] * duration)),
                                                  "public_quality": float(public_quality[i]), "quality": float(quality[i]),
                                                  "directional_scale": float(directional_scale[i]),
                                                  "predicted_band": PROGRAMS[int(actual_bands[i])],
                                                  "alt_deg": float(alt[i]), "az_deg": float(az[i])}
                                for i, f in zip(chosen, fibers)}
        return {"action": "observe", "pointing": {"alt_deg": round(cmd_alt, 7), "az_deg": round((center[1] - offset_az) % 360, 7)},
                "assignments": {str(int(f)): self.ids[int(i)] for i, f in zip(chosen, fibers)},
                "duration_seconds": int(duration), "program": PROGRAMS[int(program)]}

    def _evaluate(self, center, pool, vectors, up, k, scores, factors, multiplier, req_missing,
                  request_reward, request_threshold, request_deadline, uniform_bonus, urgency,
                  seconds_left, safety, focus_request=None):
        if not len(pool):
            return None
        fiber, valid, margin = self._classify(vectors[pool], *center)
        idx, fiber, margin = pool[valid], fiber[valid], margin[valid]
        if not len(idx):
            return None
        ki = k[idx]
        # Exact breakpoints for the frozen-Q model, rounded upward to integer seconds.
        times = [self.tmin, seconds_left]
        times.extend(np.ceil(1.0 / np.maximum(ki, 1e-12)).tolist())
        times.extend(np.floor(1.0 / np.maximum(ki, 1e-12)).tolist())
        for threshold, mask in ((self.req_threshold, req_missing[idx]),
                                (self.uniform_threshold, factors[idx] < self.uniform_threshold)):
            times.extend(np.ceil(threshold * safety / np.maximum(ki[mask], 1e-12)).tolist())
        rt = request_threshold[idx]
        rm = request_reward[idx] > 0
        times.extend(np.ceil(rt[rm] * safety / np.maximum(ki[rm], 1e-12)).tolist())
        if focus_request is not None:
            membership, _, _, focus_threshold, _ = focus_request
            focus_mask = membership[idx]
            times.extend(np.ceil(focus_threshold * safety / np.maximum(ki[focus_mask], 1e-12)).tolist())
        times.extend(np.floor(up[idx]).tolist())
        times.extend((300, 600, 900, 1200, 1800, 2400, 3600))
        durations = np.unique(np.clip(np.asarray(times, dtype=int), self.tmin, seconds_left))
        durations = durations[(durations >= self.tmin) & (durations <= seconds_left)]
        if len(durations) > 72:
            durations = durations[np.unique(np.rint(np.linspace(0, len(durations) - 1, 72)).astype(int))]
        t = durations[:, None]
        raw = np.minimum(1., t * ki[None, :])
        robust_raw = np.minimum(1., t * ki[None, :] / safety)
        req_done = req_missing[idx][None, :] & (robust_raw + 1e-10 >= self.req_threshold)
        uniform_done = (factors[idx][None, :] < self.uniform_threshold) & (robust_raw + 1e-10 >= self.uniform_threshold)
        request_done = (request_reward[idx][None, :] > 0) & (robust_raw + 1e-10 >= rt[None, :]) & (t <= request_deadline[idx][None, :])
        science = np.maximum(0., self.weight[idx][None, None, :] * raw[:, None, :] * multiplier[:, idx][None, :, :] - scores[idx][None, None, :])
        terminal = req_done * self.req_penalty + uniform_done * uniform_bonus[idx][None, :] + request_done * request_reward[idx][None, :]
        focus_eligible = None
        if focus_request is not None:
            membership, focus_reward, focus_left, focus_threshold, focus_deadline = focus_request
            focus_eligible = membership[idx][None, :] & (robust_raw + 1e-10 >= focus_threshold) & (t <= focus_deadline)
            # Replace one request's distributed shadow price with its exact quota.
            terminal -= focus_eligible * (focus_reward / focus_left)
        # Scarcity is the primal-dual scheduling price; current score remains separate.
        value = (science + terminal[:, None, :]) * urgency[idx][None, None, :]
        allowed = t <= up[idx][None, :]
        value = np.where(allowed[:, None, :], value, -np.inf)
        shape = (len(durations), 3, self.nfib)
        best_cell = np.zeros(shape)
        offsets = np.arange(len(durations) * 3)[:, None] * self.nfib + fiber[None, :]
        np.maximum.at(best_cell.ravel(), offsets.ravel(), value.reshape(len(durations) * 3, -1).ravel())
        total = best_cell.sum(axis=2)
        focus_costs = None
        force_counts = None
        if focus_eligible is not None:
            eligible_values = np.where((focus_eligible & allowed)[:, None, :], value, -np.inf)
            eligible_cell = np.full(shape, -np.inf)
            np.maximum.at(eligible_cell.ravel(), offsets.ravel(), eligible_values.reshape(len(durations) * 3, -1).ravel())
            focus_costs = best_cell - eligible_cell
            ordered_costs = np.sort(focus_costs, axis=2)
            # Exact for a single completion reward: cover the quota by choosing the
            # fibres whose request-target alternatives have the smallest regret.
            quota = min(focus_left, self.nfib)
            available = np.sum(np.isfinite(focus_costs), axis=2)
            complete_possible = (focus_left <= self.nfib) & (available >= focus_left)
            quota_cost = ordered_costs[:, :, :quota].sum(axis=2)
            full_value = np.where(complete_possible, total + focus_reward - quota_cost, -np.inf)
            # If a field cannot finish the request, price progress as the fraction
            # of the terminal reward, capped at its remaining quota.
            partial_gain = np.maximum(0., focus_reward / focus_left - ordered_costs[:, :, :quota]).sum(axis=2)
            partial_value = total + partial_gain
            use_full = complete_possible & (full_value >= total - 1e-10)
            total = np.where(complete_possible, np.maximum(total, full_value), partial_value)
            force_counts = np.where(complete_possible, np.where(use_full, focus_left, 0), np.sum(ordered_costs[:, :, :quota] < focus_reward / focus_left, axis=2))
        rates = total / durations[:, None]
        # For a new target, gain/t is flat before saturation.  Prefer the
        # largest gain on such a plateau so the best-only ledger does not invite
        # several non-accumulating short exposures of the same field.
        max_rate = float(rates.max())
        tied = rates >= max_rate - 1e-10 * max(1.0, max_rate)
        flat = int(np.argmax(np.where(tied, total, -np.inf)))
        d, p = divmod(flat, 3)
        if rates[d, p] <= 1e-12:
            return None
        selected, fibers = [], []
        force_fibers = set()
        if focus_costs is not None:
            force_fibers = set(int(f) for f in np.argsort(focus_costs[d, p])[:int(force_counts[d, p])])
        for f in range(self.nfib):
            candidates = np.flatnonzero((fiber == f) & (focus_eligible[d] if f in force_fibers else True))
            if len(candidates):
                j = int(candidates[np.argmax(value[d, p, candidates])])
                if value[d, p, j] > 0 or f in force_fibers:
                    selected.append(int(idx[j]))
                    fibers.append(f)
        return float(rates[d, p]), center, int(durations[d]), p, np.asarray(selected, dtype=int), np.asarray(fibers, dtype=int)
