"""Synthetic exact arithmetic/quota checks; no hidden source or actor tape."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import json,sys,types,time
import numpy as np
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(OUT/'strong_package'))
from sparse_native import fine_tables,max_cells
from research.spatial_candidates import SpatialPlanner
from sparse_evaluator import _evaluate as sparse_evaluate
reference_evaluate=SpatialPlanner._evaluate
rng=np.random.default_rng(4404);total=0;maximum_error=0.;start=time.perf_counter()
for case in range(1000):
 G=180;N=int(rng.integers(1,100));F=16;D=int(rng.integers(1,73))
 p=types.SimpleNamespace(n=G,nfib=F,weight=rng.uniform(.01,3,G),req_threshold=.5,uniform_threshold=.5,req_penalty=50.)
 idx=np.sort(rng.choice(G,N,replace=False)).astype(np.int64);fiber=rng.integers(F,size=N,dtype=np.int32)
 durations=np.sort(rng.integers(60,3601,size=D,dtype=np.int64));t=durations[:,None]
 up=rng.uniform(50,4000,G);k=rng.uniform(0,.01,G);k[::29]=0.;scores=rng.uniform(0,3,G);factors=rng.uniform(0,1,G)
 mult=np.where(np.arange(3)[:,None]==rng.integers(3,size=G)[None,:],np.array([1.2,1.12,1.06])[:,None],1.)
 missing=rng.random(G)<.3;rr=rng.uniform(0,80,G)*(rng.random(G)<.4);rt=rng.choice([.3,.5,.7],size=G);rd=rng.choice([60.,180.,600.,3600.,np.inf],size=G)
 ub=rng.uniform(-2,4,G);urgency=rng.uniform(1,2,G);safety=1.1
 focus=None if case%5==0 else (rng.random(G)<.4,float(rng.uniform(1,300)),int(rng.choice([1,3,7,16,20])),float(rng.choice([.3,.5,.7])),float(rng.choice([60,120,1000,3600])))
 frame=(up,k,scores,factors,mult,missing,rr,rt,rd,ub,urgency,safety,focus)
 values,cells,ecells,allowed,eligible=fine_tables(p,idx,fiber,durations,frame)
 ki=k[idx];raw=np.minimum(1.,t*ki[None,:]);robust=np.minimum(1.,t*ki[None,:]/safety)
 req_done=missing[idx][None,:]&(robust+1e-10>=p.req_threshold)
 uni_done=(factors[idx][None,:]<p.uniform_threshold)&(robust+1e-10>=p.uniform_threshold)
 reqq_done=(rr[idx][None,:]>0)&(robust+1e-10>=rt[idx][None,:])&(t<=rd[idx][None,:])
 science=np.maximum(0.,p.weight[idx][None,None,:]*raw[:,None,:]*mult[:,idx][None,:,:]-scores[idx][None,None,:])
 terminal=req_done*p.req_penalty+uni_done*ub[idx][None,:]+reqq_done*rr[idx][None,:]
 refeligible=None
 if focus is not None:
  membership,reward,left,threshold,deadline=focus
  refeligible=membership[idx][None,:]&(robust+1e-10>=threshold)&(t<=deadline)
  terminal-=refeligible*(reward/left)
 refvalue=(science+terminal[:,None,:])*urgency[idx][None,None,:]
 refallowed=t<=up[idx][None,:];refvalue=np.where(refallowed[:,None,:],refvalue,-np.inf)
 refcells=np.zeros((D,3,F));offsets=np.arange(D*3)[:,None]*F+fiber[None,:]
 np.maximum.at(refcells.ravel(),offsets.ravel(),refvalue.reshape(D*3,-1).ravel())
 assert np.array_equal(values,refvalue),('value',case,np.max(np.abs(values-refvalue)))
 assert np.array_equal(cells,refcells),('cell',case)
 assert np.array_equal(allowed,refallowed),('allowed',case)
 if focus is not None:
  assert np.array_equal(eligible,refeligible)
  refecells=np.full_like(refcells,-np.inf);refev=np.where((refeligible&refallowed)[:,None,:],refvalue,-np.inf)
  np.maximum.at(refecells.ravel(),offsets.ravel(),refev.reshape(D*3,-1).ravel())
  assert np.array_equal(ecells,refecells),('eligiblecell',case)
 C=33;f=rng.integers(F,size=(C,N),dtype=np.int32);valid=rng.random((C,N))<.8
 for row in (0,D-1):
  v=refvalue[row];a=refallowed[row];e=None if focus is None else refeligible[row]
  cc,ee=max_cells(f,valid,v,a,e,F)
  off=(np.arange(C)[:,None,None]*3*F+np.arange(3)[None,:,None]*F+f[:,None,:]).ravel()
  vv=np.where((valid&a[None,:])[:,None,:],v[None,:,:],-np.inf)
  rc=np.zeros((C,3,F));np.maximum.at(rc.ravel(),off,vv.ravel());assert np.array_equal(cc,rc),('coarse',case)
  if focus is not None:
   re=np.full_like(rc,-np.inf);ev=np.where(e[None,None,:],vv,-np.inf);np.maximum.at(re.ravel(),off,ev.ravel());assert np.array_equal(ee,re),('coarseeligible',case)
 p.tmin=60;p.glass=.632456;p.pitch=.632456;p.side=4;p.fov=2.529824
 p._classify=lambda vectors,*center:(fiber,np.ones(N,dtype=bool),np.ones(N))
 args=((45.,90.),idx,np.zeros((G,3)),up,k,scores,factors,mult,missing,rr,rt,rd,ub,urgency,3600,safety,focus)
 a=reference_evaluate(p,*args);b=sparse_evaluate(p,*args)
 assert (a is b) if a is None or b is None else (a[:4]==b[:4] and np.array_equal(a[4],b[4]) and np.array_equal(a[5],b[5])),('candidate',case,a,b)
 total+=D*3*N
result={'scope':__doc__,'cases':1000,'scored_target_program_duration_values':total,'all_value_arrays_equal':True,'all_fibre_arrays_equal':True,'all_eligibility_arrays_equal':True,'coarse_batches':2000,'fine_candidate_actions_equal':1000,'quota_cases':[1,3,7,16,20],'elapsed':time.perf_counter()-start,'numpy':np.__version__}
(OUT/('kernel_contract_linux.json' if sys.platform=='linux' else 'kernel_contract.json')).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
