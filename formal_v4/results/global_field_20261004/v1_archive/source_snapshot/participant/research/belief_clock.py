"""Calendar clock for a scalar weather belief, excluding daytime slot evolution.

Counts observing time and new observing nights from the last belief timestamp.
The product retention is an approximation for a scalar C: the actual generator
has a separate night_state and resets slot_state from it at each night start.
"""
from __future__ import annotations

import bisect
import math
from datetime import datetime, timezone
from collections.abc import Mapping, Sequence


def _timestamp(value) -> float:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, (int, float)):
        return float(value)
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("belief timestamps must include a timezone")
    return moment.astimezone(timezone.utc).timestamp()


class BeliefClock:
    """BeliefClock(public_nights, slot_seconds=900, initial_time=None).

    mark(time) anchors the stored belief after feedback or another state update.
    elapsed(time) returns elapsed_slots/night_transitions/retention without mutation.
    prior(C,E,time,seasonal_C) performs the same scalar log-mean reversion using
    that retention. Repeated waits cannot accidentally lose the night transition.
    public_nights accepts (start,end) tuples or protocol night dictionaries.
    """
    def __init__(self, public_nights: Sequence, slot_seconds: float = 900,
                 initial_time=None, *, phi_slot: float = .88, phi_night: float = .82):
        if slot_seconds <= 0 or not (0 <= phi_slot <= 1 and 0 <= phi_night <= 1):
            raise ValueError("invalid slot duration or AR retention")
        intervals = []
        for night in public_nights:
            if isinstance(night, Mapping):
                a, b = night["observing_start_utc"], night["observing_end_utc"]
            else:
                a, b = night
            intervals.append((_timestamp(a), _timestamp(b)))
        intervals.sort()
        for k, (a, b) in enumerate(intervals):
            if b <= a or (k and a < intervals[k - 1][1]):
                raise ValueError("observing nights must be positive and non-overlapping")
        self.starts = [a for a, b in intervals]
        self.ends = [b for a, b in intervals]
        self.prefix = [0.0]
        for a, b in intervals:
            self.prefix.append(self.prefix[-1] + b - a)
        self.slot_seconds = float(slot_seconds)
        self.phi_slot = float(phi_slot)
        self.phi_night = float(phi_night)
        self.anchor = _timestamp(initial_time) if initial_time is not None else (self.starts[0] if self.starts else None)

    def mark(self, time) -> None:
        self.anchor = _timestamp(time)

    def _observed_before(self, timestamp: float) -> float:
        complete = bisect.bisect_right(self.ends, timestamp)
        seconds = self.prefix[complete]
        if complete < len(self.starts):
            seconds += max(0.0, min(timestamp, self.ends[complete]) - self.starts[complete])
        return seconds

    def elapsed(self, time) -> dict:
        now = _timestamp(time)
        if self.anchor is None:
            return {"observing_seconds": 0.0, "elapsed_slots": 0.0,
                    "night_transitions": 0, "retention": 1.0,
                    "slot_retention": 1.0, "night_retention": 1.0}
        if now < self.anchor:
            raise ValueError("belief clock cannot run backward")
        observing_seconds = max(0.0, self._observed_before(now) - self._observed_before(self.anchor))
        previous_started = bisect.bisect_right(self.starts, self.anchor)
        current_started = bisect.bisect_right(self.starts, now)
        transitions = current_started - previous_started
        # Entering the first survey night is initialization, not a cross-night step.
        if previous_started == 0 and current_started > 0:
            transitions -= 1
        transitions = max(0, transitions)
        slots = observing_seconds / self.slot_seconds
        slot_retention = self.phi_slot ** slots
        night_retention = self.phi_night ** transitions
        return {"observing_seconds": observing_seconds, "elapsed_slots": slots,
                "night_transitions": transitions,
                "retention": slot_retention * night_retention,
                "slot_retention": slot_retention, "night_retention": night_retention}

    def prior(self, C: float, E: float, time, seasonal_C: float) -> tuple[float, float]:
        phi = self.elapsed(time)["retention"]
        C_prior = math.exp(phi * math.log(max(.02, float(C)))
                           + (1.0 - phi) * math.log(max(.02, float(seasonal_C))))
        return C_prior, min(1.0, max(.025, float(E)))
