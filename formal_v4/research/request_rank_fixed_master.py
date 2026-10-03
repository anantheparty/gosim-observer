"""Rank-fixed finite compensation MILP; all original time slots choose one action.

Historical rows are actual final-valid own observations. New rows are conditional
profiles. Objective science+mandatory+REQ is linear; actual Jain is then settled.
"""
from __future__ import annotations
import csv,hashlib,json,os,sys,time
from collections import defaultdict
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from scipy.sparse import coo_matrix
from request_rank_fixed_exchange import SparseLedger,rows,readlines,sha
from request_remote_owned_gate import initial_public
from quality_profile_inversion import all_target_model
from spatial_candidates import SpatialPlanner


def optimize(columns,required,request,preserve,max_changes=4,seconds=90,require_request=False):
    n=len(columns);c=[0.]*n;lo=[0.]*n;hi=[1.]*n;integers=[1]*n
    rr=[];cc=[];vv=[];rl=[];rh=[]
    def row(items,low,high):
        r=len(rl);rl.append(low);rh.append(high)
        for i,v in items:rr.append(r);cc.append(i);vv.append(v)
    def var(reward,binary=False):
        i=len(c);c.append(-reward);lo.append(0.);hi.append(1.);integers.append(int(binary));return i
    groups=defaultdict(list);winners=defaultdict(list);completes=defaultdict(list);reqcompletes=defaultdict(list)
    for i,col in enumerate(columns):
        groups[col['original_observe_index']].append((i,1))
        for t,e in col['entries'].items():
            if e['score_lower']>0:
                z=var(e['score_lower']);row([(z,1),(i,-1)],-np.inf,0);winners[t].append((z,1))
            if e['factor_lower']>=.5:completes[t].append((i,-1))
            if (t in request['target_ids'] and request['issued_at_utc']<=col['start_utc'] and col['end_utc']<=request['deadline_utc']
                and e['factor_lower']>=request['completion_factor_threshold']):reqcompletes[t].append((i,-1))
    for items in groups.values():row(items,1,1)
    for items in winners.values():row(items,-np.inf,1)
    for t in required:
        u=var(50,True);row([(u,1)]+completes[t],-np.inf,0)
        if t in preserve:lo[u]=hi[u]=1
    rq=[]
    for t in request['target_ids']:
        u=var(0,True);row([(u,1)]+reqcompletes[t],-np.inf,0);rq.append((u,-1))
    reward=var(request['completion_reward'],True);row([(reward,request['minimum_completed'])]+rq,-np.inf,0)
    if require_request:lo[reward]=hi[reward]=1
    alternatives=[(i,1) for i,col in enumerate(columns) if col['kind']=='conditional-new']
    row(alternatives,-np.inf,max_changes)
    A=coo_matrix((vv,(rr,cc)),shape=(len(rl),len(c))).tocsr();began=time.perf_counter()
    result=milp(c,integrality=integers,bounds=Bounds(lo,hi),constraints=LinearConstraint(A,np.asarray(rl),np.asarray(rh)),
                options={'time_limit':seconds,'mip_rel_gap':1e-8})
    return result,{'columns':n,'variables':len(c),'rows':len(rl),'nonzeros':A.nnz,'max_new_columns':max_changes,
                   'preserved_mandatory_targets':len(preserve),'REQ1_reward_forced':require_request,'elapsed_seconds':time.perf_counter()-began,
                   'status':int(result.status),'mip_gap':getattr(result,'mip_gap',None),'objective_proxy':None if result.fun is None else -result.fun,
                   'proxy_dual_upper':None if getattr(result,'mip_dual_bound',None) is None else -result.mip_dual_bound}


def main():
    root=Path(__file__).resolve().parents[2];out=root/'formal_v4/results/request_quota_failure_20261003'
    run=root/'formal_v4/results/cloud_request_gpu_delta_20261003';card=root/'formal_v4/practice_cards/delta/delta'
    initial,_=initial_public(card);model=all_target_model(card);planner=SpatialPlanner(initial)
    ds=[d for d in rows(run/'decisions.csv') if d['action']=='observe'];observations=rows(run/'observations.csv');allactions=readlines(run/'actions.jsonl')
    acts=[a for a in allactions if a['action']=='observe'];messages=readlines(run/'messages.jsonl')
    rq=[m for m in messages if m['record_type']=='observation_request'][0];report=json.loads((run/'score_report.json').read_text())
    fixed_reward=report['components']['report_settlement']+sum(r['reward'] for r in report['observation_requests'][1:])
    ledger=SparseLedger(model,planner,ds,observations,rq,fixed_reward);baseline=ledger.settle([])
    hist=defaultdict(dict)
    for h in observations:
        if h['valid']=='true':hist[int(h['observe_index'])][h['target_id']]={'score_lower':float(h['score']),'factor_lower':float(h['factor'])}
    columns=[{'kind':'historical','original_observe_index':j,'start_utc':d['start_utc'],'end_utc':d['end_utc'],'action':a,'entries':hist[j]}
             for j,(d,a) in enumerate(zip(ds,acts))]
    for name in ('delta_one_for_one_columns.json','delta_compensation_columns.json'):
        for c in json.loads((out/name).read_text()):columns.append({**c,'kind':'conditional-new'})
    best_pair=json.loads((out/'delta_all_pairs_exact_ledger.json').read_text())['best_pair']
    best=best_pair;solutions=[]
    for mode,preserve,limit,force in [('free',set(),4,False),('preserve_original_mandatory',ledger.required-ledger.missing,4,False),
                                    ('whole_finite_pool',set(),len(ds),False),
                                    ('whole_pool_preserve_mandatory_force_REQ1',ledger.required-ledger.missing,len(ds),True)]:
        result,stats=optimize(columns,ledger.required,rq,preserve,limit,require_request=force)
        if result.x is None:solutions.append({'mode':mode,'stats':stats,'no_solver_incumbent':True});continue
        chosen=[i for i in range(len(columns)) if result.x[i]>.5];counts=defaultdict(int)
        for i in chosen:counts[columns[i]['original_observe_index']]+=1
        assert len(chosen)==len(ds) and set(counts)==set(range(len(ds))) and set(counts.values())=={1}
        changes=[columns[i] for i in chosen if columns[i]['kind']=='conditional-new'];value=ledger.settle(changes)
        if preserve:assert value['required_missing']<=baseline['required_missing']
        solution={'mode':mode,'stats':stats,'changes':changes,'settlement':value,'conditional_total_difference':value['conditional_total']-baseline['conditional_total']}
        solutions.append(solution)
        if best is None or value['conditional_total']>best['settlement']['conditional_total']:best=solution
    if best:
        replacements={c['original_observe_index']:c['action'] for c in best['changes']};derived=[];j=0
        for a in allactions:
            if a['action']=='observe':derived.append(replacements.get(j,a));j+=1
            else:derived.append(a)
        assert len(derived)==len(allactions) and j==len(ds)
        assert all(a==b for a,b in zip(allactions,derived) if a['action']!='observe')
        obsnew=[a for a in derived if a['action']=='observe'];assert all(a['duration_seconds']==b['duration_seconds'] for a,b in zip(acts,obsnew))
        path=out/'delta_compensated_conditional_actions.jsonl';path.write_text(''.join(json.dumps(a,separators=(',',':'))+'\n' for a in derived))
        best['executable_file']=path.name;best['actions_sha256']=sha(path)
    summary={'baseline':baseline,'best_result':best,'solutions':solutions,'conditional_only_not_official_score':True,
             'all_original_time_slots_choose_exactly_one':True,'observe_count':len(ds),'fixed_loss_rank_window':[150,169],
             'all_new_outside_loss_window':all(not(150<=c['original_observe_index']<169) for c in columns[len(ds):]),
             'Jain_in_optimization':False,'Jain_in_final_settlement':True,'global_physical_search_complete':False,
             'columns':len(columns),'source_sha256':sha(Path(__file__))}
    (out/'delta_fixed_rank_compensation_master.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({'solutions':[{'mode':s['mode'],'stats':s['stats'],'settlement':s.get('settlement'),'gain':s.get('conditional_total_difference')} for s in solutions],
                      'best_change_ranks':[] if best is None else [c['original_observe_index'] for c in best['changes']]},indent=2))


if __name__=='__main__':main()
