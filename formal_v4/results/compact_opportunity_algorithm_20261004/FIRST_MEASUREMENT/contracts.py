"""Only new pattern master, oracle and dual repair mechanics; no scorer precision rerun."""
from __future__ import annotations
import os,sys,time
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
sys.dont_write_bytecode=True
import itertools,json,resource
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
import pattern_master as pm
ROOT=Path(__file__).resolve().parent

class Cost:
    stop_type=RuntimeError
    def __init__(self):self.start=time.perf_counter();self.stages=[]
    def check(self):pass
    def rss(self):return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

def full_pattern(n,nfib,cols,b,blocked):
    rows=[];scores=[];endpoints=np.unique(np.asarray([[c['start'],c['end']] for c in cols]).ravel())
    for e,c in enumerate(cols):
        if c['start']<blocked and c['end']>0:continue
        cells=[[-1]+np.flatnonzero(c['fiber']==f).tolist() for f in range(nfib)]
        for choice in itertools.product(*cells):
            selected=[i for i in choice if i>=0]
            a=np.zeros(n+len(endpoints)-1);a[c['target'][selected]]=1
            left=np.searchsorted(endpoints,c['start']);right=np.searchsorted(endpoints,c['end']);a[n+left:n+right]=1
            rows.append(a);scores.append(float(np.maximum(0.,c['c'][selected]-b[c['target'][selected]]).sum()))
    if not rows:return 0.,np.zeros((n+len(endpoints)-1,0)),np.zeros(0)
    A=np.asarray(rows).T;lp=linprog(-np.asarray(scores),A_ub=A,b_ub=np.ones(A.shape[0]),bounds=(0,None),options=dict(threads=1))
    if not lp.success:raise RuntimeError(lp.message)
    return float(-lp.fun),A,np.asarray(scores)

def compact(n,nfib,cols,b,blocked):
    ne=sum(len(c['target']) for c in cols);na=len(cols);endpoints=np.unique(np.asarray([[c['start'],c['end']] for c in cols]).ravel())
    A=np.zeros((n+na*nfib+len(endpoints)-1,ne+na));rhs=np.r_[np.ones(n),np.zeros(na*nfib),np.ones(len(endpoints)-1)]
    value=np.zeros(ne+na);at=0;upper=np.full(ne+na,np.inf)
    for e,c in enumerate(cols):
        for k,(i,f,s) in enumerate(zip(c['target'],c['fiber'],c['c'])):
            A[i,at+k]=1;A[n+e*nfib+f,at+k]=1;value[at+k]=max(0.,s-b[i])
        for f in range(nfib):A[n+e*nfib+f,ne+e]=-1
        left=np.searchsorted(endpoints,c['start']);right=np.searchsorted(endpoints,c['end']);A[n+na*nfib+left:n+na*nfib+right,ne+e]=1
        if c['start']<blocked and c['end']>0:upper[ne+e]=0
        at+=len(c['target'])
    lp=linprog(-value,A_ub=A,b_ub=rhs,bounds=np.c_[np.zeros(ne+na),upper],options=dict(threads=1))
    if not lp.success:raise RuntimeError(lp.message)
    return float(-lp.fun)

def main():
    rng=np.random.default_rng(20261004411);records=[];trace_all=[];incomplete=None
    for case in range(8):
        n=5;nfib=3;cols=[]
        for e in range(6):
            start=float(rng.integers(0,4));duration=float(rng.integers(1,4))
            cols.append(dict(start=start,end=start+duration,target=np.arange(n),fiber=rng.integers(0,nfib,n),c=rng.uniform(.05,3,n)))
        b=rng.uniform(0,.5,n)
        for blocked in (0.,1.,2.5):
            full,A,v=full_pattern(n,nfib,cols,b,blocked);old=compact(n,nfib,cols,b,blocked)
            graph=pm.PatternGraph(n,nfib,cols);trace=[];cg,sigma,lam,support=graph.solve(b,blocked,0.,Cost(),'tiny',trace)
            if not cg['converged'] or abs(full-old)>1e-8 or abs(full-cg['value'])>1e-7:raise RuntimeError('Pattern equivalence failed')
            for row in trace:
                if row.get('restricted_primal',row.get('value'))>full+1e-7 or row['full_feasible_dual_upper']<full-1e-7:raise RuntimeError('Certificate does not contain full LP')
            # Independent exhaustive full-pattern separation at arbitrary nonnegative prices.
            arbitrary_sigma=rng.uniform(0,2,n);arbitrary_lam=rng.uniform(0,1,graph.nt)
            allowed=~((graph.starts<blocked)&(graph.ends>0))
            oracle,_,_=graph.oracle(graph.gain(b),arbitrary_sigma,arbitrary_lam,allowed)
            brute=max(0.,float(np.max(v-A.T@np.r_[arbitrary_sigma,arbitrary_lam]))) if len(v) else 0.
            oracle_value=max(0.,float(np.max(oracle)))
            if abs(brute-oracle_value)>1e-8:raise RuntimeError('Full pattern pricing differs from fiber oracle')
            control=graph.greedy(b,blocked,0.,support)
            if control['increment']>full+1e-7:raise RuntimeError('Physical control above finite LP')
            records.append(dict(case=case,blocked_until=blocked,full_pattern_LP=full,edge_LP=old,CG=cg,
                integer_control=control['increment'],oracle_brute_error=brute-oracle_value))
            trace_all.extend(trace)
            if incomplete is None and len(trace)>1:
                previous=pm.MAX_ROUNDS;pm.MAX_ROUNDS=1;short=[]
                early,_,_,_=pm.PatternGraph(n,nfib,cols).solve(b,blocked,0.,Cost(),'deliberate_one_round',short)
                pm.MAX_ROUNDS=previous
                if early['converged'] or not(early['value']<=full+1e-7<=early['full_feasible_dual_upper']+2e-7):raise RuntimeError('Incomplete certificate contract failed')
                incomplete=dict(full=full,early=early,trace=short)
    output=dict(all_passed=True,cases=records,deliberate_incomplete=incomplete,full_pattern_enumeration=True,
        old_official_precision_tests_repeated=False,scope='new pattern transform, pricing separation and feasible dual repair')
    (ROOT/'PATTERN_CONTRACTS.json').write_text(json.dumps(output,indent=2)+'\n')
    (ROOT/'CONTRACT_PRICING_TRACE.json').write_text(json.dumps(trace_all,indent=2)+'\n')
    print(json.dumps(dict(all_passed=True,cases=len(records),deliberate_incomplete=incomplete is not None)))

if __name__=='__main__':main()
