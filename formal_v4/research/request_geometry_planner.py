"""Native geometry as the scientific baseline of the existing request policy."""
from __future__ import annotations

import time

from .candidate_geometry_sweep import CandidateGeometryPlanner
from .request_exact_cache import ExactRequestCacheMixin
from .request_remote_planner import RequestRemotePlanner


class GeometryCachedRequestPlanner(ExactRequestCacheMixin, RequestRemotePlanner):
    """Keep request columns, DP, terrain evidence and feedback in their owners.

    Composition avoids routing CandidateGeometryPlanner.super().choose back
    through RequestDeadlineMixin.  The geometry engine owns no score ledger.
    """

    def __init__(self, initial):
        super().__init__(initial)
        self.geometry_engine = CandidateGeometryPlanner(initial)
        if self.geometry_engine.ids != self.ids:
            raise ValueError("Geometry and request catalog orders differ")

    def _choose_baseline(self, snapshot, best_scores, best_factors, env, active_requests):
        if self.distributed_transport is not None and self.distributed_transport.enabled:
            raise ValueError("This integration requires the disabled transport")
        engine = self.geometry_engine
        old_tmax = engine.tmax
        started = time.perf_counter()
        if self.tmax < self._distributed_normal_tmax:
            self.distributed_counts["forced_cpu_crops"] += 1
        engine.tmax = self.tmax
        engine.stats = {}
        engine.last_prediction = {}
        try:
            action = engine.choose(snapshot, best_scores, best_factors, env, active_requests)
            self.last_prediction = dict(engine.last_prediction) if action else {}
            self.stats = dict(engine.stats)
            return action
        finally:
            engine.tmax = old_tmax
            elapsed = time.perf_counter() - started
            self.distributed_counts["cpu_baselines"] += 1
            self.distributed_counts["cpu_baseline_seconds"] += elapsed
            if self.distributed_budget is not None:
                self.distributed_budget.record_cpu(elapsed)
