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
from agent import main

if __name__ == "__main__":
    main()
