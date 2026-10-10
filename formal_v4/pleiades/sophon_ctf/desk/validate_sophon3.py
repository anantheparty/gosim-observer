#!/usr/bin/env python3
"""Verify existing practice runs and mock the Johnny client. Does not launch runs or access network."""
import contextlib
import csv
import importlib.util
import io
import json
import os
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
DESK = ROOT / 'work/sophon_desk'
PACKAGE = ROOT / 'work/pkgs/sophon3'
sys.path.insert(0, str(PACKAGE))
import sophon_probe


def mock_johnny():
    pol = SimpleNamespace(nights=[1], ids=['x'], nfib=25)
    with patch.dict(os.environ, {'SAC_LOCAL_RUNNER': '1', 'SOPHON_RUN_TOKEN': 'test-only-value'}, clear=True), \
            patch.object(urllib.request, 'build_opener', side_effect=AssertionError('network forbidden')), \
            contextlib.redirect_stderr(io.StringIO()) as capture:
        p = sophon_probe.Probe(pol, {'johnny_enabled': True})
        p.contact('again')
        p.final()
        assert p.calls == 0 and not p.credential
        assert 'test-only-value' not in capture.getvalue()

    class Reply:
        code = 200
        def read(self, n):
            return b'{"message":"ok", "echo":"test-only-value"}'
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    class Opener:
        def open(self, req, timeout):
            assert json.loads(req.data) == {'token': 'test-only-value'}
            assert timeout == 8 and 'Authorization' not in req.headers
            return Reply()

    with patch.dict(os.environ, {'SOPHON_RUN_TOKEN': 'test-only-value'}, clear=True), \
            patch.object(urllib.request, 'build_opener', return_value=Opener()), \
            contextlib.redirect_stderr(io.StringIO()) as capture:
        p = sophon_probe.Probe(pol, {'johnny_enabled': True})
        p.contact('final')
        p.contact('excess')
        p.final()
        assert p.calls == 2
        assert 'test-only-value' not in capture.getvalue()
        assert 'johnny_response' in capture.getvalue()
    return 'PASS: local guard, exact body, timeout, two-call cap, response redaction; network mocked'


def budget_and_dive():
    from sophon_policy import Policy
    from astro import fmt_utc
    card = DESK / 'local/sophon-local'
    scenario = json.loads((card / 'config/v4_scenario.json').read_text())
    nights = list(csv.DictReader((card / 'public/v4_night_calendar.csv').open()))
    target = list(csv.DictReader((card / 'public/targets.csv').open()))[:1]
    init = {'site': scenario['site'], 'instrument': {'grid_side': 5, 'n_fibers': 25,
        'pitch_deg': 0.4 ** 0.5, 'glass_side_deg': 0.4 ** 0.5,
        'exposure': {'min_duration_seconds': 60, 'max_duration_seconds': 3600}},
        'survey': {'nights': nights, 'end_utc': nights[-1]['observing_end_utc']},
        'scoring': json.loads((card / 'config/v4_score_config.json').read_text()),
        'targets': {'columns': list(target[0]), 'rows': [list(target[0].values())]}}
    def snapshot(t, remaining=800):
        return {'now_utc': fmt_utc(t), 'wallclock': {'remaining_seconds': remaining}, 'last_result': {}}
    with patch.dict(os.environ, {'SAC_LOCAL_RUNNER': '1'}, clear=True), contextlib.redirect_stderr(io.StringIO()):
        p = Policy(init)
        t = p.dive_t
        a = p.decide(snapshot(t - 30))
        assert a['action'] == 'wait' and a['until_utc'] == fmt_utc(t)
        a = p.decide(snapshot(t))
        assert a['action'] == 'observe' and a['assignments'] == {} and a['pointing']['alt_deg'] > 0
        assert p.decide(snapshot(t + 60))['action'] == 'finish'
        p = Policy(init)
        a = p.decide(snapshot(p.starts[0], remaining=40))
        assert p.emergency and p.dive_t is not None
        if a['action'] == 'wait':
            a = p.decide(snapshot(p.dive_t, remaining=39))
        assert a['action'] == 'observe' and p.dove
        assert p.decide(snapshot(p.dive_t + 60, remaining=38))['action'] == 'finish'
    return 'PASS: sub-minimum time to dive waits exactly; final exposure terminates; budget reserve skips to visible planet'


def main():
    spec = importlib.util.spec_from_file_location('official_local_checker', DESK / 'local/check_sky.py')
    sky = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sky)
    card = DESK / 'local/sophon-local'
    nights = list(csv.DictReader((card / 'public/v4_night_calendar.csv').open()))
    schedule = [json.loads(l) for l in (card / 'truth/v4_sophon.jsonl').read_text().splitlines()]
    expected = {next(i for i, n in enumerate(nights) if n['night_id'] == s['night_id']):
        [''.join('#' if r * 5 + c in s['fiber_ids'] else '.' for c in range(5)) for r in range(4, -1, -1)]
        for s in schedule}
    result = {'johnny_mock': mock_johnny(), 'budget_and_dive': budget_and_dive(), 'runs': {}}
    for planet in ('jupiter', 'saturn', 'mars', 'venus'):
        run = DESK / 'validation' / ('sophon3_' + planet)
        with patch.object(sys, 'argv', ['check_sky.py', str(run), '--card', str(card), '--object', planet]), \
                contextlib.redirect_stdout(io.StringIO()) as capture:
            sky.main()
        checker = capture.getvalue().strip()
        assert 'SOPHON{local-sky-ok}' in checker and 'SOPHON{local-dive-ok}' in checker, checker
        logs = []
        for line in (run / 'agent.log').read_text().splitlines():
            try:
                logs.append(json.loads(line))
            except ValueError:
                pass
        glyphs = [r for r in logs if r.get('event') == 'sophon_glyph']
        matched = sum(r['rows'] == expected.get(r['night']) for r in glyphs)
        assert matched == len(expected) == len(glyphs), (planet, matched, len(glyphs))
        initial = next(r for r in logs if r.get('event') == 'sophon_init')
        assert initial['network_allowed'] is False and not initial['credential_present']
        assert not any(r.get('event') in ('johnny_response', 'johnny_error') for r in logs)
        workflow = json.loads((run / 'workflow_result.json').read_text())
        assert workflow['termination_reason'] == 'agent_finished'
        decisions = list(csv.DictReader((run / 'decisions.csv').open()))
        last = [d for d in decisions if d['action'] == 'observe'][-1]
        dive = next(r for r in logs if r.get('event') == 'sophon_dive')
        result['runs'][planet] = {'checker_output': checker, 'glyphs_matched': matched,
            'glyphs_scheduled': len(expected), 'termination': workflow['termination_reason'],
            'observe_actions': len([d for d in decisions if d['action'] == 'observe']),
            'last_start_utc': last['start_utc'], 'last_alt_deg': dive['altitude'],
            'last_assigned_count': last['assigned_count'],
            'accounted_wallclock_seconds': workflow['accounted_wallclock_seconds'],
            'agent_wallclock_seconds': workflow['agent_wallclock_seconds']}
    output = DESK / 'validation/sophon3_validation.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
