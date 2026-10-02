"""Small protocol examples and exhaustive coverage proof checks.

Run: python3 formal_v4/research/forecast_capacity_checks.py
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from forecast_capacity import ForecastCapacity, uniform_boundary_occupancy


class ForecastChecks(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 10, 2, tzinfo=timezone.utc)
        # night_date deliberately differs from the first slot's UTC date.
        self.nights = [{"night_id": f"N2026100{k+1}", "night_date": f"2026-10-0{k+1}",
                        "observing_start_utc": (self.start + timedelta(days=k)).isoformat(),
                        "observing_end_utc": (self.start + timedelta(days=k, minutes=30)).isoformat(),
                        "slot_count": 2} for k in range(4)]

    def forecast(self, notices, *, issued=None, end=None):
        issued = issued or self.start
        return {"record_type": "forecast", "issued_at_utc": issued.isoformat(),
                "coverage_start_utc": issued.isoformat(),
                "coverage_end_utc": (end or issued + timedelta(days=7)).isoformat(),
                "notices": notices}

    def ingest(self, model, record, *, now=None):
        return model.ingest({"now_utc": (now or self.start).isoformat(),
                             "latest_forecast": record, "new_messages": [record]})

    def test_default_no_closure_and_explicit_assumption(self):
        record = self.forecast([{"event_kind": "rain", "direction": "ALL",
                                 "nights": ["2026-10-01", "2026-10-02", "2026-10-03"]}])
        model = ForecastCapacity(self.nights)
        self.assertEqual(self.ingest(model, record)["duplicates"], 1)
        summary = model.summary(self.start)
        self.assertEqual(summary["guaranteed_all_event_nights"]["rain"], ["2026-10-02"])
        self.assertEqual(summary["conditional_closed_nights"], [])
        self.assertEqual([n["unexcluded_seconds"] for n in summary["nights"]], [1800] * 4)
        closing = ForecastCapacity(self.nights, closing_kinds=("rain", "storm"))
        self.ingest(closing, record)
        summary = closing.summary(self.start)
        self.assertEqual(summary["conditional_closed_nights"], ["2026-10-02"])
        self.assertEqual([n["conditional_closed_seconds"] for n in summary["nights"]], [900, 1800, 900, 0])
        windows = closing.future_windows(self.start)
        self.assertEqual(sum((b - a).total_seconds() for a, b in windows), 3600)
        capacity = closing.capacity_in_windows([(self.start, self.start + timedelta(days=4))], self.start)
        self.assertEqual(capacity, {"2026-10-01": 900, "2026-10-02": 0,
                                    "2026-10-03": 900, "2026-10-04": 1800})

    def test_separate_notices_and_directional_notice(self):
        record = self.forecast([{"event_kind": "rain", "direction": "ALL", "nights": ["2026-10-01"]},
                                {"event_kind": "rain", "direction": "ALL", "nights": ["2026-10-03"]},
                                {"event_kind": "storm", "direction": "NE",
                                 "nights": ["2026-10-01", "2026-10-02", "2026-10-03"]}])
        model = ForecastCapacity(self.nights, closing_kinds=("rain", "storm"))
        self.ingest(model, record)
        self.assertEqual(model.summary(self.start)["conditional_closed_nights"], [])
        self.assertTrue(all(n["unexcluded_seconds"] == 1800 for n in model.summary(self.start)["nights"]))

    def test_unpublished_expired_and_repeated_latest(self):
        future = self.forecast([], issued=self.start + timedelta(days=2))
        model = ForecastCapacity(self.nights)
        self.assertEqual(self.ingest(model, future)["unpublished_ignored"], 2)
        first = self.forecast([], end=self.start + timedelta(days=2))
        self.ingest(model, first)
        at_end = model.summary(self.start + timedelta(days=2))
        self.assertTrue(all(n["forecast_covered_seconds"] == 0 for n in at_end["nights"]))
        self.assertEqual(self.ingest(model, first, now=self.start + timedelta(days=3))["duplicates"], 2)
        next_record = self.forecast([], issued=self.start + timedelta(days=3))
        self.ingest(model, next_record, now=self.start + timedelta(days=3))
        self.assertEqual(len(model.records), 2)
        self.assertEqual(model.summary(self.start + timedelta(days=3))["nights"][0]["no_forecastable_event_seconds"], 1800)

    def test_coverage_clipping_and_invalid_gap(self):
        end = self.start + timedelta(days=2, minutes=7, seconds=30)
        record = self.forecast([{"event_kind": "rain", "direction": "ALL",
                                 "nights": ["2026-10-01", "2026-10-02", "2026-10-03"]}], end=end)
        model = ForecastCapacity(self.nights, closing_kinds=("rain",))
        self.ingest(model, record)
        self.assertEqual(model.summary(self.start)["nights"][2]["conditional_closed_seconds"], 450)
        gap = self.forecast([{"event_kind": "rain", "direction": "ALL",
                              "nights": ["2026-10-01", "2026-10-03"]}])
        self.assertEqual(self.ingest(ForecastCapacity(self.nights), gap)["invalid"], 2)

    def test_exhaustive_all_slot_aligned_event_spans(self):
        slots = [(self.start + timedelta(days=k, minutes=15*j),
                  self.start + timedelta(days=k, minutes=15*(j+1)), self.nights[k]["night_date"])
                 for k in range(4) for j in range(2)]
        checked = 0
        for first in range(len(slots)):
            for last in range(first, len(slots)):
                a, b = slots[first][0], slots[last][1]
                dates = sorted({d for c, e, d in slots if c < b and e > a})
                record = self.forecast([{"event_kind": "rain", "direction": "ALL", "nights": dates}])
                model = ForecastCapacity(self.nights, closing_kinds=("rain",))
                self.ingest(model, record)
                for c, e in model.events[0]["guaranteed"]:
                    self.assertLessEqual(a.timestamp(), c)
                    self.assertGreaterEqual(b.timestamp(), e)
                checked += 1
        self.assertEqual(checked, 36)

    def test_uniform_boundary_model_matches_enumeration(self):
        for n in range(1, 8):
            spans = [(a, b) for a in range(n) for b in range(a, n)]
            exact = [sum(a <= j <= b for a, b in spans) / len(spans) for j in range(n)]
            self.assertEqual(uniform_boundary_occupancy(n, position="only"), exact)


if __name__ == "__main__":
    unittest.main()
