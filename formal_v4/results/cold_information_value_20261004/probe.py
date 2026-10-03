#!/usr/bin/env python3
"""Public-only spatial certificates, separate truth audit, official synthetic VoI.

No participant imports scenario loader or truth files. Historical per-hit score is
the same public value as last_result.hits, though the archived CSV has extra fields
that are deliberately projected away. Truth files are opened only in audit_truth.
"""
from __future__ import annotations
import csv, hashlib, json, math, sys, time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
UP = ROOT / 'formal_v4/upstream/gosim-observer-examples'
sys.path.insert(0, str(UP / 'runner'))
from challenge.v4_fiber_map import FiberGrid, altaz_to_radec, radec_to_altaz, min_altitude_during
from challenge.v4_scorer import (BestLedger, ScoreEvent, SlotTruth, WeatherTruth,
    lunar_quality_factor, program_band, program_multiplier, required_penalty,
    score_target_exposure, uniformity_penalty)
from challenge.tile_geometry_simulator import _normalized_airmass

def utc(s): return datetime.fromisoformat(s.replace('Z', '+00:00'))
def csvrows(p):
    with p.open(newline='') as f: return list(csv.DictReader(f))
def dump(name, data):
    p = OUT / name
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + '\n')
    return hashlib.sha256(p.read_bytes()).hexdigest()

REF = {
    'L1': ROOT / 'formal_v4/results/geometry_native_20261003/protocol_gate_remaining/L1',
    'L2': ROOT / 'formal_v4/results/geometry_native_20261003/protocol_gate_retry/L2',
    'L3': ROOT / 'formal_v4/results/geometry_native_20261003/protocol_gate_remaining/L3',
    'L4': ROOT / 'formal_v4/results/geometry_native_20261003/protocol_gate_retry/L4',
}

def public_certificates(card, ref):
    """Input projection uses only initialize, public bulletin, action and hits."""
    base = UP / 'local-cards' / card
    cfg = json.loads((base / 'config/v4_scenario.json').read_text())
    score = json.loads((base / 'config/v4_score_config.json').read_text())
    site = cfg['site']; lat, lon = site['latitude_deg'], site['longitude_deg']
    targets = {t['target_id']: {k: (float(v) if k in ['ra_deg','dec_deg','feature_flux','science_weight'] else v)
        for k, v in t.items()} for t in csvrows(base / 'public/targets.csv')}
    nights = [(utc(n['observing_start_utc']), utc(n['observing_end_utc']))
        for n in csvrows(base / 'public/v4_night_calendar.csv')]
    bulletins = [json.loads(l) for l in (base / 'public/v4_bulletins.jsonl').read_text().splitlines()]
    hits = defaultdict(list)
    for r in csvrows(ref / 'observations.csv'):
        hits[int(r['observe_index'])].append({'target_id': r['target_id'], 'score': float(r['score'])})
    stats = defaultdict(int); certificates = []; positive_constraints = []
    multipliers = [score['program']['mismatch_multiplier'], *score['program']['multipliers'].values()]
    mmin, mmax = min(multipliers), max(multipliers)
    for d in csvrows(ref / 'decisions.csv'):
        if d['action'] != 'observe': continue
        stats['observe'] += 1
        duration = int(d['duration_seconds']); start, end = utc(d['start_utc']), utc(d['end_utc'])
        if duration > 120 or duration <= 0: continue
        stats['short'] += 1
        night = next(((a,b) for a,b in nights if a <= start < b), None)
        if night is None: continue
        slot_start = night[0] + timedelta(seconds=900 * math.floor((start-night[0]).total_seconds()/900))
        if end > min(slot_start + timedelta(seconds=900), night[1]): continue
        stats['single_public_slot'] += 1
        bulletin = next((b for b in reversed(bulletins) if utc(b['issued_at_utc']) <= start), None)
        if not bulletin or utc(bulletin['issued_at_utc']) != slot_start: continue
        if any(n['event_kind'] != 'terrain_obstruction' for n in bulletin['notices']): continue
        stats['no_temporary_notice'] += 1
        mid = start + (end-start)/2; h = hits[int(d['observe_index'])]
        positives = [r for r in h if r['score'] > 0]; zeros = [r for r in h if r['score'] == 0]
        stats['positive_hit'] += len(positives); stats['zero_hit'] += len(zeros)
        if positives and zeros: stats['mixed_exposure'] += 1
        def k(row):
            t = targets[row['target_id']]
            alt, az = radec_to_altaz(t['ra_deg'], t['dec_deg'], mid, lat, lon)
            geom = lunar_quality_factor(t['ra_deg'], t['dec_deg'], mid, site, score) / _normalized_airmass(alt)**score['airmass_exponent']
            return t['science_weight'] * t['feature_flux'] * geom, alt, az
        for p in positives:
            _, alt, az = k(p)
            positive_constraints.append({'observe_index': int(d['observe_index']), 'target_id': p['target_id'],
                'mid_utc': mid.isoformat(), 'alt': alt, 'az': az, 'covered': False})
        for z in zeros:
            kz, altz, azz = k(z); wz = targets[z['target_id']]['science_weight']
            # If anchor is saturated this is still a lower bound on common K.
            # The public program mismatch/matching multipliers bound both scores.
            lower = max((mmin*min(wz, (p['score']-0.5e-6)/mmax * kz/k(p)[0])
                for p in positives if k(p)[0] > 0), default=0)
            if lower <= 0.5e-6: continue
            certificates.append({'observe_index': int(d['observe_index']), 'target_id': z['target_id'],
                'mid_utc': mid.isoformat(), 'alt': altz, 'az': azz, 'covered': True,
                'counterfactual_unblocked_score_lower_bound': lower,
                'anchor_target_ids': [p['target_id'] for p in positives]})
    return {'card': card, 'stats': dict(stats), 'zero_certificates': certificates,
        'positive_constraints': positive_constraints,
        'actor_inputs': ['public initialize targets/site/scoring/nights', 'already published current bulletin',
            'own start/end/duration and observe index', 'public last_result target_id and score'],
        'not_actor_inputs': ['factor', 'quality', 'prog_mult', 'fiber_id', 'weather truth', 'events truth', 'future bulletin']}

def audit_truth(record):
    """Offline evaluator only; called after public record JSON has been committed."""
    terrain = [e for e in csvrows(UP/'local-cards'/record['card']/'truth/v4_events.csv')
        if e['event_type'] == 'terrain_obstruction']
    def covered(c):
        t = utc(c['mid_utc'])
        for e in terrain:
            if not utc(e['actual_start_utc']) <= t < utc(e['actual_end_utc']): continue
            lo, hi = float(e['azimuth_start_deg']), float(e['azimuth_end_deg'])
            az = c['az']; inside = lo <= az <= hi if lo <= hi else az >= lo or az <= hi
            if inside and float(e['min_altitude_deg']) <= c['alt'] <= float(e['max_altitude_deg']): return True
        return False
    false_zero = [c for c in record['zero_certificates'] if not covered(c)]
    false_positive = [c for c in record['positive_constraints'] if covered(c)]
    return {'card': record['card'], 'zero_count': len(record['zero_certificates']),
        'zero_false_certificate_count': len(false_zero), 'positive_count': len(record['positive_constraints']),
        'positive_false_certificate_count': len(false_positive), 'false_zero': false_zero,
        'false_positive': false_positive, 'scope': 'separate offline hidden-terrain audit after public decision labels frozen'}

def synthetic():
    """Two same-public-message worlds and a public-feedback branching policy.

    Model deliberately exposes one last 900 s slot; Jain=0 and no requests/loss.
    Full geometry, path integration, banding, best ledger and required settlement
    are official. It proves a mechanism, not that actual card action pool gains.
    """
    cfg = json.loads((UP/'local-cards/L1/config/v4_score_config.json').read_text())
    cfg['uniformity']['weight'] = 0.0
    site = {'latitude_deg': -24.6157, 'longitude_deg': -70.3976}
    lat, lon = site['latitude_deg'], site['longitude_deg']
    start = utc('2026-11-02T02:00:00Z'); end = start + timedelta(seconds=900)
    grid = FiberGrid(0.4, 0.0, 16)
    # Public synthetic catalogue is built before either hidden world.
    def target(tid, alt, az, weight, required=False, flux=10.):
        ra, dec = altaz_to_radec(alt, az, start, lat, lon)
        return {'target_id': tid, 'ra_deg': ra, 'dec_deg': dec, 'science_weight': weight,
            'feature_flux': flux, 'required': required, 'target_class': 'Star'}
    targets = [target('probe_anchor',42.5,180.3,.01),
        target('A_required',41.4,180.3,5.0,True,flux=.25),target('B_safe',60,100,20.0,flux=.2)]
    tmap = {t['target_id']:t for t in targets}
    public = {'targets': targets, 'site': site, 'scoring': cfg,
        'initial_bulletin': {'notices':[{'event_kind':'terrain_obstruction','direction':'S'}]},
        'survey': {'start_utc':start.isoformat(),'end_utc':end.isoformat()},
        'declared_prior': [{'height_cap':40.,'p':.5},{'height_cap':42.2,'p':.5}],
        'assumption': 'same visible terrain S notice; exactly one of two prior sectors'}
    dump('synthetic_public.json', public)
    def action(ids, moment, duration):
        # midpoint among target positions determines command; classify via exact grid.
        positions = [radec_to_altaz(tmap[i]['ra_deg'],tmap[i]['dec_deg'],moment,lat,lon) for i in ids]
        alt = sum(p[0] for p in positions)/len(positions); az = sum(p[1] for p in positions)/len(positions)
        if len(ids)==1: alt += .16; az += .16 # avoid seams
        assignments = {}
        for tid in ids:
            t = tmap[tid]; cl = grid.classify_target(t['ra_deg'],t['dec_deg'],moment,alt,az,lat,lon)
            assert cl.region == 'glass' and str(cl.fiber_id) not in assignments
            assignments[str(cl.fiber_id)] = tid
        return {'action':'observe','duration_seconds':duration,'program':'DARK',
            'pointing':{'alt_deg':alt,'az_deg':az},'assignments':assignments}
    def simulate(height, policy):
        truth = SlotTruth('synthetic-S001',start,end,True,1.,1.,1.,1.)
        weather = WeatherTruth([truth],None)
        event = ScoreEvent('synthetic-terrain','terrain_obstruction',start,end,'HORIZON_SECTOR',150.,210.,0.,height,1.,1.,1.,1.)
        ledger = BestLedger(); now = start; tape=[]
        for idx in range(2 if policy in ('probe_adaptive','probe_no_update') else 1):
            if idx==0 and policy.startswith('probe_'): ids=['A_required','probe_anchor']; duration=60
            elif idx==0: ids=[policy]; duration=900
            else:
                # Actor has only public score IDs. Hidden height is not read.
                seen = {h['target_id']: h['score'] for h in tape[-1]['last_result']['hits']}
                choose_A = policy == 'probe_no_update' or seen.get('A_required',0)>0
                ids=['A_required' if choose_A else 'B_safe']; duration=840
            a=action(ids,now,duration); stop=now+timedelta(seconds=duration); hits=[]
            for fid,tid in a['assignments'].items():
                t=tmap[tid]
                assert min_altitude_during(t['ra_deg'],t['dec_deg'],now,stop,{'site':site}) >= 30.
                altaz=lambda m,t=t:radec_to_altaz(t['ra_deg'],t['dec_deg'],m,lat,lon)
                seg=list(weather.segments(now,stop))
                band=weather.band_quality(now,stop,cfg,lambda m:altaz(m)[0],
                    lambda m,t=t:lunar_quality_factor(t['ra_deg'],t['dec_deg'],m,site,cfg))
                mult=program_multiplier(a['program'],program_band(band,cfg),cfg)
                s=score_target_exposure(t,seg,[event],weather,duration,mult,cfg,now,altaz,site)
                ledger.record(idx,tid,s.factor,s.score,now,stop)
                hits.append({'target_id':tid,'score':round(s.score,6)})
            tape.append({'start_utc':now.isoformat(),'action':a,'last_result':{'action':'observe','hits':hits}})
            now=stop
        factors=ledger.max_factors(); missing,penalty=required_penalty(targets,factors,cfg)
        bands,jain=uniformity_penalty(targets,factors,cfg)
        science=sum(x[1] for x in ledger.best().values())
        return {'score':science-penalty-jain,'science':science,'required_missing':missing,'tape':tape}
    worlds={str(h):{p:simulate(h,p) for p in ['A_required','B_safe','probe_no_update','probe_adaptive']} for h in [40.,42.2]}
    expectation={p:sum(w[p]['score'] for w in worlds.values())/2 for p in ['A_required','B_safe','probe_no_update','probe_adaptive']}
    best_no_probe=max(expectation[p] for p in ['A_required','B_safe'])
    assert worlds['40.0']['probe_adaptive']['tape'][1]['action']['assignments'] != worlds['42.2']['probe_adaptive']['tape'][1]['action']['assignments']
    assert expectation['probe_adaptive'] > best_no_probe
    return {'worlds':worlds,'expected_score':expectation,'gain_over_best_no_probe':expectation['probe_adaptive']-best_no_probe,
        'gain_from_feedback_branching_same_probe':expectation['probe_adaptive']-expectation['probe_no_update'],
        'scope':'official scorer synthetic mechanism only, restricted two terminal action choices, not a card score claim'}

def main():
    start=time.perf_counter(); audits=[]; hashes={}
    for card,ref in REF.items():
        record=public_certificates(card,ref)
        hashes[card]=dump(f'{card}_public_certificates.json',record)
        audits.append(audit_truth(record))
    dump('offline_truth_audit.json',audits)
    mechanism=synthetic(); dump('synthetic_result.json',mechanism)
    summary={'wallclock_seconds':time.perf_counter()-start,'public_records_sha256_before_truth_audit':hashes,
        'source_sha256': {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [
            Path(__file__).resolve(), UP/'runner/challenge/v4_scorer.py',
            UP/'runner/challenge/v4_fiber_map.py', UP/'runner/challenge/v4_runner.py',
            UP/'docs/participant-guide.zh.md']},
        'reference_input_sha256': {card:{name:hashlib.sha256((ref/name).read_bytes()).hexdigest()
            for name in ['decisions.csv','observations.csv']} for card,ref in REF.items()},
        'card_audits':[{k:v for k,v in a.items() if k not in ['false_zero','false_positive']} for a in audits],
        'synthetic_expected_score':mechanism['expected_score'],
        'synthetic_gain_over_best_no_probe':mechanism['gain_over_best_no_probe'],
        'synthetic_branching_gain':mechanism['gain_from_feedback_branching_same_probe'],
        'participant_truth_access':False,'season_replanning_executed':False,'remote_jobs_started':False}
    dump('MANIFEST.json',summary); print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
