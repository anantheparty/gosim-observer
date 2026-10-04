"""Official short report/tail loop using only explicitly synthetic weather.

No real card is loaded. Only in-memory scenario/footprint loaders are replaced;
the original runner, protocol and scorer functions execute unchanged.
"""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
KIT = ROOT/'formal_v4/upstream/gosim-observer-examples'
sys.dont_write_bytecode = True
sys.path.insert(0, str(KIT/'runner'))
from challenge import v4_runner as runner
from challenge.v4_workflow import V4Workflow
from challenge.v4_scorer import SlotTruth, ScoreEvent

spec = importlib.util.spec_from_file_location('request_terminal_guard', HERE/'terminal_report_agent.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def initial():
    value = json.loads((ROOT/'formal_v4/results/policy_iteration_20261004/L1_initialize_public.json').read_text())
    value['targets']['rows'] = value['targets']['rows'][:2]
    value['survey']['end_utc'] = '2031-01-01T01:00:00Z'
    value['survey']['start_utc'] = '2031-01-01T00:59:00Z'
    value['survey']['nights'] = [{'observing_start_utc': value['survey']['start_utc'],
                                'observing_end_utc': value['survey']['end_utc']}]
    return value


def snapshot(now='2031-01-01T00:59:00Z', result=None, messages=None, remaining=900.):
    return {'now_utc': now, 'observe_action_index': 0, 'last_result': result,
            'new_messages': messages or [], 'active_requests': [],
            'wallclock': {'remaining_seconds': remaining}}


class TailBase:
    def __init__(self, data):
        self.initial = data
        self.calls = 0
        self.C, self.E = .41, .33
        self.pending = {'preserve': True}
        self.remote = None

    def decide(self, state):
        self.calls += 1
        return copy.deepcopy(self.initial.get('fixture_action', {'action': 'wait', 'until_utc': self.initial['survey']['end_utc']}))

    def summary(self):
        return {'decisions': self.calls}


def guard_checks():
    checks = []
    data = initial()
    guard = mod.TerminalReportGuard(data, enabled=True)
    terminal = {'action': 'wait', 'until_utc': data['survey']['end_utc']}
    observe = {'action': 'observe', 'duration_seconds': 60, 'program': 'DARK',
               'pointing': {'alt_deg': 50., 'az_deg': 120.},
               'assignments': {'0': data['targets']['rows'][0][0]}}
    assert guard.propose(snapshot(now='2031-01-01T00:58:00Z'), observe) == observe
    checks.append('nonterminal action unchanged')
    earlier_night=copy.deepcopy(data)
    earlier_night['survey']['nights'][0]['observing_end_utc']='2031-01-01T00:59:30Z'
    clipped=mod.TerminalReportGuard(earlier_night, enabled=True)
    assert clipped.terminal_kind(snapshot(),observe) is None
    assert guard.terminal_kind(snapshot(),observe)=='observe'
    gap=copy.deepcopy(data)
    gap['survey']['nights'][0]['observing_end_utc']='2031-01-01T00:58:30Z'
    assert mod.TerminalReportGuard(gap,enabled=True).terminal_kind(snapshot(),observe)=='observe'
    checks.append('official occupied-night clipping rejects earlier-night tail; final-night and gap effective ends match')
    guard.false_count = int(data['scoring']['reporting']['false_report_free_allowance'])
    assert guard.propose(snapshot(), terminal) == terminal
    checks.append('false quota exhaustion rejects')
    guard.false_count = 0
    guard.consecutive_reports = int(data['scoring']['reporting']['max_consecutive_reports'])
    assert guard.propose(snapshot(), terminal) == terminal
    checks.append('consecutive request quota rejects')
    guard.consecutive_reports = 0
    assert guard.propose(snapshot(remaining=10.01), terminal, time.perf_counter()-1.) == terminal
    checks.append('post-selection wallclock reserve rejects')
    target = data['targets']['rows'][0][0]
    publication = {'record_type': 'observation_request', 'request_id': 'Q',
                   'completion_factor_threshold': .5, 'completion_reward': 100.}
    completed = {'record_type': 'observation_request_result', 'request_id': 'Q',
                 'completed_target_ids': [target], 'revised': False}
    guard.ingest(snapshot(messages=[publication, completed]))
    assert guard.uniformity_harm_bound(observe) == 0.
    guard.ingest(snapshot(messages=[{**completed, 'completed_target_ids': [], 'revised': True}]))
    assert guard.uniformity_harm_bound(observe) == data['scoring']['uniformity']['weight']
    checks.append('request result without threshold uses publication and replacement revokes proof')
    guard.ingest(snapshot(messages=[completed]))
    assert guard.uniformity_harm_bound(observe) == 0.
    resync = {'record_type': 'state_resync', 'invalidated_window': {
              'action_index_start': 0, 'action_index_end_exclusive': 1}, 'observation_requests': []}
    guard.ingest(snapshot(messages=[resync]))
    assert guard.uniformity_harm_bound(observe) == data['scoring']['uniformity']['weight']
    checks.append('resync conservatively revokes stale request certificates')
    Wrapped = mod.make_policy_class(TailBase, enabled=True)
    actor = Wrapped(data)
    assert actor.decide(snapshot()) == {'action': 'report'}
    frozen = copy.deepcopy((actor.C, actor.E, actor.pending, actor.calls))
    ack = snapshot(result={'action': 'report', 'correct': True, 'repaired': True, 'score_delta': 100.})
    assert actor.decide(ack) == terminal
    assert (actor.C, actor.E, actor.pending, actor.calls) == frozen
    assert actor.decide(snapshot()) == terminal and actor.terminal_guard.report_count == 1
    checks.append('one inserted report releases exact tail without actor report ingestion')
    for change in ({'now_utc': '2031-01-01T00:59:01Z'}, {'observe_action_index': 1},
                   {'last_result': {'action': 'report', 'correct': False, 'score_delta': -150.}}):
        actor = Wrapped(data)
        assert actor.decide(snapshot()) == {'action': 'report'}
        bad = snapshot(result={'action': 'report', 'correct': False, 'score_delta': 0.})
        bad.update(change)
        try:
            actor.decide(bad)
        except RuntimeError:
            pass
        else:
            raise AssertionError('invalid report acknowledgement released a frozen tail')
    checks.append('changed UTC/rank or settlement cannot release frozen tail')
    return checks


def official_packet(kind, correct, enabled):
    data = initial()
    start, end = map(runner._parse_utc, (data['survey']['start_utc'], data['survey']['end_utc']))
    instrument = data['instrument']
    fiber = {'field': {k: instrument[k] for k in ('n_fibers', 'fiber_area_deg2', 'gap_deg')},
             'exposure': instrument['exposure']}
    if kind == 'finish':
        tail = {'action': 'finish'}
    elif kind in ('observe','night_clip'):
        tail = {'action': 'observe', 'duration_seconds': 60, 'program': 'DARK',
                'pointing': {'alt_deg': 50., 'az_deg': 120.}, 'assignments': {}}
        data['scoring']['uniformity']['weight'] = 0.
    else:
        tail = {'action': 'wait', 'until_utc': data['survey']['end_utc']}
    data['fixture_action'] = tail
    columns = data['targets']['columns']
    targets = [dict(zip(columns, row)) for row in data['targets']['rows']]
    # Explicit fixture damage; this is never a real card's fault correctness.
    fault = ScoreEvent('synthetic-fault', 'instrument_fault', start, end, 'ALL',
                       None, None, None, None, 1., 1., 1., .4)
    scenario = runner.Scenario(
        config={'name': 'synthetic-terminal-contract', 'site': data['site'],
                'minimum_altitude_deg': data['site']['minimum_altitude_deg'],
                'products': {'footprint_csv': 'synthetic-footprint.csv'}},
        scenario_dir=HERE, site=data['site'], fiber_config=fiber, score_config=data['scoring'],
        targets=targets, slots=[SlotTruth('SYNTH-S001', start, end, True, 1., 1., 1., .4 if correct else 1.)],
        events=[fault] if correct else [], bulletins=[], forecasts=[], observation_requests=[],
        stress_rows=[], survey_start=start, survey_end=end)
    if kind=='night_clip':
        middle=runner._parse_utc('2031-01-01T00:59:30Z')
        later=runner._parse_utc('2031-01-01T00:59:45Z')
        data['survey']['nights']=[{'observing_start_utc':data['survey']['start_utc'],
                                  'observing_end_utc':'2031-01-01T00:59:30Z'},
                                 {'observing_start_utc':'2031-01-01T00:59:45Z',
                                  'observing_end_utc':data['survey']['end_utc']}]
        from dataclasses import replace
        scenario=replace(scenario,slots=[SlotTruth('EARLY-S001',start,middle,True,1.,1.,1.,1.),
                                        SlotTruth('FINAL-S001',later,end,True,1.,1.,1.,1.)])
    actor = mod.make_policy_class(TailBase, enabled=enabled)(data)
    inputs, responses = [], []
    def factory(context):
        def decide(state):
            sequence = len(inputs)+1
            request = V4Workflow.request_message(sequence, state, 0., 900.)
            inputs.append(request)
            action = actor.decide(request['payload'])
            response = {'protocol_version': 'participant-agent-protocol-v4',
                        'message_type': 'decision_response', 'decision_sequence': sequence, **action}
            responses.append(response)
            return V4Workflow.action_from_response(response, sequence)
        return decide
    name = f'{kind}_{int(correct)}_{int(enabled)}'
    out = HERE/'official_synthetic_packets'/name
    out.mkdir(parents=True, exist_ok=True)
    scenario_path = out/'synthetic_fixture.json'
    scenario_path.write_text(json.dumps({'synthetic_only': True, 'kind': kind, 'correct': correct})+'\n')
    with patch.object(runner, 'load_scenario', return_value=scenario), patch.object(runner, '_read_csv', return_value=[]):
        result = runner.run_scenario(scenario_path, factory, out)
    result.pop('organizer_only', None)
    (out/'public_input.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in inputs))
    (out/'public_output.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in responses))
    if enabled:
        offset=1 if kind=='night_clip' else 0
        expected=['observe','report','observe'] if kind=='night_clip' else ['report',kind]
        assert [r['action'] for r in responses] == expected
        assert inputs[offset]['payload']['now_utc'] == inputs[offset+1]['payload']['now_utc']
        assert inputs[offset]['payload']['observe_action_index'] == inputs[offset+1]['payload']['observe_action_index']
        assert inputs[offset+1]['payload']['last_result']['correct'] == correct
        assert responses[offset+1]['action'] == tail['action'] and actor.calls == offset+1
        if kind=='night_clip':
            assert inputs[1]['payload']['now_utc']=='2031-01-01T00:59:30Z'
            assert inputs[1]['payload']['observe_action_index']==1
    else:
        assert [r['action'] for r in responses] == [kind]
    assert result['termination']['reason'] == ('agent_finished' if kind == 'finish' else 'survey_complete')
    return result


def main():
    checks = guard_checks()
    packets = []
    for kind in ('wait', 'observe', 'finish'):
        for correct in (False, True):
            control = official_packet(kind, correct, False)
            intervention = official_packet(kind, correct, True)
            delta = intervention['total']-control['total']
            assert delta == (100. if correct else 0.)
            packets.append({'kind': kind, 'synthetic_correct': correct, 'total_delta': delta,
                            'runner_loop_and_report_code_unchanged': True})
    clipped=official_packet('night_clip',False,True)
    assert clipped['counts']['observe_actions']==2 and clipped['counts']['decisions']==3
    result = {'schema': 'request-terminal-official-short-check-v1', 'passed': True,
              'guard_checks': checks, 'official_packets': packets,
              'official_earlier_night_clipping_then_gap_packet_passed':True,
              'real_card_loaded': False, 'real_card_truth_read': False,
              'synthetic_weather_fixture_only': True, 'real_score_gain_claimed': False}
    (HERE/'official_short_checks.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'passed': True, 'guard_checks': len(checks), 'official_paired_packets': len(packets),
                      'real_card_truth_read': False, 'real_score_gain_claimed': False}))


if __name__ == '__main__':
    main()
