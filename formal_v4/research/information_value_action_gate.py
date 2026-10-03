#!/usr/bin/env python3
"""Fixed public terrain-information action gate; no season/remote jobs.

Historical evaluator replay is restricted to recovering the original public
prefix. Candidate generation receives only public snapshots and past metadata.
Hidden evaluator geometry/terrain is loaded for candidate checks only after
candidate JSONs and hashes have been written.
"""
from __future__ import annotations
import argparse, copy, csv, hashlib, io, json, math, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path
sys.dont_write_bytecode = True
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ.setdefault(name, '1')
BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'results/information_value_action_gate_20261004'
FROZEN=BASE/'runs/geometry_native_20261003/release'
UP=BASE/'upstream/gosim-observer-examples'
sys.path.insert(0,str(FROZEN)); sys.path.insert(1,str(UP/'runner'))
import numpy as np
import policy
from research.candidate_geometry_sweep import CandidateGeometryPlanner
from research.spatial_candidates import SpatialPlanner, PROGRAMS, parse_utc, local_sidereal
from challenge.v4_fiber_map import FiberGrid, min_altitude_during, radec_to_altaz, altaz_to_radec
from challenge.v4_scorer import lunar_quality_factor
from challenge.tile_geometry_simulator import _normalized_airmass
policy.SpatialPlanner=CandidateGeometryPlanner
FIXED={'L4':4,'L3':255}
DEG=math.pi/180
RESULTS={}

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical(o): return json.dumps(o, sort_keys=True, separators=(',',':'))
def jsha(o): return hashlib.sha256(canonical(o).encode()).hexdigest()
def dump(name,o):
    OUT.mkdir(parents=True,exist_ok=True)
    p=OUT/name; p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(o,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    return sha(p)
def snap_hash(s): return jsha({k:v for k,v in s.items() if k!='wallclock'})
def csvrows(p):
    with Path(p).open(newline='') as f:return list(csv.DictReader(f))
def public_initial(card):
    """Derive initialize exactly from public products, no scenario loader."""
    root=UP/'local-cards'/card
    cfg=json.loads((root/'config/v4_scenario.json').read_text())
    sc=json.loads((root/'config/v4_score_config.json').read_text())
    fc=json.loads((root/'config/v4_fiber_config.json').read_text())
    grid=FiberGrid.from_config(fc)
    nights=[{**{k:r[k] for k in ('night_id','night_date','observing_start_utc','observing_end_utc')},
             'slot_count':int(r['slot_count'])} for r in csvrows(root/'public/v4_night_calendar.csv')]
    cols=['target_id','ra_deg','dec_deg','target_class','feature_flux','science_weight','required']
    rows=[]
    for t in csvrows(root/'public/targets.csv'):
        rows.append([t['target_id'],float(t['ra_deg']),float(t['dec_deg']),t['target_class'],
                     float(t['feature_flux']),float(t['science_weight']),t['required'].lower()=='true'])
    fp={}
    for r in sorted(csvrows(root/'public/footprint.csv'),key=lambda r:(r['component_id'],int(r['vertex_index']))):
        fp.setdefault(r['component_id'],[]).append([float(r['ra_deg']),float(r['dec_deg'])])
    return {'schema_version':'v4-initialize-v1','task_card':cfg['task_card'],
      'site':{**cfg['site'],'sun_altitude_limit_deg':cfg['site'].get('sun_altitude_limit_deg',-18.),
              'minimum_altitude_deg':float(cfg['minimum_altitude_deg'])},
      'survey':{'start_utc':nights[0]['observing_start_utc'],'end_utc':nights[-1]['observing_end_utc'],
                'slot_seconds':900,'nights':nights},
      'instrument':{'n_fibers':grid.n_fibers,'grid_side':grid.n_side,'fiber_area_deg2':grid.fiber_area_deg2,
          'gap_deg':grid.gap_deg,'glass_side_deg':round(grid.fiber_side_deg,6),'pitch_deg':round(grid.pitch_deg,6),
          'fov_side_deg':round(grid.fov_side_deg,6),'exposure':fc['exposure'],
          'layout':'row-major, fiber 0 bottom-left; rows along +alt, columns along +az at exposure start; gnomonic plane centred on the actual pointing'},
      'scoring':sc,'footprint':[{'component_id':k,'vertices':v} for k,v in sorted(fp.items())],
      'targets':{'columns':cols,'rows':rows},
      'limits':{'global_wallclock_seconds':900.,'max_consecutive_reports':sc['reporting']['max_consecutive_reports'],
                'response_max_bytes':524288,'decision_timeout':'global only (no per-decision timeout)'}}

def read_prefix(card):
    """Streaming cutoff: only prior rows enter actor; cut action is gate-only."""
    path=BASE/f'results/policy_iteration_20261004/natural_control/{card}/rank_0064/control/public_prefix.jsonl'
    rows=[]; heldout=None
    with path.open() as f:
        for line in f:
            r=json.loads(line)
            if int(r['rank'])>=FIXED[card]:heldout=r;break
            rows.append(r)
    assert heldout and int(heldout['rank'])==FIXED[card]
    dump(f'{card}/past_trace.json',rows)
    # Heldout target action is never a candidate generator argument.
    return rows,heldout,{'trace_path':str(path),'trace_sha256':sha(path),
        'past_count':len(rows),'past_max_rank':max(int(r['rank']) for r in rows),
        'heldout_snapshot_sha256':heldout['snapshot_sha256']}

def restore(card):
    initial=public_initial(card); rows,heldout,provenance=read_prefix(card)
    p=policy.Policy(initial); assert p.remote is None
    original=p.planner.choose; capture={}; public_history=[]; step=0
    def choose(snapshot,scores,factors,env,requests):
        nonlocal capture
        if int(snapshot['observe_action_index'])<FIXED[card]:
            r=rows[step]
            assert r['snapshot_sha256']==snap_hash(snapshot),('past snapshot',card,step)
            p.planner.last_prediction=copy.deepcopy(r['prediction'])
            p.planner.terrain_directions=set(r['planner_terrain'])
            p.planner.stats=copy.deepcopy(r['planner_stats'])
            return copy.deepcopy(r['planner_action'])
        assert not capture
        assert snap_hash(snapshot)==heldout['snapshot_sha256'],('cut snapshot',card)
        found=[]; pools=[]; original_eval=SpatialPlanner._evaluate
        def recording(self,center,pool,*frame):
            c=original_eval(self,center,pool,*frame)
            if self is p.planner and c is not None:
                found.append(c); pools.append(np.asarray(pool,dtype=int).copy())
            return c
        SpatialPlanner._evaluate=recording
        try:a=original(snapshot,scores,factors,env,requests)
        finally:SpatialPlanner._evaluate=original_eval
        # Exact original action gate occurs before any posterior model/selection.
        identical=a==heldout['action']
        capture={'snapshot':copy.deepcopy(snapshot),'env':copy.deepcopy(env),
          'scores':np.array(scores,copy=True),'factors':np.array(factors,copy=True),
          'C':float(p.C),'E':float(p.E),'base':copy.deepcopy(a),'found':found,'pools':pools,
          'native_action_exact':identical,'native_stats':copy.deepcopy(p.planner.stats),
          'public_calibrator_estimate':list(p.calibrator.estimate) if p.calibrator else None,
          'planner':p.planner,'policy':p,'history':copy.deepcopy(public_history),
          'initial':initial,'provenance':provenance}
        assert identical,('natural cut action gate',card,a,heldout['action'])
        return a
    p.planner.choose=choose
    def ingest(snapshot):
        nonlocal step
        snapshot={'schema_version':'v4-decision-snapshot-v1',**snapshot}
        snapshot.setdefault('wallclock',{'elapsed_seconds':0.,'remaining_seconds':900.})
        if step<len(rows):assert snap_hash(snapshot)==rows[step]['snapshot_sha256'],('all past snapshot',card,step)
        action=p.decide(snapshot)
        if step<len(rows):assert action==rows[step]['action'],('past action',card,step)
        public_history.append({'snapshot':copy.deepcopy(snapshot),'action':copy.deepcopy(action)})
        step+=1;return action
    if card=='L4':
        old=json.loads((BASE/'results/geometry_native_20261003/trace/L4/public_prefix.json').read_text())
        cap=json.loads((BASE/'results/policy_iteration_20261004/natural_control/L4/rank_0064/control/public_capture/capture.json').read_text())
        assert initial==old['initial'], 'public initialization shape'
        for i in range(len(rows)+1):
            s=copy.deepcopy(old['snapshots'][i]); h=cap['public_history'][i]
            # These four historical public fields restore natural hit order.
            for k in ('now_utc','observe_action_index','last_result','new_messages'):s[k]=copy.deepcopy(h[k])
            ingest(s)
        mode='existing public snapshots; canonical natural hits insertion order'
    else:
        # Original-action/feedback evaluator gate only; stops at cut immediately.
        from challenge.v4_runner import run_scenario,AgentTermination,TERMINATION_AGENT_FINISHED
        def callback(snapshot):
            a=ingest(snapshot)
            if capture:raise AgentTermination(TERMINATION_AGENT_FINISHED,'fixed public prefix captured; no cut action executed')
            return a
        run_scenario(UP/f'local-cards/{card}/config/v4_scenario.json',lambda _:callback,OUT/f'{card}/prefix_evaluator')
        mode='official historical feedback replay; exactly 273 past actor steps; immediate cut stop'
    assert capture
    public_state={k:capture[k] for k in ('snapshot','C','E','base','native_action_exact','native_stats','public_calibrator_estimate','provenance')}
    public_state.update(prefix_gate=True,prefix_steps=len(rows),native_evaluation_count=len(capture['found']),
                        restoration_mode=mode,actor_truth_access=False)
    dump(f'{card}/public_state.json',public_state)
    dump(f'{card}/public_history.json',capture['history'])
    np.savez_compressed(OUT/f'{card}/public_ledger.npz',scores=capture['scores'],factor_lower=capture['factors'])
    return capture

def public_constraints(c):
    """All constraints come from snapshots at/before cut and past own actions."""
    p=c['planner']; initial=c['initial']; sc=initial['scoring']; site=initial['site']
    history=c['history']+[{'snapshot':c['snapshot'],'action':None}]
    pos=[];zero=[];stats={'eligible_exposures':0,'mixed_exposures':0}
    multipliers=[sc['program']['mismatch_multiplier'],*sc['program']['multipliers'].values()]
    mmin,mmax=min(multipliers),max(multipliers)
    for previous,current in zip(history,history[1:]):
        a=previous['action']; s0=previous['snapshot']; s1=current['snapshot']; r=s1.get('last_result') or {}
        if not a or a.get('action')!='observe' or r.get('action')!='observe':continue
        start,end=parse_utc(s0['now_utc']),parse_utc(s1['now_utc'])
        duration=min(int(a['duration_seconds']),int((end-start).total_seconds()))
        if not 0<duration<=120:continue
        night=next(((x,y) for x,y in p.nights if x<=start<y),None)
        if not night:continue
        slot=night[0]+timedelta(seconds=900*math.floor((start-night[0]).total_seconds()/900))
        bulletin=s0.get('latest_bulletin') or {}
        if end>min(slot+timedelta(seconds=900),night[1]) or parse_utc(bulletin['issued_at_utc'])!=slot:continue
        if any(n['event_kind']!='terrain_obstruction' for n in bulletin.get('notices',[])):continue
        mid=start+timedelta(seconds=duration/2);stats['eligible_exposures']+=1
        positive=[h for h in r['hits'] if h['score']>0];zs=[h for h in r['hits'] if h['score']==0]
        if positive and zs:stats['mixed_exposures']+=1
        def k(h):
            i=p.index[h['target_id']]
            alt,az=radec_to_altaz(p.ra[i],p.dec[i],mid,p.lat,p.lon)
            g=lunar_quality_factor(p.ra[i],p.dec[i],mid,site,sc)/_normalized_airmass(alt)**p.airmass_exponent
            return p.weight[i]*p.flux[i]*g,alt,az
        for h in positive:
            _,alt,az=k(h);pos.append({'target_id':h['target_id'],'alt':alt,'az':az,'rank':r['observe_index']})
        for h in zs:
            kz,alt,az=k(h);wz=p.weight[p.index[h['target_id']]]
            lb=max((mmin*min(wz,(pa['score']-.5e-6)/mmax*kz/k(pa)[0]) for pa in positive if k(pa)[0]>0),default=0.)
            if lb>.5e-6:zero.append({'target_id':h['target_id'],'alt':alt,'az':az,'rank':r['observe_index'],'lower':lb})
    return {'positive':pos,'zero':zero,'stats':stats,'max_public_rank':max((r['snapshot']['observe_action_index'] for r in c['history']),default=-1)}

def supported_worlds(c,constraints):
    """Two canonical height endpoints; no terrain truth or fitted score target.

    Fixed compass centre is the public E label centre 90 degrees. Width is the
    smallest sector containing all certified zero points. Height endpoints are
    derived from the largest blocked altitude and the smallest positive altitude
    inside that sector. This is a declared one-sector conditional model.
    """
    directions=sorted(c['policy'].terrain)
    if directions!=['E'] or not constraints['zero']:return None,'no canonical single-E zero support'
    z=constraints['zero'];positive=constraints['positive'];center=90.
    radius=max(abs((r['az']-center+180)%360-180) for r in z)+1e-7
    low=max(r['alt'] for r in z)+1e-7
    inside=[r['alt'] for r in positive if abs((r['az']-center+180)%360-180)<=radius]
    high=min(inside,default=90.)-1e-7
    if high<=low:return None,'fixed canonical sector contradicts public positive constraints'
    worlds=[{'world':0,'p':.5,'center':center,'radius':radius,'height':low},
            {'world':1,'p':.5,'center':center,'radius':radius,'height':high}]
    for w in worlds:
        def covered(r):return abs((r['az']-w['center']+180)%360-180)<=w['radius'] and 0<=r['alt']<=w['height']
        assert all(covered(r) for r in z) and not any(covered(r) for r in positive)
    return worlds,None

def field_library(c):
    """Subset of fields already evaluated once by unchanged native parent."""
    p=c['planner'];env=c['env'];now=parse_utc(c['snapshot']['now_utc']);seen=set();fields=[]
    # Preserve parent utility order. No field refinement, seed, or pool expansion.
    order=sorted(range(len(c['found'])),key=lambda i:-c['found'][i][0])
    for i in order:
        value,center,duration,prog,chosen,fibers=c['found'][i]
        key=tuple(round(float(x),7) for x in center)
        if key in seen:continue
        seen.add(key)
        ra,dec=altaz_to_radec(*center,now,p.lat,p.lon)
        fields.append({'parent_order':len(fields),'native_rate':float(value),'native_duration':int(duration),
                       'center':tuple(map(float,center)),'eq_center':(ra,dec),'pool':c['pools'][i].copy(),
                       'program':int(prog),'chosen':np.asarray(chosen,dtype=int),'fibers':np.asarray(fibers,dtype=int)})
    return fields

class MicroModel:
    def __init__(self,c,worlds):
        self.c=c;self.p=c['planner'];self.policy=c['policy'];self.worlds=worlds
        self.now=parse_utc(c['snapshot']['now_utc']);self.s0=c['scores'];self.f0=c['factors'];self.cache={}
        self.night=next((n for n in self.p.nights if n[0]<=self.now<n[1]),None)
        self.slot_start=self.night[0]+timedelta(seconds=900*math.floor((self.now-self.night[0]).total_seconds()/900))
        self.H=int((min(self.slot_start+timedelta(seconds=900),self.night[1])-self.now).total_seconds())
        self.env=c['env'];self.safety=max(1.,float(self.env.get('duration_safety',1.06)))
        self.base_total=self.terminal(self.s0,self.f0)
        self.jain_gradient=np.asarray(self.p.frame[10]).copy()
    def terminal(self,s,f):
        p=self.p;complete=f>=p.uniform_threshold
        bc=np.bincount(p.ra_bands,weights=complete,minlength=len(p.band_sizes))
        ratios=np.divide(bc,p.band_sizes,out=np.zeros_like(bc),where=p.band_sizes>0)
        squares=float(ratios@ratios);j=float(ratios.sum()**2/(p.nonempty_bands*squares)) if squares else 0.
        return float(s.sum()-p.req_penalty*np.count_nonzero(p.required&(f<p.req_threshold))-p.uniform_weight*(1-j))
    def arrays(self,offset,duration):
        key=(int(offset),int(duration))
        if key in self.cache:return self.cache[key]
        p=self.p;start=self.now+timedelta(seconds=offset);end=start+timedelta(seconds=duration)
        total=np.zeros((2,p.n));band=np.zeros(p.n);cursor=start
        while cursor<end:
            stop=min(end,cursor+timedelta(seconds=120));mid=cursor+(stop-cursor)/2
            lst=local_sidereal(mid,p.lon);alt,az,_,_=p._altaz(lst)
            public=p._public_quality(mid,lst,alt);nonterrain=self.policy._target_scale(mid)
            # Replace only the parent's static terrain heuristic. C/E and the
            # parent empirical spots/other published directional factors persist.
            for direction in self.policy.terrain:
                assert direction=='E'
                old=np.where(np.abs((az-90+180)%360-180)<25,.05,1.)
                nonterrain=nonterrain/old
            # If the current bulletin also carries terrain, remove that duplicate
            # static heuristic exactly as source _target_scale applies it.
            for notice in self.policy.notices:
                if notice.get('event_kind')=='terrain_obstruction' and notice.get('direction')=='E':
                    nonterrain/=np.where(np.abs((az-90+180)%360-180)<30,.28,1.)
            sec=(stop-cursor).total_seconds();band+=sec*public
            for j,w in enumerate(self.worlds):
                blocked=(np.abs((az-w['center']+180)%360-180)<=w['radius'])&(alt>=0)&(alt<=w['height'])
                total[j]+=sec*public*nonterrain*(~blocked)
            cursor=stop
        raw=np.minimum(1.,p.flux[None,:]*total*self.env['quality_scale']/p.f0t0)
        # Same conservative duration margin as frozen parent planning.
        factor=raw/self.safety
        bq=band/duration*self.env['program_band_quality_scale']
        bands=np.where(bq>=p.dark_threshold,0,np.where(bq>=p.bright_threshold,1,2))
        mult=np.where(bands[None,:]==np.arange(3)[:,None],p.multipliers[:,None],p.mismatch)
        contrib=raw[:,None,:]*p.weight[None,None,:]*mult[None,:,:]
        lst=local_sidereal(start,p.lon);alt,az,_,vectors=p._altaz(lst)
        eligible=np.asarray([min_altitude_during(p.ra[i],p.dec[i],start,end,{'site':{'latitude_deg':p.lat,'longitude_deg':p.lon}})>=p.min_alt for i in range(p.n)])
        self.cache[key]={'raw':raw,'factor':factor,'contrib':contrib,'vectors':vectors,'eligible':eligible,'alt':alt,'az':az}
        return self.cache[key]
    def action(self,field,offset,duration,weights,S,F):
        p=self.p;data=self.arrays(offset,duration);start=self.now+timedelta(seconds=offset)
        center=radec_to_altaz(*field['eq_center'],start,p.lat,p.lon)
        fiber,hit,_=p._classify(data['vectors'],*center)
        pool=field['pool'];pool=pool[hit[pool]&data['eligible'][pool]]
        if not len(pool):return None
        # Program remains the native field's original selected program; no scan.
        program=field['program'];best=[];fs=[]
        for f in range(p.nfib):
            cell=pool[fiber[pool]==f]
            if not len(cell):continue
            gain=np.zeros(len(cell))
            for j,w in enumerate(weights):
                if w<=0:continue
                gain+=w*(np.maximum(0.,data['contrib'][j,program,cell]-S[j,cell])+
                    p.req_penalty*(p.required[cell]&(F[j,cell]<p.req_threshold)&(data['factor'][j,cell]>=p.req_threshold))+
                    self.jain_gradient[cell]*(F[j,cell]<p.uniform_threshold)*(data['factor'][j,cell]>=p.uniform_threshold))
            i=int(cell[np.argmax(gain)])
            if gain.max()>0:best.append(i);fs.append(f)
        if not best:return None
        ix=np.asarray(best,int);oa=float(self.env.get('pointing_offset_alt_deg',0));oz=float(self.env.get('pointing_offset_az_deg',0))
        cmdalt=round(center[0]-oa,7);cmdaz=round((center[1]-oz)%360,7)
        if not 0<=cmdalt<=90:return None
        actual=(cmdalt+oa,(cmdaz+oz)%360);check,ok,_=p._classify(data['vectors'],*actual)
        if not np.all(ok[ix]&(check[ix]==np.asarray(fs))):return None
        return {'action':'observe','pointing':{'alt_deg':cmdalt,'az_deg':cmdaz},
                'duration_seconds':int(duration),'program':PROGRAMS[program],
                'assignments':{str(int(f)):p.ids[int(i)] for i,f in zip(ix,fs)}}
    def outcomes(self,a,offset,S,F):
        p=self.p;data=self.arrays(offset,a['duration_seconds']);prog=PROGRAMS.index(a['program'])
        ix=np.asarray([p.index[t] for t in a['assignments'].values()],int)
        SS=S.copy();FF=F.copy();feedback=[]
        for j in range(2):
            SS[j,ix]=np.maximum(SS[j,ix],data['contrib'][j,prog,ix])
            FF[j,ix]=np.maximum(FF[j,ix],data['factor'][j,ix])
            feedback.append(tuple((p.ids[i],round(float(data['contrib'][j,prog,i]),6)) for i in ix))
        return SS,FF,feedback
    def known_action_outcomes(self,a,offset,S,F):
        """Preserve literal baseline action assignments; predicted misses get none."""
        p=self.p;data=self.arrays(offset,a['duration_seconds']);prog=PROGRAMS.index(a['program'])
        center=(a['pointing']['alt_deg']+self.env.get('pointing_offset_alt_deg',0),
                (a['pointing']['az_deg']+self.env.get('pointing_offset_az_deg',0))%360)
        fiber,hit,_=p._classify(data['vectors'],*center);pairs=[(int(f),p.index[t]) for f,t in a['assignments'].items()]
        ix=np.asarray([i for f,i in pairs if hit[i] and fiber[i]==f and data['eligible'][i]],int)
        SS=S.copy();FF=F.copy();feedback=[]
        for j in range(2):
            SS[j,ix]=np.maximum(SS[j,ix],data['contrib'][j,prog,ix]);FF[j,ix]=np.maximum(FF[j,ix],data['factor'][j,ix])
            feedback.append(tuple((p.ids[i],round(float(data['contrib'][j,prog,i]),6)) for i in ix))
        return SS,FF,feedback
    def continuations(self,fields,offset,S,F,weights):
        remaining=self.H-offset;found=[]
        for field in fields:
            duration=min(field['native_duration'],remaining)
            if duration<self.p.tmin:continue
            a=self.action(field,offset,duration,weights,S,F)
            if a is None:continue
            ss,ff,_=self.outcomes(a,offset,S,F)
            values=[self.terminal(ss[j],ff[j])-self.base_total for j in range(2)]
            value=float(np.dot(weights,values))
            found.append({'value':value,'world_values':values,'action':a,'parent_order':field['parent_order'],
                          'wait_after_seconds':remaining-duration})
        return found
    def grouped_value(self,fields,a,known=False):
        S=np.tile(self.s0,(2,1));F=np.tile(self.f0,(2,1))
        SS,FF,y=(self.known_action_outcomes if known else self.outcomes)(a,0,S,F)
        groups={}
        for j,feedback in enumerate(y):groups.setdefault(feedback,[]).append(j)
        # Generate the same existing decodes as before, then let every posterior
        # (including frozen) select from their common complete-action union.
        # No new field/target/program/duration proposal is generated by this step.
        union={}
        for worlds in list(groups.values())+[list(range(2))]:
            weights=np.zeros(2);weights[worlds]=1/len(worlds)
            for candidate in self.continuations(fields,a['duration_seconds'],SS,FF,weights):
                union.setdefault(jsha(candidate['action']),candidate)
        if not union:return None
        candidates=[]
        for candidate in union.values():
            ss,ff,_=self.outcomes(candidate['action'],a['duration_seconds'],SS,FF)
            values=[self.terminal(ss[j],ff[j])-self.base_total for j in range(2)]
            candidates.append({**candidate,'world_values':values})
        branches=[];value=0.
        for feedback,worlds in groups.items():
            mass=len(worlds)/2;weights=np.zeros(2);weights[worlds]=1/len(worlds)
            best=max(candidates,key=lambda b:float(np.dot(weights,b['world_values'])))
            best={**best,'value':float(np.dot(weights,best['world_values']))}
            value+=mass*best['value'];branches.append({'worlds':worlds,'probability':mass,'feedback':feedback,**best})
        frozen=max(candidates,key=lambda b:sum(b['world_values'])/2)
        frozen={**frozen,'value':sum(frozen['world_values'])/2}
        assert value>=frozen['value']-1e-9,'same-action-family value of information must be nonnegative'
        return {'value':value,'frozen_value':frozen['value'],'information_value':value-frozen['value'],
                'branches':branches,'frozen':frozen,'outcome_groups':len(groups),
                'common_complete_continuation_action_count':len(candidates),
                'same_complete_action_family_for_all_posteriors':True}

def action_gate(card,c):
    constraints=public_constraints(c);dump(f'{card}/public_constraints.json',constraints)
    worlds,error=supported_worlds(c,constraints)
    if worlds is None:return {'status':'stopped','reason':error,'candidate_frozen':False}
    assert not c['snapshot'].get('active_requests'), 'Active REQ outside this finite gate'
    fields=field_library(c);model=MicroModel(c,worlds)
    dump(f'{card}/worlds.json',{'worlds':worlds,'only_public_support':True,
        'assumptions':'one fixed E sector, centre90, minimal blocked width, two height endpoints, common frozen C/E',
        'candidate_field_count':len(fields),'parent_successful_evaluations':len(c['found']),
        'current_public_slot_remaining_seconds':model.H})
    if model.H<120:return {'status':'stopped','reason':'insufficient shared slot capacity','candidate_frozen':False}
    S=np.tile(model.s0,(2,1));F=np.tile(model.f0,(2,1));probe=None;qualifying=[]
    # Exactly one probe: first qualifying field in original native utility order.
    for field in fields:
        a=model.action(field,0,60,[.5,.5],S,F)
        if a is None:continue
        _,_,feedback=model.outcomes(a,0,S,F)
        maps=[dict(v) for v in feedback]
        anchor=[t for t in maps[0] if maps[0][t]>.5e-6 and maps[1][t]>.5e-6]
        distinguish=[t for t in maps[0] if (maps[0][t]==0)!=(maps[1][t]==0)]
        if anchor and distinguish:
            probe=a;qualifying={'parent_order':field['parent_order'],'anchor_ids':anchor,'distinguishing_ids':distinguish}
            break
    if probe is None:
        dump(f'{card}/no_probe.json',{'field_count':len(fields),'reason':'no same-field common anchor with a zero/positive world split'})
        return {'status':'stopped','reason':'no qualifying anchor/informative probe in unchanged parent fields','candidate_frozen':False}
    value=model.grouped_value(fields,probe)
    if value is None:return {'status':'stopped','reason':'no legal continuation','candidate_frozen':False}
    base=copy.deepcopy(c['base']);base['duration_seconds']=min(base['duration_seconds'],model.H-60)
    control=model.grouped_value(fields,base,known=True)
    if control is None:return {'status':'stopped','reason':'no legal control continuation','candidate_frozen':False}
    branch_hashes=[jsha(b['action']) for b in value['branches']]
    switches=len(set(branch_hashes))>1
    opportunity=value['value']-control['value']
    result={'status':'candidate' if switches and value['information_value']>1e-10 and opportunity>1e-10 else 'stopped',
        'reason':'passed finite action-value gate' if switches and value['information_value']>1e-10 and opportunity>1e-10 else 'no legal switch or information value does not cover native opportunity cost',
        'candidate_frozen':True,'probe':probe,'qualifying':qualifying,'probe_value':value,'native_control_value':control,
        'native_first_action':base,'same_probe_information_value':value['information_value'],
        'gain_after_native_opportunity_cost':opportunity,'legal_conditional_action_switch':switches,
        'scope':'two-action public frozen-C/E current-slot surrogate; exact modeled global best science/required/Jain; no activeREQ; no modeled future loss; not a true card terminal score or complete parent continuation',
        'world_probabilities':'declared equiprobable conditional scenarios, not calibrated official posterior',
        'candidate_field_count':len(fields),'pool_expansion':False,'program_expansion':False,'duration_expansion':False,
        'max_public_constraint_rank':max(r['rank'] for r in constraints['positive']+constraints['zero'])}
    # Evaluator may read hidden scenario only after this artifact is persisted.
    h=dump(f'{card}/candidate_frozen.json',result);result['candidate_artifact_sha256']=h
    result['evaluator_gate']=evaluate_frozen_geometry(card,c,result)
    return result

def evaluate_frozen_geometry(card,c,result):
    """Hidden geometry validator sees frozen actions but cannot select them."""
    from challenge.v4_runner import load_scenario,normalize_action
    scenario=load_scenario(UP/f'local-cards/{card}/config/v4_scenario.json')
    from challenge.v4_runner import _pointing_offset
    oa,oz=_pointing_offset(scenario);grid=FiberGrid.from_config(scenario.fiber_config)
    targets={t['target_id']:t for t in scenario.targets};now=parse_utc(c['snapshot']['now_utc'])
    actions=[('probe',now,result['probe'])]
    for i,b in enumerate(result['probe_value']['branches']):
        actions.append((f'branch{i}',now+timedelta(seconds=60),b['action']))
    checks=[]
    for name,start,a in actions:
        normalize_action(a,scenario,targets,start);predicted_hits=0;true_hits=0;altok=True
        for f,tid in a['assignments'].items():
            t=targets[tid]
            cl=grid.classify_target(t['ra_deg'],t['dec_deg'],start,a['pointing']['alt_deg'],a['pointing']['az_deg'],scenario.site['latitude_deg'],scenario.site['longitude_deg'],oa,oz)
            good=min_altitude_during(t['ra_deg'],t['dec_deg'],start,start+timedelta(seconds=a['duration_seconds']),scenario.config)>=scenario.minimum_altitude_deg
            altok &= good;true_hits+=int(cl.region=='glass' and cl.fiber_id==int(f) and good)
            pc=grid.classify_target(t['ra_deg'],t['dec_deg'],start,a['pointing']['alt_deg'],a['pointing']['az_deg'],scenario.site['latitude_deg'],scenario.site['longitude_deg'],c['env'].get('pointing_offset_alt_deg',0),c['env'].get('pointing_offset_az_deg',0))
            predicted_hits+=int(pc.region=='glass' and pc.fiber_id==int(f) and good)
        checks.append({'action':name,'normalization_valid':True,'assigned':len(a['assignments']),
                       'public_estimated_geometry_hits':predicted_hits,'actual_hidden_geometry_hits':true_hits,'minimum_altitude_valid':bool(altok)})
    audit={'candidate_artifact_sha256':result['candidate_artifact_sha256'],'actions':checks,
           'actor_received_hidden_offset':False,'hidden_geometry_used_for_selection':False,
           'scope':'post-freeze legal syntax, whole-exposure altitude and fiber-hit audit; no score continuation'}
    dump(f'{card}/evaluator_geometry.json',audit);return audit

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--restore-only',action='store_true');args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    sources={str(p):sha(p) for p in FROZEN.rglob('*') if p.is_file()}
    results={};start=time.perf_counter()
    for card in ('L4','L3'):
        try:
            c=restore(card)
            results[card]={'prefix_gate':True,'native_action_exact':c['native_action_exact'],
                          'rank':FIXED[card],'evaluation_count':len(c['found'])}
            print(canonical({'event':'prefix_gate','card':card,**results[card]}),flush=True)
            if not args.restore_only:
                gate=action_gate(card,c);results[card]['action_gate']=gate
                dump(f'{card}/action_gate_result.json',gate)
                print(canonical({'event':'action_gate','card':card,'status':gate['status'],'reason':gate['reason'],
                    'information_value':gate.get('same_probe_information_value'),
                    'opportunity_net':gate.get('gain_after_native_opportunity_cost')}),flush=True)
        except Exception as e:
            results[card]={'prefix_gate':False,'error':repr(e)}
            dump(f'{card}/failure.json',results[card]);print(canonical({'event':'prefix_failed','card':card,'error':repr(e)}),flush=True)
            continue
    assert all(sha(Path(k))==v for k,v in sources.items()),'frozen source changed'
    dump('RESTORE_MANIFEST.json',{'results':results,'source_sha256':sources,'harness_sha256':sha(__file__),
         'wallclock_seconds':time.perf_counter()-start,'full_season_executed':False,'remote_jobs_started':False,
         'scope':'fixed public prefix restoration and natural native cut action gate only'})
    if not args.restore_only:
        dump('MANIFEST.json',{'fixed_states':FIXED,'results':results,'source_sha256':sources,
            'harness_sha256':sha(__file__),'wallclock_seconds':time.perf_counter()-start,
            'full_season_executed':False,'remote_jobs_started':False,'gpu_used':False,'website_submitted':False,
            'actor_truth_access':False,'prior_probe_doc_modified':False,
            'scope':'fixed public prefix restoration plus two-world grouped-feedback current-slot action gate'})

if __name__=='__main__':main()
