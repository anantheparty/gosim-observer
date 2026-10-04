"""Tiny intervention checks, explicitly synthetic; no payoff estimates."""
from pathlib import Path
from datetime import timedelta
import sys,copy,json,pickle,hashlib
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE/'candidate_package'))
from research import agent_request_exact_cache as exact_entry
from persistent_fault_guard import make_policy_class
from research.geometry import parse_utc
initial=json.loads((ROOT/'formal_v4/results/policy_iteration_20261004/L1_initialize_public.json').read_text())
real=exact_entry.ExactCachedRequestPolicy(initial)
class Fixture:
 def __init__(self,initial):
  self.initial=initial;self.planner=real.planner;self.slot_seconds=900
  self.pending=None;self.C=.234;self.E=.432;self.belief_clock={'anchor':'unchanged'}
  self.low_efficiency=[(1,2,3)];self.efficiency_witnesses=[(4,5)]
  self.ledger=[{'valid':True,'rank':0}];self.false_since_correct=0
  self.correct_reports=0;self.report_count=0;self.last_report=None;self.calls=0
 def _night(self,now):return next((i for i,(a,b) in enumerate(self.planner.nights) if a<=now<b),-1)
 def decide(self,s):
  self.calls+=1
  if (s.get('last_result') or {}).get('action')=='report':
   assert self.pending['action']=={'action':'report'}
   if s['last_result']['correct']:self.E=.95;self.correct_reports+=1;self.false_since_correct=0
   else:self.E=.95;self.C=99 # would expose accidental false ingestion
  action={'action':'observe','pointing':{'alt_deg':70.,'az_deg':90.},'duration_seconds':60,'program':'DARK','assignments':{'0':'V4T000001'}}
  self.pending={'action':copy.deepcopy(action),'start':parse_utc(s['now_utc']), 'prior_C':self.C,'prior_E':self.E,'prediction':{},'notices':[]}
  return action
 def summary(self):return {'calls':self.calls}

def make():
 actor=make_policy_class(Fixture)(initial)
 # Evidence extraction is tested separately on original public histories;
 # force only the scalar diagnosis result to exercise the causal interface.
 def evidence(s):
  actor.persistent_guard.latest_features={'qualified':True,'median_ratio_upper':.4}
  return actor.persistent_guard.latest_features
 actor.persistent_guard.evidence=evidence
 s={'now_utc':initial['survey']['start_utc'],'observe_action_index':0,'new_messages':[], 'last_result':None,'wallclock':{'remaining_seconds':900}}
 return actor,s

actor,s=make();report=actor.decide(s);assert report=={'action':'report'}
fields=('C','E','belief_clock','low_efficiency','efficiency_witnesses','ledger','last_report')
before={k:copy.deepcopy(getattr(actor,k)) for k in fields};pending=copy.deepcopy(actor.persistent_guard.saved_pending)
ack={**s,'last_result':{'action':'report','correct':False,'repaired':False,'score_delta':0},'new_messages':[{'record_type':'report_result'}]}
action=actor.decide(ack)
assert action==pending['action'] and actor.pending==pending and actor.calls==1
assert all(getattr(actor,k)==v for k,v in before.items())
assert actor.false_since_correct==1 and actor.report_count==1 and actor.persistent_guard.false_count==1
actor,s=make();actor.decide(s)
ack={**s,'last_result':{'action':'report','correct':True,'repaired':True,'score_delta':100},'new_messages':[{'record_type':'report_result'}]}
action=actor.decide(ack)
assert actor.calls==2 and actor.E==.95 and actor.correct_reports==1 and actor.report_count==1
assert actor.persistent_guard.correct==1 and actor.persistent_guard.cached is None
actor,s=make();actor.persistent_guard.false_count=1
assert actor.decide(s)['action']=='observe' and actor.persistent_guard.inserted==0
actor,s=make();s.pop('wallclock')
assert actor.decide(s)['action']=='observe' and actor.persistent_guard.inserted==0
actor,s=make();actor.decide(s);bad={**s,'now_utc':'2026-11-02T00:30:01Z','last_result':{'action':'report','correct':False,'score_delta':0}}
try:actor.decide(bad)
except RuntimeError:pass
else:raise AssertionError('time movement not rejected')
result={'passed':True,'checks':['false report releases exact pending action','false C/E and belief clock unchanged','false ledger/witnesses unchanged','quota synchronized once','true report normal ingestion and replan','reserve one free quota','no fictitious wallclock accepted','UTC/rank invariant enforced'],'synthetic_interface_only':True,'score_gain_claim':False}
(HERE/'causal_interface_checks.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
