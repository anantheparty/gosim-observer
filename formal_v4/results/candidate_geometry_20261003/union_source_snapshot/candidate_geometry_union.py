"""Preserve the full existing CPUPhase baseline, then add weighted sweep."""
import numpy as np
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
from research.candidate_geometry_sweep import CandidateGeometryPlanner, PROGRAMS


class CandidateGeometryUnionPlanner(CandidateGeometryPlanner):
    def __init__(self,initial):
        super().__init__(initial)
        self.phase=CPUPhaseSpatialPlanner(initial)

    def _base_choose(self,snapshot,scores,factors,env,active_requests):
        base=self.phase.choose(snapshot,scores,factors,env,active_requests)
        self.frame=self.phase._cpu_phase_frame
        self.baseline_candidates=list(self.phase._cpu_phase_baseline_candidates)
        self.last_prediction=dict(self.phase.last_prediction)
        self.stats=dict(self.phase.stats)
        if base is not None and self.frame is not None:
            oa=float(env.get('pointing_offset_alt_deg',0.));oz=float(env.get('pointing_offset_az_deg',0.))
            center=(base['pointing']['alt_deg']+oa,(base['pointing']['az_deg']+oz)%360)
            fibers=np.asarray([int(f) for f in base['assignments']],dtype=int)
            chosen=np.asarray([self.index[t] for t in base['assignments'].values()],dtype=int)
            rate=float(self.phase.stats['selected_exact_rate'])
            self.baseline_candidates.append((rate,center,int(base['duration_seconds']),PROGRAMS.index(base['program']),chosen,fibers))
        return base
