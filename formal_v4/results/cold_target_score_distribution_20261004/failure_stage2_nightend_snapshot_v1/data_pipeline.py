"""Fresh world-level data. Host truth stays in this builder; model NPZ inputs whitelist public fields.
Public action/time template reader deliberately discards old hit/score/factor/quality/valid/offset.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import csv,json,hashlib,sys,time,pickle,shutil,copy,math,argparse
from datetime import timedelta
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent;REPO=ROOT.parents[2]
sys.path.insert(0,str(ROOT/'official'));sys.path.insert(0,str(ROOT/'strong_original'))
import wrapper
from research.geometry import local_sidereal_deg,format_utc,shift_altaz,tangent_offsets
from research.feedback_model import seasonal_quality
from challenge import v4_weather_simulator as gen
from challenge.v4_runner import load_scenario,_pointing_offset,_data_loss_plan
from challenge.v4_scorer import WeatherTruth,score_target_exposure,program_band,lunar_quality_factor
from challenge.v4_fiber_map import FiberGrid,radec_to_altaz,min_altitude_during
from public_features import utc,clip_duration,notice_features,action_metadata,publication_state,query_features
from target_core import PublicHistory,PROGRAMS,multiplier_matrix
from physical_operator import PublicPhysics,host_factor

def dump(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def new_policy(initial):return wrapper.agent.Policy(initial)

def templates(card):
    dest=ROOT/'public_templates'/card;dest.mkdir(parents=True,exist_ok=True)
    ip=REPO/'formal_v4/results/policy_iteration_20261004'/f'{card}_initialize_public.json'
    source=REPO/'formal_v4/results/request_geometry_integration_20261004/seasons/control'/card
    initial=json.loads(ip.read_text());acts=[json.loads(s) for s in (source/'actions.jsonl').read_text().splitlines()]
    acts=[{k:x[k] for k in ('action','pointing','duration_seconds','program','assignments')} for x in acts if x['action']=='observe']
    with (source/'decisions.csv').open() as f:
        # Access only action/start_utc/end_utc/duration_seconds columns, never validity/hit_count.
        times=[dict(start_utc=r['start_utc'],end_utc=r['end_utc'],actual_duration_seconds=int(r['duration_seconds'])) for r in csv.DictReader(f) if r['action']=='observe']
    assert len(acts)==len(times)
    records=[dict(**t,action=a) for a,t in zip(acts,times)]
    dump(dest/'initializer.json',initial);dump(dest/'actions_whitelisted.json',records)
    dump(dest/'receipt.json',dict(source_initializer_sha256=sha(ip),source_actions_sha256=sha(source/'actions.jsonl'),source_decisions_sha256=sha(source/'decisions.csv'),old_columns_consumed=['action','start_utc','end_utc','duration_seconds'],no_old_score_factor_quality_valid_hit_count_offset=True))
    return initial,records

def prepare_cache(card):
    path=ROOT/'public_templates'/card/'cache.pkl'
    if path.exists():
        with path.open('rb') as f:return pickle.load(f)
    initial,records=templates(card);t=time.perf_counter();pol=new_policy(initial);p=pol.planner;physics=PublicPhysics(initial,p)
    targetmap={r[0]:dict(zip(initial['targets']['columns'],r)) for r in initial['targets']['rows']}
    states=np.unique(np.rint(np.linspace(8,len(records)-1,128)).astype(int));assert len(states)==128
    history=[];q=np.zeros((128,320,51),np.float32);idx=np.full((128,320),-1,np.int32);fiber=np.full((128,320),-1,np.int8);duration=np.ones((128,10),np.float32);mask=np.zeros((128,320),bool)
    futures=[];rawrows=unique_rows=0;max_q_error=0
    for ai,r in enumerate(records):
        action=r['action'];start=utc(r['start_utc']);d=clip_duration(initial,start,action['duration_seconds']);ids=list(action['assignments'].values());indices=[p.index[z] for z in ids]
        mesh=physics.mesh(start,d,indices);query=physics.query(mesh)
        base=np.zeros((16,24),np.float32)
        for j,(tid,qi) in enumerate(zip(ids,query)):
            token=base[j];token[4]=d/p.tmax;token[5]=math.log(max(.001,targetmap[tid]['feature_flux']))/4;token[6:9]=np.eye(3)[PROGRAMS.index(action['program'])]
            parts=qi[:40].reshape(5,8);keep=parts[:,7]>0
            token[9:12]=[sum(parts[:,0]*parts[:,7]),parts[keep,1].min(),parts[keep,2].max()]
            _,amid,zmid=physics.at([indices[j]],start+timedelta(seconds=d/2));token[12:18]=[qi[42],amid[0]/90,qi[46],qi[43],math.sin(zmid[0]*math.pi/180),math.cos(zmid[0]*math.pi/180)]
            off=tangent_offsets(float(qi[42])*90,math.degrees(math.atan2(qi[44],qi[45]))%360,action['pointing']['alt_deg'],action['pointing']['az_deg']) or (0,0)
            token[18:20]=np.asarray(off)/p.fov;token[21]=min(1e6,.5/targetmap[tid]['science_weight']) if targetmap[tid]['science_weight']>0 else 0;token[23]=float(targetmap[tid]['science_weight']>0)
        history.append(dict(mesh=mesh,base=base,indices=indices,ids=ids))
        if ai not in states:continue
        si=int(np.where(states==ai)[0][0]);_,alt,az=physics.at(np.arange(p.n),start);_,_,_,vectors=p._altaz(local_sidereal_deg(start,p.lon))
        center=action['pointing'];altc,azc=center['alt_deg'],center['az_deg'];other=shift_altaz(altc,azc,.16*p.pitch,-.16*p.pitch);centers=[(altc,azc),other]
        pools=[]
        for c in centers:
            fs,valid,margin=p._classify(vectors,*c);valid&=alt>=p.min_alt+.04;pool=[]
            for f in range(p.nfib):
                members=np.flatnonzero(valid&(fs==f));rank=np.argsort(-(p.weight[members]*np.minimum(p.flux[members],4)))[:2]
                pool.extend((int(i),f) for i in members[rank])
            pools.append(pool)
        ds=[]
        for requested in [p.tmin,300,900,1800,p.tmax]:
            d=clip_duration(initial,start,requested)
            if d>=p.tmin and d not in ds:ds.append(d)
        union=sorted({i for pool in pools for i,f in pool});umeshes={d:physics.mesh(start,d,union) for d in ds};uf={d:physics.query(m) for d,m in umeshes.items()};umap={i:j for j,i in enumerate(union)}
        cases=[]
        for field,pool in enumerate(pools):
            for di,d in enumerate(ds):
                c=field*5+di;duration[si,c]=d;rows=[]
                for i,f in pool:
                    uj=umap[i]
                    if uf[d][uj,43]*90<p.min_alt:continue
                    j=c*32+len(rows);idx[si,j]=i;fiber[si,j]=f;mask[si,j]=True;q[si,j]=uf[d][uj];rows.append((j,uj,i,f));rawrows+=1
                cases.append(dict(candidate=c,field=field,center=centers[field],duration=d,rows=rows))
        unique_rows+=sum(len(union) for d in ds)
        futures.append(dict(ai=ai,start=start,night=umeshes[ds[0]]['night']['night_date'],meshes=umeshes,union=union,cases=cases))
        # Official scalar public feature parity, independently at deterministic sample rows.
        for c in cases[:1]:
            for j,uj,i,f in c['rows'][:2]:
                a=dict(action='observe',duration_seconds=c['duration'],program='DARK',pointing=dict(alt_deg=c['center'][0],az_deg=c['center'][1]),assignments={str(f):p.ids[i]})
                err=np.max(abs(q[si,j]-query_features(initial,targetmap[p.ids[i]],a,start)));max_q_error=max(max_q_error,float(err));assert err<2e-6
    cache=dict(card=card,initial=initial,records=records,states=states,history=history,futures=futures,q=q,idx=idx,fiber=fiber,duration=duration,mask=mask)
    with path.open('wb') as f:pickle.dump(cache,f)
    np.savez_compressed(path.with_suffix('.npz'),q=q,idx=idx,fiber=fiber,duration=duration,mask=mask)
    dump(path.with_name('cache_cost.json'),dict(card=card,public_geometry_seconds=time.perf_counter()-t,query_target_rows=rawrows,unique_physical_target_duration_rows=unique_rows,pure_geometry_mesh_calls=physics.calls,geometry_cache_hits=physics.hits,max_official_public_query_difference=max_q_error,cache_bytes=path.stat().st_size))
    return cache

def fresh_bundle(seed,cache):
    base=ROOT/'stage2_worlds'/str(seed)
    if (base/'config/v4_scenario.json').exists():return base,0.0
    begin=time.perf_counter();initial=cache['initial'];ref=ROOT/'official/challenge/reference/v4';cfg=json.loads((ref/'v4_weather_config.json').read_text());cfg.update(seed=seed,seed_derivation='sha256-v1');cfg['stress_tests']['enabled']=True
    cfg['survey'].update(start_date=initial['survey']['nights'][0]['night_date'],end_date=initial['survey']['nights'][-1]['night_date'])
    rng=np.random.default_rng(seed+20000000)
    for key,high in [('rainy',2),('cloudy',3),('smoggy',2),('cold_wave',2),('tornado',1)]:cfg['weather_events']['conditions'][key]['count']=int(rng.integers(high+1))
    for key,high in [('rocket_launch',2),('earthquake',3),('instrument_fault',3)]:cfg[key]['count']=int(rng.integers(high+1))
    for sub in ['generator','public','truth','config']:(base/sub).mkdir(parents=True,exist_ok=True)
    dump(base/'generator/weather.json',cfg);gen.generate(base/'generator/weather.json',base/'generator/output')
    for p in (base/'generator/output').iterdir():
        if p.name in ['v4_night_calendar.csv','v4_bulletins.jsonl','v4_forecasts.jsonl']:shutil.copyfile(p,base/'public'/p.name)
        elif p.name in ['v4_slots.csv','v4_weather_truth.csv','v4_events.csv','v4_earthquake_effects.csv','v4_stress_events.csv']:shutil.copyfile(p,base/'truth'/p.name)
    with (base/'public/targets.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(initial['targets']['columns']);w.writerows(initial['targets']['rows'])
    with (base/'public/footprint.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['component_id','vertex_index','ra_deg','dec_deg'])
        for component in initial['footprint']:
            for j,(ra,dec) in enumerate(component['vertices']):w.writerow([component['component_id'],j,ra,dec])
    (base/'truth/v4_observation_requests.jsonl').write_text('')
    scenario=json.loads((ROOT/'v4_scenario.json').read_text());scenario['name']=f'fresh-direct-target-{seed}';scenario['stress']=dict(enabled=True,stress_events_csv='../truth/v4_stress_events.csv');scenario['task_card']=dict(card_id=str(seed),scenario_slug=scenario['name'],phase='new-world-learning')
    dump(base/'config/v4_scenario.json',scenario)
    for n in ['v4_score_config.json','v4_fiber_config.json']:shutil.copyfile(ROOT/n,base/'config'/n)
    return base,time.perf_counter()-begin

def snapshot(initial,seen,now,result=None):
    state=publication_state(initial,seen,now,next(n['night_date'] for n in initial['survey']['nights'] if utc(n['observing_start_utc'])<=now<utc(n['observing_end_utc'])))
    return dict(now_utc=format_utc(now),last_result=result,new_messages=seen,latest_bulletin=state['bulletin'],latest_forecast=state['forecast'],active_requests=[])

def point_distribution(pol,now,indices,d):
    p=pol.planner;seasonalC,_=seasonal_quality(now.timetuple().tm_yday,p.q0);C,E=pol.belief_clock.prior(pol.C,pol.E,now,seasonalC)
    alt,az,_,_=p._altaz(local_sidereal_deg(now,p.lon));H=p._public_quality(now,local_sidereal_deg(now,p.lon),alt);scale=pol._target_scale(now)
    k=p.flux[indices]*H[indices]*max(.005,C*E*p.q0)*scale[indices]/p.f0t0
    band=np.where(H[indices]*max(.005,C*p.q0)>=p.dark_threshold,0,np.where(H[indices]*max(.005,C*p.q0)>=p.bright_threshold,1,2))
    return np.minimum(1,d*k),band

def build(seed,split,verify=False):
    card='L1' if seed%2==0 else 'L2';cache=prepare_cache(card);begin=time.perf_counter();base,generation_seconds=fresh_bundle(seed,cache);scenario=load_scenario(base/'config/v4_scenario.json');initial=cache['initial'];pol=new_policy(initial);p=pol.planner;physics=PublicPhysics(initial,p);weather=WeatherTruth(scenario.slots,[e for e in scenario.events if e.event_type=='instrument_fault']);grid=FiberGrid.from_config(scenario.fiber_config);da,dz=_pointing_offset(scenario);public=PublicHistory();seen=[];pubs=sorted(scenario.bulletins+scenario.forecasts,key=lambda x:utc(x['issued_at_utc']));pi=0;loss=_data_loss_plan(scenario);lost=False;mult=multiplier_matrix(scenario.score_config)
    S=128;Q=320
    data={k:np.zeros(shape,np.float32) for k,shape in [('ht',(S,8,16,24)),('hn',(S,8,129)),('hm',(S,8,16)),('cn',(S,129)),('cm',(S,16)),('F',(S,Q)),('effective',(S,Q)),('best',(S,Q)),('truebest',(S,Q)),('point',(S,Q,3))]};data['b']=np.zeros((S,Q),np.int8);data['mask']=cache['mask'];data['q']=cache['q'];data['fiber']=cache['fiber'];data['duration']=cache['duration'];data['idx']=cache['idx'];data['weight']=np.where(cache['idx']>=0,p.weight[np.maximum(cache['idx'],0)],0).astype(np.float32)
    obsmeta=[];truthobs=[];historynotices=[];historystarts=[];labels_checked=0;max_factor_error=0;hit_count=miss_count=zeros=sat=report_count=loss_count=0;label_seconds=0
    future_by_ai={f['ai']:(si,f) for si,f in enumerate(cache['futures'])}
    def publish(now):
        nonlocal pi,lost,loss_count
        new=[]
        while pi<len(pubs) and utc(pubs[pi]['issued_at_utc'])<=now:new.append(pubs[pi]);seen.append(pubs[pi]);pi+=1
        if loss and not lost and now>=loss.trigger_utc:
            lost=True;first=math.floor(loss.window_start_fraction*len(public.observations));last=math.floor(loss.window_end_fraction*len(public.observations));msg=dict(record_type='state_resync',issued_at_utc=format_utc(now),invalidated_window=dict(action_index_start=first,action_index_end_exclusive=last));public.resync(msg)
            best=public.best();msg['best_scores']=[dict(target_id=t,best_score=v) for t,v in best.items()];new.append(msg);seen.append(msg);loss_count+=1
            for o in truthobs:
                if first<=o['action_index']<last:o['valid']=False
        s=snapshot(initial,seen,now);s['new_messages']=new;pol._messages(s)
    for ai,record in enumerate(cache['records']):
        now=utc(record['start_utc']);publish(now)
        # Fixed public report schedule, gated only by current public free allowance.
        if ai>0 and ai%64==0 and weather.false_reports_since_correct<scenario.score_config['reporting']['false_report_free_allowance']:
            correct=weather.active_fault(now) is not None and weather.active_fault(now).event_id not in weather.fault_repairs;delta=weather.report_fault(now,scenario.score_config);msg=dict(record_type='report_result',issued_at_utc=format_utc(now),correct=correct,repaired=correct,score_delta=delta);seen.append(msg);public.report(msg['issued_at_utc'],msg);pol.pending=dict(action={'action':'report'});s=snapshot(initial,seen,now,dict(action='report',**{k:msg[k] for k in ('correct','repaired','score_delta')}));s['new_messages']=[msg];pol._ingest_result(s);pol._messages(s);report_count+=1
        if ai in future_by_ai:
            si,future=future_by_ai[ai];qn=future['night'];data['cn'][si]=notice_features(initial,seen,now,qn);data['cm'][si]=action_metadata(initial,None,[],now,now,seen,qn)
            for h,o in enumerate(public.observations[-8:]):
                oi=o['action_index'];base_tokens=cache['history'][oi]['base'].copy();tokens=o['tokens'];start=historystarts[oi];d=clip_duration(initial,start,o['action']['duration_seconds'])
                for j,tok in enumerate(tokens):
                    tid=tok['target_id'];i=p.index[tid];w=p.weight[i]
                    if w<=0:base_tokens[j]=0;continue
                    base_tokens[j,0]=float(tok['score_six_decimal'] or 0)/w;base_tokens[j,1]=tok['actual_hit'];base_tokens[j,2]=not tok['actual_hit'];base_tokens[j,3]=tok['actual_hit'] and tok['score_six_decimal']==0
                    alt,az=radec_to_altaz(p.ra[i],p.dec[i],start,p.lat,p.lon);off=tangent_offsets(alt,az,o['action']['pointing']['alt_deg'],o['action']['pointing']['az_deg']) or (0,0);base_tokens[j,18:20]=np.asarray(off)/p.fov
                    base_tokens[j,20]=min(1,(now-start-timedelta(seconds=d)).total_seconds()/(7*86400));base_tokens[j,22]=o['valid']
                data['ht'][si,h]=base_tokens;data['hn'][si,h]=historynotices[oi];data['hm'][si,h]=action_metadata(initial,o['action'],tokens,start,now,obsmeta[oi],cache['history'][oi]['mesh']['night']['night_date'])
            best=public.best();truebest={}
            for o in truthobs:
                if o['valid']:
                    for tid,value in o['scores'].items():truebest[tid]=max(truebest.get(tid,0),value)
            offset=pol.calibrator.estimate[:2] if pol.calibrator else (0,0);t=time.perf_counter()
            for d,mesh in future['meshes'].items():
                F,b=host_factor(mesh,physics,scenario,weather)
                if verify:
                    for uj in range(min(3,len(F))):
                        i=future['union'][uj];target=scenario.targets[i];end=now+timedelta(seconds=d);events=[e for e in scenario.events if e.scope_type=='HORIZON_SECTOR' and e.overlaps(now,end)];pos=lambda t:radec_to_altaz(target['ra_deg'],target['dec_deg'],t,p.lat,p.lon)
                        sc=score_target_exposure(target,list(weather.segments(now,end)),events,weather,d,1,scenario.score_config,now,pos,scenario.site);qb=weather.band_quality(now,end,scenario.score_config,lambda t:pos(t)[0],lambda t:lunar_quality_factor(target['ra_deg'],target['dec_deg'],t,scenario.site,scenario.score_config));bb=PROGRAMS.index(program_band(qb,scenario.score_config));err=abs(sc.factor-F[uj]);max_factor_error=max(max_factor_error,err);assert err<1e-9 and bb==b[uj];labels_checked+=1
                for c in future['cases']:
                    if c['duration']!=d:continue
                    cmd=dict(alt_deg=max(0,min(90,c['center'][0]-offset[0])),az_deg=(c['center'][1]-offset[1])%360)
                    rows=c['rows'];indices=np.asarray([i for j,uj,i,f in rows],int);pf,pb=point_distribution(pol,now,indices,d)
                    for k,(j,uj,i,f) in enumerate(rows):
                        tid=p.ids[i];cl=grid.classify_target(p.ra[i],p.dec[i],now,cmd['alt_deg'],cmd['az_deg'],p.lat,p.lon,da,dz);hit=cl.region=='glass' and cl.fiber_id==f
                        data['F'][si,j]=F[uj];data['b'][si,j]=b[uj];data['effective'][si,j]=F[uj] if hit else 0;data['best'][si,j]=best.get(tid,0);data['truebest'][si,j]=truebest.get(tid,0);data['point'][si,j]=np.maximum(0,p.weight[i]*pf[k]*mult[:,pb[k]]-data['best'][si,j])
            label_seconds+=time.perf_counter()-t
        # New-world historical score with then-current repairs. Never recalculate after later repair.
        action=copy.deepcopy(record['action']);offset=pol.calibrator.estimate[:2] if pol.calibrator else (0,0);action['pointing']['alt_deg']=max(0,min(90,action['pointing']['alt_deg']-offset[0]));action['pointing']['az_deg']=(action['pointing']['az_deg']-offset[1])%360
        h=cache['history'][ai];F,b=host_factor(h['mesh'],physics,scenario,weather);d=h['mesh']['duration'];hits=[];truescores={}
        for k,(f,tid) in enumerate(action['assignments'].items()):
            i=p.index[tid];cl=grid.classify_target(p.ra[i],p.dec[i],now,action['pointing']['alt_deg'],action['pointing']['az_deg'],p.lat,p.lon,da,dz);hit=cl.region=='glass' and cl.fiber_id==int(f) and min_altitude_during(p.ra[i],p.dec[i],now,now+timedelta(seconds=d),scenario.config)>=scenario.minimum_altitude_deg
            if hit:
                score=p.weight[i]*F[k]*mult[PROGRAMS.index(action['program']),b[k]];hits.append(dict(target_id=tid,score=round(score,6)));truescores[tid]=score;hit_count+=1;zeros+=int(F[k]==0);sat+=int(F[k]==1)
            else:miss_count+=1
        public.observe(ai,action,hits);truthobs.append(dict(action_index=ai,valid=True,scores=truescores));obsmeta.append(copy.deepcopy(seen));historystarts.append(now);historynotices.append(notice_features(initial,seen,now,h['mesh']['night']['night_date']))
        pred={p.ids[i]:dict(alt_deg=float(h['base'][j,12]*90),az_deg=math.degrees(math.atan2(h['base'][j,16],h['base'][j,17]))%360) for j,i in enumerate(h['indices'])}
        pol.pending=dict(action=action,start=now,notices=list(pol.notices),prediction=pred,prior_C=pol.C,prior_E=pol.E)
        s=snapshot(initial,seen,now+timedelta(seconds=d),dict(action='observe',observe_index=ai,hits=hits));s['new_messages']=[];pol._ingest_result(s)
    out=ROOT/'datasets'/split;out.mkdir(parents=True,exist_ok=True);npz=out/f'{seed}.npz';np.savez_compressed(npz,**data)
    receipt=dict(seed=seed,card=card,split=split,states=S,valid_future_rows=int(data['mask'].sum()),past_observations=len(public.observations),past_actual_hits=hit_count,past_misses=miss_count,past_zero_hits=zeros,past_saturated_hits=sat,reports=report_count,loss_resyncs=loss_count,fresh_generation_seconds=generation_seconds,future_label_seconds=label_seconds,total_world_seconds=time.perf_counter()-begin,npz_bytes=npz.stat().st_size,npz_sha256=sha(npz),official_scalar_labels_checked=labels_checked,max_official_factor_difference=max_factor_error,actor_inputs=['ht','hn','hm','cn','cm','q'],host_only_arrays=['F','b','effective','truebest'],public_validity_cutoff='resync processed chronologically, never final run valid columns',past_repair_measurements_frozen=True,no_old_factor_quality_offsets_or_test=True)
    dump(out/f'{seed}.json',receipt);print(json.dumps(receipt),flush=True);return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--split',choices=['mechanical','train','cal','val','test'],required=True);parser.add_argument('--seed',type=int);args=parser.parse_args();limits={'mechanical':(940911,940914),'train':(961000,961095),'cal':(962000,962015),'val':(963000,963023),'test':(964000,964023)}
    if args.split=='test' and not (ROOT/'SELECTED_MODEL_LOCK.json').exists():raise RuntimeError('sealed new test unavailable before selected model/source/calibration lock')
    lo,hi=limits[args.split]
    for seed in ([args.seed] if args.seed is not None else range(lo,hi+1)):
        if not lo<=seed<=hi:raise ValueError('seed outside frozen split')
        if (ROOT/'datasets'/args.split/f'{seed}.npz').exists():raise RuntimeError('dataset exists: no silent regenerate/relabel')
        build(seed,args.split,verify=args.split=='mechanical')
