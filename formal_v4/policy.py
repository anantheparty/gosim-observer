"""Belief state, exposure ledger, repair decisions and mathematical planner."""
from __future__ import annotations

import json
import math
import os
import sys
from collections import deque
from datetime import timedelta
from pathlib import Path

import numpy as np

from research.feedback_model import ar_prior, fit_feedback, seasonal_quality
from research.geometry import (Moon, format_utc, local_sidereal_deg, lunar_factor,
                               normalized_airmass, parse_utc, radec_to_altaz)
from research.spatial_candidates import SpatialPlanner, DIRECTION_AZ


class Policy:
    def __init__(self, initial):
        self.initial = initial
        self.planner = SpatialPlanner(initial)
        p = self.planner
        self.scores = np.zeros(p.n)
        self.factors = np.zeros(p.n)
        self.factor_lower = np.zeros(p.n)
        self.ledger = []
        self.pending = None
        self.seen_observe = set()
        self.survey_end = parse_utc(initial["survey"]["end_utc"])
        self.slot_seconds = int(initial["survey"].get("slot_seconds", 900))
        self.C, self.E = seasonal_quality(parse_utc(initial["survey"]["start_utc"]).timetuple().tm_yday, p.q0)
        self.last_feedback = None
        self.last_night = -1
        self.terrain = set()
        self.notices = []
        self.false_since_correct = 0
        self.correct_reports = 0
        self.report_count = 0
        self.last_report = None
        self.low_efficiency = deque(maxlen=12)
        self.blocked_spots = deque(maxlen=32)
        self.last_closed = False
        self.count = 0
        self.planning_seconds = 0.
        self.config = {"planning_budget_seconds": .22, "anchor_count": 24,
                       "duration_safety": 1.10, "repair_enabled": True}
        config_path = Path(__file__).with_name("policy_config.json")
        if config_path.exists():
            self.config.update(json.loads(config_path.read_text()))
        self.calibrator = None
        try:
            from research.pointing_calibration import PointingCalibrator
            self.calibrator = PointingCalibrator(initial)
        except ImportError:
            pass
        self.remote = None
        self.remote_check = None
        remote_path = Path(__file__).with_name("remote_runtime.json")
        if remote_path.exists():
            from remote_planner import RemotePlanner
            remote_config = json.loads(remote_path.read_text())
            candidate = RemotePlanner(initial, remote_config)
            self.remote_check = candidate.check()
            print(json.dumps(self.remote_check, separators=(",", ":")), file=sys.stderr, flush=True)
            if candidate.enabled and remote_config.get("enable_search", True):
                self.remote = candidate

    def _night(self, now):
        return next((k for k, (a, b) in enumerate(self.planner.nights) if a <= now < b), -1)

    def _geometric_H(self, start, duration, idx):
        """Integrate public sky geometry on the engine's <=120s mesh."""
        p = self.planner
        end = start + timedelta(seconds=duration)
        night = self._night(start)
        anchor = p.nights[night][0] if night >= 0 else start
        cursor = start
        total = np.zeros(len(idx))
        while cursor < end:
            slot_number = math.floor((cursor - anchor).total_seconds() / self.slot_seconds)
            segment_end = min(end, anchor + timedelta(seconds=(slot_number + 1) * self.slot_seconds))
            if segment_end <= cursor:
                segment_end = min(end, cursor + timedelta(seconds=self.slot_seconds))
            while cursor < segment_end:
                piece_end = min(segment_end, cursor + timedelta(seconds=120))
                moment = cursor + (piece_end - cursor) / 2
                lst = local_sidereal_deg(moment, p.lon)
                alt, _, _, _ = p._altaz(lst)
                total += (piece_end - cursor).total_seconds() * p._public_quality(moment, lst, alt)[idx] * p.q0
                cursor = piece_end
        return np.maximum(1e-9, total / duration)

    def _ingest_result(self, snapshot):
        result = snapshot.get("last_result") or {}
        now = parse_utc(snapshot["now_utc"])
        if result.get("action") == "report" and self.pending and self.pending["action"]["action"] == "report":
            if result.get("correct", result.get("repaired", False)):
                self.correct_reports += 1
                self.false_since_correct = 0
                self.E = .95
            else:
                self.false_since_correct += 1
                # A false report rules out an active repairable fault now. The
                # preceding C/E decomposition must not become a persistent fault.
                self.E = .95
                self.C = seasonal_quality(now.timetuple().tm_yday, self.planner.q0)[0]
            self.low_efficiency.clear()
            self.pending = None
            return
        if result.get("action") != "observe" or not self.pending:
            self.pending = None
            return
        observe_index = int(result.get("observe_index", len(self.ledger)))
        if observe_index in self.seen_observe:
            self.pending = None
            return
        self.seen_observe.add(observe_index)
        action = self.pending["action"]
        start = self.pending["start"]
        duration = min(action["duration_seconds"], (now - start).total_seconds())
        hits = [h for h in result.get("hits", []) if str(h.get("target_id")) in self.planner.index]
        if self.calibrator and action["action"] == "observe":
            self.calibrator.update(action, format_utc(start), hits)
        if not hits or duration <= 0:
            self.pending = None
            return
        p = self.planner
        idx = np.asarray([p.index[str(h["target_id"])] for h in hits], dtype=int)
        h_model = self._geometric_H(start, duration, idx)
        fit = fit_feedback(hits, p.weight[idx], p.flux[idx], duration, h_model,
                           action["program"], self.initial.get("scoring", {}), self.C, self.E)
        scores = np.asarray([float(h["score"]) for h in hits])
        factors = np.asarray(fit["factor_estimates"])
        lower = np.asarray(fit["factor_lower"])
        # Low fit residual cannot resolve every program/C/E ambiguity. Keep the
        # unconditional raw-factor bound for threshold decisions.
        conservative = lower
        np.maximum.at(self.scores, idx, scores)
        np.maximum.at(self.factors, idx, factors)
        np.maximum.at(self.factor_lower, idx, conservative)
        self.ledger.append({"observe_index": observe_index, "valid": True,
                            "idx": idx, "score": scores, "factor": factors, "lower": conservative})
        self.last_closed = fit["closed_evidence"]
        if fit["informative"] and fit["loss"] < 2:
            self.C, self.E = fit["C"], fit["E"]
            self.last_feedback = now
            clean = not any(n.get("event_kind") in ("earthquake", "rain", "storm") and n.get("direction") == "ALL"
                            for n in self.pending["notices"])
            if clean and len(hits) >= 3:
                self.low_efficiency.append((now, self.E, self.C, action["program"],
                                            sum(fit["program_matches"]), fit["loss"]))
        if np.any(scores > 0) and np.any(scores <= 0):
            for i in idx[scores <= 0]:
                prediction = self.pending["prediction"].get(p.ids[i])
                if prediction:
                    self.blocked_spots.append((now, prediction["alt_deg"], prediction["az_deg"]))
        self.pending = None

    def _resync(self, message):
        window = message.get("invalidated_window", {})
        first = int(window.get("action_index_start", 0))
        last = int(window.get("action_index_end_exclusive", 0))
        for entry in self.ledger:
            if first <= entry["observe_index"] < last:
                entry["valid"] = False
        self.scores.fill(0)
        self.factors.fill(0)
        self.factor_lower.fill(0)
        for entry in self.ledger:
            if entry["valid"]:
                np.maximum.at(self.scores, entry["idx"], entry["score"])
                np.maximum.at(self.factors, entry["idx"], entry["factor"])
                np.maximum.at(self.factor_lower, entry["idx"], entry["lower"])
        best = message.get("best_scores", [])
        canonical = np.zeros(self.planner.n)
        if best and isinstance(best[0], dict):
            items = ((x["target_id"], x["best_score"]) for x in best)
        else:
            items = zip(message.get("observed_target_ids", []), best)
        for target, score in items:
            if target in self.planner.index:
                canonical[self.planner.index[target]] = float(score)
        self.scores[:] = canonical

    def _messages(self, snapshot):
        for message in snapshot.get("new_messages", []):
            if message.get("record_type") == "state_resync":
                self._resync(message)
            if message.get("record_type") == "bulletin" and message.get("initial"):
                self.terrain.update(n.get("direction") for n in message.get("notices", [])
                                    if n.get("event_kind") == "terrain_obstruction")
        self.notices = (snapshot.get("latest_bulletin") or {}).get("notices", [])
        self.terrain.update(n.get("direction") for n in self.notices if n.get("event_kind") == "terrain_obstruction")
        for req in snapshot.get("active_requests", []):
            threshold = float(req.get("completion_factor_threshold", .5))
            for target in req.get("completed_target_ids", []):
                if target in self.planner.index:
                    i = self.planner.index[target]
                    self.factors[i] = max(self.factors[i], threshold)
                    self.factor_lower[i] = max(self.factor_lower[i], threshold)

    def _repair(self, now):
        if not self.config.get("repair_enabled", True):
            return False
        if any(n.get("event_kind") == "earthquake" for n in self.notices):
            return False
        if self.last_report and (now - self.last_report).total_seconds() < 86400:
            return False
        evidence = [x for x in self.low_efficiency if (now - x[0]).total_seconds() <= 7200 and x[5] < .5]
        if len(evidence) < 3:
            return False
        low = float(np.median([x[1] for x in evidence[-4:]]))
        free = int(self.initial.get("scoring", {}).get("reporting", {}).get("false_report_free_allowance", 0))
        allowed = self.false_since_correct < free
        if allowed and low < .68:
            self.report_count += 1
            self.last_report = now
            self.pending = {"action": {"action": "report"}}
            self.low_efficiency.clear()
            return True
        return False

    def _target_scale(self, now):
        p = self.planner
        _, az, _, _ = p._altaz(local_sidereal_deg(now, p.lon))
        scale = np.ones(p.n)
        for notice in self.notices:
            kind, direction = notice.get("event_kind"), notice.get("direction")
            if direction not in DIRECTION_AZ:
                continue
            delta = np.abs((az - DIRECTION_AZ[direction] + 180) % 360 - 180)
            # Direction hints conceal angular width and exact timing. Conservative
            # local expectations, rather than assuming the whole sector is shut.
            if kind in ("overcast", "haze", "cloud", "cloud_cover", "dust", "rocket", "rocket_launch", "terrain_obstruction"):
                scale *= np.where(delta < 30, .28 if kind == "terrain_obstruction" else .55, 1.)
        for direction in self.terrain:
            if direction in DIRECTION_AZ:
                delta = np.abs((az - DIRECTION_AZ[direction] + 180) % 360 - 180)
                scale *= np.where(delta < 25, .05, 1.)
        # A short-lived empirical blackout is specific to sky direction.
        for moment, alt, z in self.blocked_spots:
            if (now - moment).total_seconds() < 1200:
                delta = np.abs((az - z + 180) % 360 - 180)
                scale *= np.where(delta < 10, .5, 1.)
        return scale

    def decide(self, snapshot):
        self.count += 1
        now = parse_utc(snapshot["now_utc"])
        self._ingest_result(snapshot)
        self._messages(snapshot)
        if now >= self.survey_end:
            return {"action": "finish"}
        night = self._night(now)
        if night < 0:
            future = [a for a, b in self.planner.nights if a > now]
            if not future:
                return {"action": "finish"}
            self.pending = None
            return {"action": "wait", "until_utc": format_utc(min(future))}
        p = self.planner
        remaining = (p.nights[night][1] - now).total_seconds()
        if remaining < p.tmin:
            return {"action": "wait", "until_utc": format_utc(p.nights[night][1])}
        seasonal_C, _ = seasonal_quality(now.timetuple().tm_yday, p.q0)
        elapsed_slots = ((now - self.last_feedback).total_seconds() / self.slot_seconds) if self.last_feedback else 0
        C, E = ar_prior(self.C, self.E, elapsed_slots, seasonal_C, new_night=night != self.last_night)
        self.last_night = night
        closed = any(n.get("event_kind") in ("rain", "storm") and n.get("direction") == "ALL" for n in self.notices)
        if closed or self.last_closed:
            self.last_closed = False
            self.pending = None
            slot_elapsed = (now - p.nights[night][0]).total_seconds() % self.slot_seconds
            delay = min(max(60, int(math.ceil(self.slot_seconds - slot_elapsed))), int(math.ceil(remaining)))
            return {"action": "wait", "until_utc": format_utc(now + timedelta(seconds=delay))}
        if self._repair(now):
            return {"action": "report"}
        env = dict(self.config)
        env.update(quality_scale=C * E * p.q0, program_band_quality_scale=C * p.q0,
                   target_quality_scale=self._target_scale(now), use_bulletin_directional_prior=False)
        if self.calibrator:
            estimate = self.calibrator.estimate
            env["pointing_offset_alt_deg"], env["pointing_offset_az_deg"] = estimate[:2]
        wallclock = snapshot.get("wallclock", {})
        time_remaining = float(wallclock.get("remaining_seconds", 900))
        fraction_remaining = max(.01, (len(p.nights) - night - 1 + remaining / 28800) / len(p.nights))
        estimated_decisions = max(30, 2200 * fraction_remaining)
        env["planning_budget_seconds"] = min(float(env["planning_budget_seconds"]), max(.012, .5 * time_remaining / estimated_decisions))
        action = None
        remote_success = False
        if self.remote and self.remote.enabled and time_remaining > 10:
            try:
                remote_result = self.remote.choose(snapshot, self.scores, self.factor_lower, env,
                                                   snapshot.get("active_requests", []))
                action = remote_result["action"]
                p.last_prediction = remote_result.get("prediction", {})
                p.stats = remote_result.get("stats", {})
                remote_success = True
            except Exception as exc:
                print(json.dumps({"remote_failure": type(exc).__name__}, separators=(",", ":")), file=sys.stderr, flush=True)
        if not remote_success:
            action = p.choose(snapshot, self.scores, self.factor_lower, env, snapshot.get("active_requests", []))
        self.planning_seconds += p.stats.get("planning_seconds", 0)
        if action is None:
            self.pending = None
            return {"action": "wait", "until_utc": format_utc(now + timedelta(seconds=min(900, remaining)))}
        self.pending = {"action": action, "start": now, "prediction": dict(p.last_prediction), "notices": list(self.notices)}
        return action

    def summary(self):
        return {"decisions": self.count, "exposures": len(self.ledger), "reports": self.report_count,
                "correct_reports": self.correct_reports, "best_science_sum": float(self.scores.sum()),
                "required_missing_bound": int(np.count_nonzero(self.planner.required & (self.factor_lower < self.planner.req_threshold))),
                "planning_seconds": round(self.planning_seconds, 3), "C": round(self.C, 4), "E": round(self.E, 4),
                "remote_check": self.remote_check,
                "remote_calls": self.remote.calls if self.remote else 0,
                "remote_seconds": round(self.remote.seconds, 3) if self.remote else 0}
