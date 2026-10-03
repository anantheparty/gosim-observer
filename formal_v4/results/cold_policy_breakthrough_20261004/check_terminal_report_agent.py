#!/usr/bin/env python3
"""Synthetic protocol/guard checks; no season run or participant truth access."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('terminal_report_agent',HERE/'terminal_report_agent.py')
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def initial(targets=None):
    targets=targets or [{'target_id':'A','ra_deg':0.,'science_weight':1.},
                        {'target_id':'B','ra_deg':10.,'science_weight':1.}]
    columns=['target_id','ra_deg','science_weight']
    return {'survey':{'end_utc':'2031-01-01T01:00:00Z','nights':[
        {'observing_start_utc':'2031-01-01T00:00:00Z','observing_end_utc':'2031-01-01T01:00:00Z'}]},
        'targets':{'columns':columns,'rows':[[row[column] for column in columns] for row in targets]},
        'scoring':{'reporting':{'false_report_free_allowance':2,'max_consecutive_reports':32,'correct_reward':100},
                   'uniformity':{'observed_factor_threshold':.5,'ra_band_width_deg':10.,'weight':200.},
                   'program':{'multipliers':{'DARK':1.2,'BRIGHT':1.12,'BACKUP':1.06},'mismatch_multiplier':1.}}}


def snap(now='2031-01-01T00:59:00Z',rank=7,result=None,messages=None,remaining=80):
    return {'now_utc':now,'observe_action_index':rank,'survey_end_utc':'2031-01-01T01:00:00Z',
            'last_result':result,'new_messages':messages or [],'wallclock':{'remaining_seconds':remaining}}


def observe(duration=60,tid='A'):
    return {'action':'observe','duration_seconds':duration,'program':'DARK',
            'pointing':{'alt_deg':50.,'az_deg':120.},'assignments':{'0':tid}}


def seed_completed(guard,tid='A',rank=0):
    s=snap(now='2031-01-01T00:30:00Z',rank=rank)
    guard.sent(s,observe(tid=tid))
    guard.ingest(snap(now='2031-01-01T00:31:00Z',rank=rank+1,
                     result={'action':'observe','observe_index':rank,'hits':[{'target_id':tid,'score':1.2}]}))


class FakeBase:
    def __init__(self,initial):
        self.calls=0
        self.C=.41
        self.E=.33
        self.pending=None
        self.remote=None

    def decide(self,snapshot):
        self.calls+=1
        if (snapshot.get('last_result') or {}).get('action')=='report':
            self.C=1.
            self.E=.95
        self.pending=copy.deepcopy(snapshot['planned_action'])
        return copy.deepcopy(snapshot['planned_action'])

    def summary(self):return {'base_calls':self.calls,'C':self.C,'E':self.E}


def main():
    checks=[]
    def checked(name):checks.append(name)
    # Disabled wrapper must return every ordinary base action verbatim and call
    # the unchanged actor exactly once per input request.
    Wrapped=mod.make_policy_class(FakeBase,enabled=False)
    base=FakeBase(initial());wrapped=Wrapped(initial())
    for s,a in [(snap(now='2031-01-01T00:10:00Z'),observe()),
                (snap(),{'action':'wait','duration_seconds':60})]:
        s['planned_action']=a
        assert wrapped.decide(s)==base.decide(s)==a
    assert wrapped.calls==base.calls and (wrapped.C,wrapped.E)==(base.C,base.E)
    checked('disabled_action_and_actor_call_identity')
    # Freeze a final wait, then supply a correct report which the fake base would
    # otherwise turn into an aggressive C/E reset.  The base is never called.
    Wrapped=mod.make_policy_class(FakeBase,enabled=True)
    wrapped=Wrapped(initial());s=snap();s['planned_action']={'action':'wait','until_utc':'2031-01-01T01:00:00Z'}
    frozen=copy.deepcopy(s['planned_action'])
    assert wrapped.decide(s)=={'action':'report'}
    before=(wrapped.C,wrapped.E,copy.deepcopy(wrapped.pending),wrapped.calls)
    next_s=snap(result={'action':'report','correct':True,'repaired':True,'score_delta':100.})
    next_s['planned_action']={'action':'finish'}
    assert wrapped.decide(next_s)==frozen
    assert (wrapped.C,wrapped.E,wrapped.pending,wrapped.calls)==before
    assert wrapped.terminal_guard.terminal_correct is True
    checked('correct_report_releases_exact_action_without_actor_belief_update')
    guard=mod.TerminalReportGuard(initial(),enabled=True)
    assert guard.propose(snap(now='2031-01-01T00:10:00Z'),observe())==observe()
    checked('nonterminal_observe_guard')
    assert guard.propose(snap(now='2031-01-01T00:58:00Z'),{'action':'wait','duration_seconds':60})=={'action':'wait','duration_seconds':60}
    checked('nonterminal_wait_guard')
    # A long command cannot prove terminality if it would be cut at an earlier
    # night boundary.  This also rejects a daytime command.
    init=initial();init['survey']['nights'][0]['observing_end_utc']='2031-01-01T00:30:00Z'
    guard=mod.TerminalReportGuard(init,enabled=True)
    assert guard.terminal_kind(snap(),observe()) is None
    checked('observe_night_boundary_and_daytime_guard')
    guard=mod.TerminalReportGuard(initial(),enabled=True)
    assert guard.propose(snap(),observe())==observe()
    assert guard.gate_checks['jain_bound']==1
    checked('unknown_completion_ratios_reject_observe')
    guard=mod.TerminalReportGuard(initial(),enabled=True)
    seed_completed(guard)
    assert guard.uniformity_harm_bound(observe())==0.
    assert guard.propose(snap(),observe())=={'action':'report'}
    checked('already_completed_final_assignment_safe')
    guard=mod.TerminalReportGuard(initial(),enabled=True)
    seed_completed(guard)
    other=observe(tid='B')
    assert guard.uniformity_harm_bound(other)>100
    assert guard.propose(snap(),other)==other
    checked('large_possible_Jain_harm_rejects_report')
    guard=mod.TerminalReportGuard(initial(),enabled=True)
    for rank in [0,1]:
        s=snap(now='2031-01-01T00:10:00Z',rank=rank)
        guard.sent(s,{'action':'report'})
        guard.ingest(snap(now=s['now_utc'],rank=rank,result={'action':'report','correct':False,'score_delta':0.}))
    final={'action':'wait','duration_seconds':60}
    assert guard.propose(snap(),final)==final and guard.gate_checks['quota_exhausted']==1
    checked('public_false_quota_exhaustion')
    # The cap is checked independently from the free allowance.
    init=initial();init['scoring']['reporting']['false_report_free_allowance']=100
    guard=mod.TerminalReportGuard(init,enabled=True)
    for rank in range(32):
        s=snap(now='2031-01-01T00:10:00Z',rank=rank)
        guard.sent(s,{'action':'report'})
        guard.ingest(snap(now=s['now_utc'],rank=rank,result={'action':'report','correct':False,'score_delta':0.}))
    assert guard.propose(snap(),final)==final and guard.gate_checks['consecutive_limit']==1
    checked('consecutive_report_cap')
    guard=mod.TerminalReportGuard(initial(),enabled=True)
    assert guard.propose(snap(remaining=9.99),final)==final
    no_clock=snap();no_clock.pop('wallclock')
    assert guard.propose(no_clock,final)==final
    checked('missing_or_small_wallclock_rejects')
    # Invalidations must remove old completion evidence before the terminal gate.
    guard=mod.TerminalReportGuard(initial(),enabled=True)
    seed_completed(guard)
    guard.ingest(snap(messages=[{'record_type':'state_resync','invalidated_window':
                                {'action_index_start':0,'action_index_end_exclusive':1}}]))
    assert guard.propose(snap(),observe())==observe()
    checked('public_resync_removes_completion_evidence')
    for change in [{'now_utc':'2031-01-01T00:59:01Z'},{'observe_action_index':8}]:
        guard=mod.TerminalReportGuard(initial(),enabled=True)
        assert guard.propose(snap(),final)=={'action':'report'}
        s=snap(result={'action':'report','correct':False});s.update(change)
        try:guard.release(s)
        except RuntimeError:pass
        else:raise AssertionError('A report changed public state but tail was sent')
    checked('unexpected_report_time_or_rank_change_terminates')
    guard=mod.TerminalReportGuard(initial(),enabled=True)
    assert guard.propose(snap(),{'action':'finish'})=={'action':'report'}
    guard.sent(snap(),{'action':'report'})
    s=snap(result={'action':'report','correct':False,'score_delta':0.})
    guard.ingest(s)
    assert guard.release(s)=={'action':'finish'}
    assert guard.propose(s,{'action':'finish'})=={'action':'finish'}
    checked('finish_terminal_and_only_one_inserted_report')
    # Full JSONL protocol surface, with sequence ids and custom summary.
    first=snap();first['planned_action']=final
    second=snap(result={'action':'report','correct':False,'repaired':False,'score_delta':0.})
    second['planned_action']={'action':'finish'}
    lines=[{'message_type':'initialize','payload':initial()},
           {'message_type':'decision_request','decision_sequence':71,'payload':first},
           {'message_type':'decision_request','decision_sequence':72,'payload':second},
           {'message_type':'finish'}]
    output=io.StringIO();error=io.StringIO()
    mod.serve(io.StringIO('\n'.join(json.dumps(r) for r in lines)),output,error,
              mod.make_policy_class(FakeBase,enabled=True))
    responses=[json.loads(r) for r in output.getvalue().splitlines()]
    assert [r['decision_sequence'] for r in responses]==[71,72]
    assert [r['action'] for r in responses]==['report','wait']
    summary=json.loads(error.getvalue())
    assert summary['terminal_report']['inserted_reports']==1
    assert summary['terminal_report']['terminal_score_delta']==0.
    assert summary['base_calls']==1 and summary['C']==.41 and summary['E']==.33
    checked('full_protocol_sequence_and_terminal_summary')
    # Inputs may be renamed and dates/ranks shifted without changing the rule.
    moved=initial();moved['survey']['end_utc']='2042-03-04T06:00:00Z'
    moved['survey']['nights']=[{'observing_start_utc':'2042-03-04T05:00:00Z','observing_end_utc':'2042-03-04T06:00:00Z'}]
    guard=mod.TerminalReportGuard(moved,enabled=True)
    s=snap(now='2042-03-04T05:59:00Z',rank=123456)
    assert guard.propose(s,final)=={'action':'report'}
    checked('no_card_rank_or_date_hardcoding')
    result={'schema':'terminal-report-synthetic-guard-checks-v1','checks_passed':len(checks),
            'checks':checks,'reads_truth':False,'reads_teacher_labels':False,
            'runs_season':False,'imports_native_policy':False,
            'agent_sha256':hashlib.sha256((HERE/'terminal_report_agent.py').read_bytes()).hexdigest()}
    (HERE/'synthetic_guard_checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
