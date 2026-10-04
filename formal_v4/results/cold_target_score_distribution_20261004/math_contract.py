"""Direct target scoring math; tests exercise distribution and decision semantics."""
import json, time
from pathlib import Path
import numpy as np
from target_core import K, PROGRAMS, soft_label, moments, expected_gain, first_gain, multiplier_matrix
ROOT=Path(__file__).resolve().parent

def main():
    config=json.loads((ROOT/'v4_score_config.json').read_text())
    rng=np.random.default_rng(949199)
    n=40000
    g=rng.uniform(0,1,n);b=rng.integers(0,3,n);w=rng.uniform(.05,1.7,n)
    g[:2]=[0,1]
    best=rng.uniform(0,1.2,n)*w
    prob=soft_label(g,b)
    mu,mub=moments(prob)
    m=multiplier_matrix(config)
    truth=np.maximum(0,w[:,None]*g[:,None]*m[:,b].T-best[:,None])
    approximation=expected_gain(prob,w,best,config)
    error=approximation-truth
    assert np.min(error)>-1e-12
    bound=w[:,None]*m[:,b].T/(4*K)
    assert np.max(error-bound)<1e-12
    assert np.max(abs(mu-g))<1e-12
    assert np.max(abs(mub.sum(axis=-1)-mu))<1e-12
    first=first_gain(prob,w,config)
    assert np.max(abs(first-w[:,None]*g[:,None]*m[:,b].T))<1e-12
    # Exact worst case when the factor lies at a bin midpoint and best puts
    # its hinge there. Endpoints, zero and saturation have no projection error.
    midpoint=(23+.5)/K
    mid_prob=soft_label([midpoint],[0])
    worst=expected_gain(mid_prob,[1],[1.2*midpoint],config)[0,0]
    assert abs(worst-1.2/(4*K))<1e-12
    # Correlated target scores still obey linearity of science expectation.
    scores=np.array([[1.2,0],[0,1.2]])
    ledger=np.array([.4,.4])
    additive=np.maximum(scores-ledger,0).sum(axis=1).mean()
    separate=np.maximum(scores-ledger,0).mean(axis=0).sum()
    assert additive==separate
    # The fiber assignment is fixed before truth is known. Expected value of
    # a clairvoyant per-world fiber max is not an admissible action value.
    same_fiber=np.array([[2.,0.,1.1],[0.,2.,1.1]])
    legal=np.max(same_fiber.mean(axis=0))
    clairvoyant=np.max(same_fiber,axis=1).mean()
    assert legal==1.1 and clairvoyant==2.
    # Positivepart(mean score - best) loses the high quality tail.
    true_hinge=np.maximum(np.array([0.,1.])-.6,0).mean()
    mean_hinge=max(0,.5-.6)
    assert true_hinge==.2 and mean_hinge==0.
    # g and band independence gives a different first-exposure program value.
    correlated=.5*1.2
    independent=.5*(.5*1.2+.5*1.)
    assert correlated==.6 and independent==.55
    # Same joint head for every best value preserves the hinge shape. Its
    # quantization approximation cannot jump when best changes from zero.
    joint=rng.dirichlet(np.ones(195),size=128).reshape(128,3,65)
    bs=np.linspace(0,1.3,131);curves=[]
    for value in bs:
        curves.append(expected_gain(joint,np.ones(128),np.full(128,value),config))
    curves=np.stack(curves,axis=-1);difference=np.diff(curves,axis=-1)
    assert difference.max()<1e-12 and difference.min()>=-.01-1e-12
    assert np.diff(curves,n=2,axis=-1).min()>-1e-12
    eps=.5e-6
    shifted=expected_gain(joint,np.ones(128),np.full(128,.63+eps),config)
    original=expected_gain(joint,np.ones(128),np.full(128,.63),config)
    assert np.max(abs(shifted-original))<=eps+1e-12
    out=dict(random_joint_hinge_cases=n*3,first_moment_max_error=float(np.max(abs(first-w[:,None]*g[:,None]*m[:,b].T))),
        hinge_error_max=float(np.max(error)),bound_slack_max=float(np.max(error-bound)),
        worst_case_normalized_error=worst,analytic_normalized_bound=1.2/(4*K),
        correlated_additive_expectation=additive,legal_same_fiber_value=legal,
        inadmissible_clairvoyant_fiber_value=clairvoyant,exact_hinge_example=true_hinge,
        positivepart_mean_example=mean_hinge,correlated_g_band_example=correlated,
        false_independence_g_band_example=independent,
        single_joint_head_hinge_shape_cases=int(curves.size),
        gain_is_continuous_convex_nonincreasing_and_one_lipschitz_in_best=True,
        sixdecimal_public_best_per_target_gain_error_bound=eps,
        max_sixdecimal_public_best_error_for_16_assigned_targets=16*eps,
        scope='Science additive increment only; Jain and k-of-n REQ need joint events.')
    (ROOT/'MATH_CONTRACT.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps(out))

if __name__=='__main__':main()
