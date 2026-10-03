#!/usr/bin/env python3
"""Independent phase-search RPC process; default port 19929.

Only this process changes the planner binding. The baseline service and its
source files remain independent. Deployment supplies its scoped token file.
"""
import os
import sys
import hashlib
import json

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from research.gpu_phase_candidates import PhaseGPUSpatialPlanner
import research.gpu_spatial_candidates as gpu_backend

PHASE_GATE_DEFAULTS = {
    'gpu_anchor_count': 1024,
    'gpu_max_candidates': 32768,
    'gpu_refine_count': 64,
    'gpu_refine_budget_seconds': .3,
    'gpu_fixed_workload': True,
    'gpu_exact_candidate_count': 256,
    'gpu_refinement_steps': 32,
    'gpu_emergency_seconds': 3.,
    'gpu_phase_top_count': 16,
    'gpu_phase_local_target_count': 24,
    'gpu_phase_exact_count': 64,
    'gpu_phase_emergency_seconds': 3.,
    'gpu_phase_mode': 'phase',
}
PHASE_GATE_DEFAULTS_SHA256 = hashlib.sha256(
    json.dumps(PHASE_GATE_DEFAULTS, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class PhaseServicePlanner(PhaseGPUSpatialPlanner):
    """Recorded gate defaults for missing keys; explicit client keys prevail."""

    def choose(self, snapshot, best_scores, best_factors, env_estimate=None, active_requests=None):
        supplied = dict(env_estimate or {})
        env = {**PHASE_GATE_DEFAULTS, **supplied}
        action = super().choose(snapshot, best_scores, best_factors, env, active_requests)
        self.stats.update(service_gate_defaults_sha256=PHASE_GATE_DEFAULTS_SHA256,
                          service_gate_default_keys=sorted(set(PHASE_GATE_DEFAULTS)-set(supplied)))
        return action


# PhaseGPUSpatialPlanner has already inherited the original baseline class.
# The existing server's initialize import now resolves this process-local class.
gpu_backend.GPUSpatialPlanner = PhaseServicePlanner
import gpu_rpc_server


class PhaseHandler(gpu_rpc_server.Handler):
    def reply(self, code, value):
        if code == 200 and self.path == '/health':
            value = {**value, 'planner': 'PhaseServicePlanner',
                     'phase_gate_defaults': PHASE_GATE_DEFAULTS,
                     'phase_gate_defaults_sha256': PHASE_GATE_DEFAULTS_SHA256}
        return super().reply(code, value)


gpu_rpc_server.Handler = PhaseHandler

if __name__ == "__main__":
    if not any(arg == "--port" or arg.startswith("--port=") for arg in sys.argv):
        sys.argv.extend(["--port", "19929"])
    gpu_rpc_server.main()
