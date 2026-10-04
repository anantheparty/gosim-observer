"""Diagnostic constrained Bellman only; original model/prior/DP immutable."""
import itertools,json,math,hashlib
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;SOURCE=HERE.parent
data=np.load(SOURCE/'report_dp.npz');K=data['kernels'];L=data['loss'];PG=data['pgrid'];NP=len(PG);NST=NP*9;H=int(data['horizon']);pp=np.tile(PG,9);pp[6*NP:]=0.
V=np.zeros((H+1,3,NST));D=np.full((H,3,NST),-np.inf);A=np.zeros((H,3,NST),bool);maxerr=0.;checked=0
with np.errstate(all='ignore'):
    for i in range(H-1,-1,-1):
        ph=min(7,int(8*i/H))
        for q in range(3):
            W=-L[ph]+K[ph,0]@V[i+1,q]
            if q==0:V[i,q]=W
            else:
                R=pp*(100+K[ph,1]@V[i+1,2])+(1-pp)*(K[ph,2]@V[i+1,q-1])
                allowed=(pp>0);A[i,q]=allowed;D[i,q,allowed]=(R-W)[allowed];V[i,q]=np.where(allowed,np.maximum(W,R),W)
    # Every state verifies both feasible action set and exact Bellman equation.
    for i,q in itertools.product(range(H),range(3)):
        ph=min(7,int(8*i/H));W=-L[ph]+K[ph,0]@V[i+1,q]
        if q==0:
            assert not A[i,q].any() and np.isneginf(D[i,q]).all();err=np.max(np.abs(V[i,q]-W))
        else:
            R=pp*(100+K[ph,1]@V[i+1,2])+(1-pp)*(K[ph,2]@V[i+1,q-1]);mask=(pp>0)
            assert np.array_equal(A[i,q],mask) and np.isneginf(D[i,q,~mask]).all()
            err=np.max(np.abs(V[i,q]-np.where(mask,np.maximum(W,R),W)))
            assert np.max(np.abs(D[i,q,mask]-(R-W)[mask]))<1e-10
        maxerr=max(maxerr,float(err));checked+=NST
assert np.isfinite(V).all() and np.isfinite(D[A]).all() and np.max(np.abs(V[:,:,6*NP:]))==0.
def terminal(p,q):return 100*p if q>0 else 0.
def enumerate_tree(p,q,h,ell):
    values=[]
    for report in [False,True]:
        if report and q==0:values.append(-math.inf);continue
        outcomes=['correct','false'] if report else ['wait'];best=-math.inf
        for choices in itertools.product([False,True],repeat=len(outcomes)):
            value=0.;feasible=True
            for f0 in [0,1]:
                prob=p if f0 else 1-p;outcome=('correct' if f0 else 'false') if report else 'wait';qn=(2 if f0 else q-1) if report else q;do=choices[outcomes.index(outcome)]
                if do and qn==0:feasible=False;break
                first=100*f0 if report else -ell*f0
                for new in [0,1]:
                    pr=(h if new else 1-h) if not f0 else float(new==0);ft=int((f0 and not report) or (not f0 and new))
                    value+=prob*pr*(first+100*ft*do)
            if feasible:best=max(best,value)
        values.append(best)
    return values
trees=0;treeerr=0.
for p,q,h,ell in itertools.product([0.,.005,.1,.35,.6,.9,1.],range(3),[0.,.2],[0.,4.,30.]):
    wanted=[-p*ell+terminal(p+(1-p)*h,q),100*p+(1-p)*terminal(h,q-1) if q>0 else -math.inf]
    got=enumerate_tree(p,q,h,ell)
    for a,b in zip(got,wanted):
        assert (math.isinf(a) and a==b) or abs(a-b)<1e-10
        if math.isfinite(a):treeerr=max(treeerr,abs(a-b))
    trees+=1
np.savez_compressed(HERE/'diagnostic_free_only_dp.npz',value=V,delta=D,report_allowed=A,kernels=K,loss=L,pgrid=PG,horizon=H)
out=dict(passed=True,source_DP_sha256=hashlib.sha256((SOURCE/'report_dp.npz').read_bytes()).hexdigest(),diagnostic_DP_sha256=hashlib.sha256((HERE/'diagnostic_free_only_dp.npz').read_bytes()).hexdigest(),model_and_calibration_unchanged=True,generation_prior_unchanged=True,production_candidate_unchanged=True,
    feasible_action_contract='q0 V=W, report illegal; q1/2 report legal only public current p>0 within max2 research state; true quota2; false q-1; correctcount2 healthy absorption',all_states_checked=checked,all_state_Bellman_error=maxerr,exhaustive_two_epoch_trees=trees,max_tree_error=treeerr,
    illustrative_last_free_shadow_price={'future_certain_fault_science_recovery':400,'future_correct_reward':100,'paid_Bellman_q0_vs_q1_shadow':0,'deployed_free_only_q0_vs_q1_shadow':500},
    limitations='Only action-set mismatch repaired in diagnostic DP. Same fixed-action kernels, posterior and missing baseline controller remain. No production permission or new test claim.')
(HERE/'free_only_contract_checks.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
