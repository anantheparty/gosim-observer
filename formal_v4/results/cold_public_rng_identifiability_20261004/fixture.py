"""Frozen synthetic fixtures. No actual card data is opened by any experiment."""
import copy
import csv
import hashlib
import io
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OFFICIAL = ROOT / 'official'
sys.path.insert(0, str(OFFICIAL))
from challenge import v4_bundle, v4_catalog_generator as cat, v4_weather_simulator as weather
from challenge.contracts import stream_seed


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def digest(data):
    if not isinstance(data, bytes):
        data = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(data).hexdigest()


def read_rows(path):
    with Path(path).open(newline='') as handle:
        return list(csv.DictReader(handle))


def make_configs():
    ref = OFFICIAL / 'challenge/reference/v4'
    load = lambda name: json.loads((ref / name).read_text())
    c = load('v4_catalog_config.json')
    w = load('v4_weather_stress_config.json')
    f = load('v4_fiber_config.json')
    s = load('v4_score_config.json')
    for cfg in (c, w):
        cfg.pop('seed', None)
        cfg['seed_derivation'] = 'sha256-v1'
    c['footprint'].update(total_area_deg2=900., n_components=2,
        vertices_per_component=24, component_area_weights=[.5, .5],
        component_centers=[[30., -35.], [75., -35.], [120., -35.]],
        harmonic_amplitude_ranges=[.06, .04, .02], component_gap_deg=5.)
    c['targets'].update(total_count=96, n_cluster_centers=1, clustered_fraction=0.)
    c['observability'].update(start_date='2027-01-01', end_date='2027-02-01',
        minimum_window_seconds=600)
    w['survey'].update(start_date='2027-01-01', end_date='2027-02-01')
    w['stress_tests']['enabled'] = True
    for definition in w['weather_events']['conditions'].values():
        definition['count'] = 1
    w['rocket_launch']['count'] = 1
    w['earthquake']['count'] = 1
    w['instrument_fault']['count'] = 1
    card = dict(name='SYNTHETIC identifiability fixture', card_id='synthetic-only',
        scenario_slug='synthetic-only', phase='synthetic-only', stress=True,
        observation_requests=dict(count=2, targets_per_request=2,
            include_required_targets=True, minimum_feature_flux=0.))
    return dict(catalog=c, weather=w, fiber=f, score=s, card=card)


def build(root, configs, catalog_seed, weather_seed):
    spec = root.parent / (root.name + '_spec_SYNTHETIC')
    spec.mkdir(parents=True)
    for key, name in [('catalog', 'v4_catalog_config.json'),
                      ('weather', 'v4_weather_config.json'),
                      ('fiber', 'v4_fiber_config.json'),
                      ('score', 'v4_score_config.json'), ('card', 'card.json')]:
        cfg = copy.deepcopy(configs[key])
        if key in ('catalog', 'weather'):
            cfg['seed'] = catalog_seed if key == 'catalog' else weather_seed
        dump(spec / name, cfg)
    return v4_bundle.build_spec_bundle(root, spec)


def footprint_bytes(config, seed):
    cfg = copy.deepcopy(config)
    cfg['seed'] = seed
    rng = random.Random(stream_seed(cfg, 'v4.catalog', 0))
    parts = cat.generate_footprint(cfg, rng)
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=cat.FOOTPRINT_COLUMNS, lineterminator='\n')
    writer.writeheader()
    for part in parts:
        for j, vertex in enumerate(part.vertices):
            writer.writerow(dict(component_id=part.component_id, vertex_index=j,
                ra_deg=f'{vertex[0]:.6f}', dec_deg=f'{vertex[1]:.6f}'))
    return buffer.getvalue().encode()


if __name__ == '__main__':
    cfg = make_configs()
    dump(ROOT / 'synthetic_nonseed_configs_frozen.json', cfg)
    dump(ROOT / 'freeze_receipt.json', dict(
        protocol_sha256=digest((ROOT / 'protocol_frozen.json').read_bytes()),
        fixture_sha256=digest(Path(__file__).read_bytes()),
        config_sha256=digest((ROOT / 'synthetic_nonseed_configs_frozen.json').read_bytes()),
        generated_worlds_exist=(ROOT / 'worlds_SYNTHETIC').exists()))
