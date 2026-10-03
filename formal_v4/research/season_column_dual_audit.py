"""Isolated LP-dual/pricing audit; no edit to the frozen master or GPU calls."""
from __future__ import annotations
import csv,hashlib,json,os,sys,time
from collections import defaultdict
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('MKL_NUM_THREADS','1')
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
import season_science_required_master as frozen
from required_opportunity_model import parse,stamp
from quality_profile_inversion import PublicQualityMatrix,ReferenceClearFilter
from request_remote_owned_gate import initial_public
from spatial_candidates import SpatialPlanner,local_sidereal,SIDEREAL_SPEED


class CapturedColumns(Exception):pass


def capture(root,card):
    """Build the same column pool, intercept before any solve/output writes."""
    captured={};original=frozen.solve_master
    def stop(columns,model,requests,fixed,mode,seconds=90):
        captured.update(columns=columns,model=model,requests=requests,fixed=fixed);raise CapturedColumns()
    frozen.solve_master=stop
    try:frozen.card_master(root,card)
    except CapturedColumns:pass
    finally:frozen.solve_master=original
    assert captured
    return captured


def lp_duals(columns,model,requests,fixed):
    times=sorted(set([c['start'] for c in columns]+[c['end'] for c in columns]));node={t:j for j,t in enumerate(times)}
    ncol=len(columns);arcs=[(node[c['start']],node[c['end']]) for c in columns]+[(j,j+1) for j in range(len(times)-1)]
    na=len(arcs);cost=[0.]*na;bounds=[(0,None)]*na
    eq_r=[];eq_c=[];eq_v=[]
    for j,(a,b) in enumerate(arcs):eq_r.extend((a,b));eq_c.extend((j,j));eq_v.extend((1,-1))
    rhs=np.zeros(len(times));rhs[0]=1;rhs[-1]=-1
    Aeq=coo_matrix((eq_v,(eq_r,eq_c)),shape=(len(times),na))
    rr=[];cc=[];vv=[];ub=[];metadata=[]
    def row(items,value,tag):
        r=len(ub);ub.append(value);metadata.append(tag)
        for c,v in items:rr.append(r);cc.append(c);vv.append(v)
    def var(value,cap=1):
        j=len(cost);cost.append(-value);bounds.append((0,cap));return j
    winners=defaultdict(list);completion=defaultdict(list);req_completion=defaultdict(list)
    windows=[(parse(r['issued_at_utc']).timestamp(),parse(r['deadline_utc']).timestamp()) for r in requests]
    for c,col in enumerate(columns):
        for tid,e in col['entries'].items():
            s,g=e['score_upper'],e['factor_upper']
            if s>0:
                z=var(s,None);row([(z,1),(c,-1)],0,('winner_link',c,tid));winners[tid].append((z,1))
            if g>=.5:completion[tid].append((c,-1))
            for r,request in enumerate(requests):
                if tid in request['target_ids'] and windows[r][0]<=col['start'] and col['end']<=windows[r][1] and g>=request['completion_factor_threshold']:req_completion[r,tid].append((c,-1))
    for tid,items in winners.items():row(items,1,('winner_simplex',tid))
    for tid in model.actual_required:
        b=var(50);row([(b,1)]+completion[tid],0,('required',tid))
    for r,request in enumerate(requests):
        distinct=[]
        for tid in request['target_ids']:
            u=var(0);row([(u,1)]+req_completion[r,tid],0,('request_target',r,tid));distinct.append((u,-1))
        h=var(request['completion_reward']);row([(h,request['minimum_completed'])]+distinct,0,('quorum',r))
    for c in fixed:bounds[c]=(1,1)
    Aeq=coo_matrix((eq_v,(eq_r,eq_c)),shape=(len(times),len(cost))).tocsr()
    Aub=coo_matrix((vv,(rr,cc)),shape=(len(ub),len(cost))).tocsr()
    started=time.perf_counter();result=linprog(cost,A_ub=Aub,b_ub=ub,A_eq=Aeq,b_eq=rhs,bounds=bounds,method='highs')
    assert result.success,result.message
    rho={};nu={};eta={};links={}
    for tag,marginal in zip(metadata,result.ineqlin.marginals):
        price=-float(marginal)
        if tag[0]=='winner_simplex':rho[tag[1]]=price
        elif tag[0]=='required':nu[tag[1]]=price
        elif tag[0]=='request_target':eta[tag[1],tag[2]]=price
        elif tag[0]=='winner_link':links[tag[1],tag[2]]=price
    potential={t:float(result.eqlin.marginals[node[t]]) for t in times}
    # Audit minimum-LP stationarity including all lower/upper bound marginals.
    residual=np.asarray(cost)-Aeq.T@result.eqlin.marginals-Aub.T@result.ineqlin.marginals-result.lower.marginals-result.upper.marginals
    dual_objective=float(rhs@result.eqlin.marginals+np.asarray(ub)@result.ineqlin.marginals)
    dual_objective+=sum((a or 0)*float(m) for (a,b),m in zip(bounds,result.lower.marginals))
    dual_objective+=sum(b*float(m) for (a,b),m in zip(bounds,result.upper.marginals) if b is not None)
    audit={'lp_objective_without_constants':-result.fun,'seconds':time.perf_counter()-started,
        'max_stationarity_residual':float(np.max(np.abs(residual))),
        'dual_primal_objective_residual':abs(dual_objective-result.fun),
        'max_inequality_marginal':float(max(result.ineqlin.marginals)),
        'redundant_flow_and_winner_upper_bounds_removed':True}
    return result,{'rho':rho,'nu':nu,'eta':eta,'potential':potential,'windows':windows,'links':links},audit


def reduced_cost(column,dual,requests):
    science=required=req=0.
    for tid,e in column['entries'].items():
        science+=max(0.,e['score_upper']-dual['rho'].get(tid,0.))
        if e['factor_upper']>=.5:required+=dual['nu'].get(tid,0.)
        for r,request in enumerate(requests):
            a,b=dual['windows'][r]
            if tid in request['target_ids'] and a<=column['start'] and column['end']<=b and e['factor_upper']>=request['completion_factor_threshold']:req+=dual['eta'].get((r,tid),0.)
    arc=dual['potential'][column['end']]-dual['potential'][column['start']]
    return science+required+req-arc,{'science_residual':science,'required':required,'requests':req,'time_arc_cost':arc}


def run(root,card='alpha'):
    began=time.perf_counter();captured=capture(root,card);columns,model,requests,fixed=[captured[k] for k in ('columns','model','requests','fixed')]
    solution,dual,audit=lp_duals(columns,model,requests,fixed)
    prices=[reduced_cost(c,dual,requests)[0] for c in columns]
    nonbasic=[j for j in range(len(columns)) if solution.x[j]<1e-9 and j not in fixed]
    audit.update(existing_columns=len(columns),existing_nonbasic=len(nonbasic),
                 existing_nonbasic_max_reduced_profit=max((prices[j] for j in nonbasic),default=0.),
                 existing_unfixed_max_reduced_profit=max(prices[j] for j in range(len(columns)) if j not in fixed))
    assert audit['existing_nonbasic_max_reduced_profit']<=1e-7
    assert audit['max_stationarity_residual']<=1e-7
    initial,_=initial_public(root/'formal_v4/practice_cards'/card/card);planner=SpatialPlanner(initial)
    profile=np.load(root/'formal_v4/research'/f'quality_profile_{card}_result.npz');meta=json.loads((root/'formal_v4/research'/f'quality_profile_{card}_result.json').read_text())
    matrix=PublicQualityMatrix(model,[parse(t).timestamp() for t in meta['repair_timestamps_utc']]);directory=root/'formal_v4/results'/f'cloud_cd2_{card}_20261003'
    messages=[json.loads(l) for l in (directory/'messages.jsonl').read_text().splitlines()];clear=ReferenceClearFilter(model,messages)
    prefix_end=max((parse(m['issued_at_utc']).timestamp() for m in messages if m['record_type']=='state_resync'),default=None)
    report_times=[parse(d['start_utc']).timestamp() for d in csv.DictReader((directory/'decisions.csv').open()) if d['action']=='report']
    # CPU pricing over existing finite centers/endpoints, different joint fibre
    # assignments. No new potential node is interpolated or assumed known.
    order=sorted(range(len(columns)),key=lambda j:prices[j],reverse=True)
    best=None;seen=set();tested=0;positive=[]
    for c in order:
        old=columns[c];start,end=old['start'],old['end'];duration=int(end-start)
        if prefix_end is not None and start<prefix_end:continue
        if any(start<t<end for t in report_times):continue
        center=old['action']['pointing'];key=(start,end,center['alt_deg'],center['az_deg'])
        if key in seen:continue
        seen.add(key);now=parse(stamp(start));alt,az,hour,vectors=planner._altaz(local_sidereal(now,planner.lon))
        fiber,valid,margin=planner._classify(vectors,center['alt_deg'],center['az_deg']);up=(planner.hmax-hour)/SIDEREAL_SPEED
        pool=np.flatnonzero(valid&(alt>=planner.min_alt+.04)&(up>=duration)&(margin>.03))
        if not len(pool):continue
        cells,coef=matrix.coefficients(start,duration,pool);qhi=coef@profile['upper'][cells]
        factor=np.minimum(1.,planner.flux[pool]*duration/planner.f0t0*qhi);score=planner.weight[pool]*factor*1.2
        overlap=matrix.overlaps(start,duration);choices={}
        for j,i in enumerate(pool):
            tid=model.ids[int(i)];value=max(0.,float(score[j])-dual['rho'].get(tid,0.))
            if factor[j]>=.5:value+=dual['nu'].get(tid,0.)
            for r,request in enumerate(requests):
                a,b=dual['windows'][r]
                if tid in request['target_ids'] and a<=start and end<=b and factor[j]>=request['completion_factor_threshold']:value+=dual['eta'].get((r,tid),0.)
            f=int(fiber[i])
            if value<=0 or (f in choices and value<=choices[f][0]):continue
            if not clear.clear(int(i),overlap):continue
            choices[f]=(value,j)
        if not choices:continue
        entries={model.ids[int(pool[j])]:{'score_upper':float(score[j]),'factor_upper':float(factor[j])} for value,j in choices.values()}
        proposal={'kind':'dual-priced-optimistic','start':start,'end':end,'entries':entries,'action':{'action':'observe','pointing':center,'duration_seconds':duration,
                     'program':'DARK','assignments':{str(f):model.ids[int(pool[j])] for f,(value,j) in choices.items()}}}
        profit,parts=reduced_cost(proposal,dual,requests);tested+=1
        priced={'column':proposal,'reduced_profit':profit,'parts':parts,'based_on_existing_column':c}
        if best is None or profit>best['reduced_profit']:best=priced
        if profit>1e-7:positive.append(priced)
        if tested>=150:break
    audit['pricing_candidates_tested']=tested
    if best is not None:
        audit['best_new_column_reduced_profit']=best['reduced_profit'];audit['best_new_column_parts']=best['parts']
        if best['reduced_profit']>1e-7:
            second,newdual,second_audit=lp_duals(columns+[best['column']],model,requests,fixed)
            audit['augmented_lp_objective_without_constants']=-second.fun
            audit['restricted_lp_improvement']=-second.fun+solution.fun
            audit['new_column_flow']=float(second.x[len(columns)])
            audit['positive_column_improves_restricted_lp']=audit['restricted_lp_improvement']>1e-7
    batch=sorted(positive,key=lambda p:p['reduced_profit'],reverse=True)[:20]
    if batch:
        augmented=columns+[p['column'] for p in batch]
        batch_result,batch_dual,batch_audit=lp_duals(augmented,model,requests,fixed)
        audit['batch_positive_columns']=len(batch)
        audit['batch_augmented_lp_objective_without_constants']=-batch_result.fun
        audit['batch_restricted_lp_improvement']=-batch_result.fun+solution.fun
        audit['batch_column_flows']=batch_result.x[len(columns):len(augmented)].tolist()
        audit['batch_strict_improvement']=audit['batch_restricted_lp_improvement']>1e-7
        # Same optimistic assignments, independently price conservative quality
        # and a single common DARK program, then solve the season integer master.
        from challenge.v4_fiber_map import FiberGrid
        grid=FiberGrid(planner.glass**2,planner.pitch-planner.glass,planner.nfib)
        conservative_batch=[];geometry_checks=0
        for priced in batch:
            col=priced['column'];ids=list(col['entries']);indices=np.array([model.index[tid] for tid in ids])
            duration=col['end']-col['start'];cells,coef=matrix.coefficients(col['start'],duration,indices)
            qlo=coef@profile['lower'][cells];glo=np.minimum(1.,planner.flux[indices]*duration/planner.f0t0*qlo)
            entries={tid:{**col['entries'][tid], 'factor_lower':float(glo[j]),
                         'score_lower':float(planner.weight[indices[j]]*glo[j]*(1.2 if qlo[j]>=planner.dark_threshold else 1.))} for j,tid in enumerate(ids)}
            conservative_batch.append({**col,'entries':entries})
            point=col['action']['pointing'];moment=parse(stamp(col['start']))
            for fid,tid in col['action']['assignments'].items():
                i=model.index[tid];hit=grid.classify_target(model.ra[i],model.dec[i],moment,point['alt_deg'],point['az_deg'],planner.lat,planner.lon)
                assert hit.region=='glass' and hit.fiber_id==int(fid);geometry_checks+=1
        full=columns+conservative_batch
        primal,primal_stats=frozen.solve_master(full,model,requests,fixed,'lower',60)
        report=json.loads((directory/'score_report.json').read_text());historical=[j for j,col in enumerate(columns) if col['kind']=='historical']
        baseline=frozen.settle(full,historical,model,requests,report['components']['report_settlement'])
        chosen=[j for j in range(len(full)) if primal.x is not None and primal.x[j]>.5] if primal.x is not None else historical
        score=frozen.settle(full,chosen,model,requests,report['components']['report_settlement'])
        audit['conservative_primal']={'mip_status':primal.status,'mip_gap':getattr(primal,'mip_gap',None),'stats':primal_stats,
              'original_reconstruction':baseline,'candidate_with_actual_uniformity':score,
              'conditional_total_difference':score['total_conditional_conservative']-baseline['total_conditional_conservative'],
              'science_change':score['science']-baseline['science'],'required_reward_change':50*(baseline['required_missing']-score['required_missing']),
              'request_reward_change':sum(score['request_rewards'])-sum(baseline['request_rewards']),
              'new_priced_columns_selected':[j-len(columns) for j in chosen if j>=len(columns)],
              'new_assignment_official_geometry_checks':geometry_checks}
        schedule=[{'start_utc':stamp(full[j]['start']),'end_utc':stamp(full[j]['end']),'kind':full[j]['kind'],'action':full[j]['action']} for j in sorted(chosen,key=lambda j:full[j]['start'])]
        schedule += [{'start_utc':stamp(t),'end_utc':stamp(t),'kind':'fixed-report','action':{'action':'report'}} for t in report_times]
        audit['_primal_schedule']=sorted(schedule,key=lambda r:(r['start_utc'],r['kind']))
    audit['elapsed_seconds']=time.perf_counter()-began
    destination=root/'formal_v4/results/season_column_dual_audit_20261004'/card;destination.mkdir(parents=True,exist_ok=True)
    if '_primal_schedule' in audit:(destination/'conservative_schedule.json').write_text(json.dumps(audit.pop('_primal_schedule'),indent=2))
    (destination/'audit.json').write_text(json.dumps(audit,indent=2))
    if best:(destination/'priced_column.json').write_text(json.dumps(best,indent=2))
    (destination/'priced_batch.json').write_text(json.dumps(batch,indent=2))
    exported={'target_order':model.ids,'rho':[dual['rho'].get(tid,0.) for tid in model.ids],
              'required_nu':[dual['nu'].get(tid,0.) for tid in model.ids],
              'request_eta':[[dual['eta'].get((r,tid),0.) for tid in model.ids] for r in range(len(requests))],
              'requests':requests,'time_nodes':sorted(dual['potential']),'time_potential':[dual['potential'][t] for t in sorted(dual['potential'])],
              'time_arc_cost_definition':'potential[end] - potential[start], potentials are scipy equality marginals',
              'fixed_column_indices':fixed,'hypothesis':'optimistic fixed finite pool; reference geometry/Z bounds; original report/E history; no hidden-offset guarantee'}
    exported['admissibility']={'new_start_at_or_after_fixed_resync':prefix_end,
                               'fixed_report_times':report_times,'new_column_must_not_straddle_report':True,
                               'pricing_endpoints_must_be_existing_time_nodes':True}
    (destination/'pricing_duals.json').write_text(json.dumps(exported,indent=2));print(json.dumps(audit,indent=2),flush=True)
    return audit


if __name__=='__main__':
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'formal_v4/upstream/gosim-observer-examples/runner'))
    run(root,sys.argv[1] if len(sys.argv)>1 else 'alpha')
