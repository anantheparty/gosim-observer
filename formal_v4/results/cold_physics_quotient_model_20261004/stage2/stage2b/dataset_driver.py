"""Frozen 2B fresh dataset driver derived from proven 2A. No test generation."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import sys
sys.dont_write_bytecode=True
import copy,csv,hashlib,json,math,resource,shutil,time,traceback
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent.parent
OWN=Path(__file__).resolve().parent
OUTPUT=Path(os.environ.get("QUOTIENT_OUTPUT","/output"))
ROLE=os.environ["QUOTIENT_SPLIT"]
if ROLE not in ("train","cal","val"):raise ValueError("test generation forbidden")
sys.path[:0]=[str(ROOT),str(ROOT/'official'),str(ROOT/'point_source')]
import sparse_entry
from challenge import v4_weather_simulator as gen
from challenge.v4_runner import load_scenario,run_scenario,_pointing_offset,normalize_action
from challenge.v4_workflow import V4Workflow
from challenge.v4_scorer import (WeatherTruth,BestLedger,score_target_exposure,
    program_band,program_multiplier,lunar_quality_factor)
from challenge.v4_fiber_map import FiberGrid,radec_to_altaz,min_altitude_during
from research.geometry import format_utc,local_sidereal_deg,shift_altaz
from research.feedback_model import seasonal_quality
from public_core import PROGRAMS,PublicHistory,quotient_intervals
from public_features import (utc,clip_duration,notice_features,action_metadata,
    history_target_features,publication_state)
from physical_operator import PublicPhysics,host_integrals
from model import encode

def json_default(value):
    if isinstance(value,np.generic):return value.item()
    raise TypeError(type(value).__name__)
def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False,default=json_default)+'\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def verify_freeze():
    lock=json.loads((ROOT/'SOURCE_FREEZE.json').read_text())
    for name,value in lock['files'].items():
        if sha(ROOT/name)!=value:raise AssertionError(('frozen source changed',name))
    b=json.loads((OWN/'SOURCE_FREEZE.json').read_text())
    assert b['parent_source_freeze_sha256']==sha(ROOT/'SOURCE_FREEZE.json')
    for name,value in b['files'].items():
        if sha(OWN/name)!=value:raise AssertionError(('2B frozen source changed',name))
    return sha(OWN/'SOURCE_FREEZE.json')

def bundle(index,lock):
    begin=time.perf_counter();seed=lock['splits'][ROLE][index];card=['L1','L2'][index%2]
    initial=json.loads((ROOT/'public_initializers'/f'{card}.json').read_text())
    base=OUTPUT/'worlds'/f'{ROLE}_{index}'
    if base.exists():raise RuntimeError('refuse regenerate existing world '+str(base))
    ref=ROOT/'official/challenge/reference/v4'
    cfg=json.loads((ref/'v4_weather_config.json').read_text());cfg.update(seed=seed,seed_derivation='sha256-v1')
    cfg['stress_tests']['enabled']=True
    cfg['site']={k:initial['site'][k] for k in ('name','latitude_deg','longitude_deg','utc_offset_hours')}
    cfg['survey'].update(start_date=initial['survey']['nights'][0]['night_date'],
        end_date=(utc(initial['survey']['nights'][-1]['night_date']+'T00:00:00Z')+timedelta(days=1)).date().isoformat(),
        slot_seconds=initial['survey']['slot_seconds'])
    design_seed=int.from_bytes(hashlib.sha256(f'physics-quotient-public-sampling/v1/{ROLE}/{index}'.encode()).digest()[:8],'big')
    prior_seed=int.from_bytes(hashlib.sha256(f'physics-quotient-weather-prior/v1/{ROLE}/{index}'.encode()).digest()[:8],'big')
    rng=np.random.default_rng(prior_seed)
    for kind,high in lock['weather_event_count_max'].items():
        cfg['weather_events']['conditions'][kind]['count']=int(rng.integers(high+1))
    for kind,high in lock['other_event_count_max'].items():cfg[kind]['count']=int(rng.integers(high+1))
    for sub in ['generator','public','truth','config']:(base/sub).mkdir(parents=True,exist_ok=True)
    dump(base/'generator/weather.json',cfg);gen.generate(base/'generator/weather.json',base/'generator/output')
    for p in (base/'generator/output').iterdir():
        if p.name in ['v4_night_calendar.csv','v4_bulletins.jsonl','v4_forecasts.jsonl']:shutil.copyfile(p,base/'public'/p.name)
        elif p.name in ['v4_slots.csv','v4_weather_truth.csv','v4_events.csv','v4_earthquake_effects.csv','v4_stress_events.csv']:shutil.copyfile(p,base/'truth'/p.name)
    with (base/'public/targets.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(initial['targets']['columns']);writer.writerows(initial['targets']['rows'])
    with (base/'public/footprint.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['component_id','vertex_index','ra_deg','dec_deg'])
        for component in initial['footprint']:
            for j,(ra,dec) in enumerate(component['vertices']):writer.writerow([component['component_id'],j,ra,dec])
    (base/'truth/v4_observation_requests.jsonl').write_text('')
    scenario=dict(schema_version='v4-scenario-v1',name=f'physics-quotient-{ROLE}-{index}',
        site=cfg['site'],minimum_altitude_deg=initial['site']['minimum_altitude_deg'],
        fiber_config='v4_fiber_config.json',score_config='v4_score_config.json',
        products=dict(targets_csv='../public/targets.csv',footprint_csv='../public/footprint.csv',
            night_calendar_csv='../public/v4_night_calendar.csv',slots_csv='../truth/v4_slots.csv',
            weather_truth_csv='../truth/v4_weather_truth.csv',events_csv='../truth/v4_events.csv',
            earthquake_effects_csv='../truth/v4_earthquake_effects.csv',bulletins_jsonl='../public/v4_bulletins.jsonl',
            forecasts_jsonl='../public/v4_forecasts.jsonl',observation_requests_jsonl='../truth/v4_observation_requests.jsonl'),
        stress=dict(enabled=True,stress_events_csv='../truth/v4_stress_events.csv'),
        task_card=dict(card_id=f'fresh-physics-quotient-{ROLE}-{index}',phase='stage2b-independent',scenario_slug=f'physics-quotient-{ROLE}-{index}'))
    exposure=initial['instrument']['exposure']
    fiber=dict(schema_version='v4-fiber-v1',field=dict(n_fibers=initial['instrument']['n_fibers'],
        fiber_area_deg2=initial['instrument']['fiber_area_deg2'],gap_deg=initial['instrument']['gap_deg']),
        exposure=dict(exposure))
    # Preserve public instrument schema/constraints from the official template.
    template=json.loads((ref/'v4_fiber_config.json').read_text());template['field'].update(fiber['field']);template['exposure'].update(exposure)
    dump(base/'config/v4_fiber_config.json',template);dump(base/'config/v4_score_config.json',initial['scoring']);dump(base/'config/v4_scenario.json',scenario)
    init=V4Workflow(base).initialize_payload(900)
    assert init['targets']==initial['targets'] and init['survey']['nights']==initial['survey']['nights']
    dump(base/'public_initializer.json',init)
    return base,init,card,design_seed,time.perf_counter()-begin

def point_distribution(pol,now,indices):
    p=pol.planner;seasonal,_=seasonal_quality(now.timetuple().tm_yday,p.q0)
    C,E=pol.belief_clock.prior(pol.C,pol.E,now,seasonal)
    alt,_,_,_=p._altaz(local_sidereal_deg(now,p.lon));h=p._public_quality(now,local_sidereal_deg(now,p.lon),alt)
    k=p.flux[indices]*h[indices]*max(.005,C*E*p.q0)*pol._target_scale(now)[indices]/p.f0t0
    band=np.where(h[indices]*max(.005,C*p.q0)>=p.dark_threshold,0,np.where(h[indices]*max(.005,C*p.q0)>=p.bright_threshold,1,2))
    return k,band

def build(index):
    freeze_sha=verify_freeze();lock=json.loads((ROOT/'SAMPLING_LOCK.json').read_text());begin=time.perf_counter()
    base,initial,card,design_seed,generation= bundle(index,lock)
    scenario=load_scenario(base/'config/v4_scenario.json');pol=sparse_entry.wrapper.agent.Policy(initial);p=pol.planner
    physics=PublicPhysics(initial,p);weather=WeatherTruth(scenario.slots,[e for e in scenario.events if e.event_type=='instrument_fault'])
    grid=FiberGrid.from_config(scenario.fiber_config);offset=_pointing_offset(scenario);trueledger=BestLedger();history=PublicHistory()
    rng=np.random.default_rng(design_seed);targetmap={t['target_id']:t for t in scenario.targets};seen=[];seen_history=[]
    nights=initial['survey']['nights'];ni=np.rint(np.linspace(0,len(nights)-1,32)).astype(int)
    sensor_ds=lock['history_durations'];blocks=[]
    for j,k in enumerate(ni):
        n=nights[k];a,b=utc(n['observing_start_utc']),utc(n['observing_end_utc'])
        query=a+(b-a)*lock['query_night_phase_cycle'][j%3]+timedelta(seconds=lock['query_phase_seconds_cycle'][j%3])
        start=max(a,query-timedelta(seconds=sum(sensor_ds)))
        blocks.append(dict(start=start,night=n,history_count=0,query_done=False))
    state_features=[];rows=[];cases=[];point_actions=[];point_original_host=[];checks=Counter();timings=Counter()
    maxerrors=Counter();pending_host=None;blocki=0;last_report=None;point_nonobserve=Counter();scope_examples=[]
    chronological_messages=[];scalar_receipts=[];past_receipts=[]

    def historical_action(now,d):
        _,alt,az=physics.at(np.arange(p.n),now)
        visible=np.flatnonzero(alt>=p.min_alt+.5)
        if not len(visible):return dict(action='wait',duration_seconds=d)
        anchor=int(rng.choice(visible));center=(float(min(88,alt[anchor])),float(az[anchor]))
        end=now+timedelta(seconds=clip_duration(initial,now,d));pairs={}
        for i in visible:
            c=grid.classify_target(p.ra[i],p.dec[i],now,*center,p.lat,p.lon)
            if c.region!='glass':continue
            if min_altitude_during(p.ra[i],p.dec[i],now,end,{'site':initial['site']})<p.min_alt:continue
            prev=pairs.get(int(c.fiber_id))
            if prev is None or p.weight[i]>p.weight[prev]:pairs[int(c.fiber_id)]=int(i)
        return dict(action='observe',pointing=dict(alt_deg=center[0],az_deg=center[1]),
            assignments={str(f):p.ids[i] for f,i in pairs.items()},duration_seconds=d,
            program=PROGRAMS[int(rng.integers(3))])

    def set_sensor_pending(action,now):
        seasonal,_=seasonal_quality(now.timetuple().tm_yday,p.q0);C,E=pol.belief_clock.prior(pol.C,pol.E,now,seasonal)
        idx=[p.index[t] for t in action['assignments'].values()];_,alt,az=physics.at(idx,now)
        pol.pending=dict(action=action,start=now,notices=list(pol.notices),prior_C=C,prior_E=E,
            prediction={p.ids[i]:dict(alt_deg=float(alt[j]),az_deg=float(az[j])) for j,i in enumerate(idx)})

    def ingest_public(snapshot):
        nonlocal pending_host,last_report
        now=utc(snapshot['now_utc']);result=snapshot.get('last_result') or {}
        for msg in snapshot.get('new_messages',[]):
            seen.append(copy.deepcopy(msg));chronological_messages.append(copy.deepcopy(msg))
            if msg.get('record_type')=='state_resync':
                history.resync(msg);w=msg['invalidated_window'];trueledger.invalidate_window(w['action_index_start'],w['action_index_end_exclusive'],msg['trigger_event_id']);checks['resyncs']+=1
        if result.get('action')=='report' and last_report!=now:
            # Host mirror follows the official executed repair. Actor only gets
            # this public result; no hidden fault/efficiency is supplied to pol.
            host_delta=weather.report_fault(now,initial['scoring']);assert abs(host_delta-result['score_delta'])<1e-9
            msg=dict(record_type='report_result',issued_at_utc=format_utc(now),correct=result['correct'],repaired=result['repaired'],score_delta=result['score_delta'])
            seen.append(msg);history.reports.append(msg);last_report=now;checks['reports']+=1
        if result.get('action')=='observe' and pending_host is not None:
            t=time.perf_counter();action,start=pending_host;d=clip_duration(initial,start,action['duration_seconds'])
            tokens=result.get('hits',[]);history.observe(result['observe_index'],action,tokens,start)
            ids=list(action['assignments'].values());idx=[p.index[tid] for tid in ids]
            integrals=host_integrals(physics.mesh(start,d,idx),physics,scenario,weather)
            actual={h['target_id']:h['score'] for h in tokens};private=[]
            for j,(f,tid) in enumerate(action['assignments'].items()):
                i=p.index[tid];c=grid.classify_target(p.ra[i],p.dec[i],start,action['pointing']['alt_deg'],action['pointing']['az_deg'],p.lat,p.lon,*offset)
                hit=c.region=='glass' and c.fiber_id==int(f) and min_altitude_during(p.ra[i],p.dec[i],start,start+timedelta(seconds=d),scenario.config)>=p.min_alt
                assert hit==(tid in actual);checks['past_hit_checks']+=1
                m=program_multiplier(action['program'],PROGRAMS[int(integrals['b'][j])],initial['scoring']);score=p.weight[i]*integrals['F'][j]*m
                if hit:
                    assert round(float(score),6)==actual[tid];trueledger.record(result['observe_index'],tid,float(integrals['F'][j]),float(score),start,start+timedelta(seconds=d))
                    features,interval=quotient_intervals(actual[tid],True,p.weight[i],p.flux[i],d,integrals['Hbar'][j],action['program'],initial['scoring'])
                    q=interval[int(integrals['b'][j])];assert q['possible'] and q['lower']<=integrals['R'][j]+1e-12 and (q['upper'] is None or integrals['R'][j]<=q['upper']+1e-12)
                    checks['past_interval_contains_true_R']+=1
                private.append(dict(target_id=tid,hit=hit,physical_R=float(integrals['R'][j]),band=int(integrals['b'][j]),score=float(score) if hit else None))
            past_receipts.append(dict(start_utc=format_utc(start),duration=d,action=action,public_result=result,host_private=private))
            seen_history.append(copy.deepcopy(seen));pending_host=None;timings['past_label_seconds']+=time.perf_counter()-t

    def history_features(now):
        ht=np.zeros((8,16,36),np.float32);hn=np.zeros((8,129),np.float32);hm=np.zeros((8,16),np.float32)
        for oi,o in enumerate(history.observations[-8:]):
            start=o['start'];action=o['action'];d=clip_duration(initial,start,action['duration_seconds']);qn=next(n['night_date'] for n in nights if utc(n['observing_start_utc'])<=start<utc(n['observing_end_utc']))
            original_index=history.observations.index(o);seen_then=seen_history[original_index]
            hn[oi]=notice_features(initial,seen_then,start,qn);hm[oi]=action_metadata(initial,action,o['tokens'],start,now,seen_then,qn)
            for ti,tok in enumerate(o['tokens']):
                target=targetmap[tok['target_id']];basefeatures=history_target_features(initial,target,action,start,tok,now,o['valid'])
                hbar=float(physics.mesh(start,d,[p.index[tok['target_id']]])['seconds']@physics.mesh(start,d,[p.index[tok['target_id']]])['H'][:,0]/d)
                extra,_=quotient_intervals(tok['score_six_decimal'],tok['actual_hit'],target['science_weight'],target['feature_flux'],d,hbar,action['program'],initial['scoring'])
                ht[oi,ti]=np.r_[basefeatures,extra.ravel()]
        qn=next(n['night_date'] for n in nights if utc(n['observing_start_utc'])<=now<utc(n['observing_end_utc']))
        return dict(ht=ht,hn=hn,hm=hm,cn=notice_features(initial,seen,now,qn),cm=action_metadata(initial,None,[],now,now,seen,qn))

    def build_cases(now,original,state):
        t=time.perf_counter();d0=clip_duration(initial,now,original['duration_seconds']);assert d0>0
        estimate=pol.calibrator.estimate[:2] if pol.calibrator else (0.,0.)
        center0=(original['pointing']['alt_deg'],original['pointing']['az_deg'])
        # Public second field; no next-action or future label is read.
        center1=shift_altaz(center0[0],center0[1],.25*p.pitch,-.25*p.pitch)
        centers=[center0,center1];public_best=history.best();tb=trueledger.best();newrows=[];newcases=[]
        allidx=np.arange(p.n);_,alt,az=physics.at(allidx,now)
        for field,command in enumerate(centers):
            actual_guess=(command[0]+estimate[0],(command[1]+estimate[1])%360)
            pool=[]
            for i in np.flatnonzero(alt>=p.min_alt):
                c=grid.classify_target(p.ra[i],p.dec[i],now,*actual_guess,p.lat,p.lon)
                if c.region=='glass':pool.append((int(i),int(c.fiber_id)))
            mandatory=[(p.index[tid],int(f)) for f,tid in original['assignments'].items()] if field==0 else []
            mandatory_ids={pair[0] for pair in mandatory}
            pool=list(dict.fromkeys(mandatory+[pair for pair in pool if pair[0] not in mandatory_ids]))
            cap=lock['candidate_targets_per_field']
            if len(pool)>cap:
                spare=[pair for pair in pool if pair not in mandatory]
                spare.sort(key=lambda pair:(-p.weight[pair[0]]*min(p.flux[pair[0]],4),pair[0],pair[1]))
                pool=mandatory+spare[:max(0,cap-len(mandatory))];checks['public_pool_capped']+=1
            assert all(pair in pool for pair in mandatory)
            ds=list(dict.fromkeys(clip_duration(initial,now,x) for x in [original['duration_seconds'],300,900,1800,3600]))
            for d in ds:
                if d<=0:continue
                admitted=[]
                for i,f in pool:
                    minalt=min_altitude_during(p.ra[i],p.dec[i],now,now+timedelta(seconds=d),{'site':initial['site']})
                    if minalt>=p.min_alt or (field==0 and d==d0 and (i,f) in mandatory):admitted.append((i,f,minalt>=p.min_alt))
                if not admitted:continue
                idx=[i for i,f,valid in admitted];mesh=physics.mesh(now,d,idx);q=physics.query(mesh)[:,np.r_[0:40,41:51]]
                intervals=host_integrals(mesh,physics,scenario,weather);checks['future_slots_'+str(intervals['slots'])]+=len(idx)
                checks['future_with_directional_events']+=len(idx) if intervals['hidden_directional_events'] else 0
                k,bpoint=point_distribution(pol,now,np.asarray(idx,int));caseid=len(cases)+len(newcases);indices=[]
                for j,(i,f,valid) in enumerate(admitted):
                    cls=grid.classify_target(p.ra[i],p.dec[i],now,*command,p.lat,p.lon,*offset)
                    actualhit=valid and cls.region=='glass' and cls.fiber_id==f
                    R=float(intervals['R'][j]);B=public_best.get(p.ids[i],0.);T=tb.get(p.ids[i],(0.,0.))[1]
                    a=p.flux[i]*d*intervals['Hbar'][j]/p.f0t0;physicalF=min(a*R,1.)
                    assert abs(physicalF-intervals['F'][j])<1e-10
                    checks['future_rows']+=1;checks['future_zero_R']+=R==0;checks['future_saturated_F']+=physicalF==1.;checks['future_nominal_altitude_invalid']+=not valid;checks['future_actual_misses']+=not actualhit
                    maxerrors['factorization']=max(maxerrors['factorization'],abs(physicalF-intervals['F'][j]))
                    # Actual scalar samples include each original mandatory target,
                    # then deterministic two extra rows per candidate.
                    if False:  # no repeated scalar proof; 2A already verified current operator
                        st=time.perf_counter();target=targetmap[p.ids[i]];end=now+timedelta(seconds=d);events=[e for e in scenario.events if e.scope_type=='HORIZON_SECTOR' and e.overlaps(now,end)]
                        pos=lambda moment:radec_to_altaz(p.ra[i],p.dec[i],moment,p.lat,p.lon)
                        scalar=score_target_exposure(target,list(weather.segments(now,end)),events,weather,d,1.,initial['scoring'],now,pos,initial['site'])
                        qb=weather.band_quality(now,end,initial['scoring'],lambda moment:pos(moment)[0],lambda moment:lunar_quality_factor(p.ra[i],p.dec[i],moment,initial['site'],initial['scoring']))
                        errors=[abs(scalar.quality-intervals['Q'][j]),abs(scalar.quality/intervals['Hbar'][j]-R),abs(scalar.factor-physicalF),abs(qb-intervals['band_quality'][j])]
                        assert max(errors)<1e-9 and PROGRAMS[int(intervals['b'][j])]==program_band(qb,initial['scoring'])
                        maxerrors['official_scalar']=max(maxerrors['official_scalar'],max(errors));checks['official_scalar']+=1;timings['scalar_check_seconds']+=time.perf_counter()-st
                    rid=len(rows)+len(newrows);indices.append(rid)
                    newrows.append(dict(q=q[j],state=state,case=caseid,idx=i,fiber=f,R=R,b=int(intervals['b'][j]),F=physicalF,
                        actual_hit=actualhit,altitude_valid=valid,weight=float(p.weight[i]),flux=float(p.flux[i]),scale=float(a),best=float(B),truebest=float(T),
                        point_factor=float(min(d*k[j],1.)),point_band=int(bpoint[j]),Hbar=float(intervals['Hbar'][j])))
                newcases.append(dict(state=state,field=field,pointing=dict(alt_deg=float(command[0]),az_deg=float(command[1])),duration=d,rows=indices,
                    original_point_case=field==0 and d==d0,original_assignments=original['assignments'] if field==0 and d==d0 else None,
                    original_program=original['program'] if field==0 and d==d0 else None))
        timing=time.perf_counter()-t;timings['future_query_H_labels_cases_seconds']+=timing
        assert sum(c['original_point_case'] for c in newcases)==1
        rows.extend(newrows);cases.extend(newcases)
        originalcase=next(c for c in newcases if c['original_point_case']);mandatory_map={(r['idx'],r['fiber']):r for r in (rows[x] for x in originalcase['rows'])}
        realized=0.
        for f,tid in original['assignments'].items():
            r=mandatory_map[(p.index[tid],int(f))];m=program_multiplier(original['program'],PROGRAMS[r['b']],initial['scoring'])
            realized+=max(r['weight']*r['F']*m-r['truebest'],0.) if r['actual_hit'] else 0.
        point_original_host.append(dict(state=state,realized_science_rate=realized/d0,all_original_pairs_preserved=True,actual_duration=d0))
        checks['original_point_pairs_retained']+=len(original['assignments'])

    def factory(_ignored_host_context):
        def actor(snapshot):
            nonlocal blocki,pending_host
            ingest_public(snapshot);now=utc(snapshot['now_utc'])
            if blocki>=len(blocks):return None
            block=blocks[blocki]
            if now<block['start']:
                pol._ingest_result(snapshot);pol._messages(snapshot);pol.pending=None
                return dict(action='wait',until_utc=format_utc(block['start']))
            if block['history_count']<len(sensor_ds):
                pol._ingest_result(snapshot);pol._messages(snapshot);d=sensor_ds[block['history_count']];block['history_count']+=1
                action=historical_action(now,d)
                if action['action']=='observe':set_sensor_pending(action,now);pending_host=(copy.deepcopy(action),now)
                return action
            # Full frozen public selector is called exactly once per state; report,
            # wait or REQ behavior is retained, not converted to science wins.
            t=time.perf_counter();original=pol.decide(snapshot);timings['full_point_selector_seconds']+=time.perf_counter()-t
            state=blocki;point_actions.append(dict(state=state,start_utc=snapshot['now_utc'],action=copy.deepcopy(original)))
            t=time.perf_counter();features=history_features(now);timings['public_history_features_seconds']+=time.perf_counter()-t
            state_features.append(features)
            if original['action']=='observe':build_cases(now,original,state);pending_host=(copy.deepcopy(original),now)
            else:point_nonobserve[original['action']]+=1
            blocki+=1
            return original
        return actor

    run_begin=time.perf_counter();report=run_scenario(base/'config/v4_scenario.json',factory,base/'short_official_run');timings['short_official_runner_seconds']=time.perf_counter()-run_begin
    assert len(point_actions)==32 and len(state_features)==32
    # Pure public arrays are reconstructed by encoder; all private labels separate.
    data={key:np.stack([s[key] for s in state_features]) for key in ['ht','hn','hm','cn','cm']}
    data['q']=np.stack([r['q'] for r in rows]) if rows else np.empty((0,50),np.float32)
    for key in ['state','case','idx','fiber','b']:data[key]=np.asarray([r[key] for r in rows],np.int32)
    for key in ['R','F','weight','flux','scale','best','truebest','point_factor','Hbar']:data[key]=np.asarray([r[key] for r in rows],np.float64)
    data['point_band']=np.asarray([r['point_band'] for r in rows],np.int8)
    for key in ['actual_hit','altitude_valid']:data[key]=np.asarray([r[key] for r in rows],bool)
    for state in range(32):
        ii=np.flatnonzero(data['state']==state)
        if len(ii):assert encode(data,state,ii[:2]).shape==(min(2,len(ii)),5963)
    # Public evidence causality/support checks from fresh complete publications.
    terrain_public=set(n['direction'] for m in seen if m.get('initial') for n in m.get('notices',[]) if n['event_kind']=='terrain_obstruction')
    terrain_host=set(gen.event_direction(e) for e in scenario.events if e.event_type=='terrain_obstruction')
    assert terrain_public==terrain_host;checks['initial_terrain_exact_direction_support']=1
    assert all(utc(m['issued_at_utc'])<=scenario.survey_end for m in seen if 'issued_at_utc' in m)
    with (base/'short_official_run/observations.csv').open() as f:official=list(csv.DictReader(f))
    for o in official:
        # History dictionary includes every returned score including zero.
        match=next(x for x in past_receipts if x['public_result']['observe_index']==int(o['observe_index']))
        s=next(h['score'] for h in match['public_result']['hits'] if h['target_id']==o['target_id']);assert float(o['score'])==s
        checks['public_csv_score_checks']+=1
    t=time.perf_counter();npz=OUTPUT/'datasets'/ROLE/f'{index}.npz';npz.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(npz,**data)
    dump(OUTPUT/'datasets'/ROLE/f'{index}_cases.json',cases);dump(OUTPUT/'datasets'/ROLE/f'{index}_point_actions.json',point_actions);dump(OUTPUT/'datasets'/ROLE/f'{index}_point_host.json',point_original_host)
    dump(OUTPUT/'datasets'/ROLE/f'{index}_history_judge.json',past_receipts);timings['write_seconds']=time.perf_counter()-t
    runtime=time.perf_counter()-begin;peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
    budget_pass=runtime<=lock['pilot_max_worker_seconds'] and peak<=lock['pilot_max_worker_bytes']
    verify_freeze()
    receipt=dict(status='PASS_REAL_PILOT' if budget_pass else 'FAIL_PREDECLARED_COST',split=ROLE,world_index=index,seed=lock['splits'][ROLE][index],public_catalog=card,
        source_freeze_sha256=freeze_sha,world_generation_seconds=generation,full_worker_seconds=runtime,peak_process_rss_bytes=peak,
        npz_sha256=sha(npz),npz_bytes=npz.stat().st_size,states=32,point_nonobserve_states=dict(point_nonobserve),
        future_rows=len(rows),candidate_cases=len(cases),checks=dict(checks),maximum_errors=dict(maxerrors),timing_seconds=dict(timings),
        initial_terrain_public=sorted(terrain_public),source_selector_full_output_retained=True,
        actor_input_arrays=['ht','hn','hm','cn','cm','q'],no_future_flux_in_query=True,
        label_arrays=['R','b','F','actual_hit','truebest','point_factor','point_band'],
        prototype_scope='current candidate marginal, no joint future paths; fresh official short execution; original full point non-science control retained',
        future_point_offset_labels_host_only=True,public_mesh_does_not_include_hidden_event_boundaries=True,
        official_short_termination=report.get('termination'),budget_pass=budget_pass,
        no_fit_no_formal_test_no_900season=True)
    dump(OUTPUT/'datasets'/ROLE/f'{index}_receipt.json',receipt)
    print(json.dumps(receipt,allow_nan=False,default=json_default),flush=True)
    if not budget_pass:raise RuntimeError('predeclared pilot cost failed; do not launch later worlds')
    return receipt

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--index',type=int,required=True,choices=range({'train':96,'cal':16,'val':24}[ROLE]));args=parser.parse_args()
    try:build(args.index)
    except Exception:
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');path=OUTPUT/'failures'/f'{ROLE}_{args.index}_{stamp}.txt';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(traceback.format_exc());raise
if __name__=='__main__':main()
