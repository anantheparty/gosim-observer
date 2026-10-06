#!/usr/bin/env python3
"""Build five A1 offline stress worlds; no engine, model, credentials or network.

Run from any directory: python work/logtest/mkstressworlds.py
All five destinations and both redacted variant directories must be new.
Only new paths under work/worlds and work/logtest are written. Existing world,
package, log, generator and run files are read-only. Uses mkvariantworld.build
for rewritten worlds; redacted controls clone GA1 to preserve physical truth
byte-for-byte, including mkguider's final event-end convention.
"""
from __future__ import annotations

import copy
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'work'
HERE = WORK / 'logtest'
VARIANTS = HERE / 'variants'
WORLDS = WORK / 'worlds'
REWRITES = ('engineering_table', 'bullet_workorders', 'cipher_words')
REDACTIONS = ('silent', 'noflat')
NAMES = REWRITES + REDACTIONS
REQUESTS = Path('truth/v4_observation_requests.jsonl')
EVENTS = Path('truth/v4_events.csv')
WEATHER = Path('truth/v4_weather_truth.csv')
SUMMARY = HERE / 'stress_worlds_A1_validation.json'

spec = importlib.util.spec_from_file_location('stress_mkvariantworld', WORK / 'mkvariantworld.py')
world = importlib.util.module_from_spec(spec)
spec.loader.exec_module(world)
# Pure text decoder/oracle only; no model imports or constructors, no bytecode writes.
sys.path.insert(0, str(WORK / 'pkgs/c31'))
from guider_log import GuiderLog, prep, GUIDER, FLAT, REL_FLAT


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_jsonl(path, values):
    with path.open('w', encoding='utf-8') as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')


def inventory(path):
    return {str(p.relative_to(path)): world.sha(p) for p in sorted(path.rglob('*')) if p.is_file()}


def tags(line):
    normalized = prep(line)
    return bool(GUIDER.search(normalized)), bool(FLAT.search(normalized)), bool(REL_FLAT.search(normalized))


def make_redacted(name, source_requests, source_truth):
    """Whole-line deletion, preserving every retained byte in the request reason."""
    requests = copy.deepcopy(source_requests)
    removed, shared = [], []
    counts = Counter()
    for request in requests:
        if not request['request_id'].startswith('V4LG'):
            continue
        kept = []
        original = request['reason']
        for number, raw in enumerate(original.splitlines(keepends=True), 1):
            guider, flat, relative = tags(raw)
            counts['source_lines'] += 1
            drop = (guider or flat) if name == 'silent' else (flat and not guider)
            if drop:
                counts['removed_lines'] += 1
                removed.append({'request_id': request['request_id'], 'line_number': number,
                                'guider': guider, 'flat': flat, 'text': raw.rstrip('\r\n')})
            else:
                kept.append(raw)
                counts['retained_lines'] += 1
                if guider and flat:
                    shared.append({'request_id': request['request_id'], 'line_number': number,
                                   'relative_fault_reference': relative, 'text': raw.rstrip('\r\n')})
        request['reason'] = ''.join(kept)
        if not request['reason'].strip():
            raise ValueError('Redaction would produce an empty reason: ' + request['request_id'])
    folder = VARIANTS / name
    folder.mkdir()
    log_path = folder / 'A1.log.txt'
    # A separating newline is necessary before each issued header. Worlds use
    # the exact filtered reasons above, without adding serialization newlines.
    with log_path.open('w', encoding='utf-8') as stream:
        for request in requests:
            if request['request_id'].startswith('V4LG'):
                body = request['reason']
                stream.write('#### issued ' + request['issued_at_utc'] + '\n' + body)
                if not body.endswith('\n'):
                    stream.write('\n')
    truth = copy.deepcopy(source_truth)
    truth.update(variant=name, description='GA1 physical truth, with ' + name + ' duty-log redaction',
                 truth_kind='Latent GA1 events, not a claim that the filtered logs disclose their times',
                 log_sha256=world.sha(log_path),
                 request_reason_source='GA1 reasons with whole lines removed; log serialization may add a final newline')
    write_json(folder / 'A1.truth.json', truth)
    audit = {'variant': name, 'source_world': str(WORLDS / 'GA1'), 'classification': 'c31 prep + GUIDER/FLAT',
             'filter': 'drop guider OR flat lines' if name == 'silent' else 'drop flat-only lines; keep all guider lines verbatim',
             'counts': dict(counts), 'removed_lines': removed, 'preserved_shared_lines': shared,
             'preserved_relative_fault_lines': sum(x['relative_fault_reference'] for x in shared),
             'note': 'noflat retains generic standing rules and relative fault references; it publishes no flat-window schedule'}
    write_json(folder / 'redaction.json', audit)
    return requests, truth, audit


def validate(name, reference_requests, source_truth, initial_reference_hashes):
    path = WORLDS / ('V_' + name + '_A1')
    reference = WORLDS / 'GA1'
    fields, events = world.read_csv(path / EVENTS)
    reference_fields, ref_events = world.read_csv(reference / EVENTS)
    assert fields == reference_fields
    assert len(events) == len(ref_events)
    event_differences = []
    for expected, actual in zip(ref_events, events):
        assert expected['event_id'] == actual['event_id']
        for key in fields:
            if expected[key] != actual[key]:
                event_differences.append({'event_id': actual['event_id'], 'field': key,
                                          'GA1': expected[key], 'world': actual[key]})
    _, slots = world.read_csv(reference / 'truth/v4_slots.csv')
    end = max(world.epoch(s['timestamp_utc']) + float(s['duration_seconds']) for s in slots)
    faults = [e for e in events if e['event_type'] == 'instrument_fault']
    assert [e['actual_start_utc'] for e in faults] == source_truth['faults_utc']
    assert all(e['event_id'].startswith('V4GF') and e['scope_type'] == 'ALL' and
               float(e['instrument_efficiency_multiplier']) == 0.3 for e in faults)
    if name in REDACTIONS:
        assert not event_differences
        assert world.sha(path / EVENTS) == world.sha(reference / EVENTS)
    else:
        assert event_differences == [{'event_id': faults[-1]['event_id'], 'field': 'actual_end_utc',
                                     'GA1': ref_events[-1]['actual_end_utc'], 'world': world.utc(end)}]
        assert world.epoch(event_differences[0]['GA1']) - end == 2700
    assert world.sha(path / WEATHER) == world.sha(reference / WEATHER)
    current_hashes = inventory(path)
    for rel, digest in initial_reference_hashes.items():
        if rel not in (str(REQUESTS), str(EVENTS)):
            assert current_hashes[rel] == digest, (name, rel)

    rows = read_jsonl(path / REQUESTS)
    by_id = {r['request_id']: r for r in rows}
    assert len(by_id) == len(rows) == len(reference_requests)
    issued = [world.epoch(r['issued_at_utc']) for r in rows]
    assert issued == sorted(issued)
    for original in reference_requests:
        row = by_id[original['request_id']]
        assert row.keys() == original.keys()
        if not original['request_id'].startswith('V4LG'):
            assert row == original
        else:
            assert {k: v for k, v in row.items() if k != 'reason'} == {k: v for k, v in original.items() if k != 'reason'}
            assert row['completion_reward'] == 0.0 and row['reason'].strip()
            if name in REDACTIONS:
                lines = original['reason'].splitlines(keepends=True)
                wanted = [ln for ln in lines if not ((tags(ln)[0] or tags(ln)[1]) if name == 'silent'
                                                     else (tags(ln)[1] and not tags(ln)[0]))]
                assert row['reason'] == ''.join(wanted)
    logs = [r for r in rows if r['request_id'].startswith('V4LG')]
    if name in REWRITES:
        blocks = world.log_blocks(VARIANTS / name / 'A1.log.txt')
        assert [(r['issued_at_utc'], r['reason']) for r in logs] == blocks
    parser_summary = None
    if name in REDACTIONS:
        reader = GuiderLog(-4)
        for row in logs:
            reader.read(row['reason'], world.epoch(row['issued_at_utc']))
        assert not reader.flats, 'Redacted logs still disclose flat windows'
        if name == 'silent':
            assert not reader.active and not reader.cands and not reader.due() and not reader.probes()
        parser_summary = {'active': reader.active, 'faults_due': len(reader.due()), 'probes': len(reader.probes()),
                          'flat_windows': len(reader.flats), 'pending_relative_flat_references': len(reader.rel_flat)}
    return {'world': str(path), 'reference': str(reference), 'passed': True,
            'fault_events': len(faults), 'flat_windows_in_truth': len(source_truth['flats_utc']),
            'weather_truth_byte_identical': True, 'event_columns_equal': True,
            'events_byte_identical': world.sha(path / EVENTS) == world.sha(reference / EVENTS),
            'event_differences': event_differences,
            'other_world_files_byte_identical': True, 'request_schema_and_metadata_equal': True,
            'base_requests_unchanged': len(rows) - len(logs), 'log_requests': len(logs),
            'parser_diagnostic_not_physical_truth': parser_summary}


def main():
    for path in [WORLDS / ('V_' + name + '_A1') for name in NAMES] + [VARIANTS / name for name in REDACTIONS] + [SUMMARY]:
        if path.exists() or path.is_symlink():
            raise SystemExit('Refusing to replace an existing path: ' + str(path))
    inputs = {name: inventory(WORLDS / name) for name in ('FA1', 'GA1')}
    variant_hashes = {name: {ext: world.sha(VARIANTS / name / ('A1.' + ext)) for ext in ('log.txt', 'truth.json')}
                      for name in REWRITES + ('original',)}
    source_requests = read_jsonl(WORLDS / 'GA1' / REQUESTS)
    source_truth = json.loads((VARIANTS / 'original/A1.truth.json').read_text(encoding='utf-8'))
    source_logs = [r for r in source_requests if r['request_id'].startswith('V4LG')]
    original_blocks = world.log_blocks(VARIANTS / 'original/A1.log.txt')
    assert [(t, body.rstrip('\r\n')) for t, body in original_blocks] == [(r['issued_at_utc'], r['reason']) for r in source_logs]
    reports = {}
    for name in REWRITES:
        reports[name] = world.build(WORLDS / 'FA1', VARIANTS / name, 'A1', WORLDS / ('V_' + name + '_A1'))
    for name in REDACTIONS:
        requests, truth, audit = make_redacted(name, source_requests, source_truth)
        dst = WORLDS / ('V_' + name + '_A1')
        shutil.copytree(WORLDS / 'GA1', dst)
        write_jsonl(dst / REQUESTS, requests)
        report = copy.deepcopy(reports[REWRITES[0]])
        report.update(base_world=str(WORLDS / 'GA1'), source_base_world=str(WORLDS / 'FA1'),
                      build_method='clone GA1 physical world; whole-line deletion from duty request reasons only',
                      variant_dir=str(VARIANTS / name), log_sha256=world.sha(VARIANTS / name / 'A1.log.txt'),
                      truth_sha256=world.sha(VARIANTS / name / 'A1.truth.json'),
                      removed_instrument_faults=0, restored_weather_slots=0,
                      fault_terminal_end_utc=world.read_csv(dst / EVENTS)[1][-1]['actual_end_utc'],
                      redaction_counts=audit['counts'], preserved_shared_lines=len(audit['preserved_shared_lines']),
                      preserved_relative_fault_lines=audit['preserved_relative_fault_lines'],
                      redaction_audit=str(VARIANTS / name / 'redaction.json'),
                      request_reason_source=truth['request_reason_source'])
        reports[name] = report
        write_json(dst / 'variant_world.json', report)
    checks = {}
    for name in NAMES:
        checks[name] = validate(name, source_requests, source_truth, inputs['GA1'])
        checks[name]['flat_weather_slots'] = reports[name]['flat_weather_slots']
        reports[name]['validation_against_GA1'] = checks[name]
        write_json(WORLDS / ('V_' + name + '_A1') / 'variant_world.json', reports[name])
    assert all(inventory(WORLDS / name) == inputs[name] for name in inputs), 'An input world changed'
    assert all(world.sha(VARIANTS / name / ('A1.' + ext)) == digest
               for name, hashes in variant_hashes.items() for ext, digest in hashes.items()), 'An input variant changed'
    result = {'created_utc': datetime.now(timezone.utc).isoformat(), 'worlds': checks,
              'input_world_hashes': inputs, 'input_worlds_unchanged': True, 'input_variants_unchanged': True,
              'source_parser_sha256': world.sha(WORK / 'pkgs/c31/guider_log.py'),
              'no_model_or_engine': True}
    write_json(SUMMARY, result)
    for name, c in checks.items():
        print(f"{Path(c['world']).name}: PASS; {c['fault_events']} faults; {c['flat_weather_slots']} flat slots; "
              f"{c['log_requests']} logs; GA1 event diffs={len(c['event_differences'])}; "
              f"parser={c['parser_diagnostic_not_physical_truth']}")
    print('Validation:', SUMMARY)


if __name__ == '__main__':
    main()
