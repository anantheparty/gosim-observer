"""Independent local contract audit. No fitting, network or sealed-world input."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent / "cold_target_score_distribution_20261004"
sys.path[:0] = [str(SOURCE), str(SOURCE / "official")]
from public_features import (clip_duration, geometry, query_features,
    history_target_features, notice_features, action_metadata, publication_state, utc)
from target_core import K, PROGRAMS, soft_label, moments, expected_gain, first_gain, PublicHistory
from challenge.v4_scorer import (SlotTruth, ScoreEvent, WeatherTruth, score_target_exposure,
    lunar_quality_factor, program_band, program_multiplier, _normalized_airmass)
from challenge.v4_runner import load_scenario
from challenge.v4_fiber_map import radec_to_altaz
from pilot import labels


def main():
    ini = json.loads((SOURCE / "worlds/940901/public_initialize.json").read_text())
    scenario = load_scenario(SOURCE / "worlds/940901/config/v4_scenario.json")
    target = next(t for t in scenario.targets if t["target_id"] == "V4T000919")
    weather = WeatherTruth(scenario.slots, [e for e in scenario.events if e.event_type == "instrument_fault"])
    first_night = ini["survey"]["nights"][0]
    start = utc(first_night["observing_end_utc"]) - timedelta(seconds=60)
    action = dict(action="observe", duration_seconds=900, program="DARK",
        pointing=dict(alt_deg=60., az_deg=100.), assignments={"0": target["target_id"]})
    clipped = dict(action, duration_seconds=60)
    assert clip_duration(ini, start, 900) == 60
    assert np.array_equal(query_features(ini, target, action, start), query_features(ini, target, clipped, start))
    token = dict(target_id=target["target_id"], actual_hit=True, score_six_decimal=.059523)
    now = start + timedelta(seconds=60)
    assert np.array_equal(history_target_features(ini, target, action, start, token, now, True),
                          history_target_features(ini, target, clipped, start, token, now, True))
    assert np.array_equal(action_metadata(ini, action, [token], start, now, [], first_night["night_date"]),
                          action_metadata(ini, clipped, [token], start, now, [], first_night["night_date"]))
    raw = labels(scenario, weather, action, start, ini)[0]
    canonical = labels(scenario, weather, clipped, start, ini)[0]
    assert raw["actual_duration_seconds"] == 60 and raw["b"] == 0
    assert raw["physical_factor"] == canonical["physical_factor"]
    final_start = utc(ini["survey"]["nights"][-1]["observing_end_utc"]) - timedelta(seconds=52)
    assert clip_duration(ini, final_start, 3600) == 52
    five_start = utc(first_night["observing_start_utc"]) + timedelta(seconds=1)
    pieces, _, _ = geometry(ini, target, five_start, 3600)
    assert len(pieces) == 5 and abs(sum(p[-1] for p in pieces) - 1) < 1e-12
    altered = dict(target, science_weight=0)
    altered_action = dict(action, program="BACKUP", best=1e9)
    assert np.array_equal(query_features(ini, target, action, start), query_features(ini, altered, altered_action, start))
    different_center = dict(action, pointing=dict(alt_deg=65., az_deg=110.))
    assert np.array_equal(query_features(ini, target, action, start), query_features(ini, target, different_center, start))
    assert not history_target_features(ini, altered, action, start, token, now, True).any()
    h = history_target_features(ini, target, action, start, token, now, True)
    assert abs(float(h[21]) * 1e-6 - .5e-6 / target["science_weight"]) < 1e-12

    at = utc(first_night["observing_start_utc"])
    initial_notice = dict(record_type="bulletin", issued_at_utc=at.isoformat(), initial=True,
        notices=[dict(event_kind="terrain_obstruction", direction="NE")])
    false_report = dict(record_type="report_result", issued_at_utc=at.isoformat(),
        correct=False, repaired=False, score_delta=0)
    forecast = dict(record_type="forecast", issued_at_utc=at.isoformat(),
        coverage_start_utc=at.isoformat(), coverage_end_utc=(at+timedelta(days=3)).isoformat(),
        notices=[dict(event_kind="rain", direction="N", nights=[first_night["night_date"]])])
    future = dict(record_type="bulletin", issued_at_utc=(at+timedelta(seconds=1)).isoformat(),
        initial=True, notices=[dict(event_kind="terrain_obstruction", direction="SW")])
    seen = [initial_notice, forecast, false_report]
    baseline = notice_features(ini, seen, at, first_night["night_date"])
    assert np.array_equal(baseline, notice_features(ini, seen+[future], at, first_night["night_date"]))
    assert baseline[-3] == 0 and baseline[-2] == 0 and baseline[-1] == 1
    assert publication_state(ini, seen, at, first_night["night_date"])["forecast_covers_query_night"]
    assert not publication_state(ini, seen, at, ini["survey"]["nights"][4]["night_date"])["forecast_covers_query_night"]
    terrain_codes = []
    for mask in range(256):
        bulletin = dict(initial_notice, notices=[dict(event_kind="terrain_obstruction", direction=d)
            for j,d in enumerate(("N", "NE", "E", "SE", "S", "SW", "W", "NW")) if mask & (1 << j)])
        terrain_codes.append(notice_features(ini, [bulletin], at, first_night["night_date"])[:8].tobytes())
    assert len(set(terrain_codes)) == 256
    history = PublicHistory()
    history.observe(0, action, [dict(target_id=target["target_id"], score=.6)])
    history.observe(1, action, [dict(target_id=target["target_id"], score=.4)])
    history.resync(dict(invalidated_window=dict(action_index_start=0, action_index_end_exclusive=1)))
    assert history.best() == {target["target_id"]: .4}
    assert history.observations[0]["tokens"][0]["score_six_decimal"] == .6
    miss_action = dict(action, assignments={"0": target["target_id"], "1": "miss"})
    tokens = history.observe(2, miss_action, [dict(target_id=target["target_id"], score=0)])
    assert tokens[0]["actual_hit"] and not tokens[1]["actual_hit"] and tokens[1]["score_six_decimal"] is None

    config = ini["scoring"]
    rng = np.random.default_rng(441019)
    f = rng.uniform(0, 1, 5000); band = rng.integers(0, 3, 5000)
    weight = rng.choice([.3, .45, 1., 1.7], 5000); best = rng.uniform(0, 1.2, 5000) * weight
    p = soft_label(f, band)
    assert p.shape == (5000, 3, 65) and np.max(abs(p.sum(axis=(1,2))-1)) < 1e-12
    mu, _ = moments(p)
    assert np.max(abs(mu-f)) < 1e-12
    coeff = np.array([[program_multiplier(a, PROGRAMS[b], config) for b in band] for a in PROGRAMS]).T * weight[:,None]
    exact = np.maximum(coeff*f[:,None]-best[:,None], 0)
    error = expected_gain(p, weight, best, config)-exact
    assert error.min() > -1e-12 and np.max(error-coeff/(4*K)) < 1e-12
    assert np.max(abs(first_gain(p, weight, config)-coeff*f[:,None])) < 1e-12
    threshold_example = soft_label([.5-1e-6], [0])
    projected_tail = float(threshold_example[...,32:].sum())
    assert abs(projected_tail-.999936) < 1e-12

    # Independent constant-position integral with a directional event boundary.
    no_moon = copy.deepcopy(config); no_moon.pop("lunar_model")
    slot = SlotTruth("audit-S0", at, at+timedelta(seconds=120), True, 1., 1., 1., 1.)
    synthetic_weather = WeatherTruth([slot], [])
    event = ScoreEvent("audit-rain", "rainy", at+timedelta(seconds=30), at+timedelta(seconds=60),
        "HORIZON_SECTOR", 350., 10., 0., 90., 2., .5, 1., 1.)
    synthetic_target = dict(target_id="audit", feature_flux=.5, science_weight=1.7, ra_deg=0., dec_deg=0.)
    scored = score_target_exposure(synthetic_target, [(120.,slot)], [event], synthetic_weather,
        120, 1.2, no_moon, at, lambda _: (60.,0.))
    integrated = (90+30*.25) / (_normalized_airmass(60.) ** config["airmass_exponent"] * config["q0"])
    expected_f = min(.5*integrated/(config["flux_zero_point"]*config["exposure_zero_point_seconds"]), 1.)
    assert abs(scored.factor-expected_f) < 1e-12
    assert abs(scored.score-1.7*1.2*expected_f) < 1e-12
    plain_band = synthetic_weather.band_quality(at,at+timedelta(seconds=120),no_moon,lambda _:60.)
    assert abs(plain_band-1/(_normalized_airmass(60.)**config["airmass_exponent"]*config["q0"])) < 1e-12

    paths = ["target_core.py", "public_features.py", "pilot.py", "math_contract.py", "input_probe.py",
        "official/challenge/v4_scorer.py", "official/challenge/v4_runner.py", "official/challenge/v4_weather_simulator.py",
        "official/challenge/v4_workflow.py", "official/challenge/v4_config_check.py", "v4_score_config.json"]
    result = dict(status="pass_limited_scope", checks=dict(actual_duration_clipping=True,
        query_history_metadata_clipping_parity=True, night_and_final_survey_boundaries=True,
        full_five_slot_geometry=True, query_excludes_weight_best_program=True,
        physical_query_pointing_invariant=True,
        zero_weight_history_safe=True, history_rounding_halfwidth_in_micro_units=True,
        issue_time_future_censor=True, forecast_coverage_distinguishable=True,
        all_256_terrain_sets=True, false_report_same_time_healthy_anchor=True,
        loss_retains_measurements_and_invalidates_best=True, assigned_miss_differs_zero_hit=True,
        joint_195_mean_and_hinge_bound=True, directional_boundary_integral=True,
        band_excludes_directional_and_efficiency=True),
        random_hinge_cases=15000, first_moment_error=float(np.max(abs(mu-f))),
        hinge_error_max=float(error.max()), directional_F_error=float(abs(scored.factor-expected_f)),
        hard_threshold_counterexample=dict(F=.5-1e-6, official_completed=False,
            projected_probability_ge_point5=projected_tail, hinge_bound_does_not_cover_indicator=True),
        source_sha256={p:hashlib.sha256((SOURCE/p).read_bytes()).hexdigest() for p in paths})
    (OUT/"PROBE_RESULT.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
