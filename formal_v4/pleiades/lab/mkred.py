#!/usr/bin/env python3
"""mkred.py : red-team worlds. Each copies a base world and edits only its score/fibre/scenario config, request
file or stress events, so the base world is the twin for a clean comparison.
  RU uniformity weight 20000 (x100)        RP program multipliers inverted (BACKUP > BRIGHT > DARK)
  RF false-report penalty -1000, no free    RQ required penalty 500 (x10), threshold 0.7
  RR request rewards x10, 7 of 8 targets    RT time budget 200 s (of 900)
  RO pointing offset 0.008 rad (~0.46 deg)  RX exposures 1200-3600 s
  RH minimum altitude 55 deg"""
import csv, json, shutil, sys
from pathlib import Path
W = Path('/home/shu/kamico/observer/work/worlds')

def clone(base, name):
    dst = W / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(W / base, dst)
    sc = json.loads((dst / 'config/v4_scenario.json').read_text())
    sc['name'] = name
    sc['task_card'].update(card_id=name, scenario_slug=name)
    (dst / 'config/v4_scenario.json').write_text(json.dumps(sc, indent=2, sort_keys=True))
    return dst

def edit(path, fn):
    d = json.loads(path.read_text())
    fn(d)
    path.write_text(json.dumps(d, indent=2, sort_keys=True))

def make(base, tag):
    name = f'R{tag}{base[-2:]}'
    dst = clone(base, name)
    S, F, C = dst / 'config/v4_score_config.json', dst / 'config/v4_fiber_config.json', dst / 'config/v4_scenario.json'
    if tag == 'U':
        edit(S, lambda d: d['uniformity'].update(weight=20000.0))
    elif tag == 'P':
        edit(S, lambda d: (d['program']['multipliers'].update(DARK=1.0, BRIGHT=1.15, BACKUP=1.3),
                           d['program'].update(mismatch_multiplier=0.5)))
    elif tag == 'F':
        edit(S, lambda d: d['reporting'].update(false_penalty=-1000, false_report_free_allowance=0))
    elif tag == 'Q':
        edit(S, lambda d: d['required'].update(penalty_per_missing=500, observed_factor_threshold=0.7))
    elif tag == 'R':
        p = dst / 'truth/v4_observation_requests.jsonl'
        out = []
        for line in p.read_text().splitlines():
            r = json.loads(line)
            r['completion_reward'] = r['completion_reward'] * 10
            r['minimum_completed'] = min(len(r['target_ids']), r['minimum_completed'] + 1)
            out.append(json.dumps(r, sort_keys=True))
        p.write_text('\n'.join(out) + '\n')
    elif tag == 'T':
        edit(C, lambda d: d['limits'].update(global_wallclock_seconds=200))
    elif tag == 'O':
        rows = [['event_id', 'event_type', 'trigger_mode', 'trigger_ref', 'window_start_fraction', 'window_end_fraction',
                 'window_max_fraction', 'alt_offset_rad', 'az_offset_rad'],
                ['V4ST0001', 'pointing_offset', 'at_survey_start', '', '', '', '', '0.00800000', '-0.00800000']]
        with open(dst / 'truth/v4_stress_events.csv', 'w', newline='') as f:
            csv.writer(f, lineterminator='\n').writerows(rows)
        edit(C, lambda d: d.update(stress={'enabled': True, 'stress_events_csv': '../truth/v4_stress_events.csv'}))
    elif tag == 'X':
        edit(F, lambda d: d['exposure'].update(min_duration_seconds=1200, max_duration_seconds=3600))
    elif tag == 'H':
        edit(C, lambda d: d.update(minimum_altitude_deg=55.0))
    print('built', name)

for base in sys.argv[1].split(','):
    for tag in sys.argv[2].split(','):
        make(base, tag)
