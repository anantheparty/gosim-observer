"""Bounded science controller inside the frozen request/fault actor.

Finite-season shadow prices are a heuristic for the stochastic formal scorer.
The original actor owns request completion, required terms, feedback and report
state. This wrapper only proposes ordinary science observations through the
same public planner. It never reads the calendar world's hidden future.
"""
from __future__ import annotations
import copy,json,time,types
import numpy as np
from research.spatial_candidates import parse_utc
from shared_graph import SharedGraph,Budget,CostStop
from priced_evaluator import _evaluate as priced_evaluate

class SeasonController:
 max_extra_seconds=220.
 update_night_period=2
 graph_seconds=55.
 solve_seconds=3.
 minimum_remaining_seconds=90.
 def __init__(self,actor,emit=None,graph=None,model=None):
  self.actor=actor;self.p=actor.planner;self.original_choose=self.p.choose
  self.emit=emit;self.graph=graph;self.model=model;self.last_price_night=-1
  self.extra_seconds=0.;self.events=[];self.overrides=0;self.disabled=False
 def event(self,**r):
  self.events.append(r)
  if self.emit:self.emit(r)
 def time_price(self,durations,now):
  g=self.graph;lam=self.model['lam'];a=g.endpoints[:-1];z=g.endpoints[1:];durations=np.asarray(durations)
  overlap=np.maximum(0.,np.minimum(now+durations[:,None],z)-np.maximum(now,a))
  return (overlap/np.maximum(1e-9,z-a)*lam).sum(axis=1)
 def protect(self,B,pred,factors,snapshot):
  if not B or B.get('action')!='observe':return 'original_non_observe'
  if snapshot.get('active_requests'):return 'public_active_request'
  if self.p.stats.get('request_dp_active'):return 'original_request_controller'
  ids=[self.p.index[t] for t in B['assignments'].values()]
  if any(self.p.required[i] and factors[i]<self.p.req_threshold for i in ids):return 'original_required_assignment'
  return None
 def completion_bands(self,action,pred,factors,safety):
  counts=np.zeros(len(self.p.band_sizes),dtype=int)
  for tid in action.get('assignments',{}).values():
   i=self.p.index[tid]
   if factors[i]<self.p.uniform_threshold and float(pred.get(tid,{}).get('factor',0))/safety+1e-10>=self.p.uniform_threshold:counts[self.p.ra_bands[i]]+=1
  return counts
 def proxy(self,action,pred,best,now):
  # This comparison is the same frozen-Q short-step proxy used by the strong
  # planner, with explicit nonuniform future-target and time opportunity costs.
  ids=np.asarray([self.p.index[t] for t in action['assignments'].values()],dtype=int)
  gain=sum(max(0.,self.p.weight[i]*float(pred.get(self.p.ids[i],{}).get('factor',0))*float(pred.get(self.p.ids[i],{}).get('program_multiplier',1))-best[i]) for i in ids)
  target_fee=float(self.model['sigma'][ids].sum());d=int(action['duration_seconds']);time_fee=float(self.time_price([d],now)[0])
  return dict(gain=float(gain),target_fee=target_fee,time_fee=time_fee,surplus=float(gain-target_fee-time_fee),duration=d)
 def propose_from_prices(self,snapshot,best,factors,env,B,Bpred):
  p=self.p;now=parse_utc(snapshot['now_utc']).timestamp();original_eval=p._evaluate
  old_time=getattr(p,'_season_time_price',None)
  # Changing only the best-score argument subtracts the target opportunity
  # price inside both native coarse search and exact duration/fiber evaluator.
  priced_best=best+self.model['sigma']
  from research import spatial_candidates
  old_class_eval=spatial_candidates.SpatialPlanner._evaluate
  try:
   spatial_candidates.SpatialPlanner._evaluate=priced_evaluate
   p._season_time_price=lambda ds:self.time_price(ds,now)
   action=self.original_choose(copy.deepcopy(snapshot),priced_best,factors,copy.deepcopy(env),snapshot.get('active_requests',[]))
   pred=copy.deepcopy(p.last_prediction)
  finally:
   spatial_candidates.SpatialPlanner._evaluate=old_class_eval
   if old_time is None:p.__dict__.pop('_season_time_price',None)
   else:p._season_time_price=old_time
  if not action or action.get('action')!='observe':p.last_prediction=Bpred;return B,dict(status='no_positive_priced_observation')
  safety=max(1.,float(env.get('duration_safety',1.1)))
  if np.any(self.completion_bands(action,pred,factors,safety)<self.completion_bands(B,Bpred,factors,safety)):
   p.last_prediction=Bpred;return B,dict(status='uniform_completion_guard')
  base=self.proxy(B,Bpred,best,now);candidate=self.proxy(action,pred,best,now)
  # A candidate has to improve the explicit surplus, with B retained at ties.
  changed=action!=B and candidate['surplus']>base['surplus']+1e-7
  if not changed:p.last_prediction=Bpred;action=B
  else:self.overrides+=1
  return action,dict(status='changed' if changed else 'original_surplus_better',baseline_proxy=base,candidate_proxy=candidate,
   finite_model_certificate=False,model_claim='current fixed-Q marginal surplus heuristic, not stochastic formal value')
 def choose(self,snapshot,best_scores,best_factors,env_estimate=None,active_requests=None):
  p=self.p;env=env_estimate or {};B=self.original_choose(snapshot,best_scores,best_factors,env,active_requests);Bpred=copy.deepcopy(p.last_prediction)
  best=p._array(best_scores);factors=p._array(best_factors);now=parse_utc(snapshot['now_utc']);night=self.actor._night(now)
  reason=self.protect(B,Bpred,factors,snapshot)
  remaining=float((snapshot.get('wallclock') or {}).get('remaining_seconds',0))
  if reason or self.disabled or self.extra_seconds>=self.max_extra_seconds or remaining<self.minimum_remaining_seconds:return B
  started=time.perf_counter();action=B
  try:
   if self.graph is None:
    budget=Budget(seconds=min(self.graph_seconds,self.max_extra_seconds-self.extra_seconds,remaining-self.minimum_remaining_seconds),rss_mb=1536)
    self.graph=SharedGraph(self.actor,snapshot,budget,current=False)
    self.event(event='season_shared_graph',night=night,metadata=self.graph.metadata(),build_seconds=time.perf_counter()-started)
   g=self.graph
   if self.model is None or night>=self.last_price_night+self.update_night_period:
    g.budget=Budget(seconds=min(self.solve_seconds+.5,self.max_extra_seconds-self.extra_seconds,remaining-self.minimum_remaining_seconds),rss_mb=1536)
    model=g.solve(best,now.timestamp(),seconds=self.solve_seconds,relative_gap=.005)
    if model is None:self.event(event='season_price_incomplete',night=night);return B
    self.model=model;self.last_price_night=night
    self.event(event='season_price',night=night,lower=model['lower'],upper=model['upper'],gap=model['gap'],rounds=model['rounds'],stop=model['stop'])
   action,diagnostic=self.propose_from_prices(snapshot,best,factors,env,B,Bpred)
   self.event(event='season_science_proposal',night=night,now_utc=snapshot['now_utc'],**diagnostic)
  except CostStop as exc:
   self.event(event='season_cost_stop',night=night,reason=str(exc));p.last_prediction=Bpred;action=B
   if self.graph is None:self.disabled=True
  except Exception as exc:
   self.event(event='season_error_fallback',night=night,error=type(exc).__name__,reason=str(exc));p.last_prediction=Bpred;action=B;self.disabled=True
  finally:self.extra_seconds+=time.perf_counter()-started
  return action
 def summary(self):return dict(extra_seconds=self.extra_seconds,max_extra_seconds=self.max_extra_seconds,overrides=self.overrides,disabled=self.disabled,events=self.events,
  scope='fixed deterministic season science shadow prices; original REQ/required/fault/report actor retained',
  coefficient_refresh='physical coefficient bank frozen at first eligible public state; target/time ledger replanned every two nights')

def make_policy(base,emit=None):
 class SeasonPolicy(base):
  def __init__(self,initial):
   super().__init__(initial);self.season_controller=SeasonController(self,emit)
   self.planner.choose=self.season_controller.choose
  def summary(self):return {**super().summary(),'season_pattern_controller':self.season_controller.summary()}
 return SeasonPolicy
