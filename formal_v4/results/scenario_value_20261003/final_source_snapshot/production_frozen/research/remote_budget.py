"""Allocate optional accelerator calls while reserving local completion time.

The forecast of remaining decisions is empirical, not a runtime guarantee.
At each decision, the optional-call allowance is the remaining wall clock minus
the local completion forecast and a fixed final reserve. A fractional quota
spreads that allowance across the rest of the survey rather than spending it
all at the beginning. Costs use the observed 90th percentile, not GPU kernel
time, because the official budget includes the complete network round trip.
"""
from __future__ import annotations

from collections import deque
import math


class RemoteBudget:
    def __init__(self, *, reserve_seconds=30., cpu_default=.26,
                 remote_default=1.2, timeout_seconds=3.):
        self.reserve = float(reserve_seconds)
        self.cpu_default = float(cpu_default)
        self.remote_default = float(remote_default)
        self.timeout = float(timeout_seconds)
        self.cpu_samples = deque(maxlen=64)
        self.remote_samples = deque(maxlen=64)
        self.credit = 0.
        self.accepted = 0
        self.skipped = 0
        self.last = {}

    @staticmethod
    def _cost(samples, default):
        if not samples:
            return default
        ordered = sorted(samples)
        return max(.001, ordered[min(len(ordered) - 1,
                                      math.ceil(.9 * len(ordered)) - 1)])

    def record_cpu(self, seconds):
        self.cpu_samples.append(max(0., float(seconds)))

    def record_remote(self, seconds):
        self.remote_samples.append(max(0., float(seconds)))

    def allow(self, remaining_seconds, remaining_decisions):
        wall = max(0., float(remaining_seconds))
        count = max(1., float(remaining_decisions))
        cpu = self._cost(self.cpu_samples, self.cpu_default)
        remote = self._cost(self.remote_samples, self.remote_default)
        extra = max(0., wall - self.reserve - count * cpu)
        # A remote action replaces a local search, so only its incremental
        # cost consumes the optional-search allowance.
        increment = max(.05, remote - cpu)
        fraction = min(1., extra / (count * increment))
        self.credit = min(1., self.credit + fraction)
        allowed = self.credit >= 1. - 1e-12 and wall > self.reserve + self.timeout
        if allowed:
            self.credit -= 1.
            self.accepted += 1
        else:
            self.skipped += 1
        self.last = {"fraction": round(fraction, 4), "cpu_p90": round(cpu, 4),
                     "remote_p90": round(remote, 4), "completion_reserve": self.reserve,
                     "estimated_remaining_decisions": round(count, 1)}
        return allowed

    def summary(self):
        return {"accepted": self.accepted, "skipped": self.skipped, **self.last}
