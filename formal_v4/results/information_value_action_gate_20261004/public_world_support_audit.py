#!/usr/bin/env python3
"""Necessary terrain support test using saved public history only.

No policy replay, candidate search, hidden files, or continuation evaluation.
A positive hit contradicts a terrain world only when conservative continuous
trajectory envelopes lie wholly within that world's permanent terrain sector.
Zero contradictions does not establish a calibrated posterior likelihood.
"""
from __future__ import annotations
import csv, hashlib, json, math, sys
from datetime import datetime, timedelta
from pathlib import Path

sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parent
BASE = OUT.parents[1]
UP = BASE / 'upstream/gosim-observer-examples'
sys.path.insert(0, str(UP / 'runner'))
from challenge.v4_fiber_map import radec_to_altaz, SIDEREAL_DEGREES_PER_DAY

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text())

def parse(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))

def audit(card):
    folder = OUT / card
    state, worlds = read(folder / 'public_state.json'), read(folder / 'worlds.json')['worlds']
    history = read(folder / 'public_history.json')
    history.append({'snapshot': state['snapshot'], 'action': None})
    # Exactly the site fields disclosed by v4-initialize-v1; no truth paths used.
    site = read(UP / f'local-cards/{card}/config/v4_scenario.json')['site']
    target_path = UP / f'local-cards/{card}/public/targets.csv'
    with target_path.open(newline='') as f:
        targets = {t['target_id']: t for t in csv.DictReader(f)}
    checked, contradictions = 0, []
    speed = SIDEREAL_DEGREES_PER_DAY / 86400.0
    for step, (previous, current) in enumerate(zip(history, history[1:])):
        action = previous['action']
        result = current['snapshot'].get('last_result') or {}
        if not action or action.get('action') != 'observe' or result.get('action') != 'observe':
            continue
        assert result['observe_index'] == previous['snapshot']['observe_action_index']
        start, end = parse(previous['snapshot']['now_utc']), parse(current['snapshot']['now_utc'])
        assert (end-start).total_seconds() == action['duration_seconds']
        for hit in result['hits']:
            if float(hit['score']) <= 0.0:
                continue
            checked += 1
            target, envelopes, cursor = targets[hit['target_id']], [], start
            while cursor < end:
                stop = min(end, cursor+timedelta(seconds=60))
                midpoint = cursor+(stop-cursor)/2
                alt, az = radec_to_altaz(float(target['ra_deg']), float(target['dec_deg']),
                    midpoint, float(site['latitude_deg']), float(site['longitude_deg']))
                # Rotation speed bounds spherical path length. Altitude is
                # 1-Lipschitz; azimuth metric is ds^2 = dalt^2+cos(alt)^2*daz^2.
                reach = speed*(stop-cursor).total_seconds()/2+1e-7
                max_abs_alt = max(abs(alt-reach), abs(alt+reach))
                az_reach = (180.0 if max_abs_alt >= 90.0 else
                    min(180.0, reach/max(1e-15, math.cos(math.radians(max_abs_alt)))))
                envelopes.append({'start_utc': cursor.isoformat(), 'end_utc': stop.isoformat(),
                    'alt_lower': alt-reach, 'alt_upper': alt+reach,
                    'az_mid': az, 'az_reach': az_reach})
                cursor = stop
            for world in worlds:
                fully_covered = all(
                    e['alt_lower'] >= 0.0 and e['alt_upper'] <= world['height'] and
                    abs((e['az_mid']-world['center']+180)%360-180)+e['az_reach'] <= world['radius']
                    for e in envelopes)
                if fully_covered:
                    contradictions.append({'world': world['world'], 'observe_index': result['observe_index'],
                        'history_step': step, 'target_id': hit['target_id'], 'score': hit['score'],
                        'start_utc': previous['snapshot']['now_utc'],
                        'end_utc': current['snapshot']['now_utc'],
                        'duration_seconds': action['duration_seconds'],
                        'world_sector': world,
                        'max_alt_upper': max(e['alt_upper'] for e in envelopes),
                        'min_az_sector_margin': min(world['radius']-
                            abs((e['az_mid']-world['center']+180)%360-180)-e['az_reach'] for e in envelopes),
                        'trajectory_envelopes': envelopes})
    return {'all_past_positive_hits_checked': checked,
        'continuous_terrain_positive_contradictions': contradictions,
        'contradiction_count': len(contradictions), 'only_public_history_used': True,
        'necessary_test_only': True,
        'method': 'Conservative 60 s continuous trajectory envelopes using sidereal angular speed and azimuth metric Lipschitz bound; no truth or future trace',
        'public_site': site,
        'source_sha256': {str(p.relative_to(BASE)): sha(p) for p in
            (folder/'public_history.json', folder/'public_state.json', folder/'worlds.json', target_path,
             UP/'runner/challenge/v4_fiber_map.py', UP/'runner/challenge/tile_geometry_simulator.py')}}

if __name__ == '__main__':
    result = {card: audit(card) for card in ('L4', 'L3')}
    (OUT/'PUBLIC_WORLD_SUPPORT_AUDIT.json').write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({c: {'positive_hits': r['all_past_positive_hits_checked'],
                         'contradictions': r['contradiction_count']} for c,r in result.items()}))
