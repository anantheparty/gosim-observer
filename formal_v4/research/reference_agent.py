#!/usr/bin/env python3
"""Local deterministic reference for the v4 public practice cards.

Reuse the official numerical anchor-search, geometry, state update, and action
validation. Forecast advice is a structured rule; instrument reports use the
official quality-drop statistic and only the public free-report allowance.
This entry point deliberately depends on the adjacent upstream checkout.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sys

UPSTREAM_PYTHON = Path(__file__).resolve().parents[1] / "upstream" / "gosim-observer-examples" / "python"
sys.path.insert(0, str(UPSTREAM_PYTHON))

from agent_core.planner import (  # noqa: E402
    DIRECTION_AZ,
    MAX_REPORTS,
    REPORT_CONFIRMATIONS,
    REPORT_DROP,
    REPORT_SPACING_HOURS,
    Planner,
)
from agent_core.protocol import log, read_messages, send_response  # noqa: E402
from agent_core.state import SurveyState  # noqa: E402
from agent_core.validation import ActionRejected, fallback_action, validate_action  # noqa: E402


class NullTrace:
    def write(self, record: dict) -> None:
        pass

    def close(self) -> None:
        pass


class ReferencePlanner(Planner):
    def __init__(self, state: SurveyState, log=log):
        self.state = state
        self.log = log
        self.grid = state.fiber_grid
        self.trace = NullTrace()
        self.observe_count = 0
        self.reports = 0
        self.last_report_hours = float("-inf")
        self.suspicion_hours: list[float] = []
        self.night_index_seen: int | None = None
        self.consecutive_reports = 0
        self._last_forecast_notices: list = []
        self.total_assigned = 0
        self.total_hit = 0
        log(f"reference: {len(state.ids)} targets ({sum(state.required)} required), "
            f"{len(state.nights)} nights")

    def _night_advice(self, night_start, payload: dict) -> None:
        night_date = (night_start - timedelta(hours=12)).date().isoformat()
        tonight = [notice for notice in self._last_forecast_notices
                   if night_date in (notice.get("nights") or [])]
        bulletin = (payload.get("latest_bulletin") or {}).get("notices", [])
        self.state.extra_avoid = {
            str(notice.get("direction", "")).upper()
            for notice in tonight + bulletin
            if str(notice.get("direction", "")).upper() in DIRECTION_AZ
        }
        # A coarse forecast does not determine exposure quality. The numerical
        # planner estimates quality from measured hits and its public sky model.
        self.state.duration_scale = 1.0
        self.log(f"reference: night {night_date} avoid={sorted(self.state.extra_avoid)}")

    def _maybe_report(self, hours: float, payload: dict):
        state = self.state
        state.force_program = None
        report_cap = min(MAX_REPORTS, state.false_report_free_allowance)
        if self.reports >= report_cap or hours - self.last_report_hours < 24.0:
            return None
        evidence = state.fault_evidence()
        threshold = REPORT_DROP if self.reports == 0 else REPORT_DROP - 0.07
        if evidence is None or evidence.drop >= threshold:
            self.suspicion_hours = []
            return None
        if evidence.dark_checks < 6:
            state.force_program = "DARK"
        elif evidence.dark_matched < 0.5 * evidence.dark_checks:
            self.suspicion_hours = []
            return None
        if self.suspicion_hours and hours - self.suspicion_hours[-1] < REPORT_SPACING_HOURS:
            return None
        self.suspicion_hours.append(hours)
        if len(self.suspicion_hours) < REPORT_CONFIRMATIONS:
            return None
        self.suspicion_hours = []
        self.reports += 1
        self.last_report_hours = hours
        state.forget_quality_history()
        self.log(f"reference: reporting at {payload.get('now_utc')} evidence={evidence}")
        return {"action": "report",
                "reason": f"quality dropped to {evidence.drop:.0%} of the earlier level",
                "decision_source": "rule"}

    def on_finish(self, payload: dict) -> None:
        self.log(f"reference: finished termination_reason={payload.get('termination_reason')} "
                 f"observes={self.observe_count} reports={self.reports}")


def main() -> int:
    state = None
    planner = None
    for message in read_messages(sys.stdin):
        kind = message.get("message_type")
        if kind == "initialize":
            state = SurveyState(message["payload"])
            planner = ReferencePlanner(state)
        elif kind == "decision_request":
            sequence = message["decision_sequence"]
            consecutive_reports = planner.consecutive_reports if planner else 0
            try:
                action = planner.decide(message["payload"]) if planner else fallback_action("not initialized")
                action = validate_action(action, state, consecutive_reports)
            except ActionRejected as exc:
                log(f"reference: invalid action ({exc}); falling back")
                action = fallback_action("validation-rejected")
            except Exception as exc:
                log(f"reference: planner error ({type(exc).__name__}: {exc}); falling back")
                action = fallback_action("planner-exception")
            if planner:
                planner.note_action(action)
            send_response(sequence, action)
        elif kind == "finish" and planner:
            planner.on_finish(message.get("payload", {}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
