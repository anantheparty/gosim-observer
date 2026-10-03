"""One predeclared program-only intervention, then genuine strong-policy replanning."""
import hashlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
import policy
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner

PLAN = json.loads(Path(__file__).with_name("objective_graph_program_plan.json").read_text())
CASE = os.environ.get("OBJECTIVE_GRAPH_CASE", "control")
policy.SpatialPlanner = CPUPhaseSpatialPlanner
BasePolicy = policy.Policy


class ProgramProbePolicy(BasePolicy):
    def __init__(self, initial):
        super().__init__(initial)
        self.probe_prefix = hashlib.sha256()
        self.probe_done = False
        self.probe_post_feedback = False
        self.probe_capture = None

    def decide(self, snapshot):
        action = super().decide(snapshot)
        rank = snapshot["observe_action_index"]
        if action.get("action") == "observe" and rank == PLAN["rank"] and not self.probe_done:
            assert self.probe_prefix.hexdigest() == PLAN["prefix_sha256"], "original-prefix hash mismatch"
            assert action == PLAN["action"], "source changed predeclared exposure"
            self.probe_capture = dict(event="program_probe_intervention", case=CASE, rank=rank,
                                      now_utc=snapshot["now_utc"], prefix_sha256=self.probe_prefix.hexdigest(),
                                      action=action, factor_lower=float(self.factor_lower[self.planner.index[PLAN["target"]]]),
                                      scores_sum=float(self.scores.sum()), C=float(self.C), E=float(self.E))
            print(json.dumps(self.probe_capture), file=sys.stderr, flush=True)
            if CASE == "backup":
                action = {**action, "program": "BACKUP"}
                self.pending["action"] = action
            self.probe_done = True
        result = snapshot.get("last_result") or {}
        if (self.probe_done and not self.probe_post_feedback and result.get("action") == "observe"
                and result.get("observe_index") == PLAN["rank"]):
            i = self.planner.index[PLAN["target"]]
            print(json.dumps(dict(event="program_probe_post_feedback", case=CASE, rank=rank,
                                   target=PLAN["target"], factor_lower=float(self.factor_lower[i]),
                                   fitted_factor=float(self.factors[i]), score=float(self.scores[i]),
                                   C=float(self.C), E=float(self.E))), file=sys.stderr, flush=True)
            self.probe_post_feedback = True
        self.probe_prefix.update((json.dumps(action, sort_keys=True, separators=(",", ":")) + "\n").encode())
        return action

    def summary(self):
        return {**super().summary(), "probe_case": CASE, "probe_done": self.probe_done,
                "probe_post_feedback": self.probe_post_feedback, "probe_capture": self.probe_capture,
                "cpu_phase": self.planner.cpu_phase_summary}


policy.Policy = ProgramProbePolicy
from agent import main
if __name__ == "__main__":
    main()
