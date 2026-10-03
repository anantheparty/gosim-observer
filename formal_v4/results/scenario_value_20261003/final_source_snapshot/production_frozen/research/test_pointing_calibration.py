"""Synthetic cross-checks against the official v4 geometry, using public inputs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import random
import sys
import time
import unittest

BASE = Path(__file__).resolve().parents[1]
UPSTREAM = BASE / "upstream" / "gosim-observer-examples"
sys.path.insert(0, str(UPSTREAM / "runner"))
sys.path.insert(0, str(UPSTREAM / "python"))

from challenge.v4_fiber_map import FiberGrid, altaz_to_radec, min_altitude_during  # noqa: E402
from agent_core.geometry import shift_altaz  # noqa: E402
from pointing_calibration import PointingCalibrator, _Evidence  # noqa: E402


def payload():
    return {
        "site": {"latitude_deg": -30.169, "longitude_deg": -70.806,
                 "minimum_altitude_deg": 30.0},
        "instrument": {"grid_side": 4, "n_fibers": 16, "fiber_area_deg2": 0.4,
                       "glass_side_deg": 0.632456, "pitch_deg": 0.632456,
                       "fov_side_deg": 2.529822, "gap_deg": 0.0},
        "targets": {"columns": ["target_id", "ra_deg", "dec_deg"], "rows": []},
    }


def exposure(number, rng, grid, init, bias, altitude=None):
    moment = datetime(2026, 11, 15, tzinfo=timezone.utc) + timedelta(hours=number)
    alt = altitude if altitude is not None else [38.0, 53.0, 72.0, 88.0][number % 4]
    az = (rng.uniform(0, 360) if number % 3 else 359.98)
    site = init["site"]
    metadata, assignments, hits = {}, {}, []
    duration = 60
    for fiber in range(grid.n_fibers):
        north, east = grid.fiber_center_offset(fiber)
        north += rng.uniform(-0.495, 0.495) * grid.fiber_side_deg
        east += rng.uniform(-0.495, 0.495) * grid.fiber_side_deg
        target_alt, target_az = shift_altaz(alt, az, north, east)
        ra, dec = altaz_to_radec(target_alt, target_az, moment,
                               site["latitude_deg"], site["longitude_deg"])
        target_id = f"S{number:03d}_{fiber:02d}"
        assignments[str(fiber)] = target_id
        metadata[target_id] = (ra, dec)
        classified = grid.classify_target(ra, dec, moment, alt, az,
                                         site["latitude_deg"], site["longitude_deg"], *bias)
        eligible = min_altitude_during(ra, dec, moment, moment + timedelta(seconds=duration),
                                      {"site": site}) >= site["minimum_altitude_deg"]
        if eligible and classified.region == "glass" and classified.fiber_id == fiber:
            # Every other exposure has zero-score weather but retains all hits.
            hits.append({"target_id": target_id, "score": 0.0 if number % 2 else 1.0})
    action = {"action": "observe", "pointing": {"alt_deg": alt, "az_deg": az},
              "assignments": assignments, "duration_seconds": duration, "program": "DARK"}
    return action, moment, hits, metadata


def synthetic_fit(bias, seed, count=80):
    init, grid = payload(), FiberGrid(0.4, 0.0, 16)
    rng = random.Random(seed)
    calibrator = PointingCalibrator(init)
    started = time.perf_counter()
    for number in range(count):
        action, moment, hits, metadata = exposure(number, rng, grid, init, bias)
        calibrator.update(action, moment, hits, metadata)
    estimate = calibrator.estimate
    return {
        "bias_deg": list(bias), "estimate": list(estimate),
        "maximum_error_deg": max(abs(estimate[i] - bias[i]) for i in range(2)),
        "runtime_seconds": time.perf_counter() - started,
        "diagnostics": calibrator.diagnostics,
    }


class CalibrationTests(unittest.TestCase):
    def test_exact_predicate_matches_official(self):
        init, grid = payload(), FiberGrid(0.4, 0.0, 16)
        calibrator = PointingCalibrator(init)
        rng = random.Random(136)
        for number in range(12):
            command_alt = [31.0, 65.0, 88.0][number % 3]
            command_az = rng.uniform(0, 360)
            target_alt, target_az = shift_altaz(command_alt, command_az,
                                              rng.uniform(-1.5, 1.5), rng.uniform(-1.5, 1.5))
            ta, tz = math.radians(target_alt), math.radians(target_az)
            vector = (math.cos(ta) * math.cos(tz), math.cos(ta) * math.sin(tz), math.sin(ta))
            fiber = rng.randrange(16)
            evidence = _Evidence(command_alt, command_az, vector, fiber, True)
            predicted = calibrator._predicted_hits(evidence)
            indices = [rng.randrange(predicted.size) for _ in range(100)]
            for index in indices:
                actual_alt = command_alt + calibrator.delta_alt[index]
                actual_az = command_az + calibrator.delta_az[index]
                offsets = grid.tangent_offsets(target_alt, target_az, actual_alt, actual_az)
                found, region = grid.classify_offset(*offsets)
                self.assertEqual(bool(predicted[index]), found == fiber and region == "glass")

    def test_zero_scores_still_supply_hit_evidence(self):
        init, grid = payload(), FiberGrid(0.4, 0.0, 16)
        action, moment, hits, metadata = exposure(2, random.Random(923), grid, init, (0.08, -0.08))
        ordinary, zero = PointingCalibrator(init), PointingCalibrator(init)
        ordinary.update(action, moment, hits, metadata)
        zero.update(action, moment, [{**hit, "score": 0} for hit in hits], metadata)
        self.assertEqual(ordinary.estimate, zero.estimate)
        self.assertEqual(ordinary.diagnostics, zero.diagnostics)

    def test_below_altitude_misses_are_not_offset_evidence(self):
        init, grid = payload(), FiberGrid(0.4, 0.0, 16)
        action, moment, hits, metadata = exposure(0, random.Random(103), grid, init, (0.08, 0.08), altitude=25)
        calibrator = PointingCalibrator(init)
        self.assertEqual(hits, [])
        calibrator.update(action, moment, hits, metadata)
        self.assertEqual(calibrator.diagnostics["constraints"], 0)
        self.assertEqual(calibrator.diagnostics["skipped_altitude"], 16)
        self.assertEqual(calibrator.estimate[2], 0.0)

    def test_unknown_result_does_not_invent_misses(self):
        calibrator = PointingCalibrator(payload())
        self.assertEqual(calibrator.update({"action": "observe"}, "2026-11-15T00:00:00Z", None),
                         calibrator.estimate)
        self.assertEqual(calibrator.diagnostics["constraints"], 0)

    def test_uniform_reference_prior_converges(self):
        for seed, bias in enumerate([(0.0874, -0.0631), (0.0054, 0.1014),
                                     (-0.1027, -0.1111), (0.0, 0.0)], start=40):
            result = synthetic_fit(bias, seed)
            self.assertLess(result["maximum_error_deg"], 0.003, result)
            self.assertEqual(result["diagnostics"]["minimum_mismatches"], 0, result)

    def test_wider_actual_bias_expands_reference_prior(self):
        result = synthetic_fit((0.31, -0.22), 91, count=120)
        self.assertGreater(result["diagnostics"]["expansions"], 0, result)
        self.assertLess(result["maximum_error_deg"], 0.005, result)


if __name__ == "__main__":
    unittest.main()
