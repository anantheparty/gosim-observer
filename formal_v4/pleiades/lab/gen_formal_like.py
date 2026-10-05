#!/usr/bin/env python3
"""Build a local, scorable bundle from a released formal card (A-D public files) plus synthetic hidden weather.

usage: gen_formal_like.py CARD(A|B|C|D) SEED OUTNAME [--stress 0|1] [--event-scale X]
The released targets/footprint/calendar/fiber/score files are used verbatim; weather, events, bulletins,
forecasts, requests (and stress events) come from the official generator with the card's site and dates.
"""
import argparse, csv, json, shutil, sys, tempfile
from pathlib import Path

sys.path.insert(0, '/home/shu/kamico/observer/hackathon-survey26')
from challenge import v4_weather_simulator, v4_observation_requests  # noqa: E402

REF = Path('/home/shu/kamico/observer/hackathon-survey26/challenge/reference/v4')
FORMAL = Path('/home/shu/kamico/observer/gosim-observer/formal_v4/formal_cards')
OUT = Path('/home/shu/kamico/observer/work/worlds')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('card')
    ap.add_argument('seed', type=int)
    ap.add_argument('name')
    ap.add_argument('--stress', type=int, default=None)
    ap.add_argument('--event-scale', type=float, default=1.0)
    ap.add_argument('--faults', type=int, default=None)
    ap.add_argument('--quakes', type=int, default=None)
    ap.add_argument('--dataloss', type=float, default=None)
    a = ap.parse_args()
    card = a.card.upper()
    src = FORMAL / card / card.lower()
    fiber = json.loads((src / 'config/v4_fiber_config.json').read_text())
    score = json.loads((src / 'config/v4_score_config.json').read_text())
    nights = list(csv.DictReader(open(src / 'public/v4_night_calendar.csv')))
    first, last = nights[0]['night_date'], nights[-1]['night_date']
    import datetime
    end_date = (datetime.date.fromisoformat(last) + datetime.timedelta(days=1)).isoformat()
    stress = (card == 'D') if a.stress is None else bool(a.stress)
    weather = json.loads((REF / ('v4_weather_stress_config.json' if stress else 'v4_weather_config.json')).read_text())
    weather.update(seed=a.seed, seed_derivation='sha256-v1')
    weather['site'] = dict(fiber['site'])
    weather['survey'].update(start_date=first, end_date=end_date)
    weather['stress_tests']['enabled'] = stress
    if a.faults is not None:
        weather['instrument_fault']['count'] = a.faults
    if a.quakes is not None:
        weather['earthquake']['count'] = a.quakes
    if a.dataloss is not None:
        weather['stress_tests']['data_loss']['window_max_fraction'] = a.dataloss
    if a.event_scale != 1.0:
        for k, v in weather['weather_events']['conditions'].items():
            v['count'] = max(0, int(round(v['count'] * a.event_scale)))
        for k in ('rocket_launch', 'earthquake'):
            weather[k]['count'] = max(0, int(round(weather[k]['count'] * a.event_scale)))
    scenario = json.loads((REF / ('v4_scenario_stress.json' if stress else 'v4_scenario_default.json')).read_text())
    scenario['name'] = a.name
    scenario['site'] = dict(fiber['site'])
    scenario['task_card'] = {'card_id': a.name, 'scenario_slug': a.name, 'phase': 'local'}
    scenario['fiber_config'] = 'v4_fiber_config.json'
    scenario['score_config'] = 'v4_score_config.json'
    scenario['products'] = {
        'targets_csv': '../public/targets.csv', 'footprint_csv': '../public/footprint.csv',
        'night_calendar_csv': '../public/v4_night_calendar.csv', 'bulletins_jsonl': '../public/v4_bulletins.jsonl',
        'forecasts_jsonl': '../public/v4_forecasts.jsonl', 'slots_csv': '../truth/v4_slots.csv',
        'weather_truth_csv': '../truth/v4_weather_truth.csv', 'events_csv': '../truth/v4_events.csv',
        'earthquake_effects_csv': '../truth/v4_earthquake_effects.csv',
        'observation_requests_jsonl': '../truth/v4_observation_requests.jsonl',
    }
    scenario.pop('agent_params', None)
    if stress:
        scenario['stress']['stress_events_csv'] = '../truth/v4_stress_events.csv'
    scenario['limits'] = {'global_wallclock_seconds': 900}
    root = OUT / a.name
    if root.exists():
        shutil.rmtree(root)
    with tempfile.TemporaryDirectory(prefix='v4f-') as tmp:
        work = Path(tmp)
        (work / 'weather.json').write_text(json.dumps(weather))
        v4_weather_simulator.generate(work / 'weather.json', work / 'out')
        out = work / 'out'
        # Use the released calendar/targets/footprint verbatim.
        gen_cal = list(csv.DictReader(open(out / 'v4_night_calendar.csv')))
        if [r['night_id'] for r in gen_cal] != [r['night_id'] for r in nights]:
            print('WARNING calendar mismatch', len(gen_cal), len(nights), file=sys.stderr)
        for name in ('targets.csv', 'footprint.csv', 'v4_night_calendar.csv'):
            shutil.copyfile(src / 'public' / name, out / name)
        settings = {'completion_factor_threshold': score['observation_requests']['completion_factor_threshold']}
        settings['minimum_feature_flux'] = (float(settings['completion_factor_threshold']) * float(score['flux_zero_point'])
                                            * float(score['exposure_zero_point_seconds']) / float(fiber['exposure']['max_duration_seconds']))
        v4_observation_requests.generate_requests(
            seed=a.seed, targets_csv=out / 'targets.csv', night_calendar_csv=out / 'v4_night_calendar.csv',
            slots_csv=out / 'v4_slots.csv', site=scenario['site'], minimum_altitude_deg=float(scenario['minimum_altitude_deg']),
            output_path=out / 'v4_observation_requests.jsonl', settings=settings,
            flux_zero_point=float(score['flux_zero_point']), exposure_zero_point_seconds=float(score['exposure_zero_point_seconds']),
            min_duration_seconds=int(fiber['exposure']['min_duration_seconds']), max_duration_seconds=int(fiber['exposure']['max_duration_seconds']))
        for d in ('config', 'public', 'truth'):
            (root / d).mkdir(parents=True)
        (root / 'config/v4_scenario.json').write_text(json.dumps(scenario, indent=2, sort_keys=True) + '\n')
        (root / 'config/v4_fiber_config.json').write_text(json.dumps(fiber, indent=2, sort_keys=True) + '\n')
        (root / 'config/v4_score_config.json').write_text(json.dumps(score, indent=2, sort_keys=True) + '\n')
        for name in ('targets.csv', 'footprint.csv', 'v4_night_calendar.csv', 'v4_bulletins.jsonl', 'v4_forecasts.jsonl'):
            shutil.copyfile(out / name, root / 'public' / name)
        for name in ('v4_slots.csv', 'v4_weather_truth.csv', 'v4_events.csv', 'v4_earthquake_effects.csv',
                     'v4_observation_requests.jsonl') + (('v4_stress_events.csv',) if stress else ()):
            shutil.copyfile(out / name, root / 'truth' / name)
    print('built', root)


if __name__ == '__main__':
    main()
