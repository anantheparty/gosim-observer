"""Deployment never turns the training max-two-fault prior into protocol law."""
import json,sys,copy
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'candidate_package'))
from report_policy import make_policy_class
from research.agent_request_exact_cache import ExactCachedRequestPolicy
from research.geometry import parse_utc
initial=json.loads((ROOT.parents[2]/'formal_v4/results/policy_iteration_20261004/L1_initialize_public.json').read_text())
actor=make_policy_class(ExactCachedRequestPolicy)(initial);g=actor.persistent_guard;g.correct=2;actor.pending={}
def forbidden(*args):raise AssertionError('NN/DP queried outside max-two training domain')
g.model=SimpleNamespace(posterior=forbidden);g.dp=SimpleNamespace(delta=forbidden)
action=dict(action='observe',pointing=dict(alt_deg=70.,az_deg=90.),duration_seconds=60,program='DARK',assignments={'0':'V4T000001'})
snapshot=dict(now_utc=initial['survey']['start_utc'],observe_action_index=0,last_result=None,new_messages=[],wallclock=dict(remaining_seconds=900))
g.evidence=lambda s:dict(qualified=False)
assert g.propose(snapshot,action,analytical=True)==action
g.evidence=lambda s:dict(qualified=True,median_ratio_upper=.2)
assert g.propose(snapshot,action,analytical=True)=={'action':'report'}
assert g.insert_reason=='faultv1' and g.cached==action
out=dict(passed=True,public_correct_count_ge2_excludes_NN_and_DP=True,faultv1_still_can_report_future_third_fault=True,training_max2_prior_not_protocol_guarantee=True,actor_source_or_model_unchanged=True)
(ROOT/'count2_fallback_checks.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
