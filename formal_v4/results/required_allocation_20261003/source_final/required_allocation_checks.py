"""Independent finite-model assignment and official geometry/scoring checks."""
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import linear_sum_assignment

BASE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BASE / 'runs/cold_neural_value_20261003/production_frozen'), str(BASE / 'upstream/gosim-observer-examples')]
spec = importlib.util.spec_from_file_location('research.required_allocation_calendar', BASE / 'research/required_allocation_calendar.py')
allocation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(allocation)
from runner.challenge.v4_workflow import V4Workflow
from runner.challenge.v4_fiber_map import min_altitude_during
from runner.challenge.v4_scorer import SlotTruth, WeatherTruth, score_target_exposure
from datetime import datetime, timezone, timedelta


def main():
    random = np.random.default_rng(12251)
    assignment_checks = 0
    error = 0.
    for nr in (1, 2, 3, 10, 40):
        for _ in range(15):
            cost = random.integers(0, 100, size=(nr, nr + 17)).astype(float)
            chosen = allocation.rectangular_assignment(cost)
            rows, cols = linear_sum_assignment(cost)
            difference = abs(float(cost[np.arange(nr), chosen].sum() - cost[rows, cols].sum()))
            assert len(set(chosen.tolist())) == nr and difference < 1e-9
            error = max(error, difference)
            assignment_checks += 1
    initial = V4Workflow(BASE / 'upstream/gosim-observer-examples/local-cards/L1').initialize_payload(900)
    p = allocation.RequiredAllocationPlanner(initial)
    cal = p.calendar
    cal.match(p.nights[0][0].timestamp(), np.zeros(p.n), .95)
    quality_error = 0.
    for night in (0, 11, 25, 31):
        now = p.nights[night][0] + timedelta(seconds=1703)
        lst = allocation.local_sidereal(now, p.lon)
        alt = p._altaz(lst)[0]
        expected = p._public_quality(now, lst, alt)[cal.required]
        computed = cal._quality([now.timestamp()])[0]
        quality_error = max(quality_error, float(np.max(np.abs(expected - computed))))
    assert quality_error < 1e-10
    bins = set()
    lowest_factor = 1.
    for row in cal.plan:
        i, block = row['target'], row['block']
        assert block not in bins
        bins.add(block)
        night, left, right = cal.blocks[block]
        assert left <= row['start'] and row['end'] <= right
        start = datetime.fromtimestamp(row['start'], timezone.utc)
        end = datetime.fromtimestamp(row['end'], timezone.utc)
        fiber_config = dict(site=dict(latitude_deg=p.lat, longitude_deg=p.lon))
        assert min_altitude_during(p.ra[i], p.dec[i], start, end, fiber_config) >= p.min_alt
        # A conditional constant site weather gives the graph's .85 scalar.
        slot = SlotTruth('test', p.nights[int(night)][0], p.nights[int(night)][1], True, 1., 1., 1., .85)
        weather = WeatherTruth([slot], [])
        target = dict(target_id=p.ids[i], feature_flux=p.flux[i], science_weight=p.weight[i], ra_deg=p.ra[i], dec_deg=p.dec[i])
        def altaz(moment):
            a, z, _, _ = p._altaz(allocation.local_sidereal(moment, p.lon))
            return a[i], z[i]
        scored = score_target_exposure(target, list(weather.segments(start, end)), [], weather, row['duration'], 1.,
                                      initial['scoring'], start, altaz, initial['site'])
        lowest_factor = min(lowest_factor, scored.factor)
        assert scored.factor >= p.req_threshold
    result = dict(assignment_cases=assignment_checks, assignment_max_error=error, public_quality_max_error=quality_error,
                  official_threshold_checks=len(cal.plan), minimum_official_conditional_factor=lowest_factor,
                  matched_bins_unique=True, no_future_truth_inputs=True)
    out = BASE / 'results/required_allocation_20261003/checks.json'
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
