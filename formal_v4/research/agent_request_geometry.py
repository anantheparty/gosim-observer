"""Public JSONL entry combining the frozen request policy and native geometry."""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

from research import agent_request_exact_cache as frozen_entry
from research.geometry_native import load_library
from research.request_geometry_planner import GeometryCachedRequestPlanner
import agent
import policy

load_library()

# The frozen policy validates this factory at initialization.  Both bindings
# refer to the new factory before any initialize message is consumed.
frozen_entry.ExactCachedRequestRemotePlanner = GeometryCachedRequestPlanner
policy.SpatialPlanner = GeometryCachedRequestPlanner


class GeometryRequestPolicy(frozen_entry.ExactCachedRequestPolicy):
    def summary(self):
        return {
            **super().summary(),
            "native_geometry": dict(self.planner.geometry_engine.geometry_summary),
            "request_geometry_integration": "native-baseline-preserved-request-terrain",
        }


policy.Policy = GeometryRequestPolicy
agent.Policy = GeometryRequestPolicy

if __name__ == "__main__":
    agent.main()
