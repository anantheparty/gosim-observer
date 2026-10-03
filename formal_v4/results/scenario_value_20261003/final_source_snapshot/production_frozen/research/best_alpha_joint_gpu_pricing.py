"""Fresh best-alpha dual stabilization and conditional physical GPU pricing.

Independent research outputs. Device branch imports only NumPy and the copied
pricing utility/kernel. All temporal/quality evidence is participant-public.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math,os,shutil,sys,time
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
import numpy as np
PROGRAMS=('DARK','BRIGHT','BACKUP')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def dump(p,x):Path(p).write_text(json.dumps(x,indent=2,allow_nan=False,default=lambda v:v.item() if isinstance(v,np.generic) else v.tolist())+'\n')
def root_setup():
    root=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root/'formal_v4/upstream/gosim-observer-examples/runner'))
    return root
def context(root):
    from quality_profile_inversion import all_target_model,PublicQualityMatrix,load_messages,ReferenceClearFilter
    from required_opportunity_model import parse
    from request_remote_owned_gate import initial_public
    base=root/'formal_v4/results/best_incumbent_alpha_master_20261003'
    summary=read(base/'summary.json');serialized=read(base/'pricing_duals.json');columns=read(base/'column_pool.json')
    assert sha(base/'column_pool.json')==serialized['column_pool_sha256'] and len(columns)==1376
    model=all_target_model(root/'formal_v4/practice_cards/alpha/alpha')
    model.actual_required=[r['target_id'] for r in csv.DictReader((root/'formal_v4/practice_cards/alpha/alpha/public/targets.csv').open()) if r['required'].lower()=='true']
    initial,_=initial_public(root/'formal_v4/practice_cards/alpha/alpha')
    repairs=[parse(t).timestamp() for t in summary['fixed_successful_repair_times_utc']]
    matrix=PublicQualityMatrix(model,repairs);profile=np.load(base/'conditional_profile_new_repair_cells.npz')
    assert np.array_equal(profile['cell_start'],matrix.starts) and np.array_equal(profile['cell_end'],matrix.ends)
    messages=load_messages(root/'formal_v4/results/cloud_phase_gpu_alpha_20261003/messages.jsonl')
    return base,summary,serialized,columns,model,initial,matrix,profile,messages,ReferenceClearFilter(model,messages)


def prepare(out):
    root=root_setup();out=Path(out);out.mkdir(parents=True,exist_ok=True);began=time.perf_counter()
    base,summary,serialized,columns,model,initial,matrix,profile,messages,clear=context(root)
    from season_dual_stabilization import finite_primal,secondary_dual
    from required_opportunity_model import parse,stamp
    from actual_joint_gpu_pricing import clear_geometry
    from spatial_candidates import _shift_altaz
    call,primal,original,original_audit,tags=finite_primal(columns,model,serialized['requests'],[])
    completed=set(model.actual_required)-set(summary['baseline_reconstructed']['missing_ids'])
    lam,mu,lower,upper,rawproof=secondary_dual(call,primal,tags,completed,90)
    clean_mu=np.minimum(mu,0.);clean_lower=np.maximum(lower,0.);clean_upper=np.minimum(upper,0.)
    residual=call['c']-call['A_eq'].T@lam-call['A_ub'].T@clean_mu-clean_lower-clean_upper
    b=np.asarray(call['b_eq']);d=np.asarray(call['b_ub']);bounds=call['bounds']
    objective=math.fsum(float(x)*float(y) for x,y in zip(b,lam))+math.fsum(float(x)*float(y) for x,y in zip(d,clean_mu))
    objective+=math.fsum(float(l)*float(clean_lower[j]) for j,(l,u) in enumerate(bounds) if l is not None)
    objective+=math.fsum(float(u)*float(clean_upper[j]) for j,(l,u) in enumerate(bounds) if u is not None)
    cp=[float(np.max(abs(clean_mu*(d-call['A_ub']@primal.x))))]
    cp += [max((abs(clean_lower[j]*(primal.x[j]-l)) for j,(l,u) in enumerate(bounds) if l is not None),default=0.),
           max((abs(clean_upper[j]*(u-primal.x[j])) for j,(l,u) in enumerate(bounds) if u is not None),default=0.)]
    cleanup={'mu_positive_count':int((mu>0).sum()),'mu_positive_max':float(max(0.,mu.max())),
             'total_multiplier_l1_change':float(abs(clean_mu-mu).sum()+abs(clean_lower-lower).sum()+abs(clean_upper-upper).sum()),
             'stationarity_max_abs_after':float(np.max(abs(residual))),'objective_error_after':abs(objective-primal.fun),
             'complementarity_max_after':max(cp),'clean_signs_exact':bool(np.all(clean_mu<=0)&np.all(clean_lower>=0)&np.all(clean_upper<=0)),
             'numeric_gate_tolerance_stationarity':1e-7,'numeric_gate_tolerance_objective_complementarity':1e-6}
    assert cleanup['stationarity_max_abs_after']<1e-7 and cleanup['objective_error_after']<1e-6 and max(cp)<1e-6
    rho={};nu={};eta={}
    for tag,value in zip(tags,-clean_mu):
        if tag[0]=='winner_simplex':rho[tag[1]]=float(value)
        elif tag[0]=='required':nu[tag[1]]=float(value)
        elif tag[0]=='request_target':eta[tag[1],tag[2]]=float(value)
    times=np.array(sorted(set(c['start'] for c in columns)|set(c['end'] for c in columns)))
    assert list(times)==serialized['time_nodes'] and model.ids==serialized['target_order']
    dual={'rho':[rho.get(t,0.) for t in model.ids],'required_nu':[nu.get(t,0.) for t in model.ids],
          'request_eta':[[eta.get((r,t),0.) for t in model.ids] for r in range(len(serialized['requests']))],
          'time_nodes':times.tolist(),'time_potential':lam.tolist(),'target_order':model.ids,'requests':serialized['requests'],
          'admissibility':serialized['admissibility'],'fresh_column_pool_sha256':sha(base/'column_pool.json')}
    from season_column_dual_audit import reduced_cost
    pricing={'rho':rho,'nu':nu,'eta':eta,'potential':dict(zip(times,lam)),
             'windows':[(parse(r['issued_at_utc']).timestamp(),parse(r['deadline_utc']).timestamp()) for r in serialized['requests']]}
    pool_rc=[reduced_cost(c,pricing,serialized['requests'])[0] for c in columns]
    cleanup['existing_pool_reduced_profit_max_after']=float(max(pool_rc));assert max(pool_rc)<1e-7
    proof={'raw':rawproof,'cleanup':cleanup,'fresh_primal_audit':original_audit,
           'completed_nu_sum_before':sum(original['nu'].get(t,0.) for t in completed),
           'completed_nu_sum_after':sum(nu.get(t,0.) for t in completed),
           'baseline_official_total':summary['baseline_official_total'],'source_pool_sha256':sha(base/'column_pool.json')}
    dump(out/'stabilization.json',proof);dump(out/'pricing_duals_stabilized.json',dual)
    np.savez_compressed(out/'full_dual_raw_clean.npz',lambda_eq=lam,raw_mu=mu,clean_mu=clean_mu,raw_lower=lower,clean_lower=clean_lower,
                        raw_upper=upper,clean_upper=clean_upper,primal_x=primal.x,primal_cost=call['c'],primal_fun=np.array(primal.fun))
    reports=np.array(serialized['admissibility']['fixed_report_times']);support=profile['support'];lo=profile['lower'];hi=profile['upper']
    scarce=np.array([model.index[t] for t in summary['baseline_reconstructed']['missing_ids']]);allpairs={};opportunities=[];rejected=0
    for j,start in enumerate(times):
        night=int(np.searchsorted(matrix.night_ends,start,side='right'))
        if night>=len(model.nights) or start<model.nights[night][0]:continue
        for k in range(j+1,min(len(times),np.searchsorted(times,min(start+3600,model.nights[night][1]),side='right'))):
            duration=times[k]-start
            if not 60<=duration<=3600 or abs(duration-round(duration))>1e-7 or np.any((reports>start)&(reports<times[k])):continue
            a=np.searchsorted(matrix.starts,start,side='right')-1;z=np.searchsorted(matrix.starts,times[k]-1e-6,side='right')
            if a<0 or z<=a or np.any(support[a:z]<=0) or not np.all(np.isfinite(lo[a:z])) or np.any(hi[a:z]-lo[a:z]>1e-4) or matrix.ends[z-1]<times[k]-1e-7:
                rejected+=1;continue
            allpairs.setdefault(j,[]).append((k,int(round(duration))))
            cells,coef=matrix.coefficients(start,duration,scarce);q=coef@lo[cells];factor=np.minimum(1,model.flux[scarce]*duration/model.f0t0*q)
            for s,index in enumerate(scarce):
                if factor[s]>=.5:opportunities.append((float(factor[s]),int(index),j,k,night))
    opportunities.sort(reverse=True);selected=[];used_nights={};coverage={model.ids[i]:{'supported_factor_ge_half_pairs':int(sum(v[1]==i for v in opportunities)),'selected_cases':[]} for i in scarce}
    for index in scarce:
        for factor,i,j,k,night in opportunities:
            if i!=index or (i,night) in used_nights:continue
            if j in selected:
                coverage[model.ids[i]]['selected_cases'].append(selected.index(j));used_nights[i,night]=True;continue
            overlaps=matrix.overlaps(times[j],times[k]-times[j])
            if not clear.clear(i,overlaps):continue
            if np.min(model._alt(np.array([times[j],times[k],(times[j]+times[k])/2]),[i]))<model.minimum_altitude+.04:continue
            selected.append(j);coverage[model.ids[i]]['selected_cases'].append(len(selected)-1);used_nights[i,night]=True
            if len(coverage[model.ids[i]]['selected_cases'])>=2:break
        if len(selected)>=6:break
    dump(out/'coverage.json',{'missing_targets':coverage,'supported_pair_starts':len(allpairs),'unsupported_pairs_rejected':rejected,'selected_cases':len(selected)})
    if not selected:raise ValueError('No clear fully-supported missing-target window at existing fresh nodes')
    rows=np.array(dual['rho']);nuv=np.array(dual['required_nu']);ev=np.array(dual['request_eta']);rng=np.random.default_rng(2026100303)
    glass=math.sqrt(initial['instrument']['fiber_area_deg2']);pitch=glass+initial['instrument']['gap_deg'];cases=[]
    for case,j in enumerate(selected[:6]):
        start=float(times[j]);pairs=sorted(allpairs[j],key=lambda x:x[1],reverse=True)[:12];pairs.sort(key=lambda x:x[1])
        durations=np.array([d for k,d in pairs]);ends=np.array([times[k] for k,d in pairs]);qlo=[];qhi=[]
        for duration in durations:
            cells,coef=matrix.coefficients(start,int(duration),np.arange(len(model.ids)))
            qlo.append(coef@lo[cells]);qhi.append(coef@hi[cells])
        qlo=np.array(qlo);qhi=np.array(qhi);assert np.isfinite(qlo).all() and np.isfinite(qhi).all()
        flo=np.minimum(1,model.flux[None,:]*durations[:,None]/model.f0t0*qlo);fhi=np.minimum(1,model.flux[None,:]*durations[:,None]/model.f0t0*qhi)
        weights=np.array([float(r['science_weight']) for r in csv.DictReader((root/'formal_v4/practice_cards/alpha/alpha/public/targets.csv').open())])
        mult=np.array([model.score['program']['multipliers'][p] for p in PROGRAMS]);mismatch=model.score['program']['mismatch_multiplier']
        shi=weights[None,None,:]*fhi[:,None,:]*np.maximum(mismatch,mult)[None,:,None]
        slo=weights[None,None,:]*flo[:,None,:]*np.minimum(mismatch,mult)[None,:,None]
        slo[:,0,:]=weights[None,:]*flo*np.where(qlo>=model.score['program']['bands']['DARK'],mult[0],mismatch)
        values=np.maximum(0,shi-rows[None,None,:])+nuv[None,None,:]*(fhi[:,None,:]>=.5)
        for r,request in enumerate(dual['requests']):
            eligible=(start>=parse(request['issued_at_utc']).timestamp())&(ends<=parse(request['deadline_utc']).timestamp())
            values+=eligible[:,None,None]*ev[r,None,None,:]*(fhi[:,None,:]>=request['completion_factor_threshold'])
        altaz,visible=clear_geometry(model,start,durations,messages);eligible=np.flatnonzero(visible.any(axis=0));assert len(eligible)
        chosen=rng.choice(eligible,32768);centers=altaz[chosen]+rng.uniform(-.4,.4,(32768,2));centers[:,0]=np.clip(centers[:,0],model.minimum_altitude,89.9);centers[:,1]%=360
        seeds=[]
        for i in scarce:
            if not visible[:,i].any():continue
            for row in range(4):
                for col in range(4):seeds.append(_shift_altaz(*altaz[i],-(row-1.5)*pitch,-(col-1.5)*pitch))
        centers[:len(seeds)]=seeds;a,z=altaz.T*math.pi/180;vectors=np.column_stack((np.cos(a)*np.cos(z),np.cos(a)*np.sin(z),np.sin(a)))
        path=out/f'case_{case}.npz';np.savez_compressed(path,vectors=vectors,centers=centers,values=values,visible=visible,durations=durations,ends=ends,
                     time_cost=lam[[k for k,d in pairs]]-lam[j],qlo=qlo,qhi=qhi,flo=flo,fhi=fhi,slo=slo,shi=shi)
        cases.append({'case':case,'start':start,'start_utc':stamp(start),'file':path.name,'sha256':sha(path),'D':len(durations),
                      'missing_visible_factor_ge_half':{model.ids[i]:int(np.sum(visible[:,i]&(flo[:,i]>=.5))) for i in scarce}})
    for name in ('interval_column_pricing.py','actual_joint_gpu_pricing.py'):
        shutil.copyfile(root/'formal_v4/research'/name,out/name)
    shutil.copyfile(__file__,out/Path(__file__).name)
    meta={'card':'alpha','cases':cases,'programs':PROGRAMS,'glass':glass,'pitch':pitch,'nfib':16,
          'pricing_source_sha256':sha(out/'interval_column_pricing.py'),'dual_path':str((out/'pricing_duals_stabilized.json').resolve()),
          'dual_sha256':sha(out/'pricing_duals_stabilized.json'),'profile_sha256':sha(base/'conditional_profile_new_repair_cells.npz'),
          'hypotheses':'fresh Phase alpha report/E partition; conditional narrow same-realization Z gate; zerooffset; reference event direction bounds; program bounds; .03 margin',
          'fresh_pool_sha256':sha(base/'column_pool.json'),'prepare_seconds':time.perf_counter()-began}
    dump(out/'metadata.json',meta);print(json.dumps({'cases':len(cases),'prepare_seconds':meta['prepare_seconds'],'coverage':coverage,'cleanup':cleanup},indent=2),flush=True)


def refine(directory,out):
    root=root_setup();directory=Path(directory);began=time.perf_counter();base,summary,serialized,columns,model,initial,matrix,profile,messages,clear=context(root)
    from challenge.v4_fiber_map import FiberGrid,min_altitude_during
    from interval_column_pricing import fiber_indices,basis
    from required_opportunity_model import parse,stamp
    meta=read(directory/'metadata.json');top=read(directory/'gpu_top.json');assert top['metadata_sha256']==sha(directory/'metadata.json')
    grid=FiberGrid(meta['glass']**2,meta['pitch']-meta['glass'],16);found=[];seen=set();checks=0;quality_error=0.;price_error=0.
    for case,priced in zip(meta['cases'],top['cases']):
        assert sha(directory/case['file'])==case['sha256'];a=np.load(directory/case['file']);start=case['start']
        for candidate in priced['top'][:50]:
            c,d,p=[candidate[k] for k in ('center_index','duration_index','program_index')];center=a['centers'][c];end=float(a['ends'][d]);duration=int(a['durations'][d]);program=PROGRAMS[p]
            fibers=fiber_indices(a['vectors'],center,meta['glass']-.06,meta['pitch'],4);b=basis([center])[0];depth=np.einsum('ij,j->i',a['vectors'],b[:3]);den=np.maximum(depth,1e-300)*math.pi/180
            dn=np.einsum('ij,j->i',a['vectors'],b[3:6])/den;de=np.einsum('ij,j->i',a['vectors'],b[6:9])/den
            rows=np.clip(fibers//4,0,3);cols=np.clip(fibers%4,0,3);margin=np.minimum(meta['glass']/2-abs(dn-(rows-1.5)*meta['pitch']),meta['glass']/2-abs(de-(cols-1.5)*meta['pitch']))
            allowed=(fibers>=0)&a['visible'][d]&(margin>.03);assignment={}
            for f in range(16):
                ids=np.flatnonzero(allowed&(fibers==f)&(a['values'][d,p]>0))
                if len(ids):assignment[str(f)]=int(ids[np.argmax(a['values'][d,p,ids])])
            if not assignment:continue
            idx=np.array(list(assignment.values()));cells,coef=matrix.coefficients(start,duration,idx);assert (profile['support'][cells]>0).all()
            qlo=coef@profile['lower'][cells];qhi=coef@profile['upper'][cells]
            quality_error=max(quality_error,float(np.max(abs(qlo-a['qlo'][d,idx]))),float(np.max(abs(qhi-a['qhi'][d,idx]))));assert quality_error<1e-8
            action_assign={};entries={};now=parse(stamp(start));stop=parse(stamp(end));overlaps=matrix.overlaps(start,duration)
            for j,(f,i) in enumerate(assignment.items()):
                assert clear.clear(i,overlaps)
                hit=grid.classify_target(model.ra[i],model.dec[i],now,*center,model.latitude,model.longitude);assert hit.region=='glass' and hit.fiber_id==int(f)
                assert min_altitude_during(model.ra[i],model.dec[i],now,stop,{'site':initial['site']})>=model.minimum_altitude-1e-8
                tid=model.ids[i];action_assign[f]=tid;checks+=1
                entries[tid]={'factor_lower':float(a['flo'][d,i]),'factor_upper':float(a['fhi'][d,i]),'score_lower':float(a['slo'][d,p,i]),'score_upper':float(a['shi'][d,p,i])}
            rc=sum(float(a['values'][d,p,i]) for i in idx)-float(a['time_cost'][d]);price_error=max(price_error,abs(rc-candidate['reduced_profit_before_margin_refine']));assert price_error<1e-7
            key=(start,end,program,tuple(sorted(action_assign.items())))
            if rc<=1e-7 or key in seen:continue
            seen.add(key);found.append({'kind':'fresh-best-GPU-joint-priced','start':start,'end':end,'entries':entries,'reduced_profit':rc,
                       'action':{'action':'observe','pointing':{'alt_deg':float(center[0]),'az_deg':float(center[1])},'duration_seconds':duration,'program':program,'assignments':action_assign},
                       'minimum_margin_deg':float(margin[idx].min()),'case':case['case']})
    found.sort(key=lambda c:c['reduced_profit'],reverse=True)
    result={'columns':found[:120],'conditional_scope':meta['hypotheses'],'official_checks':checks,'quality_maxerror':quality_error,'refined_pricing_maxerror':price_error,
            'positive_unique':len(found),'retained':min(120,len(found)),'GPU_top_sha256':sha(directory/'gpu_top.json'),'elapsed_seconds':time.perf_counter()-began}
    dump(out,result);print(json.dumps({k:v for k,v in result.items() if k!='columns'},indent=2),flush=True)


def gate(directory,out):
    root=root_setup();directory=Path(directory);out=Path(out);out.mkdir(parents=True,exist_ok=True);began=time.perf_counter()
    base,summary,serialized,columns,model,initial,matrix,profile,messages,clear=context(root)
    from season_science_required_master import solve_master,settle
    from season_column_dual_audit import lp_duals
    from required_opportunity_model import stamp
    batch=read(directory/'refined_columns.json');times=set(serialized['time_nodes']);reports=serialized['admissibility']['fixed_report_times']
    for c in batch['columns']:
        assert c['start'] in times and c['end'] in times and not any(c['start']<t<c['end'] for t in reports)
    full=columns+batch['columns'];hist=[j for j,c in enumerate(columns) if c['kind']=='historical'];baseline=settle(full,hist,model,serialized['requests'],100.)
    mip,stats=solve_master(full,model,serialized['requests'],[],'lower',90);assert mip.x is not None
    selected=[j for j in range(len(full)) if mip.x[j]>.5];primal=settle(full,selected,model,serialized['requests'],100.)
    ordered=sorted(selected,key=lambda j:full[j]['start']);assert all(full[a]['end']<=full[b]['start'] for a,b in zip(ordered,ordered[1:]))
    oldlp,_,oldstats=lp_duals(columns,model,serialized['requests'],[]);newlp,_,newstats=lp_duals(full,model,serialized['requests'],[])
    tolerance=2*summary['baseline_rounding_error_bound'];keep=primal['total_conditional_conservative']<=baseline['total_conditional_conservative']+tolerance
    result={'baseline_official_total':summary['baseline_official_total'],'baseline':baseline,'conditional_primal':primal,
            'conditional_net_change':primal['total_conditional_conservative']-baseline['total_conditional_conservative'],
            'source_columns':len(columns),'new_columns':len(batch['columns']),'new_selected_indices':[j-len(columns) for j in selected if j>=len(columns)],
            'finite_optimistic_LP_change':oldlp.fun-newlp.fun,'old_finite_optimistic_LP':-oldlp.fun-24900,'new_finite_optimistic_LP':-newlp.fun-24900,
            'mip_status':int(mip.status),'mip_gap':float(getattr(mip,'mip_gap',math.inf)),'mip_stats':stats,'incumbent_kept':keep,
            'uniformity_in_MIP_objective':False,'uniformity_recomputed':True,'rounding_comparison_tolerance':tolerance,
            'old_dual_audit':oldstats,'new_dual_audit':newstats,'new_official_score':False,'global_optimality_certificate':False,'elapsed_seconds':time.perf_counter()-began}
    dump(out/'gate.json',result)
    if keep:selected=hist
    schedule=[{'start_utc':stamp(full[j]['start']),'end_utc':stamp(full[j]['end']),'kind':full[j]['kind'],'action':full[j]['action']} for j in selected]
    schedule += [{'start_utc':stamp(t),'end_utc':stamp(t),'kind':'fixed-report','action':{'action':'report'}} for t in reports]
    dump(out/'retained_schedule.json',sorted(schedule,key=lambda c:(c['start_utc'],c['kind'])))
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prepare');parser.add_argument('--gpu');parser.add_argument('--refine');parser.add_argument('--gate');parser.add_argument('--out');args=parser.parse_args()
    if args.prepare:prepare(args.prepare)
    elif args.gpu:
        from actual_joint_gpu_pricing import gpu
        gpu(args.gpu,args.out,.03)
    elif args.refine:refine(args.refine,args.out)
    elif args.gate:gate(args.gate,args.out)
