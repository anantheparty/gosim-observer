"""Isolated strong CPUPhase control using the identical frozen controller."""
import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
import policy
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
policy.SpatialPlanner = CPUPhaseSpatialPlanner
from agent import main
if __name__ == "__main__":
    main()
