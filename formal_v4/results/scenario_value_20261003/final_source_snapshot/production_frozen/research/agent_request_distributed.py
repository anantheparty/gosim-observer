#!/usr/bin/env python3
"""Independent supported API baseline + local published-future request entry."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')

# Reuse the already guarded optional transport and ModelRemoteBudget classes.
# This import binds that entry in this process; the final binding below installs
# the independent candidate class in both modules, including agent's cached name.
from research import agent_model_gpu as model_entry
import policy
import agent
from research.request_remote_planner import RequestRemotePlanner,DisabledRemoteFacade,PlannerBudgetFacade
from research.terrain_policy import install_terrain_policy

policy.SpatialPlanner=RequestRemotePlanner
TerrainBase=install_terrain_policy(model_entry.ModelGPUPolicy)


class DistributedRequestPolicy(TerrainBase):
    def __init__(self,initial):
        super().__init__(initial)
        self.config.setdefault('request_dp_future_field_mode','published')
        self.planner.attach_transport(self.remote,self.remote_budget)
        if self.remote is not None:self.remote=DisabledRemoteFacade(self.remote)
        self.remote_budget=PlannerBudgetFacade(self.remote_budget)

    def summary(self):
        return {**super().summary(),'request_dp':self.planner.request_dp_summary(),
                'distributed_request':self.planner.distributed_summary()}


policy.Policy=DistributedRequestPolicy
agent.Policy=DistributedRequestPolicy
if __name__=='__main__':agent.main()
