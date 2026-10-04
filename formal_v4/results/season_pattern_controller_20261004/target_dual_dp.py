"""Target-cap Lagrange oracle: full fibre scan + exact interval DP.

Each oracle computes a rigorous full finite deterministic LP upper bound.
Kelley cuts use concrete legal pattern paths, with safe target price boxes.
Integer controls reevaluate the max ledger and may revisit a target. Their
value is a feasible lower bound, independent of dual convergence.
"""
from __future__ import annotations
import time
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from shared_graph import LIB,ptr

def interval_path(g,values,allowed):
 # Fixed target prices make field/program alternatives of the same interval
 # interchangeable for timing. Keep the largest physical assignment weight.
 winner=np.empty(g.ns*g.nd,dtype=np.int32)
 LIB.compress_intervals(g.na,len(winner),ptr(values),ptr(g.interval_group),ptr(allowed),ptr(winner))
 arcs=winner[winner>=0];arcs=arcs[np.lexsort((arcs,g.starts[arcs],g.ends[arcs]))]
 end=g.ends[arcs];start=g.starts[arcs];previous=np.searchsorted(end,start,side='right')
 V=np.zeros(len(arcs)+1);take=np.zeros(len(arcs),dtype=bool)
 for k,e in enumerate(arcs):
  value=float(values[e])+V[previous[k]]
  if value>V[k]+1e-10:V[k+1]=value;take[k]=True
  else:V[k+1]=V[k]
 path=[];k=len(arcs)
 while k>0:
  if take[k-1]:path.append(int(arcs[k-1]));k=int(previous[k-1])
  else:k-=1
 return float(V[-1]),path[::-1],arcs

def physical_control(g,b,path):
 ledger=b.copy();schedule=[]
 for e in path:
  ids=g.pattern(e,ledger,np.zeros(g.n))
  if not ids:continue
  ids=np.asarray(ids,dtype=int);score=g.scores(e,ids);ledger[ids]=np.maximum(ledger[ids],score)
  f=int(g.af[e]);lookup={int(i):int(fi) for i,fi in zip(g.target[g.offset[f]:g.offset[f+1]],g.fiber[g.offset[f]:g.offset[f+1]])}
  schedule.append(dict(action=e,start=float(g.starts[e]),end=float(g.ends[e]),targets=ids.tolist(),fibers=[lookup[int(i)] for i in ids],scores=score.tolist()))
 return dict(increment=float((ledger-b).sum()),schedule=schedule,ledger=ledger)

def oracle(g,b,sigma,blocked_until):
 allowed=(g.starts>=blocked_until-1e-7).astype(np.uint8)
 values,_,gmax=g.oracle(b,sigma,np.zeros(g.nt),allowed,return_bestgain=True)
 value,path,arcs=interval_path(g,values,allowed)
 counts=np.zeros(g.n);raw=0.;selected=[]
 for e in path:
  ids=g.pattern(e,b,sigma);selected.append((e,ids));np.add.at(counts,list(ids),1.)
  raw+=float(np.maximum(0.,g.scores(e,np.asarray(ids,dtype=int))-b[list(ids)]).sum())
 D=float(sigma.sum()+value)
 if abs(D-(sigma.sum()+raw-counts@sigma))>1e-6:raise RuntimeError('DP path and full-fiber reduced value mismatch')
 control=physical_control(g,b,path)
 if control['increment']>D+1e-6:raise RuntimeError('physical max-ledger schedule exceeds target dual upper')
 return dict(upper=D,control=control,path=path,counts=counts,raw=raw,gradient=1.-counts,gmax=gmax,
  compressed_interval_arcs=len(arcs),full_action_scan=g.na,selected_patterns=selected)

def solve(g,b,blocked_until,seconds=3.,sigma0=None,relative_gap=.005):
 start=time.perf_counter();deadline=min(start+seconds,g.budget.start+g.budget.limit)
 sigma=np.zeros(g.n) if sigma0 is None else np.maximum(0.,np.asarray(sigma0).copy())
 best_upper=np.inf;best_control=None;best_sigma=None;cuts=[];trace=[];master_lower=0.;gmax=None;paths=[]
 while time.perf_counter()<deadline:
  g.budget.check();t=time.perf_counter();r=oracle(g,b,sigma,blocked_until)
  paths.append(r['path'])
  if r['upper']<best_upper:best_upper=r['upper'];best_sigma=sigma.copy()
  if gmax is None:gmax=r['gmax']
  if best_control is None or r['control']['increment']>best_control['increment']:best_control=r['control']
  gap=best_upper-best_control['increment'];dualgap=best_upper-master_lower
  row=dict(iteration=len(trace)+1,upper=r['upper'],best_upper=best_upper,best_feasible_lower=best_control['increment'],feasible_gap=gap,
   dual_master_lower=master_lower,dual_gap=dualgap,oracle_seconds=time.perf_counter()-t,elapsed_seconds=time.perf_counter()-start,
   positive_prices=int(np.count_nonzero(sigma)),compressed_interval_arcs=r['compressed_interval_arcs'],full_actions=r['full_action_scan'],path_exposures=len(r['path']))
  trace.append(row)
  if gap<=max(1e-7,relative_gap*max(1.,best_upper)):row['stop']='feasible_bound_gap';break
  cuts.append((r['counts'],r['raw']))
  rows=[];cols=[];data=[];rhs=[]
  for k,(counts,raw) in enumerate(cuts):
   ids=np.flatnonzero(counts);rows.extend([k]*(len(ids)+1));cols.extend(ids.tolist()+[g.n]);data.extend((-counts[ids]).tolist()+[-1.]);rhs.append(-raw)
  A=coo_matrix((data,(rows,cols)),shape=(len(cuts),g.n+1)).tocsr();t=time.perf_counter()
  lp=linprog(np.ones(g.n+1),A_ub=A,b_ub=np.asarray(rhs),bounds=np.c_[np.zeros(g.n+1),np.r_[gmax,np.inf]],method='highs',options={'threads':1,'time_limit':max(.001,deadline-time.perf_counter())})
  row['bundle_master_seconds']=time.perf_counter()-t
  if not lp.success:row['stop']='bundle_master_budget';row['message']=lp.message;break
  master_lower=max(master_lower,float(lp.fun));sigma=np.maximum(0.,lp.x[:g.n])
  if master_lower>best_upper+1e-6:raise RuntimeError('Kelley master lower exceeds feasible finite dual upper')
  if best_upper-master_lower<=max(1e-7,relative_gap*max(1.,best_upper)):row['stop']='dual_bound_gap';break
 if best_control is None:return None
 return dict(upper=float(best_upper),feasible_lower=float(best_control['increment']),feasible_gap=float(best_upper-best_control['increment']),
  dual_master_lower=master_lower,dual_gap=float(best_upper-master_lower),sigma=best_sigma,control=best_control,trace=trace,paths=paths,
  elapsed_seconds=time.perf_counter()-start,stop=trace[-1].get('stop','time_budget'),converged=best_upper-master_lower<=1e-7,
  model='deterministic finite shared-exposure LP bound; target Lagrange plus exact interval path',
  no_time_solver_rows=True,no_exposure_solver_variables=True)
