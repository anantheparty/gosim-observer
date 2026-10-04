#!/usr/bin/env python3
"""Terminal report guard adapted to the unchanged offline RequestCache policy.

Reads only initialization and live protocol messages.  It freezes the final
already selected action, reports once, and returns that exact action without
ingesting the new report into the actor.  It never reads a card or teacher file.
"""
from __future__ import annotations

import collections
import copy
import hashlib
import json
import math
import os
import sys
import traceback
import time
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
sys.dont_write_bytecode=True


def parse_utc(value):
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def action_hash(action):
    return hashlib.sha256(json.dumps(action,sort_keys=True,separators=(',',':'),
                                     allow_nan=False).encode()).hexdigest()


class TerminalReportGuard:
    def __init__(self,initial,enabled=False,minimum_wallclock=10.,emit=None):
        self.enabled=bool(enabled)
        self.emit=emit
        self.minimum_wallclock=float(minimum_wallclock)
        self.end=parse_utc(initial['survey']['end_utc'])
        self.nights=[(parse_utc(n['observing_start_utc']),parse_utc(n['observing_end_utc']))
                     for n in initial['survey']['nights']]
        self.cfg=initial['scoring']
        self.reporting=self.cfg['reporting']
        self.threshold=float(self.cfg['uniformity']['observed_factor_threshold'])
        self.band_width=float(self.cfg['uniformity']['ra_band_width_deg'])
        self.weight=float(self.cfg['uniformity']['weight'])
        # Official v4 initialize uses a columnar public catalogue, exactly as
        # v4_workflow.initialize_payload and the unchanged RequestCache planner do.
        targets=initial['targets']
        columns=targets['columns']
        col={name:i for i,name in enumerate(columns)}
        self.catalog={str(row[col['target_id']]):
                      {'weight':float(row[col['science_weight']]),
                       'band':int(float(row[col['ra_deg']])//self.band_width)}
                      for row in targets['rows']}
        self.band_totals=collections.Counter(t['band'] for t in self.catalog.values())
        self.entries={}
        self.request_thresholds={}
        self.request_completed={}
        self.invalid=set()
        self.last_sent=None
        self.awaiting_feedback=False
        self.false_count=0
        self.consecutive_reports=0
        self.report_count=0
        self.correct_reports=0
        self.cached=None
        self.cache_now=None
        self.cache_rank=None
        self.fired=False
        self.events=[]
        self.terminal_correct=None
        self.terminal_score_delta=None
        self.gate_checks=collections.Counter()
        self.last_bound_details={}

    def _record(self,event,**fields):
        record={'event':event,**fields}
        self.events.append(record)
        if self.emit:self.emit(record)

    def ingest(self,snapshot):
        if not self.enabled:return
        result=snapshot.get('last_result') or {}
        previous=self.last_sent
        if self.awaiting_feedback and previous:
            sent=previous['action']
            if sent['action']=='report':
                if result.get('action')!='report' or not isinstance(result.get('correct'),bool):
                    raise RuntimeError('Missing public result for the last report')
                if result['correct']:
                    self.correct_reports+=1
                    self.false_count=0
                else:self.false_count+=1
                if self.cached is not None:
                    self.terminal_correct=result['correct']
                    self.terminal_score_delta=result.get('score_delta')
                    self._record('terminal_report_result',correct=result['correct'],
                                 score_delta=result.get('score_delta'),
                                 now_utc=snapshot['now_utc'],
                                 observe_action_index=snapshot['observe_action_index'])
            elif sent['action']=='observe' and result.get('action')=='observe':
                rank=int(result['observe_index'])
                if rank!=previous['rank']:
                    raise RuntimeError('Public observation rank differs from emitted action')
                multiplier=float(self.cfg['program']['multipliers'].get(sent.get('program','BACKUP'),1.))
                mismatch=float(self.cfg['program']['mismatch_multiplier'])
                rows=[]
                for hit in result.get('hits',[]):
                    tid=hit['target_id']
                    weight=self.catalog[tid]['weight']
                    score=float(hit['score'])
                    if not math.isfinite(score) or score<0 or weight<0:
                        raise RuntimeError('Invalid public target score/weight')
                    eps=0.500001e-6
                    denominator_lo=weight*max(multiplier,mismatch)
                    denominator_hi=weight*min(multiplier,mismatch)
                    lo=min(1.,max(0.,score-eps)/denominator_lo) if denominator_lo>0 else 0.
                    hi=min(1.,max(0.,score+eps)/denominator_hi) if denominator_hi>0 else 1.
                    rows.append((tid,lo,hi))
                if rank in self.entries:raise RuntimeError('Duplicate public observation feedback')
                self.entries[rank]=rows
            self.awaiting_feedback=False
        # Request results omit threshold; publications (including those carried
        # over a wait-until) establish it before results are consumed.
        for message in snapshot.get('new_messages',[]):
            if message.get('record_type')=='observation_request':
                self._request(message)
        for message in snapshot.get('new_messages',[]):
            kind=message.get('record_type')
            if kind=='state_resync':
                window=message['invalidated_window']
                self.invalid.update(range(int(window['action_index_start']),
                                          int(window['action_index_end_exclusive'])))
                # Conservatively revoke every cached request certificate. An
                # unaffected expired request need not be re-announced; losing
                # its certificate makes the bound weaker and remains safe.
                self.request_completed.clear()
                for request in message.get('observation_requests',[]):self._request(request)
            elif kind=='observation_request_result':self._request(message)
        for request in snapshot.get('active_requests',[]):self._request(request)

    def _request(self,request):
        request_id=str(request['request_id'])
        threshold=request.get('completion_factor_threshold',self.request_thresholds.get(request_id))
        if threshold is not None:
            threshold=float(threshold)
            if not math.isfinite(threshold) or not 0<threshold<=1:
                raise RuntimeError('Invalid public request threshold')
            self.request_thresholds[request_id]=threshold
        if 'completion_reward' in request and float(request['completion_reward'])<0:
            raise RuntimeError('Negative request reward violates official v4 contract')
        if 'completed_target_ids' in request:
            # Replace, rather than union: a revised result revokes lost proofs.
            self.request_completed[request_id]=set(map(str,request['completed_target_ids']))

    def sent(self,snapshot,action):
        if not self.enabled:return
        self.last_sent={'action':copy.deepcopy(action),'rank':int(snapshot['observe_action_index']),
                        'now_utc':snapshot['now_utc']}
        self.awaiting_feedback=action['action'] in ('observe','report')
        if action['action']=='report':
            self.report_count+=1
            self.consecutive_reports+=1
        else:self.consecutive_reports=0

    def terminal_kind(self,snapshot,action):
        now=parse_utc(snapshot['now_utc'])
        if now>=self.end:return None
        kind=action.get('action')
        if kind=='finish':return 'finish'
        if kind=='wait':
            if 'until_utc' in action:
                return 'wait' if parse_utc(action['until_utc'])>=self.end else None
            return 'wait' if now+timedelta(seconds=int(action['duration_seconds']))>=self.end else None
        if kind!='observe':return None
        effective_end=min(now+timedelta(seconds=int(action['duration_seconds'])),self.end)
        # Official v4_runner also clips to night_end when exposure start lies
        # inside a slot. Public nights give those occupied interval bounds.
        # In a daytime gap the runner only applies duration/survey clipping.
        for start,end in self.nights:
            if start<=now<end:
                effective_end=min(effective_end,end)
                break
        return 'observe' if effective_end>=self.end else None

    def uniformity_harm_bound(self,action):
        if action['action'] in ('wait','finish'):return 0.
        lo=collections.defaultdict(float)
        hi=collections.defaultdict(float)
        for rank,rows in self.entries.items():
            if rank in self.invalid:continue
            for tid,l,u in rows:
                lo[tid]=max(lo[tid],l)
                hi[tid]=max(hi[tid],u)
        for request_id,completed in self.request_completed.items():
            threshold=self.request_thresholds.get(request_id)
            if threshold is None:continue
            for tid in completed:
                if tid in self.catalog:
                    lo[tid]=max(lo[tid],threshold)
                    hi[tid]=max(hi[tid],threshold)
        low_counts=collections.Counter()
        high_counts=collections.Counter()
        for tid,target in self.catalog.items():
            low_counts[target['band']]+=lo[tid]>=self.threshold
            high_counts[target['band']]+=hi[tid]>=self.threshold
        increments=collections.Counter()
        for tid in set(action.get('assignments',{}).values()):
            if tid not in self.catalog:return math.inf
            if lo[tid]<self.threshold:increments[self.catalog[tid]['band']]+=1
        bands=sorted(self.band_totals)
        lower=[low_counts[b]/self.band_totals[b] for b in bands]
        upper=[high_counts[b]/self.band_totals[b] for b in bands]
        delta=[increments[b]/self.band_totals[b] for b in bands]
        q_min=sum(l*l for l in lower)
        self.last_bound_details={'valid_feedback_ranks':len(set(self.entries)-self.invalid),
            'invalidated_feedback_ranks':sorted(self.invalid),
            'request_certificate_targets':len(set().union(*self.request_completed.values())) if self.request_completed else 0,
            'bands':bands,'lower_ratios':lower,'upper_ratios':upper,
            'possible_final_increments':delta,'q_min':q_min}
        if not any(delta) or self.weight==0:return 0.
        if q_min<=0:return self.weight
        s_max=sum(u+d for u,d in zip(upper,delta))
        derivative=sum(2*self.weight*s_max*s_max*(u+d)*d/(len(bands)*q_min*q_min)
                       for u,d in zip(upper,delta))
        return min(self.weight,derivative)

    def propose(self,snapshot,action,decision_started=None):
        if not self.enabled:return action
        if self.fired:return action
        terminal=self.terminal_kind(snapshot,action)
        if terminal is None:
            self.gate_checks['not_terminal']+=1
            return action
        quota=int(self.reporting.get('false_report_free_allowance',0))-self.false_count
        if quota<=0:
            self.gate_checks['quota_exhausted']+=1
            return action
        if self.consecutive_reports>=int(self.reporting.get('max_consecutive_reports',32)):
            self.gate_checks['consecutive_limit']+=1
            return action
        remaining=snapshot.get('wallclock',{}).get('remaining_seconds')
        elapsed=max(0.,time.perf_counter()-decision_started) if decision_started is not None else 0.
        remaining=None if remaining is None else float(remaining)-elapsed
        if remaining is None or not math.isfinite(remaining) or remaining<self.minimum_wallclock:
            self.gate_checks['wallclock']+=1
            return action
        harm=self.uniformity_harm_bound(action)
        reward=float(self.reporting['correct_reward'])
        if not math.isfinite(harm) or harm>reward or reward<0:
            self.gate_checks['jain_bound']+=1
            return action
        # The catalogue/ledger scan itself also consumes the public budget.
        if decision_started is not None:
            elapsed=max(0.,time.perf_counter()-decision_started)
            remaining=float(snapshot['wallclock']['remaining_seconds'])-elapsed
            if remaining<self.minimum_wallclock:
                self.gate_checks['wallclock']+=1
                return action
        self.cached=copy.deepcopy(action)
        self.cache_now=snapshot['now_utc']
        self.cache_rank=int(snapshot['observe_action_index'])
        self.fired=True
        self._record('terminal_report_frozen',now_utc=self.cache_now,
                     observe_action_index=self.cache_rank,terminal_kind=terminal,
                     frozen_action_hash=action_hash(action),frozen_action=action,
                     free_reports_remaining=quota,consecutive_reports=self.consecutive_reports,
                     worst_jain_harm=harm,conditional_correct_gain_lower=reward-harm,
                     wallclock_remaining=remaining,selection_elapsed_seconds=elapsed,
                     ledger_bound=copy.deepcopy(self.last_bound_details))
        return {'action':'report'}

    def release(self,snapshot):
        if self.cached is None:raise RuntimeError('No frozen terminal action')
        if snapshot['now_utc']!=self.cache_now or int(snapshot['observe_action_index'])!=self.cache_rank:
            raise RuntimeError('Report unexpectedly changed public time or observation rank')
        result=snapshot.get('last_result') or {}
        if result.get('action')!='report' or not isinstance(result.get('correct'),bool):
            raise RuntimeError('Terminal report acknowledgement missing')
        expected=float(self.reporting['correct_reward']) if result['correct'] else 0.
        if result.get('score_delta')!=expected:
            raise RuntimeError('Report settlement differs from the certified public quota')
        if any(message.get('record_type')!='report_result' for message in snapshot.get('new_messages',[])):
            raise RuntimeError('Unexpected new public information between report and frozen tail')
        action=self.cached
        self.cached=None
        self._record('terminal_report_frozen_action_released',
                     frozen_action_hash=action_hash(action),actor_belief_update_suppressed=True)
        return action

    def summary(self):
        return {'enabled':self.enabled,'inserted_reports':int(self.fired),
                'terminal_correct':self.terminal_correct,'terminal_score_delta':self.terminal_score_delta,
                'all_reports_sent':self.report_count,'all_correct_reports_received':self.correct_reports,
                'false_reports_since_correct':self.false_count,
                'gate_checks':dict(self.gate_checks),'events':self.events,
                'reads_truth':False,'reads_teacher_labels':False}


def make_policy_class(base,enabled=False,minimum_wallclock=10.,emit=None):
    class TerminalPolicy(base):
        def __init__(self,initial):
            super().__init__(initial)
            self.terminal_guard=TerminalReportGuard(initial,enabled,minimum_wallclock,emit)

        def decide(self,snapshot):
            decision_started=time.perf_counter()
            guard=self.terminal_guard
            if not guard.enabled:return super().decide(snapshot)
            guard.ingest(snapshot)
            if guard.cached is not None:
                action=guard.release(snapshot)
            else:
                action=super().decide(snapshot)
                action=guard.propose(snapshot,action,decision_started)
            guard.sent(snapshot,action)
            return action

        def summary(self):
            result=super().summary()
            result['terminal_report']=self.terminal_guard.summary()
            return result
    return TerminalPolicy


def serve(input_stream,output_stream,error_stream,policy_class):
    policy=None
    for line in input_stream:
        if not line.strip():continue
        message=json.loads(line)
        kind=message.get('message_type')
        if kind=='initialize':
            policy=policy_class(message['payload'])
        elif kind=='decision_request':
            try:
                action=policy.decide(message['payload']) if policy else {'action':'wait','duration_seconds':900}
            except Exception:
                traceback.print_exc(file=error_stream)
                # If a terminal report has been emitted, failing its state guards
                # must terminate rather than accidentally send a different tail.
                if policy and policy.terminal_guard.fired:raise
                action={'action':'wait','duration_seconds':900}
            response={'protocol_version':'participant-agent-protocol-v4',
                      'message_type':'decision_response',
                      'decision_sequence':message['decision_sequence'],**action}
            print(json.dumps(response,separators=(',',':'),allow_nan=False),file=output_stream,flush=True)
        elif kind=='finish':
            if policy:
                print(json.dumps(policy.summary(),separators=(',',':'),allow_nan=False),file=error_stream,flush=True)
            break
    if policy and getattr(policy,'remote',None):policy.remote.close()
    return policy
