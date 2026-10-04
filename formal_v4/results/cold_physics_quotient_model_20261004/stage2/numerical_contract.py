"""Predeclared float32-vs-float64 export bounds, not an observed pass receipt."""
import math
import numpy as np
U32=2.**-24

def gamma(n):
    if n*U32>=1:raise ValueError('invalid rounding model size')
    return n*U32/(1-n*U32)

def forward_error_bound(x,layers,input_error=None):
    """Conservative sequential float32 dot/add error; FMA is covered.

    Inputs/weights are the exact decoded float32 values on both sides. TF32,
    reduced precision accumulation and nondeterministic training math disabled.
    Optional input_error includes preprocessing mismatch. ReLU is 1-Lipschitz.
    """
    a=np.asarray(x,np.float64);err=np.zeros_like(a) if input_error is None else np.asarray(input_error,np.float64)
    trace=[]
    for j,(weight,bias) in enumerate(layers):
        w=np.asarray(weight,np.float64);b=np.asarray(bias,np.float64)
        prop=np.einsum('bi,oi->bo',err,abs(w),optimize=False)
        absolute=np.einsum('bi,oi->bo',abs(a)+err,abs(w),optimize=False)
        err=prop+gamma(w.shape[1]+2)*(absolute+abs(b))+2e-12
        a=np.einsum('bi,oi->bo',a,w,optimize=False)+b
        if j+1<len(layers):a=np.maximum(a,0)
        trace.append(dict(width=w.shape[1],gamma=gamma(w.shape[1]+2),max_bound=float(err.max())))
    return err,trace

def distribution_gain_bound(prob_a,prob_b,mu_a,mu_b,sigma_a,sigma_b,wm_max):
    """Couple two normals by the same Z; capped score is wm-Lipschitz in log R.

    The probability-law term uses total variation; all component gains in[0,wm].
    Atom and band probabilities are joint. Future scale does not enlarge bound.
    """
    tv=.5*np.abs(prob_a-prob_b).sum(axis=(1,2))
    displacement=np.max(abs(mu_a-mu_b)+math.sqrt(2/math.pi)*abs(sigma_a-sigma_b),axis=(1,2))
    return np.asarray(wm_max)*(tv+displacement+8e-8)

def action_certificate(values_a,values_b,error_bound):
    ia=int(np.argmax(values_a));ib=int(np.argmax(values_b))
    gap=float(values_a[ia]-np.max(np.delete(values_a,ia))) if len(values_a)>1 else math.inf
    stable=all(values_a[ia]-values_a[j]>error_bound[ia]+error_bound[j] for j in range(len(values_a)) if j!=ia)
    if stable and ia!=ib:raise AssertionError('certified winner changed')
    if ia!=ib and abs(values_a[ia]-values_a[ib])>error_bound[ia]+error_bound[ib]+2e-12:
        raise AssertionError('uncertified action change exceeds value error bound')
    return dict(index_a=ia,index_b=ib,certified=stable,margin=gap,same_action=ia==ib)
