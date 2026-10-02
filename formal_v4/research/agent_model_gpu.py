#!/usr/bin/env python3
"""Use the injected compatible API, with the gated CPU phase fallback."""
import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import policy
import remote_planner
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
from research.model_gpu_transport import ModelGPUTransport
from research.remote_budget import RemoteBudget


class OptionalModelGPUTransport(ModelGPUTransport):
    def __init__(self, initial, config=None):
        self.configuration_error = None
        try:
            super().__init__(initial, config)
        except ValueError as exc:
            self.configuration_error = type(exc).__name__
            self.enabled = False

    def check(self):
        if self.configuration_error:
            return {"remote_check": "unavailable", "transport": "official-compatible-api",
                    "exception": self.configuration_error}
        return super().check()


policy.SpatialPlanner = CPUPhaseSpatialPlanner
remote_planner.RemotePlanner = OptionalModelGPUTransport
old_summary = policy.Policy.summary


def summary(self):
    value = {**old_summary(self), "cpu_phase": self.planner.cpu_phase_summary}
    if self.remote:
        value["compatible_api"] = {"chat_calls": self.remote.rpc_calls,
                                   "chat_seconds": self.remote.rpc_seconds}
    return value


policy.Policy.summary = summary


class ModelRemoteBudget(RemoteBudget):
    """Setup consumes the clock once; forecast only recurring decision cost."""
    def __init__(self, transport, **kwargs):
        super().__init__(remote_default=4., timeout_seconds=10., **kwargs)
        self.transport = transport
        self.initialization_seconds = 0.
        self.observed_remote_seconds = 0.
        self.failed_initializations = 0

    def allow(self, remaining_seconds, remaining_decisions):
        if self.transport is not None and getattr(self.transport, "session", None) is None:
            config = getattr(self.transport, "config", {})
            setup_limit = max(0., float(config.get("initialize_timeout_seconds", 25)))
            decision_limit = max(self.timeout, float(config.get("timeout_seconds", self.timeout)))
            if float(remaining_seconds) <= self.reserve + setup_limit + decision_limit:
                self.skipped += 1
                self.last = {"reason": "initialization_budget", "completion_reserve": self.reserve,
                             "initialization_timeout_seconds": setup_limit,
                             "decision_timeout_seconds": decision_limit}
                return False
        return super().allow(remaining_seconds, remaining_decisions)

    def record_remote(self, seconds):
        setup = getattr(self.transport, "last_initialization_seconds", 0.)
        self.initialization_seconds += setup
        self.observed_remote_seconds += max(0., float(seconds))
        decision = getattr(self.transport, "last_decision_seconds", seconds)
        if getattr(self.transport, "last_failure_kind", None) == "initialize":
            # Setup is still required on retry. Forecast at least the full failed
            # attempt; a zero decision sample would hide that real failure cost.
            decision = max(float(seconds), setup, decision)
            self.failed_initializations += 1
        else:
            decision = max(decision, max(0., float(seconds) - setup))
        super().record_remote(decision)

    def summary(self):
        return {**super().summary(), "initialization_seconds": round(self.initialization_seconds, 3),
                "observed_remote_seconds": round(self.observed_remote_seconds, 3),
                "failed_initializations": self.failed_initializations}


class ModelGPUPolicy(policy.Policy):
    def __init__(self, initial):
        super().__init__(initial)
        self.remote_budget = ModelRemoteBudget(self.remote,
            cpu_default=float(self.config["planning_budget_seconds"]) + .04)


policy.Policy = ModelGPUPolicy
from agent import main

if __name__ == "__main__":
    main()
