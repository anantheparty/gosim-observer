#!/usr/bin/env python3
"""Independent, finite-family pruning certificates using only the official v4 runner.

This is an offline local-card experiment, not a global continuous-pointing solver.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
import time
from datetime import timedelta
import numpy as np

HERE = Path(__file__).resolve().parents[1]
UPSTREAM = HERE / "upstream/gosim-observer-examples"
sys.path.insert(0, str(UPSTREAM / "runner"))
from challenge.v4_runner import load_scenario, _pointing_offset, _data_loss_plan, run_scenario
from challenge.v4_fiber_map import FiberGrid, radec_to_altaz, min_altitude_during
from challenge.v4_scorer import (WeatherTruth, lunar_quality_factor, program_band,
    program_multiplier, score_target_exposure)


def jain_box_upper(lower, upper):
    """Exact continuous box maximum of Jain; upper bound for integer band counts.

    At a positive optimum x=clip(c,l,u), Q=c*S. For every feasible y,
    sum (x-c)*(y-x)>=0, hence x.y>=c*sum(y). Cauchy-Schwarz yields
    sum(y)^2/sum(y^2)<=sum(x)^2/sum(x^2). Bisection finds a root.
    """
    l = np.asarray(lower, dtype=float)
    u = np.asarray(upper, dtype=float)
    assert np.all(0 <= l) and np.all(l <= u)
    if len(l) == 0 or np.max(u) == 0:
        return 0.0
    if np.array_equal(l,u):
        return min(1.0, float(l.sum()**2/(len(l)*np.dot(l,l))) + 1e-12)
    if np.max(l) == 0:
        # Put equal small positive ratios in all and only positive-upper bands.
        return min(1.0, float(np.count_nonzero(u)/len(u)) + 1e-12)
    if np.max(l) <= np.min(u) and np.min(u) > 0:
        return 1.0
    lo, hi = 0.0, float(np.max(u))
    for _ in range(48):
        c = (lo + hi) / 2
        x = np.clip(c, l, u)
        if float(np.dot(x, x) - c * x.sum()) >= 0:
            lo = c
        else:
            hi = c
    # Keep the nonnegative-residual side. Even before exact convergence,
    # Q-c*S>=0 gives x.y>=c*sum(y), hence Q/(K*c*c) is an upper certificate.
    if lo == 0:
        return 1.0  # Conservative floating-point fallback.
    x = np.clip(lo, l, u)
    return min(1.0, float(np.dot(x,x)/(len(x)*lo*lo)) + 1e-12)


def validate_jain():
    rng = np.random.default_rng(311)
    cases = checked = 0
    worst = 0.0
    for k in (2, 3, 4, 5):
        for _ in range(100):
            total = rng.integers(2, 7, k)
            low = np.array([rng.integers(0, n + 1) for n in total])
            high = np.array([rng.integers(l, n + 1) for l, n in zip(low, total)])
            ub = jain_box_upper(low / total, high / total)
            for counts in itertools.product(*(range(l, h + 1) for l, h in zip(low, high))):
                x = np.array(counts) / total
                value = 0.0 if np.dot(x, x) == 0 else x.sum()**2 / (k * np.dot(x, x))
                worst = max(worst, value - ub)
                assert value <= ub + 1e-12, (low, high, total, counts, value, ub)
                checked += 1
            cases += 1
    return {"boxes": cases, "integer_vectors": checked, "largest_violation": worst}


def build_columns(scenario, stages, duration):
    grid = FiberGrid.from_config(scenario.fiber_config)
    offset_alt, offset_az = _pointing_offset(scenario)
    weather = WeatherTruth(scenario.slots, [e for e in scenario.events if e.event_type == "instrument_fault"])
    requests = [r for r in scenario.observation_requests if r['issued_at_utc'] <= scenario.survey_end]
    request = requests[-1]
    start = request['issued_at_utc'] + timedelta(hours=2)
    loss = _data_loss_plan(scenario)
    assert loss is None or start >= loss.trigger_utc, "experiment requires no future invalidation"
    target_map = {t['target_id']: t for t in scenario.targets}
    # Eight prescribed request-centered pointings, plus two prescribed required targets.
    centers = list(request['target_ids'])
    for t in sorted(scenario.targets, key=lambda t: (-t['required'], -t['science_weight'], t['target_id'])):
        alt, _ = radec_to_altaz(t['ra_deg'], t['dec_deg'], start, **{
            'latitude_deg': scenario.site['latitude_deg'], 'longitude_deg': scenario.site['longitude_deg']})
        if t['required'] and alt >= 40 and t['target_id'] not in centers:
            centers.append(t['target_id'])
            if len(centers) >= 10:
                break
    lat, lon = scenario.site['latitude_deg'], scenario.site['longitude_deg']
    all_columns = []
    geometry_checks = 0
    for s in range(stages):
        moment = start + timedelta(seconds=s * duration)
        end = moment + timedelta(seconds=duration)
        segments = list(weather.segments(moment, end))
        directional = [e for e in scenario.events if e.scope_type == 'HORIZON_SECTOR' and e.overlaps(moment, end)]
        # A deliberately empty observe keeps duration and observe count identical.
        stage_columns = [{'name': 'empty', 'scores': {}, 'factors': {},
            'action': {'action': 'observe', 'pointing': {'alt_deg': 45., 'az_deg': 180.},
                       'assignments': {}, 'duration_seconds': duration, 'program': 'BACKUP'},
            'start': moment, 'end': end}]
        for center_id in centers:
            center = target_map[center_id]
            actual_alt, actual_az = radec_to_altaz(center['ra_deg'], center['dec_deg'], moment, lat, lon)
            cmd_alt, cmd_az = actual_alt - offset_alt, (actual_az - offset_az) % 360
            if not 0 <= cmd_alt <= 90:
                continue
            cells = {}
            for t in scenario.targets:
                classified = grid.classify_target(t['ra_deg'], t['dec_deg'], moment, cmd_alt, cmd_az,
                                                   lat, lon, offset_alt, offset_az)
                if classified.region != 'glass':
                    continue
                geometry_checks += 1
                if min_altitude_during(t['ra_deg'], t['dec_deg'], moment, end, scenario.config) < scenario.minimum_altitude_deg:
                    continue
                priority = (t['target_id'] in request['target_ids'], t['required'], t['science_weight'], t['feature_flux'], t['target_id'])
                fiber = classified.fiber_id
                if fiber not in cells or priority > cells[fiber][0]:
                    cells[fiber] = (priority, t)
            assignments = {int(f): t['target_id'] for f, (_, t) in cells.items()}
            facts = {}
            bands = {}
            for _, t in cells.values():
                def altaz_at(m, t=t):
                    return radec_to_altaz(t['ra_deg'], t['dec_deg'], m, lat, lon)
                qb = weather.band_quality(moment, end, scenario.score_config, lambda m: altaz_at(m)[0],
                    lambda m, t=t: lunar_quality_factor(t['ra_deg'], t['dec_deg'], m, scenario.site, scenario.score_config))
                bands[t['target_id']] = program_band(qb, scenario.score_config)
                facts[t['target_id']] = score_target_exposure(t, segments, directional, weather, duration, 1.,
                    scenario.score_config, moment, altaz_at, scenario.site)
            for program in ('DARK', 'BRIGHT', 'BACKUP'):
                stage_columns.append({'name': f'{center_id}:{program}',
                    'scores': {tid: v.score * program_multiplier(program, bands[tid], scenario.score_config) for tid, v in facts.items()},
                    'factors': {tid: v.factor for tid, v in facts.items()},
                    'action': {'action': 'observe', 'pointing': {'alt_deg': cmd_alt, 'az_deg': cmd_az},
                               'assignments': assignments, 'duration_seconds': duration, 'program': program},
                    'start': moment, 'end': end})
        all_columns.append(stage_columns)
    return start, requests, all_columns, geometry_checks


class FiniteModel:
    def __init__(self, scenario, requests, columns):
        self.scenario = scenario
        self.requests = [r for r in requests if r['issued_at_utc'] <= columns[-1][0]['end']]
        ids = sorted({tid for stage in columns for c in stage for tid in c['factors']})
        self.ids = ids
        self.index = {tid: i for i, tid in enumerate(ids)}
        target_map = {t['target_id']: t for t in scenario.targets}
        self.required = np.array([target_map[tid]['required'] for tid in ids])
        self.required_total = sum(t['required'] for t in scenario.targets)
        width = scenario.score_config['uniformity']['ra_band_width_deg']
        bands = sorted({int(t['ra_deg'] // width) for t in scenario.targets})
        band_index = {b: i for i, b in enumerate(bands)}
        self.band = np.array([band_index[int(target_map[tid]['ra_deg'] // width)] for tid in ids])
        self.band_total = np.array([sum(int(t['ra_deg']//width) == b for t in scenario.targets) for b in bands])
        self.request_indices = [np.array([self.index[tid] for tid in r['target_ids'] if tid in self.index], dtype=int) for r in self.requests]
        self.score_cfg = scenario.score_config
        self.columns = columns
        self.raw_counts = [len(s) for s in columns]
        self.dominance_witnesses = []
        self.stages = []
        for si, stage in enumerate(columns):
            for c in stage:
                c['b'] = np.array([c['scores'].get(tid, 0.) for tid in ids])
                c['f'] = np.array([c['factors'].get(tid, 0.) for tid in ids])
                c['r'] = np.array([[c['factors'].get(tid, 0.) if req['issued_at_utc'] <= c['start'] and c['end'] <= req['deadline_utc'] else 0. for tid in ids] for req in self.requests])
            retained = []
            for ci, c in enumerate(stage):
                witness = next((di for di, d in enumerate(stage) if di != ci and
                    np.array_equal(c['f'], d['f']) and np.array_equal(c['r'], d['r']) and
                    np.all(d['b'] >= c['b']) and (np.any(d['b'] > c['b']) or di < ci)), None)
                if witness is None:
                    retained.append(c)
                else:
                    self.dominance_witnesses.append({'stage': si, 'removed': c['name'], 'witness': stage[witness]['name']})
            self.stages.append(retained)
        # The transitive witness may itself be removed; every chain terminates in a retained action.
        n, q = len(ids), len(self.requests)
        self.suffix_b = [np.zeros(n) for _ in range(len(columns)+1)]
        self.suffix_f = [np.zeros(n) for _ in range(len(columns)+1)]
        self.suffix_r = [np.zeros((q,n)) for _ in range(len(columns)+1)]
        for s in reversed(range(len(columns))):
            self.suffix_b[s] = np.maximum(self.suffix_b[s+1], np.max([c['b'] for c in self.stages[s]], axis=0))
            self.suffix_f[s] = np.maximum(self.suffix_f[s+1], np.max([c['f'] for c in self.stages[s]], axis=0))
            self.suffix_r[s] = np.maximum(self.suffix_r[s+1], np.max([c['r'] for c in self.stages[s]], axis=0))

    def zero(self):
        return np.zeros(len(self.ids)), np.zeros(len(self.ids)), np.zeros((len(self.requests), len(self.ids)))

    def apply(self, state, c):
        return tuple(np.maximum(x, c[k]) for x,k in zip(state, ('b','f','r')))

    def settlement(self, state):
        b,f,r = state
        rcfg, ucfg = self.score_cfg['required'], self.score_cfg['uniformity']
        missing = self.required_total - np.sum(self.required & (f >= rcfg['observed_factor_threshold']))
        counts = np.bincount(self.band[f >= ucfg['observed_factor_threshold']], minlength=len(self.band_total))
        ratios = counts/self.band_total
        square = np.dot(ratios, ratios)
        jain = 0. if square == 0 else ratios.sum()**2/(len(ratios)*square)
        reqreward = sum(req['completion_reward'] for qi,(req,ii) in enumerate(zip(self.requests,self.request_indices))
            if np.sum(r[qi,ii] >= req['completion_factor_threshold']) >= req['minimum_completed'])
        return float(b.sum() - missing*rcfg['penalty_per_missing'] - ucfg['weight']*(1-jain) + reqreward)

    def bound(self, s, state):
        b,f,r = state
        sb,sf,sr = self.suffix_b[s],self.suffix_f[s],self.suffix_r[s]
        rcfg,ucfg = self.score_cfg['required'],self.score_cfg['uniformity']
        possible = np.maximum(f,sf)
        current_req = self.required & (f >= rcfg['observed_factor_threshold'])
        unmet_req = self.required & ~current_req
        bonus = rcfg['penalty_per_missing']
        target_gain = np.maximum(sb-b,0) + bonus*(unmet_req & (sf >= rcfg['observed_factor_threshold']))
        stage_gain = sum(max((np.maximum(c['b']-b,0) + bonus*(unmet_req & (c['f'] >= rcfg['observed_factor_threshold']))).sum()
                             for c in stage) for stage in self.stages[s:])
        science_required = b.sum() - bonus*(self.required_total - current_req.sum()) + min(target_gain.sum(),stage_gain)
        low = np.bincount(self.band[f >= ucfg['observed_factor_threshold']], minlength=len(self.band_total)) / self.band_total
        high = np.bincount(self.band[possible >= ucfg['observed_factor_threshold']], minlength=len(self.band_total)) / self.band_total
        uniformity = ucfg['weight']*(1-jain_box_upper(low,high))
        reqpossible = np.maximum(r,sr)
        reqreward = sum(req['completion_reward'] for qi,(req,ii) in enumerate(zip(self.requests,self.request_indices))
            if np.sum(reqpossible[qi,ii] >= req['completion_factor_threshold']) >= req['minimum_completed'])
        return float(science_required - uniformity + reqreward)

    def exhaustive(self, raw=False, validate_bound=False):
        counts = {'nodes': 0, 'leaves': 0, 'bound_checks': 0, 'bound_violations': 0, 'largest_violation': 0.}
        family = self.columns if raw else self.stages
        def visit(s,state):
            counts['nodes'] += 1
            if s == len(family):
                counts['leaves'] += 1
                return self.settlement(state), []
            best,seq = -math.inf,None
            for c in family[s]:
                v,tail=visit(s+1,self.apply(state,c))
                if v > best:
                    best,seq = v,[c]+tail
            if validate_bound:
                ub = self.bound(s,state)
                violation = best-ub
                counts['bound_checks'] += 1
                counts['largest_violation'] = max(counts['largest_violation'],violation)
                if violation > 1e-9:
                    counts['bound_violations'] += 1
                    raise AssertionError(('inadmissible bound',s,best,ub))
            return best,seq
        begun=time.perf_counter()
        best,seq=visit(0,self.zero())
        counts['seconds']=time.perf_counter()-begun
        return best,seq,counts

    def branch_bound(self):
        counts={'nodes':0,'leaves':0,'pruned_nodes':0,'pruned_leaves':0}
        incumbent=-math.inf
        winner=None
        def visit(s,state,path):
            nonlocal incumbent,winner
            counts['nodes']+=1
            if s == len(self.stages):
                counts['leaves']+=1
                value=self.settlement(state)
                if value>incumbent:
                    incumbent,winner=value,path
                return
            if self.bound(s,state) < incumbent-1e-9:
                counts['pruned_nodes']+=1
                counts['pruned_leaves']+=math.prod(len(stage) for stage in self.stages[s:])
                return
            children=[(self.apply(state,c),c) for c in self.stages[s]]
            children.sort(key=lambda pair:self.bound(s+1,pair[0]),reverse=True)
            for child,c in children:
                visit(s+1,child,path+[c])
        begun=time.perf_counter()
        visit(0,self.zero(),[])
        counts['seconds']=time.perf_counter()-begun
        return incumbent,winner,counts


def run_card(card, out, stages, duration, raw_stages):
    begun=time.perf_counter()
    scenario_path=UPSTREAM/'local-cards'/card/'config/v4_scenario.json'
    scenario=load_scenario(scenario_path)
    start,requests,columns,geometry_checks=build_columns(scenario,stages,duration)
    model=FiniteModel(scenario,requests,columns)
    best,sequence,exhaustive=model.exhaustive(validate_bound=True)
    bb_best,bb_sequence,bb=model.branch_bound()
    assert abs(best-bb_best)<1e-8
    # Raw Cartesian family check on a shorter, explicit interval.
    raw_model=FiniteModel(scenario,requests,columns[:raw_stages])
    raw_best,_,raw_counts=raw_model.exhaustive(raw=True)
    reduced_best,_,reduced_counts=raw_model.exhaustive()
    assert abs(raw_best-reduced_best)<1e-8
    actions=[{'action':'wait','until_utc':start.strftime('%Y-%m-%dT%H:%M:%SZ')}]+[c['action'] for c in sequence]+[{'action':'finish'}]
    iterator=iter(actions)
    report=run_scenario(scenario_path,lambda context:lambda snapshot:next(iterator,None),out/card/'native')
    assert abs(report['total']-best)<2e-6,(report['total'],best)
    sourcepaths=[UPSTREAM/'runner/challenge'/x for x in ('v4_runner.py','v4_scorer.py','v4_fiber_map.py',
                                                       'tile_geometry_simulator.py','v4_config_check.py','contracts.py')]
    sourcepaths += sorted(p for p in (UPSTREAM/'local-cards'/card).rglob('*') if p.is_file())
    manifest={str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sourcepaths}
    summary={'card':card,'scope':'finite, prescribed pointing centers and one prescribed assignment per center; empty initial ledger; no future loss; no reports; no continuation after interval',
        'start_utc':start.isoformat(),'stages':stages,'duration_seconds':duration,'target_universe':len(model.ids),
        'geometry_on_glass_checked':geometry_checks,'raw_stage_counts':model.raw_counts,'retained_stage_counts':[len(s) for s in model.stages],
        'raw_full_family_leaves':math.prod(model.raw_counts),'retained_full_family_leaves':math.prod(len(s) for s in model.stages),
        'dominated_actions':len(model.dominance_witnesses),'dominance_witnesses':model.dominance_witnesses,
        'exhaustive_best':best,'branch_bound_best':bb_best,'exhaustive':exhaustive,'branch_bound':bb,
        'raw_short_interval':{'stages':raw_stages,'raw_best':raw_best,'reduced_best':reduced_best,'raw':raw_counts,'reduced':reduced_counts},
        'native_total':report['total'],'native_counts':report['counts'],'native_components':report['components'],
        'wall_seconds':time.perf_counter()-begun,'source_sha256':manifest,
        'best_actions':[c['action'] for c in sequence]}
    (out/card).mkdir(parents=True,exist_ok=True)
    (out/card/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ['card','raw_stage_counts','retained_stage_counts','exhaustive_best','exhaustive','branch_bound','native_total','wall_seconds']}),flush=True)
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--cards',nargs='+',default=['L1','L2','L3','L4']);p.add_argument('--stages',type=int,default=4)
    p.add_argument('--duration',type=int,default=900);p.add_argument('--raw-stages',type=int,default=3)
    p.add_argument('--out',type=Path,default=HERE/'results/cold_pruning_proofs_20261003')
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    jain=validate_jain();print('jain',json.dumps(jain),flush=True)
    summaries=[run_card(c,args.out,args.stages,args.duration,args.raw_stages) for c in args.cards]
    compact={'jain_validation':jain,'cards':[{k:v for k,v in s.items() if k not in ['source_sha256','best_actions','dominance_witnesses']} for s in summaries]}
    (args.out/'summary.json').write_text(json.dumps(compact,indent=2)+'\n')

if __name__=='__main__':main()
