#!/usr/bin/env python3
"""Frozen complete-card entry; policy config selects phase or bypass mode."""
import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import policy
from research.gpu_phase_candidates import PhaseGPUSpatialPlanner
policy.SpatialPlanner = PhaseGPUSpatialPlanner
from agent import main

if __name__ == "__main__":
    main()
