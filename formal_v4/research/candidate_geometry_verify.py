#!/usr/bin/env python3
"""Independent exhaustive arrangement checks for the weighted sweep kernel."""
import json
import math
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research.candidate_geometry_sweep import weighted_sweep

rng=np.random.default_rng(4771);records=[]
cases=Path(__file__).resolve().parents[1]/'results/candidate_geometry_20261003/kernel_cases'
cases.mkdir(parents=True,exist_ok=True)
for test in range(24):
    n=6+test%13;side=2+test%3;pitch=math.sqrt(.4)
    glass=pitch-(.03 if test%2 else 0);half=glass/2-.008;radius=pitch*(.5+(test%4)*.35)
    x=rng.uniform(-pitch*side/2-radius,pitch*side/2+radius,n)
    y=rng.uniform(-pitch*side/2-radius,pitch*side/2+radius,n)
    value=rng.uniform(0.,3.,(4,n));value[rng.random(value.shape)<.2]=0
    xe=np.unique(np.concatenate([[-radius,radius]]+[x-(c-(side-1)/2)*pitch+s*half for c in range(side) for s in (-1,1)]))
    ye=np.unique(np.concatenate([[-radius,radius]]+[y-(c-(side-1)/2)*pitch+s*half for c in range(side) for s in (-1,1)]))
    xe=xe[(xe>=-radius)&(xe<=radius)];ye=ye[(ye>=-radius)&(ye<=radius)]
    xx,yy=np.meshgrid((xe[1:]+xe[:-1])/2,(ye[1:]+ye[:-1])/2,indexing='ij')
    xx=xx.ravel();yy=yy.ravel();col=np.floor((x[None,:]-xx[:,None])/pitch+side/2).astype(int)
    row=np.floor((y[None,:]-yy[:,None])/pitch+side/2).astype(int)
    ok=(col>=0)&(col<side)&(row>=0)&(row<side)&(abs(x[None,:]-xx[:,None]-(col-(side-1)/2)*pitch)<half)&(abs(y[None,:]-yy[:,None]-(row-(side-1)/2)*pitch)<half)
    nf=side*side;fiber=np.clip(row,0,side-1)*side+np.clip(col,0,side-1)
    cells=np.zeros((len(xx),4,nf));offset=np.arange(len(xx))[:,None,None]*4*nf+np.arange(4)[None,:,None]*nf+fiber[:,None,:]
    np.maximum.at(cells.ravel(),offset.ravel(),np.where(ok[:,None,:],value[None,:,:],0).ravel())
    brute=cells.sum(axis=2).max(axis=0)
    bx,by,bv,visited=weighted_sweep(x,y,value,pitch,glass,side,radius,2)
    err=float(abs(bv[:,0]-brute).max());assert err<1e-10,(test,brute,bv)
    assert visited==len(xx)
    np.savez_compressed(cases/f'{test:02d}.npz',x=x,y=y,values=value,pitch=pitch,glass=glass,side=side,
                        radius=radius,keep=2,bx=bx,by=by,bv=bv,visited=visited,brute_best=brute)
    records.append(dict(test=test,targets=n,side=side,radius=radius,cells=visited,max_error=err))
out=Path(__file__).resolve().parents[1]/'results/candidate_geometry_20261003/kernel_verification.json'
out.write_text(json.dumps(dict(tests=records,max_error=max(r['max_error'] for r in records),all_passed=True),indent=2))
print(json.dumps(dict(tests=len(records),cells=sum(r['cells'] for r in records),max_error=max(r['max_error'] for r in records))))
