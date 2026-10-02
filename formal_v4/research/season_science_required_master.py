"""Restricted full-season science-max/required/REQ flow master, CPU research.

All historical columns remain available. New columns use conditional interval
bounds and conservative shared background fibres. Report times stay fixed.
For data-loss cards the entire original pre-trigger prefix is fixed, preserving
the public observed action-count/rank invalidation window exactly.
"""
from __future__ import annotations
import csv,hashlib,json,math,os,sys,time
from collections import defaultdict
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('MKL_NUM_THREADS','1')
import numpy as np
from scipy.optimize import milp,linprog,Bounds,LinearConstraint
from scipy.sparse import coo_matrix
from quality_profile_inversion import all_target_model,PublicQualityMatrix,ReferenceClearFilter
from required_opportunity_model import parse,stamp
from request_remote_owned_gate import initial_public
from spatial_candidates import SpatialPlanner,local_sidereal,DEG,SIDEREAL_SPEED


def solve_master(columns,model,requests,fixed,mode,seconds=90):
    ncol=len(columns);times=sorted(set([c['start'] for c in columns]+[c['end'] for c in columns]));nodes={t:j for j,t in enumerate(times)}
    arcs=[(nodes[c['start']],nodes[c['end']]) for c in columns]+[(j,j+1) for j in range(len(times)-1)]
    na=len(arcs);objective=[0.]*na;varlo=[0.]*na;varhi=[1.]*na;integer=[1]*ncol+[0]*(na-ncol)
    rr=[];cc=[];vv=[];clo=[];chi=[]
    def row(items,low,high):
        r=len(clo);clo.append(low);chi.append(high)
        for c,v in items:rr.append(r);cc.append(c);vv.append(v)
    def variable(cost,binary=False):
        j=len(objective);objective.append(-cost);varlo.append(0.);varhi.append(1.);integer.append(int(binary));return j
    nodeflow=defaultdict(list)
    for j,(a,b) in enumerate(arcs):nodeflow[a].append((j,1));nodeflow[b].append((j,-1))
    for t in range(len(times)):row(nodeflow[t],1 if t==0 else -1 if t==len(times)-1 else 0,1 if t==0 else -1 if t==len(times)-1 else 0)
    winners=defaultdict(list);completion=defaultdict(list);req_completions=defaultdict(list)
    for c,col in enumerate(columns):
        for tid,entry in col['entries'].items():
            score=entry['score_upper' if mode=='upper' else 'score_lower'];factor=entry['factor_upper' if mode=='upper' else 'factor_lower']
            if score>0:
                z=variable(score);row([(z,1),(c,-1)],-np.inf,0);winners[tid].append((z,1))
            if factor>=.5:completion[tid].append((c,-1))
            for r,request in enumerate(requests):
                if (tid in request['target_ids'] and col['start']>=parse(request['issued_at_utc']).timestamp()
                    and col['end']<=parse(request['deadline_utc']).timestamp()
                    and factor>=request['completion_factor_threshold']):req_completions[r,tid].append((c,-1))
    for items in winners.values():row(items,-np.inf,1)
    # Only actual mandatory targets get a 50-point reward; model has all targets
    # marked required internally solely to reuse the public geometry matrix API.
    required=model.actual_required
    for tid in required:
        b=variable(50,True);row([(b,1)]+completion[tid],-np.inf,0)
    for r,request in enumerate(requests):
        distinct=[]
        for tid in request['target_ids']:
            u=variable(0,True);row([(u,1)]+req_completions[r,tid],-np.inf,0);distinct.append((u,-1))
        h=variable(request['completion_reward'],True);row([(h,request['minimum_completed'])]+distinct,-np.inf,0)
    for c in fixed:varlo[c]=varhi[c]=1
    A=coo_matrix((vv,(rr,cc)),shape=(len(clo),len(objective))).tocsr();clo=np.array(clo);chi=np.array(chi)
    start=time.perf_counter()
    if mode=='upper':
        eq=np.isfinite(clo)&np.isfinite(chi)&(clo==chi);ub=np.isfinite(chi)&~eq
        result=linprog(objective,A_ub=A[ub],b_ub=chi[ub],A_eq=A[eq],b_eq=chi[eq],bounds=list(zip(varlo,varhi)),method='highs',options={'time_limit':seconds})
    else:
        result=milp(objective,integrality=integer,bounds=Bounds(varlo,varhi),constraints=LinearConstraint(A,clo,chi),options={'time_limit':seconds,'mip_rel_gap':1e-7})
    return result,{'variables':len(objective),'rows':len(clo),'nonzeros':A.nnz,'time_nodes':len(times),'seconds':time.perf_counter()-start,'mode':mode}


def settle(columns,selected,model,requests,report_value):
    score=defaultdict(float);factor=defaultdict(float);rq=[defaultdict(float) for r in requests]
    request_windows=[(parse(r['issued_at_utc']).timestamp(),parse(r['deadline_utc']).timestamp()) for r in requests]
    for c in selected:
        col=columns[c]
        eligible_requests=[r for r,(a,b) in enumerate(request_windows) if col['start']>=a and col['end']<=b]
        for tid,e in col['entries'].items():
            score[tid]=max(score[tid],e['score_lower']);factor[tid]=max(factor[tid],e['factor_lower'])
            for r in eligible_requests:rq[r][tid]=max(rq[r][tid],e['factor_lower'])
    missing=[tid for tid in model.actual_required if factor[tid]<.5]
    rewards=[request['completion_reward'] if sum(rq[r][tid]>=request['completion_factor_threshold'] for tid in request['target_ids'])>=request['minimum_completed'] else 0 for r,request in enumerate(requests)]
    band_total=defaultdict(int);band_completed=defaultdict(int)
    for i,tid in enumerate(model.ids):
        band=int(model.ra[i]//10);band_total[band]+=1;band_completed[band]+=factor[tid]>=.5
    ratios=[band_completed[b]/n for b,n in band_total.items()];squares=sum(v*v for v in ratios)
    uniform=200*(1-sum(ratios)**2/(len(ratios)*squares)) if squares else 200.
    science=sum(score.values());total=science-50*len(missing)+sum(rewards)+report_value-uniform
    return {'total_conditional_conservative':total,'science':science,'required_missing':len(missing),'missing_ids':missing,
            'request_rewards':rewards,'report_fixed':report_value,'uniformity_penalty':uniform,'observe_columns':len(selected)}


def card_master(root,card):
    started=time.perf_counter();directory=root/'formal_v4/results'/f'cloud_cd2_{card}_20261003';base=root/'formal_v4/practice_cards'/card/card
    initial,_=initial_public(base);model=all_target_model(base);model.actual_required=[row['target_id'] for row in csv.DictReader((base/'public/targets.csv').open()) if row['required'].lower()=='true']
    planner=SpatialPlanner(initial);profile_path=root/'formal_v4/research'/f'quality_profile_{card}_result.npz';profile=np.load(profile_path)
    messages=[json.loads(l) for l in (directory/'messages.jsonl').read_text().splitlines()];report=json.loads((directory/'score_report.json').read_text())
    decisions=[d for d in csv.DictReader((directory/'decisions.csv').open())];historical=[d for d in decisions if d['action']=='observe']
    actions=[json.loads(l) for l in (directory/'actions.jsonl').read_text().splitlines()];observe_actions=[a for a in actions if a['action']=='observe']
    report_times=[parse(d['start_utc']).timestamp() for d in decisions if d['action']=='report']
    meta=json.loads(profile_path.with_suffix('.json').read_text());matrix=PublicQualityMatrix(model,[parse(t).timestamp() for t in meta['repair_timestamps_utc']]);clear=ReferenceClearFilter(model,messages)
    assert np.allclose(matrix.starts,profile['cell_start'])
    reqs=[m for m in messages if m['record_type']=='observation_request'];hits=defaultdict(list)
    for e in csv.DictReader((directory/'observations.csv').open()):hits[int(e['observe_index'])].append(e)
    columns=[]
    for j,(d,action) in enumerate(zip(historical,observe_actions)):
        entries={e['target_id']:{'score_lower':float(e['score']),'score_upper':float(e['score'])+0.0000005,
                               'factor_lower':float(e['factor']),'factor_upper':float(e['factor'])+0.0000005}
                 for e in hits[j] if e['valid']=='true'}
        columns.append({'kind':'historical','old_observe_index':j,'start':parse(d['start_utc']).timestamp(),'end':parse(d['end_utc']).timestamp(),'action':action,'entries':entries})
    old_count=len(columns);baseline_score=settle(columns,list(range(old_count)),model,reqs,report['components']['report_settlement'])
    assert baseline_score['required_missing']==report['counts']['required_missing']
    assert abs(baseline_score['total_conditional_conservative']-report['total'])<.0000005*len(model.ids)+1e-5
    fixed=[];prefix_end=None;validity_evidence=[]
    for m in messages:
        if m['record_type']=='state_resync':
            n=m['invalidated_window']['action_count_at_trigger'];fixed.extend(range(n));prefix_end=max(prefix_end or 0,parse(m['issued_at_utc']).timestamp())
            validity_evidence.append({'issued_at_utc':m['issued_at_utc'],'public_message':m['invalidated_window'],
                                     'constraint':'all original first N observe columns fixed; all new columns starting before resync decision excluded'})
    pilot=json.loads((root/'formal_v4/results/required_quality_interval_20261003/flow_pilot.json').read_text())
    # Regenerate the pilot pool, rather than only its jointly selected columns,
    # from saved target coupons and exact known pointing/fibre cell centres.
    audit=json.loads((root/'formal_v4/results/required_quality_interval_20261003/audit.json').read_text())
    from spatial_candidates import _shift_altaz
    from terrain_version_space import altaz_at
    from challenge.v4_fiber_map import FiberGrid
    grid=FiberGrid(planner.glass**2,planner.pitch-planner.glass,planner.nfib)
    seen=set();new_geometry_checks=0
    for target in audit['cards'][card]['targets']:
        anchor=model.index[target['target_id']]
        for witness in target['top_conditional_coupons']:
            start=parse(witness['start_utc']).timestamp();duration=witness['duration_seconds'];end=start+duration
            if prefix_end is not None and start<prefix_end:continue
            if any(start<t<end for t in report_times):continue
            now=parse(stamp(start));lst=local_sidereal(now,planner.lon);alt,az,hour,vectors=planner._altaz(lst)
            up=(planner.hmax-hour)/SIDEREAL_SPEED
            for r in range(planner.side):
                for c in range(planner.side):
                    center=_shift_altaz(alt[anchor],az[anchor],-(r-(planner.side-1)/2)*planner.pitch,-(c-(planner.side-1)/2)*planner.pitch)
                    fiber,valid,margin=planner._classify(vectors,*center)
                    pool=np.flatnonzero(valid&(alt>=planner.min_alt+.04)&(up>=duration)&(margin>.03))
                    if anchor not in pool:continue
                    cells,coef=matrix.coefficients(start,duration,pool);qlo=coef@profile['lower'][cells];qhi=coef@profile['upper'][cells]
                    glo=np.minimum(1.,planner.flux[pool]*duration/planner.f0t0*qlo);ghi=np.minimum(1.,planner.flux[pool]*duration/planner.f0t0*qhi)
                    overlaps=matrix.overlaps(start,duration);good=np.array([clear.clear(int(i),overlaps) for i in pool])
                    eligible=np.flatnonzero(good);assignment={};entries={}
                    for f in np.unique(fiber[pool[eligible]]):
                        choices=eligible[fiber[pool[eligible]]==f]
                        anchor_choice=choices[pool[choices]==anchor]
                        if len(anchor_choice):j=int(anchor_choice[0])
                        else:
                            delta=planner.weight[pool[choices]]*glo[choices]*np.where(qlo[choices]>=planner.dark_threshold,1.2,1.)
                            j=int(choices[np.argmax(delta)])
                        i=int(pool[j]);tid=model.ids[i];assignment[str(int(f))]=tid
                        entries[tid]={'factor_lower':float(glo[j]),'factor_upper':float(ghi[j]),
                            'score_lower':float(planner.weight[i]*glo[j]*(1.2 if qlo[j]>=planner.dark_threshold else 1.)),
                            'score_upper':float(planner.weight[i]*ghi[j]*1.2)}
                        hit=grid.classify_target(planner.ra[i],planner.dec[i],now,*center,planner.lat,planner.lon)
                        assert hit.region=='glass' and hit.fiber_id==int(f);new_geometry_checks+=1
                    if target['target_id'] not in entries or entries[target['target_id']]['factor_lower']<.5:continue
                    key=(start,end,tuple(sorted(assignment.items())))
                    if key in seen:continue
                    seen.add(key);action={'action':'observe','pointing':{'alt_deg':center[0],'az_deg':center[1]},'duration_seconds':duration,'assignments':assignment,'program':'DARK'}
                    columns.append({'kind':'interval-new','start':start,'end':end,'action':action,'entries':entries,'anchor_required':target['target_id'],
                                    'minimum_fiber_margin_deg':float(np.min(margin[pool[eligible]]))})
    mip,stats=solve_master(columns,model,reqs,fixed,'lower',90)
    if mip.x is None:selected=list(range(old_count))
    else:selected=[c for c in range(len(columns)) if mip.x[c]>.5]
    score=settle(columns,selected,model,reqs,report['components']['report_settlement'])
    raw_solver_selected=selected
    retained_incumbent=score['total_conditional_conservative']<=baseline_score['total_conditional_conservative']+.0000005*len(model.ids)
    if retained_incumbent:selected=list(range(old_count));score=baseline_score
    lp,lpstats=solve_master(columns,model,reqs,fixed,'upper',90)
    marginal=[]
    for c in range(old_count,len(columns)):
        added=columns[c];dropped=[j for j in range(old_count) if columns[j]['start']<added['end'] and columns[j]['end']>added['start']]
        if any(j in fixed for j in dropped):continue
        chosen=[j for j in range(old_count) if j not in dropped]+[c]
        one=settle(columns,chosen,model,reqs,report['components']['report_settlement'])
        marginal.append({'column':c,'anchor_required':added['anchor_required'],'start_utc':stamp(added['start']),
                         'science_change':one['science']-baseline_score['science'],
                         'required_reward_change':50*(baseline_score['required_missing']-one['required_missing']),
                         'request_reward_change':sum(one['request_rewards'])-sum(baseline_score['request_rewards']),
                         'uniformity_change':baseline_score['uniformity_penalty']-one['uniformity_penalty'],
                         'conditional_total_change':one['total_conditional_conservative']-baseline_score['total_conditional_conservative'],
                         'historical_columns_replaced':len(dropped)})
    marginal.sort(key=lambda r:r['conditional_total_change'],reverse=True)
    original_selected={c for c in selected if c<old_count};new_selected=[c for c in selected if c>=old_count]
    ordered=sorted(selected,key=lambda c:columns[c]['start']);assert all(columns[a]['end']<=columns[b]['start'] for a,b in zip(ordered,ordered[1:]))
    destination=root/'formal_v4/results/season_science_required_master_20261003'/card;destination.mkdir(parents=True,exist_ok=True)
    schedule=[{'start_utc':stamp(columns[c]['start']),'end_utc':stamp(columns[c]['end']),'kind':columns[c]['kind'],
               'old_observe_index':columns[c].get('old_observe_index'),'action':columns[c]['action']} for c in ordered]
    # Report actions remain explicitly scheduled at their original zero-time times.
    schedule += [{'start_utc':stamp(t),'end_utc':stamp(t),'kind':'fixed-report','action':{'action':'report'}} for t in report_times]
    schedule.sort(key=lambda r:(r['start_utc'],r['kind']))
    (destination/'schedule.json').write_text(json.dumps(schedule,indent=2))
    constant=-50*len(model.actual_required)+report['components']['report_settlement']
    summary={'card':card,'scope':'full-season finite historical+conditional-new column master; fixed report/E and data-loss prefix; not official replay',
       'historical_columns':old_count,'new_columns':len(columns)-old_count,'baseline_reconstructed':baseline_score,'baseline_official_total':report['total'],
       'candidate_reconstructed':score,'conditional_total_difference':score['total_conditional_conservative']-baseline_score['total_conditional_conservative'],
       'new_selected':[{'column':c,'start_utc':stamp(columns[c]['start']),'end_utc':stamp(columns[c]['end']),'action':columns[c]['action'],
                        'anchor_required':columns[c]['anchor_required']} for c in new_selected],
       'incumbent_retained_on_score_tie':retained_incumbent,'raw_solver_observe_columns':len(raw_solver_selected),
       'best_single_column_counterfactuals':marginal[:10],
       'historical_dropped':[c for c in range(old_count) if c not in original_selected],
       'mip_status':mip.status,'mip_gap':getattr(mip,'mip_gap',None),'mip_stats':stats,
       'lower_surrogate_dual_upper_without_uniformity':None if getattr(mip,'mip_dual_bound',None) is None else -mip.mip_dual_bound+constant,
       'conditional_optimistic_finite_LP_upper_without_uniformity':None if lp.fun is None else -lp.fun+constant,'lp_status':lp.status,'lp_stats':lpstats,
       'omitted_column_global_bound_available':False,'fixed_report_times':[stamp(t) for t in report_times],
       'fixed_original_prefix_columns':len(set(fixed)),'validity_public_evidence':validity_evidence,
       'new_fiber_geometry_checks':new_geometry_checks,'new_pointing_assumption':'declared zero offset with >.03deg glass margin; not hidden-offset certificate',
       'CSV_science_rounding_error_bound':0.0000005*len(model.ids),'hidden_inputs_read':False,
       'profile_sha256':hashlib.sha256(profile_path.read_bytes()).hexdigest(),'elapsed_seconds':time.perf_counter()-started}
    (destination/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary),flush=True)
    (destination/'single_column_counterfactuals.json').write_text(json.dumps(marginal,indent=2))
    return summary


if __name__=='__main__':
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'formal_v4/upstream/gosim-observer-examples/runner'))
    for card in ('alpha','delta'):card_master(root,card)
