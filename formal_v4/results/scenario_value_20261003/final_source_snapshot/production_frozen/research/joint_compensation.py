"""Alternating mandatory compensation columns on frozen latest-alpha evidence.

Finite conditional exchange model; independent research, not a submission.
"""
from __future__ import annotations
import argparse,hashlib,json,math,os,shutil,sys,time
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
import numpy as np
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,indent=2,allow_nan=False,default=lambda v:v.item() if isinstance(v,np.generic) else v.tolist())+'\n')
def setup():
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'formal_v4/upstream/gosim-observer-examples/runner'));return root


def forced_candidates(directory,targets,model):
    """Force the designated target in its fiber; exact max in other fibers.

    Ranking is a construction heuristic, not a reduced-cost certificate.
    """
    from interval_column_pricing import fiber_indices,basis
    from spatial_candidates import _shift_altaz
    directory=Path(directory);meta=read(directory/'metadata.json');found={t:[] for t in targets};seen=set()
    for case in meta['cases']:
        packed=np.load(directory/case['file'])
        a={key:packed[key] for key in packed.files};packed.close();start=case['start']
        for tid in targets:
            i=model.index[tid];vec=a['vectors'][i];alt=math.degrees(math.asin(vec[2]));az=math.degrees(math.atan2(vec[1],vec[0]))%360
            for row in range(4):
                for col in range(4):
                    center=_shift_altaz(alt,az,-(row-1.5)*meta['pitch'],-(col-1.5)*meta['pitch'])
                    fibers=fiber_indices(a['vectors'],center,meta['glass']-.060001,meta['pitch'],4)
                    if fibers[i]<0:continue
                    for d in np.flatnonzero(a['visible'][:,i]&(a['flo'][:,i]>=.5)):
                        allowed=(fibers>=0)&a['visible'][d];assignment={str(int(fibers[i])):i}
                        for f in range(16):
                            if f==fibers[i]:continue
                            ids=np.flatnonzero(allowed&(fibers==f)&(a['values'][d,0]>0))
                            if len(ids):assignment[str(f)]=int(ids[np.argmax(a['values'][d,0,ids])])
                        action_assign={f:model.ids[j] for f,j in assignment.items()};end=float(a['ends'][d]);key=(start,end,tuple(sorted(action_assign.items())))
                        if key in seen:continue
                        seen.add(key);entries={}
                        for j in assignment.values():entries[model.ids[j]]={'score_lower':float(a['slo'][d,0,j]),'score_upper':float(a['shi'][d,0,j]),'factor_lower':float(a['flo'][d,j]),'factor_upper':float(a['fhi'][d,j])}
                        found[tid].append({'kind':'forced-compensation','start':start,'end':end,'entries':entries,'anchor':tid,
                            'action':{'action':'observe','pointing':{'alt_deg':float(center[0]),'az_deg':float(center[1])},'duration_seconds':int(a['durations'][d]),'program':'DARK','assignments':action_assign},
                            'constructed_from_case':case['case']})
    return found


def official_check(c,model,initial,matrix,clear,glass,pitch):
    from challenge.v4_fiber_map import FiberGrid,min_altitude_during
    from required_opportunity_model import stamp,parse
    grid=FiberGrid(glass**2,pitch-glass,16);now=parse(stamp(c['start']));end=parse(stamp(c['end']));point=c['action']['pointing'];n=0
    for f,t in c['action']['assignments'].items():
        i=model.index[t];hit=grid.classify_target(model.ra[i],model.dec[i],now,point['alt_deg'],point['az_deg'],model.latitude,model.longitude)
        assert hit.region=='glass' and hit.fiber_id==int(f)
        assert min_altitude_during(model.ra[i],model.dec[i],now,end,{'site':initial['site']})>=model.minimum_altitude-1e-8
        assert clear.clear(i,matrix.overlaps(c['start'],c['end']-c['start']));n+=1
    return n


def select_forced(directory,targets,base_columns,model,requests,initial,matrix,clear,limit=6):
    from season_science_required_master import settle
    meta=read(Path(directory)/'metadata.json');allc=forced_candidates(directory,targets,model)
    hist=[j for j,c in enumerate(base_columns) if c['kind']=='historical'];baseline=settle(base_columns,hist,model,requests,100.);selected=[];rankings={};checks=0;cache={};mandatory=set(model.actual_required)
    for tid,candidates in allc.items():
        ranked=[]
        for c in candidates:
            pair=(c['start'],c['end'])
            if pair not in cache:
                drop={j for j in hist if base_columns[j]['start']<c['end'] and base_columns[j]['end']>c['start']};survivors=[j for j in hist if j not in drop]
                settled=settle(base_columns,survivors,model,requests,100.);scores={};observed=set()
                for j in survivors:
                    for t,e in base_columns[j]['entries'].items():
                        scores[t]=max(scores.get(t,0.),e['score_lower'])
                        if e['factor_lower']>=.5:observed.add(t)
                cache[pair]=(drop,survivors,settled,scores,observed)
            drop,survivors,settled,scores,observed=cache[pair]
            # A cheap construction ranking: exact survivor settlement plus
            # marginal science/mandatory; REQ and Jain settled exactly on the
            # retained candidates and in the full integer master.
            estimate=settled['total_conditional_conservative']+sum(max(0,e['score_lower']-scores.get(t,0.)) for t,e in c['entries'].items())
            estimate+=50*sum(t in mandatory and t not in observed and e['factor_lower']>=.5 for t,e in c['entries'].items())
            ranked.append((estimate-baseline['total_conditional_conservative'],c,drop))
        ranked.sort(key=lambda z:z[0],reverse=True);used=set();kept=[]
        for estimate,c,drop in ranked:
            signature=(c['start'],c['end'],tuple(sorted(c['action']['assignments'].items())))
            if signature in used:continue
            checks+=official_check(c,model,initial,matrix,clear,meta['glass'],meta['pitch']);used.add(signature);selected.append(c)
            score=settle(base_columns+[c],cache[(c['start'],c['end'])][1]+[len(base_columns)],model,requests,100.)
            delta=score['total_conditional_conservative']-baseline['total_conditional_conservative']
            kept.append({'delta':delta,'historical_dropped':len(drop),'blocking_required':sorted(set(score['missing_ids'])-set(baseline['missing_ids'])),
                         'completion_target':tid,'start':c['start'],'end':c['end']})
            if len(kept)>=limit:break
        rankings[tid]={'constructed':len(candidates),'official_retained':len(kept),'witnesses':kept}
    return selected,rankings,checks


def solve(pool,model,requests,historical,forced=None):
    from season_science_required_master import solve_master,settle
    mip,stats=solve_master(pool,model,requests,forced or [],'lower',45)
    assert mip.x is not None
    selected=[j for j in range(len(pool)) if mip.x[j]>.5];ordered=sorted(selected,key=lambda j:pool[j]['start'])
    assert all(pool[a]['end']<=pool[b]['start'] for a,b in zip(ordered,ordered[1:]))
    return settle(pool,selected,model,requests,100.),selected,{'status':int(mip.status),'gap':float(mip.mip_gap),'stats':stats}


def initial(out):
    root=setup();out=Path(out);out.mkdir(parents=True,exist_ok=True);began=time.perf_counter()
    from best_alpha_joint_gpu_pricing import context
    base,s,ser,cols,model,ini,matrix,profile,msg,clear=context(root);src=root/'formal_v4/results/best_alpha_joint_gpu_pricing_20261003'
    previous=read(src/'refined_columns.json')['columns'];cols=cols+previous;missing=s['baseline_reconstructed']['missing_ids'];hist=[j for j,c in enumerate(cols) if c['kind']=='historical']
    primary,rankings,checks=select_forced(src,missing,cols,model,ser['requests'],ini,matrix,clear)
    assert all(rankings[t]['official_retained']>=3 for t in missing),'insufficient forced completion candidates'
    pool=cols+primary;traces=[];blockers=set();offset=len(cols)
    for tid in missing:
        candidates=[offset+j for j,c in enumerate(primary) if c['anchor']==tid];best=None
        for index in candidates[:3]:
            score,selected,stats=solve(pool,model,ser['requests'],hist,[index]);result={'target':tid,'forced_column':index,'score':score,'selected_new_indices':[j-offset for j in selected if j>=offset],'mip':stats}
            if best is None or score['total_conditional_conservative']>best['score']['total_conditional_conservative']:best=result
        traces.append(best);blockers.update(set(best['score']['missing_ids'])-set(missing))
    baseline=s['baseline_reconstructed'];free,sel,stats=solve(pool,model,ser['requests'],hist)
    dump(out/'initial_pool.json',pool);dump(out/'primary_forced_rankings.json',rankings)
    report={'baseline_official_total':s['baseline_official_total'],'baseline':baseline,'primary_forced_columns':len(primary),'official_checks':checks,
            'forced_branch_traces':traces,'blocking_set':sorted(blockers),'free_pool_result':free,'free_mip':stats,'free_new_selected':[j-offset for j in sel if j>=offset],
            'elapsed_seconds':time.perf_counter()-began,'fresh_pool_sha256':sha(base/'column_pool.json'),'source_previous_npz_metadata_sha256':sha(src/'metadata.json')}
    dump(out/'initial_exchange.json',report);print(json.dumps({k:v for k,v in report.items() if k not in ('forced_branch_traces','baseline')},indent=2),flush=True)


def prepare(out):
    root=setup();out=Path(out);began=time.perf_counter()
    from best_alpha_joint_gpu_pricing import context
    from season_dual_stabilization import finite_primal,secondary_dual
    from actual_joint_gpu_pricing import clear_geometry
    from required_opportunity_model import parse,stamp
    from spatial_candidates import _shift_altaz
    base,s,ser,cols,model,ini,matrix,profile,msg,clear=context(root);pool=read(out/'initial_pool.json');exchange=read(out/'initial_exchange.json')
    wanted=sorted(set(exchange['blocking_set'])|set(s['baseline_reconstructed']['missing_ids']));indices=np.array([model.index[t] for t in wanted])
    call,primal,old,oldstats,tags=finite_primal(pool,model,ser['requests'],[])
    # Preserve critical compensation targets in the secondary objective; minimize
    # nu only for other historically completed targets on the same dual face.
    minimize=set(model.actual_required)-set(wanted);lam,mu,lower,upper,proof=secondary_dual(call,primal,tags,minimize,90)
    cm=np.minimum(mu,0.);cl=np.maximum(lower,0.);cu=np.minimum(upper,0.);res=call['c']-call['A_eq'].T@lam-call['A_ub'].T@cm-cl-cu
    obj=math.fsum(float(a)*float(b) for a,b in zip(call['b_eq'],lam))+math.fsum(float(a)*float(b) for a,b in zip(call['b_ub'],cm))
    obj+=math.fsum(float(l)*cl[j] for j,(l,u) in enumerate(call['bounds']) if l is not None)+math.fsum(float(u)*cu[j] for j,(l,u) in enumerate(call['bounds']) if u is not None)
    complementarity=max(float(np.max(abs(cm*(np.asarray(call['b_ub'])-call['A_ub']@primal.x)))),
          max((abs(cl[j]*(primal.x[j]-l)) for j,(l,u) in enumerate(call['bounds']) if l is not None),default=0.),
          max((abs(cu[j]*(u-primal.x[j])) for j,(l,u) in enumerate(call['bounds']) if u is not None),default=0.))
    proof.update(cleanup_l1=float(abs(cm-mu).sum()+abs(cl-lower).sum()+abs(cu-upper).sum()),cleanup_stationarity=float(max(abs(res))),cleanup_objective_error=abs(obj-primal.fun),cleanup_complementarity=complementarity)
    assert max(abs(res))<1e-7 and abs(obj-primal.fun)<1e-6 and complementarity<1e-6
    rho={};nu={};eta={}
    for tag,val in zip(tags,-cm):
        if tag[0]=='winner_simplex':rho[tag[1]]=float(val)
        elif tag[0]=='required':nu[tag[1]]=float(val)
        elif tag[0]=='request_target':eta[tag[1],tag[2]]=float(val)
    times=np.array(sorted(set(c['start'] for c in pool)|set(c['end'] for c in pool)));assert times.tolist()==ser['time_nodes']
    dump(out/'fresh_repricing_dual_proof.json',proof)
    dual={'target_order':model.ids,'rho':[rho.get(t,0.) for t in model.ids],'required_nu':[nu.get(t,0.) for t in model.ids],
          'request_eta':[[eta.get((r,t),0.) for t in model.ids] for r in range(len(ser['requests']))],'time_nodes':times.tolist(),'time_potential':lam.tolist(),
          'requests':ser['requests'],'admissibility':ser['admissibility']};dump(out/'compensation_duals.json',dual)
    support=profile['support'];lo=profile['lower'];hi=profile['upper'];reports=np.array(ser['admissibility']['fixed_report_times']);pairs={};rank={t:[] for t in wanted}
    for j,start in enumerate(times):
        night=int(np.searchsorted(matrix.night_ends,start,side='right'))
        if night>=len(model.nights) or start<model.nights[night][0]:continue
        for k in range(j+1,min(len(times),np.searchsorted(times,min(start+3600,model.nights[night][1]),side='right'))):
            duration=times[k]-start
            if not 60<=duration<=3600 or abs(duration-round(duration))>1e-7 or any(start<t<times[k] for t in reports):continue
            a=np.searchsorted(matrix.starts,start,side='right')-1;z=np.searchsorted(matrix.starts,times[k]-1e-6,side='right')
            if a<0 or z<=a or np.any(support[a:z]<=0) or not np.isfinite(lo[a:z]).all() or np.any(hi[a:z]-lo[a:z]>1e-4) or matrix.ends[z-1]<times[k]-1e-7:continue
            pairs.setdefault(j,[]).append((k,int(duration)));cells,coef=matrix.coefficients(start,duration,indices);f=np.minimum(1,model.flux[indices]*duration/model.f0t0*(coef@lo[cells]))
            for x,i in enumerate(indices):
                if f[x]>=.5:rank[model.ids[i]].append((float(lam[k]-lam[j]),int(duration),j,k,night))
    selected=[];covered={};missing_windows=[]
    for tid in wanted:
        choices=sorted(rank[tid]);i=model.index[tid]
        for cost,duration,j,k,night in choices:
            if not clear.clear(i,matrix.overlaps(times[j],duration)):continue
            if np.min(model._alt([times[j],times[k],(times[j]+times[k])/2],[i]))<model.minimum_altitude+.04:continue
            if j not in selected:selected.append(j)
            covered[tid]=selected.index(j);break
        if tid not in covered:missing_windows.append(tid)
        if len(selected)>=8:break
    # Each wanted target has a visible conditional window before selecting a
    # bounded case pool; selection cap is reported, never treated as coverage.
    selected=selected[:8];rows=np.array(dual['rho']);nv=np.array(dual['required_nu']);ev=np.array(dual['request_eta']);rng=np.random.default_rng(2026100304)
    weight_column=model.initial['targets']['columns'].index('science_weight')
    weights=np.array([float(r[weight_column]) for r in model.initial['targets']['rows']]);glass=math.sqrt(ini['instrument']['fiber_area_deg2']);pitch=glass+ini['instrument']['gap_deg'];cases=[]
    for case,j in enumerate(selected):
        start=float(times[j]);chosen=sorted(pairs[j],key=lambda v:(v[1],lam[v[0]]-lam[j]))[:12];chosen.sort(key=lambda x:x[1])
        durations=np.array([d for k,d in chosen]);ends=np.array([times[k] for k,d in chosen]);qlo=[];qhi=[]
        for d in durations:
            cells,coef=matrix.coefficients(start,int(d),np.arange(len(model.ids)));qlo.append(coef@lo[cells]);qhi.append(coef@hi[cells])
        qlo=np.array(qlo);qhi=np.array(qhi);flo=np.minimum(1,model.flux[None,:]*durations[:,None]/model.f0t0*qlo);fhi=np.minimum(1,model.flux[None,:]*durations[:,None]/model.f0t0*qhi)
        mult=np.array([model.score['program']['multipliers'][p] for p in ('DARK','BRIGHT','BACKUP')]);mis=model.score['program']['mismatch_multiplier']
        shi=weights[None,None,:]*fhi[:,None,:]*np.maximum(mult,mis)[None,:,None];slo=weights[None,None,:]*flo[:,None,:]*np.minimum(mult,mis)[None,:,None]
        slo[:,0,:]=weights[None,:]*flo*np.where(qlo>=model.score['program']['bands']['DARK'],mult[0],mis)
        values=np.maximum(0,shi-rows[None,None,:])+nv[None,None,:]*(fhi[:,None,:]>=.5)
        for r,req in enumerate(ser['requests']):values+=((start>=parse(req['issued_at_utc']).timestamp())&(ends<=parse(req['deadline_utc']).timestamp()))[:,None,None]*ev[r,None,None,:]*(fhi[:,None,:]>=req['completion_factor_threshold'])
        altaz,visible=clear_geometry(model,start,durations,msg);eligible=np.flatnonzero(visible.any(axis=0));centers=altaz[rng.choice(eligible,32768)]+rng.uniform(-.4,.4,(32768,2));centers[:,0]=np.clip(centers[:,0],model.minimum_altitude,89.9);centers[:,1]%=360;seeds=[]
        for i in indices:
            if visible[:,i].any():
                for r in range(4):
                    for c in range(4):seeds.append(_shift_altaz(*altaz[i],-(r-1.5)*pitch,-(c-1.5)*pitch))
        centers[:len(seeds)]=seeds;a,z=altaz.T*math.pi/180;vec=np.column_stack((np.cos(a)*np.cos(z),np.cos(a)*np.sin(z),np.sin(a)))
        file=out/f'case_{case}.npz';np.savez_compressed(file,vectors=vec,centers=centers,values=values,visible=visible,durations=durations,ends=ends,time_cost=lam[[k for k,d in chosen]]-lam[j],qlo=qlo,qhi=qhi,flo=flo,fhi=fhi,slo=slo,shi=shi)
        cases.append({'case':case,'start':start,'start_utc':stamp(start),'file':file.name,'sha256':sha(file),'D':len(durations),
                      'actual_visible_completable_targets':[model.ids[i] for i in indices if np.any(visible[:,i]&(flo[:,i]>=.5))]})
    assert cases
    for f in ('interval_column_pricing.py','actual_joint_gpu_pricing.py'):shutil.copyfile(root/'formal_v4/research'/f,out/f)
    shutil.copyfile(__file__,out/Path(__file__).name)
    metadata={'cases':cases,'glass':glass,'pitch':pitch,'nfib':16,'programs':['DARK','BRIGHT','BACKUP'],'pricing_source_sha256':sha(out/'interval_column_pricing.py'),
              'hypotheses':'frozen latest Phase alpha report/repair; narrow conditional profile; zerooffset; reference directional bounds; .03 margin; finite existing nodes',
              'wanted_targets':wanted,'covered_selected_start':covered,'no_supported_clear_pair':missing_windows,'unprocessed_at_case_cap':[t for t in wanted if t not in covered and t not in missing_windows],
              'profile_sha256':sha(base/'conditional_profile_new_repair_cells.npz'),'dual_sha256':sha(out/'compensation_duals.json'),
              'source_pool_sha256':sha(out/'initial_pool.json'),'prepare_seconds':time.perf_counter()-began}
    dump(out/'metadata.json',metadata);print(json.dumps(metadata,indent=2),flush=True)


def finish(directory):
    root=setup();out=Path(directory);began=time.perf_counter()
    from best_alpha_joint_gpu_pricing import context,refine
    from season_science_required_master import settle
    from season_column_dual_audit import lp_duals
    from required_opportunity_model import stamp
    base,s,ser,cols,model,ini,matrix,profile,msg,clear=context(root);pool=read(out/'initial_pool.json');meta=read(out/'metadata.json')
    refined=out/'gpu_refined_columns.json'
    if refined.exists():assert read(refined)['GPU_top_sha256']==sha(out/'gpu_top.json')
    else:refine(out,refined)
    gpu=read(refined)['columns']
    prechecked=out/'compensation_prechecked.json'
    if prechecked.exists():
        cached=read(prechecked)
        assert cached['input_metadata_sha256']==sha(out/'metadata.json') and cached['input_pool_sha256']==sha(out/'initial_pool.json')
        forced,ranks,checks=cached['columns'],cached['rankings'],cached['official_checks']
    else:forced,ranks,checks=select_forced(out,meta['wanted_targets'],pool,model,ser['requests'],ini,matrix,clear,limit=4)
    full=pool+gpu+forced;hist=[j for j,c in enumerate(pool) if c['kind']=='historical'];baseline=settle(full,hist,model,ser['requests'],100.)
    primal,selected,mipstats=solve(full,model,ser['requests'],hist);oldlp,_,oldstats=lp_duals(pool,model,ser['requests'],[]);newlp,_,newstats=lp_duals(full,model,ser['requests'],[])
    gain=primal['total_conditional_conservative']-baseline['total_conditional_conservative'];keep=gain<=2*s['baseline_rounding_error_bound']
    report={'status':'READY_CONDITIONAL_RESEARCH','baseline_official_total':s['baseline_official_total'],'baseline':baseline,'conditional_primal':primal,'conditional_net_gain':gain,
            'initial_pool':len(pool),'GPU_refined_columns':len(gpu),'forced_compensation_columns':len(forced),'compensation_official_checks':checks,
            'finite_LP_gain':oldlp.fun-newlp.fun,'selected_new_indices':[j-len(pool) for j in selected if j>=len(pool)],'mip':mipstats,
            'old_dual_audit':oldstats,'new_dual_audit':newstats,'incumbent_kept':keep,'actual_Jain_after_solve':True,'Jain_in_MIP_objective':False,
            'new_official_score':False,'global_certificate':False,'finish_seconds':time.perf_counter()-began,
            'stop_reason':'One explicit blocking-set expansion completed; no further enumeration in this bounded study'}
    dump(out/'compensation_forced_rankings.json',ranks);dump(out/'final_pool.json',full);dump(out/'result.json',report)
    if keep:selected=hist
    schedule=[{'start_utc':stamp(full[j]['start']),'end_utc':stamp(full[j]['end']),'kind':full[j]['kind'],'action':full[j]['action']} for j in selected]
    schedule += [{'start_utc':stamp(t),'end_utc':stamp(t),'kind':'fixed-report','action':{'action':'report'}} for t in ser['admissibility']['fixed_report_times']]
    dump(out/'retained_schedule.json',sorted(schedule,key=lambda x:(x['start_utc'],x['kind'])));print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--initial');p.add_argument('--prepare');p.add_argument('--gpu');p.add_argument('--finish');p.add_argument('--out');args=p.parse_args()
    if args.initial:initial(args.initial)
    elif args.prepare:prepare(args.prepare)
    elif args.gpu:
        from actual_joint_gpu_pricing import gpu
        gpu(args.gpu,args.out,.03)
    elif args.finish:finish(args.finish)
