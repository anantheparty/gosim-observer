"""Independent spherical containment and frozen-utility/matching checks."""
from __future__ import annotations
import ctypes
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('global_field_experiment',BASE/'research/global_field_experiment.py')
ex=importlib.util.module_from_spec(spec);sys.modules[spec.name]=ex;spec.loader.exec_module(ex)

def main():
    _,Workflow,Grid,Planner,load_native,upper_rates,_,_=ex.prepare()
    from research.spatial_candidates import SpatialPlanner,parse_utc,local_sidereal
    p=Planner(Workflow(ex.OFFICIAL/'local-cards/L1').initialize_payload(900))
    lib=load_native();array=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
    lib.global_field_bound.argtypes=[ctypes.c_int,array,array,array];lib.global_field_bound.restype=ctypes.c_double
    lib.global_field_point_rate.argtypes=[ctypes.c_int,array,array,ctypes.c_double,ctypes.c_double];lib.global_field_point_rate.restype=ctypes.c_double
    label=np.load(ex.OUT/'micro_L1.npz');rng=np.random.default_rng(2601004)
    vec=label['vectors'];alts=np.arcsin(np.clip(vec[:,2],-1,1))/np.pi*180
    azs=np.arctan2(vec[:,1],vec[:,0])/np.pi*180%360
    cases=0;gap=0.;focus_cases=0
    for trial in range(250):
        seed=int(rng.choice(label['useful']));near=np.flatnonzero(np.einsum('ij,j->i',vec,vec[seed])>np.cos(2.4*np.pi/180))
        idx=rng.choice(near,size=min(12,len(near)),replace=False)
        k=np.full(p.n,.003);k[idx]=rng.uniform(.0003,.01,len(idx))
        up=np.full(p.n,3600.);up[idx]=rng.integers(300,3601,len(idx))
        scores=np.zeros(p.n);scores[idx]=rng.uniform(0.,12.,len(idx))
        factors=np.ones(p.n);factors[idx]=rng.choice([0.,.3,.5,1.],len(idx))
        mult=np.ones((3,p.n));bands=rng.integers(0,3,len(idx))
        for program in range(3):mult[program,idx[bands==program]]=p.multipliers[program]
        missing=np.zeros(p.n,dtype=bool);missing[idx]=rng.random(len(idx))<.3
        rr=np.zeros(p.n);rt=np.zeros(p.n);rd=np.full(p.n,np.inf);ub=np.zeros(p.n);urg=np.ones(p.n)
        ub[idx]=rng.uniform(-3.,3.,len(idx));urg[idx]=rng.uniform(1.,2.,len(idx))
        focus=None;membership=np.zeros(p.n,dtype=bool)
        if trial%2 and len(idx)>=3:
            membership[idx[:3]]=True;focus=(membership,60.,2,.5,1800.)
            rr[membership]=30.;rt[membership]=.5;rd[membership]=1800.;focus_cases+=1
        frame=(vec,up,k,scores,factors,mult,missing,rr,rt,rd,ub,urg,3600,1.1,focus)
        rates=upper_rates(p,frame)
        data=np.ascontiguousarray(np.column_stack((alts[idx],azs[idx],k[idx],up[idx],scores[idx],factors[idx],p.weight[idx],
               urg[idx],missing[idx],rr[idx],rt[idx],rd[idx],ub[idx],rates[idx],mult[:,idx].T,membership[idx])),dtype=float)
        cfg=np.ascontiguousarray([4,p.pitch,p.glass,60,3600,1.1,.5,50,.5,0.,256,16,
                                  2 if focus is not None else 0,60. if focus is not None else 0.,.5,1800.,28.,90.],dtype=float)
        a,z=float(alts[seed]),float(azs[seed]);width=float(rng.uniform(.02,2.))
        box=np.ascontiguousarray([max(0,a-width),min(90,a+width),z-width/max(.05,np.cos(a*np.pi/180)),z+width/max(.05,np.cos(a*np.pi/180))])
        bound=lib.global_field_bound(len(data),data,cfg,box)
        for j in range(10):
            center=(float(rng.uniform(box[0],box[1])),float(rng.uniform(box[2],box[3])))
            actual=SpatialPlanner._evaluate(p,center,idx,*frame)
            parent=0. if actual is None else actual[0]
            native=lib.global_field_point_rate(len(data),data,cfg,*center)
            # Native includes deadline breakpoints missing from the old evaluator;
            # it can improve the rate, but cannot be below the exact old family.
            assert native+2e-10>=parent,(trial,center,parent,native)
            assert bound+2e-9>=native,(trial,center,bound,native)
            gap=max(gap,native-parent);cases+=1
    result=dict(trials=250,point_cases=cases,focus_trials=focus_cases,geometry_bound_violations=0,
                parent_family_dominance_violations=0,max_native_rate_gain=gap)
    (ex.OUT/'utility_bound_verify.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)

if __name__=='__main__':main()
