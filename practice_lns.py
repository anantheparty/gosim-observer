#!/usr/bin/env python3
"""Local search over grouped first-observation moves on dev-reference.

The 28 request-tagged revisits stay at their original slots. Each candidate
schedule is evaluated with a precomputed exact start-of-wait actionability mask
and the authoritative scorer checks the best output. This is an offline practice
optimizer and never contacts the competition platform.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import bounds_public as geometry
from challenge.contracts import DECISION_COLUMNS
from challenge.scoring_core import ChallengeScorer, load_decisions


ROOT = Path(__file__).resolve().parent
PROGRAMS = ("DARK", "BRIGHT", "BACKUP")


@dataclass(frozen=True)
class FixedVisit:
    tile_index: int
    slot_index: int
    request_id: str
    program: str


def _midpoint_legal(
    tile: dict[str, str], moments: np.ndarray, latitude: float,
    longitude: float, minimum_altitude: float,
) -> np.ndarray:
    days = moments / 86400.0 + 2440587.5 - 2451545.0
    sidereal = (280.46061837 + 360.98564736629 * days + longitude) % 360.0
    hour_angle = np.deg2rad((sidereal - float(tile["ra_deg"]) + 180.0) % 360.0 - 180.0)
    lat = math.radians(latitude)
    dec = math.radians(float(tile["dec_deg"]))
    sin_altitude = (
        math.sin(lat) * math.sin(dec)
        + math.cos(lat) * math.cos(dec) * np.cos(hour_angle)
    )
    return (
        (moments >= geometry._epoch(tile["available_from_utc"]))
        & (moments < geometry._epoch(tile["available_until_utc"]))
        & (sin_altitude >= math.sin(math.radians(minimum_altitude)) - 1e-12)
    )


class PracticeModel:
    def __init__(self, scenario: Path, seed_plan: Path):
        self.scenario = scenario
        self.scorer = ChallengeScorer.from_files(scenario)
        if self.scorer.mechanics:
            raise ValueError("practice_lns.py only supports the public-weather practice rules")
        self.tiles = geometry._read_csv(scenario / "outputs" / "reference" / "tiles.csv")
        self.tile_ids = [row["tile_id"] for row in self.tiles]
        self.tile_index = {tile_id: i for i, tile_id in enumerate(self.tile_ids)}
        self.slots = geometry._read_csv(scenario / "outputs" / "reference" / "slots.csv")
        calendar = self.scorer.geometry.calendar_config
        self.tile_config = self.scorer.geometry.tile_config
        self.weather_config = self.scorer.weather.config
        self.latitude = float(calendar["site"]["latitude_deg"])
        self.longitude = float(calendar["site"]["longitude_deg"])
        self.minimum_altitude = float(self.tile_config["geometry"]["minimum_altitude_deg"])
        self.instants, self.sidereal, self.night_end = geometry._time_grid(
            self.slots, self.longitude
        )
        self.n_units = len(self.instants)
        self.unit_index = np.arange(self.n_units)
        self.exposure_units = np.array([
            int(tile["nominal_exptime_seconds"]) // geometry.UNIT_SECONDS
            for tile in self.tiles
        ], dtype=np.int32)
        self.actionable = np.zeros(self.n_units, dtype=np.uint64)
        self.scores = np.full((len(self.tiles), len(self.slots)), np.nan, dtype=np.float64)
        self.program_codes = np.zeros((len(self.tiles), len(self.slots)), dtype=np.uint8)
        self._precompute()
        self.initial_starts, self.fixed_visits = self._load_plan(seed_plan)
        self.first_request_start = np.full(len(self.tiles), self.n_units + 1, dtype=np.int32)
        for visit in self.fixed_visits:
            self.first_request_start[visit.tile_index] = min(
                self.first_request_start[visit.tile_index],
                visit.slot_index * geometry.POINTS_PER_SLOT,
            )
        self.fixed_request_reward = 3920.0  # all individually possible requests in dev-reference
        self._fixed_occupied = np.zeros(self.n_units, dtype=np.bool_)
        for visit in self.fixed_visits:
            start = visit.slot_index * geometry.POINTS_PER_SLOT
            end = start + self.exposure_units[visit.tile_index]
            if np.any(self._fixed_occupied[start:end]):
                raise ValueError("fixed request revisits overlap")
            self._fixed_occupied[start:end] = True

    def _precompute(self) -> None:
        scorer = self.scorer
        wc = self.weather_config
        airmass_exponent = float(wc["score_interface"]["airmass_exponent"])
        quality_cap = float(wc["score_interface"]["maximum_weather_quality"])
        dark = float(scorer.config["quality_thresholds"]["dark"])
        bright = float(scorer.config["quality_thresholds"]["bright"])
        bonus = scorer.config["program_bonus"]
        for i, tile in enumerate(self.tiles):
            tile_id = tile["tile_id"]
            exposure = int(tile["nominal_exptime_seconds"])
            value = scorer.tile_values[tile_id]
            geometry_mask = geometry._geometry_candidate_mask(
                tile, self.instants, self.sidereal, self.night_end,
                self.latitude, self.minimum_altitude,
            )
            candidates = np.flatnonzero(geometry_mask)
            observable = np.zeros(len(self.slots), dtype=np.bool_)
            weather_numerator = np.zeros(len(self.slots), dtype=np.float64)
            for k, slot in enumerate(scorer.slots):
                conditions = scorer.weather.get_effective_conditions(slot.slot_id, tile_id)
                if conditions["is_observable"]:
                    observable[k] = True
                    weather_numerator[k] = (
                        float(conditions["instrument_efficiency"])
                        * float(conditions["transparency"])
                        * float(conditions["sky_quality"])
                        / float(conditions["seeing_arcsec"])
                    )
            for offset_units in range(geometry.POINTS_PER_SLOT):
                starts = candidates[
                    candidates % geometry.POINTS_PER_SLOT == offset_units
                ]
                if len(starts) == 0:
                    continue
                segments = geometry._segments(
                    exposure, offset_units * geometry.UNIT_SECONDS
                )
                successful = np.ones(len(starts), dtype=np.bool_)
                actionable = np.ones(len(starts), dtype=np.bool_)
                for segment_index, (_, midpoint_after_start) in enumerate(segments):
                    slot_index = starts // geometry.POINTS_PER_SLOT + segment_index
                    successful &= observable[slot_index]
                    actionable &= observable[slot_index]
                    actionable &= _midpoint_legal(
                        tile, self.instants[starts] + midpoint_after_start,
                        self.latitude, self.longitude, self.minimum_altitude,
                    )
                self.actionable[starts[actionable]] |= np.uint64(1) << np.uint64(i)
                starts = starts[successful]
                if offset_units != 0 or len(starts) == 0:
                    continue
                base = np.zeros(len(starts), dtype=np.float64)
                dark_parts = np.zeros(len(starts), dtype=np.float64)
                bright_parts = np.zeros(len(starts), dtype=np.float64)
                backup_parts = np.zeros(len(starts), dtype=np.float64)
                for segment_index, (seconds, midpoint_after_start) in enumerate(segments):
                    slot_index = starts // geometry.POINTS_PER_SLOT + segment_index
                    quality = geometry._segment_quality_upper(
                        tile, self.instants[starts] + midpoint_after_start,
                        self.latitude, self.longitude, self.tile_config["lunar_model"],
                        weather_numerator[slot_index], airmass_exponent, quality_cap,
                    )
                    part = seconds / exposure * quality
                    base += part
                    dark_parts += part * (quality >= dark)
                    bright_parts += part * ((quality < dark) & (quality >= bright))
                    backup_parts += part * (quality < bright)
                bonuses = np.vstack((
                    dark_parts * float(bonus["DARK"]),
                    bright_parts * float(bonus["BRIGHT"]),
                    backup_parts * float(bonus["BACKUP"]),
                ))
                chosen = np.argmax(bonuses, axis=0)
                slot_indices = starts // geometry.POINTS_PER_SLOT
                self.scores[i, slot_indices] = value * (
                    base + bonuses[chosen, np.arange(len(starts))]
                )
                self.program_codes[i, slot_indices] = chosen.astype(np.uint8)

    def _load_plan(self, path: Path) -> tuple[np.ndarray, list[FixedVisit]]:
        starts = np.full(len(self.tiles), -1, dtype=np.int32)
        revisits = []
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["action"] != "observe":
                    raise ValueError("seed plan must contain only observations")
                i = self.tile_index[row["tile_id"]]
                slot_index = self.scorer.slot_indices[row["slot_id"]]
                if starts[i] < 0:
                    if row["request_id"]:
                        raise ValueError("seed plan first observations must be untagged")
                    starts[i] = slot_index
                else:
                    revisits.append(FixedVisit(
                        i, slot_index, row["request_id"], row["program"]
                    ))
        if np.any(starts < 0):
            raise ValueError("seed plan must complete all tiles")
        return starts, revisits

    def evaluate(self, starts: np.ndarray) -> float:
        if starts.shape != self.initial_starts.shape:
            return -math.inf
        if np.any(starts < 0) or np.any(starts >= len(self.slots)):
            return -math.inf
        science = self.scores[np.arange(len(starts)), starts]
        if np.any(np.isnan(science)):
            return -math.inf
        start_units = starts * geometry.POINTS_PER_SLOT
        end_units = start_units + self.exposure_units
        if np.any(end_units > self.first_request_start):
            return -math.inf
        occupied = self._fixed_occupied.copy()
        completed_events = np.zeros(self.n_units + 1, dtype=np.uint64)
        for i in range(len(starts)):
            begin = int(start_units[i])
            end = int(end_units[i])
            if np.any(occupied[begin:end]):
                return -math.inf
            occupied[begin:end] = True
            completed_events[end] |= np.uint64(1) << np.uint64(i)
        final_unit = max(
            int(end_units.max()),
            max(
                (visit.slot_index * geometry.POINTS_PER_SLOT
                 + int(self.exposure_units[visit.tile_index]))
                for visit in self.fixed_visits
            ),
        )
        wait_starts = (
            ~occupied[:final_unit]
            & (
                (self.unit_index[:final_unit] % geometry.POINTS_PER_SLOT == 0)
                | np.r_[False, occupied[: final_unit - 1]]
            )
        )
        candidates = np.flatnonzero(wait_starts)
        if len(candidates):
            completed = np.bitwise_or.accumulate(completed_events[:final_unit])
            charge = (self.actionable[candidates] & ~completed[candidates]) != 0
            units = geometry.POINTS_PER_SLOT - candidates % geometry.POINTS_PER_SLOT
            charged_seconds = int(np.sum(units[charge])) * geometry.UNIT_SECONDS
        else:
            charged_seconds = 0
        return float(np.sum(science)) + self.fixed_request_reward - charged_seconds * 0.001

    def candidate_pool(self, per_week: int = 8) -> list[np.ndarray]:
        slots_per_week = 7 * 48  # approximate only for grouping; no legality effect
        result = []
        for i in range(len(self.tiles)):
            eligible = np.flatnonzero(np.isfinite(self.scores[i]))
            eligible = eligible[
                eligible * geometry.POINTS_PER_SLOT
                + self.exposure_units[i]
                <= self.first_request_start[i]
            ]
            if len(eligible) == 0:
                raise ValueError(f"tile {self.tile_ids[i]} has no candidate")
            selected = {int(self.initial_starts[i])}
            for group in np.unique(eligible // slots_per_week):
                rows = eligible[eligible // slots_per_week == group]
                selected.add(int(rows[0]))
                selected.add(int(rows[-1]))
                top = rows[np.argsort(self.scores[i, rows])[-per_week:]]
                selected.update(map(int, top))
            result.append(np.array(sorted(selected), dtype=np.int32))
        return result

    def all_candidates(self) -> list[np.ndarray]:
        """Every legal start for a first visit, with fixed revisits respected."""
        result = []
        for i in range(len(self.tiles)):
            eligible = np.flatnonzero(np.isfinite(self.scores[i]))
            eligible = eligible[
                eligible * geometry.POINTS_PER_SLOT + self.exposure_units[i]
                <= self.first_request_start[i]
            ]
            result.append(eligible.astype(np.int32))
        return result

    def _construct(
        self, candidates: list[np.ndarray], rng: random.Random,
        time_price_per_day: float, noise: float, order_noise: float,
    ) -> np.ndarray | None:
        """Randomized earliest-deadline assignment of all first visits.

        This creates large coherent moves: the whole first-visit schedule is
        rebuilt while all previously earned request revisits remain fixed.
        Time price is a surrogate used only to generate proposals. The exact
        wait formula in evaluate() selects the winning proposal.
        """
        occupied = self._fixed_occupied.copy()
        starts = np.full(len(self.tiles), -1, dtype=np.int32)
        days = self.instants[::geometry.POINTS_PER_SLOT] / 86400.0
        scarcity = []
        for i, eligible in enumerate(candidates):
            if len(eligible) == 0:
                return None
            first_day = days[eligible[0]]
            early_count = int(np.searchsorted(days[eligible], first_day + 30.0))
            scarcity.append((early_count + rng.uniform(-order_noise, order_noise), i))
        for _, i in sorted(scarcity):
            eligible = candidates[i]
            weight = (
                self.scores[i, eligible]
                - time_price_per_day * (days[eligible] - days[eligible[0]])
            )
            if noise:
                weight = weight + np.array(
                    [rng.gauss(0.0, noise) for _ in range(len(eligible))]
                )
            # Higher surrogate utility is tried first; check exact intervals.
            for pos in np.argsort(weight)[::-1]:
                slot = int(eligible[pos])
                begin = slot * geometry.POINTS_PER_SLOT
                end = begin + self.exposure_units[i]
                if not np.any(occupied[begin:end]):
                    starts[i] = slot
                    occupied[begin:end] = True
                    break
            if starts[i] < 0:
                return None
        return starts

    def wait_profile(self, starts: np.ndarray, bucket_slots: int) -> list[dict]:
        """Exact charged-wait starts and unfinished actionable sets by window."""
        occupied = self._fixed_occupied.copy()
        events = np.zeros(self.n_units + 1, dtype=np.uint64)
        for i, slot in enumerate(starts):
            begin = int(slot) * geometry.POINTS_PER_SLOT
            end = begin + int(self.exposure_units[i])
            occupied[begin:end] = True
            events[end] |= np.uint64(1) << np.uint64(i)
        final_unit = max(
            int(np.max(starts * geometry.POINTS_PER_SLOT + self.exposure_units)),
            max(v.slot_index * geometry.POINTS_PER_SLOT +
                int(self.exposure_units[v.tile_index]) for v in self.fixed_visits),
        )
        starts_mask = (
            ~occupied[:final_unit]
            & ((self.unit_index[:final_unit] % geometry.POINTS_PER_SLOT == 0)
               | np.r_[False, occupied[:final_unit - 1]])
        )
        wait_indices = np.flatnonzero(starts_mask)
        completed = np.bitwise_or.accumulate(events[:final_unit])
        remaining = self.actionable[wait_indices] & ~completed[wait_indices]
        windows = {}
        for t, mask in zip(wait_indices, remaining):
            if not mask:
                continue
            slot = int(t // geometry.POINTS_PER_SLOT)
            key = slot // bucket_slots
            seconds = int(geometry.POINTS_PER_SLOT - t % geometry.POINTS_PER_SLOT) * geometry.UNIT_SECONDS
            if key not in windows:
                windows[key] = {"start_slot": key * bucket_slots,
                                "end_slot": (key + 1) * bucket_slots,
                                "charged_seconds": 0, "blocker_mask": 0,
                                "wait_starts": 0}
            item = windows[key]
            item["charged_seconds"] += seconds
            item["blocker_mask"] |= int(mask)
            item["wait_starts"] += 1
        return sorted(windows.values(), key=lambda item: -item["charged_seconds"])

    def reassign_blockers(
        self, starts: np.ndarray, blocker_mask: int, end_slot: int,
        candidates: list[np.ndarray], rng: random.Random,
        time_price_per_day: float, noise: float,
    ) -> np.ndarray | None:
        """Move a whole wait-window blocker set to slots before its end."""
        moved = [i for i in range(len(self.tiles)) if blocker_mask & (1 << i)
                 and starts[i] >= end_slot]
        if not moved:
            return None
        occupied = self._fixed_occupied.copy()
        proposal = starts.copy()
        for i, slot in enumerate(starts):
            if i in moved:
                continue
            begin = int(slot) * geometry.POINTS_PER_SLOT
            occupied[begin:begin + self.exposure_units[i]] = True
        eligible_map = {}
        for i in moved:
            eligible = candidates[i][candidates[i] < end_slot]
            if len(eligible) == 0:
                return None
            eligible_map[i] = eligible
        order = sorted(moved, key=lambda i: len(eligible_map[i]) * rng.uniform(0.85, 1.15))
        days = self.instants[::geometry.POINTS_PER_SLOT] / 86400.0
        for i in order:
            eligible = eligible_map[i]
            weight = self.scores[i, eligible] - time_price_per_day * (
                days[eligible] - days[eligible[0]])
            if noise:
                weight = weight + np.array(
                    [rng.gauss(0.0, noise) for _ in range(len(eligible))]
                )
            for pos in np.argsort(weight)[::-1]:
                slot = int(eligible[pos])
                begin = slot * geometry.POINTS_PER_SLOT
                end = begin + self.exposure_units[i]
                if not np.any(occupied[begin:end]):
                    proposal[i] = slot
                    occupied[begin:end] = True
                    break
            if proposal[i] == starts[i]:
                return None
        return proposal

    def write_plan(self, starts: np.ndarray, path: Path) -> None:
        actions = []
        for i, slot_index in enumerate(starts):
            actions.append((int(slot_index), i, "", PROGRAMS[int(self.program_codes[i, slot_index])]))
        for visit in self.fixed_visits:
            actions.append((visit.slot_index, visit.tile_index, visit.request_id, visit.program))
        actions.sort(key=lambda row: (row[0], row[1]))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS)
            writer.writeheader()
            for index, (slot_index, tile_index, request_id, program) in enumerate(actions, 1):
                writer.writerow({
                    "decision_id": f"D{index:06d}",
                    "slot_id": self.scorer.slots[slot_index].slot_id,
                    "action": "observe",
                    "tile_id": self.tile_ids[tile_index],
                    "program": program,
                    "request_id": request_id,
                    "reason": "",
                })

    def authoritative_score(self, path: Path) -> dict:
        scorer = ChallengeScorer.from_files(self.scenario)
        for decision in load_decisions(path, allow_reports=False):
            scorer.apply_decision(decision)
        return scorer.finalize("trace_complete")


def search(model: PracticeModel, seconds: float, seed: int, per_week: int) -> tuple[np.ndarray, float]:
    rng = random.Random(seed)
    pool = model.candidate_pool(per_week)
    all_candidates = model.all_candidates()
    current = model.initial_starts.copy()
    current_score = model.evaluate(current)
    if not math.isfinite(current_score):
        raise RuntimeError("seed plan fails the fast evaluator")
    best = current.copy()
    best_score = current_score
    print(json.dumps({"phase": "seed", "score": current_score, "pool_sizes": [len(x) for x in pool]}), flush=True)

    # Rebuild the entire first-visit schedule under several time prices. These
    # proposals cross a long wait plateau in one step, unlike coordinate moves.
    for price in (0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0):
        for repetition in range(3):
            proposal = model._construct(
                all_candidates, rng, price,
                noise=0.0 if repetition == 0 else 3.0,
                order_noise=0.0 if repetition == 0 else 5.0,
            )
            if proposal is None:
                continue
            value = model.evaluate(proposal)
            if value > best_score + 1e-8:
                best, best_score = proposal.copy(), value
                print(json.dumps({"phase": "construct", "price": price,
                                  "score": best_score}), flush=True)

    # A charged week can depend on many tiles through an OR. The neighborhood
    # below moves every unfinished actionable tile from that window together.
    for bucket_slots in (2 * 48, 7 * 48, 14 * 48, 30 * 48, 90 * 48):
        for window in model.wait_profile(best, bucket_slots)[:4]:
            print(json.dumps({"phase": "window", "days": bucket_slots / 48,
                              "charge": window["charged_seconds"] * 0.001,
                              "blockers": window["blocker_mask"].bit_count()}), flush=True)
            for price in (1.0, 4.0, 16.0):
                for repetition in range(2):
                    proposal = model.reassign_blockers(
                        best, window["blocker_mask"], window["end_slot"],
                        all_candidates, rng, price, 0.0 if repetition == 0 else 4.0,
                    )
                    if proposal is None:
                        continue
                    value = model.evaluate(proposal)
                    if value > best_score + 1e-8:
                        best, best_score = proposal.copy(), value
                        print(json.dumps({"phase": "group", "days": bucket_slots / 48,
                                          "price": price, "score": best_score}), flush=True)
    current, current_score = best.copy(), best_score
    deadline = time.monotonic() + seconds
    iterations = 0
    accepts = 0
    # Mix coordinate ascent with grouped perturbations. A single moved tile
    # often cannot clear an OR-wait penalty; block moves can cross that barrier.
    while time.monotonic() < deadline:
        iterations += 1
        proposal = current.copy()
        group_size = rng.choices([1, 2, 3, 5, 8], weights=[25, 25, 20, 20, 10])[0]
        indices = rng.sample(range(len(model.tiles)), group_size)
        for i in indices:
            choices = pool[i]
            if rng.random() < 0.65:
                choices = choices[choices <= current[i]]
                if len(choices) == 0:
                    choices = pool[i]
            proposal[i] = int(choices[rng.randrange(len(choices))])
        value = model.evaluate(proposal)
        if not math.isfinite(value):
            continue
        temperature = max(2.0, 120.0 * ((deadline - time.monotonic()) / seconds))
        if value >= current_score or rng.random() < math.exp((value - current_score) / temperature):
            current, current_score = proposal, value
            accepts += 1
            if value > best_score + 1e-8:
                best, best_score = proposal.copy(), value
                print(json.dumps({"phase": "improved", "iteration": iterations, "score": best_score}), flush=True)
        if iterations % 2000 == 0:
            current, current_score = best.copy(), best_score
    print(json.dumps({"phase": "done", "iterations": iterations, "accepts": accepts, "best_score": best_score}), flush=True)
    return best, best_score


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=ROOT / "scenarios" / "dev-reference")
    parser.add_argument("--seed-plan", type=Path, default=ROOT / "results" / "practice_reference.csv")
    parser.add_argument("--out", type=Path, default=ROOT / "runs" / "practice_lns" / "decisions.csv")
    parser.add_argument("--seconds", type=float, default=120.0)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--per-week", type=int, default=8)
    args = parser.parse_args()
    model = PracticeModel(args.scenario, args.seed_plan)
    best, predicted = search(model, args.seconds, args.seed, args.per_week)
    model.write_plan(best, args.out)
    report = model.authoritative_score(args.out)
    report_path = args.out.parent / "score_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"predicted": predicted, "authoritative": report["score"]["total"], "output": str(args.out)}), flush=True)


if __name__ == "__main__":
    main()
