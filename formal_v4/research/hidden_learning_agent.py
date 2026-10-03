"""Isolated matched-source baseline/critic protocol entry; NumPy and no LLM."""
import os,sys
from pathlib import Path
os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
os.environ.setdefault("OMP_NUM_THREADS","1")
os.environ.setdefault("MKL_NUM_THREADS","1")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import policy
from research.hidden_learning_policy import CandidateCriticPlanner
class Planner(CandidateCriticPlanner):
    def __init__(self,initial):
        super().__init__(initial)
        if os.environ.get("HIDDEN_LEARNING_MODE","baseline")=="critic":
            self.load_model(Path(__file__).with_name("hidden_learning_model.npz"))
            self.critic_margin=float(os.environ.get("HIDDEN_LEARNING_MARGIN","0"))
policy.SpatialPlanner=Planner
old=policy.Policy.summary
def summary(self):
    return {**old(self),"candidate_critic":{"calls":self.planner.critic_calls,"changes":self.planner.critic_changes,
        "seconds":self.planner.critic_seconds,"margin":self.planner.critic_margin}}
policy.Policy.summary=summary
from agent import main
if __name__=="__main__":main()
