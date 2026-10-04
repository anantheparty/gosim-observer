"""Four wholly new official generated worlds, host labels, public-only history pilot."""
from __future__ import annotations
import csv, hashlib, json, shutil, sys, time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'official'))
from challenge import v4_catalog_generator as catalog, v4_weather_simulator as gen
from challenge.v4_runner import load_scenario, run_scenario, _pointing_offset
from challenge.v4_scorer import (WeatherTruth, BestLedger, score_target_exposure,
    program_band, program_multiplier, lunar_quality_factor)
from challenge.v4_fiber_map import FiberGrid, radec_to_altaz, min_altitude_during
from challenge.v4_config_check import cross_validate_generator_configs
from target_core import K, PROGRAMS, soft_label, moments, expected_gain, first_gain, PublicHistory

def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')

def utc(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))

def bundle(seed, lock):
    base = ROOT / 'worlds' / str(seed)
    if base.exists():
        return base
    ref = ROOT / 'official/challenge/reference/v4'
    cat = json.loads((ref / 'v4_catalog_config.json').read_text())
    cfg = json.loads((ref / 'v4_weather_config.json').read_text())
    for config in (cat, cfg):
        config.update(seed=seed, seed_derivation='sha256-v1')
    cat['targets']['total_count'] = lock['catalog_targets']
    cat['footprint'].update(total_area_deg2=lock['catalog_area_deg2'],n_components=2,
        component_area_weights=[.6,.4],vertices_per_component=24)
    cat['observability'].update(start_date=lock['start_date'], end_date=lock['end_date'])
    cfg['survey'].update(start_date=lock['start_date'], end_date=lock['end_date'])
    cfg['stress_tests']['enabled'] = True
    # Four pilot worlds retain the official reference event counts, not labels from old worlds.
    scenario = json.loads((ROOT / 'v4_scenario.json').read_text())
    scenario['name'] = 'direct-target-pilot-' + str(seed)
    scenario['stress'] = dict(enabled=True,stress_events_csv='../truth/v4_stress_events.csv')
    scenario['task_card'] = dict(card_id='fresh-'+str(seed),phase='independent-stage1',scenario_slug=scenario['name'])
    fiber = json.loads((ROOT/'v4_fiber_config.json').read_text())
    cross_validate_generator_configs(cat,cfg,scenario,fiber,require_hashed_seeds=True)
    for name in ['generator','config','public','truth']:
        (base/name).mkdir(parents=True,exist_ok=True)
    dump(base/'generator/catalog.json',cat);dump(base/'generator/weather.json',cfg)
    scratch=base/'generator/output'
    catalog.generate_catalog(base/'generator/catalog.json',scratch)
    gen.generate(base/'generator/weather.json',scratch)
    publics=['targets.csv','footprint.csv','v4_night_calendar.csv','v4_bulletins.jsonl','v4_forecasts.jsonl']
    for p in scratch.iterdir():
        if p.name in publics:
            shutil.copyfile(p,base/'public'/p.name)
        elif p.name in ['v4_slots.csv','v4_weather_truth.csv','v4_events.csv','v4_earthquake_effects.csv','v4_stress_events.csv']:
            shutil.copyfile(p,base/'truth'/p.name)
    (base/'truth/v4_observation_requests.jsonl').write_text('')
    dump(base/'config/v4_scenario.json',scenario)
    shutil.copyfile(ROOT/'v4_score_config.json',base/'config/v4_score_config.json')
    shutil.copyfile(ROOT/'v4_fiber_config.json',base/'config/v4_fiber_config.json')
    return base

def design(scenario, start, duration, rng):
    lat,lon=float(scenario.site['latitude_deg']),float(scenario.site['longitude_deg'])
    grid=FiberGrid.from_config(scenario.fiber_config)
    visible=[]
    for target in scenario.targets:
        alt,az=radec_to_altaz(target['ra_deg'],target['dec_deg'],start,lat,lon)
        if alt>=31:
            visible.append((target,alt,az))
    if not visible:return None
    target,alt,az=visible[int(rng.integers(len(visible)))]
    # Public candidates; offset is neither passed to this function nor used for sampling.
    center=(float(np.clip(alt+rng.uniform(-.2,.2),30,88)),float((az+rng.uniform(-.2,.2))%360))
    cells={}
    end=start+timedelta(seconds=duration)
    for t,_,_ in visible:
        if min_altitude_during(t['ra_deg'],t['dec_deg'],start,end,scenario.config)<scenario.minimum_altitude_deg:
            continue
        c=grid.classify_target(t['ra_deg'],t['dec_deg'],start,*center,lat,lon)
        if c.region=='glass':
            # Keep one public target per cell; no private factor or future label ranks targets.
            previous=cells.get(c.fiber_id)
            if previous is None or t['science_weight']>previous['science_weight']:
                cells[c.fiber_id]=t
    if not cells:return None
    return dict(action='observe',pointing=dict(alt_deg=center[0],az_deg=center[1]),
        duration_seconds=duration,program=PROGRAMS[int(rng.integers(3))],
        assignments={str(f):t['target_id'] for f,t in cells.items()})

def labels(scenario, weather, action, start):
    grid=FiberGrid.from_config(scenario.fiber_config)
    lat,lon=float(scenario.site['latitude_deg']),float(scenario.site['longitude_deg'])
    da,dz=_pointing_offset(scenario)
    targetmap={t['target_id']:t for t in scenario.targets}
    end=start+timedelta(seconds=action['duration_seconds'])
    pieces=list(weather.segments(start,end))
    events=[e for e in scenario.events if e.scope_type=='HORIZON_SECTOR' and e.overlaps(start,end)]
    out=[]
    for f,tid in action['assignments'].items():
        target=targetmap[tid]
        c=grid.classify_target(target['ra_deg'],target['dec_deg'],start,
            action['pointing']['alt_deg'],action['pointing']['az_deg'],lat,lon,da,dz)
        if c.region!='glass' or c.fiber_id!=int(f):continue
        def pos(t):return radec_to_altaz(target['ra_deg'],target['dec_deg'],t,lat,lon)
        b=program_band(weather.band_quality(start,end,scenario.score_config,lambda t:pos(t)[0],
            lambda t:lunar_quality_factor(target['ra_deg'],target['dec_deg'],t,scenario.site,scenario.score_config)),scenario.score_config)
        score=score_target_exposure(target,pieces,events,weather,action['duration_seconds'],1.,
            scenario.score_config,start,pos,scenario.site)
        out.append(dict(target_id=tid,g=score.factor,b=PROGRAMS.index(b),w=target['science_weight'],
            public_score=round(score.score*program_multiplier(action['program'],b,scenario.score_config),6)))
    return out

def small_runtime(scenario_path, seed):
    """Stop after twelve observations; official runner validates the public interface."""
    scenario=load_scenario(scenario_path)
    rng=np.random.default_rng(seed+16000000)
    history=PublicHistory();actions=[];snapshots=[];pending=None;n=0;report_next=False
    def factory(_context):
        def actor(s):
            nonlocal pending,n,report_next
            snapshots.append(s)
            result=s.get('last_result') or {}
            if result.get('action')=='observe' and pending is not None:
                history.observe(result['observe_index'],pending,result['hits']);pending=None
                n+=1
                if n%4==0:report_next=True
            for msg in s.get('new_messages',[]):
                if msg.get('record_type')=='state_resync':history.resync(msg)
                if msg.get('record_type')=='report_result':history.report(msg['issued_at_utc'],msg)
            if report_next:
                report_next=False;return dict(action='report')
            if n>=12:return None
            now=utc(s['now_utc'])
            slot=next((q for q in scenario.slots if q.start_utc<=now<q.end_utc),None)
            if slot is None:
                future=next((q for q in scenario.slots if q.start_utc>now),None)
                return dict(action='wait',until_utc=future.start_utc.isoformat()) if future else None
            night=slot.slot_id.split('-S')[0]
            end=max(q.end_utc for q in scenario.slots if q.slot_id.split('-S')[0]==night)
            duration=min(900,int((end-now).total_seconds()))
            if duration<60:return dict(action='wait',duration_seconds=60)
            action=design(scenario,now,duration,rng)
            if action is None:return dict(action='wait',duration_seconds=900)
            pending=action;actions.append(action);return action
        return actor
    out=ROOT/'small_runtime'/str(seed)
    run_scenario(scenario_path,factory,out)
    dump(out/'public_snapshots.json',snapshots)
    with (out/'observations.csv').open() as f:rows=list(csv.DictReader(f))
    observed={(int(r['observe_index']),r['target_id']):float(r['score']) for r in rows}
    for obs in history.observations:
        for t in obs['tokens']:
            if t['actual_hit']:assert observed[(obs['action_index'],t['target_id'])]==t['score_six_decimal']
    return dict(observations=n,public_hit_tokens=len(observed),public_report_results=len(history.reports),
        public_score_matches_csv_six_decimals=True,small_termination=True)

def main():
    lock=json.loads((ROOT/'PILOT_LOCK.json').read_text())
    begin=time.perf_counter();worlds=[];allrows=[];scalar_time=0.;history=PublicHistory()
    report_cases=0;rounding_bound=0.;operror=0.;hingeerror=0.;firsterror=0.;negative=0.;counts=Counter()
    for seed in lock['pilot_world_seeds']:
        t=time.perf_counter();base=bundle(seed,lock);build_seconds=time.perf_counter()-t
        scenario=load_scenario(base/'config/v4_scenario.json')
        weather=WeatherTruth(scenario.slots,[e for e in scenario.events if e.event_type=='instrument_fault'])
        rng=np.random.default_rng(seed+lock['action_seed_offset']);actions=[];row_count=0
        for j in range(lock['host_queries_per_world']):
            slot=scenario.slots[int(rng.integers(len(scenario.slots)))]
            night=slot.slot_id.split('-S')[0]
            night_end=max(q.end_utc for q in scenario.slots if q.slot_id.split('-S')[0]==night)
            duration=min(int(rng.choice(lock['durations'])),int((night_end-slot.start_utc).total_seconds()))
            if duration<60:continue
            action=design(scenario,slot.start_utc,duration,rng)
            if action is None:continue
            t=time.perf_counter();rows=labels(scenario,weather,action,slot.start_utc);scalar_time+=time.perf_counter()-t
            row_count+=len(rows);counts['assigned']+=len(action['assignments']);counts['hit']+=len(rows)
            tokens=history.observe(j,action,[dict(target_id=r['target_id'],score=r['public_score']) for r in rows])
            counts['miss']+=sum(not z['actual_hit'] for z in tokens)
            for r in rows:
                counts['zero' if r['g']==0 else 'saturated' if r['g']==1 else 'interior']+=1
                counts['band_'+PROGRAMS[r['b']]]+=1
                prob=soft_label([r['g']],[r['b']]);mu,mub=moments(prob)
                first=first_gain(prob,[r['w']],scenario.score_config)[0]
                truth=np.array([r['w']*r['g']*program_multiplier(p,PROGRAMS[r['b']],scenario.score_config) for p in PROGRAMS])
                firsterror=max(firsterror,float(np.max(abs(first-truth))))
                for best in [0.,.25*r['w'],.5*r['w'],.85*r['w'],1.1*r['w']]:
                    gain=expected_gain(prob,[r['w']],[best],scenario.score_config)[0]
                    actual=np.maximum(0.,truth-best)
                    err=gain-actual
                    negative+=int(np.any(err < -1e-12));hingeerror=max(hingeerror,float(err.max()))
                    bound=r['w']*max(scenario.score_config['program']['multipliers'].values())/(4*K)
                    assert np.max(err)<=bound+1e-12
                    operror=max(operror,float(np.max(abs(gain-actual))))
                public=r['public_score'];declared=PROGRAMS.index(action['program'])
                rounding_bound=max(rounding_bound,abs(public-truth[declared]));assert abs(public-truth[declared])<=.5e-6+1e-12
                allrows.append([seed,j,r['g'],r['b'],r['w'],public])
            actions.append(dict(start_utc=slot.start_utc.isoformat(),action=action))
        dump(base/'public_action_design.json',actions)
        # Official repaired branch label must be regenerated, never copied from old scores.
        for fault in weather.faults:
            at=fault.actual_start_utc
            action=design(scenario,at,60,rng)
            if action:
                before=labels(scenario,weather,action,at)
                reward=weather.report_fault(at,scenario.score_config)
                assert reward==scenario.score_config['reporting']['correct_reward']
                after=labels(scenario,weather,action,at)
                assert [r['b'] for r in before]==[r['b'] for r in after]
                assert all(a['g']+1e-12>=b['g'] for a,b in zip(after,before))
                report_cases+=1
                # A second report is false; it supplies a same-time healthy anchor too.
                assert not weather.repair_fault(at)
        runtime=small_runtime(base/'config/v4_scenario.json',seed)
        worlds.append(dict(seed=seed,build_seconds=build_seconds,label_rows=row_count,events=len(scenario.events),
            terrain_directions=next(b['notices'] for b in scenario.bulletins if b.get('initial')),runtime=runtime))
    np.savez_compressed(ROOT/'pilot_host_labels.npz',rows=np.asarray(allrows))
    # An explicit public loss message updates best but keeps its past score measurement.
    h=PublicHistory();action=dict(action='observe',program='DARK',duration_seconds=900,assignments={'0':'zero','1':'hit','2':'miss'})
    h.observe(0,action,[{'target_id':'zero','score':0.},{'target_id':'hit','score':.6}]);h.observe(1,action,[{'target_id':'hit','score':.4}])
    h.resync({'invalidated_window':{'action_index_start':0,'action_index_end_exclusive':1}})
    assert h.best()=={'hit':.4} and h.observations[0]['tokens'][0]['actual_hit'] and not h.observations[0]['tokens'][2]['actual_hit']
    # C/E is never reconstructed: all labels are direct official g and per-target band.
    result=dict(schema='direct-target-distribution-stage1-result-v1',worlds=worlds,counts=dict(counts),
        official_scalar_label_seconds=scalar_time,label_rows=len(allrows),first_best_exact_moment_max_error=firsterror,
        hinge_quantization_max_error=hingeerror,hinge_quantization_negative_cases=negative,
        analytic_normalized_gain_bound=1.2/(4*K),six_decimal_public_score_max_rounding_error=rounding_bound,
        official_report_repair_cases=report_cases,loss_best_vs_measurement_contract=True,
        public_miss_vs_zero_contract=True,elapsed_seconds=time.perf_counter()-begin,
        no_fit_no_old_cal_test_no_actual_truth=True)
    dump(ROOT/'PILOT_RESULT.json',result);print(json.dumps(result))

if __name__=='__main__':main()
