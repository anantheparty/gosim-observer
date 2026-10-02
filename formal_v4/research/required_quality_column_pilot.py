"""CPU pilot: exact finite DAG-flow coverage, shared glass assignments.

Objective is only 50 points per formerly missing required target. This is not a
whole-survey science optimizer or full-problem upper bound.
"""
import json,math,os,sys,time
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
import numpy as np
from scipy.optimize import milp,linprog,Bounds,LinearConstraint
from scipy.sparse import coo_matrix
from required_opportunity_model import RequiredOpportunityModel,public_initial,parse,stamp
from quality_profile_inversion import PublicQualityMatrix,ReferenceClearFilter
from terrain_version_space import altaz_at
from spatial_candidates import _shift_altaz


def main():
    began=time.perf_counter();root=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root/'formal_v4/upstream/gosim-observer-examples/runner'))
    from challenge.v4_fiber_map import FiberGrid
    audit=json.loads((root/'formal_v4/results/required_quality_interval_20261003/audit.json').read_text())
    results={}
    for card in ('alpha','beta','gamma','delta'):
        base=root/'formal_v4/practice_cards'/card/card
        model=RequiredOpportunityModel(public_initial(base));targets=audit['cards'][card]['targets']
        indices=np.array([model.index[t['target_id']] for t in targets]);ids=[t['target_id'] for t in targets]
        profile=np.load(root/'formal_v4/research'/f'quality_profile_{card}_result.npz')
        repairs=[parse(t).timestamp() for t in audit['cards'][card]['repair_times']]
        matrix=PublicQualityMatrix(model,repairs)
        messages=[json.loads(l) for l in (root/'formal_v4/results'/f'cloud_cd2_{card}_20261003/messages.jsonl').read_text().splitlines()]
        clear=ReferenceClearFilter(model,messages)
        field=json.loads((base/'config/v4_fiber_config.json').read_text())['field'];grid=FiberGrid.from_config({'field':field})
        glass,pitch,side=math.sqrt(field['fiber_area_deg2']),math.sqrt(field['fiber_area_deg2'])+field['gap_deg'],math.isqrt(field['n_fibers'])
        seeds=sorted(set((parse(w['start_utc']).timestamp(),w['duration_seconds']) for t in targets for w in t['top_conditional_coupons']))
        columns=[];seen=set()
        for start,duration in seeds:
            now=parse(stamp(start));cells,coef=matrix.coefficients(start,duration,indices)
            factors=np.minimum(1.,model.flux[indices]*duration/model.f0t0*(coef@profile['lower'][cells]))
            feasible=[]
            for j,i in enumerate(indices):
                night=next(n for n,(a,b) in enumerate(model.nights) if a<=start<b)
                visible=any(a-1e-7<=start and start+duration<=b+1e-7 for a,b in model.windows(i,night))
                if visible and factors[j]>=.5 and clear.clear(i,matrix.overlaps(start,duration)):feasible.append(j)
            if not feasible:continue
            alt,az=altaz_at(start,model.ra[indices],model.dec[indices],model.latitude,model.longitude)
            for anchor in feasible:
                for r in range(side):
                    for c in range(side):
                        center=_shift_altaz(alt[anchor],az[anchor],-(r-(side-1)/2)*pitch,-(c-(side-1)/2)*pitch)
                        assigned={}
                        for j in feasible:
                            hit=grid.classify_target(model.ra[indices[j]],model.dec[indices[j]],now,*center,model.latitude,model.longitude)
                            if hit.region=='glass' and (hit.fiber_id not in assigned or factors[j]>factors[assigned[hit.fiber_id]]):assigned[hit.fiber_id]=j
                        if not assigned:continue
                        mask=sum(1<<j for j in assigned.values());key=(start,duration,mask)
                        if key in seen:continue
                        seen.add(key);columns.append({'start':start,'end':start+duration,'mask':mask,'assignments':{str(f):ids[j] for f,j in assigned.items()},'pointing':center})
        if not columns:
            results[card]={'columns':0,'covered':0};continue
        times=sorted(set([x['start'] for x in columns]+[x['end'] for x in columns]));node={t:j for j,t in enumerate(times)}
        arcs=[(node[x['start']],node[x['end']]) for x in columns]+[(j,j+1) for j in range(len(times)-1)]
        n_arc,n_target=len(arcs),len(ids);n_var=n_arc+n_target
        rr=[];cc=[];vv=[]
        for a,(start,end) in enumerate(arcs):rr.extend((start,end));cc.extend((a,a));vv.extend((1,-1))
        for j in range(n_target):
            rr.append(len(times)+j);cc.append(n_arc+j);vv.append(1)
            for c,x in enumerate(columns):
                if x['mask']&(1<<j):rr.append(len(times)+j);cc.append(c);vv.append(-1)
        A=coo_matrix((vv,(rr,cc)),shape=(len(times)+n_target,n_var)).tocsr()
        b=np.zeros(len(times));b[0]=1;b[-1]=-1
        lower=np.r_[b,np.full(n_target,-np.inf)];upper=np.r_[b,np.zeros(n_target)]
        objective=np.r_[np.zeros(n_arc),np.full(n_target,-50.)]
        solve_started=time.perf_counter()
        mip=milp(objective,integrality=np.r_[np.ones(len(columns)),np.zeros(n_arc-len(columns)),np.ones(n_target)],bounds=Bounds(0,1),constraints=LinearConstraint(A,lower,upper),options={'time_limit':15})
        lp=linprog(objective,A_ub=A[len(times):],b_ub=np.zeros(n_target),A_eq=A[:len(times)],b_eq=b,bounds=(0,1),method='highs')
        selected=[c for c in range(len(columns)) if mip.x is not None and mip.x[c]>.5]
        union=0
        for c in selected:union|=columns[c]['mask']
        results[card]={'finite_columns':len(columns),'time_nodes':len(times),'variables':n_var,
            'formerly_missing':n_target,'maximum_shared_required_per_column':max(x['mask'].bit_count() for x in columns),
            'integer_covered':union.bit_count(),'integer_objective':None if mip.fun is None else -mip.fun,
            'lp_upper_for_this_column_pool':None if lp.fun is None else -lp.fun,'mip_status':mip.status,
            'mip_gap':getattr(mip,'mip_gap',None),'solver_seconds':time.perf_counter()-solve_started,
            'selected_columns':[{**columns[c],'start_utc':stamp(columns[c]['start']),'end_utc':stamp(columns[c]['end'])} for c in selected],
            'uncovered_ids':[tid for j,tid in enumerate(ids) if not union&(1<<j)]}
    result={'scope':'exact finite shared-required coverage pilot; ignores competing science and REQ; original E path/reference geometry conditional',
            'finite_lp_not_global_upper':True,'hidden_inputs_read':False,'cards':results,'elapsed_seconds':time.perf_counter()-began}
    destination=root/'formal_v4/results/required_quality_interval_20261003/flow_pilot.json'
    destination.write_text(json.dumps(result,indent=2));print(json.dumps({c:{k:v for k,v in x.items() if k!='selected_columns'} for c,x in results.items()},indent=2))


if __name__=='__main__':main()
