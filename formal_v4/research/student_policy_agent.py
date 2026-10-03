"""Research-only full-season NumPy student over the frozen native candidates.

Run from a NEW package overlay on the exact native READY release. No prefix,
future tape, terminal report, teacher label, Torch, network, or training is used.
Default/control mode returns the native action even when a model is instrumented.
The explicit L3 research override does not change export calibration metadata.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

NATIVE_MANIFEST_SHA256 = "88a307956ab7e6bcccab4fa59bad30c98f6d475855686ff40a3b0bc1cbaca5a2"
STUDENT_SOURCE_HASHES = {
    "research/structured_student_features.py": "ac5a6a09fc9cd559ad32559a0281ef71b2b25df13c91351c2d5efb6c918f0db0",
    "research/structured_student_runtime.py": "5b62f375e6746055814eaa81eee8f2ada596565a883ecf2f75ffc0e3450ffc35",
}
FAMILY = ("control", "field", "short", "long", "program")
RESEARCH_ACKNOWLEDGEMENT = "L3_FULL_SEASON_RESEARCH_ONLY"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_package():
    """Fail before importing a mutable/Numba workspace planner by accident."""
    root = Path(__file__).resolve().parents[1]
    manifest = root / "build_manifest.json"
    if not manifest.is_file() or sha(manifest) != NATIVE_MANIFEST_SHA256:
        raise RuntimeError("Student entry requires the frozen native READY package overlay")
    hashes = json.loads(manifest.read_text())
    if len(hashes) != 19:
        raise RuntimeError("Unexpected native READY inventory")
    for name, expected in {**hashes, **STUDENT_SOURCE_HASHES}.items():
        if sha(root / name) != expected:
            raise RuntimeError("Student package source-lock drift: " + name)
    if (root / "remote_runtime.json").exists():
        raise RuntimeError("Student research package cannot enable a remote planner")
    if os.environ.get("GEOMETRY_NATIVE_LIBRARY"):
        raise RuntimeError("Student research uses only the package's frozen native library")
    for name in os.environ:
        if name.startswith("POLICY_ITERATION_"):
            raise RuntimeError("Student research cannot consume teacher/prefix configuration")
    return root


PACKAGE_ROOT = verify_package()

import numpy as np
import policy
from research.candidate_geometry_sweep import CandidateGeometryPlanner, PROGRAMS, DEG
from research.geometry import parse_utc, local_sidereal_deg
from research.geometry_native import load_library
from research.spatial_candidates import SpatialPlanner
from research.structured_student_features import FEATURE_SCHEMA, TARGET_SOURCE_NAMES, SchemaError, build_public_features, canonical_action
from research.structured_student_runtime import NumpyValue

load_library()


class RecordingSpatialPlanner(SpatialPlanner):
    def _evaluate(self, center, pool, *frame):
        result = super()._evaluate(center, pool, *frame)
        if self.student_recording and result is not None:
            self.student_evaluations.append(result)
        return result


class StudentPlanner(CandidateGeometryPlanner, RecordingSpatialPlanner):
    """MRO records both CandidateGeometry's super calls and baseline calls."""
    def __init__(self, initial):
        super().__init__(initial)
        self.student_recording = False
        self.student_evaluations = []
        self.student_env = {}

    def choose(self, snapshot, scores, factors, env_estimate=None, active_requests=None):
        self.student_evaluations = []
        self.student_env = dict(env_estimate or {})
        self.student_recording = True
        try:
            return super().choose(snapshot, scores, factors, env_estimate, active_requests)
        finally:
            self.student_recording = False


# Same participant entry injection as agent_geometry_native; no file is changed.
policy.SpatialPlanner = StudentPlanner
BasePolicy = policy.Policy


def choose_research(features, advantages, threshold):
    """Strict threshold; argmax keeps native control first on exact ties."""
    values = np.asarray(advantages)[:, 0]
    if not np.isfinite(values).all() or not math.isfinite(threshold) or threshold < 0:
        raise SchemaError("Research selection requires finite predictions/nonnegative threshold")
    winner = int(np.argmax(values))
    return features.actions[winner].name if values[winner] > threshold else "control"


class NumpyPairRidge:
    """Exact saved flat_pair_ridge format; schema bound by locked builder SHA."""
    def __init__(self, path):
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != {"weight", "mean", "std"}:
                raise SchemaError("Ridge archive must contain only weight/mean/std")
            self.weight, self.mean, self.std = (archive[name].copy() for name in ("weight", "mean", "std"))
        if any(row.ndim != 1 or row.dtype.kind not in "fiu" or not np.isfinite(row).all()
               for row in (self.weight, self.mean, self.std)):
            raise SchemaError("Ridge arrays must be finite numeric vectors")
        if self.weight.shape != self.mean.shape or self.std.shape != self.mean.shape or np.any(self.std <= 0):
            raise SchemaError("Ridge weight/normalizer dimensions or standard deviations differ")

    def advantages(self, features):
        values = features.flat()
        if values.ndim != 2 or values.shape[1:] != self.weight.shape:
            raise SchemaError("Ridge input dimension differs from frozen public feature schema")
        prediction = np.clip((values-self.mean)/self.std, -10, 10) @ self.weight
        control = [action.name for action in features.actions].index("control")
        result = (prediction-prediction[control])[:, None]
        if not np.isfinite(result).all():
            raise SchemaError("Non-finite ridge inference result")
        return result


class StudentPolicy(BasePolicy):
    def __init__(self, initial):
        self.student_mode = os.environ.get("STUDENT_POLICY_MODE", "control")
        if self.student_mode not in ("control", "research_l3"):
            raise ValueError("STUDENT_POLICY_MODE must be control or research_l3")
        self.student_selector = os.environ.get("STUDENT_POLICY_SELECTOR", "native_control")
        selectors = ("native_control", "structured", "flat", "flat_pair_ridge", "public_gain_per_second", "public_terminal_components_one_step")
        if self.student_selector not in selectors:
            raise ValueError("Unknown research selector: " + self.student_selector)
        model = os.environ.get("STUDENT_POLICY_MODEL")
        expected = os.environ.get("STUDENT_POLICY_MODEL_SHA256")
        if bool(model) != bool(expected):
            raise ValueError("A student model requires its explicit SHA256")
        self.student_model_sha256 = sha(model) if model else None
        if model and self.student_model_sha256 != expected:
            raise ValueError("Student model SHA256 mismatch")
        learned = self.student_selector in ("structured", "flat", "flat_pair_ridge")
        if bool(model) != learned:
            raise ValueError("Learned selectors require a pinned model; public/native selectors take no model")
        self.student_value = (NumpyPairRidge(model) if self.student_selector == "flat_pair_ridge" else NumpyValue(model)) if model else None
        if self.student_selector in ("structured", "flat"):
            if self.student_value.config["model_kind"] != self.student_selector:
                raise SchemaError("Requested neural selector differs from NumPy export kind")
            if not self.student_value.config.get("metadata", {}).get("feature_names"):
                raise SchemaError("Neural policy integration requires frozen export feature names")
        self.student_units = ("public_utility_per_exposure_second" if self.student_selector == "public_gain_per_second"
                              else "public_coarse_one_step_utility" if self.student_selector == "public_terminal_components_one_step"
                              else "predicted_raw_terminal_return_difference" if learned else "native_control")
        self.student_threshold = None
        if self.student_mode == "research_l3":
            if initial.get("task_card", {}).get("card_id") != "L3":
                raise ValueError("Research intervention is restricted to public card L3")
            if os.environ.get("STUDENT_POLICY_RESEARCH_L3_OVERRIDE") != RESEARCH_ACKNOWLEDGEMENT:
                raise ValueError("Explicit L3 research acknowledgement is required")
            if self.student_selector == "native_control":
                raise ValueError("Research mode requires an explicit nonnative selector")
            if self.student_selector == "flat_pair_ridge" and os.environ.get("STUDENT_POLICY_RIDGE_SCHEMA") != FEATURE_SCHEMA:
                raise SchemaError("Research ridge requires explicit frozen feature schema acknowledgement")
            self.student_threshold = float(os.environ["STUDENT_POLICY_MINIMUM_ADVANTAGE"])
            if not math.isfinite(self.student_threshold) or self.student_threshold < 0:
                raise ValueError("Research threshold must be finite and nonnegative")
        self.student_limit = int(os.environ.get("STUDENT_POLICY_DIAGNOSTIC_LIMIT", "2048"))
        if not 0 <= self.student_limit <= 8192:
            raise ValueError("Diagnostic limit must lie in 0..8192")
        diagnostic_dir = os.environ.get("STUDENT_POLICY_DIAGNOSTIC_DIR")
        self.student_diagnostic_file = None
        if diagnostic_dir:
            directory = Path(diagnostic_dir)
            directory.mkdir(parents=True, exist_ok=True)
            # No overwrite/restart into a previous trial's choice record.
            self.student_diagnostic_file = (directory / "student_choices.jsonl").open("x")
        super().__init__(initial)
        if self.remote is not None:
            raise RuntimeError("Student policy requires offline frozen native feedback/planning")
        self.student_history = []
        self.student_counts = Counter()
        self.student_choices = Counter()
        self.student_candidate_counts = Counter()
        self.student_absent_counts = Counter()
        self.student_signs = {name: Counter() for name in FAMILY}
        self.student_errors = Counter()
        self.student_feature_seconds = 0.
        self.student_inference_seconds = 0.
        self.student_max_feature_seconds = 0.
        self.student_max_inference_seconds = 0.
        self.student_action_digest = hashlib.sha256()
        self.student_native_action_digest = hashlib.sha256()
        self.student_intervention_digest = hashlib.sha256()
        self._prepare_geometry_support()

    def _prepare_geometry_support(self):
        """Cache only known-night geometry, preserving teacher's three samples."""
        p = self.planner
        support = []
        for start, end in p.nights:
            row = np.zeros(p.n, bool)
            for moment in (start, start + (end - start) / 2, end):
                alt, _, _, _ = p._altaz(local_sidereal_deg(moment, p.lon))
                row |= alt >= p.min_alt
            support.append(row)
        support = np.asarray(support, bool)
        seconds = np.asarray([(end-start).total_seconds() for start, end in p.nights])
        self.student_support_count = np.vstack((np.cumsum(support[::-1], axis=0)[::-1], np.zeros((1, p.n))))
        self.student_support_seconds = np.vstack((np.cumsum((support*seconds[:, None])[::-1], axis=0)[::-1], np.zeros((1, p.n))))

    def _remaining_geometry(self, now):
        p = self.planner
        first = next((i for i, (_, end) in enumerate(p.nights) if end > now), len(p.nights))
        remaining = self.student_support_seconds[first].copy()
        visible = self.student_support_count[first].copy()
        if first < len(p.nights) and now > p.nights[first][0]:
            _, end = p.nights[first]
            support = np.zeros(p.n, bool)
            for moment in (now, now+(end-now)/2, end):
                alt, _, _, _ = p._altaz(local_sidereal_deg(moment, p.lon))
                support |= alt >= p.min_alt
            remaining = self.student_support_seconds[first+1] + support*(end-now).total_seconds()
            visible = self.student_support_count[first+1] + support
        return remaining, visible

    def _tuple_action(self, candidate):
        p = self.planner
        _, center, duration, program, chosen, fibers = candidate
        oa = float(p.student_env.get("pointing_offset_alt_deg", 0))
        oz = float(p.student_env.get("pointing_offset_az_deg", 0))
        return dict(action="observe", pointing=dict(alt_deg=round(center[0]-oa, 7), az_deg=round((center[1]-oz) % 360, 7)),
                    duration_seconds=int(duration), program=PROGRAMS[int(program)],
                    assignments={str(int(f)): p.ids[int(i)] for i, f in zip(chosen, fibers)})

    def _actions(self, base):
        """Revision 7 family, order, duration eligibility and duplicate handling."""
        p = self.planner
        actions = {"control": base}
        for candidate in sorted(p.student_evaluations, key=lambda x: -x[0]):
            action = self._tuple_action(candidate)
            if not 0 <= action["pointing"]["alt_deg"] <= 90 or not action["assignments"]:
                continue
            dz = abs((action["pointing"]["az_deg"]-base["pointing"]["az_deg"]+180) % 360-180)
            da = abs(action["pointing"]["alt_deg"]-base["pointing"]["alt_deg"])
            if da+dz*np.cos(base["pointing"]["alt_deg"]*DEG) >= .45*p.pitch:
                actions["field"] = action
                break
        for name, scale in (("short", .6), ("long", 1.5)):
            duration = max(p.tmin, min(int(p.frame[12]), int(round(base["duration_seconds"]*scale))))
            assignments = {f: t for f, t in base["assignments"].items() if p.frame[1][p.index[t]]+1e-9 >= duration}
            if assignments and duration != base["duration_seconds"]:
                actions[name] = {**base, "duration_seconds": duration, "assignments": assignments}
        actions["program"] = {**base, "program": PROGRAMS[(PROGRAMS.index(base["program"])+1) % len(PROGRAMS)]}
        seen, unique, rejected = set(), {}, []
        for name, action in actions.items():
            key = canonical_action(action)
            if key in seen:
                rejected.append(dict(case=name, reason="duplicate_exact_action", hash=key))
            else:
                unique[name] = action
                seen.add(key)
        return unique, rejected

    def _predictions(self, actions):
        p, env = self.planner, self.planner.student_env
        now = self.pending["start"]
        vectors, k = p.frame[0], p.frame[2]
        alt = np.arcsin(np.clip(vectors[:, 2], -1, 1))/DEG
        az = np.arctan2(vectors[:, 1], vectors[:, 0])/DEG % 360
        public = p._public_quality(now, local_sidereal_deg(now, p.lon), alt)
        qs = max(.005, float(env.get("quality_scale", .55)))
        bs = max(.005, float(env.get("program_band_quality_scale", qs/.95)))
        bands = np.where(public*bs >= p.dark_threshold, 0, np.where(public*bs >= p.bright_threshold, 1, 2))
        quality = k*p.f0t0/np.maximum(p.flux, 1e-12)
        tq = np.asarray(env.get("target_quality_scale", np.ones(p.n)))
        directional = quality/np.maximum(1e-12, public*qs*tq)
        return {name: {t: dict(index=p.index[t], fiber_id=int(f), factor=min(1., float(k[p.index[t]]*action["duration_seconds"])),
                              public_quality=float(public[p.index[t]]), quality=float(quality[p.index[t]]),
                              directional_scale=float(directional[p.index[t]]), predicted_band=PROGRAMS[int(bands[p.index[t]])],
                              alt_deg=float(alt[p.index[t]]), az_deg=float(az[p.index[t]]))
                       for f, t in action["assignments"].items()} for name, action in actions.items()}

    def _public_features(self, snapshot, actions, predictions):
        p = self.planner
        now = parse_utc(snapshot["now_utc"])
        alt, az, _, _ = p._altaz(local_sidereal_deg(now, p.lon))
        config = self.initial["scoring"]["program"]
        minimum = min(list(config["multipliers"].values())+[config["mismatch_multiplier"]])
        upper = np.minimum(1., np.maximum(self.factor_lower, self.scores/np.maximum(p.weight*minimum, 1e-12)))
        remaining, visible = self._remaining_geometry(now)
        target = np.column_stack((p.ra/360, p.dec/90, p.flux, p.weight, p.required.astype(float), self.scores,
                                  self.factor_lower, self.factors, upper, alt/90, np.sin(az*DEG), np.cos(az*DEG),
                                  remaining/86400, visible/len(p.nights))).astype(np.float32)
        ledger = self.ledger
        arrays = dict(target_features=target, scores=self.scores, factor_lower=self.factor_lower, factor_estimate=self.factors)
        for output, source in (("ledger_target", "idx"), ("ledger_score", "score"), ("ledger_factor_estimate", "factor"), ("ledger_lower", "lower")):
            arrays[output] = np.concatenate([row[source] for row in ledger]) if ledger else np.array([], int if source == "idx" else float)
        arrays["ledger_rank"] = np.concatenate([np.full(len(row["idx"]), row["observe_index"]) for row in ledger]) if ledger else np.array([], int)
        arrays["ledger_valid"] = np.concatenate([np.full(len(row["idx"]), row["valid"]) for row in ledger]) if ledger else np.array([], bool)
        for name, action in actions.items():
            arrays[name+"_assignment"] = np.asarray([[int(f), p.index[t]] for f, t in action["assignments"].items()], np.int32)
        evaluated = {canonical_action(self._tuple_action(candidate)): float(candidate[0]) for candidate in p.student_evaluations}
        utility = {name: evaluated.get(canonical_action(action)) for name, action in actions.items()}
        capture = dict(feature_schema="public-target-ledger-v1", rank=int(snapshot["observe_action_index"]), now_utc=snapshot["now_utc"],
                       snapshot=snapshot, target_ids=p.ids, target_feature_names=TARGET_SOURCE_NAMES, actions=actions,
                       candidate_predictions=predictions, candidate_utilities=utility, C=float(self.C), E=float(self.E),
                       false_since_correct=self.false_since_correct, calibrator_estimate=list(self.calibrator.estimate) if self.calibrator else None,
                       notices=self.notices, terrain=sorted(self.terrain), public_history=self.student_history)
        return build_public_features(self.initial, capture, arrays)

    def _replace_pending(self, action, prediction):
        """Native feedback, ledger, reports and calibrator now see sent action."""
        if not self.pending or self.pending["action"].get("action") != "observe":
            raise RuntimeError("Student intervention lacks the native pending observation")
        self.pending["action"] = action
        self.pending["prediction"] = prediction
        self.planner.last_prediction = prediction

    def _advantages(self, features):
        if self.student_value is not None:
            return self.student_value.advantages(features)
        if self.student_selector == "public_gain_per_second":
            values = np.asarray([action.gain_per_second for action in features.actions])
        elif self.student_selector == "public_terminal_components_one_step":
            values = np.asarray([action.coarse_utility for action in features.actions])
        else:
            raise SchemaError("Native control has no inferred selection deltas")
        control = [action.name for action in features.actions].index("control")
        return (values-values[control])[:, None]

    def _record(self, record):
        if self.student_diagnostic_file and self.student_counts["diagnostic_rows"] < self.student_limit:
            self.student_diagnostic_file.write(json.dumps(record, separators=(",", ":"), allow_nan=False)+"\n")
            self.student_counts["diagnostic_rows"] += 1
            if self.student_counts["diagnostic_rows"] % 32 == 0:
                self.student_diagnostic_file.flush()

    def decide(self, snapshot):
        # All previous actual feedback is ingested and replanned by native Policy.
        native = super().decide(snapshot)
        result = snapshot.get("last_result") or {}
        history_row = dict(now_utc=snapshot["now_utc"], observe_action_index=int(snapshot["observe_action_index"]),
                           action={k: v for k, v in native.items() if k in ("action", "duration_seconds")},
                           last_result={k: v for k, v in result.items() if k in ("action", "observe_index")})
        self.student_history.append(history_row)
        action = native
        self.student_counts["decisions"] += 1
        if native.get("action") == "observe":
            self.student_counts["observe_choices"] += 1
            actions, rejected = self._actions(native)
            for name in actions:
                self.student_candidate_counts[name] += 1
            for name in FAMILY:
                self.student_absent_counts[name] += int(name not in actions)
            selected, reason, advantages = "control", "no_model_native_control", None
            feature_seconds = inference_seconds = 0.
            predictions = None
            if self.student_selector != "native_control":
                if not self.ledger and snapshot.get("active_requests"):
                    # Locked builder's np.array([]) is float, then '& lv' fails.
                    # No fabricated ledger or altered feature code: this state abstains.
                    reason = "empty_ledger_active_request_native_fallback"
                    self.student_counts[reason] += 1
                else:
                    started = time.perf_counter()
                    stage = "features"
                    try:
                        predictions = self._predictions(actions)
                        features = self._public_features(snapshot, actions, predictions)
                        feature_seconds = time.perf_counter()-started
                        stage = "inference"
                        started = time.perf_counter()
                        advantages = self._advantages(features)
                        inference_seconds = time.perf_counter()-started
                        self.student_counts["inferences"] += 1
                        for candidate, value in zip(features.actions, advantages[:, 0]):
                            sign = "positive" if value > 1e-6 else "negative" if value < -1e-6 else "tie"
                            self.student_signs[candidate.name][sign] += 1
                        if self.student_mode == "research_l3":
                            selected = choose_research(features, advantages, self.student_threshold)
                            reason = "research_threshold_selected" if selected != "control" else "research_threshold_abstained"
                        else:
                            reason = "instrumented_native_control"
                    except (SchemaError, ValueError, KeyError, TypeError, FloatingPointError) as exc:
                        elapsed = time.perf_counter()-started
                        if stage == "features":
                            feature_seconds = elapsed
                        else:
                            inference_seconds = elapsed
                        reason = "student_error_native_fallback"
                        self.student_counts[reason] += 1
                        error = stage+":"+type(exc).__name__+":"+str(exc)[:160]
                        key = error if error in self.student_errors or len(self.student_errors) < 32 else "other_student_errors"
                        self.student_errors[key] += 1
                        if sum(self.student_errors.values()) <= 5:
                            print(json.dumps(dict(event=reason, rank=int(snapshot["observe_action_index"]), error=error)), file=sys.stderr, flush=True)
            self.student_choices[selected] += 1
            self.student_counts[reason] += int(reason not in ("empty_ledger_active_request_native_fallback", "student_error_native_fallback"))
            self.student_feature_seconds += feature_seconds
            self.student_inference_seconds += inference_seconds
            self.student_max_feature_seconds = max(self.student_max_feature_seconds, feature_seconds)
            self.student_max_inference_seconds = max(self.student_max_inference_seconds, inference_seconds)
            if selected != "control":
                action = actions[selected]
                self._replace_pending(action, predictions[selected])
                self.student_counts["interventions"] += 1
                self.student_intervention_digest.update((canonical_action(action)+"\n").encode())
            record = dict(event="student_policy_choice", step=self.count-1, rank=int(snapshot["observe_action_index"]),
                          now_utc=snapshot["now_utc"], mode=self.student_mode, selector=self.student_selector,
                          selection_units=self.student_units, selected=selected, reason=reason,
                          available=list(actions), absent=[name for name in FAMILY if name not in actions], rejected=rejected,
                          native_action_sha256=canonical_action(native), selected_action_sha256=canonical_action(action),
                          selection_deltas={name: float(value) for name, value in zip(actions, advantages[:, 0])} if advantages is not None else None,
                          feature_seconds=feature_seconds, inference_seconds=inference_seconds)
            self._record(record)
        history_row["action"] = {k: v for k, v in action.items() if k in ("action", "duration_seconds")}
        for digest, chosen in ((self.student_action_digest, action), (self.student_native_action_digest, native)):
            digest.update((json.dumps(chosen, sort_keys=True, separators=(",", ":"))+"\n").encode())
        return action

    def summary(self):
        if self.student_diagnostic_file:
            self.student_diagnostic_file.flush()
        return {**super().summary(), "student_policy": dict(schema="student-policy-research-summary-v1", mode=self.student_mode,
                    selector=self.student_selector, selection_units=self.student_units, feature_schema=FEATURE_SCHEMA,
                    deployment_calibrated=False, cloud_deployment_authorized=False, research_override=self.student_mode == "research_l3",
                    model_sha256=self.student_model_sha256, model_export_deployment_calibrated=bool(isinstance(self.student_value, NumpyValue) and self.student_value.config.get("metadata", {}).get("deployment_calibrated", False)),
                    minimum_advantage=self.student_threshold, native_manifest_sha256=NATIVE_MANIFEST_SHA256,
                    counts=dict(self.student_counts), choices=dict(self.student_choices), candidate_counts=dict(self.student_candidate_counts),
                    absent_counts=dict(self.student_absent_counts), candidate_predicted_signs={name: dict(counts) for name, counts in self.student_signs.items()},
                    errors=dict(self.student_errors), feature_seconds=self.student_feature_seconds, inference_seconds=self.student_inference_seconds,
                    max_feature_seconds=self.student_max_feature_seconds, max_inference_seconds=self.student_max_inference_seconds,
                    diagnostic_limit=self.student_limit, actions_sha256=self.student_action_digest.hexdigest(),
                    native_actions_on_reached_states_sha256=self.student_native_action_digest.hexdigest(),
                    interventions_sha256=self.student_intervention_digest.hexdigest(), suffix_mode="natural_native_replan_after_every_actual_feedback",
                    forced_prefix=False, forced_suffix=False, public_history_rows=len(self.student_history))}


policy.Policy = StudentPolicy
from agent import main

if __name__ == "__main__":
    main()
