"""CPU-only complete-deadline request DP over the bounded phase planner."""
from .request_deadline_common import RequestDeadlineMixin
from .cpu_phase_candidates import CPUPhaseSpatialPlanner

class RequestCPUDeadlinePlanner(RequestDeadlineMixin,CPUPhaseSpatialPlanner):
    pass
