#!/usr/bin/env python3
"""Read only public score feedback and messages; no factor/quality/mult labels.

Audit a report immediately before an already frozen final action.  The actor uses
only target catalogue, declared programs, rounded scores, and public loss windows.
"""
import collections
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CONTROL = ROOT / 'results/policy_iteration_20261004/natural_control'
CARDS = ROOT / 'upstream/gosim-observer-examples/local-cards'


def read_selected_csv(path, fields):
    # Deliberately discard inaccessible factor, quality, program multiplier,
    # fiber labels, and terminal teacher fields from ordinary runner artifacts.
    with path.open(newline='') as handle:
        reader = csv.reader(handle)
        header = next(reader)
        selected = [(field, header.index(field)) for field in fields]
        return [{field: row[index] for field, index in selected} for row in reader]


def audit(card):
    directory = CONTROL / card / 'rank_0064/control'
    config = json.loads((CARDS / card / 'config/v4_score_config.json').read_text())
    targets = read_selected_csv(CARDS/card/'public/targets.csv',
                                ['target_id', 'ra_deg', 'science_weight', 'required'])
    targets_by_id = {r['target_id']: r for r in targets}
    totals = collections.Counter(int(float(r['ra_deg']) // 10) for r in targets)
    decisions = read_selected_csv(directory/'decisions.csv',
                                  ['observe_index', 'action', 'start_utc', 'end_utc',
                                   'duration_seconds', 'program'])
    observations = read_selected_csv(directory/'observations.csv',
                                     ['observe_index', 'target_id', 'score'])
    messages = [json.loads(line) for line in (directory/'messages.jsonl').read_text().splitlines()]
    actions = [json.loads(line) for line in (directory/'actions.jsonl').read_text().splitlines()]
    last = decisions[-1]
    # actions.jsonl contains only real agent round trips, whereas decisions has
    # additional automatic wait-until expansion rows.  Last action is sufficient.
    final_action = actions[-1]
    if final_action['action'] != last['action']:
        raise AssertionError((card, final_action, last))
    final_rank = int(last['observe_index']) if last['action']=='observe' else None
    end = last['end_utc']
    now = last['start_utc']
    invalidated = set()
    false_count = 0
    correct_reports = 0
    for message in messages:
        if message.get('issued_at_utc', '') > now:
            continue
        if message['record_type'] == 'state_resync':
            win = message['invalidated_window']
            invalidated.update(range(win['action_index_start'], win['action_index_end_exclusive']))
        if message['record_type'] == 'report_result':
            if message['correct']:
                false_count = 0
                correct_reports += 1
            else:
                false_count += 1
    declared = {int(r['observe_index']): r['program'] for r in decisions if r['action']=='observe'}
    factor_lo = collections.defaultdict(float)
    factor_hi = collections.defaultdict(float)
    score_best = collections.defaultdict(float)
    threshold = config['uniformity']['observed_factor_threshold']
    eps = 0.500001e-6
    for row in observations:
        rank = int(row['observe_index'])
        if rank in invalidated or (final_rank is not None and rank >= final_rank):
            continue
        tid = row['target_id']
        weight = float(targets_by_id[tid]['science_weight'])
        score = float(row['score'])
        declared_multiplier = config['program']['multipliers'][declared[rank]]
        mismatch = config['program']['mismatch_multiplier']
        factor_lo[tid] = max(factor_lo[tid], max(0.,score-eps)/(weight*max(declared_multiplier,mismatch)))
        factor_hi[tid] = max(factor_hi[tid], min(1.,(score+eps)/(weight*min(declared_multiplier,mismatch))))
        score_best[tid] = max(score_best[tid],score)
    lower = collections.Counter()
    upper = collections.Counter()
    for target in targets:
        tid = target['target_id']
        band = int(float(target['ra_deg'])//10)
        lower[band] += factor_lo[tid] >= threshold
        upper[band] += factor_hi[tid] >= threshold
    # Only these targets can cross the completion threshold in the final frozen
    # exposure.  Repair never changes program-band, duration, hit geometry, or rank.
    assigned = set(final_action.get('assignments', {}).values())
    uncertain_final = [tid for tid in assigned if factor_lo[tid] < threshold]
    increments = collections.Counter(int(float(targets_by_id[tid]['ra_deg'])//10) for tid in uncertain_final)
    ratios_lower = [lower[b]/totals[b] for b in sorted(totals)]
    ratios_upper = [upper[b]/totals[b] for b in sorted(totals)]
    deltas = [increments[b]/totals[b] for b in sorted(totals)]
    k = len(totals)
    q_min = sum(r*r for r in ratios_lower)
    s_max = sum(u+d for u,d in zip(ratios_upper,deltas))
    uniformity_weight = config['uniformity']['weight']
    # Along r -> r+delta, positive penalty derivative is
    # 2U*s*(s*r_k-q)/(K*q^2) <= 2U*s_max^2*(u_k+delta_k)/(K*q_min^2).
    # Integrating that componentwise gives a conservative certified increase.
    harm = (sum(2*uniformity_weight*s_max*s_max*(u+d)*d/(k*q_min*q_min)
                for u,d in zip(ratios_upper,deltas)) if q_min else float('inf'))
    reward = config['reporting']['correct_reward']
    free_remaining = max(0,config['reporting']['false_report_free_allowance']-false_count)
    return {
        'card':card,'now_utc':now,'survey_end_utc':end,
        'final_action':final_action,'final_action_frozen':True,
        'final_action_seconds':int(last['duration_seconds']),
        'prior_correct_reports':correct_reports,'prior_false_reports_since_correct':false_count,
        'free_reports_remaining':free_remaining,
        'prior_invalidated_ranks':sorted(invalidated),
        'science_best_from_public_feedback':sum(score_best.values()),
        'uniformity_lower_ratios':dict(zip(sorted(totals),ratios_lower)),
        'uniformity_upper_ratios':dict(zip(sorted(totals),ratios_upper)),
        'final_targets_without_completion_certificate':uncertain_final,
        'worst_uniformity_harm_bound':harm,
        'conditional_correct_total_gain_lower_bound':reward-harm,
        'conditional_false_gain_with_free_allowance':0,
        'public_only_weak_dominance_gate':free_remaining>0 and harm<=reward,
        'actual_correctness_verified':False,
        'inputs_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in [directory/'decisions.csv',directory/'observations.csv',
                                  directory/'actions.jsonl',directory/'messages.jsonl',
                                  CARDS/card/'public/targets.csv',
                                  CARDS/card/'config/v4_score_config.json']},
    }


if __name__ == '__main__':
    result = {'schema':'terminal-report-public-audit-v1',
              'reads_teacher_labels':False,'reads_weather_truth':False,
              'reads_raw_factor_quality_program_mult':False,
              'cards':[audit(card) for card in ['L1','L2','L3','L4']]}
    (OUT/'public_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    for r in result['cards']:
        print(r['card'],r['now_utc'],r['final_action']['action'],
              'free',r['free_reports_remaining'],'Jain harm <=',r['worst_uniformity_harm_bound'],
              'correct gain >=',r['conditional_correct_total_gain_lower_bound'])
