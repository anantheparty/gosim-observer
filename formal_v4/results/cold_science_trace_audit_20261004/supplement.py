#!/usr/bin/env python3
"""Reproduce public-calendar budgets, class statistics and quality hurdles."""
import collections
import csv
import hashlib
import json
import statistics
import zipfile
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
summary = json.loads((OUT / 'summary.json').read_text())
batch = json.loads((ROOT / 'formal_v4/results/cloud_request_cache_batch_20261003/summary.json').read_text())
dt = lambda value: datetime.fromisoformat(value.replace('Z', '+00:00'))


def rows(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def csvout(name, data):
    with (OUT / name).open('w', newline='') as f:
        w = csv.DictWriter(f, list(dict.fromkeys(k for r in data for k in r)))
        w.writeheader()
        w.writerows(data)


deadlines = []
class_stats = []
hurdles = {}
prior = []
for card in ('alpha', 'beta', 'gamma', 'delta'):
    source = ROOT / f'formal_v4/results/cloud_request_cache_{card}_20261003'
    ds = rows(source / 'decisions.csv')
    cal = rows(ROOT / f'formal_v4/practice_cards/{card}/{card}/public/v4_night_calendar.csv')
    end = dt(ds[-1]['end_utc'])
    total = sum(int(n['night_seconds']) for n in cal)
    remaining = sum(max(0, (dt(n['observing_end_utc']) - max(end, dt(n['observing_start_utc']))).total_seconds()) for n in cal)
    workflow = json.loads((source / 'workflow_result.json').read_text())
    b = batch.get('cards', {}).get(card, {})
    deadlines.append({'card': card, 'night_seconds': total, 'remaining_night_seconds': remaining,
                      'night_time_progress': 1 - remaining / total,
                      'whole_nights_unstarted': sum(dt(n['observing_start_utc']) > end for n in cal),
                      'simulation_wall_progress': (end - dt(cal[0]['observing_start_utc'])).total_seconds() /
                                                  (dt(cal[-1]['observing_end_utc']) - dt(cal[0]['observing_start_utc'])).total_seconds(),
                      'workflow': {k: v for k, v in workflow.items() if k not in ('score_report', 'report')},
                      'policy_summary': b.get('final_policy_summary')})
    tr = rows(OUT / f'{card}_targets.csv')
    hr = rows(OUT / f'{card}_hit_marginals.csv')
    counts = collections.Counter(r['target_id'] for r in hr)
    by = collections.defaultdict(list)
    for r in hr:
        by[r['target_id']].append(r)
    for cls in ('BGS', 'ELG', 'LRG', 'QSO', 'Star'):
        group = [r for r in tr if r['class'] == cls]
        covered = [r for r in group if r['covered'] == 'True']
        hits = [r for r in hr if r['class'] == cls]
        repeat = [r for r in hits if r['is_repeat'] == 'True']
        class_stats.append({'card': card, 'class': cls,
                            'catalog_flux_median': statistics.median(float(r['flux']) for r in group),
                            'covered_best_duration_median': statistics.median(float(r['best_duration']) for r in covered),
                            'covered_best_quality_mean': statistics.mean(float(r['best_quality']) for r in covered),
                            'single_visit_covered': sum(counts[r['target_id']] == 1 for r in covered),
                            'covered_factor_lt_0_5': sum(float(r['max_valid_factor']) < .5 for r in covered),
                            'first_visit_gain': sum(float(r['gain']) for r in hits if r['is_repeat'] == 'False'),
                            'repeat_gain': sum(float(r['gain']) for r in repeat),
                            'repeat_raw': sum(float(r['score']) for r in repeat),
                            'valid_hit_rows': len(hits), 'repeat_hit_rows': len(repeat)})
    under = []
    for t in tr:
        if float(t['max_valid_factor']) >= .5 or t['covered'] != 'True':
            continue
        maxq = max(float(o['quality']) for o in by[t['target_id']])
        qneed = .0625 / float(t['flux'])  # .5 * 450 / 3600 / flux
        under.append({'target_id': t['target_id'], 'class': t['class'], 'required': t['required'] == 'True',
                      'max_factor': float(t['max_valid_factor']), 'max_observed_quality': maxq,
                      'quality_needed_for_factor0_5_at3600': qneed,
                      'can_reach0_5_at_same_max_q_with3600': maxq >= qneed,
                      'max_factor_at3600_same_maxq': min(1, float(t['flux']) * 3600 * maxq / 450)})
    csvout(f'{card}_underexposed_conditioned_quality.csv', under)
    hurdles[card] = {'under0_5': len(under),
                     'recorded_quality_sufficient_for_factor0_5_at3600': sum(r['can_reach0_5_at_same_max_q_with3600'] for r in under),
                     'by_class': {c: {'under0_5': sum(r['class'] == c for r in under),
                                      'recorded_quality_sufficient': sum(r['class'] == c and r['can_reach0_5_at_same_max_q_with3600'] for r in under)}
                                  for c in ('BGS', 'ELG', 'LRG', 'QSO', 'Star')},
                     'required_under0_5': [r for r in under if r['required']]}
    old = ROOT / f'formal_v4/results/cloud_request_gpu_{card}_20261003'
    old_report = json.loads((old / 'score_report.json').read_text())
    old_workflow = json.loads((old / 'workflow_result.json').read_text())
    prior.append({'card': card, 'source': str(old.relative_to(ROOT)), 'prior_total': old_report['total'],
                  'prior_components': old_report['components'], 'prior_termination': old_report['termination'],
                  'prior_end': rows(old / 'decisions.csv')[-1]['end_utc'],
                  'prior_accounted': old_workflow['accounted_wallclock_seconds'],
                  'prior_agent': old_workflow['agent_wallclock_seconds'],
                  'current_science_gain': summary[card]['official_components']['sum_best_scores'] - old_report['components']['sum_best_scores'],
                  'byte_equality': {f: (old / f).read_bytes() == (source / f).read_bytes()
                                    for f in ('actions.jsonl', 'decisions.csv', 'messages.jsonl', 'observations.csv', 'score_report.json')}})

csvout('class_trace_stats.csv', class_stats)
for name, data in [('deadline_budget.json', deadlines), ('duration_quality_hurdle.json', hurdles), ('prior_official_comparison.json', prior)]:
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
zpath = Path('/Users/kamico/Downloads/observer_request_exact_cache.zip')
z = zipfile.ZipFile(zpath)
build = json.loads(z.read('build_manifest.json'))
package = {'zip_path': str(zpath), 'zip_sha256': hashlib.sha256(zpath.read_bytes()).hexdigest(),
           'bytes': zpath.stat().st_size, 'files': len(z.namelist()),
           'official_source_fingerprint': batch['official_source_fingerprint'],
           'build_manifest_member_checks': {k: hashlib.sha256(z.read(k)).hexdigest() == v for k, v in build.items()},
           'entrypoint': json.loads(z.read('observer.project.json')),
           'runtime': json.loads(z.read('remote_runtime.json')),
           'zip_provenance': json.loads(z.read('exact_cache_provenance.json'))}
(OUT / 'package_provenance.json').write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'deadline_progress': [(r['card'], r['night_time_progress']) for r in deadlines],
                  'zip_sha256': package['zip_sha256'], 'all_build_members_match': all(package['build_manifest_member_checks'].values())}))
