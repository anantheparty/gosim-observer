"""Actual public cached graph with the candidate's original-actor adapter."""
import os,sys,time,json,copy
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/'baseline_package'))
from sparse_exact import install
install()
import numpy as np
from public_states import states
from shared_graph import SharedGraph,Budget,rss
from continuation_controller import ContinuationController,make_policy
from run_actual import dump,shaobj
import wrapper
def main():
 actor,snapshot,env,meta=next(states('L2',[7]));p=actor.planner;c=ContinuationController(actor)
 prior=ROOT/'time_dp'/'L2_night08';c.graph=SharedGraph.load(prior/'SHARED_PUBLIC_GRAPH.npz',actor,snapshot,Budget(30,1536))
 expected=json.loads((prior/'RESULT.json').read_text())['baseline_action'];scores=actor.scores.copy();factors=actor.factor_lower.copy()
 t=time.perf_counter();result=c.choose(copy.deepcopy(snapshot),actor.scores,actor.factor_lower,copy.deepcopy(env),snapshot['active_requests']);elapsed=time.perf_counter()-t
 assert np.array_equal(scores,actor.scores) and np.array_equal(factors,actor.factor_lower)
 assert result['action']=='observe';assert len(result['assignments'])==len(set(result['assignments'].values()))
 assert 0<=result['pointing']['alt_deg']<=90 and 0<=result['pointing']['az_deg']<360
 assert p.tmin<=result['duration_seconds']<=p.tmax
 protected_req=c.protected(expected,actor.factor_lower,{**snapshot,'active_requests':[{'request_id':'PUBLIC_TEST'}]})
 assert protected_req
 required_ids=np.flatnonzero(p.required)
 factor_test=np.ones(p.n);factor_test[required_ids[0]]=0
 required_action={**expected,'assignments':{'0':p.ids[int(required_ids[0])]}}
 assert c.protected(required_action,factor_test,snapshot)
 assert issubclass(make_policy(wrapper.wrapped),wrapper.wrapped)
 r=dict(scope='reconstructed actual L2night8 public adapter state, cached same-public graph; no historical action parity or official execution claim',
  passed=True,elapsed_seconds=elapsed,extra_seconds=c.extra_seconds,peak_rss_bytes=rss(),events=c.events,
  selected_action=result,selected_matches_original_fixture=shaobj(result)==shaobj(expected),score_and_factor_ledger_unchanged=True,
  request_guard=True,required_assignment_guard=True,original_fault_class_inherited=True,physical_bank_reused=True)
 dump(ROOT/'ADAPTER_AUDIT.json',r);print(json.dumps({k:v for k,v in r.items() if k not in ('events','selected_action')}))
 # A later real public state has no unfinished required target in its original
 # B action, so it exercises the expensive adapter rather than only the guard.
 actor,snapshot,env,meta=next(states('L2',[17]));p=actor.planner;c=ContinuationController(actor)
 c.graph=SharedGraph.load(prior/'SHARED_PUBLIC_GRAPH.npz',actor,snapshot,Budget(30,1536))
 expected=p.choose(copy.deepcopy(snapshot),actor.scores,actor.factor_lower,copy.deepcopy(env),snapshot['active_requests'])
 scores=actor.scores.copy();factors=actor.factor_lower.copy();assert not c.protected(expected,factors,snapshot)
 t=time.perf_counter();result=c.choose(copy.deepcopy(snapshot),actor.scores,actor.factor_lower,copy.deepcopy(env),snapshot['active_requests']);elapsed=time.perf_counter()-t
 assert np.array_equal(scores,actor.scores) and np.array_equal(factors,actor.factor_lower)
 assert result['action']=='observe' and len(result['assignments'])==len(set(result['assignments'].values()))
 r=dict(scope='actual reconstructed public L2night18 with night8 physical bank frozen from earlier public data; no action parity or official execution claim',
  passed=True,elapsed_seconds=elapsed,extra_seconds=c.extra_seconds,peak_rss_bytes=rss(),events=c.events,meta=meta,
  selected_action=result,baseline_action=expected,selected_matches_original_same_state=shaobj(result)==shaobj(expected),
  ledger_unchanged=True,original_request_and_fault_class_inherited=True)
 dump(ROOT/'ADAPTER_AUDIT_L2_N18.json',r);print(json.dumps({k:v for k,v in r.items() if k not in ('events','selected_action','baseline_action','meta')}))
if __name__=='__main__':main()
