"""Small independent mathematical contracts, without loading the actual graph."""
import itertools
import json
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from fixed_graph import FixedGraph
from bundle_search import prox_trial, outside_ledger

def toy(edges, n=5, nf=2):
    g=FixedGraph.__new__(FixedGraph);g.n=n;g.nf=nf;g.starts=np.arange(len(edges),dtype=float);g.ends=g.starts+1.
    g._edge_cache={e:(np.asarray([r[0] for r in rows],dtype=int),np.asarray([r[1] for r in rows],dtype=int),
                    np.asarray([r[2] for r in rows],dtype=float)) for e,rows in enumerate(edges)}
    return g

def brute(g,b,path):
    resources=[]
    for e in path:
        ids,fib,score=g.edges(e)
        for f in range(g.nf):resources.append([None]+[(int(i),float(s)) for i,ff,s in zip(ids,fib,score) if ff==f])
    best=0.
    for items in itertools.product(*resources):
        ledger=b.copy()
        for item in items:
            if item is not None:ledger[item[0]]=max(ledger[item[0]],item[1])
        best=max(best,float((ledger-b).sum()))
    return best

def run():
    rng=np.random.default_rng(80410);rows=[]
    g=toy([[(0,0,10.),(1,0,9.)],[(0,0,10.)]],n=2,nf=1)
    c=g.match(np.zeros(2),(0,1));assert abs(c['increment']-19.)<1e-10
    rows.append(dict(name='greedy_10_vs_matching_19',gain=c['increment'],audit=g.validate(np.zeros(2),c,0.)))
    for k in range(30):
        edges=[]
        for e in range(3):
            ids=rng.choice(5,size=3,replace=False)
            edges.append([(int(i),int(rng.integers(2)),float(rng.uniform(0,3))) for i in ids])
        g=toy(edges);b=rng.uniform(0,1,5);c=g.match(b,(0,1,2));v=brute(g,b,(0,1,2))
        assert abs(c['increment']-v)<1e-9;g.validate(b,c,0.)
    rows.append(dict(name='matching_vs_full_max_ledger_enumeration',cases=30))
    g=toy([[(0,0,.1)]],n=2,nf=1);c=g.match(np.ones(2),(0,))
    assert len(c['schedule'])==1 and c['schedule'][0]['targets']==[];g.validate(np.ones(2),c,0.)
    rows.append(dict(name='empty_exposure_time_retained',cases=1))
    largest=0.
    for k in range(15):
        n=4;j=6;box=rng.uniform(.1,2,n);center=rng.uniform(0,1,n)*box;t=float(rng.uniform(.02,2))
        N=np.r_[np.zeros((1,n)),rng.integers(0,5,size=(j-1,n))];raw=np.r_[0.,rng.uniform(0,5,j-1)]
        s,lam,z=prox_trial(center,t,box,N,raw,maxiter=160,ftol=1e-12)
        def fun(x):return x[:n].sum()+x[n]+np.square(x[:n]-center).sum()/(2*t)
        def jac(x):return np.r_[1+(x[:n]-center)/t,1.]
        def constraints(x):return x[n]-raw+N@x[:n]
        direct=minimize(fun,np.r_[center,max(raw-N@center)],jac=jac,method='SLSQP',
            bounds=[(0.,m) for m in box]+[(None,None)],
            constraints=[dict(type='ineq',fun=constraints,jac=lambda x:np.c_[N,np.ones(j)])],
            options=dict(ftol=1e-10,maxiter=150))
        assert direct.success
        err=abs(z['prox_primal']-direct.fun);largest=max(largest,err)
        assert err<1e-5 and z['qp_gap']<1e-5 and abs(lam.sum()-1)<1e-10, (k,err,z,direct.fun,lam.tolist())
        assert np.all(s>=0) and np.all(s<=box+1e-10)
    rows.append(dict(name='cut_simplex_prox_vs_direct_epigraph_QP',cases=15,max_error=largest))
    branch=dict(first=np.zeros(3));control=dict(schedule=[
        dict(action=1,start=0.,end=1.,targets=[0],scores=[2.]),
        dict(action=2,start=1.,end=3.,targets=[1],scores=[3.]),
        dict(action=3,start=3.,end=4.,targets=[2],scores=[4.])])
    b,path=outside_ledger(branch,control,(1.5,2.5));assert path==[1,3] and np.array_equal(b,[2.,0.,4.])
    rows.append(dict(name='crossing_exposure_removed_and_outside_ledger_exact',cases=1))
    return dict(status='passed',actual_graph_loaded=False,rows=rows)

if __name__=='__main__':
    r=run();p=Path(__file__).resolve().parent/'CONTRACTS.json';p.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
