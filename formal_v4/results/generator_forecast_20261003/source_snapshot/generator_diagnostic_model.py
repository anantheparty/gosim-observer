"""Public score-feedback stopping rule for zero-time free report coupons.

No evaluator, truth, seed, network, or LLM. The threshold is frozen at the
existing 0.68 efficiency suspicion threshold before heldout card evaluation.
"""
from __future__ import annotations
from collections import deque
import numpy as np
from research.feedback_model import fit_feedback
from research.geometry import parse_utc

THRESHOLD=.68
CONFIDENCE_LOSS=.5
FRESH_SECONDS=7200
COOLDOWN_SECONDS=86400
MIN_FEEDBACK=3

def install_diagnostic_policy(BasePolicy,reserve_coupons=0):
    class DiagnosticPolicy(BasePolicy):
        def __init__(self,initial):
            super().__init__(initial)
            self.diagnostic_evidence=deque(maxlen=12)
            self.diagnostic_seen=set()
            self.diagnostic_stats={'fresh_fits':0,'coupon_reports':0,'coupon_reports_with_quake':0,
                                   'original_reports':0,'correct_coupon_reports':0,'false_coupon_reports':0,
                                   'minimum_coupon_remaining_before_report':None,'reserve_coupons':reserve_coupons}
            self.diagnostic_pending=False

        def _ingest_result(self,snapshot):
            result=snapshot.get('last_result') or {}
            pending=self.pending
            new_index=result.get('observe_index')
            super()._ingest_result(snapshot)
            now=parse_utc(snapshot['now_utc'])
            if result.get('action')=='report':
                if self.diagnostic_pending:
                    key='correct_coupon_reports' if result.get('correct',result.get('repaired',False)) else 'false_coupon_reports'
                    self.diagnostic_stats[key]+=1
                self.diagnostic_pending=False
                self.diagnostic_evidence.clear()
                return
            if (result.get('action')!='observe' or not pending or new_index is None
                    or int(new_index) in self.diagnostic_seen):return
            self.diagnostic_seen.add(int(new_index))
            action=pending['action'];start=pending['start']
            duration=min(float(action['duration_seconds']),(now-start).total_seconds())
            hits=[h for h in result.get('hits',[]) if str(h.get('target_id')) in self.planner.index]
            if len(hits)<3 or duration<=0:return
            p=self.planner;idx=np.array([p.index[str(h['target_id'])] for h in hits],int)
            H=self._geometric_H(start,duration,idx)
            fit=fit_feedback(hits,p.weight[idx],p.flux[idx],duration,H,action['program'],
                self.initial.get('scoring',{}),pending.get('prior_C',self.C),pending.get('prior_E',self.E))
            if fit['informative'] and fit['loss']<CONFIDENCE_LOSS:
                self.diagnostic_evidence.append((now,float(fit['E']),float(fit['C']),float(fit['loss'])))
                self.diagnostic_stats['fresh_fits']+=1

        def _repair(self,now):
            if super()._repair(now):
                self.diagnostic_stats['original_reports']+=1
                self.diagnostic_evidence.clear()
                return True
            if not self.config.get('repair_enabled',True):return False
            allowance=int(self.initial.get('scoring',{}).get('reporting',{}).get('false_report_free_allowance',0))
            remaining=allowance-int(self.false_since_correct)
            # Keep a coupon for the source's stronger, unconfounded fault witness.
            if remaining<=reserve_coupons:return False
            if self.last_report and (now-self.last_report).total_seconds()<COOLDOWN_SECONDS:return False
            evidence=[e for e in self.diagnostic_evidence if 0<=(now-e[0]).total_seconds()<=FRESH_SECONDS]
            if len(evidence)<MIN_FEEDBACK:return False
            if float(np.median([e[1] for e in evidence[-4:]]))>=THRESHOLD:return False
            self.diagnostic_stats['coupon_reports']+=1
            self.diagnostic_stats['coupon_reports_with_quake']+=int(any(n.get('event_kind')=='earthquake' for n in self.notices))
            prev=self.diagnostic_stats['minimum_coupon_remaining_before_report']
            self.diagnostic_stats['minimum_coupon_remaining_before_report']=remaining if prev is None else min(prev,remaining)
            self.diagnostic_pending=True
            self.report_count+=1;self.last_report=now
            self.pending={'action':{'action':'report'}}
            self.low_efficiency.clear();self.efficiency_witnesses.clear();self.diagnostic_evidence.clear()
            return True

        def summary(self):
            return {**super().summary(),'generator_diagnostic':self.diagnostic_stats}

    return DiagnosticPolicy
