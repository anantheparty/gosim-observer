"""Executable bounded season controller using common concrete time paths.

Default adoption requires a finite deterministic model certificate. This code
is a candidate, and has not earned a formal-season evaluation or deployment.
"""
from __future__ import annotations
import copy,time
import numpy as np
from research.spatial_candidates import parse_utc
from shared_graph import SharedGraph,Budget,CostStop
from target_dual_dp import solve,physical_control
from nominal_current import score_action

class ContinuationController:
 max_extra_seconds=220.
 graph_seconds=55.
 update_period_nights=2
 oracle_seconds=2.
 remaining_reserve_seconds=90.
 def __init__(self,actor,emit=None):
  self.actor=actor;self.p=actor.planner;self.original_choose=self.p.choose;self.emit=emit
  self.graph=None;self.extra_seconds=0.;self.last_night=-2;self.sigma=None;self.disabled=False;self.events=[];self.overrides=0
 def event(self,**r):
  self.events.append(r)
  if self.emit:self.emit(r)
 def protected(self,B,factors,snapshot):
  if not B or B.get('action')!='observe':return True
  if snapshot.get('active_requests') or self.p.stats.get('request_dp_active'):return True
  return any(self.p.required[self.p.index[t]] and factors[self.p.index[t]]<self.p.req_threshold for t in B['assignments'].values())
 def completion_bands(self,action,pred,factors,safety):
  counts=np.zeros(len(self.p.band_sizes),dtype=int)
  for tid in action.get('assignments',{}).values():
   i=self.p.index[tid]
   if factors[i]<self.p.uniform_threshold and float(pred.get(tid,{}).get('factor',0))/safety+1e-10>=self.p.uniform_threshold:counts[self.p.ra_bands[i]]+=1
  return counts
 def current_ledger(self,snapshot,action,env,best):
  g=self.graph;field=g.field;oldnow=g.now
  try:
   g.now=parse_utc(snapshot['now_utc']);g.field=self.p._future_field(snapshot,env)
   return score_action(g,action,env,best)
  finally:g.now=oldnow;g.field=field
 def choose(self,snapshot,best_scores,best_factors,env_estimate=None,active_requests=None):
  env=env_estimate or {};p=self.p;B=self.original_choose(snapshot,best_scores,best_factors,env,active_requests);Bpred=copy.deepcopy(p.last_prediction)
  best=p._array(best_scores);factors=p._array(best_factors);now=parse_utc(snapshot['now_utc']);night=self.actor._night(now)
  remaining=float((snapshot.get('wallclock') or {}).get('remaining_seconds',0));left=self.max_extra_seconds-self.extra_seconds
  if self.disabled or left<7 or remaining<self.remaining_reserve_seconds+7 or night<self.last_night+self.update_period_nights or self.protected(B,factors,snapshot):return B
  started=time.perf_counter();action=B;self.last_night=night
  try:
   if self.graph is None:
    budget=Budget(min(self.graph_seconds,left,remaining-self.remaining_reserve_seconds),1536)
    self.graph=SharedGraph(self.actor,snapshot,budget,current=False)
    self.event(event='season_shared_graph',night=night,metadata=self.graph.metadata(),build_seconds=time.perf_counter()-started)
   g=self.graph;g.budget=Budget(min(9.,max(.001,left-(time.perf_counter()-started)),remaining-self.remaining_reserve_seconds),1536)
   initial=solve(g,best,now.timestamp(),seconds=self.oracle_seconds,sigma0=self.sigma)
   if initial is None:return B
   self.sigma=initial['sigma']
   self.event(event='season_target_dual',night=night,upper=initial['upper'],feasible_lower=initial['feasible_lower'],dual_gap=initial['dual_gap'],rounds=len(initial['trace']),positive_prices=int(np.count_nonzero(self.sigma)),stop=initial['stop'])
   # Shadow prices only generate a proposal; final adoption compares concrete
   # common continuations and an independently feasible full finite upper bound.
   candidate=self.original_choose(copy.deepcopy(snapshot),best+self.sigma,factors,copy.deepcopy(env),active_requests)
   pred=copy.deepcopy(p.last_prediction)
   if not candidate or candidate.get('action')!='observe' or candidate==B:
    self.event(event='season_no_distinct_science_proposal',night=night);p.last_prediction=Bpred;return B
   safety=max(1.,float(env.get('duration_safety',1.1)))
   if np.any(self.completion_bands(candidate,pred,factors,safety)<self.completion_bands(B,Bpred,factors,safety)):
    self.event(event='season_uniform_completion_guard',night=night);p.last_prediction=Bpred;return B
   rows=[];pool=list(initial['paths'])
   for name,a in [('B',B),('candidate',candidate)]:
    first=self.current_ledger(snapshot,a,env,best);blocked=now.timestamp()+int(a['duration_seconds'])
    model=solve(g,first,blocked,seconds=self.oracle_seconds,sigma0=self.sigma)
    if model is None:p.last_prediction=Bpred;return B
    pool.extend(model['paths']);rows.append(dict(name=name,action=a,first=first,blocked=blocked,current=float((first-best).sum()),upper=float((first-best).sum()+model['upper'])))
   common=sorted(set(tuple(path) for path in pool))
   for row in rows:
    controls=[physical_control(g,row['first'],[e for e in path if g.starts[e]>=row['blocked']-1e-7]) for path in common]
    row['lower']=row['current']+max(c['increment'] for c in controls)
    if row['lower']>row['upper']+1e-6:raise RuntimeError('common continuation exceeds full finite upper')
   g.budget.check();base,cand=rows;certificate=cand['lower']>base['upper']+1e-7
   if certificate:action=candidate;p.last_prediction=pred;self.overrides+=1
   else:p.last_prediction=Bpred
   self.event(event='season_common_continuation',night=night,now_utc=snapshot['now_utc'],baseline_lower=base['lower'],baseline_upper=base['upper'],candidate_lower=cand['lower'],candidate_upper=cand['upper'],common_paths=len(common),changed=certificate,
    finite_model_certificate=certificate,stochastic_formal_value_certificate=False)
  except CostStop as exc:
   self.event(event='season_cost_stop',night=night,reason=str(exc));p.last_prediction=Bpred;action=B
   if self.graph is None:self.disabled=True
  except Exception as exc:
   self.event(event='season_error_fallback',night=night,error=type(exc).__name__,reason=str(exc));p.last_prediction=Bpred;action=B;self.disabled=True
  finally:self.extra_seconds+=time.perf_counter()-started
  return action
 def summary(self):return dict(extra_seconds=self.extra_seconds,max_extra_seconds=self.max_extra_seconds,overrides=self.overrides,disabled=self.disabled,events=self.events,
  scope='fixed deterministic season coefficient bank; live public score ledger and common continuation DP',
  adoption='candidate feasible nominal continuation must exceed baseline full finite deterministic dual upper',
  physical_bank_freeze='first eligible published calendar/forecast/terrain/belief; later public current first-action model is refreshed')

def make_policy(base,emit=None):
 class ContinuationPolicy(base):
  def __init__(self,initial):
   super().__init__(initial);self.season_controller=ContinuationController(self,emit);self.planner.choose=self.season_controller.choose
  def summary(self):return {**super().summary(),'season_pattern_controller':self.season_controller.summary()}
 return ContinuationPolicy
