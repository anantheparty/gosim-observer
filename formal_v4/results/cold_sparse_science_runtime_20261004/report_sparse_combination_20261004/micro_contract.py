"""Report intervention contract on actual original or accelerated science actions."""
import os,sys,json,copy
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[name]='1'
sys.dont_write_bytecode=True
from pathlib import Path
from types import SimpleNamespace
import numpy as np
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(OUT/'candidate_package'))
accelerated='--accelerated' in sys.argv
if accelerated:import report_sparse_entry as entry
else:import report_entry as entry
effective_entry=entry.report_entry if accelerated else entry
from research import agent_request_exact_cache as exact_entry
from research import spatial_candidates as spatial,cpu_phase_candidates as phase
import report_policy as rp,report_support,report_core
from research.geometry import parse_utc
initial=json.loads((OUT/'initialize_public.json').read_text())
real=exact_entry.ExactCachedRequestPolicy(initial)
assert 'wrapper' not in sys.modules and 'persistent_fault_guard' not in sys.modules
assert effective_entry.agent.Policy is effective_entry.policy.Policy
actual=effective_entry.agent.Policy(initial)
assert type(actual.persistent_guard) is rp.SparseReportGuard
assert actual.persistent_guard.model is None and actual.persistent_guard.dp is None
assert report_support.PersistentFaultGuard is rp.SparseReportGuard
if accelerated:
 assert spatial.SpatialPlanner._evaluate.__module__=='sparse_evaluator'
 assert phase.coarse_numpy_local.__module__=='sparse_exact'
else:
 assert spatial.SpatialPlanner._evaluate.__module__=='research.spatial_candidates'

class Fixture:
 def __init__(self,initial):
  self.initial=initial;self.planner=real.planner;self.slot_seconds=900;self.pending=None
  self.C=.234;self.E=.432;self.belief_clock={'anchor':'preserve'};self.low_efficiency=[1];self.efficiency_witnesses=[2]
  self.scores=np.zeros(self.planner.n);self.factors=np.zeros(self.planner.n);self.factor_lower=np.zeros(self.planner.n)
  self.ledger=[{'valid':True}];self.false_since_correct=0;self.correct_reports=0;self.report_count=0;self.last_report=None;self.calls=0
  self.actions=[]
 def _night(self,now):return next((i for i,(a,b) in enumerate(self.planner.nights) if a<=now<b),-1)
 def decide(self,s):
  self.calls+=1
  if (s.get('last_result') or {}).get('action')=='report':
   assert self.pending['action']=={'action':'report'}
   if s['last_result']['correct']:self.E=.95;self.correct_reports+=1;self.false_since_correct=0
   else:raise AssertionError('A free false result must release the cached action without entering base decide')
  config=json.loads((OUT/'candidate_package/policy_config.json').read_text())
  env={**config,'quality_scale':.55*self.E/.432,'program_band_quality_scale':.55*self.E/.432/.95,'use_bulletin_directional_prior':False,'target_quality_scale':np.ones(self.planner.n)}
  action=self.planner._choose_baseline(s,self.scores,self.factors,env,[])
  assert action['action']=='observe' and len(action['assignments'])>0
  self.pending={'action':copy.deepcopy(action),'start':parse_utc(s['now_utc']),'prior_C':self.C,'prior_E':self.E,'prediction':copy.deepcopy(self.planner.last_prediction),'notices':[]}
  self.actions.append(copy.deepcopy(action));return action
 def summary(self):return {'calls':self.calls}

def same(a,b):
 if isinstance(a,np.ndarray):return isinstance(b,np.ndarray) and np.array_equal(a,b)
 if isinstance(a,dict):return isinstance(b,dict) and a.keys()==b.keys() and all(same(a[k],b[k]) for k in a)
 if isinstance(a,(list,tuple)):return type(a)==type(b) and len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
 return a==b

def snapshot():return {'now_utc':initial['survey']['start_utc'],'observe_action_index':0,'new_messages':[],'last_result':None,'wallclock':{'remaining_seconds':900}}
def make():
 a=rp.make_policy_class(Fixture)(initial);g=a.persistent_guard
 g.feature=lambda s,a:([0]*1568,.5,(0,0));g.model=SimpleNamespace(posterior=lambda x:.8);g.dp=SimpleNamespace(delta=lambda *args:2.)
 return a,snapshot()
def ack(s,correct):return {**s,'last_result':{'action':'report','correct':correct,'repaired':correct,'score_delta':100 if correct else 0},'new_messages':[{'record_type':'report_result','correct':correct}]}
def saved(a):return {k:copy.deepcopy(getattr(a,k)) for k in ('C','E','belief_clock','low_efficiency','efficiency_witnesses','ledger','scores','factors','factor_lower','last_report')}
a,s=make();assert a.decide(s)=={'action':'report'};assert a.persistent_guard.insert_reason=='sparse_dp'
before=saved(a);pending=copy.deepcopy(a.persistent_guard.saved_pending)
false_action=a.decide(ack(s,False));assert same(false_action,pending['action']) and same(a.pending,pending) and a.calls==1
assert same(saved(a),before) and a.false_since_correct==1 and a.persistent_guard.false_count==1
assert a.persistent_guard.model_queries==1
false_trace=a.actions[:]
a,s=make();assert a.decide(s)=={'action':'report'};old_pending=copy.deepcopy(a.persistent_guard.saved_pending)
true_action=a.decide(ack(s,True));assert a.calls==2 and a.E==.95 and a.correct_reports==1 and a.persistent_guard.correct==1
assert a.pending['action']==true_action and a.persistent_guard.cached is None and a.persistent_guard.false_count==0
true_trace=a.actions[:]
a,s=make();a.persistent_guard.false_count=1;assert a.decide(s)=={'action':'report'};assert a.persistent_guard.insert_reason=='sparse_dp'
assert a.persistent_guard.dp_features['quota']==1

ctor_calls=[]
def forbidden(*args,**kwargs):ctor_calls.append(1);raise AssertionError('NN/DP/feature requested outside model support')
old_model,old_dp=rp.ReportModel,rp.ReportDP;rp.ReportModel=forbidden;rp.ReportDP=forbidden
try:
 a=rp.make_policy_class(Fixture)(initial);g=a.persistent_guard;s=snapshot();g.false_count=2;g.feature=forbidden
 g.evidence=lambda s:{'qualified':False}
 quota0=a.decide(s);assert quota0['action']=='observe' and g.model is None and g.dp is None and g.model_queries==0
 a=rp.make_policy_class(Fixture)(initial);g=a.persistent_guard;s=snapshot();g.correct=2;a.correct_reports=2;g.feature=forbidden
 g.evidence=lambda s:{'qualified':False}
 count2_declined=a.decide(s);assert count2_declined['action']=='observe' and g.model is None and g.dp is None and g.model_queries==0
 g.latest_features={'qualified':True,'median_ratio_upper':.2};g.evidence=lambda s:g.latest_features
 assert a.decide(s)=={'action':'report'} and g.insert_reason=='faultv1' and g.correct==2
 count2_cached=copy.deepcopy(g.cached);assert g.model is None and g.dp is None
 before=saved(a);pending=copy.deepcopy(g.saved_pending)
 released=a.decide(ack(s,False));assert same(released,count2_cached) and same(a.pending,pending) and same(saved(a),before) and a.calls==2
 assert g.false_count==1 and g.negative_level==.2 and g.model_queries==0
 # Independent publicly-known count2 actor may still repair a third event.
 a=rp.make_policy_class(Fixture)(initial);g=a.persistent_guard;s=snapshot();g.correct=2;a.correct_reports=2;g.feature=forbidden
 g.latest_features={'qualified':True,'median_ratio_upper':.2};g.evidence=lambda s:g.latest_features
 assert a.decide(s)=={'action':'report'} and g.insert_reason=='faultv1'
 third=a.decide(ack(s,True));assert third['action']=='observe' and g.correct==3 and a.correct_reports==3 and a.calls==2
 assert g.model is None and g.dp is None and g.model_queries==0 and not ctor_calls
finally:rp.ReportModel,rp.ReportDP=old_model,old_dp
out={'passed':True,'accelerated':accelerated,'actual_science_actions_used':True,'false_exact_action_pending_and_C_E_clock_scores_factors_ledger_preserved':True,'false_does_not_replan':True,'true_normal_replan_and_reset':True,'quota1_usable_quota0_declined':True,'public_correct_count_ge2_excludes_model_DP_feature_and_constructor_calls':True,'future_third_fault_v1_reporting_and_correct_replan':True,'single_SparseReportGuard_no_fault_wrapper':True,'baseline_action_traces':{'sparse_false':false_trace,'sparse_true':true_trace,'count2_declined':count2_declined,'count2_cached':count2_cached,'third_after_correct':third},'policy_mro':[c.__name__ for c in type(actual).__mro__],'evaluator_module':spatial.SpatialPlanner._evaluate.__module__,'no_network_or_truth':True}
name='micro_contract_sparse.json' if accelerated else 'micro_contract_original.json'
(OUT/name).write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k!='baseline_action_traces'}))
