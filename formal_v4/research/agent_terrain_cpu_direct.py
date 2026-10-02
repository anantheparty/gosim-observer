#!/usr/bin/env python3
"""Independent CPU phase candidate with shared online terrain version space."""
import os
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import policy
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
from research.terrain_policy import install_terrain_policy
if Path(policy.__file__).with_name('remote_runtime.json').exists():
    raise ValueError('terrain CPU gate requires isolated project without RPC config')
policy.SpatialPlanner=CPUPhaseSpatialPlanner
Base=policy.Policy
TerrainPolicy=install_terrain_policy(Base)
class Candidate(TerrainPolicy):
    def summary(self):
        return {**super().summary(),'cpu_phase':self.planner.cpu_phase_summary}
policy.Policy=Candidate
from agent import main
if __name__=='__main__':main()
