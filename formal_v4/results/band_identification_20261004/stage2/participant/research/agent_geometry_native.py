"""Separate participant entry for the native geometry candidate release."""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import policy
from research.geometry_native import load_library
from research.candidate_geometry_sweep import CandidateGeometryPlanner

load_library()
mode = os.environ.get("GEOMETRY_NATIVE_PLANNER", "sweep")
if mode == "union":
    from research.candidate_geometry_union import CandidateGeometryUnionPlanner
    policy.SpatialPlanner = CandidateGeometryUnionPlanner
elif mode == "sweep":
    policy.SpatialPlanner = CandidateGeometryPlanner
else:
    raise ValueError("Unknown native geometry planner: " + mode)

from agent import main

if __name__ == "__main__":
    main()
