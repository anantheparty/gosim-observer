"""Frozen RequestCache plus public joint quality distribution adapter."""
from research import agent_request_exact_cache as frozen_entry
from research.predictive_policy import install_predictive_policy
import agent
import policy
PredictivePolicy=install_predictive_policy(frozen_entry.ExactCachedRequestPolicy)
policy.Policy=PredictivePolicy
agent.Policy=PredictivePolicy
if __name__=='__main__':agent.main()
