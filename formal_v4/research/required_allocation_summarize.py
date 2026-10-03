#!/usr/bin/env python3
"""Score and calendar diagnostics for the locked public-input experiment."""
import csv
from decimal import Decimal
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / 'results/required_allocation_20261003'


def ledger(folder):
    factors, scores = {}, {}
    for row in csv.DictReader((folder / 'observations.csv').open()):
        if row['valid'] != 'true':
            continue
        target = row['target_id']
        factors[target] = max(factors.get(target, 0.), float(row['factor']))
        scores[target] = max(scores.get(target, 0.), float(row['score']))
    durations = [int(row['duration_seconds']) for row in csv.DictReader((folder / 'decisions.csv').open()) if row['action'] == 'observe']
    return factors, scores, dict(exposures=len(durations), exposure_seconds=sum(durations),
                               below_300_seconds=sum(d < 300 for d in durations),
                               below_600_seconds=sum(d < 600 for d in durations),
                               targets_raw_half=sum(f >= .5 for f in factors.values()),
                               targets_raw_full=sum(f >= .99 for f in factors.values()))


def main():
    comparisons = []
    for card in ('L1', 'L2', 'L3', 'L4'):
        folders = [OUT / 'final' / mode / card for mode in ('control', 'allocation')]
        if not all((d / 'experiment_summary.json').exists() for d in folders):
            continue
        reports = [json.loads((d / 'experiment_summary.json').read_text()) for d in folders]
        control, candidate = reports
        ledgers = [ledger(d) for d in folders]
        rows = list(csv.DictReader((BASE / 'upstream/gosim-observer-examples/local-cards' / card / 'public/targets.csv').open()))
        required = {r['target_id'] for r in rows if r['required'].lower() == 'true'}
        missing = [required - {tid for tid, f in values[0].items() if f >= .5} for values in ledgers]
        history = json.loads((folders[1] / 'allocation_history.json').read_text())
        expired = sum(sum(r['start'] < h['now'] - 1e-7 for r in h['reservations']) for h in history)
        comparisons.append(dict(card=card, control=control['total'], allocation=candidate['total'],
             delta=float(Decimal(str(candidate['total'])) - Decimal(str(control['total']))),
             component_delta={k: float(Decimal(str(candidate['components'][k])) - Decimal(str(control['components'][k]))) for k in control['components']},
             required_missing=[control['counts']['required_missing'], candidate['counts']['required_missing']],
             required_saved=sorted(missing[0] - missing[1]), required_lost=sorted(missing[1] - missing[0]),
             control_seconds=control['seconds'], allocation_seconds=candidate['seconds'],
             control_ledger_stats=ledgers[0][2], allocation_ledger_stats=ledgers[1][2],
             calendar_stats={k: v for k, v in candidate['allocation_summary'].items() if k != 'forced_ids'},
             expired_starts_in_match_history=expired,
             source_identical=control['source_sha256'] == candidate['source_sha256'],
             termination=[r['termination']['reason'] for r in reports]))
    result = dict(deployment_rejected_on_fixed_L2_validation=True,
                  validation_card='L2', heldout_cards=['L3', 'L4'],
                  no_heldout_parameter_selection=True, comparisons=comparisons,
                  complete=len(comparisons) == 4,
                  source_identical_all=all(r['source_identical'] for r in comparisons),
                  all_survey_complete=all(all(t == 'survey_complete' for t in r['termination']) for r in comparisons))
    if comparisons:
        n = Decimal(len(comparisons))
        for key in ('control', 'allocation', 'delta'):
            result['mean_' + key] = str(sum(Decimal(str(r[key])) for r in comparisons) / n)
    (OUT / 'paired_summary.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
