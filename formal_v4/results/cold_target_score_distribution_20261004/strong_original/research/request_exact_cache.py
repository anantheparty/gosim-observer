"""Research-only exact memoization of repeated finite request computations.

The search family, integration cuts, summation order and tie order are retained.
This module does not replace a production planner or package entry point.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import timedelta
import math

import numpy as np

from .request_deadline_common import RequestDeadlineMixin, _SciencePricePlanner
from .cpu_phase_candidates import CPUPhaseSpatialPlanner


class _ExactCachedSciencePricePlanner(_SciencePricePlanner):
    """One-epoch reuse inside successive fixed-duration science searches."""

    def _altaz(self, lst):
        cached = getattr(self, "_exact_altaz_cache", None)
        if cached is None or cached[0] != lst:
            cached = (lst, super()._altaz(lst))
            self._exact_altaz_cache = cached
        return cached[1]

    def _public_quality(self, now, lst, alt):
        # Only reuse when the very same cached geometry was supplied. A caller
        # with another altitude array receives the original computation.
        geometry = getattr(self, "_exact_altaz_cache", None)
        if geometry is None or geometry[0] != lst or alt is not geometry[1][0]:
            return super()._public_quality(now, lst, alt)
        cached = getattr(self, "_exact_public_cache", None)
        if cached is None or cached[0] != now or cached[1] != lst:
            cached = (now, lst, super()._public_quality(now, lst, alt))
            self._exact_public_cache = cached
        return cached[2]


class ExactRequestCacheMixin:
    """Reuse immutable midpoint arrays only inside one synchronous build/start.

    At most 16 MiB is added by the midpoint cache. This is not a prefix-sum
    integration: each duration still adds its original pieces in original order.
    Geometry, quality model and public evidence are fixed in each build. A new
    start or a new build dictionary drops every midpoint entry.
    """

    _exact_cache_limit_bytes = 16 * 1024 * 1024

    def __init__(self, initial):
        super().__init__(initial)
        self._price_planner = _ExactCachedSciencePricePlanner(initial)
        self.exact_cache_stats = {"midpoint_hits": 0, "midpoint_misses": 0,
                                  "midpoint_peak_bytes": 0}
        self._exact_midpoints = OrderedDict()
        self._exact_midpoint_scope = None
        self._exact_midpoint_bytes = 0
        self._exact_build_serial = 0

    def _build_pool(self, *args, **kwargs):
        self._exact_build_serial += 1
        self._price_planner._exact_altaz_cache = None
        self._price_planner._exact_public_cache = None
        try:
            return super()._build_pool(*args, **kwargs)
        finally:
            self._exact_midpoints.clear()
            self._exact_midpoint_scope = None
            self._exact_midpoint_bytes = 0
            self._price_planner._exact_altaz_cache = None
            self._price_planner._exact_public_cache = None

    def _integrated_public_quality(self, start, duration, idx, field=None):
        # Preserve the general subset/execution path. During a build the
        # existing duration cache always requests the full catalogue in order.
        idx = np.asarray(idx)
        if (self._build_quality is None or len(idx) != self.n or
                not np.array_equal(idx, np.arange(self.n))):
            return super()._integrated_public_quality(start, duration, idx, field)
        scope = (self._exact_build_serial, start, id(self._active_future_field))
        if self._exact_midpoint_scope != scope:
            self._exact_midpoints.clear()
            self._exact_midpoint_bytes = 0
            self._exact_midpoint_scope = scope
        night = next(k for k, (a, b) in enumerate(self.nights) if a <= start < b)
        anchor = self.nights[night][0]
        end = start + timedelta(seconds=duration)
        cursor, total = start, np.zeros(len(idx))
        slot_seconds = int(self.init["survey"].get("slot_seconds", 900))
        while cursor < end:
            slot = math.floor((cursor-anchor).total_seconds()/slot_seconds)
            segment_end = min(end, anchor+timedelta(seconds=(slot+1)*slot_seconds))
            while cursor < segment_end:
                piece_end = min(segment_end, cursor+timedelta(seconds=120))
                moment = cursor+(piece_end-cursor)/2
                public_key = (moment, None)
                value = self._exact_midpoints.get(public_key)
                if value is None:
                    self.exact_cache_stats["midpoint_misses"] += 1
                    value = self._subset_public_quality(moment, idx)
                    self._remember_exact_midpoint(public_key, value)
                else:
                    self.exact_cache_stats["midpoint_hits"] += 1
                if field is not None:
                    raw_key = (moment, id(field))
                    raw = self._exact_midpoints.get(raw_key)
                    if raw is None:
                        self.exact_cache_stats["midpoint_misses"] += 1
                        raw = value * field.raw_scale_at(moment, idx)
                        self._remember_exact_midpoint(raw_key, raw)
                    else:
                        self.exact_cache_stats["midpoint_hits"] += 1
                    value = raw
                total += (piece_end-cursor).total_seconds()*value
                cursor = piece_end
        return total/duration

    def _remember_exact_midpoint(self, key, value):
        size = value.nbytes
        if size > self._exact_cache_limit_bytes:
            return
        while self._exact_midpoint_bytes+size > self._exact_cache_limit_bytes:
            _, old = self._exact_midpoints.popitem(last=False)
            self._exact_midpoint_bytes -= old.nbytes
        self._exact_midpoints[key] = value
        self._exact_midpoint_bytes += size
        self.exact_cache_stats["midpoint_peak_bytes"] = max(
            self.exact_cache_stats["midpoint_peak_bytes"], self._exact_midpoint_bytes)


class ExactCachedRequestCPUPlanner(ExactRequestCacheMixin,
                                   RequestDeadlineMixin,
                                   CPUPhaseSpatialPlanner):
    pass
