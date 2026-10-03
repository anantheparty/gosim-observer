"""Bounded synthetic integration checks: no season, labels, fit, or network."""
from __future__ import annotations

import argparse
import copy
from datetime import timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def child(package):
    sys.path.insert(0, str(package))
    os.environ["STUDENT_POLICY_MODE"] = "control"
    os.environ["STUDENT_POLICY_SELECTOR"] = "native_control"
    for key in ("STUDENT_POLICY_MODEL", "STUDENT_POLICY_MODEL_SHA256", "STUDENT_POLICY_RESEARCH_L3_OVERRIDE", "STUDENT_POLICY_MINIMUM_ADVANTAGE"):
        os.environ.pop(key, None)
    import numpy as np
    from research import student_policy_agent as module
    from research.geometry import altaz_to_radec, shift_altaz, parse_utc, local_sidereal_deg, format_utc
    from research.structured_student_features import FEATURE_SCHEMA

    def initial_payload():
        now = parse_utc("2026-11-02T00:00:00Z")
        rows = []
        for field, center in enumerate(((60., 80.), (55., 93.))):
            for fiber in range(4):
                row, col = divmod(fiber, 2)
                alt, az = shift_altaz(*center, (row-.5)*.5, (col-.5)*.5)
                ra, dec = altaz_to_radec(alt, az, local_sidereal_deg(now, 0), 30)
                rows.append([f"T{field}_{fiber}", ra, dec, .5+.02*fiber, 1.+.1*fiber, fiber % 2 == 0])
        return dict(task_card=dict(card_id="L3"), site=dict(latitude_deg=30, longitude_deg=0, minimum_altitude_deg=30),
                    targets=dict(columns=["target_id", "ra_deg", "dec_deg", "feature_flux", "science_weight", "required"], rows=rows),
                    survey=dict(start_utc=format_utc(now), end_utc=format_utc(now+timedelta(days=2)), slot_seconds=900,
                                nights=[dict(night_date="2026-11-02", observing_start_utc=format_utc(now), observing_end_utc=format_utc(now+timedelta(hours=4))),
                                        dict(night_date="2026-11-03", observing_start_utc=format_utc(now+timedelta(days=1)), observing_end_utc=format_utc(now+timedelta(days=1,hours=4)))]),
                    instrument=dict(n_fibers=4, grid_side=2, glass_side_deg=.4, gap_deg=.1, pitch_deg=.5, fov_side_deg=1.,
                                    exposure=dict(min_duration_seconds=60, max_duration_seconds=900)),
                    scoring=dict(q0=.68, flux_zero_point=.5, exposure_zero_point_seconds=900, airmass_exponent=.6,
                                 program=dict(multipliers=dict(DARK=1.2, BRIGHT=1.12, BACKUP=1.06), mismatch_multiplier=1.),
                                 required=dict(observed_factor_threshold=.5, penalty_per_missing=50),
                                 uniformity=dict(observed_factor_threshold=.5, weight=200, ra_band_width_deg=10), reporting=dict(false_report_free_allowance=1)))

    initial = initial_payload()
    snapshot = dict(now_utc=initial["survey"]["start_utc"], observe_action_index=0, running_total=0., last_result=None,
                    new_messages=[], active_requests=[], latest_bulletin=None, latest_forecast=None,
                    wallclock=dict(remaining_seconds=900))
    # Build the unchanged READY native object as well as the recorder subclass.
    module.policy.SpatialPlanner = module.CandidateGeometryPlanner
    native = module.BasePolicy(initial)
    module.policy.SpatialPlanner = module.StudentPlanner
    student = module.StudentPolicy(initial)
    checks = {}
    base = native.decide(copy.deepcopy(snapshot))
    action = student.decide(copy.deepcopy(snapshot))
    checks["native_first_action_identical"] = action == base and action["action"] == "observe"
    checks["native_pending_control_identical"] = student.pending["action"] == native.pending["action"] and student.pending["prediction"] == native.pending["prediction"]
    checks["recording_mro_captures_refinements"] = len(student.planner.student_evaluations) > len(student.planner.baseline_candidates) and student.planner.stats["geometry_exact"] > 0
    actions, rejected = student._actions(action)
    predictions = student._predictions(actions)
    features = student._public_features(snapshot, actions, predictions)
    checks["native_family_nonempty_distinct"] = list(actions)[0] == "control" and len(set(map(module.canonical_action, actions.values()))) == len(actions)
    checks["all_numpy_no_torch_numba_import"] = "torch" not in sys.modules and "numba" not in sys.modules

    # Exact cache equivalence to revision 7 known-night sample support.
    for now in (parse_utc(snapshot["now_utc"]), parse_utc(snapshot["now_utc"])+timedelta(hours=1), parse_utc(snapshot["now_utc"])+timedelta(hours=12)):
        remaining, visible = student._remaining_geometry(now)
        expected_remaining, expected_visible = np.zeros(student.planner.n), np.zeros(student.planner.n)
        for start, end in student.planner.nights:
            if end <= now:
                continue
            start = max(start, now)
            support = np.zeros(student.planner.n, bool)
            for moment in (start, start+(end-start)/2, end):
                alt, _, _, _ = student.planner._altaz(local_sidereal_deg(moment, student.planner.lon))
                support |= alt >= student.planner.min_alt
            expected_remaining += support*(end-start).total_seconds()
            expected_visible += support
        assert np.array_equal(remaining, expected_remaining) and np.array_equal(visible, expected_visible)
    checks["geometry_cache_matches_teacher_samples"] = True

    names = [row.name for row in features.actions]
    synthetic = np.zeros((len(names), 1), np.float32)
    synthetic[1:, 0] = -1
    checks["negative_predictions_retained_and_abstain"] = module.choose_research(features, synthetic, 0) == "control"
    synthetic[:] = 0
    checks["ties_retain_control"] = module.choose_research(features, synthetic, 0) == "control"
    synthetic[names.index("program"), 0] = 3
    checks["strict_threshold_and_positive_selection"] = module.choose_research(features, synthetic, 3) == "control" and module.choose_research(features, synthetic, 0) == "program"

    # Small random, UNTRAINED NumPy exports exercise both runtime routes.
    rng = np.random.default_rng(20261004)
    feature_names = dict(target=features.target_names, edge=features.edge_names, global_features=features.global_names, scalar=features.scalar_names)
    for kind in ("structured", "flat"):
        arrays = {}
        if kind == "structured":
            dimensions = dict(target=features.target_nodes.shape[1], edge=features.actions[0].edges.shape[1], global_features=features.global_features.size, scalar=features.actions[0].scalars.size)
            for name, size in (("target", dimensions["target"]), ("edge", dimensions["edge"]), ("global", dimensions["global_features"]), ("scalar", dimensions["scalar"])):
                arrays["normalizer."+name+"_mean"] = np.zeros(size, np.float32)
                arrays["normalizer."+name+"_std"] = np.ones(size, np.float32)
            layers = (("target.0", dimensions["target"], 16), ("target.2", 16, 8), ("edge.0", 8+dimensions["edge"], 16), ("edge.2", 16, 8),
                      ("head.0", 48+dimensions["global_features"]+dimensions["scalar"], 16), ("head.2", 16, 6))
        else:
            size = features.flat().shape[1]
            arrays["normalizer.flat_mean"], arrays["normalizer.flat_std"] = np.zeros(size, np.float32), np.ones(size, np.float32)
            layers = (("head.0", size, 11), ("head.2", 11, 6))
        for prefix, inputs, outputs in layers:
            arrays["weight."+prefix+".weight"] = rng.normal(0, .03, (outputs, inputs)).astype(np.float32)
            arrays["weight."+prefix+".bias"] = rng.normal(0, .01, outputs).astype(np.float32)
        arrays["config_json"] = np.asarray(json.dumps(dict(schema=FEATURE_SCHEMA, model_kind=kind, output_scale=1., metadata=dict(deployment_calibrated=False, feature_names=feature_names))))
        path = package / (kind+"_UNTRAINED_fixture.npz")
        np.savez(path, **arrays)
        runtime = module.NumpyValue(path)
        checks[kind+"_uncalibrated_runtime_returns_control"] = runtime.choose(features) == "control" and np.isfinite(runtime.advantages(features)).all()
        os.environ.update(STUDENT_POLICY_SELECTOR=kind, STUDENT_POLICY_MODEL=str(path), STUDENT_POLICY_MODEL_SHA256=module.sha(path))
        instrumented = module.StudentPolicy(initial)
        instrumented_action = instrumented.decide(copy.deepcopy(snapshot))
        checks[kind+"_instrumented_control_action_identical"] = instrumented_action == base and instrumented.student_counts["inferences"] == 1
        checks[kind+"_export_metadata_unmodified"] = instrumented.student_value.config["metadata"]["deployment_calibrated"] is False
    os.environ.pop("STUDENT_POLICY_MODEL"); os.environ.pop("STUDENT_POLICY_MODEL_SHA256")
    flat = features.flat()
    ridge_path = package / "ridge_UNTRAINED_fixture.npz"
    weight = rng.normal(0, .03, flat.shape[1]).astype(np.float32)
    np.savez(ridge_path, weight=weight, mean=np.zeros(len(weight), np.float32), std=np.ones(len(weight), np.float32))
    ridge = module.NumpyPairRidge(ridge_path)
    expected = np.clip(flat, -10, 10) @ weight
    checks["ridge_saved_format_exact_algebra"] = np.allclose(ridge.advantages(features)[:, 0], expected-expected[names.index("control")])
    os.environ.update(STUDENT_POLICY_SELECTOR="flat_pair_ridge", STUDENT_POLICY_MODEL=str(ridge_path), STUDENT_POLICY_MODEL_SHA256=module.sha(ridge_path))
    ridge_control = module.StudentPolicy(initial)
    checks["ridge_instrumented_native_control_action_identical"] = ridge_control.decide(copy.deepcopy(snapshot)) == base and ridge_control.student_counts["inferences"] == 1
    os.environ.pop("STUDENT_POLICY_MODEL"); os.environ.pop("STUDENT_POLICY_MODEL_SHA256")
    os.environ["STUDENT_POLICY_SELECTOR"] = "public_terminal_components_one_step"
    total_control = module.StudentPolicy(initial)
    checks["public_total_instrumented_native_control_action_identical"] = total_control.decide(copy.deepcopy(snapshot)) == base and total_control.student_counts["inferences"] == 1
    total_values = np.asarray([row.coarse_utility for row in features.actions])
    checks["public_total_deltas_preserve_own_units"] = np.array_equal(total_control._advantages(features)[:, 0], total_values-total_values[names.index("control")])
    invalid_path = package / "ridge_bad_dimension_fixture.npz"
    np.savez(invalid_path, weight=weight[:-1], mean=np.zeros(len(weight)-1), std=np.ones(len(weight)-1))
    try:
        module.NumpyPairRidge(invalid_path).advantages(features)
    except module.SchemaError:
        checks["ridge_dimension_guard"] = True
    else:
        checks["ridge_dimension_guard"] = False

    # Native control continues from synthetic actual feedback without intervention.
    next_snapshot = copy.deepcopy(snapshot)
    next_snapshot.update(now_utc=format_utc(parse_utc(snapshot["now_utc"])+timedelta(seconds=base["duration_seconds"])), observe_action_index=1,
                         last_result=dict(action="observe", observe_index=0, hits=[dict(target_id=t, score=.3, fiber_id=int(f)) for f, t in base["assignments"].items()]))
    a, b = native.decide(copy.deepcopy(next_snapshot)), student.decide(copy.deepcopy(next_snapshot))
    checks["native_after_actual_feedback_action_identical"] = a == b and np.array_equal(native.scores, student.scores) and np.array_equal(native.factors, student.factors)

    # Reproduce the known empty-ledger request exception, then verify safe fallback.
    os.environ["STUDENT_POLICY_SELECTOR"] = "public_gain_per_second"
    request = dict(request_id="SYNTHETIC", target_ids=[row[0] for row in initial["targets"]["rows"]], completed_target_ids=[], minimum_completed=2,
                   completion_factor_threshold=.5, completion_reward=100., issued_at_utc=snapshot["now_utc"], deadline_utc=initial["survey"]["nights"][0]["observing_end_utc"])
    request_snapshot = copy.deepcopy(snapshot); request_snapshot["active_requests"] = [request]
    request_control = module.StudentPolicy(initial)
    request_action = request_control.decide(request_snapshot)
    checks["empty_ledger_active_request_is_native_fallback"] = request_control.student_counts["empty_ledger_active_request_native_fallback"] == 1 and request_control.student_counts["inferences"] == 0 and request_control.ledger == []
    request_actions, _ = request_control._actions(request_action)
    try:
        request_control._public_features(request_snapshot, request_actions, request_control._predictions(request_actions))
    except TypeError:
        checks["locked_empty_ledger_dtype_error_reproduced"] = True
    else:
        checks["locked_empty_ledger_dtype_error_reproduced"] = False

    # Force a declared program choice on this fabricated state only to exercise
    # actual pending ingestion, calibrator action, and subsequent native planning.
    os.environ.update(STUDENT_POLICY_MODE="research_l3", STUDENT_POLICY_RESEARCH_L3_OVERRIDE=module.RESEARCH_ACKNOWLEDGEMENT, STUDENT_POLICY_MINIMUM_ADVANTAGE="0")
    branch = module.StudentPolicy(initial)
    branch._advantages = lambda f: np.asarray([[5.] if row.name == "program" else [-1.] if row.name != "control" else [0.] for row in f.actions])
    branch_action = branch.decide(copy.deepcopy(snapshot))
    checks["research_sent_action_and_pending_same"] = branch_action["program"] != base["program"] and branch.pending["action"] is branch_action and branch.pending["prediction"] == branch.planner.last_prediction
    pristine = module.StudentPolicy(initial)
    pristine.student_mode = "control"
    pristine.decide(copy.deepcopy(snapshot))
    checks["research_preserves_native_pending_start_priors_notices"] = all(branch.pending[key] == pristine.pending[key] for key in ("start", "prior_C", "prior_E", "notices"))
    observed = []
    original_update = branch.calibrator.update
    branch.calibrator.update = lambda actual, start, hits: (observed.append((actual, start)), original_update(actual, start, hits))[-1]
    feedback = copy.deepcopy(next_snapshot)
    feedback["now_utc"] = format_utc(parse_utc(snapshot["now_utc"])+timedelta(seconds=branch_action["duration_seconds"]))
    feedback["last_result"]["hits"] = [dict(target_id=t, score=.3, fiber_id=int(f)) for f, t in branch_action["assignments"].items()]
    branch._advantages = lambda f: np.zeros((len(f.actions), 1))
    branch.decide(feedback)
    checks["calibrator_receives_actual_branch_action_start"] = observed == [(branch_action, snapshot["now_utc"])]
    checks["branch_feedback_is_ledger_then_normal_replan"] = len(branch.ledger) == 1 and branch.ledger[0]["observe_index"] == 0 and branch.planner.geometry_summary["calls"] == 2 and branch.student_history[0]["action"]["duration_seconds"] == branch_action["duration_seconds"]
    checks["research_deployment_flags_stay_false"] = branch.summary()["student_policy"]["deployment_calibrated"] is False and branch.summary()["student_policy"]["cloud_deployment_authorized"] is False
    bad_card = copy.deepcopy(initial); bad_card["task_card"]["card_id"] = "L4"
    try:
        module.StudentPolicy(bad_card)
    except ValueError:
        checks["research_l4_refused"] = True
    else:
        checks["research_l4_refused"] = False
    os.environ.pop("STUDENT_POLICY_RESEARCH_L3_OVERRIDE")
    try:
        module.StudentPolicy(initial)
    except ValueError:
        checks["research_missing_override_refused"] = True
    else:
        checks["research_missing_override_refused"] = False

    # Bounded diagnostics retain the full signed candidate inventory, including
    # negative and tied candidates; cumulative counts continue after the cap.
    os.environ.update(STUDENT_POLICY_MODE="control", STUDENT_POLICY_SELECTOR="public_gain_per_second", STUDENT_POLICY_DIAGNOSTIC_LIMIT="1", STUDENT_POLICY_DIAGNOSTIC_DIR=str(package / "synthetic_diagnostics"))
    diagnostic = module.StudentPolicy(initial)
    diagnostic._advantages = lambda f: np.asarray([[0.] if row.name in ("control", "short") else [-2.] for row in f.actions])
    diagnostic.decide(copy.deepcopy(snapshot))
    diagnostic.decide(copy.deepcopy(snapshot))
    diagnostic.summary()
    diagnostic_rows = [json.loads(line) for line in (package / "synthetic_diagnostics/student_choices.jsonl").read_text().splitlines()]
    checks["diagnostic_cap_signed_candidates_and_full_counts"] = len(diagnostic_rows) == 1 and diagnostic.student_counts["inferences"] == 2 and min(diagnostic_rows[0]["selection_deltas"].values()) < 0 and diagnostic_rows[0]["selection_deltas"]["control"] == 0

    # Fabricated late-state footprint: 2,000 targets, 1,000 past actions and
    # 16,000 ledger rows. This is a feature CPU microcheck, not a valid season.
    saved_builder = module.build_public_features
    captured = []
    module.build_public_features = lambda init, cap, arr: (captured.append((copy.deepcopy(cap), {key: value.copy() for key, value in arr.items()})), saved_builder(init, cap, arr))[1]
    pristine._public_features(snapshot, *[actions, predictions])
    module.build_public_features = saved_builder
    late_capture, late_arrays = captured[0]
    late_initial = copy.deepcopy(initial)
    old_rows = late_initial["targets"]["rows"]
    late_initial["targets"]["rows"] = [copy.deepcopy(old_rows[i % len(old_rows)]) for i in range(2000)]
    for i, row in enumerate(late_initial["targets"]["rows"]):
        if i >= len(old_rows):
            row[0] = "FABRICATED_EXTRA_"+str(i)
    late_capture["target_ids"] = [row[0] for row in late_initial["targets"]["rows"]]
    late_arrays["target_features"] = np.tile(late_arrays["target_features"], (250, 1))
    for name in ("scores", "factor_lower", "factor_estimate"):
        late_arrays[name] = np.tile(late_arrays[name], 250)
    late_rank = np.repeat(np.arange(1000), 16)
    late_arrays.update(ledger_rank=late_rank, ledger_target=np.arange(len(late_rank)) % 2000,
                       ledger_score=np.full(len(late_rank), .1), ledger_factor_estimate=np.full(len(late_rank), .1),
                       ledger_lower=np.full(len(late_rank), .05), ledger_valid=np.ones(len(late_rank), bool))
    late_capture["rank"] = 1000
    late_now = parse_utc(snapshot["now_utc"])+timedelta(seconds=60000)
    late_capture["now_utc"] = format_utc(late_now)
    late_capture["snapshot"].update(now_utc=format_utc(late_now), observe_action_index=1000)
    late_capture["public_history"] = [dict(now_utc=format_utc(parse_utc(snapshot["now_utc"])+timedelta(seconds=60*i)), observe_action_index=i,
                                          action=dict(action="observe", duration_seconds=60), last_result=dict(action="observe", observe_index=i-1) if i else {}) for i in range(1001)]
    feature_times, inference_times = [], []
    late_runtime = module.NumpyValue(package / "structured_UNTRAINED_fixture.npz")
    for _ in range(3):
        started = time.perf_counter()
        late_features = saved_builder(late_initial, late_capture, late_arrays)
        feature_times.append(time.perf_counter()-started)
        started = time.perf_counter()
        late_runtime.advantages(late_features)
        inference_times.append(time.perf_counter()-started)
    checks["fabricated_late_state_features_and_numpy_finite"] = np.isfinite(late_features.target_nodes).all() and np.isfinite(late_runtime.advantages(late_features)).all()
    assert all(checks.values()), checks
    return dict(schema="student-policy-synthetic-integration-v1", passed=True, checks={key: bool(value) for key, value in checks.items()},
                actual_teacher_labels_read=0, seasons_launched=0, optimization_steps=0,
                synthetic_decision_calls=14, native_evaluations_recorded=len(student.planner.student_evaluations),
                fabricated_late_state=dict(targets=2000, past_observe_actions=1000, ledger_rows=16000,
                                           feature_seconds=feature_times, inference_seconds=inference_times,
                                           valid_season=False, full_900s_budget_verified=False),
                diagnostic_limit=branch.student_limit, deployment_calibrated=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--comparison-lock-sha256")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.package:
        print(json.dumps(child(args.package.resolve())))
        return
    spec = importlib.util.spec_from_file_location("prepare_student_package", Path(__file__).with_name("prepare_package.py"))
    preparation = importlib.util.module_from_spec(spec); spec.loader.exec_module(preparation)
    if not args.comparison_lock_sha256:
        parser.error("A reviewed --comparison-lock-sha256 is required")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="student-policy-synthetic-") as directory:
        package = Path(directory) / "package"
        preparation.prepare(args.root, package, args.comparison_lock_sha256)
        env = {key: value for key, value in os.environ.items() if not key.startswith(("STUDENT_POLICY_", "POLICY_ITERATION_"))}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("GEOMETRY_NATIVE_LIBRARY", None)
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--package", str(package)], env=env,
                                   cwd=package, capture_output=True, text=True, timeout=60)
        if completed.returncode:
            raise RuntimeError(completed.stderr+completed.stdout)
        result = json.loads(completed.stdout)
        result["seconds"] = time.perf_counter()-started
    if args.out:
        args.out.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
