"""Post hoc host-only loss diagnosis. This is never an actor policy or input."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
read_csv = lambda p: list(csv.DictReader(p.open()))
eps = .500001e-6
cards = {}
sources = {}
for card in ['L1', 'L2', 'L3']:
    season = ROOT / 'formal_v4/results' / ('request_geometry_integration_20261004' if card != 'L3' else 'request_terminal_pair_20261004') / 'seasons/control' / card
    data = ROOT / 'formal_v4/upstream/gosim-observer-examples/local-cards' / card
    paths = [data / 'truth/v4_events.csv', data / 'public/targets.csv', season / 'decisions.csv', season / 'observations.csv', season / 'messages.jsonl', season / 'score_report.json']
    sources.update({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    faults = [r for r in read_csv(paths[0]) if r['event_type'] == 'instrument_fault']
    targets = {r['target_id']: r for r in read_csv(paths[1])}
    decisions = {int(r['observe_index']): r for r in read_csv(paths[2]) if r['action'] == 'observe'}
    reports = [r for r in [json.loads(s) for s in paths[4].read_text().splitlines()] if r.get('record_type') == 'report_result']
    observed = {}
    repaired = {}
    before_lo, before_hi, after_lo, after_hi = {}, {}, {}, {}
    affected_hits = 0
    positive_hits = 0
    for row in read_csv(paths[3]):
        if row['valid'] != 'true':
            continue
        target_id, score = row['target_id'], float(row['score'])
        old_lo, old_hi = max(0., score - eps), score + eps
        new_lo, new_hi, new_score = old_lo, old_hi, score
        decision = decisions[int(row['observe_index'])]
        for fault in faults:
            start, end = fault['actual_start_utc'], fault['actual_end_utc']
            actual_repairs = [r['issued_at_utc'] for r in reports if r['correct'] and start <= r['issued_at_utc'] < end]
            stop = min(actual_repairs) if actual_repairs else end
            # Boundary-crossing exposures are deliberately unchanged. They can
            # only raise the fully repaired science contribution, not this loss.
            if start <= decision['start_utc'] < stop and decision['end_utc'] <= stop:
                multiplier = float(fault['instrument_efficiency_multiplier'])
                assert 0 < multiplier < 1
                scale = float(targets[target_id]['science_weight']) * float(row['prog_mult'])
                factor = float(row['factor'])
                new_score = scale * min(1., factor / multiplier)
                new_lo = max(old_lo, scale * min(1., max(0., factor - eps) / multiplier))
                new_hi = max(old_hi, scale * min(1., (factor + eps) / multiplier))
                affected_hits += 1
                positive_hits += new_score > score + eps
        for table, value in [(observed, score), (repaired, new_score), (before_lo, old_lo), (before_hi, old_hi), (after_lo, new_lo), (after_hi, new_hi)]:
            table[target_id] = max(table.get(target_id, 0.), value)
    cards[card] = {'fault_intervals_host_only': faults, 'actual_public_reports': reports, 'baseline_science_from_rounded_rows': sum(observed.values()), 'fixed_hit_trajectory_repair_science_delta_approx': sum(repaired.values()) - sum(observed.values()), 'conservative_rounding_delta_interval': [sum(after_lo.values()) - sum(before_hi.values()), sum(after_hi.values()) - sum(before_lo.values())], 'affected_valid_hits': affected_hits, 'individual_hits_increased': positive_hits}
result = {'schema': 'post-hoc-host-fixed-hit-science-loss-diagnostic-v1', 'purpose': 'Measure a mechanism capable of causing hundreds of points of loss; not actor triggers or measured deployable gain.', 'scope': 'Same actual hit set, original valid/invalid ledger and program multipliers; repair complete exposures before the first actual repair; crossing exposures unchanged.', 'future_data_used_for_host_diagnosis': True, 'future_data_used_by_actor': False, 'new_policy_evaluated': False, 'science_only': True, 'full_score_claim': None, 'L4_teacher_read': False, 'cards': cards, 'source_sha256': sources}
(BASE / 'HOST_DIAGNOSTIC.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({card: {key: row[key] for key in ['fixed_hit_trajectory_repair_science_delta_approx', 'conservative_rounding_delta_interval', 'affected_valid_hits']} for card, row in cards.items()}))
