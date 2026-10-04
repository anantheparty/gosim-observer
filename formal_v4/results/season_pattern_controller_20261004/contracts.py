"""New shared-oracle/interval-DP/bounds contracts; no formal world/truth loader."""
import os,sys,time,itertools,json
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/'baseline_package'))
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from types import SimpleNamespace
from shared_graph import SharedGraph,Budget
from target_dual_dp import interval_path,oracle,solve

def fixture(seed):
 rng=np.random.default_rng(seed);g=SharedGraph.__new__(SharedGraph);g.n=6;g.nfib=2;g.nd=3;g.ns=3;g.nt=0
 p=SimpleNamespace(n=6,nfib=2,weight=rng.uniform(.5,2,6),multipliers=np.array([1.2,1.12,1.06]),mismatch=1.)
 g.p=p;g.factor=rng.uniform(.05,1,(3,3,6));g.band=rng.integers(0,3,(3,3,6),dtype=np.uint8);g.eligible=rng.integers(0,2,(3,3,6),dtype=np.uint8)
 g.offset=np.arange(0,6*6+1,6,dtype=np.int32);g.target=np.tile(np.arange(6,dtype=np.int32),6);g.fiber=rng.integers(0,2,36,dtype=np.uint8);g.field_start=np.repeat(np.arange(3,dtype=np.int32),2)
 g.af=np.repeat(np.arange(6,dtype=np.int32),9);g.ad=np.tile(np.repeat(np.arange(3,dtype=np.uint8),3),6);g.ap=np.tile(np.arange(3,dtype=np.uint8),18);g.na=len(g.af)
 g.starts=np.array([0.,1200.,2700.])[g.field_start[g.af]];g.ends=g.starts+np.array(g.durations)[g.ad]
 g.endpoints=np.unique(np.r_[g.starts,g.ends]);g.nt=len(g.endpoints)-1;g.left=np.searchsorted(g.endpoints,g.starts).astype(np.int32);g.right=np.searchsorted(g.endpoints,g.ends).astype(np.int32)
 g.interval_group=np.ascontiguousarray(g.field_start[g.af]*g.nd+g.ad,dtype=np.int32);g.budget=Budget(30,1536)
 return g,rng.uniform(0,.5,6),rng

def full_lp(g,b):
 rows=[];cols=[];values=[]
 for e in range(g.na):
  f=g.af[e];s=g.field_start[f];d=g.ad[e];ids=g.target[g.offset[f]:g.offset[f+1]];fib=g.fiber[g.offset[f]:g.offset[f+1]]
  choices=[[-1]+ids[(fib==k)&g.eligible[s,d,ids].astype(bool)].tolist() for k in range(g.nfib)]
  for pattern in itertools.product(*choices):
   targets=[i for i in pattern if i>=0];atoms=list(range(g.left[e],g.right[e]));col=len(values)
   rows.extend(targets+[g.n+j for j in atoms]);cols.extend([col]*(len(targets)+len(atoms)));values.append(float(np.maximum(0.,g.scores(e,np.asarray(targets,dtype=int))-b[targets]).sum()))
 A=coo_matrix((np.ones(len(rows)),(rows,cols)),shape=(g.n+g.nt,len(values))).tocsr()
 r=linprog(-np.asarray(values),A_ub=A,b_ub=np.ones(g.n+g.nt),bounds=(0,None),method='highs',options={'threads':1})
 if not r.success:raise RuntimeError(r.message)
 return float(-r.fun)

def main():
 t=time.perf_counter();records=[]
 for seed in range(12):
  g,b,rng=fixture(29100+seed);lp=full_lp(g,b);largest=0.
  for trial in range(4):
   sigma=rng.uniform(0,1,g.n);allowed=np.ones(g.na,dtype=np.uint8);actual,_=g.oracle(b,sigma,np.zeros(g.nt),allowed);reference=[]
   for e in range(g.na):
    f=g.af[e];s=g.field_start[f];d=g.ad[e];ids=g.target[g.offset[f]:g.offset[f+1]];fib=g.fiber[g.offset[f]:g.offset[f+1]]
    gain=np.maximum(0.,g.scores(e,ids)-b[ids])-sigma[ids];gain=np.where(g.eligible[s,d,ids],gain,-np.inf)
    reference.append(sum(max(0.,max(gain[fib==k],default=-np.inf)) for k in range(g.nfib)))
   largest=max(largest,float(np.max(np.abs(actual-reference))));assert largest<1e-12
   value,path,arcs=interval_path(g,actual,allowed);brute=0.
   for mask in range(1<<len(arcs)):
    chosen=[arcs[k] for k in range(len(arcs)) if mask>>k&1]
    if all(not(g.starts[a]<g.ends[z] and g.starts[z]<g.ends[a]) for a,z in itertools.combinations(chosen,2)):brute=max(brute,float(actual[chosen].sum()))
   assert abs(value-brute)<1e-10
   r=oracle(g,b,sigma,0.);assert r['control']['increment']<=lp+1e-8<=r['upper']+1e-8
  sol=solve(g,b,0.,seconds=.1,relative_gap=0.)
  assert sol['feasible_lower']<=lp+1e-8<=sol['upper']+1e-8
  assert sol['dual_master_lower']<=lp+1e-8
  for row in sol['trace']:
   assert row['best_feasible_lower']<=lp+1e-8<=row['best_upper']+1e-8
  # blocked first interval and empty future are separate new time-DP boundaries.
  empty=oracle(g,b,np.zeros(g.n),1e9);assert empty['upper']==0 and not empty['path']
  records.append(dict(seed=29100+seed,full_pattern_lp=lp,shared_oracle_max_error=largest,dp_exhaustive_subsets_passed=True,
   dual_upper=sol['upper'],bundle_lower=sol['dual_master_lower'],feasible_lower=sol['feasible_lower'],rounds=len(sol['trace'])))
 out=dict(scope='new shared incidence oracle + compressed interval DP + target-dual Kelley bounds only',cases=len(records),passed=True,elapsed_seconds=time.perf_counter()-t,records=records)
 (ROOT/'CONTRACTS.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k!='records'}))
if __name__=='__main__':main()
