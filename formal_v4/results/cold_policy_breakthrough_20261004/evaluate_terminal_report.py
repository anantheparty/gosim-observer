#!/usr/bin/env python3
"""Evaluator-only truth use for one frozen L3 terminal action, never a season run."""
import copy
import csv
import hashlib
import json
import sys
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ENGINE = ROOT/'upstream/gosim-observer-examples/runner'
sys.path.insert(0,str(ENGINE))
sys.dont_write_bytecode = True
from challenge.v4_runner import load_scenario, normalize_action, _parse_utc, _pointing_offset
from challenge.v4_fiber_map import FiberGrid, min_altitude_during, radec_to_altaz
from challenge.v4_scorer import (WeatherTruth, BestLedger, FAULT_TYPE, lunar_quality_factor,
    program_band, program_multiplier, score_target_exposure, required_penalty,
    uniformity_penalty, settle_observation_requests)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))


def prefix_signature(ledger):
    return hashlib.sha256(json.dumps([
        [e.action_index,e.target_id,e.factor,e.score,e.valid,e.invalidated_by]
        for e in ledger.entries],separators=(',',':')).encode()).hexdigest()


def score_last(scenario,weather,action,start,end):
    grid=FiberGrid.from_config(scenario.fiber_config)
    cfg=scenario.score_config
    lat=float(scenario.site['latitude_deg'])
    lon=float(scenario.site['longitude_deg'])
    offset_alt,offset_az=_pointing_offset(scenario) # evaluator only
    target_by_id={t['target_id']:t for t in scenario.targets}
    directionals=[e for e in scenario.events if e.scope_type=='HORIZON_SECTOR' and e.overlaps(start,end)]
    segments=list(weather.segments(start,end))
    duration=int((end-start).total_seconds())
    hits=[]
    for fiber,tid in action['assignments'].items():
        target=target_by_id[tid]
        if min_altitude_during(target['ra_deg'],target['dec_deg'],start,end,scenario.config)<scenario.minimum_altitude_deg:
            continue
        classified=grid.classify_target(target['ra_deg'],target['dec_deg'],start,
            action['pointing']['alt_deg'],action['pointing']['az_deg'],lat,lon,offset_alt,offset_az)
        if classified.region!='glass' or classified.fiber_id!=fiber:
            continue
        def at(moment,target=target):
            return radec_to_altaz(target['ra_deg'],target['dec_deg'],moment,lat,lon)
        band_quality=weather.band_quality(start,end,cfg,lambda m:at(m)[0],
            lambda m,target=target:lunar_quality_factor(target['ra_deg'],target['dec_deg'],m,scenario.site,cfg))
        band=program_band(band_quality,cfg)
        multiplier=program_multiplier(action['program'],band,cfg)
        scored=score_target_exposure(target,segments,directionals,weather,duration,multiplier,
                                   cfg,start,at,scenario.site)
        hits.append({'target_id':tid,'factor':scored.factor,'score':scored.score,'program_band':band,
                     'program_multiplier':multiplier})
    return hits


def settlement(scenario,ledger,now,report_settlement):
    science=sum(v[1] for v in ledger.best().values())
    factors=ledger.max_factors()
    missing,cost=required_penalty(scenario.targets,factors,scenario.score_config)
    bands,uniform=uniformity_penalty(scenario.targets,factors,scenario.score_config)
    requests=[r for r in scenario.observation_requests if r['issued_at_utc']<=now]
    statuses,reward=settle_observation_requests(requests,ledger)
    return {'total':science-cost-uniform+report_settlement+reward,
            'sum_best_scores':science,'required_penalty':-cost,'required_missing':missing,
            'uniformity_penalty':-uniform,'report_settlement':report_settlement,
            'observation_request_reward':reward,'uniformity_bands':bands,
            'observation_requests':statuses}


def main():
    begin=time.perf_counter()
    lock=json.loads((OUT/'PRE_TRUTH_LOCK.json').read_text())
    for name,value in lock['files'].items():
        assert sha(OUT/name)==value,('pre-truth lock mismatch',name)
    public=json.loads((OUT/'public_audit.json').read_text())
    fixed=next(r for r in public['cards'] if r['card']=='L3')
    assert fixed['public_only_weak_dominance_gate']
    # First evaluator truth access occurs only after every candidate hash is checked.
    scenario_path=ROOT/'upstream/gosim-observer-examples/local-cards/L3/config/v4_scenario.json'
    scenario=load_scenario(scenario_path)
    start=_parse_utc(fixed['now_utc'])
    end=_parse_utc(fixed['survey_end_utc'])
    target_by_id={t['target_id']:t for t in scenario.targets}
    original=normalize_action(fixed['final_action'],scenario,target_by_id,start)
    report=normalize_action({'action':'report'},scenario,target_by_id,start)
    assert report=={'action':'report'}
    assert start+timedelta(seconds=original['duration_seconds'])==end
    directory=ROOT/'results/policy_iteration_20261004/natural_control/L3/rank_0064/control'
    decisions=read_csv(directory/'decisions.csv')
    prior_decisions={int(r['observe_index']):r for r in decisions if r['action']=='observe'}
    rank=int(decisions[-1]['observe_index'])
    rows=read_csv(directory/'observations.csv') # evaluator exact CSV only; no teacher labels
    prefix=BestLedger()
    expected_final={r['target_id']:r for r in rows if int(r['observe_index'])==rank}
    for r in rows:
        index=int(r['observe_index'])
        if index>=rank:continue
        d=prior_decisions[index]
        prefix.record(index,r['target_id'],float(r['factor']),float(r['score']),
                      _parse_utc(d['start_utc']),_parse_utc(d['end_utc']))
        prefix.entries[-1].valid=r['valid']=='true'
        prefix.entries[-1].invalidated_by=r['invalidated_by']
    faults=[e for e in scenario.events if e.event_type==FAULT_TYPE]
    weather=WeatherTruth(scenario.slots,faults)
    weather.false_reports_since_correct=fixed['prior_false_reports_since_correct']
    # L3 has no prior reports, fixed by the public audit before truth.
    assert fixed['prior_correct_reports']==0
    before=score_last(scenario,weather,original,start,end)
    assert set(expected_final)=={h['target_id'] for h in before}
    max_final_score_error=max(abs(h['score']-float(expected_final[h['target_id']]['score'])) for h in before)
    max_final_factor_error=max(abs(h['factor']-float(expected_final[h['target_id']]['factor'])) for h in before)
    assert max_final_score_error<=0.500001e-6
    assert max_final_factor_error<=0.500001e-6
    sig_before=prefix_signature(prefix)
    score_delta=weather.report_fault(start,scenario.score_config)
    correct=weather.active_fault(start) is not None and score_delta==scenario.score_config['reporting']['correct_reward']
    assert prefix_signature(prefix)==sig_before
    after=score_last(scenario,weather,original,start,end)
    assert [h['target_id'] for h in before]==[h['target_id'] for h in after]
    assert all(a['program_band']==b['program_band'] and a['program_multiplier']==b['program_multiplier']
               for a,b in zip(before,after))
    assert all(a['score']>=b['score']-1e-12 and a['factor']>=b['factor']-1e-12
               for a,b in zip(after,before))
    ledgers=[]
    for hits in [before,after]:
        ledger=copy.deepcopy(prefix)
        for hit in hits:
            ledger.record(rank,hit['target_id'],hit['factor'],hit['score'],start,end)
        ledgers.append(ledger)
    base=settlement(scenario,ledgers[0],end,0.)
    changed=settlement(scenario,ledgers[1],end,score_delta)
    official=json.loads((directory/'score_report.json').read_text())
    prefix_rounding_gap=base['total']-official['total']
    assert abs(prefix_rounding_gap)<0.01
    assert base['required_missing']==official['counts']['required_missing']
    assert abs(base['uniformity_penalty']-official['components']['uniformity_penalty'])<1e-6
    false_weather=WeatherTruth(scenario.slots,[])
    false_weather.false_reports_since_correct=fixed['prior_false_reports_since_correct']
    free_false_delta=false_weather.report_fault(start,scenario.score_config)
    assert free_false_delta==0.
    deltas={k:changed[k]-base[k] for k in ['total','sum_best_scores','required_penalty',
               'uniformity_penalty','report_settlement','observation_request_reward']}
    assert -deltas['uniformity_penalty']<=fixed['worst_uniformity_harm_bound']+1e-12
    truth_files=[scenario_path.parent/scenario.config['products'][key]
                 for key in ['slots_csv','weather_truth_csv','events_csv','earthquake_effects_csv',
                             'observation_requests_jsonl']]
    truth_files += [scenario_path.parent/scenario.config['stress']['stress_events_csv']]
    result={'schema':'terminal-report-one-action-evaluator-v1','card':'L3',
            'pre_truth_lock':lock,'truth_access':'evaluator_only_fully_public_local_L3',
            'actor_action_uses_truth':False,'runs_full_season':False,'reads_teacher_labels':False,
            'correct':correct,'direct_report_score_delta':score_delta,'free_false_report_delta':free_false_delta,
            'now_utc_unchanged':fixed['now_utc'],'observe_rank_unchanged':rank,
            'prefix_ledger_sha256_before_after':sig_before,
            'frozen_next_action':fixed['final_action'],'next_action_mutated':False,
            'same_final_geometry_hits':True,'same_program_bands':True,'factor_and_science_non_decreasing':True,
            'baseline_full_report_total':official['total'],'baseline_reconstructed_total':base['total'],
            'rounding_gap':prefix_rounding_gap,'baseline_last_action_score_error_max':max_final_score_error,
            'baseline_last_action_factor_error_max':max_final_factor_error,
            'delta':deltas,'estimated_full_ledger_total_after_one_action_substitution':official['total']+deltas['total'],
            'lower_bound_total_delta_public':fixed['conditional_correct_total_gain_lower_bound'],
            'baseline_settlement':base,'changed_settlement':changed,
            'baseline_final_hits':before,'changed_final_hits':after,
            'evaluator_truth_inputs_sha256':{str(p.resolve().relative_to(ROOT)):sha(p) for p in truth_files},
            'official_engine_sha256':{name:sha(ENGINE/'challenge'/name) for name in ['v4_runner.py','v4_scorer.py','v4_fiber_map.py']},
            'seconds':time.perf_counter()-begin}
    (OUT/'terminal_report_evaluation.json').write_text(json.dumps(result,indent=2)+'\n')
    # Restore an already earned public ledger and rank into an isolated in-memory
    # copy of the original runner.  Only three initial-state literals change.
    # The report/observe/scoring/settlement code itself is byte-for-byte source.
    import inspect
    import challenge.v4_runner as runner
    source=inspect.getsource(runner.run_scenario)
    substitutions={'observe_index = 0':f'observe_index = {rank}',
                   'loss_triggered = False':'loss_triggered = True'}
    for old,new in substitutions.items():
        assert source.count(old)==1,old
        source=source.replace(old,new)
    terminal_scenario=replace(copy.deepcopy(scenario),survey_start=start)
    env=dict(vars(runner))
    env['load_scenario']=lambda path:copy.deepcopy(terminal_scenario)
    env['BestLedger']=lambda:copy.deepcopy(prefix)
    exec(compile(source,'<official-runner-terminal-state-restoration>','exec'),env)
    packet_results=[]
    for name,packet in [('control',[fixed['final_action']]),
                        ('terminal_report',[{'action':'report'},fixed['final_action']])]:
        seen=[]
        def factory(context,packet=packet,seen=seen):
            def choose(snapshot):
                seen.append({'now_utc':snapshot['now_utc'],
                             'observe_action_index':snapshot['observe_action_index'],
                             'running_total':snapshot['running_total'],
                             'last_result':snapshot['last_result']})
                return copy.deepcopy(packet[len(seen)-1])
            return choose
        report_out=env['run_scenario'](scenario_path,factory,OUT/'terminal_packets'/name)
        report_out.pop('organizer_only',None)
        packet_results.append({'case':name,'report':report_out,'snapshots':seen})
    control_packet,report_packet=packet_results
    assert len(control_packet['snapshots'])==1 and len(report_packet['snapshots'])==2
    assert report_packet['snapshots'][0]['now_utc']==report_packet['snapshots'][1]['now_utc']==fixed['now_utc']
    assert report_packet['snapshots'][0]['observe_action_index']==report_packet['snapshots'][1]['observe_action_index']==rank
    assert report_packet['snapshots'][1]['last_result']=={'action':'report','correct':True,'repaired':True,'score_delta':100.}
    actual_packet_delta=report_packet['report']['total']-control_packet['report']['total']
    assert abs(actual_packet_delta-deltas['total'])<1e-6
    runner_check={'schema':'official-runner-terminal-packet-check-v1',
        'runs_full_season':False,'initial_state_restoration_only':substitutions,
        'initial_survey_start':fixed['now_utc'],'initial_loss_already_triggered':True,
        'initial_ledger_sha256':sig_before,'official_runner_disk_sha256_unchanged':sha(ENGINE/'challenge/v4_runner.py'),
        'report_observe_code_mutated':False,'report_does_not_advance_time_or_observe_rank':True,
        'packet_total_delta':actual_packet_delta,'packets':packet_results}
    (OUT/'official_runner_packet_check.json').write_text(json.dumps(runner_check,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['correct','direct_report_score_delta','free_false_report_delta',
                 'delta','rounding_gap','estimated_full_ledger_total_after_one_action_substitution','seconds']},indent=2))
    print('official runner terminal packet delta',actual_packet_delta)


if __name__=='__main__':
    main()
