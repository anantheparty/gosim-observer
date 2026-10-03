"""Public geometry / owned local trajectory labels for a candidate value NN.

The teacher is spherical fibre assignment and exposure-breakpoint evaluation,
not incumbent action imitation or a finite season DP. Only L1--L4 are allowed.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, os, sys, time
from datetime import timedelta
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from spatial_candidates import DEG, PROGRAMS, SpatialPlanner, _shift_altaz, parse_utc
from cpu_phase_candidates import CPUPhaseSpatialPlanner, coarse_numpy_local

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ['altitude', 'azimuth_sin', 'azimuth_cos', 'targets_per_fibre', 'occupied_fibres',
            'missing_required_per_fibre', 'mean_weight', 'max_weight', 'mean_log_flux',
            'max_log_flux', 'mean_up_fraction', 'mean_glass_margin', 'quality_scale',
            'night_fraction', 'mean_existing_score'] + [f'rate_{d}_{p}' for d in (60,240,900,1800) for p in PROGRAMS]


def public_initialization(card):
    directory=ROOT/'upstream/gosim-observer-examples/local-cards'/card
    names=['config/v4_scenario.json','config/v4_fiber_config.json','config/v4_score_config.json',
           'public/targets.csv','public/v4_night_calendar.csv']
    content={n:(directory/n).read_bytes() for n in names}
    scenario,fiber,score=[json.loads(content[n]) for n in names[:3]]
    targets=list(csv.DictReader(content[names[3]].decode().splitlines()))
    calendar=list(csv.DictReader(content[names[4]].decode().splitlines()))
    field=fiber['field']; side=math.isqrt(int(field['n_fibers']))
    glass=math.sqrt(float(field['fiber_area_deg2'])); pitch=glass+float(field['gap_deg'])
    columns=list(targets[0]); rows=[[r[n] if n in ('target_id','target_class') else
        r[n].lower()=='true' if n=='required' else float(r[n]) for n in columns] for r in targets]
    nights=[{k:r[k] for k in ('night_id','night_date','observing_start_utc','observing_end_utc')} for r in calendar]
    site={**scenario['site'],'minimum_altitude_deg':float(scenario['minimum_altitude_deg'])}
    return {'site':site, 'survey':{'nights':nights},'instrument':{**field,'grid_side':side,
        'glass_side_deg':glass,'pitch_deg':pitch,'fov_side_deg':side*pitch,'exposure':fiber['exposure']},
        'targets':{'columns':columns,'rows':rows},'scoring':score}, {
        str(directory/n):hashlib.sha256(content[n]).hexdigest() for n in names}


def local_ledger(card, planner, now):
    directory=ROOT/'results/gpu_direct_calendar_witness_20261003'/card
    decisions={r['observe_index']:r for r in csv.DictReader((directory/'decisions.csv').open()) if r['action']=='observe'}
    scores=np.zeros(planner.n); factors=np.zeros(planner.n)
    for row in csv.DictReader((directory/'observations.csv').open()):
        if row['valid']=='true' and parse_utc(decisions[row['observe_index']]['end_utc'])<=now:
            i=planner.index[row['target_id']]
            scores[i]=max(scores[i],float(row['score'])); factors[i]=max(factors[i],float(row['factor']))
    return scores,factors, {str(directory/n):hashlib.sha256((directory/n).read_bytes()).hexdigest()
                           for n in ('observations.csv','decisions.csv')}


def center_features(planner, center, pool, frame, quality, night_fraction, compare_coarse=True):
    _,up,k,scores,factors,mult,missing,rr,rt,rd,ub,urgency,left,safety,focus=frame
    assert focus is None
    fibre,valid,margin=planner._classify(frame[0][pool],*center)
    idx=pool[valid]; fibre=fibre[valid]; margin=margin[valid]
    x=[center[0]/90, math.sin(center[1]*DEG), math.cos(center[1]*DEG),len(idx)/planner.nfib,
       len(np.unique(fibre))/planner.nfib, float(missing[idx].sum())/planner.nfib,
       float(planner.weight[idx].mean()) if len(idx) else 0, float(planner.weight[idx].max()) if len(idx) else 0,
       float(np.log1p(planner.flux[idx]).mean()) if len(idx) else 0,
       float(np.log1p(planner.flux[idx]).max()) if len(idx) else 0,
       float(np.minimum(up[idx]/planner.tmax,1).mean()) if len(idx) else 0,
       float(margin.mean()/planner.glass) if len(idx) else 0,quality,night_fraction,
       float(scores[idx].mean()) if len(idx) else 0]
    def rates(duration):
        duration=min(int(duration),left); raw=np.minimum(1,duration*k[idx]); robust=np.minimum(1,duration*k[idx]/safety)
        terminal=missing[idx]*(robust+1e-10>=planner.req_threshold)*planner.req_penalty
        terminal+=(factors[idx]<planner.uniform_threshold)*(robust+1e-10>=planner.uniform_threshold)*ub[idx]
        terminal+=(rr[idx]>0)*(robust+1e-10>=rt[idx])*(duration<=rd[idx])*rr[idx]
        value=(np.maximum(0,planner.weight[idx]*raw*mult[:,idx]-scores[idx])+terminal)*urgency[idx]
        value=np.where(duration<=up[idx],value,-np.inf)
        cells=np.zeros((3,planner.nfib))
        for p in range(3):np.maximum.at(cells[p],fibre,value[p])
        return cells.sum(axis=1)/duration
    for duration in (60,240,900,1800):x.extend(rates(duration))
    coarse=max(float(rates(d).max()) for d in (60,120,240,400,900,1800,left)) if compare_coarse else None
    return np.asarray(x,dtype=np.float32),coarse


def generate(destination, states=8, candidates=768):
    destination=Path(destination); destination.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(261003); features=[]; labels=[]; coarse=[]; groups=[]; geometry=[]; metadata=[]; sources={}
    for ci,card in enumerate(('L1','L2','L3','L4')):
        initial,source=public_initialization(card); sources.update(source); planner=CPUPhaseSpatialPlanner(initial)
        for si in range(states):
            night=min(len(planner.nights)-1,si*max(1,len(planner.nights)//states))
            begin,end=planner.nights[night]; now=begin+timedelta(seconds=int((end-begin).total_seconds()*(.12+.11*(si%4))))
            scores,factors,source=local_ledger(card,planner,now); sources.update(source)
            # Counterfactual state perturbations: real earlier outcomes are a
            # starting state, never labels. New target subsets change scarcity.
            if si%2:
                erased=rng.random(planner.n)<.25; scores[erased]=0; factors[erased]=0
                sampled=rng.random(planner.n)<.10
                factors[sampled]=rng.uniform(.15,.85,int(sampled.sum()))
                scores[sampled]=planner.weight[sampled]*factors[sampled]
            quality=float((.35,.55,.75,.9)[si%4]); snapshot={'now_utc':now.isoformat(),'latest_bulletin':{'notices':[]}}
            env={'quality_scale':quality,'program_band_quality_scale':quality/.95,'cpu_phase_fixed_workload':True,
                 'use_bulletin_directional_prior':False}
            started=time.perf_counter(); action=planner.choose(snapshot,scores,factors,env,[])
            if action is None:continue
            frame=planner._cpu_phase_frame; useful=np.flatnonzero(planner._merit(frame)>1e-10)
            alt=np.arcsin(np.clip(frame[0][:,2],-1,1))/DEG; az=np.arctan2(frame[0][:,1],frame[0][:,0])/DEG%360
            # Wider global proposal distribution than the four incumbent seeds:
            # priority-weighted + uniform visible target anchors, all fibres,
            # continuous random glass offsets, and existing baseline centres.
            weights=planner._merit(frame)[useful]; weights=weights/weights.sum()
            anchors=np.r_[rng.choice(useful,48,p=weights),rng.choice(useful,48)]
            centers=[tuple(c[1]) for c in planner._cpu_phase_baseline_candidates]
            for anchor in anchors:
                f=int(rng.integers(planner.nfib)); row,col=divmod(f,planner.side)
                dn=-(row-(planner.side-1)/2)*planner.pitch+rng.uniform(-.5,.5)*planner.pitch
                de=-(col-(planner.side-1)/2)*planner.pitch+rng.uniform(-.5,.5)*planner.pitch
                for scale in (0.,.25,.6,1.):
                    centers.append(_shift_altaz(float(alt[anchor]),float(az[anchor]),dn*scale,de*scale))
            centers=np.unique(np.round(centers,7),axis=0); centers=centers[(centers[:,0]>=0)&(centers[:,0]<=90)]
            if len(centers)>candidates:centers=centers[rng.choice(len(centers),candidates,replace=False)]
            gid=len(metadata); xs=[]; ys=[]; cs=[]; valid_geometry=True
            for center in centers:
                vector=np.array([math.cos(center[0]*DEG)*math.cos(center[1]*DEG),math.cos(center[0]*DEG)*math.sin(center[1]*DEG),math.sin(center[0]*DEG)])
                pool=useful[np.einsum('ij,j->i',frame[0][useful],vector)>=math.cos(planner.fov*DEG)]
                x,c=center_features(planner,center,pool,frame,quality,(now-begin).total_seconds()/(end-begin).total_seconds())
                exact=SpatialPlanner._evaluate(planner,tuple(center),pool,*frame)
                y=0. if exact is None else exact[0]
                if exact is not None:
                    fibres,valid,_=planner._classify(frame[0][exact[4]],*center)
                    valid_geometry &= bool(np.all(valid)&np.all(fibres==exact[5]))
                xs.append(x); ys.append(y); cs.append(c)
            assert valid_geometry
            baseline=float(planner.stats['selected_exact_rate'])
            # Explicit coarse feature arithmetic comparison against original
            # evaluator, using the full useful catalogue and same durations.
            reference=coarse_numpy_local(planner,centers[:8],useful,frame,np.unique(np.minimum((60,120,240,400,900,1800,frame[12]),frame[12])))
            assert np.max(np.abs(reference-np.asarray(cs[:8])))<1e-10
            features.extend(xs);labels.extend(ys);coarse.extend(cs);groups.extend([gid]*len(xs));geometry.extend(centers)
            record={'group':gid,'card':card,'night':night,'now_utc':now.isoformat(),'counterfactual':bool(si%2),
                    'candidates':len(xs),'CPUPhase_exact_rate':baseline,'wide_oracle_exact_rate':max(ys),
                    'geometry_gate':True,'coarse_crosscheck_max_error':float(np.max(np.abs(reference-np.asarray(cs[:8])))),
                    'seconds':time.perf_counter()-started}
            metadata.append(record);print(json.dumps(record),flush=True)
    np.savez_compressed(destination/'dataset.npz',x=np.asarray(features,dtype=np.float32),y=np.asarray(labels,dtype=np.float32),
                        coarse=np.asarray(coarse,dtype=np.float32),group=np.asarray(groups,dtype=np.int32),centers=np.asarray(geometry))
    manifest={'schema':'candidate-NN-local-supervision-v1','features':FEATURES,'groups':metadata,'source_sha256':sources,
              'truth_files_opened':0,'platform_cards_read':0,'teacher':'frozen spherical per-fibre exposure-breakpoint oracle; no season DP',
              'label_scope':'bounded local utility, not official score or global optimum','split':'L1/L2 early nights train; late nights heldout; L3 validation; L4 test',
              'rows':len(labels),'seed':261003}
    (destination/'data_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',default=str(ROOT/'results/nn_proposal_20261003'))
    p.add_argument('--states',type=int,default=8);p.add_argument('--candidates',type=int,default=768)
    a=p.parse_args();generate(a.out,a.states,a.candidates)
