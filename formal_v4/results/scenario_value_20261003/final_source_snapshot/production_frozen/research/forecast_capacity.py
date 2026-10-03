"""Sound time constraints from already-issued v4 public forecasts.

``rain``/``storm`` labels prove event occurrence, not force_close.  The public
generator accepts weather configs with force_close=False.  Consequently the
default closing_kinds is empty: future_windows is an upper bound on available
time, never a promise that weather/background/instrument state will be good.

Supply closing_kinds only when that additional generator assumption is known.
No two notices are joined into one event, including equal kind/direction pairs.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

WEATHER_KINDS = frozenset(("rain", "storm", "overcast", "haze", "cold_snap"))
FORECASTABLE_KINDS = WEATHER_KINDS | {"rocket_launch"}


def _timestamp(value) -> float:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, (float, int)):
        return float(value)
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("forecast timestamps must include a timezone")
    return moment.astimezone(timezone.utc).timestamp()


def _utc(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def _merge(intervals) -> list[tuple[float, float]]:
    result = []
    for a, b in sorted(intervals):
        if b <= a:
            continue
        if result and a <= result[-1][1]:
            result[-1] = result[-1][0], max(result[-1][1], b)
        else:
            result.append((a, b))
    return result


def _intersection(left, right) -> list[tuple[float, float]]:
    left, right = _merge(left), _merge(right)
    result, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        a, b = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if a < b:
            result.append((a, b))
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return result


def _subtract(intervals, excluded) -> list[tuple[float, float]]:
    excluded = _merge(excluded)
    result = []
    for a, b in _merge(intervals):
        cursor = a
        for c, d in excluded:
            if d <= cursor:
                continue
            if c >= b:
                break
            if c > cursor:
                result.append((cursor, min(c, b)))
            cursor = max(cursor, d)
            if cursor >= b:
                break
        if cursor < b:
            result.append((cursor, b))
    return result


def _seconds(intervals) -> float:
    return sum(b - a for a, b in _merge(intervals))


def extract_forecasts(snapshot: Mapping) -> list[Mapping]:
    """Read latest_forecast plus all new_messages, accepting wrapped protocol JSON.

    This function does not establish that an issue is in the past; ingest does.
    Duplicate delivery in both fields is expected and is deduplicated there.
    """
    snapshot = snapshot.get("payload", snapshot)
    records = [record for record in snapshot.get("new_messages", [])
               if record.get("record_type") == "forecast"]
    latest = snapshot.get("latest_forecast")
    if latest and latest.get("record_type") == "forecast":
        records.append(latest)
    return records


class ForecastCapacity:
    """Public-calendar forecast constraints, with explicit closure assumptions.

    ForecastCapacity(public_nights, slot_seconds=900, *, closing_kinds=()).
    ingest(snapshot): accept only already-issued messages; retain older forecasts.
    summary(now, end=None): per-night guaranteed/possible event and time capacities.
    future_windows(now, end=None, visibility_windows=None): calendar windows minus
      guaranteed ALL event coverage for closing_kinds. Returns datetime pairs.
    capacity_in_windows(windows, now, end=None): same remaining seconds by night.

    ``closing_kinds`` is an additional caller assumption, not learned from a label.
    No hard exclusion is made for directional notices: coarse azimuth does not
    reveal the sector's azimuth boundaries or altitude extent.
    """
    def __init__(self, public_nights: Sequence, slot_seconds: float = 900,
                 *, closing_kinds=()):
        if slot_seconds <= 0:
            raise ValueError("slot_seconds must be positive")
        self.slot_seconds = float(slot_seconds)
        self.closing_kinds = frozenset(closing_kinds)
        if not self.closing_kinds <= WEATHER_KINDS:
            raise ValueError("global closure assumptions must be weather kinds")
        self.nights = []
        for night in public_nights:
            a, b = _timestamp(night["observing_start_utc"]), _timestamp(night["observing_end_utc"])
            count = (b - a) / self.slot_seconds
            if b <= a or abs(count - round(count)) > 1e-7:
                raise ValueError("night must consist of complete public observing slots")
            if "slot_count" in night and int(night["slot_count"]) != round(count):
                raise ValueError("slot_count does not match the night interval")
            self.nights.append({"night_date": str(night["night_date"]),
                                "night_id": str(night.get("night_id", night["night_date"])),
                                "start": a, "end": b, "slot_count": int(round(count))})
        self.nights.sort(key=lambda n: n["start"])
        for k, night in enumerate(self.nights):
            if k and night["start"] < self.nights[k - 1]["end"]:
                raise ValueError("public observing nights must not overlap")
        self.by_date = {n["night_date"]: n for n in self.nights}
        if len(self.by_date) != len(self.nights):
            raise ValueError("night_date must uniquely identify an observing night")
        self.records = {}
        self.events = []
        self.warnings = []

    def _notice(self, notice, coverage, source_key, notice_index):
        kind, direction = notice.get("event_kind"), notice.get("direction")
        dates = set(map(str, notice.get("nights", [])))
        if kind not in FORECASTABLE_KINDS or not dates or not dates <= self.by_date.keys():
            raise ValueError("notice has unknown event kind, empty nights, or unknown night_date")
        touched = sorted((self.by_date[d] for d in dates), key=lambda n: n["start"])
        if any(n["start"] >= coverage[1] or n["end"] <= coverage[0] for n in touched):
            raise ValueError("notice names a night outside its forecast coverage")
        if kind == "rocket_launch" and (direction == "ALL" or len(touched) != 1):
            raise ValueError("official rocket events are directional and end in their starting night")
        first, last = touched[0], touched[-1]
        inside = {n["night_date"] for n in self.nights
                  if first["start"] <= n["start"] <= last["start"]}
        if dates != inside:
            raise ValueError("one continuous event cannot omit an intermediate observing night")
        possible = _intersection([(n["start"], n["end"]) for n in touched], [coverage])
        guaranteed = []
        if kind in WEATHER_KINDS:
            # Start is a published slot start and end is a slot end. If the event
            # touches first and last, start <= first.end-slot and end >= last.start+slot.
            # For one multi-slot night this interval is empty; a one-slot night is full.
            core = (first["end"] - self.slot_seconds, last["start"] + self.slot_seconds)
            guaranteed = _intersection([core], possible)
        return {"event_kind": kind, "direction": direction,
                "night_dates": [n["night_date"] for n in touched],
                "guaranteed": guaranteed, "possible": possible,
                "source": source_key, "notice_index": notice_index}

    def ingest(self, snapshot: Mapping) -> dict:
        """Consume a decision snapshot; unpublished forecasts are never queued.

        A later issue does not retract an older factual forecast. v4 has no forecast
        revision protocol. Conflicting records with one issue/coverage key are ignored
        and reported as warnings rather than silently replacing the earlier record.
        """
        payload = snapshot.get("payload", snapshot)
        now = _timestamp(payload["now_utc"])
        accepted = duplicates = unpublished = invalid = 0
        for record in extract_forecasts(payload):
            try:
                issued = _timestamp(record["issued_at_utc"])
                coverage = (_timestamp(record["coverage_start_utc"]),
                            _timestamp(record["coverage_end_utc"]))
                if issued > now:
                    unpublished += 1
                    continue
                if coverage[1] <= coverage[0] or coverage[0] != issued:
                    raise ValueError("v4 coverage must begin at issue time and have positive duration")
                key = (issued, *coverage)
                signature = json.dumps(record, sort_keys=True, separators=(",", ":"))
                if key in self.records:
                    if self.records[key]["signature"] != signature:
                        raise ValueError("conflicting duplicate forecast; v4 has no revision semantics")
                    duplicates += 1
                    continue
                events = [self._notice(notice, coverage, key, i)
                          for i, notice in enumerate(record.get("notices", []))]
                self.records[key] = {"issued": issued, "coverage": coverage,
                                     "signature": signature, "events": events}
                self.events.extend(events)
                accepted += 1
            except (KeyError, TypeError, ValueError) as exc:
                invalid += 1
                self.warnings.append(str(exc))
        return {"accepted": accepted, "duplicates": duplicates,
                "unpublished_ignored": unpublished, "invalid": invalid}

    def _bounds(self, now, end):
        now = _timestamp(now)
        last = self.nights[-1]["end"] if self.nights else now
        end = min(last, _timestamp(end)) if end is not None else last
        return now, max(now, end)

    def _excluded(self, bounds):
        return _intersection([interval for event in self.events
                              if event["source"][0] <= bounds[0]
                              and event["direction"] == "ALL" and event["event_kind"] in self.closing_kinds
                              for interval in event["guaranteed"]], [bounds])

    def _future_windows(self, now, end=None, visibility_windows=None):
        bounds = self._bounds(now, end)
        windows = _intersection([(n["start"], n["end"]) for n in self.nights], [bounds])
        if visibility_windows is not None:
            windows = _intersection(windows, [(_timestamp(a), _timestamp(b)) for a, b in visibility_windows])
        return _subtract(windows, self._excluded(bounds))

    def future_windows(self, now, end=None, visibility_windows=None) -> list[tuple[datetime, datetime]]:
        return [(datetime.fromtimestamp(a, timezone.utc), datetime.fromtimestamp(b, timezone.utc))
                for a, b in self._future_windows(now, end, visibility_windows)]

    def capacity_in_windows(self, windows, now, end=None) -> dict[str, float]:
        """Upper bound on remaining usable geometric time, keyed by night_date."""
        remaining = self._future_windows(now, end, windows)
        return {n["night_date"]: _seconds(_intersection(remaining, [(n["start"], n["end"])]))
                for n in self.nights if n["end"] > _timestamp(now)}

    def summary(self, now, end=None) -> dict:
        bounds = self._bounds(now, end)
        excluded = self._excluded(bounds)
        records = [record for record in self.records.values() if record["issued"] <= bounds[0]]
        events = [event for event in self.events if event["source"][0] <= bounds[0]]
        published_coverage = _merge([record["coverage"] for record in records])
        certain_all = {kind: _merge([interval for event in events
                                    if event["direction"] == "ALL" and event["event_kind"] == kind
                                    for interval in event["guaranteed"]]) for kind in WEATHER_KINDS}
        possible = {kind: _merge([interval for event in events if event["event_kind"] == kind
                                 for interval in event["possible"]]) for kind in FORECASTABLE_KINDS}
        nights = []
        for night in self.nights:
            window = _intersection([(night["start"], night["end"])], [bounds])
            if not window:
                continue
            guaranteed = {kind: _seconds(_intersection(window, spans)) for kind, spans in certain_all.items()}
            # Absence of a forecastable event is a valid negative observation only
            # inside a complete, already-issued forecast's coverage. It does not
            # imply the station is open or the instrument is healthy.
            no_event = []
            for record in records:
                covered = _intersection(window, [record["coverage"]])
                possible_here = [interval for event in record["events"] for interval in event["possible"]]
                no_event.extend(_subtract(covered, possible_here))
            seconds = _seconds(window)
            closed = _seconds(_intersection(window, excluded))
            nights.append({"night_id": night["night_id"], "night_date": night["night_date"],
                           "remaining_observing_seconds": seconds,
                           "forecast_covered_seconds": _seconds(_intersection(window, published_coverage)),
                           "guaranteed_all_event_seconds": guaranteed,
                           "possible_event_seconds": {kind: _seconds(_intersection(window, spans))
                                                      for kind, spans in possible.items()},
                           "no_forecastable_event_seconds": _seconds(no_event),
                           "conditional_closed_seconds": closed,
                           "unexcluded_seconds": seconds - closed,
                           "fully_excluded_remaining_window": math.isclose(closed, seconds, abs_tol=1e-7)})
        full_nights = {kind: [n["night_date"] for n in self.nights
                             if _seconds(_intersection([(n["start"], n["end"])], spans))
                             >= n["end"] - n["start"] - 1e-7
                             and n["end"] > bounds[0] and n["start"] < bounds[1]]
                      for kind, spans in certain_all.items()}
        return {"closing_kinds_assumption": sorted(self.closing_kinds),
                "guaranteed_all_event_nights": full_nights,
                "conditional_closed_nights": [n["night_date"] for n in self.nights
                                              if n["end"] > bounds[0] and n["start"] < bounds[1] and
                                              _seconds(_intersection([(n["start"], n["end"])], excluded))
                                              >= n["end"] - n["start"] - 1e-7],
                "guaranteed_closing_windows_utc": [[_utc(a), _utc(b)] for a, b in excluded],
                "nights": nights,
                "warnings": list(self.warnings)}


def uniform_boundary_occupancy(slot_count: int, *, position: str) -> list[float]:
    """Optional soft model, NOT generator probability or an exact closure bound.

    Assumes uniform start/end slot boundaries inside fully observed touched nights.
    ``only`` gives uniform admissible ordered start/end pairs in one night;
    ``first``/``last`` give a uniform boundary in one edge of a multi-night event.
    Do not apply this model to a coverage-censored edge or for hard pruning.
    """
    n = int(slot_count)
    if n < 1:
        raise ValueError("slot_count must be positive")
    if position == "only":
        return [(j + 1) * (n - j) / (n * (n + 1) / 2) for j in range(n)]
    if position == "first":
        return [(j + 1) / n for j in range(n)]
    if position == "last":
        return [(n - j) / n for j in range(n)]
    if position == "middle":
        return [1.0] * n
    raise ValueError("position must be only, first, last, or middle")
