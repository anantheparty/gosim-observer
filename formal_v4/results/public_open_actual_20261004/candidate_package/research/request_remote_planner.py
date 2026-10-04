"""Opt-in GPU baseline transport with local future-field request scheduling.

The existing Policy keeps ownership of its score ledger, calibration and shared
terrain state. Only baseline production crosses the supported model transport.
"""
from __future__ import annotations

import time

from .request_deadline_common import RequestDeadlineMixin
from .cpu_phase_candidates import CPUPhaseSpatialPlanner
from .spatial_candidates import parse_utc


class DisabledRemoteFacade:
    """Disable Policy's separate remote path; retain counters and close proxy."""
    enabled=False

    def __init__(self,transport):self.actual=transport
    def __getattr__(self,name):return getattr(self.actual,name)
    def close(self):return self.actual.close()


class PlannerBudgetFacade:
    """Policy's full choose time is real wall cost, not a CPU baseline sample."""
    def __init__(self,budget):self.actual=budget
    def __getattr__(self,name):return getattr(self.actual,name)
    def record_cpu(self,seconds):pass
    def summary(self):return self.actual.summary()


class RequestRemotePlanner(RequestDeadlineMixin,CPUPhaseSpatialPlanner):
    """Same planner interface, with an optional attached budgeted transport."""

    def __init__(self,initial):
        super().__init__(initial)
        self.distributed_transport=None
        self.distributed_budget=None
        self._distributed_normal_tmax=self.tmax
        self._distributed_choose_started=None
        self._total_night_seconds=sum((b-a).total_seconds() for a,b in self.nights)
        self.distributed_counts={'remote_baselines':0,'cpu_baselines':0,'forced_cpu_crops':0,
                                 'transport_failures':0,'cpu_baseline_seconds':0.,
                                 'remote_baseline_seconds':0.}

    def attach_transport(self,transport,budget):
        self.distributed_transport,self.distributed_budget=transport,budget

    def choose(self,*args,**kwargs):
        old=self._distributed_choose_started
        self._distributed_choose_started=time.perf_counter()
        try:return super().choose(*args,**kwargs)
        finally:self._distributed_choose_started=old

    def _remaining_decisions(self,snapshot):
        now=parse_utc(snapshot['now_utc'])
        remaining=sum(max(0.,(b-max(a,now)).total_seconds()) for a,b in self.nights if b>now)
        return max(30.,2200*max(.01,remaining/max(1.,self._total_night_seconds)))

    def _choose_baseline(self,snapshot,best_scores,best_factors,env,active_requests):
        transport,budget=self.distributed_transport,self.distributed_budget
        crop=self.tmax<self._distributed_normal_tmax
        if crop:self.distributed_counts['forced_cpu_crops']+=1
        elapsed=0. if self._distributed_choose_started is None else time.perf_counter()-self._distributed_choose_started
        remaining=max(0.,float((snapshot.get('wallclock') or {}).get('remaining_seconds',900))-elapsed)
        if (not crop and transport is not None and getattr(transport,'enabled',False) and budget is not None
                and budget.allow(remaining,self._remaining_decisions(snapshot))):
            started=time.perf_counter()
            try:
                result=transport.choose(snapshot,self._array(best_scores),self._array(best_factors),env,active_requests)
                action=result['action']
                if action is not None and not isinstance(action,dict):raise ValueError('invalid planner action')
                self.last_prediction=result.get('prediction',{})
                self.stats=result.get('stats',{})
                self.distributed_counts['remote_baselines']+=1
                return action
            except Exception:
                self.distributed_counts['transport_failures']+=1
            finally:
                spent=time.perf_counter()-started
                self.distributed_counts['remote_baseline_seconds']+=spent
                budget.record_remote(spent)
        started=time.perf_counter()
        try:return super()._choose_baseline(snapshot,best_scores,best_factors,env,active_requests)
        finally:
            spent=time.perf_counter()-started
            self.distributed_counts['cpu_baselines']+=1
            self.distributed_counts['cpu_baseline_seconds']+=spent
            if budget is not None:budget.record_cpu(spent)

    def distributed_summary(self):
        return {**self.distributed_counts,
                'budget':self.distributed_budget.summary() if self.distributed_budget is not None else None,
                'cpu_sample_scope':'actual baseline search only; excludes transport, REQ pool and DP'}
