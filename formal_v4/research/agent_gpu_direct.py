#!/usr/bin/env python3
"""Local complete-card harness: retain the frozen policy, replace search backend."""
import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import policy
from research.gpu_spatial_candidates import GPUSpatialPlanner
policy.SpatialPlanner = GPUSpatialPlanner
from agent import main

if __name__ == "__main__":
    main()
