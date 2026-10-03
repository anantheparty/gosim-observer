#!/usr/bin/env python3
"""Offline audit of participant-visible official RequestCache outputs only.

No runner execution, new simulations, hidden weather, event truth, or opponent
actions. Exposure-duration diagnostics condition on realized mean quality and
are descriptions, not prospective counterfactual scores.
"""
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
CARDS = ('alpha', 'beta', 'gamma', 'delta')


def read_csv(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def pct(num, den):
    return num / den if den else 0.0


def quantiles(values):
    values = sorted(values)
    if not values:
        return {}
    def q(p):
        pos = p * (len(values) - 1)
        lo = math.floor(pos)
        return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (pos - lo)
    return {str(p): q(p) for p in (0, .1, .25, .5, .75, .9, .95, 1)}


def dump_csv(name, rows):
    if rows:
        keys = list(dict.fromkeys(k for row in rows for k in row))
        with (OUT / name).open('w', newline='') as f:
            wr = csv.DictWriter(f, keys)
            wr.writeheader()
            wr.writerows(rows)


def catalog_group(cat, best, maxf, ids):
    ids = list(ids)
    covered = [i for i in ids if i in best]
    weighted_all = sum(cat[i]['w'] for i in ids)
    weighted_cov = sum(cat[i]['w'] for i in covered)
    base = sum(cat[i]['w'] * best[i]['factor'] for i in covered)
    science = sum(best[i]['score'] for i in covered)
    return {
        'catalog_count': len(ids), 'catalog_weight': weighted_all,
        'covered_count': len(covered), 'covered_weight': weighted_cov,
        'weighted_coverage': pct(weighted_cov, weighted_all),
        'factor_ge_0_5_count': sum(maxf.get(i, 0) >= .5 for i in ids),
        'factor_ge_0_5_weight': sum(cat[i]['w'] for i in ids if maxf.get(i, 0) >= .5),
        'factor_ge_0_95_count': sum(maxf.get(i, 0) >= .95 for i in ids),
        'factor_eq_1_count': sum(maxf.get(i, 0) >= 1 - 1e-6 for i in ids),
        'best_base_weighted_factor': base,
        'best_mean_factor_weighted': pct(base, weighted_cov),
        'science': science, 'science_per_covered_weight': pct(science, weighted_cov),
        'effective_program_mult': pct(science, base),
        'program_bonus': science - base,
        # Algebraic ceiling; does not imply simultaneous feasibility.
        'uncovered_ceiling_gap': 1.2 * (weighted_all - weighted_cov),
        'covered_unsaturation_ceiling_gap': 1.2 * (weighted_cov - base),
        'covered_program_ceiling_gap': 1.2 * base - science,
    }


all_summary = {}
all_provenance = []
for card in CARDS:
    source = ROOT / f'formal_v4/results/cloud_request_cache_{card}_20261003'
    public = ROOT / f'formal_v4/practice_cards/{card}/{card}'
    report = json.loads((source / 'score_report.json').read_text())
    manifest = json.loads((source / 'archive_manifest.json').read_text())
    config = json.loads((public / 'config/v4_score_config.json').read_text())
    catrows = read_csv(public / 'public/targets.csv')
    cat = {r['target_id']: {'w': float(r['science_weight']), 'flux': float(r['feature_flux']),
                           'class': r['target_class'], 'required': r['required'] == 'true',
                           'ra': float(r['ra_deg'])} for r in catrows}
    ds = read_csv(source / 'decisions.csv')
    observe = {int(d['observe_index']): d for d in ds if d['action'] == 'observe'}
    for d in observe.values():
        d['duration'] = int(d['duration_seconds'])
        d['start'] = utc(d['start_utc'])
        d['end'] = utc(d['end_utc'])
    ms = read_jsonl(source / 'messages.jsonl')
    os = read_csv(source / 'observations.csv')
    for o in os:
        for k in ('factor', 'quality', 'prog_mult', 'score'):
            o[k] = float(o[k])
        o['observe_index'] = int(o['observe_index'])
        o['valid'] = o['valid'] == 'true'
        o['duration'] = observe[o['observe_index']]['duration']
    by_action = defaultdict(list)
    for o in os:
        by_action[o['observe_index']].append(o)
    actions = read_jsonl(source / 'actions.jsonl')
    submitted_observe = [a for a in actions if a['action'] == 'observe']
    action_alignment = len(submitted_observe) == len(observe)
    if action_alignment:
        action_alignment = all(a['duration_seconds'] == d['duration'] and len(a['assignments']) == int(d['assigned_count'])
                               for a, d in zip(submitted_observe, observe.values()))
    for filename in ('actions.jsonl', 'agent.log', 'decisions.csv', 'messages.jsonl',
                     'observations.csv', 'score_report.json', 'workflow_result.json'):
        path = source / filename
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        all_provenance.append({'card': card, 'path': str(path.relative_to(ROOT)), 'sha256': sha,
                               'matches_archive': sha == manifest['file_sha256'][filename]})
    for path in (public / 'public/targets.csv', public / 'public/v4_night_calendar.csv',
                 public / 'config/v4_score_config.json'):
        all_provenance.append({'card': card, 'path': str(path.relative_to(ROOT)),
                               'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'matches_archive': ''})

    best = {}
    maxf = defaultdict(float)
    seen = set()
    gains = []
    action_stats = []
    for idx, d in observe.items():
        gain = raw = repeated_raw = first_raw = 0.0
        repeat_n = nongain_n = saturated_n = positive_n = 0
        row_count = 0
        for o in by_action[idx]:
            if not o['valid']:
                continue
            row_count += 1
            i = o['target_id']
            delta = max(0.0, o['score'] - best.get(i, {'score': 0})['score'])
            o['final_valid_chronological_gain'] = delta
            gains.append({'card': card, 'target_id': i, 'observe_index': idx,
                          'class': cat[i]['class'], 'weight': cat[i]['w'],
                          'flux': cat[i]['flux'], 'duration': d['duration'],
                          'score': o['score'], 'factor': o['factor'], 'quality': o['quality'],
                          'prog_mult': o['prog_mult'], 'is_repeat': i in seen, 'gain': delta})
            if i in seen:
                repeat_n += 1
                repeated_raw += o['score']
            else:
                first_raw += o['score']
            seen.add(i)
            if delta <= 1e-9:
                nongain_n += 1
            if o['factor'] >= 1 - 1e-6:
                saturated_n += 1
            if o['score'] > 0:
                positive_n += 1
            gain += delta
            raw += o['score']
            maxf[i] = max(maxf[i], o['factor'])
            if i not in best or o['score'] > best[i]['score']:
                best[i] = o
        action_stats.append({'card': card, 'observe_index': idx, 'start_utc': d['start_utc'],
                             'end_utc': d['end_utc'], 'duration': d['duration'], 'program': d['program'],
                             'assigned_count': int(d['assigned_count']), 'hit_count': int(d['hit_count']),
                             'final_valid': d['valid'] == 'true', 'valid_hit_count': row_count,
                             'positive_hit_count': positive_n, 'sat_hit_count': saturated_n,
                             'repeated_hit_count': repeat_n, 'nonimproving_hit_count': nongain_n,
                             'raw_score': raw, 'science_gain': gain,
                             'gain_per_second': pct(gain, d['duration']),
                             'first_raw_score': first_raw, 'repeat_raw_score': repeated_raw})

    overall = catalog_group(cat, best, maxf, cat)
    valid = [o for o in os if o['valid']]
    valid_action = [a for a in action_stats if a['final_valid']]
    repeat_gains = [g for g in gains if g['is_repeat']]
    nongains = [g for g in gains if g['gain'] <= 1e-9]
    final_science = sum(o['score'] for o in best.values())
    replay_checks = {'science_error_vs_report': final_science - report['components']['sum_best_scores'],
                     'observed_count_matches': len(best) == report['counts']['targets_observed'],
                     'invalidated_rows_match': len(os) - len(valid) == report['counts']['invalidated_observations'],
                     'actions_observe_alignment': action_alignment,
                     'factors_formula_max_error': max(abs(o['factor'] - min(1, cat[o['target_id']]['flux'] * o['duration'] * o['quality'] /
                                                                          (config['flux_zero_point'] * config['exposure_zero_point_seconds']))) for o in valid)}

    # Program diagnostics: mismatch per target is visible; actual band is not given
    # for mismatch rows. All bands offer >=1.06; independent-target upper bound1.2.
    progrows = []
    for label, group in [('all_valid_hits', valid), ('final_best', list(best.values()))]:
        for mult in sorted(set(o['prog_mult'] for o in group)):
            rows = [o for o in group if o['prog_mult'] == mult]
            base = sum(cat[o['target_id']]['w'] * o['factor'] for o in rows)
            progrows.append({'card': card, 'scope': label, 'prog_mult': mult, 'rows': len(rows),
                             'base': base, 'science': sum(o['score'] for o in rows),
                             'gap_to_independent_1_2': 1.2 * base - sum(o['score'] for o in rows)})
    dump_csv(f'{card}_program.csv', progrows)

    duration_rows = []
    bins = [(0, 300), (300, 600), (600, 900), (900, 1200), (1200, 1800), (1800, 2400), (2400, 3601)]
    for lo, hi in bins:
        ar = [a for a in valid_action if lo <= a['duration'] < hi]
        gg = [g for g in gains if lo <= g['duration'] < hi]
        bb = [o for o in best.values() if lo <= o['duration'] < hi]
        seconds = sum(a['duration'] for a in ar)
        duration_rows.append({'card': card, 'duration_bin': f'[{lo},{hi})', 'actions': len(ar),
                              'exposure_seconds': seconds, 'seconds_fraction': pct(seconds, sum(a['duration'] for a in valid_action)),
                              'science_gain': sum(a['science_gain'] for a in ar),
                              'science_gain_per_second': pct(sum(a['science_gain'] for a in ar), seconds),
                              'hit_rows': len(gg), 'repeat_rows': sum(g['is_repeat'] for g in gg),
                              'nongain_rows': sum(g['gain'] <= 1e-9 for g in gg),
                              'factor_eq_1_rows': sum(g['factor'] >= 1 - 1e-6 for g in gg),
                              'best_target_rows': len(bb), 'best_science': sum(o['score'] for o in bb)})
    dump_csv(f'{card}_duration.csv', duration_rows)

    targetrows = []
    for i, c in cat.items():
        b = best.get(i)
        targetrows.append({'card': card, 'target_id': i, 'class': c['class'], 'weight': c['w'],
                           'flux': c['flux'], 'required': c['required'], 'ra': c['ra'],
                           'covered': b is not None, 'max_valid_factor': maxf.get(i, 0),
                           'best_factor': b['factor'] if b else 0, 'best_score': b['score'] if b else 0,
                           'score_per_weight': pct(b['score'], c['w']) if b else 0,
                           'best_prog_mult': b['prog_mult'] if b else None,
                           'best_duration': b['duration'] if b else None,
                           'best_quality': b['quality'] if b else None,
                           'best_observe_index': b['observe_index'] if b else None})
    dump_csv(f'{card}_targets.csv', targetrows)
    classrows = [{'card': card, 'class': klass, **catalog_group(cat, best, maxf, [i for i in cat if cat[i]['class'] == klass])}
                 for klass in sorted(set(c['class'] for c in cat.values()))]
    dump_csv(f'{card}_classes.csv', classrows)
    fluxrows = []
    for lo, hi in ((0, .15), (.15, .3), (.3, .6), (.6, 1.2), (1.2, float('inf'))):
        ids = [i for i in cat if lo <= cat[i]['flux'] < hi]
        fluxrows.append({'card': card, 'flux_bin': f'[{lo},{hi})', **catalog_group(cat, best, maxf, ids)})
    dump_csv(f'{card}_flux.csv', fluxrows)

    # Public progress over the calendar. Both final-valid and initially acquired
    # scores are kept; runtime loss is replayed only when its published resync arrives.
    resyncs = [m for m in ms if m['record_type'] == 'state_resync']
    runtime_best = {}
    invalidated_now = set()
    runtime_loss = []
    calendar = read_csv(public / 'public/v4_night_calendar.csv')
    progress = []
    final_prefix = {}
    final_factors = defaultdict(float)
    req_first_cross = {}
    resync_cursor = 0
    decisions_processed = set()
    for night in calendar:
        ns, ne = utc(night['observing_start_utc']), utc(night['observing_end_utc'])
        night_actions = [a for a in action_stats if ns <= utc(a['start_utc']) < ne]
        for a in night_actions:
            idx = a['observe_index']
            d = observe[idx]
            while resync_cursor < len(resyncs) and utc(resyncs[resync_cursor]['issued_at_utc']) <= d['start']:
                m = resyncs[resync_cursor]
                before = sum(o['score'] for o in runtime_best.values())
                window = m['invalidated_window']
                invalidated_now.update(range(window['action_index_start'], window['action_index_end_exclusive']))
                runtime_best = {}
                for prev in os:
                    pi = prev['observe_index']
                    if pi not in decisions_processed or pi in invalidated_now:
                        continue
                    ti = prev['target_id']
                    if ti not in runtime_best or prev['score'] > runtime_best[ti]['score']:
                        runtime_best[ti] = prev
                after = sum(o['score'] for o in runtime_best.values())
                runtime_loss.append({'issued_at_utc': m['issued_at_utc'], 'action_index_at_trigger': window['action_count_at_trigger'],
                                     'window': [window['action_index_start'], window['action_index_end_exclusive']],
                                     'science_before': before, 'science_after': after, 'science_withdrawn_at_trigger': before - after,
                                     'resync_science': sum(t['best_score'] for t in m['best_scores']),
                                     'resync_science_error': after - sum(t['best_score'] for t in m['best_scores'])})
                resync_cursor += 1
            for o in by_action[idx]:
                i = o['target_id']
                if i not in runtime_best or o['score'] > runtime_best[i]['score']:
                    runtime_best[i] = o
                if o['valid']:
                    if i not in final_prefix or o['score'] > final_prefix[i]['score']:
                        final_prefix[i] = o
                    final_factors[i] = max(final_factors[i], o['factor'])
                    if cat[i]['required'] and i not in req_first_cross and o['factor'] >= .5:
                        req_first_cross[i] = d['end_utc']
            decisions_processed.add(idx)
        if not night_actions and ns > utc(ds[-1]['end_utc']):
            state = 'after_termination'
        else:
            state = 'executed' if night_actions else 'no_observe'
        progress.append({'card': card, 'night_id': night['night_id'], 'night_date': night['night_date'], 'state': state,
                         'actions': len(night_actions), 'exposure_seconds': sum(a['duration'] for a in night_actions),
                         'science_gain_final_valid': sum(a['science_gain'] for a in night_actions),
                         'cumulative_final_valid_science': sum(o['score'] for o in final_prefix.values()),
                         'cumulative_runtime_science': sum(o['score'] for o in runtime_best.values()),
                         'cumulative_final_valid_covered': len(final_prefix),
                         'required_remaining_final_valid': sum(c['required'] and final_factors.get(i, 0) < .5 for i, c in cat.items())})
    dump_csv(f'{card}_progress.csv', progress)

    requiredrows = []
    for i, c in cat.items():
        if not c['required']:
            continue
        oo = [o for o in os if o['target_id'] == i]
        vv = [o for o in oo if o['valid']]
        rf = max([o['factor'] for o in oo] or [0])
        requiredrows.append({'card': card, 'target_id': i, 'class': c['class'], 'weight': c['w'],
                             'flux': c['flux'], 'ra': c['ra'], 'hit_count_all': len(oo), 'hit_count_valid': len(vv),
                             'max_factor_all': rf, 'max_factor_valid': maxf.get(i, 0), 'missing': maxf.get(i, 0) < .5,
                             'first_cross_valid_utc': req_first_cross.get(i),
                             'lost_only_completion': rf >= .5 and maxf.get(i, 0) < .5,
                             'max_factor_valid_duration': max(vv, key=lambda o: o['factor'])['duration'] if vv else 0,
                             'max_factor_valid_quality': max(vv, key=lambda o: o['factor'])['quality'] if vv else 0,
                             'best_duration_scale_to_0_5_conditioned_on_realized_q': pct(.5, maxf.get(i, 0)) if vv else None})
    dump_csv(f'{card}_required.csv', requiredrows)

    # Request settlement uses wholly contained exposures and factor, not score.
    reqrows = []
    request_details = []
    for rq in report['observation_requests']:
        qs, qe = utc(rq['issued_at_utc']), utc(rq['deadline_utc'])
        events = [m for m in ms if m['record_type'] == 'observation_request_result' and m['request_id'] == rq['request_id']]
        detail = {'request_id': rq['request_id'], 'issued_at_utc': rq['issued_at_utc'], 'deadline_utc': rq['deadline_utc'],
                  'minimum_completed': rq['minimum_completed'], 'final_completed_count': rq['completed_count'],
                  'result_messages': events, 'targets': []}
        for i in rq['target_ids']:
            oo = [o for o in os if o['target_id'] == i]
            inside = [o for o in oo if qs <= observe[o['observe_index']]['start'] and observe[o['observe_index']]['end'] <= qe]
            vv = [o for o in inside if o['valid']]
            bc = max(vv, key=lambda o: o['factor']) if vv else None
            crosses = [o for o in vv if o['factor'] >= rq['completion_factor_threshold']]
            r = {'card': card, 'request_id': rq['request_id'], 'target_id': i, 'class': cat[i]['class'],
                 'weight': cat[i]['w'], 'flux': cat[i]['flux'], 'ra': cat[i]['ra'],
                 'hits_in_window_all': len(inside), 'hits_in_window_valid': len(vv),
                 'max_in_window_all': max([o['factor'] for o in inside] or [0]),
                 'max_in_window_valid': bc['factor'] if bc else 0,
                 'max_all_season_valid': maxf.get(i, 0),
                 'first_qualifying_window_utc': min([observe[o['observe_index']]['end_utc'] for o in crosses] or ['']),
                 'lost_qualifying_action_indices': [o['observe_index'] for o in inside if not o['valid'] and o['factor'] >= .5],
                 'best_valid_action': bc['observe_index'] if bc else None,
                 'best_valid_duration': bc['duration'] if bc else None,
                 'best_valid_quality': bc['quality'] if bc else None}
            reqrows.append(r)
            detail['targets'].append(r)
        request_details.append(detail)
    dump_csv(f'{card}_requests.csv', reqrows)

    # Lost science at final settlement differs from withdrawal at trigger if
    # later reobservations partly recover it.
    raw_best = {}
    for o in os:
        i = o['target_id']
        if i not in raw_best or o['score'] > raw_best[i]['score']:
            raw_best[i] = o
    uncovered_valid_positive = [i for i in best if best[i]['score'] > 0]
    mismatch_best = [o for o in best.values() if o['prog_mult'] == 1 and o['score'] > 0]
    mismatch_base = sum(cat[o['target_id']]['w'] * o['factor'] for o in mismatch_best)
    summary = {'card': card, 'source': str(source.relative_to(ROOT)), 'official_total': report['total'],
               'official_components': report['components'], 'official_counts': report['counts'],
               'termination': report['termination'], 'replay_checks': replay_checks, 'catalog': overall,
               'class_decomposition': classrows, 'flux_decomposition': fluxrows,
               'progress': {'calendar_nights': len(calendar), 'executed_observe_nights': sum(p['actions'] > 0 for p in progress),
                            'calendar_start': calendar[0]['observing_start_utc'], 'calendar_end': calendar[-1]['observing_end_utc'],
                            'actual_end': ds[-1]['end_utc'], 'runtime_invalidation': runtime_loss,
                            'final_unrecovered_science_from_invalidation': sum(o['score'] for o in raw_best.values()) - final_science},
               'exposures': {'count': len(observe), 'valid_count': len(valid_action),
                             'all_exposure_seconds': sum(d['duration'] for d in observe.values()),
                             'valid_exposure_seconds': sum(a['duration'] for a in valid_action),
                             'duration_quantiles': quantiles([d['duration'] for d in observe.values()]),
                             'best_duration_quantiles': quantiles([o['duration'] for o in best.values()]),
                             'quality_quantiles_valid': quantiles([o['quality'] for o in valid]),
                             'best_quality_weighted': pct(sum(cat[i]['w'] * o['quality'] for i, o in best.items()), overall['covered_weight']),
                             'assigned_total': sum(int(d['assigned_count']) for d in observe.values()),
                             'hit_total': len(os), 'zero_score_hit_rows_valid': sum(o['score'] == 0 for o in valid),
                             'zero_score_only_targets': len(best) - len(uncovered_valid_positive),
                             'positive_score_targets': len(uncovered_valid_positive),
                             'nongain_actions': sum(a['science_gain'] <= 1e-9 for a in valid_action),
                             'nongain_action_seconds': sum(a['duration'] for a in valid_action if a['science_gain'] <= 1e-9),
                             'duration_bins': duration_rows},
               'historical_max': {'valid_hit_rows': len(valid), 'repeat_rows': len(repeat_gains),
                                  'nonimproving_rows': len(nongains), 'nonimproving_raw_score': sum(g['score'] for g in nongains),
                                  'raw_score_sum': sum(o['score'] for o in valid), 'science_sum': final_science,
                                  'first_visit_score': sum(g['gain'] for g in gains if not g['is_repeat']),
                                  'repeat_marginal_gain': sum(g['gain'] for g in repeat_gains),
                                  'repeat_raw_score': sum(g['score'] for g in repeat_gains),
                                  'repeat_marginal_fraction_of_raw': pct(sum(g['gain'] for g in repeat_gains), sum(g['score'] for g in repeat_gains)),
                                  'target_hit_count_quantiles': quantiles(list(Counter(o['target_id'] for o in valid).values()))},
               'program': {'breakdown': progrows, 'final_best_mismatch_positive_count': len(mismatch_best),
                           'final_best_mismatch_base': mismatch_base,
                           'independent_target_mismatch_bonus_lower_algebraic': .06 * mismatch_base,
                           'independent_target_mismatch_bonus_upper_algebraic': .2 * mismatch_base,
                           'actual_band_unknown_for_mismatch': True},
               'required': {'total': len(requiredrows), 'missing': [r for r in requiredrows if r['missing']],
                            'missing_count_replay': sum(r['missing'] for r in requiredrows)},
               'requests': request_details}
    all_summary[card] = summary
    dump_csv(f'{card}_action_marginals.csv', action_stats)
    dump_csv(f'{card}_hit_marginals.csv', gains)

(OUT / 'summary.json').write_text(json.dumps(all_summary, ensure_ascii=False, indent=2) + '\n')
(OUT / 'provenance.json').write_text(json.dumps(all_provenance, ensure_ascii=False, indent=2) + '\n')
dump_csv('four_card_summary.csv', [{'card': c, 'official_total': s['official_total'],
                                  **s['official_components'], **s['catalog'],
                                  'termination': s['termination']['reason']} for c, s in all_summary.items()])
print(json.dumps({c: {'catalog': s['catalog'], 'exposures': s['exposures'], 'historical_max': s['historical_max'],
                      'progress': s['progress'], 'replay_checks': s['replay_checks'], 'required_missing': s['required']['missing']}
                  for c, s in all_summary.items()}, ensure_ascii=False, indent=2))
