"""Participant role. File audit denies synthetic labels, specs, and truth inputs.

The search is a demonstration on a frozen, advertised 10-bit synthetic domain.
It is never applied to an actual card.
"""
import copy
import json
import sys
import time
from pathlib import Path
from fixture import ROOT, OFFICIAL, weather, footprint_bytes, digest, dump
from challenge import v4_observation_requests
from challenge.contracts import format_utc
import csv

opened = []
def audit(event, args):
    if event != 'open' or not isinstance(args[0], (str, bytes, Path)):
        return
    path = Path(args[0]).resolve()
    mode = args[1]
    reading = isinstance(mode, str) and ('r' in mode or mode == '')
    if reading:
        if 'worlds_SYNTHETIC' in path.parts or 'counterexample_SYNTHETIC' in path.parts or 'SYNTHETIC_SEALED_LABELS' in path.name or path.name.endswith('_spec_SYNTHETIC'):
            raise RuntimeError(f'Blind input boundary violation: {path}')
        if path.is_relative_to(ROOT):
            if path != ROOT / 'synthetic_nonseed_configs_frozen.json' and not path.is_relative_to(ROOT / 'blind_public') and not path.is_relative_to(OFFICIAL):
                raise RuntimeError(f'Non-allowlisted blind input: {path}')
        opened.append(str(path))
sys.addaudithook(audit)
cfg = json.loads((ROOT / 'synthetic_nonseed_configs_frozen.json').read_text())
inventory = json.loads((ROOT / 'blind_public/inventory.json').read_text())
fingerprints = {}
failures = []
started = time.perf_counter()
for seed in range(1024):
    try:
        fingerprint = digest(footprint_bytes(cfg['catalog'], seed))
        fingerprints.setdefault(fingerprint, []).append(seed)
    except Exception as exc:
        failures.append(dict(candidate=seed, error=str(exc)))
predictions = []
for entry in inventory:
    record = dict(world_id=entry['world_id'], generation_status=entry['status'])
    if entry['status'] != 'generated':
        record['status'] = 'generation_failed'
        predictions.append(record)
        continue
    public = ROOT / 'blind_public' / entry['world_id']
    fingerprint = digest((public / 'footprint.csv').read_bytes())
    candidates = fingerprints.get(fingerprint, [])
    record['candidates'] = candidates
    if len(candidates) != 1:
        record['status'] = 'abstain'
        predictions.append(record)
        continue
    recovered = candidates[0]
    wc = copy.deepcopy(cfg['weather'])
    wc['seed'] = recovered
    nights, slots = weather.build_nights(wc)
    events, effects = weather.generate_events(wc, nights, slots)
    rows = weather.generate_weather(wc, nights, slots, events, effects)
    stress = weather.generate_stress_events(wc, events)
    with (public / 'targets.csv').open(newline='') as h:
        targets = list(csv.DictReader(h))
    settings = dict(cfg['card']['observation_requests'])
    settings.setdefault('completion_factor_threshold', cfg['score']['observation_requests']['completion_factor_threshold'])
    settings.setdefault('minimum_feature_flux', float(settings['completion_factor_threshold']) * float(cfg['score']['flux_zero_point']) * float(cfg['score']['exposure_zero_point_seconds']) / float(cfg['fiber']['exposure']['max_duration_seconds']))
    requests = v4_observation_requests.build_requests(seed=recovered, targets=targets,
        nights=[n.csv_row() for n in nights], slots=[s.csv_row() for s in slots],
        site=cfg['catalog']['site'], minimum_altitude_deg=cfg['catalog']['observability']['minimum_altitude_deg'],
        settings=settings, flux_zero_point=cfg['score']['flux_zero_point'],
        exposure_zero_point_seconds=cfg['score']['exposure_zero_point_seconds'],
        min_duration_seconds=cfg['fiber']['exposure']['min_duration_seconds'],
        max_duration_seconds=cfg['fiber']['exposure']['max_duration_seconds'])
    forecast = {'weather_future': rows[1:], 'events': [e.csv_row() for e in events],
        'earthquake_effects': [e.csv_row() for e in effects], 'stress': stress, 'requests': requests}
    dump(ROOT / 'blind_predictions' / entry['world_id'] / 'future_SYNTHETIC.json', forecast)
    record.update(status='unique', recovered_master=recovered,
        future_hashes={key:digest(value) for key,value in forecast.items()},
        future_weather_rows=len(rows)-1)
    predictions.append(record)
result = dict(candidate_count=1024, distinct_rounded_footprints=len(fingerprints),
    collisions=[v for v in fingerprints.values() if len(v)>1], candidate_failures=failures,
    duration_seconds=time.perf_counter()-started, worlds=predictions, input_reads=opened)
dump(ROOT / 'blind_predictions_frozen.json', result)
print(json.dumps({k:result[k] for k in ('candidate_count','distinct_rounded_footprints','collisions','candidate_failures','duration_seconds')}))
