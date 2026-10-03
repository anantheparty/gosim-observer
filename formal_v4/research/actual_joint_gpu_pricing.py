"""Bounded real-dual alpha pricing, public measured intervals, isolated GPU.

Prepare/refine run locally. Device phase imports only the finite pricing kernel,
reads fixed public-derived tensors, and returns candidate indices/totals. No API,
production policy, hidden products, or time-potential interpolation.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math,os,shutil,sys,time
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
import numpy as np

PROGRAMS=('DARK','BRIGHT','BACKUP')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clear_geometry(model,start,durations,messages):
    """Conservative continuous whole-track bounds, reference-domain only."""
    from terrain_version_space import altaz_at,DIRECTIONS,SPEED
    from quality_profile_inversion import PublicQualityMatrix
    from required_opportunity_model import parse
    alt0,az0=altaz_at(np.full(len(model.ids),start),model.ra,model.dec,model.latitude,model.longitude)
    endalt=model._alt(start+durations,np.arange(len(model.ids)))
    h0=model._lst([start])[0]-model.ra
    lo=np.minimum(alt0[None,:],endalt);hi=np.maximum(alt0[None,:],endalt)
    lower=np.degrees(np.arcsin(np.clip(model.sinlat*model.sin_dec-model.coslat*model.cos_dec,-1,1)))
    lo=np.where((180-h0)[None,:]%360<=durations[:,None]*SPEED+1e-7,np.minimum(lo,lower[None,:]),lo)-1e-7
    upper=90-np.abs(model.latitude-model.dec)
    hi=np.where((-h0)[None,:]%360<=durations[:,None]*SPEED+1e-7,np.maximum(hi,upper[None,:]),hi)+1e-7
    azmid=np.array([altaz_at(np.full(len(model.ids),start+d/2),model.ra,model.dec,model.latitude,model.longitude)[1] for d in durations])
    radius=np.minimum(180.,SPEED*durations[:,None]/2/np.maximum(np.cos(np.maximum(abs(lo),abs(hi))*math.pi/180),1e-12)+1e-7)
    bulletins={parse(m['issued_at_utc']).timestamp():m for m in messages if m.get('record_type')=='bulletin'}
    terrain=list(dict.fromkeys(n['direction'] for m in messages if m.get('initial') for n in m.get('notices',[]) if n.get('event_kind')=='terrain_obstruction'))
    clear=np.ones(lo.shape,bool)
    def avoid(direction,width,height,d):
        if direction not in DIRECTIONS:return lo[d]>height
        distance=np.abs((azmid[d]-DIRECTIONS[direction]+180)%360-180)
        return (lo[d]>height)|(distance-radius[d]>22.5+width/2+1e-7)
    matrix=PublicQualityMatrix(model)
    for d,duration in enumerate(durations):
        for direction in terrain:clear[d]&=avoid(direction,70,50,d)
        for left,right,slot_start in matrix.overlaps(start,float(duration)):
            bulletin=bulletins.get(slot_start)
            if bulletin is None:clear[d]&=lo[d]>80;continue
            for notice in bulletin.get('notices',[]):
                kind,direction=notice.get('event_kind'),notice.get('direction')
                if direction=='ALL' or kind in ('earthquake','terrain_obstruction'):continue
                width,height=(80,60) if kind=='rocket_launch' else (120,80)
                clear[d]&=avoid(direction,width,height,d)
    visible=(lo>=model.minimum_altitude)&clear
    return np.column_stack((alt0,az0)),visible


def prepare(destination,root=None):
    from quality_profile_prior import ProfileRegistry,public_protocol_initial
    from quality_profile_inversion import load_messages
    from required_opportunity_model import parse,stamp
    from spatial_candidates import _shift_altaz
    root=Path(root or Path(__file__).resolve().parents[2]);formal=root/'formal_v4';destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    dual_path=formal/'results/season_column_dual_audit_20261004/alpha/pricing_duals.json';dual=json.loads(dual_path.read_text())
    initial=public_protocol_initial(formal/'practice_cards/alpha/alpha')
    prior=ProfileRegistry(formal/'research/quality_profile_prior_data/registry.json').identify(initial);assert prior
    model=prior.model;assert model.ids==dual['target_order']
    # Explicit counterfactual old repair path, not a current online confirmation.
    for t in prior.old_repairs:prior.note_report(float(t),True)
    nodes=np.array(dual['time_nodes']);pi=np.array(dual['time_potential']);rho=np.array(dual['rho']);nu=np.array(dual['required_nu']);eta=np.array(dual['request_eta'])
    reports=np.array(dual['admissibility']['fixed_report_times']);allpairs={}
    for j,start in enumerate(nodes):
        n=np.searchsorted(prior.night_end,start,side='right')
        if n>=len(prior.night_start) or start<prior.night_start[n]:continue
        candidates=[]
        for k in range(j+1,min(len(nodes),np.searchsorted(nodes,min(start+3600,prior.night_end[n]),side='right'))):
            end=nodes[k];duration=end-start
            if not 60<=duration<=3600 or abs(duration-round(duration))>1e-7:continue
            if np.any((reports>start)&(reports<end)):continue
            a=np.searchsorted(prior.starts,start,side='right')-1;b=np.searchsorted(prior.starts,end-1e-5,side='right')
            if a<0 or b<=a or np.any(prior.support[a:b]<=0) or np.any(prior.upper[a:b]-prior.lower[a:b]>1e-4):continue
            if prior.ends[b-1]<end-1e-7:continue
            candidates.append((k,int(round(duration)),float(pi[k]-pi[j])))
        if candidates:allpairs[j]=candidates
    rq=dual['requests'][0];rq_a=parse(rq['issued_at_utc']).timestamp();rq_b=parse(rq['deadline_utc']).timestamp()
    scarce=np.flatnonzero((nu>0)|(eta.sum(axis=0)>0))
    ranked=[]
    for j,pairs in allpairs.items():
        best=-np.inf
        for k,duration,cost in pairs:
            t=nodes[j]+duration/2;cell=np.searchsorted(prior.starts,t,side='right')-1
            q=model.public_quality([t],scarce)[0]*prior.lower[cell]
            factor=np.minimum(1,model.flux[scarce]*duration/model.f0t0*q)
            reward=float(nu[scarce][factor>=.5].sum())
            for r,request in enumerate(dual['requests']):
                if parse(request['issued_at_utc']).timestamp()<=nodes[j] and nodes[k]<=parse(request['deadline_utc']).timestamp():
                    reward+=float(eta[r,scarce][factor>=request['completion_factor_threshold']].sum())
            best=max(best,reward-cost)
        ranked.append((best,j))
    ranked.sort(reverse=True);selected=[]
    for night in sorted(set(np.searchsorted(prior.night_end,nodes[j],side='right') for _,j in ranked if rq_a<=nodes[j]<rq_b)):
        choices=[(v,j) for v,j in ranked if rq_a<=nodes[j]<rq_b and np.searchsorted(prior.night_end,nodes[j],side='right')==night]
        if choices:selected.append(choices[0][1])
        if len(selected)>=2:break
    for _,j in ranked:
        if j not in selected:selected.append(j)
        if len(selected)>=4:break
    messages=load_messages(formal/'results/cloud_cd2_alpha_20261003/messages.jsonl')
    np_rng=np.random.default_rng(2026100401);cases=[];fiber=initial['instrument'];glass=math.sqrt(fiber['fiber_area_deg2']);pitch=glass+fiber['gap_deg'];nfib=fiber['n_fibers']
    for case,j in enumerate(selected):
        start=float(nodes[j]);pairs=sorted(allpairs[j],key=lambda r:r[1],reverse=True)[:20];pairs.sort(key=lambda r:r[1])
        durations=np.array([d for k,d,c in pairs]);ends=np.array([nodes[k] for k,d,c in pairs]);cost=np.array([c for k,d,c in pairs])
        chunks=(len(model.ids)+15)//16;idx=np.minimum(np.arange(chunks*16).reshape(chunks,16),len(model.ids)-1)
        target=np.tile(idx,(len(durations),1));starts=np.full(chunks*len(durations),start);ds=np.repeat(durations,chunks)
        q=prior.price_columns(starts,ds,target,now=prior.night_end[-1],require_live_compatibility=False)
        assert q['supported_column'].all()
        qlo=q['quality_lower'].reshape(len(durations),-1)[:,:len(model.ids)];qhi=q['quality_upper'].reshape(len(durations),-1)[:,:len(model.ids)]
        coeff=model.flux[None,:]*durations[:,None]/model.f0t0;flo=np.minimum(1,coeff*qlo);fhi=np.minimum(1,coeff*qhi)
        altaz,visible=clear_geometry(model,start,durations,messages)
        mult=np.array([model.score['program']['multipliers'][p] for p in PROGRAMS]);mismatch=model.score['program']['mismatch_multiplier']
        shi=prior.weights[None,None,:]*fhi[:,None,:]*np.maximum(mismatch,mult)[None,:,None]
        slo=prior.weights[None,None,:]*flo[:,None,:]*np.minimum(mismatch,mult)[None,:,None]
        # E<=1 and clear raw integration imply B>=q; only this one-sided DARK
        # matching lower bound is used. Low q does not classify BRIGHT/BACKUP.
        slo[:,0,:]=prior.weights[None,:]*flo*np.where(qlo>=model.score['program']['bands']['DARK'],mult[0],mismatch)
        values=np.maximum(0,shi-rho[None,None,:])+nu[None,None,:]*(fhi[:,None,:]>=.5)
        for r,request in enumerate(dual['requests']):
            eligible=(start>=parse(request['issued_at_utc']).timestamp())&(ends<=parse(request['deadline_utc']).timestamp())
            values+=eligible[:,None,None]*eta[r,None,None,:]*(fhi[:,None,:]>=request['completion_factor_threshold'])
        eligible=np.flatnonzero(visible.any(axis=0));assert len(eligible)
        choices=np_rng.choice(eligible,32768,replace=True);centers=altaz[choices]+np_rng.uniform(-.4,.4,(32768,2))
        centers[:,0]=np.clip(centers[:,0],model.minimum_altitude,89.9);centers[:,1]%=360
        interesting=np.flatnonzero((nu>0)|(eta.sum(axis=0)>0));seed_centers=[]
        for i in interesting:
            if not visible[:,i].any():continue
            for row in range(4):
                for col in range(4):seed_centers.append(_shift_altaz(*altaz[i],-(row-1.5)*pitch,-(col-1.5)*pitch))
        if seed_centers:centers[:len(seed_centers)]=seed_centers
        deg=math.pi/180;alt,az=altaz.T*deg
        vectors=np.column_stack((np.cos(alt)*np.cos(az),np.cos(alt)*np.sin(az),np.sin(alt)))
        path=destination/f'case_{case}.npz';np.savez_compressed(path,vectors=vectors,centers=centers,values=values,visible=visible,
                            durations=durations,ends=ends,time_cost=cost,qlo=qlo,qhi=qhi,flo=flo,fhi=fhi,slo=slo,shi=shi,altaz=altaz)
        cases.append({'case':case,'start':start,'start_utc':stamp(start),'end_nodes':ends.tolist(),'D':len(durations),'file':path.name,'sha256':sha(path),
                      'inside_first_REQ_window':rq_a<=start<rq_b,'conditional_visible_targets':visible.sum(axis=1).tolist()})
    source=formal/'research/interval_column_pricing.py';shutil.copyfile(source,destination/source.name);shutil.copyfile(__file__,destination/Path(__file__).name)
    metadata={'schema':'actual-joint-public-interval-pricing-v1','card':'alpha','cases':cases,'dual_path':str(dual_path),'dual_sha256':sha(dual_path),
              'rho_nu_eta_source':'existing optimistic joint full-season LP marginals','time_cost':'existing pi[end]-pi[start], no interpolation',
              'programs':PROGRAMS,'glass':glass,'pitch':pitch,'nfib':nfib,'pricing_source_sha256':sha(source),
              'profile_sha256':sha(formal/'research/quality_profile_alpha_result.npz'),
              'hypotheses':'old report/E history; narrow measured reference-domain Z prior; same-realization empirical prior; zerooffset;.03glassmargin; program bounds, not E*W band classification'}
    (destination/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n');print(json.dumps(metadata,indent=2),flush=True)


def gpu(directory,output,pricing_margin=0.):
    imported=time.perf_counter()
    from interval_column_pricing import price_cuda,price_cpu
    from numba import cuda
    import platform
    import_seconds=time.perf_counter()-imported
    directory=Path(directory);meta=json.loads((directory/'metadata.json').read_text());assert sha(directory/'interval_column_pricing.py')==meta['pricing_source_sha256']
    device=cuda.get_current_device()
    pricing_glass=meta['glass']-2*pricing_margin
    assert 0<=pricing_margin<meta['glass']/2
    result={'schema':'actual-joint-GPU-top-candidates-v1','cases':[],'metadata_sha256':sha(directory/'metadata.json'),
            'executed_source_sha256':sha(__file__),'import_seconds':import_seconds,
            'pricing_margin_deg':pricing_margin,'pricing_glass_deg':pricing_glass,
            'device':{'name':device.name.decode() if isinstance(device.name,bytes) else str(device.name),
                      'compute_capability':list(device.compute_capability),'python':platform.python_version(),
                      'numpy':np.__version__,'cuda_simulator':bool(cuda.config.ENABLE_CUDASIM)}};began=time.perf_counter()
    assert not result['device']['cuda_simulator'],'this phase requires physical hardware'
    for case in meta['cases']:
        path=directory/case['file'];assert sha(path)==case['sha256'];a=np.load(path)
        t=time.perf_counter();total=price_cuda(a['vectors'],a['centers'],a['values'],a['visible'],glass=pricing_glass,pitch=meta['pitch'],nfib=meta['nfib'],max_cell_bytes=256*1024**2)
        reduced=total-a['time_cost'][None,:,None];flat=reduced.ravel();positive=np.flatnonzero(flat>1e-7)
        keep=positive[np.argsort(flat[positive])[-min(150,len(positive)):]][::-1]
        pricing_seconds=time.perf_counter()-t
        # Independent NumPy fiber maxima at representative pointings, including
        # the selected best reduced-profit column, before imposing the margin.
        sample=list(np.linspace(0,len(a['centers'])-1,8,dtype=int))
        sample.extend(int(np.unravel_index(index,reduced.shape)[0]) for index in keep[:3])
        sample=np.array(sorted(set(sample)),dtype=int);cpu_began=time.perf_counter()
        reference=price_cpu(a['vectors'],a['centers'][sample],a['values'],a['visible'],
                            glass=pricing_glass,pitch=meta['pitch'],nfib=meta['nfib'])
        error=float(np.max(abs(reference-total[sample])))
        assert error<1e-8,'physical CUDA pricing differs from independent CPU maxima'
        candidates=[]
        for index in keep:
            c,d,p=np.unravel_index(index,reduced.shape);candidates.append({'center_index':int(c),'duration_index':int(d),'program_index':int(p),'reduced_profit_before_margin_refine':float(reduced[c,d,p])})
        result['cases'].append({'case':case['case'],'seconds':time.perf_counter()-t,'pricing_seconds':pricing_seconds,
                               'cpu_gate_seconds':time.perf_counter()-cpu_began,'cpu_checked_pointings':len(sample),
                               'cpu_checked_finite_columns':int(reference.size),'cpu_cuda_max_absolute_error':error,
                               'positive_finite_columns':len(positive),'finite_columns':int(flat.size),'top':candidates})
        print(json.dumps({'case':case['case'],'positive':len(positive),'seconds':result['cases'][-1]['seconds']}),flush=True)
    result['elapsed_seconds']=time.perf_counter()-began;Path(output).write_text(json.dumps(result,indent=2)+'\n')


def refine(directory,output,top_path=None):
    from quality_profile_inversion import all_target_model,load_messages,PublicQualityMatrix,ReferenceClearFilter
    from required_opportunity_model import parse,stamp
    directory=Path(directory);top_path=Path(top_path) if top_path else directory/'gpu_top.json'
    meta=json.loads((directory/'metadata.json').read_text());top=json.loads(top_path.read_text());root=Path(__file__).resolve().parents[2];formal=root/'formal_v4'
    sys.path.insert(0,str(formal/'upstream/gosim-observer-examples/runner'))
    from challenge.v4_fiber_map import FiberGrid,min_altitude_during
    from interval_column_pricing import fiber_indices,basis
    assert top['metadata_sha256']==sha(directory/'metadata.json')
    assert sha(Path(meta['dual_path']))==meta['dual_sha256']
    assert sha(formal/'research/quality_profile_alpha_result.npz')==meta['profile_sha256']
    dual=json.loads(Path(meta['dual_path']).read_text());model=all_target_model(formal/'practice_cards/alpha/alpha');rho=np.array(dual['rho']);nu=np.array(dual['required_nu']);eta=np.array(dual['request_eta'])
    profile=np.load(formal/'research/quality_profile_alpha_result.npz');pm=json.loads((formal/'research/quality_profile_alpha_result.json').read_text());matrix=PublicQualityMatrix(model,[parse(t).timestamp() for t in pm['repair_timestamps_utc']])
    clear=ReferenceClearFilter(model,load_messages(formal/'results/cloud_cd2_alpha_20261003/messages.jsonl'))
    grid=FiberGrid(meta['glass']**2,meta['pitch']-meta['glass'],meta['nfib']);columns=[];seen=set();checks=0;discarded=0;geometryerr=0.;began=time.perf_counter()
    for case,priced in zip(meta['cases'],top['cases']):
        assert case['case']==priced['case'] and sha(directory/case['file'])==case['sha256']
        a=np.load(directory/case['file']);start=case['start']
        for candidate in priced['top']:
            c,d,p=[candidate[k] for k in ('center_index','duration_index','program_index')];center=a['centers'][c];end=float(a['ends'][d]);duration=int(a['durations'][d]);program=meta['programs'][p]
            fibers=fiber_indices(a['vectors'],center,meta['glass'],meta['pitch'],4);b=basis([center])[0];depth=a['vectors']@b[:3]
            dn=(a['vectors']@b[3:6])/np.maximum(depth,1e-300)/(math.pi/180);de=(a['vectors']@b[6:9])/np.maximum(depth,1e-300)/(math.pi/180)
            rows=np.clip(fibers//4,0,3);cols=np.clip(fibers%4,0,3)
            margin=np.minimum(meta['glass']/2-abs(dn-(rows-1.5)*meta['pitch']),meta['glass']/2-abs(de-(cols-1.5)*meta['pitch']))
            allowed=(fibers>=0)&a['visible'][d]&(margin>.03);assignment={}
            for f in range(16):
                ids=np.flatnonzero(allowed&(fibers==f)&(a['values'][d,p]>0))
                if len(ids):assignment[str(f)]=int(ids[np.argmax(a['values'][d,p,ids])])
            if not assignment:discarded+=1;continue
            indices=np.array(list(assignment.values()));cells,coef=matrix.coefficients(start,duration,indices)
            qlo=coef@profile['lower'][cells];qhi=coef@profile['upper'][cells]
            geometryerr=max(geometryerr,float(np.max(abs(qlo-a['qlo'][d,indices]))),float(np.max(abs(qhi-a['qhi'][d,indices]))))
            assert geometryerr<1e-8
            entries={};action_assign={};moment=parse(stamp(start));stop=parse(stamp(end));overlaps=matrix.overlaps(start,duration)
            for j,(f,i) in enumerate(assignment.items()):
                assert clear.clear(i,overlaps)
                hit=grid.classify_target(model.ra[i],model.dec[i],moment,*center,model.latitude,model.longitude);assert hit.region=='glass' and hit.fiber_id==int(f)
                assert min_altitude_during(model.ra[i],model.dec[i],moment,stop,{'site':{'latitude_deg':model.latitude,'longitude_deg':model.longitude}})>=model.minimum_altitude-1e-8
                tid=model.ids[i];action_assign[f]=tid
                entries[tid]={'score_lower':float(a['slo'][d,p,i]),'score_upper':float(a['shi'][d,p,i]),
                              'factor_lower':float(a['flo'][d,i]),'factor_upper':float(a['fhi'][d,i]),'quality_lower':float(qlo[j]),'quality_upper':float(qhi[j])};checks+=1
            reduced=sum(float(a['values'][d,p,i]) for i in assignment.values())-float(a['time_cost'][d])
            if reduced<=1e-7:discarded+=1;continue
            key=(start,end,program,tuple(sorted(action_assign.items())))
            if key in seen:continue
            seen.add(key);columns.append({'kind':'actual-GPU-dual-priced','start':start,'end':end,'entries':entries,
              'action':{'action':'observe','pointing':{'alt_deg':float(center[0]),'az_deg':float(center[1])},'duration_seconds':duration,'program':program,'assignments':action_assign},
              'reduced_profit':reduced,'quality_scope':meta['hypotheses'],'source_case':case['case'],'minimum_fiber_margin_deg':float(margin[indices].min())})
    columns.sort(key=lambda c:c['reduced_profit'],reverse=True)
    result={'card':'alpha','columns':columns[:60],'scope':meta['hypotheses'],'counters':{'positive_refined_unique':len(columns),'retained':min(60,len(columns)),
            'discarded_or_nonpositive':discarded,'official_assignment_and_visibility_checks':checks,'batch_exact_quality_maxerror':geometryerr},
            'dual_sha256':meta['dual_sha256'],'profile_sha256':meta['profile_sha256'],'GPU_top_sha256':sha(top_path),
            'pricing_margin_deg':top.get('pricing_margin_deg',0.),
            'elapsed_seconds':time.perf_counter()-began}
    Path(output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='columns'},indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prepare');parser.add_argument('--gpu');parser.add_argument('--refine');parser.add_argument('--output');parser.add_argument('--top');parser.add_argument('--pricing-margin',type=float,default=0.);args=parser.parse_args()
    if args.prepare:prepare(args.prepare)
    elif args.gpu:gpu(args.gpu,args.output,args.pricing_margin)
    elif args.refine:refine(args.refine,args.output,args.top)
