"""Read-only science-model audit: synthetic official scoring + public trace scan.

Never calls a planner choose, workflow.run, SSH, GPU, or reads card truth.
Replay actor inputs are public initialize, past actions and past rounded scores.
Observation factor/quality/prog_mult are used only by separate diagnostic counts.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import zipfile

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'upstream/gosim-observer-examples/runner'))
from challenge.v4_scorer import (SlotTruth, ScoreEvent, WeatherTruth,
    score_target_exposure, program_band, program_multiplier, BestLedger, lunar_quality_factor)
from challenge.tile_geometry_simulator import _normalized_airmass
from challenge.v4_fiber_map import radec_to_altaz, min_altitude_during
from research.spatial_candidates import SpatialPlanner, local_sidereal, PROGRAMS
from research.feedback_model import seasonal_quality
from research.terrain_policy import install_terrain_policy
from research.terrain_version_space import DIRECTIONS, altaz_at
from policy import Policy


def parse(s):
    if isinstance(s, datetime): return s
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def read_csv(p):
    with p.open() as f: return list(csv.DictReader(f))


def public_initial(base):
    s = json.loads((base/'config/v4_scenario.json').read_text())
    f = json.loads((base/'config/v4_fiber_config.json').read_text())
    q = json.loads((base/'config/v4_score_config.json').read_text())
    targets = read_csv(base/'public/targets.csv')
    nights = read_csv(base/'public/v4_night_calendar.csv')
    field = f['field']; side = math.isqrt(int(field['n_fibers']))
    glass = math.sqrt(float(field['fiber_area_deg2'])); pitch = glass+float(field['gap_deg'])
    sec=(parse(nights[0]['observing_end_utc'])-parse(nights[0]['observing_start_utc'])).total_seconds()
    columns=list(targets[0])
    return {'schema_version':'v4-initialize-v1','task_card':s['task_card'],
        'site':{**s['site'],'minimum_altitude_deg':s['minimum_altitude_deg']},
        'survey':{'start_utc':nights[0]['observing_start_utc'],'end_utc':nights[-1]['observing_end_utc'],
            'slot_seconds':int(round(sec/int(nights[0]['slot_count']))),
            'nights':[{**r,'slot_count':int(r['slot_count'])} for r in nights]},
        'instrument':{**field,'grid_side':side,'glass_side_deg':round(glass,6),
            'pitch_deg':round(pitch,6),'fov_side_deg':round(side*pitch,6),'exposure':f['exposure']},
        'scoring':q,'targets':{'columns':columns,'rows':[[r[k] if k in ('target_id','target_class')
            else r[k].lower()=='true' if k=='required' else float(r[k]) for k in columns] for r in targets]}}


def official_one(target, start, duration, weather, config, site, declared, events=(), altaz=None):
    if altaz is None:
        altaz=lambda t:radec_to_altaz(target['ra_deg'],target['dec_deg'],t,
            float(site['latitude_deg']),float(site['longitude_deg']))
    end=start+timedelta(seconds=duration)
    # All synthetic lunar penalties are disabled explicitly in the common config.
    band_q=weather.band_quality(start,end,config,lambda t:altaz(t)[0],lambda t:1.)
    band=program_band(band_q,config)
    mult=program_multiplier(declared,band,config)
    scored=score_target_exposure(target,list(weather.segments(start,end)),events,weather,
        duration,mult,config,start,altaz,site)
    return {'q_band':band_q,'band':band,'mult':mult,'factor':scored.factor,
        'quality':scored.quality,'score':scored.score}


def synthetic_checks():
    initial=public_initial(ROOT/'upstream/gosim-observer-examples/local-cards/L1')
    config=deepcopy(initial['scoring']); config['lunar_model']['maximum_penalty']=0.
    initial['scoring']=config
    p=SpatialPlanner(initial); start=parse(initial['survey']['start_utc'])
    site=initial['site']; duration=900
    target={'target_id':'synthetic','ra_deg':0.,'dec_deg':0.,'feature_flux':1.,'science_weight':1.}
    # a=2 before terrain. One entire-exposure terrain blockage with posterior p=.5.
    quality=1.; weather=WeatherTruth([SlotTruth('s',start,start+timedelta(seconds=3600),True,
        1.,config['q0'],1.,1.)],None)
    terrain=ScoreEvent('terrain','terrain_obstruction',start,start+timedelta(seconds=duration),
        'HORIZON_SECTOR',0.,360.,0.,90.,1.,1.,1.,1.)
    clean=official_one(target,start,duration,weather,config,site,'DARK',altaz=lambda t:(90.,10.))
    blocked=official_one(target,start,duration,weather,config,site,'DARK',(terrain,),lambda t:(90.,10.))
    safe=official_one({**target,'target_id':'safe','feature_flux':1./3},start,duration,
        weather,config,site,'DARK',altaz=lambda t:(90.,10.))
    prob=.5; frozen=float(min(1.,target['feature_flux']*duration*quality*prob/p.f0t0)*p.multipliers[0])
    expected=prob*clean['score']+(1-prob)*blocked['score']
    assert abs(clean['score']-1.2)<1e-12 and blocked['score']==0.
    assert abs(frozen-1.2)<1e-12 and abs(expected-.6)<1e-12
    # Exercise the deployed _evaluate implementation on a fixed one-fiber collision.
    two=deepcopy(initial)
    cols=two['targets']['columns']
    catalogue=[]
    for name,flux in [('uncertain',1.),('safe',1./3)]:
        r=dict(zip(cols,two['targets']['rows'][0]))
        r.update(target_id=name,feature_flux=flux,science_weight=1.,required=False)
        catalogue.append([r[k] for k in cols])
    two['targets']['rows']=catalogue
    evaluator=SpatialPlanner(two); evaluator.tmin=evaluator.tmax=900
    evaluator._classify=lambda vectors,*center:(np.zeros(len(vectors),dtype=int),
        np.ones(len(vectors),dtype=bool),np.ones(len(vectors)))
    selected=evaluator._evaluate((90.,10.),np.arange(2),np.zeros((2,3)),
        np.full(2,1e9),np.asarray([1./900,2./(3*900)]),np.zeros(2),np.zeros(2),
        np.asarray([[1.2,1.2],[1.,1.],[1.,1.]]),np.zeros(2,dtype=bool),
        np.zeros(2),np.zeros(2),np.full(2,1e9),np.zeros(2),np.ones(2),900,1.)
    assert selected[4].tolist()==[0]
    # With historical best the positive-part can reverse the sign of the bias.
    a=.8; best=.9
    under_plugin=max(0.,1.2*min(1.,a*prob)-best)
    under_expected=prob*max(0.,1.2*min(1.,a)-best)
    assert under_plugin==0. and under_expected>0.
    ledger=BestLedger(); ledger.record(0,'t',1.,1.); ledger.record(1,'t',.9,1.08)
    assert ledger.best()['t']==(.9,1.08) and ledger.max_factors()['t']==1.
    # Real public target geometry, constant synthetic weather, no lunar penalty.
    # Locate a setting where integration changes DARK to BRIGHT.
    duration=3600
    start=start+timedelta(hours=4)
    lst=local_sidereal(start,p.lon); alt,az,_,_=p._altaz(lst)
    h0=p._public_quality(start,lst,alt)
    band_example=None
    for i in np.flatnonzero((alt>40)&(alt<65)):
        t={'target_id':p.ids[i],'ra_deg':float(p.ra[i]),'dec_deg':float(p.dec[i]),
           'feature_flux':1.,'science_weight':1.}
        if min_altitude_during(t['ra_deg'],t['dec_deg'],start,start+timedelta(seconds=duration),
                {'site':site})<30.:continue
        scale=.651/float(h0[i])
        w=WeatherTruth([SlotTruth('s',start,start+timedelta(seconds=3600),True,1.,scale,1.,.95)],None)
        off=official_one(t,start,duration,w,config,site,'DARK')
        if off['band']=='BRIGHT':
            band_example={'target':t,'start':start.isoformat(),'duration':duration,'weather_scale':scale,
                'frozen_q_band':.651,'frozen_band':'DARK','frozen_score':1.2,
                'official_declared_DARK':off,
                'official_declared_BRIGHT':official_one(t,start,duration,w,config,site,'BRIGHT')}
            break
    assert band_example is not None
    return {'terrain_probability_cap':{'posterior_clear_probability':prob,'official_clear':clean,
        'official_blocked':blocked,'strategy_plug_in_score':frozen,'posterior_expected_official_score':expected,
        'safe_alternative_score':safe['score'],'official_safe_alternative':safe,
        'actual_SpatialPlanner_evaluate_selected':evaluator.ids[int(selected[4][0])],
        'actual_SpatialPlanner_evaluate_program':PROGRAMS[int(selected[3])],
        'actual_SpatialPlanner_evaluate_duration':int(selected[2]),
        'strategy_prefers':'uncertain','expectation_prefers':'safe'},
        'existing_best_undervaluation':{'unattenuated_factor':a,'clear_probability':prob,
            'historical_best':best,'plug_in_gain':under_plugin,'posterior_expected_gain':under_expected},
        'best_vs_factor_negative_control':{'best':list(ledger.best()['t']),'max_factor':ledger.max_factors()['t']},
        'deterministic_duration_program':band_example}


def posterior_factors(policy, start, duration, i, C, E):
    """Finite midpoint terrain posterior: score each surviving box before averaging.

    Uses the SAME explicit reference-prior posterior as deployed terrain model.
    Restrict to one possibly covering direction, avoiding an independence shortcut.
    Constant C/E is a shared counterfactual, not truth or a claim of calibrated weather.
    """
    p=policy.planner; model=policy.terrain_model
    end=start+timedelta(seconds=duration); cursor=start
    anchor=p.nights[policy._night(start)][0]; pieces=[]
    while cursor<end:
        slot=math.floor((cursor-anchor).total_seconds()/policy.slot_seconds)
        boundary=min(end,anchor+timedelta(seconds=(slot+1)*policy.slot_seconds))
        while cursor<boundary:
            pe=min(boundary,cursor+timedelta(seconds=120)); mid=cursor+(pe-cursor)/2
            lst=local_sidereal(mid,p.lon); aa,zz,_,_=p._altaz(lst)
            h=float(p._public_quality(mid,lst,aa)[i])
            pieces.append(((pe-cursor).total_seconds()/duration,float(aa[i]),float(zz[i]),h))
            cursor=pe
    relevant=[]
    for direction,active in model.active.items():
        ids=np.flatnonzero(active)
        if not len(ids):continue
        center=(DIRECTIONS[direction]+(model.c_lo[ids]+model.c_hi[ids])/2)%360
        width=(model.w_lo[ids]+model.w_hi[ids])/2
        height=(model.h_lo[ids]+model.h_hi[ids])/2
        clear=[]
        for _,aa,zz,_ in pieces:
            delta=np.abs((zz-center+180)%360-180)
            clear.append(~((aa<=height)&(delta<=width/2)))
        clear=np.asarray(clear)
        if not np.all(clear):relevant.append((direction,ids,clear))
    if len(relevant)!=1:return None
    direction,ids,clear=relevant[0]
    weights=model.volume[ids]/model.volume[ids].sum()
    htimes=np.asarray([a*h for a,_,_,h in pieces])
    effective_h=np.sum(htimes[:,None]*clear,axis=0)
    k=float(p.flux[i]*duration*C*E*p.q0/p.f0t0)
    factors=np.minimum(1.,k*effective_h)
    mean_factor=float(weights@factors)
    mean_q_factor=float(k*(weights@effective_h))
    plugin_integrated_factor=min(1.,mean_q_factor)
    average_h=sum(htimes)
    band_q=C*p.q0*average_h
    band=0 if band_q>=p.dark_threshold else 1 if band_q>=p.bright_threshold else 2
    return {'direction':direction,'posterior_box_count':len(ids),'weights':weights,'factors':factors,
        'expected_factor':mean_factor,'plugin_integrated_factor':plugin_integrated_factor,
        'mean_uncapped_factor':mean_q_factor,'clear_capacity':k*average_h,'band':band,'average_h':average_h}


def scan_trace(card, directory, cap=220):
    initial=public_initial(ROOT/f'practice_cards/{card}/{card}')
    policy=install_terrain_policy(Policy)(initial)
    with zipfile.ZipFile('/Users/kamico/Downloads/observer_request_exact_cache.zip') as z:
        policy.config.update(json.loads(z.read('policy_config.json')))
    p=policy.planner
    rows=read_csv(directory/'decisions.csv'); obs=read_csv(directory/'observations.csv')
    actions=[json.loads(s) for s in (directory/'actions.jsonl').read_text().splitlines()]
    observe_actions=[a for a in actions if a.get('action')=='observe']
    groups=defaultdict(list)
    for r in obs:groups[int(r['observe_index'])].append(r)
    messages=[json.loads(s) for s in (directory/'messages.jsonl').read_text().splitlines()]
    messages=sorted(enumerate(messages),key=lambda t:(parse(t[1]['issued_at_utc']),t[0]))
    report_results=[m for _,m in messages if m.get('record_type')=='report_result']
    cursor=0; bulletin=None; last_result=None; seen=0; replay_checks=[]
    examples=[]; freeze=[]; counters=Counter(); max_factor_bias=0.; max_gain_over=0.; max_gain_under=0.
    program_action_examples=[]
    gain_over_sum=0.;gain_under_sum=0.;required_examples=[]
    for row in rows:
        now=parse(row['start_utc']); new=[]
        while cursor<len(messages) and parse(messages[cursor][1]['issued_at_utc'])<=now:
            m=messages[cursor][1];new.append(m)
            if m.get('record_type')=='bulletin':bulletin=m
            cursor+=1
        snapshot={'now_utc':row['start_utc'],'last_result':last_result,'new_messages':new,
                  'latest_bulletin':bulletin,'active_requests':[]}
        policy._ingest_result(snapshot);policy._messages(snapshot)
        last_result={'action':'wait'}
        night=policy._night(now)
        if night>=0:
            seasonal,_=seasonal_quality(now.timetuple().tm_yday,p.q0)
            C,E=policy.belief_clock.prior(policy.C,policy.E,now,seasonal)
            policy.last_night=night
        if row['action']=='report':
            rr=next(m for m in report_results if parse(m['issued_at_utc'])==now)
            policy.pending={'action':{'action':'report'}}
            last_result={'action':'report','correct':rr['correct'],'repaired':rr['repaired']}
            continue
        if row['action']!='observe':continue
        index=int(row['observe_index']); action=observe_actions[index]
        assert len(action['assignments'])==int(row['assigned_count'])
        assert int(action['duration_seconds'])>=int(row['duration_seconds'])
        duration=int(row['duration_seconds']);ids=[p.index[t] for t in action['assignments'].values()]
        lst=local_sidereal(now,p.lon);alt,az,_,_=p._altaz(lst);h0=p._public_quality(now,lst,alt)
        terrain_prob=policy.terrain_model.expected_clear_fraction(alt,az)
        scale=policy._target_scale(now)
        prediction={p.ids[i]:{'alt_deg':float(alt[i]),'az_deg':float(az[i])} for i in ids}
        policy.pending={'action':action,'start':now,'prediction':prediction,
            'notices':list(policy.notices),'prior_C':C,'prior_E':E}
        hits=[{'target_id':r['target_id'],'score':float(r['score'])} for r in groups[index]]
        last_result={'action':'observe','observe_index':index,'hits':hits}
        # Actor state only to this point. Diagnostic observations never feed back factors or quality.
        seen+=1
        if seen>cap:break
        hbar=policy._geometric_H(now,duration,np.asarray(ids))/p.q0
        frozen_bands=np.where(C*p.q0*h0[ids]>=p.dark_threshold,0,
            np.where(C*p.q0*h0[ids]>=p.bright_threshold,1,2))
        integrated_bands=np.where(C*p.q0*hbar>=p.dark_threshold,0,
            np.where(C*p.q0*hbar>=p.bright_threshold,1,2))
        if np.any(frozen_bands!=integrated_bands):
            ix=np.asarray(ids)
            raw0=np.minimum(1.,p.flux[ix]*duration*h0[ix]*C*E*p.q0*scale[ix]/p.f0t0)
            rawbar=np.minimum(1.,p.flux[ix]*duration*hbar*C*E*p.q0*scale[ix]/p.f0t0)
            hour=(lst-p.ra[ix]+180)%360-180
            urgency=1+.8/np.maximum(1,p.future_nights[night,ix])+.3*np.maximum(hour,0)/np.maximum(p.hmax[ix],1)
            gain0=[];gainbar=[]
            for prog in range(3):
                m0=np.where(frozen_bands==prog,p.multipliers[prog],p.mismatch)
                mb=np.where(integrated_bands==prog,p.multipliers[prog],p.mismatch)
                gain0.append(float(np.sum(np.maximum(0.,p.weight[ix]*raw0*m0-policy.scores[ix])*urgency)))
                gainbar.append(float(np.sum(np.maximum(0.,p.weight[ix]*rawbar*mb-policy.scores[ix])*urgency)))
            oldbest=PROGRAMS[int(np.argmax(gain0))];newbest=PROGRAMS[int(np.argmax(gainbar))]
            if oldbest!=newbest:counters['fixed_assignment_program_ranking_reversals']+=1
            program_action_examples.append({'observe_index':index,'start':now.isoformat(),'duration':duration,
                'declared':action['program'],'programs':list(PROGRAMS),'frozen_weighted_science_gains':gain0,
                'integrated_weighted_science_gains':gainbar,'frozen_best_program':oldbest,
                'integrated_best_program':newbest,'note':'same assigned targets; same public prior C/E and start terrain scale; actual source urgency retained'})
        for j,i in enumerate(ids):
            counters['assigned_prefix']+=1
            if frozen_bands[j]!=integrated_bands[j]:
                counters['public_geometry_band_crossings']+=1
                freeze.append({'observe_index':index,'start':now.isoformat(),'duration':duration,'target_id':p.ids[i],
                    'frozen_band':PROGRAMS[int(frozen_bands[j])],'integrated_band':PROGRAMS[int(integrated_bands[j])],
                    'qband_start':float(C*p.q0*h0[i]),'qband_integrated':float(C*p.q0*hbar[j]),
                    'declared':action['program'],
                    'actual_reported_prog_mult':next((float(r['prog_mult']) for r in groups[index] if r['target_id']==p.ids[i]),None)})
            if 1e-6<terrain_prob[i]<1-1e-6:
                counters['uncertain_terrain_assignments']+=1
                # Skip temporary weather modifiers to isolate terrain posterior arithmetic.
                if abs(scale[i]-terrain_prob[i])>1e-9:continue
                post=posterior_factors(policy,now,duration,i,C,E)
                if post is None:continue
                counters['single_family_terrain_assignments']+=1
                prog=PROGRAMS.index(action['program'])
                mult=float(p.multipliers[prog] if prog==post['band'] else p.mismatch)
                best=float(policy.scores[i]);weight=float(p.weight[i])
                expected=float(post['weights']@np.maximum(0.,weight*mult*post['factors']-best))
                plugin=max(0.,weight*mult*post['plugin_integrated_factor']-best)
                factor_bias=post['plugin_integrated_factor']-post['expected_factor']
                gain_bias=plugin-expected
                gain_over_sum+=max(0.,gain_bias);gain_under_sum+=min(0.,gain_bias)
                if factor_bias>1e-6:counters['cap_expectation_bias_assignments']+=1
                if gain_bias>1e-6:counters['expected_gain_overvalued_assignments']+=1
                if gain_bias<-1e-6:counters['expected_gain_undervalued_assignments']+=1
                max_factor_bias=max(max_factor_bias,factor_bias)
                max_gain_over=max(max_gain_over,gain_bias);max_gain_under=min(max_gain_under,gain_bias)
                if p.required[i] and policy.factor_lower[i]<p.req_threshold:
                    robust=min(1.,post['mean_uncapped_factor']/float(policy.config['duration_safety']))
                    probability=float(post['weights']@(post['factors']>=p.req_threshold))
                    if robust>=p.req_threshold and probability<1-1e-9:
                        counters['required_mean_threshold_with_uncertain_completion']+=1
                        required_examples.append({'observe_index':index,'target_id':p.ids[i],
                            'robust_plugin_factor':robust,'posterior_probability_raw_factor_ge_threshold':probability,
                            'threshold':float(p.req_threshold)})
                if abs(gain_bias)>1e-6:
                    actual=next((r for r in groups[index] if r['target_id']==p.ids[i]),None)
                    examples.append({'observe_index':index,'start':now.isoformat(),'duration':duration,
                        'target_id':p.ids[i],'declared':action['program'],'historical_best_score':best,
                        'terrain_clear_probability_start':float(terrain_prob[i]),'direction':post['direction'],
                        'remaining_posterior_boxes':post['posterior_box_count'],'C':C,'E':E,
                        'unobstructed_capacity':post['clear_capacity'],'plugin_integrated_factor':post['plugin_integrated_factor'],
                        'posterior_expected_factor':post['expected_factor'],'plugin_gain':plugin,
                        'posterior_expected_gain':expected,'gain_bias':gain_bias,
                        'actual_reported_score':None if actual is None else float(actual['score'])})
    # Historical settlement diagnostic uses the downloaded official measurements only.
    # It is separate from reconstruction and never supplies actor factors.
    best_rows={}; maxfactor={}; hit_counts=Counter(); mults=Counter(); weights=dict(zip(p.ids,p.weight))
    for r in obs:
        if r['valid']!='true':continue
        t=r['target_id'];score=float(r['score']);f=float(r['factor'])
        maxfactor[t]=max(maxfactor.get(t,0.),f);hit_counts[t]+=1
        mults[r['prog_mult']]+=1
        if t not in best_rows or score>float(best_rows[t]['score']):best_rows[t]=r
    total_science=sum(float(r['score']) for r in best_rows.values())
    official=json.loads((directory/'score_report.json').read_text())
    assert abs(total_science-official['components']['sum_best_scores'])<.002
    zero_only=sum(float(r['score'])==0. for r in best_rows.values())
    best_hist=Counter('saturated' if float(r['factor'])>=1-1e-6 else 'threshold_to_cap' if float(r['factor'])>=.5
        else 'positive_below_threshold' if float(r['score'])>0 else 'zero_only' for r in best_rows.values())
    gap_to_best_matched=sum(max(0.,weights[t]*1.2-float(r['score'])) for t,r in best_rows.items())
    return {'card':card,'input_trace':str(directory.relative_to(ROOT)),
        'prefix_exposures_scanned':min(cap,seen),'reconstruction':'ingest past rounded hit scores; same published messages and C/E priors; no choose calls',
        'prefix_counts':dict(counters),'max_cap_factor_bias':max_factor_bias,
        'max_expected_gain_overvaluation':max_gain_over,'max_expected_gain_undervaluation':max_gain_under,
        'sum_expected_gain_overvaluation_on_prefix_assigned_targets':gain_over_sum,
        'sum_expected_gain_undervaluation_on_prefix_assigned_targets':gain_under_sum,
        'required_threshold_examples':required_examples,
        'terrain_examples':sorted(examples,key=lambda x:-abs(x['gain_bias']))[:30],
        'fixed_assignment_program_examples':program_action_examples,
        'public_geometry_band_examples':freeze[:30],
        'historical_settlement':{'official_sum_best_scores':total_science,'official_targets_observed':len(best_rows),
            'positive_score_targets':len(best_rows)-zero_only,'zero_score_only_targets':zero_only,
            'best_exposure_factor_categories':dict(best_hist),'valid_observation_program_multiplier_counts':dict(mults),
            'observed_target_gap_to_all_DARK_saturation_upper_bound':gap_to_best_matched,
            'required_missing':official['counts']['required_missing'],
            'note':'gap is an unattainable diagnostic upper bound, never a predicted policy gain'}}


def main():
    sources=['upstream/gosim-observer-examples/runner/challenge/v4_scorer.py',
        'upstream/gosim-observer-examples/runner/challenge/v4_fiber_map.py',
        'upstream/gosim-observer-examples/runner/challenge/v4_runner.py',
        'policy.py','research/spatial_candidates.py','research/feedback_model.py',
        'research/request_exact_cache.py','research/request_deadline_common.py',
        'research/terrain_policy.py','research/terrain_version_space.py']
    hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in sources}
    synthetic=synthetic_checks()
    geom_max_error=0.;geom_cases=0
    for card in ('L1','L2'):
        init=public_initial(ROOT/f'upstream/gosim-observer-examples/local-cards/{card}')
        planner=SpatialPlanner(init)
        for seconds in (0,900,7200,18000):
            moment=parse(init['survey']['start_utc'])+timedelta(seconds=seconds)
            lst=local_sidereal(moment,planner.lon);alt,_,_,_=planner._altaz(lst)
            vector=planner._public_quality(moment,lst,alt)
            ids=np.flatnonzero(alt>=30)[::37][:100]
            for i in ids:
                lunar=lunar_quality_factor(float(planner.ra[i]),float(planner.dec[i]),moment,
                    init['site'],init['scoring'])
                expected=lunar/(planner.q0*_normalized_airmass(float(alt[i]))**planner.airmass_exponent)
                geom_max_error=max(geom_max_error,abs(expected-vector[i]));geom_cases+=1
    assert geom_max_error<1e-10
    synthetic['public_geometry_pointwise_negative_control']={'cases':geom_cases,
        'max_abs_quality_difference':geom_max_error,'cards':['L1','L2']}
    (HERE/'minimal_counterexamples.json').write_text(json.dumps(synthetic,indent=2)+'\n')
    scans=[]
    for card,name in [('delta','cloud_request_cache_delta_20261003'),('alpha','cloud_request_cache_alpha_20261003')]:
        result=scan_trace(card,ROOT/'results'/name,cap=220)
        scans.append(result)
        (HERE/f'{card}_public_history_audit.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'card':card,'prefix_counts':result['prefix_counts'],
            'max_factor_bias':result['max_cap_factor_bias'],'max_gain_over':result['max_expected_gain_overvaluation'],
            'max_gain_under':result['max_expected_gain_undervaluation'],
            'historical':result['historical_settlement']}),flush=True)
    (HERE/'source_manifest.json').write_text(json.dumps({'source_sha256':hashes,
        'request_cache_zip_sha256':hashlib.sha256(Path('/Users/kamico/Downloads/observer_request_exact_cache.zip').read_bytes()).hexdigest(),
        'actor_inputs':['public scenario/fiber/scoring/targets/night-calendar files per practice card','already occurred downloaded actions',
            'already occurred rounded target scores','already delivered messages'],
        'never_read':['sealed L4 labels','L3 rescue parameters','future truth'],
        'operations':'no workflow run, no planner choose, no SSH/GPU/submit'},indent=2)+'\n')
    print(json.dumps(synthetic),flush=True)


if __name__=='__main__':main()
