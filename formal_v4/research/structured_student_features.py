"""Public-only features for a small action-value student.

This module does not open score reports, terminal labels, or teacher truth.
Every ledger row is consumed before pooling. Factor estimates/bounds remain
learning features, not completion certificates. Target IDs are join keys only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Mapping

import numpy as np


FEATURE_SCHEMA = "structured-public-action-v1"
TARGET_SOURCE_NAMES = (
    "ra_fraction", "dec_fraction", "feature_flux", "science_weight", "required",
    "best_science_score", "max_factor_lower", "max_factor_estimate", "max_factor_upper_approx",
    "alt_fraction", "az_sin", "az_cos", "future_visible_days_approx", "future_visible_night_fraction_approx",
)
PROGRAMS = ("DARK", "BRIGHT", "BACKUP")
EVENTS = ("rain", "overcast", "haze", "cold_snap", "storm", "rocket_launch",
          "earthquake", "terrain_obstruction", "instrument_fault", "other")
DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW", "ALL")
COMPONENTS = ("sum_best_scores", "required_penalty", "uniformity_penalty",
              "report_settlement", "observation_request_reward")


class SchemaError(ValueError):
    pass


def utc(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise SchemaError("Public timestamps must have a timezone")
    return result.astimezone(timezone.utc)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_action(action):
    return hashlib.sha256(json.dumps(action, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _jain(ratios):
    squares = np.square(ratios).sum()
    return float(np.square(ratios.sum()) / (len(ratios) * squares)) if squares > 0 else 0.0


def _pool(rows):
    if not len(rows):
        return np.zeros(rows.shape[1] * 3, np.float32)
    return np.concatenate((rows.mean(0), rows.max(0), rows.sum(0) / np.sqrt(len(rows))))


@dataclass
class ActionFeatures:
    name: str
    target_index: np.ndarray
    edges: np.ndarray
    scalars: np.ndarray
    coarse_utility: float
    gain_per_second: float
    native_utility: float | None


@dataclass
class PublicFeatures:
    target_nodes: np.ndarray
    global_features: np.ndarray
    actions: list[ActionFeatures]
    target_names: tuple[str, ...]
    edge_names: tuple[str, ...]
    global_names: tuple[str, ...]
    scalar_names: tuple[str, ...]
    warnings: list[str]

    def flat(self):
        """Strong flat comparator uses the SAME public information as DeepSets."""
        target_pool = _pool(self.target_nodes)
        return np.stack([np.concatenate((self.global_features, target_pool, a.scalars,
                         _pool(np.column_stack((self.target_nodes[a.target_index], a.edges)))))
                         for a in self.actions]).astype(np.float32)


def load_public(initial_path, capture_path, features_path):
    initial = json.loads(Path(initial_path).read_text())
    initial = initial.get("payload", initial)
    capture = json.loads(Path(capture_path).read_text())
    if capture.get("feature_blob_sha256") != sha(features_path):
        raise SchemaError("Public feature blob hash differs from capture")
    with np.load(features_path, allow_pickle=False) as archive:
        arrays = {key: archive[key].copy() for key in archive.files}
    return initial, capture, arrays


def _validate(initial, capture, arrays, require_predictions):
    if capture.get("feature_schema") != "public-target-ledger-v1":
        raise SchemaError("Unsupported teacher public feature schema")
    for name in ("targets", "survey", "instrument", "scoring"):
        if name not in initial:
            raise SchemaError("Missing public initialization field: " + name)
    table = initial["targets"]
    cols, rows = table["columns"], table["rows"]
    ids = [str(row[cols.index("target_id")]) for row in rows]
    declared_ids = capture.get("target_ids")
    if declared_ids is None:
        raise SchemaError("Capture lacks target_ids in exact planner index order")
    if len(set(declared_ids)) != len(ids) or set(declared_ids) != set(ids):
        raise SchemaError("Planner target_ids do not match public catalog")
    if arrays["target_features"].shape != (len(ids), len(TARGET_SOURCE_NAMES)):
        raise SchemaError("Unexpected target source shape")
    if tuple(capture.get("target_feature_names", ())) != TARGET_SOURCE_NAMES:
        raise SchemaError("Target source column names/order mismatch")
    # Compare stable public attributes, not merely row count, to prevent silent joins.
    public = {str(row[cols.index("target_id")]): dict(zip(cols, row)) for row in rows}
    ordered = [public[str(t)] for t in declared_ids]
    expected = np.asarray([[float(t["ra_deg"]) / 360, float(t["dec_deg"]) / 90,
                            float(t["feature_flux"]), float(t["science_weight"]), float(t["required"])]
                           for t in ordered])
    if not np.allclose(arrays["target_features"][:, :5], expected, rtol=2e-6, atol=2e-7):
        raise SchemaError("Target public attribute/order mismatch")
    for key, value in arrays.items():
        if value.dtype.kind not in "biuf" or not np.isfinite(value).all():
            raise SchemaError("Non-numeric/non-finite public feature: " + key)
    ledger_keys = ("ledger_rank", "ledger_target", "ledger_score", "ledger_factor_estimate", "ledger_lower", "ledger_valid")
    lengths = {len(arrays[k]) for k in ledger_keys}
    if len(lengths) != 1:
        raise SchemaError("Ledger columns differ in length")
    rank = int(capture["rank"])
    if (np.any(arrays["ledger_rank"] < 0) or np.any(arrays["ledger_rank"] >= rank)
            or np.any(arrays["ledger_target"] < 0) or np.any(arrays["ledger_target"] >= len(ids))):
        raise SchemaError("Ledger contains a future/out-of-range target or action rank")
    if require_predictions and "candidate_predictions" not in capture:
        raise SchemaError("Capture lacks pre-feedback public candidate_predictions")
    if "control" not in capture["actions"]:
        raise SchemaError("A control action is required")
    return tuple(map(str, declared_ids)), ordered


def _exposure_times(capture):
    """Actual public exposure span: start action, next decision feedback time."""
    history = capture.get("public_history", [])
    times = {}
    for before, after in zip(history, history[1:]):
        action, result = before.get("action", {}), after.get("last_result") or {}
        if action.get("action") == "observe" and result.get("action") == "observe":
            rank = int(before["observe_action_index"])
            if int(result["observe_index"]) != rank:
                raise SchemaError("Public history observe feedback rank mismatch")
            start = utc(before["now_utc"])
            end = min(utc(after["now_utc"]), start + timedelta(seconds=int(action["duration_seconds"])))
            if end <= start:
                raise SchemaError("Invalid public exposure interval")
            times[rank] = (start, end)
    return times


def build_public_features(initial: Mapping, capture: Mapping, arrays: Mapping,
                          *, require_predictions=True) -> PublicFeatures:
    ids, catalog = _validate(initial, capture, arrays, require_predictions)
    index, n = {t: i for i, t in enumerate(ids)}, len(ids)
    source = np.asarray(arrays["target_features"], np.float64)
    scoring, instrument = initial["scoring"], initial["instrument"]
    rank = int(capture["rank"])
    snapshot = capture["snapshot"]
    if int(snapshot["observe_action_index"]) != rank or snapshot["now_utc"] != capture["now_utc"]:
        raise SchemaError("Capture and public snapshot cut disagree")
    now, start, end = map(utc, (snapshot["now_utc"], initial["survey"]["start_utc"], initial["survey"]["end_utc"]))
    score, lower, estimate = map(lambda k: np.asarray(arrays[k], np.float64), ("scores", "factor_lower", "factor_estimate"))
    weight = np.maximum(source[:, 3], 1e-12)
    m_min = min(list(scoring["program"]["multipliers"].values()) + [scoring["program"]["mismatch_multiplier"]])
    if m_min <= 0:
        raise SchemaError("Nonpositive public program multiplier")
    # Unlike the upstream proxy, include public score's 0.5e-6 rounding allowance.
    upper = np.minimum(1.0, np.maximum(lower, (score + 0.5e-6) / (weight * m_min)))
    req_t = float(scoring["required"]["observed_factor_threshold"])
    uni_t = float(scoring["uniformity"]["observed_factor_threshold"])
    bands = np.floor(source[:, 0] * 360 / scoring["uniformity"]["ra_band_width_deg"]).astype(int)
    occupied = np.unique(bands)
    band_counts = np.array([(bands == b).sum() for b in occupied], float)
    ratios = np.array([np.mean(estimate[bands == b] >= uni_t) for b in occupied])
    base_jain = _jain(ratios)
    warnings = ["Factor lower/estimate/upper are public-derived learning features; no completion certificate.",
                "Remaining geometry support is three samples per public night, not exact future visibility.",
                "Rank pooling compresses the full ledger; the representation is not a sufficient statistic for all future invalidations."]

    # Consume ALL ledger rows, retaining attachment to the target and action rank.
    li, lr = np.asarray(arrays["ledger_target"], int), np.asarray(arrays["ledger_rank"], int)
    ls = np.asarray(arrays["ledger_score"], float) / weight[li]
    lf, ll = arrays["ledger_factor_estimate"], arrays["ledger_lower"]
    lv = np.asarray(arrays["ledger_valid"], bool)
    valid_count, invalid_count = np.bincount(li[lv], minlength=n), np.bincount(li[~lv], minlength=n)
    bin_id = np.minimum(7, (lr * 8 // max(rank, 1)).astype(int))
    rank_max = np.zeros((n, 8))
    rank_count = np.zeros((n, 8))
    np.maximum.at(rank_max, (li[lv], bin_id[lv]), ls[lv])
    np.add.at(rank_count, (li[lv], bin_id[lv]), 1)
    second = np.zeros(n)
    latest = np.zeros(n)
    best_rank = np.zeros(n)
    if lv.any():
        order = np.flatnonzero(lv)
        order = order[np.lexsort((lr[order], ls[order], li[order]))]
        ends = np.r_[np.flatnonzero(li[order][1:] != li[order][:-1]), len(order)-1]
        starts = np.r_[0, ends[:-1]+1]
        winners = order[ends]
        has_second = ends > starts
        second[li[winners[has_second]]] = ls[order[ends[has_second]-1]]
        best_rank[li[winners]] = (lr[winners]+1)/max(rank,1)
        np.maximum.at(latest, li[lv], (lr[lv]+1)/max(rank,1))

    # Per-target request features use public progress plus exact reconstructed timing.
    exposure_times = _exposure_times(capture)
    if set(map(int, np.unique(lr))) - set(exposure_times):
        raise SchemaError("Public history cannot reconstruct every ledger exposure span")
    request_nodes = np.zeros((n, 6))
    requests = snapshot.get("active_requests", [])
    for request in requests:
        members = np.asarray([index[t] for t in request["target_ids"]], int)
        completed = set(map(str, request.get("completed_target_ids", [])))
        remaining = max(0, int(request["minimum_completed"]) - len(completed))
        deadline = utc(request["deadline_utc"])
        issued = utc(request["issued_at_utc"])
        eligible = np.array([issued <= exposure_times[int(r)][0] and exposure_times[int(r)][1] <= deadline for r in lr]) & lv
        max_factor = np.zeros(n)
        np.maximum.at(max_factor, li[eligible], np.asarray(lf)[eligible])
        request_nodes[members, 0] += 1
        request_nodes[members, 1] += float(request["completion_reward"]) / max(remaining, 1) / 100
        request_nodes[members, 2] += remaining / max(int(request["minimum_completed"]), 1)
        request_nodes[members, 3] = np.maximum(request_nodes[members, 3], 1 / (1 + max(0, (deadline-now).total_seconds()) / 3600))
        request_nodes[members, 4] = np.maximum(request_nodes[members, 4], max_factor[members])
        for t in completed:
            request_nodes[index[t], 5] = 1
    target_names = ("sin_ra", "cos_ra", "dec", "log_flux", "log_weight", "required", "best_score_per_weight",
                    "factor_lower", "factor_estimate", "factor_upper_proxy_rounding_adjusted", "factor_uncertainty",
                    "alt", "sin_az", "cos_az", "remaining_geometry_days", "visible_night_fraction",
                    "log_valid_hits", "log_invalid_hits", "second_score_per_weight", "best_second_gap",
                    "latest_valid_rank_fraction", "best_valid_rank_fraction")
    nodes = np.column_stack((np.sin(source[:, 0]*2*np.pi), np.cos(source[:, 0]*2*np.pi), source[:, 1],
            np.log1p(source[:, 2]), np.log1p(weight), source[:, 4], score/weight, lower, estimate, upper, upper-lower,
            source[:, 9:14], np.log1p(valid_count), np.log1p(invalid_count), second, score/weight-second, latest, best_rank))
    target_names += tuple(f"rank_bin_{b}_best_score_per_weight" for b in range(8))
    target_names += tuple(f"rank_bin_{b}_log_hits" for b in range(8))
    target_names += ("active_request_count", "request_reward_density", "request_remaining_fraction", "request_urgency",
                     "request_window_factor_estimate", "request_public_completed")
    nodes = np.column_stack((nodes, rank_max, np.log1p(rank_count), request_nodes)).astype(np.float32)

    gnames = ["season_fraction", "remaining_days", "log_observe_rank", "running_score_per_target", "C", "E",
              "false_reports_since_correct", "pointing_offset_alt", "pointing_offset_az", "required_missing_lower_fraction",
              "required_missing_estimate_fraction", "required_missing_upper_fraction", "jain_estimate", "band_ratio_mean",
              "band_ratio_min", "band_ratio_std", "log_ledger_rows", "invalid_ledger_fraction", "active_request_count",
              "active_request_reward", "future_public_nights_fraction"]
    required = source[:, 4] > 0
    missing = lambda factor: np.mean(factor[required] < req_t) if required.any() else 0
    calibration = capture.get("calibrator_estimate") or [0, 0]
    global_values = [(now-start).total_seconds()/max((end-start).total_seconds(),1), (end-now).total_seconds()/86400,
                     np.log1p(rank), float(snapshot["running_total"])/max(n,1), capture["C"], capture["E"],
                     capture.get("false_since_correct",0), *list(calibration[:2]), missing(lower), missing(estimate), missing(upper),
                     base_jain, ratios.mean(), ratios.min(), ratios.std(), np.log1p(len(li)), np.mean(~lv) if len(li) else 0,
                     len(requests), sum(r["completion_reward"] for r in requests)/100,
                     sum(utc(t["observing_end_utc"])>now for t in initial["survey"]["nights"])/max(len(initial["survey"]["nights"]),1)]
    for b in range(8):
        rows = bin_id == b
        metrics = (rows.sum()/max(len(li),1), ls[rows & lv].sum()/max(n,1), float((rows & ~lv).sum())/max(len(li),1),
                   float(np.mean(lf[rows & lv])) if np.any(rows & lv) else 0,
                   float(np.mean(ll[rows & lv])) if np.any(rows & lv) else 0)
        global_values.extend(metrics)
        gnames.extend(f"ledger_rank_{b}_{s}" for s in ("row_fraction", "valid_score_per_target", "invalid_fraction", "factor_estimate", "factor_lower"))
    for event in EVENTS:
        for direction in DIRECTIONS:
            count = sum((notice.get("event_kind") == event if event != "other" else notice.get("event_kind") not in EVENTS)
                        and notice.get("direction", "ALL") == direction for notice in capture.get("notices", []))
            global_values.append(count)
            gnames.append("notice_" + event + "_" + direction)
    # Forecasts are public night-grained facts, not quantitative weather truth.
    forecast = snapshot.get("latest_forecast") or {}
    future_dates = {str(night.get("night_date")) for night in initial["survey"]["nights"] if utc(night["observing_end_utc"])>now}
    for event in EVENTS:
        for direction in DIRECTIONS:
            count = sum(len(set(notice.get("nights",[])) & future_dates)
                        for notice in forecast.get("notices",[])
                        if (notice.get("event_kind")==event if event!="other" else notice.get("event_kind") not in EVENTS)
                        and notice.get("direction","ALL")==direction)
            global_values.append(count/max(len(future_dates),1))
            gnames.append("forecast_future_night_fraction_"+event+"_"+direction)
    global_values.extend((float(bool(forecast)),max(0,(utc(forecast["coverage_end_utc"])-now).total_seconds()/86400) if forecast else 0))
    gnames.extend(("public_forecast_present","public_forecast_coverage_remaining_days"))
    for direction in DIRECTIONS:
        global_values.append(float(direction in capture.get("terrain",[])))
        gnames.append("persistent_public_terrain_"+direction)
    global_features = np.asarray(global_values, np.float32)

    enames = ("fiber_row", "fiber_column", "fiber_north", "fiber_east", "offset_north", "offset_east",
              "predicted_factor", "predicted_public_quality", "predicted_quality", "directional_scale",
              "band_dark", "band_bright", "band_backup", "predicted_score_gain_per_weight", "predicted_required_crossing",
              "predicted_uniformity_crossing", "request_candidate_eligible")
    snames = ("duration_max_fraction", "log_duration", "assignment_fraction", "program_dark", "program_bright", "program_backup",
              "pointing_alt", "pointing_sin_az", "pointing_cos_az", "coarse_science_gain", "coarse_required_gain",
              "coarse_jain_gain", "coarse_request_gain", "coarse_utility", "coarse_gain_per_second", "native_utility_present", "native_utility")
    action_features = []
    predictions = capture.get("candidate_predictions", {})
    utilities = capture.get("candidate_utilities", {})
    tmax = int(instrument["exposure"]["max_duration_seconds"])
    grid, pitch = int(instrument["grid_side"]), float(instrument["pitch_deg"])
    for name, action in capture["actions"].items():
        if action.get("action") != "observe":
            raise SchemaError("This student currently ranks observe candidates only")
        assignment = arrays.get(name + "_assignment")
        expected = {(int(f), index[t]) for f, t in action["assignments"].items()}
        if assignment is None or set(map(tuple, assignment.tolist())) != expected:
            raise SchemaError("Assignment array/action mismatch: " + name)
        # Sorting by fiber makes floating sums reproducible without using target index order.
        assignment = np.asarray(sorted(expected), int)
        if not len(assignment) or len(set(assignment[:, 1])) != len(assignment):
            raise SchemaError("Empty or duplicate-target observe action")
        ap = predictions.get(name)
        if require_predictions and (ap is None or any(ids[i] not in ap for i in assignment[:,1])):
            raise SchemaError("Incomplete pre-feedback candidate predictions: " + name)
        if ap is None:
            warnings.append("Missing candidate prediction: " + name + "; cannot train/use approximate utility")
            ap = {}
        duration, program = int(action["duration_seconds"]), PROGRAMS.index(action["program"])
        center_alt, center_az = action["pointing"]["alt_deg"], action["pointing"]["az_deg"]
        edges, new_estimate, science_gain, required_gain = [], estimate.copy(), 0., 0.
        for fiber, i in assignment:
            prediction = ap.get(ids[i], {})
            if prediction and (int(prediction.get("index",i)) != i or int(prediction.get("fiber_id",fiber)) != fiber):
                raise SchemaError("Candidate prediction target/fiber index mismatch")
            f = float(prediction.get("factor", 0))
            band = prediction.get("predicted_band", "BACKUP")
            multiplier = scoring["program"]["multipliers"][band] if band == action["program"] else scoring["program"]["mismatch_multiplier"]
            gain = max(0, weight[i]*f*multiplier-score[i])
            crossing = float(source[i,4] > 0 and estimate[i] < req_t <= f)
            science_gain += gain
            required_gain += crossing * scoring["required"]["penalty_per_missing"]
            new_estimate[i] = max(new_estimate[i], f)
            row, col = divmod(int(fiber), grid)
            north, east = (row-(grid-1)/2)*pitch, (col-(grid-1)/2)*pitch
            target_alt = float(prediction.get("alt_deg", source[i,9]*90))
            target_az = float(prediction.get("az_deg", np.degrees(np.arctan2(source[i,10],source[i,11]))%360))
            offset_n = target_alt-center_alt
            offset_e = ((target_az-center_az+180)%360-180)*np.cos(np.radians(center_alt))
            eligible = any(ids[i] in r["target_ids"] and utc(r["issued_at_utc"]) <= now
                           and now + timedelta(seconds=duration) <= utc(r["deadline_utc"]) for r in requests)
            edges.append([row/max(grid-1,1), col/max(grid-1,1), north/pitch, east/pitch, offset_n/pitch, offset_e/pitch,
                          f, prediction.get("public_quality",0), prediction.get("quality",0), prediction.get("directional_scale",0),
                          *(float(band==p) for p in PROGRAMS), gain/weight[i], crossing, float(estimate[i]<uni_t<=f), float(eligible)])
        new_ratios = np.array([np.mean(new_estimate[bands==b] >= uni_t) for b in occupied])
        jain_gain = scoring["uniformity"]["weight"]*(_jain(new_ratios)-base_jain)
        request_gain = 0.
        for request in requests:
            if now + timedelta(seconds=duration) > utc(request["deadline_utc"]) or now < utc(request["issued_at_utc"]):
                continue
            completed = set(map(str, request.get("completed_target_ids", [])))
            need = int(request["minimum_completed"])-len(completed)
            crossings = sum(ids[i] in request["target_ids"] and ids[i] not in completed and float(ap.get(ids[i],{}).get("factor",0)) >= request["completion_factor_threshold"] for i in assignment[:,1])
            if 0 < need <= crossings:
                request_gain += request["completion_reward"]
        coarse = science_gain + required_gain + jain_gain + request_gain
        utility = utilities.get(name)
        if isinstance(utility, Mapping):
            # Optional provenance-bearing scalar; action hash must match exactly.
            if utility.get("action_sha256") != canonical_action(action):
                raise SchemaError("Native utility belongs to a different action")
            utility = utility.get("utility")
        utility = float(utility) if utility is not None else None
        utility_record = capture.get("evaluated_native_utility_by_action_hash",{}).get(canonical_action(action))
        if utility_record is not None:
            witnessed = utility_record.get("native_utility_rate")
            if witnessed != utility or bool(utility_record.get("evaluated")) != (utility is not None):
                raise SchemaError("Native utility metadata/action hash mismatch")
        scalars = np.asarray([duration/tmax, np.log1p(duration), len(assignment)/instrument["n_fibers"],
                 *(float(program==i) for i in range(3)), center_alt/90, np.sin(np.radians(center_az)), np.cos(np.radians(center_az)),
                 science_gain, required_gain, jain_gain, request_gain, coarse, coarse/duration, float(utility is not None), utility or 0], np.float32)
        action_features.append(ActionFeatures(name,assignment[:,1].astype(np.int64),np.asarray(edges,np.float32),scalars,
                                             coarse,coarse/duration,utility))
    result = PublicFeatures(nodes,global_features,action_features,target_names,enames,tuple(gnames),snames,list(dict.fromkeys(warnings)))
    for matrix,names in ((nodes,target_names),(global_features,gnames)):
        if matrix.shape[-1] != len(names) or not np.isfinite(matrix).all():
            raise SchemaError("Feature dimension/finite check failed")
    for action in result.actions:
        if action.edges.shape[1] != len(enames) or action.scalars.size != len(snames) or not np.isfinite(action.edges).all() or not np.isfinite(action.scalars).all():
            raise SchemaError("Action feature dimension/finite check failed")
    return result
