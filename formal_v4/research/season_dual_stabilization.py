"""Select a valid dual on the same finite season LP optimal face.

Secondary objective: minimize mandatory-row prices for targets already completed
by the historical incumbent. No new pointings, GPU, policy, or hidden inputs.
"""
from __future__ import annotations
import argparse,hashlib,json,math,os,sys,time
from pathlib import Path
from collections import defaultdict
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix,hstack,vstack,csr_matrix
import season_column_dual_audit as audit
import season_science_required_master as master
from required_opportunity_model import parse


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite_primal(columns,model,requests,fixed):
    """Intercept the actual upstream LP call, retaining every bound unchanged."""
    call={};original=audit.linprog
    def wrapped(c,**kwargs):
        call.update(c=np.asarray(c,dtype=float),**kwargs)
        return original(c,**kwargs)
    audit.linprog=wrapped
    try:result,old_dual,old_audit=audit.lp_duals(columns,model,requests,fixed)
    finally:audit.linprog=original
    # Row tags reproduce exactly the unmodified audited primal construction.
    tags=[];winners=defaultdict(list)
    for j,col in enumerate(columns):
        for tid,e in col['entries'].items():
            if e['score_upper']>0:tags.append(('winner_link',j,tid));winners[tid].append(j)
    tags.extend(('winner_simplex',tid) for tid in winners)
    tags.extend(('required',tid) for tid in model.actual_required)
    for r,req in enumerate(requests):
        tags.extend(('request_target',r,tid) for tid in req['target_ids'])
        tags.append(('quorum',r))
    assert len(tags)==call['A_ub'].shape[0]
    return call,result,old_dual,old_audit,tags


def secondary_dual(call,primal,tags,completed,seconds):
    c=call['c'];A=call['A_eq'];G=call['A_ub'];b=np.asarray(call['b_eq']);d=np.asarray(call['b_ub'])
    bounds=call['bounds'];n=len(c);ne=A.shape[0];ng=G.shape[0]
    il=np.array([j for j,(l,u) in enumerate(bounds) if l is not None],dtype=int)
    iu=np.array([j for j,(l,u) in enumerate(bounds) if u is not None],dtype=int)
    lo=np.array([bounds[j][0] for j in il]);hi=np.array([bounds[j][1] for j in iu])
    L=coo_matrix((np.ones(len(il)),(il,np.arange(len(il)))),shape=(n,len(il))).tocsr()
    U=coo_matrix((np.ones(len(iu)),(iu,np.arange(len(iu)))),shape=(n,len(iu))).tocsr()
    # SciPy min dual: lambda free, mu<=0, alpha>=0, beta<=0.
    # c = A.T lambda + G.T mu + L alpha + U beta.
    stationarity=hstack((A.T,G.T,L,U),format='csr')
    objective_coeff=np.concatenate((b,d,lo,hi))
    equalities=vstack((stationarity,csr_matrix(objective_coeff.reshape(1,-1))),format='csr')
    target=np.zeros(equalities.shape[1])
    for k,tag in enumerate(tags):
        if tag[0]=='required' and tag[1] in completed:target[ne+k]=-1.
    solved_at=time.perf_counter()
    secondary=linprog(target,A_eq=equalities,b_eq=np.r_[c,primal.fun],
                      bounds=[(None,None)]*ne+[(None,0.)]*ng+[(0.,None)]*len(il)+[(None,0.)]*len(iu),
                      method='highs',options={'time_limit':seconds,'dual_feasibility_tolerance':1e-8,
                                             'primal_feasibility_tolerance':1e-8})
    assert secondary.success,secondary.message
    v=secondary.x;lam=v[:ne];mu=v[ne:ne+ng];alpha=v[ne+ng:ne+ng+len(il)];beta=v[ne+ng+len(il):]
    lower=np.zeros(n);upper=np.zeros(n);lower[il]=alpha;upper[iu]=beta
    residual=stationarity@v-c
    # math.fsum avoids an unrelated BLAS floating-point warning on this host.
    obj=math.fsum(float(a)*float(z) for a,z in zip(objective_coeff,v))
    eq_error=float(np.max(abs(A@primal.x-b)))
    inequality_slack=d-G@primal.x
    low_slack=primal.x[il]-lo;up_slack=hi-primal.x[iu]
    proof={'secondary_status':secondary.status,'secondary_message':secondary.message,
           'secondary_solve_seconds':time.perf_counter()-solved_at,
           'stationarity_max_abs':float(np.max(abs(residual))),
           'original_min_objective':float(primal.fun),'stabilized_min_dual_objective':obj,
           'optimal_face_objective_error':abs(obj-primal.fun),
           'mu_max':float(max(mu)),'alpha_min':float(min(alpha)),'beta_max':float(max(beta)) if len(beta) else 0.,
           'primal_equality_error':eq_error,'primal_inequality_violation':float(max(0.,-min(inequality_slack))),
           'inequality_complementarity_max':float(np.max(abs(mu*inequality_slack))),
           'lower_bound_complementarity_max':float(np.max(abs(alpha*low_slack))),
           'upper_bound_complementarity_max':float(np.max(abs(beta*up_slack))) if len(beta) else 0.,
           'finite_lower_bounds':len(il),'finite_upper_bounds':len(iu),
           'original_bound_arrays_preserved':True,'dual_variables':len(v),'dual_equalities':equalities.shape[0],
           'minimum_completed_mandatory_price_sum':float(secondary.fun)}
    assert proof['stationarity_max_abs']<1e-7 and proof['optimal_face_objective_error']<1e-6
    assert proof['mu_max']<1e-8 and proof['alpha_min']>=-1e-8 and proof['beta_max']<1e-8
    assert max(proof[k] for k in ('inequality_complementarity_max','lower_bound_complementarity_max','upper_bound_complementarity_max'))<1e-6
    return lam,mu,lower,upper,proof


def run(root,out,seconds):
    began=time.perf_counter();out.mkdir(parents=True,exist_ok=True)
    old=audit.capture(root,'alpha');columns,model,requests,fixed=[old[k] for k in ('columns','model','requests','fixed')]
    call,primal,original,original_audit,tags=finite_primal(columns,model,requests,fixed)
    historical=[j for j,c in enumerate(columns) if c['kind']=='historical']
    baseline=master.settle(columns,historical,model,requests,100.)
    completed=set(model.actual_required)-set(baseline['missing_ids'])
    lam,mu,lower,upper,proof=secondary_dual(call,primal,tags,completed,seconds)
    times=sorted(set(c['start'] for c in columns)|set(c['end'] for c in columns))
    prices={'rho':{},'nu':{},'eta':{},'links':{},'potential':dict(zip(times,map(float,lam))),
            'windows':[(parse(r['issued_at_utc']).timestamp(),parse(r['deadline_utc']).timestamp()) for r in requests]}
    for tag,marginal in zip(tags,mu):
        val=-float(marginal)
        if tag[0]=='winner_simplex':prices['rho'][tag[1]]=val
        elif tag[0]=='required':prices['nu'][tag[1]]=val
        elif tag[0]=='request_target':prices['eta'][tag[1],tag[2]]=val
        elif tag[0]=='winner_link':prices['links'][tag[1],tag[2]]=val
    # An unfixed arc has no finite upper bound. Fixed prefix arcs may have a
    # positive raw reduced profit only compensated by their explicit bound duals.
    pool=[audit.reduced_cost(c,prices,requests)[0] for c in columns]
    adjusted=[v+float(lower[j])+float(upper[j]) for j,v in enumerate(pool)]
    unfixed=[v for j,v in enumerate(pool) if j not in fixed]
    proof.update(pool_columns=len(columns),fixed_prefix_columns=len(fixed),
                 pool_unfixed_reduced_profit_max=float(max(unfixed)),
                 pool_bound_adjusted_reduced_profit_max=float(max(adjusted)))
    assert max(unfixed)<1e-7 and max(adjusted)<1e-7
    prepared=root/'formal_v4/results/actual_joint_gpu_pricing_20261004/alpha'
    meta=json.loads((prepared/'metadata.json').read_text());batch=json.loads((prepared/'refined_columns.json').read_text())
    serialized=json.loads(Path(meta['dual_path']).read_text())
    assert serialized['target_order']==model.ids
    old_arrays=([original['rho'].get(t,0.) for t in model.ids],
                [original['nu'].get(t,0.) for t in model.ids],
                [[original['eta'].get((r,t),0.) for t in model.ids] for r in range(len(requests))])
    proof['serialized_original_dual_max_error']=max(float(np.max(abs(np.asarray(x)-np.asarray(serialized[k]))))
                                                 for x,k in zip(old_arrays,('rho','required_nu','request_eta')))
    assert proof['serialized_original_dual_max_error']<1e-7
    rows=[]
    for j,col in enumerate(batch['columns']):
        before,bc=audit.reduced_cost(col,original,requests);after,ac=audit.reduced_cost(col,prices,requests)
        assert abs(before-col['reduced_profit'])<1e-7
        rows.append({'column':j,'before':before,'after':after,'before_components':bc,'after_components':ac})
    cases=[]
    for case in meta['cases']:
        assert case['start'] in prices['potential'] and all(t in prices['potential'] for t in case['end_nodes'])
        cases.append({'case':case['case'],'start':case['start'],'ends':case['end_nodes'],
                      'original_arc_costs':[original['potential'][t]-original['potential'][case['start']] for t in case['end_nodes']],
                      'stabilized_arc_costs':[prices['potential'][t]-prices['potential'][case['start']] for t in case['end_nodes']]})
    required_rows=[{'target_id':tid,'historically_completed':tid in completed,
                    'original_nu':original['nu'].get(tid,0.),'stabilized_nu':prices['nu'].get(tid,0.)}
                   for tid in model.actual_required]
    summary={'status':'COMPLETE_VALID_DUAL_OPTIMAL_FACE','card':'alpha','baseline_official_total':7094.664204,
             'original_finite_LP_max_without_constants':-primal.fun,
             'completed_mandatory':len(completed),'baseline_missing_ids':baseline['missing_ids'],
             'completed_nu_sum_before':sum(original['nu'].get(t,0.) for t in completed),
             'completed_nu_sum_after':sum(prices['nu'].get(t,0.) for t in completed),
             'missing_nu_sum_before':sum(original['nu'].get(t,0.) for t in baseline['missing_ids']),
             'missing_nu_sum_after':sum(prices['nu'].get(t,0.) for t in baseline['missing_ids']),
             'candidate_count':len(rows),'candidate_positive_before':sum(r['before']>1e-7 for r in rows),
             'candidate_positive_after':sum(r['after']>1e-7 for r in rows),
             'candidate_price_max_before':max(r['before'] for r in rows),'candidate_price_max_after':max(r['after'] for r in rows),
             'original_primal_audit':original_audit,'proof':proof,'elapsed_seconds':time.perf_counter()-began,
             'new_score_produced':False,'global_bound_produced':False,'GPU_called':False}
    exported={'schema':'stabilized-optimal-finite-season-pricing-duals-v1','target_order':model.ids,
              'rho':[prices['rho'].get(t,0.) for t in model.ids],
              'required_nu':[prices['nu'].get(t,0.) for t in model.ids],
              'request_eta':[[prices['eta'].get((r,t),0.) for t in model.ids] for r in range(len(requests))],
              'requests':requests,'time_nodes':times,'time_potential':list(map(float,lam)),
              'admissibility':serialized['admissibility'],
              'scope':'same old-alpha finite pool; same objective; minimize completed mandatory nu; not a new score/global certificate',
              'bound_duals':{'lower_nonzero':{str(j):float(v) for j,v in enumerate(lower) if abs(v)>1e-10},
                            'upper_nonzero':{str(j):float(v) for j,v in enumerate(upper) if abs(v)>1e-10}},
              'proof':proof}
    for name,data in [('summary.json',summary),('pricing_duals_stabilized.json',exported),
                      ('required_nu_comparison.json',required_rows),('existing_candidates.json',rows),('prepared_case_time_costs.json',cases)]:
        (out/name).write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    # Full local winner-link, quorum and bound multipliers remain reproducible,
    # including the variables absent from the compact pricing JSON.
    np.savez_compressed(out/'full_dual_certificate.npz',lambda_eq=lam,mu_ub=mu,
                        alpha_lower=lower,beta_upper=upper,original_primal_x=primal.x,
                        original_primal_cost=call['c'],original_primal_fun=np.array(primal.fun))
    def sparse_digest(a):
        h=hashlib.sha256()
        for part in (np.asarray(a.shape,dtype=np.int64),a.data,a.indices,a.indptr):h.update(part.tobytes())
        return h.hexdigest()
    matrix_hashes={'A_eq':sparse_digest(call['A_eq']),'A_ub':sparse_digest(call['A_ub']),
                   'bounds_sha256':hashlib.sha256(json.dumps(call['bounds']).encode()).hexdigest(),
                   'ineq_row_tags_sha256':hashlib.sha256(json.dumps(tags).encode()).hexdigest()}
    (out/'primal_matrix_hashes.json').write_text(json.dumps(matrix_hashes,indent=2)+'\n')
    manifest={'source_sha256':sha(__file__),'original_audit_source_sha256':sha(root/'formal_v4/research/season_column_dual_audit.py'),
              'master_source_sha256':sha(root/'formal_v4/research/season_science_required_master.py'),
              'input_original_dual_sha256':sha(Path(meta['dual_path'])),
              'input_prepared_metadata_sha256':sha(prepared/'metadata.json'),'input_candidates_sha256':sha(prepared/'refined_columns.json'),
              'output_hashes':{f.name:sha(f) for f in sorted(out.iterdir()) if f.is_file() and f.name not in ('manifest.json','README.md')}}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(summary,indent=2,allow_nan=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--seconds',type=float,default=90.);args=parser.parse_args()
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'formal_v4/upstream/gosim-observer-examples/runner'))
    try:run(root,Path(args.out),args.seconds)
    except Exception as exc:
        p=Path(args.out);p.mkdir(parents=True,exist_ok=True)
        (p/'INCOMPLETE.json').write_text(json.dumps({'status':'INCOMPLETE','error':str(exc),'valid_dual_exported':False},indent=2)+'\n')
        raise
