"""Direct GPU request-DP backend; shared model is CPU-only."""
from .request_deadline_common import RequestDeadlineMixin
from .gpu_phase_candidates import PhaseGPUSpatialPlanner

class RequestDPPlanner(RequestDeadlineMixin,PhaseGPUSpatialPlanner):
    pass
