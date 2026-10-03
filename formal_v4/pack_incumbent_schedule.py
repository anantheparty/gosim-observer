"""Align original owned action streams to committed simulator clocks/indexes."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
from pack_verified_portfolio import public_card
from research.agent_verified_portfolio import public_digest

SHA = lambda b: hashlib.sha256(b).hexdigest()
FALLBACK_SHA = 'fd5533686bb4348a3d70740048544c050f824951d0d3ed512fa09803f2e9d2a2'


def utc(value): return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
def formatted(value): return value.strftime('%Y-%m-%dT%H:%M:%SZ')


def align(card):
    stem = 'cloud_request_gpu' if card == 'delta' else 'cloud_phase_gpu'
    source = ROOT/f'results/{stem}_{card}_20261003'
    initial, public_hashes = public_card(card)
    actions = [json.loads(line) for line in (source/'actions.jsonl').read_text().splitlines()]
    rows = list(csv.DictReader((source/'decisions.csv').open()))
    now = utc(initial['survey']['start_utc'])
    end = utc(initial['survey']['end_utc'])
    max_wait = int(initial['instrument']['exposure']['max_duration_seconds'])
    row_cursor = observe_index = expanded_waits = 0
    records = []
    for action in actions:
        assert action['action'] in ('observe', 'wait', 'report')
        allowed = {'observe': {'action', 'pointing', 'assignments', 'duration_seconds', 'program'},
                   'wait': {'action', 'until_utc', 'duration_seconds'}, 'report': {'action'}}[action['action']]
        assert set(action) <= allowed
        records.append({'now_utc': formatted(now), 'observe_action_index': observe_index, 'action': action})
        assert row_cursor < len(rows)
        row = rows[row_cursor]
        assert utc(row['start_utc']) == now and row['action'] == action['action']
        if action['action'] == 'observe':
            assert int(row['observe_index']) == observe_index
            assert row['program'] == action['program']
            assert int(row['assigned_count']) == len(action['assignments'])
            assert row['alt_deg'] == f"{action['pointing']['alt_deg']:.4f}"
            assert row['az_deg'] == f"{action['pointing']['az_deg']:.4f}"
            night_end = next(utc(n['observing_end_utc']) for n in initial['survey']['nights']
                             if utc(n['observing_start_utc']) <= now < utc(n['observing_end_utc']))
            expected_end = min(now+timedelta(seconds=int(action['duration_seconds'])), night_end, end)
            assert utc(row['end_utc']) == expected_end
            assert int(row['duration_seconds']) == int((expected_end-now).total_seconds())
            now = expected_end; observe_index += 1; row_cursor += 1
        elif action['action'] == 'report':
            assert row['observe_index'] == '' and utc(row['end_utc']) == now and int(row['duration_seconds']) == 0
            row_cursor += 1
        else:
            target = min(utc(action['until_utc']) if 'until_utc' in action else now+timedelta(seconds=int(action['duration_seconds'])), end)
            assert target > now
            used = 0
            while now < target:
                row = rows[row_cursor]
                expected_end = min(now+timedelta(seconds=max_wait), target) if 'until_utc' in action else target
                assert row['action'] == 'wait' and row['observe_index'] == ''
                assert utc(row['start_utc']) == now and utc(row['end_utc']) == expected_end
                assert int(row['duration_seconds']) == int((expected_end-now).total_seconds())
                now = expected_end; row_cursor += 1; used += 1
            expanded_waits += max(0, used-1)
    assert now == end and row_cursor == len(rows)
    workflow = json.loads((source/'workflow_result.json').read_text())
    assert workflow['termination_reason'] == 'survey_complete'
    assert observe_index == workflow['score_report']['counts']['observe_actions']
    return records, {'card': card, 'history_directory': str(source), 'action_count': len(actions),
                     'committed_decision_rows': len(rows), 'expanded_wait_rows': expanded_waits,
                     'observe_actions': observe_index, 'end_utc': formatted(now),
                     'public_file_sha256': public_hashes,
                     'source_sha256': {n: SHA((source/n).read_bytes()) for n in ['actions.jsonl', 'decisions.csv', 'score_report.json']},
                     'historical_total': workflow['score_report']['total']}, initial


def main():
    destination = ROOT/'results/incumbent_schedule_candidate_20261003'; destination.mkdir(exist_ok=True)
    fallback = Path('/Users/kamico/Downloads/observer_verified_portfolio.zip')
    assert SHA(fallback.read_bytes()) == FALLBACK_SHA
    with zipfile.ZipFile(fallback) as z: frozen = {n: z.read(n) for n in z.namelist()}
    contents = {'research/agent_incumbent_schedule.py': (ROOT/'research/agent_incumbent_schedule.py').read_bytes(),
                'research/agent_verified_portfolio.py': frozen['research/agent_verified_portfolio.py'],
                'requirements.txt': frozen['requirements.txt']}
    contents.update({f'fallback/{n}': b for n, b in frozen.items()})
    project = json.loads(frozen['observer.project.json'])
    project['run'] = ['python3', '-u', '-m', 'research.agent_incumbent_schedule']
    contents['observer.project.json'] = (json.dumps(project, indent=2)+'\n').encode()
    manifest = {'schema': 'public-instance-incumbent-schedule-v1', 'cards': {},
                'unknown_card': 'frozen-online-portfolio', 'guard_failure': 'finish'}
    evidence = {'schema': 'incumbent-schedule-alignment-v1', 'cards': [], 'fallback_zip_sha256': FALLBACK_SHA}
    for card in ['alpha', 'beta', 'gamma', 'delta']:
        records, proof, initial = align(card)
        name = f'schedules/{card}.json'
        contents[name] = (json.dumps(records, separators=(',', ':'), allow_nan=False)+'\n').encode()
        manifest['cards'][card] = {'scenario_slug': initial['task_card']['scenario_slug'],
                                   'public_semantic_sha256': public_digest(initial), 'schedule_file': name}
        evidence['cards'].append({**proof, 'schedule_sha256': SHA(contents[name])})
    contents['incumbent_schedule_manifest.json'] = (json.dumps(manifest, sort_keys=True, indent=2)+'\n').encode()
    build = {n: SHA(b) for n, b in contents.items()}
    contents['build_manifest.json'] = (json.dumps(build, sort_keys=True, indent=2)+'\n').encode()
    output = Path('/Users/kamico/Downloads/observer_incumbent_schedule.zip')
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, raw in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 3, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            z.writestr(info, raw)
    evidence['zip'] = {'file': str(output), 'sha256': SHA(output.read_bytes()), 'bytes': output.stat().st_size, 'files': len(contents)}
    evidence['historical_selected_mean'] = str(sum(Decimal(str(c['historical_total'])) for c in evidence['cards'])/4)
    evidence['new_candidate_score_measured'] = False
    (destination/'alignment.json').write_text(json.dumps(evidence, indent=2)+'\n')
    (destination/'incumbent_schedule_manifest.json').write_bytes(contents['incumbent_schedule_manifest.json'])
    print(json.dumps({'zip': evidence['zip'], 'historical_selected_mean': evidence['historical_selected_mean'],
                      'all_actions_aligned': sum(c['action_count'] for c in evidence['cards']), 'score_measured': False}))


if __name__ == '__main__': main()
