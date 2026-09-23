#!/usr/bin/env python3
"""Published-information receding-horizon observer policy.

At each decision this agent solves a short time-expanded beam DP.  A state
contains the exact cursor, first visits to tiles considered in the horizon,
and capped visit counts for *issued* requests.  A request obtains its value
only on the transition that completes its whole bundle.  A fractional
knapsack price for later published nights supplies a continuation value for
unfinished tiles; a small Bernoulli DP supplies the analogous request value.
The beam, the published-window sampling and the future-weather model make
this a policy heuristic, not an optimality certificate.

The process reads only initialize and decision_request envelopes.  It never
loads a scenario directory or uses a scenario seed or unpublished requests.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from anomaly_detection import AnomalyDetector
from decision_graph import MinimalDecisionAgent
from protocol import decision_response, parse_platform_message


UNIT = 150
SLOT = 900
HORIZON_SLOTS = 12
BEAM_WIDTH = 36
MAX_TILES = 80
MAX_ACTIONS = 24
PROGRAMS = ("DARK", "BRIGHT", "BACKUP")


def _sec(value: object) -> int:
    return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _number(value: object, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _evenness(counts: tuple[int, ...]) -> float:
    total = sum(counts)
    square = sum(item * item for item in counts)
    return total * total / (len(counts) * square) if square else 0.0


@dataclass(frozen=True)
class Option:
    tile_id: str
    end: int
    program: str
    science: float
    base: float
    success: float


class RequestState:
    """Mixed-radix capped visit counters for currently issued requests."""

    def __init__(self, rows: list[dict], now: int) -> None:
        self.requests = []
        self.pairs: dict[tuple[str, str], tuple[int, int, int]] = {}
        radix = 1
        for row in rows:
            if row.get("is_complete") or _sec(row["deadline_utc"]) <= now:
                continue
            req_id = str(row["request_id"])
            parts = []
            baseline = 0
            for part in row.get("tile_requirements", ()):
                tile_id = str(part["tile_id"])
                needed = max(0, int(part.get("remaining_visits", part["required_visits"])))
                if needed == 0:
                    baseline += 1
                else:
                    # Published challenges have a small active request frontier.
                    # If a later format grows it, this cap drops the least urgent
                    # request from the modeled state, while the action stays legal.
                    if radix * (needed + 1) > 512:
                        continue
                    self.pairs[req_id, tile_id] = (radix, needed + 1, needed)
                    parts.append((tile_id, radix, needed + 1, needed))
                    radix *= needed + 1
            self.requests.append({
                "id": req_id,
                "parts": parts,
                "baseline": baseline,
                "required": int(row["required_tile_count"]),
                "delta": float(row["completion_reward"]) + float(row["miss_penalty"]),
                "available": _sec(row["available_from_utc"]),
                "deadline": _sec(row["deadline_utc"]),
            })
        self.size = radix
        self.by_id = {row["id"]: row for row in self.requests}

    def completed(self, row: dict, state: int) -> bool:
        count = row["baseline"]
        for _, mul, base, need in row["parts"]:
            count += (state // mul) % base >= need
        return count >= row["required"]

    def transition(self, state: int, req_id: str, tile_id: str) -> tuple[int, float]:
        pair = self.pairs.get((req_id, tile_id))
        if pair is None:
            return state, 0.0
        mul, base, need = pair
        old = (state // mul) % base
        if old >= need:
            return state, 0.0
        row = self.by_id[req_id]
        before = self.completed(row, state)
        after = state + mul
        reward = row["delta"] if not before and self.completed(row, after) else 0.0
        return after, reward

    def tags(self, tile_id: str, moment: int) -> tuple[str, ...]:
        return tuple(
            row["id"] for row in self.requests
            if row["available"] <= moment < row["deadline"]
            and (row["id"], tile_id) in self.pairs
        )


class ModelPolicy:
    def __init__(self, initial: dict) -> None:
        self.tiles = {str(row["tile_id"]): row for row in initial["tile_catalog"]["tiles"]}
        self.regions = sorted(initial["tile_catalog"]["region_ids"])
        self.region_index = {name: index for index, name in enumerate(self.regions)}
        self.config = initial["scoring_contract"]["score_config"]
        self.interface = initial["scoring_contract"]["weather_score_interface"]
        self.mechanics = float(self.config.get("coverage_bonus_weight", 0)) > 0
        self.detector = AnomalyDetector(initial)
        self.formal_policy = MinimalDecisionAgent(initial, model=None, top_k=12)
        self.windows: dict[str, list[dict]] = {}
        self.forecasts: dict[str, dict] = {}
        self.weather_total = 10
        self.weather_open = 8
        self.weather_numerator = 10.0
        self.seen_slots: set[str] = set()
        self.science_base_estimate = 0.0
        self.last_feedback: tuple[str, float] | None = None

    def _publication(self, snap: dict) -> None:
        weekly = snap.get("weekly")
        if weekly:
            for row in weekly.get("tile_windows", ()):
                self.windows.setdefault(str(row["night_id"]), []).append(row)
            for item in weekly.get("weather_forecast", ()):
                event_id = str(item.get("event_id", item.get("forecast_id", "")))
                old = self.forecasts.get(event_id)
                if old is None or int(item.get("revision", 0)) >= int(old.get("revision", 0)):
                    self.forecasts[event_id] = item
        night = snap.get("night_start")
        if night:
            self.windows[str(snap["cursor"]["night_id"])] = list(night.get("tile_windows", ()))
        current = str(snap["cursor"]["night_id"])
        self.windows = {key: rows for key, rows in self.windows.items() if key >= current}
        sid = str(snap["cursor"]["slot_id"])
        if sid not in self.seen_slots:
            self.seen_slots.add(sid)
            weather = snap.get("current_site_weather") or {}
            if weather:
                self.weather_total += 1
                self.weather_open += bool(weather.get("is_observable", False))
                seeing = max(0.1, _number(weather.get("seeing_arcsec"), 1.0))
                self.weather_numerator += _number(weather.get("transparency"), 1.0) * _number(weather.get("sky_quality"), 1.0) / seeing
        feedback = snap.get("tile_last_finished")
        if feedback and feedback.get("tile_id"):
            key = (str(feedback["tile_id"]), float(feedback.get("score", 0.0)))
            if key != self.last_feedback:
                self.last_feedback = key
                # This is only a public estimate of base; it never reconstructs
                # hidden segment conditions or anomaly tags.
                self.science_base_estimate += max(0.0, key[1]) / 1.15

    def _scope_applies(self, forecast: dict, tile_id: str) -> bool:
        scope = forecast.get("spatial_scope_type")
        payload = forecast.get("spatial_scope_payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {}
        tile = self.tiles[tile_id]
        if scope == "ALL":
            return True
        if scope == "REGION_SET":
            return tile["region_id"] in payload.get("region_ids", ())
        if scope == "TILE_SET":
            return tile_id in payload.get("tile_ids", ())
        if scope == "SKY_CAP_ICRS":
            ra1, dec1 = math.radians(float(tile["ra_deg"])), math.radians(float(tile["dec_deg"]))
            ra2, dec2 = math.radians(float(payload.get("ra_deg", 0))), math.radians(float(payload.get("dec_deg", 0)))
            cosine = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2)
            return math.degrees(math.acos(_clamp(cosine, -1, 1))) <= float(payload.get("radius_deg", 0))
        return True  # unknown directional scope: conservative forecast use

    def _forecast_factor(self, tile_id: str, start: int, end: int) -> float:
        risk = 0.0
        for row in self.forecasts.values():
            if _sec(row["predicted_start_utc"]) >= end or _sec(row["predicted_end_utc"]) <= start:
                continue
            if not self._scope_applies(row, tile_id):
                continue
            risk = max(risk, float(row.get("probability", 0)) * float(row.get("severity", 0)))
        return _clamp(1.0 - risk, 0.15, 1.0)

    def _band(self, quality: float) -> str:
        levels = self.config["quality_thresholds"]
        return "DARK" if quality >= float(levels["dark"]) else "BRIGHT" if quality >= float(levels["bright"]) else "BACKUP"

    def _future_option(self, tile_id: str, window: dict, start: int) -> Option:
        duration = int(self.tiles[tile_id]["nominal_exptime_seconds"])
        airmass = max(1.0, float(window.get("mean_airmass", 1.5)))
        lunar = float(window.get("mean_lunar_quality_factor", 1.0))
        atmosphere = min(float(self.interface["maximum_weather_quality"]),
                         (self.weather_numerator / self.weather_total) /
                         airmass ** float(self.interface["airmass_exponent"]))
        quality = atmosphere * lunar
        program = self._band(quality)
        base = float(self.tiles[tile_id]["tile_science_value"]) * quality
        open_prob = self.weather_open / self.weather_total
        success = open_prob ** math.ceil(duration / SLOT)
        success *= self._forecast_factor(tile_id, start, start + duration)
        return Option(tile_id, start + duration, program,
                      base * (1.0 + float(self.config["program_bonus"][program])) * success,
                      base * success, success)

    def _current_options(self, snap: dict, now: int) -> dict[str, Option]:
        result = {}
        offset = int(snap["cursor"]["slot_offset_seconds"])
        for row in snap.get("candidate_tiles", ()):
            tile_id = str(row["tile_id"])
            duration = int(row["nominal_exptime_seconds"])
            if not row["effective_weather"].get("is_observable"):
                continue
            # Published window ends are conservative.  Requiring completion
            # inside one avoids intentional geometry interruptions.
            if now + duration > _sec(row["window_end_utc"]):
                continue
            weather = row["effective_weather"]
            seeing = max(0.1, float(weather["seeing_arcsec"]))
            airmass = max(1.0, float(row["geometry"]["airmass"]))
            atmosphere = min(float(self.interface["maximum_weather_quality"]),
                             float(weather["transparency"]) * float(weather["sky_quality"]) /
                             (seeing * airmass ** float(self.interface["airmass_exponent"])))
            quality = atmosphere * float(row["geometry"]["lunar_quality_factor"])
            program = self._band(quality)
            base = float(row["tile_science_value"]) * quality
            segments = math.ceil((offset + duration) / SLOT)
            success = (self.weather_open / self.weather_total) ** max(0, segments - 1)
            result[tile_id] = Option(tile_id, now + duration, program,
                                     base * (1.0 + float(self.config["program_bonus"][program])) * success,
                                     base * success, success)
        return result

    def _night_windows(self, snap: dict, now: int) -> tuple[int, list[dict]]:
        night = snap.get("night_start")
        night_id = str(snap["cursor"]["night_id"])
        if night:
            end = _sec(night["night"]["observing_end_utc"])
        else:
            rows = self.windows.get(night_id, ())
            end = max((_sec(row["window_end_utc"]) for row in rows), default=now + SLOT)
        return end, self.windows.get(night_id, [])

    def _future_market(self, now: int, cutoff: int, completed: set[str],
                       flex_counts: dict[str, int]) -> tuple[dict[str, float], dict[str, list[tuple[str, int, float]]]]:
        quota = int(self.config["flexible_quota_per_region"])
        required_penalty = float(self.config["penalties"]["required_miss"])
        flex_penalty = float(self.config["penalties"]["flexible_shortfall_per_tile"])
        rows_by_night: dict[str, dict[str, tuple[float, int]]] = defaultdict(dict)
        availability_by_night: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
        for night_id, rows in self.windows.items():
            for row in rows:
                tile_id = str(row["tile_id"])
                start = max(cutoff, _sec(row["window_start_utc"]))
                end = _sec(row["window_end_utc"])
                duration = int(self.tiles[tile_id]["nominal_exptime_seconds"])
                if start + duration > end:
                    continue
                option = self._future_option(tile_id, row, start)
                opportunity_key = tile_id, night_id
                availability_by_night[opportunity_key].append((start, option.success))
                if tile_id in completed:
                    continue
                tile = self.tiles[tile_id]
                penalty = required_penalty if tile["scheduling_class"] == "REQUIRED" else (
                    flex_penalty if flex_counts.get(str(tile["region_id"]), 0) < quota else 0.0)
                value = option.science + option.success * penalty
                previous = rows_by_night[night_id].get(tile_id)
                if previous is None or value > previous[0]:
                    rows_by_night[night_id][tile_id] = (value, duration)
        reduced: dict[str, float] = defaultdict(float)
        for night_id, tile_rows in rows_by_night.items():
            window_rows = self.windows[night_id]
            start = min(_sec(row["window_start_utc"]) for row in window_rows)
            end = max(_sec(row["window_end_utc"]) for row in window_rows)
            capacity = max(0, end - max(start, cutoff))
            sorted_rows = sorted(tile_rows.values(), key=lambda pair: pair[0] / pair[1], reverse=True)
            used = 0
            price = 0.0
            for value, duration in sorted_rows:
                if used + duration > capacity:
                    price = value / duration
                    break
                used += duration
            for tile_id, (value, duration) in tile_rows.items():
                reduced[tile_id] = max(reduced[tile_id], value - price * duration)
        availability: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
        for (tile_id, night_id), opportunities in availability_by_night.items():
            availability[tile_id].extend((night_id, start, probability)
                                         for start, probability in opportunities)
        return reduced, availability

    def _request_terminal(self, request: dict, state: int, model: RequestState,
                          future_prob: Mapping[str, list[tuple[str, int, float]]], cutoff: int) -> float:
        if model.completed(request, state) or request["deadline"] <= cutoff:
            return 0.0
        probabilities = []
        for tile_id, mul, base, need in request["parts"]:
            remaining = need - (state // mul) % base
            if remaining <= 0:
                probabilities.append(1.0)
                continue
            by_night: dict[str, float] = {}
            for night_id, start, probability in future_prob.get(tile_id, ()):
                if start < request["deadline"]:
                    by_night[night_id] = max(by_night.get(night_id, 0.0), probability)
            trials = list(by_night.values())
            distribution = [1.0] + [0.0] * len(trials)
            for p in trials:
                for count in range(len(trials), 0, -1):
                    distribution[count] = distribution[count] * (1.0 - p) + distribution[count - 1] * p
                distribution[0] *= 1.0 - p
            probabilities.append(sum(distribution[remaining:]))
        needed = max(0, request["required"] - request["baseline"])
        distribution = [1.0] + [0.0] * len(probabilities)
        for p in probabilities:
            for count in range(len(probabilities), 0, -1):
                distribution[count] = distribution[count] * (1.0 - p) + distribution[count - 1] * p
            distribution[0] *= 1.0 - p
        return request["delta"] * sum(distribution[needed:])

    def decide(self, snap: dict) -> dict:
        if snap.get("schema_version") == "decision-snapshot-v3":
            # The official mechanics reward the best observation of a tile and
            # information gathered for later anomaly reports.  The short
            # horizon state below does not include either full history; use
            # the tested score-preview policy until those states are modeled.
            decision = self.formal_policy.decide(snap)
            decision["reason"] = ""
            return decision
        reports = self.detector.process_snapshot(snap) if self.mechanics else []
        if self.mechanics:
            snap = self.detector.filter_fault_scope(snap)
        self._publication(snap)
        now = _sec(snap["cursor"]["timestamp_utc"])
        actual = self._current_options(snap, now)
        if not actual:
            if self.mechanics:
                self.detector.note_observation(None, None)
            return {"action": "wait", "reason": "", "reports": reports}
        completed = set(snap.get("progress", {}).get("completed_tile_ids", ()))
        flex_counts = {str(k): int(v) for k, v in snap.get("progress", {}).get("flexible_completed_by_region", {}).items()}
        requests = RequestState(list(snap.get("active_requests", ())), now)
        night_end, night_rows = self._night_windows(snap, now)
        horizon = min(night_end, now + HORIZON_SLOTS * SLOT)
        horizon -= (horizon - now) % UNIT
        future_value, future_prob = self._future_market(now, horizon, completed, flex_counts)

        current_night = str(snap["cursor"]["night_id"])
        relevant = {}
        for row in night_rows:
            tile_id = str(row["tile_id"])
            if _sec(row["window_end_utc"]) <= now:
                continue
            tile = self.tiles[tile_id]
            duration = int(tile["nominal_exptime_seconds"])
            t = max(now, _sec(row["window_start_utc"]))
            estimate = self._future_option(tile_id, row, t)
            penalty = float(self.config["penalties"]["required_miss"]) if tile["scheduling_class"] == "REQUIRED" else (
                float(self.config["penalties"]["flexible_shortfall_per_tile"])
                if flex_counts.get(str(tile["region_id"]), 0) < int(self.config["flexible_quota_per_region"]) else 0.0)
            urgency = sum(request["delta"] for request in requests.requests if (request["id"], tile_id) in requests.pairs)
            priority = (estimate.science + estimate.success * penalty + urgency) / duration
            if tile_id not in relevant or priority > relevant[tile_id]:
                relevant[tile_id] = priority
        for tile_id, option in actual.items():
            relevant[tile_id] = max(relevant.get(tile_id, 0.0), option.science / max(1, option.end - now))
        selected = sorted(relevant, key=lambda item: relevant[item], reverse=True)[:MAX_TILES]
        # The exact current action set is never discarded by a geometric
        # publication cache.  When more than MAX_TILES are visible, the score
        # ranking itself is the explicit tractability truncation.
        selected_set = set(selected)
        bit = {tile_id: 1 << index for index, tile_id in enumerate(selected)}
        by_tile: dict[str, list[dict]] = defaultdict(list)
        for row in night_rows:
            tile_id = str(row["tile_id"])
            if tile_id in selected_set:
                by_tile[tile_id].append(row)
        count = max(1, (horizon - now) // UNIT)
        states: list[dict[tuple[int, int], tuple[float, tuple[str, str, str] | None]]] = [dict() for _ in range(count + 1)]
        states[0][(0, 0)] = (0.0, None)
        option_cache: dict[int, list[Option]] = {}
        terminal_cache: dict[tuple[int, int], float] = {}
        coverage_weight = float(self.config.get("coverage_bonus_weight", 0.0))
        baseline_counts = [0] * len(self.regions)
        for tile_id in completed:
            region = str(self.tiles[tile_id]["region_id"])
            baseline_counts[self.region_index[region]] += 1
        quota = int(self.config["flexible_quota_per_region"])

        def terminal(mask: int, req_state: int) -> float:
            key = mask, req_state
            if key not in terminal_cache:
                value = sum(future_value.get(tile_id, 0.0) for tile_id in selected
                            if tile_id not in completed and not mask & bit[tile_id])
                value += sum(self._request_terminal(row, req_state, requests, future_prob, horizon)
                             for row in requests.requests)
                terminal_cache[key] = value
            return terminal_cache[key]

        def node_options(index: int) -> list[Option]:
            if index in option_cache:
                return option_cache[index]
            moment = now + index * UNIT
            if index == 0:
                options = [item for tile_id, item in actual.items() if tile_id in selected_set]
            else:
                options = []
                for tile_id in selected:
                    tile = self.tiles[tile_id]
                    duration = int(tile["nominal_exptime_seconds"])
                    if moment + duration > horizon:
                        continue
                    if not _sec(tile["available_from_utc"]) <= moment < _sec(tile["available_until_utc"]):
                        continue
                    for row in by_tile[tile_id]:
                        if _sec(row["window_start_utc"]) <= moment and moment + duration <= _sec(row["window_end_utc"]):
                            options.append(self._future_option(tile_id, row, moment))
                            break
            options = [item for item in options if item.end <= horizon]
            def action_priority(item: Option) -> float:
                tile = self.tiles[item.tile_id]
                penalty = (float(self.config["penalties"]["required_miss"])
                           if tile["scheduling_class"] == "REQUIRED"
                           else float(self.config["penalties"]["flexible_shortfall_per_tile"])
                           if flex_counts.get(str(tile["region_id"]), 0) < quota else 0.0)
                request_value = sum(row["delta"] for row in requests.requests
                                    if (row["id"], item.tile_id) in requests.pairs)
                return (item.science + item.success * penalty + request_value) / max(1, item.end - moment)
            options.sort(key=action_priority, reverse=True)
            option_cache[index] = options[:MAX_ACTIONS]
            return option_cache[index]

        def add(target: int, key: tuple[int, int], score: float,
                first: tuple[str, str, str] | None) -> None:
            previous = states[target].get(key)
            if previous is None or score > previous[0]:
                states[target][key] = (score, first)

        slot_anchor = now - int(snap["cursor"]["slot_offset_seconds"])
        wait_rate = float(self.config["penalties"]["avoidable_wait_per_second"])
        for index in range(count):
            if not states[index]:
                continue
            moment = now + index * UNIT
            options = node_options(index)
            if len(states[index]) > BEAM_WIDTH:
                ranked = sorted(states[index].items(),
                                key=lambda item: item[1][0] + terminal(*item[0]), reverse=True)
                states[index] = dict(ranked[:BEAM_WIDTH])
            step = SLOT - ((moment - slot_anchor) % SLOT)
            wait_target = min(count, index + max(1, step // UNIT))
            for (mask, req_state), (score, first) in states[index].items():
                actionable = any((tile_id not in completed and not mask & bit[tile_id])
                                 for tile_id in actual if index == 0 and tile_id in bit)
                if index > 0:
                    actionable = any(item.tile_id not in completed and not mask & bit[item.tile_id]
                                     for item in options)
                wait_cost = wait_rate * (wait_target - index) * UNIT if actionable else 0.0
                add(wait_target, (mask, req_state), score - wait_cost,
                    first if first is not None else ("wait", "", ""))
                for option in options:
                    tile_id = option.tile_id
                    was_done = tile_id in completed or bool(mask & bit[tile_id])
                    tag_options = requests.tags(tile_id, moment)
                    if was_done and not tag_options and not self.mechanics:
                        continue
                    if was_done and not tag_options and option.science <= self.detector.bests.get(tile_id, 0.0):
                        continue
                    variants = tag_options + (() if was_done and not self.mechanics else ("",))
                    if not variants:
                        continue
                    next_mask = mask | bit[tile_id]
                    if was_done:
                        marginal_science = max(0.0, option.science - self.detector.bests.get(tile_id, option.science)) if self.mechanics else 0.0
                        base = 0.0
                        obligation = 0.0
                    else:
                        marginal_science = option.science
                        base = option.base
                        tile = self.tiles[tile_id]
                        region = str(tile["region_id"])
                        if tile["scheduling_class"] == "REQUIRED":
                            obligation = float(self.config["penalties"]["required_miss"]) * option.success
                        else:
                            already = flex_counts.get(region, 0) + sum(
                                bool(mask & bit[other]) for other in selected
                                if other not in completed and self.tiles[other]["scheduling_class"] == "FLEXIBLE"
                                and self.tiles[other]["region_id"] == region)
                            obligation = (float(self.config["penalties"]["flexible_shortfall_per_tile"]) * option.success
                                          if already < quota else 0.0)
                    coverage = 0.0
                    if coverage_weight and not was_done:
                        counts = baseline_counts.copy()
                        for other in selected:
                            if other not in completed and mask & bit[other]:
                                counts[self.region_index[str(self.tiles[other]["region_id"])]] += 1
                        old_even = _evenness(tuple(counts))
                        counts[self.region_index[str(self.tiles[tile_id]["region_id"])]] += 1
                        new_even = _evenness(tuple(counts))
                        coverage = coverage_weight * (base * new_even + self.science_base_estimate * (new_even - old_even))
                    for req_id in variants:
                        new_req, bundle = requests.transition(req_state, req_id, tile_id) if req_id else (req_state, 0.0)
                        end_index = index + (option.end - moment) // UNIT
                        choice = first if first is not None else ("observe", tile_id, req_id)
                        add(end_index, (next_mask, new_req),
                            score + marginal_science + obligation + coverage + option.success * bundle,
                            choice)

        if not states[count]:
            decision = {"action": "wait", "reason": ""}
        else:
            (_, _), (_, first) = max(states[count].items(),
                                     key=lambda item: item[1][0] + terminal(*item[0]))
            if first is None or first[0] == "wait" or first[1] not in actual:
                decision = {"action": "wait", "reason": ""}
            else:
                option = actual[first[1]]
                decision = {"action": "observe", "tile_id": first[1],
                            "program": option.program, "request_id": first[2], "reason": ""}
        if self.mechanics:
            if decision["action"] == "observe":
                option = actual[decision["tile_id"]]
                baseline = option.science / max(0.01, option.success)
                self.detector.note_observation(option.tile_id, baseline,
                                               under_cold_wave=self.detector.under_cold_wave(snap))
            else:
                self.detector.note_observation(None, None)
        if reports:
            decision["reports"] = reports
        return decision


def run() -> None:
    policy: ModelPolicy | None = None
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        kind, payload = parse_platform_message(message)
        if kind == "initialize":
            policy = ModelPolicy(payload)
            continue
        if policy is None:
            raise RuntimeError("decision before initialize")
        decision = policy.decide(payload)
        output = decision_response(int(message["decision_sequence"]), decision,
                                   decision.get("reports"))
        print(json.dumps(output, ensure_ascii=False, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    run()
