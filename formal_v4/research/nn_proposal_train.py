"""A small conventional MLP, trained on owned PRO6000 with Numba CUDA.

Standalone numeric training only. No service, API, platform or power changes.
"""
from __future__ import annotations
import argparse, hashlib, json, math, time
from pathlib import Path
import numpy as np


def numpy_predict(x, model):
    x=(x-model['xmean'])/model['xscale']
    # Explicit contractions avoid platform BLAS floating status flags and keep
    # deployment independent of a Torch/CUDA runtime.
    hidden=np.maximum(0,np.einsum('ij,jk->ik',x,model['w1'],optimize=False)+model['b1'])
    return (np.einsum('ij,j->i',hidden,model['w2'],optimize=False)+model['b2'])*model['yscale']+model['ymean']


def train(directory, steps=2000, batch=512, width=64):
    from numba import cuda
    directory=Path(directory); data=np.load(directory/'dataset.npz'); manifest=json.loads((directory/'data_manifest.json').read_text())
    x=data['x']; y=np.log1p(data['y']); group=data['group']
    train_groups=[g['group'] for g in manifest['groups'] if g['card'] in ('L1','L2') and g['night']<20]
    training=np.isin(group,train_groups); assert training.any() and (~training).any()
    mean=x[training].mean(axis=0); scale=np.maximum(x[training].std(axis=0),.01)
    ymean=float(y[training].mean()); yscale=max(float(y[training].std()),.01)
    xx=np.ascontiguousarray((x-mean)/scale,dtype=np.float32); yy=np.asarray((y-ymean)/yscale,dtype=np.float32)
    weights=np.ones(len(y),np.float32)
    for g in train_groups:
        rows=np.flatnonzero(group==g); weights[rows[y[rows]>=np.quantile(y[rows],.9)]]=4
    rng=np.random.default_rng(261003); nfeatures=x.shape[1]
    w1=np.asarray(rng.normal(0,math.sqrt(2/nfeatures),(nfeatures+1,width)),np.float32); w1[-1]=0
    w2=np.asarray(rng.normal(0,math.sqrt(1/width),width+1),np.float32);w2[-1]=0
    dx=cuda.to_device(xx); dy=cuda.to_device(yy); dw=cuda.to_device(weights)
    d1=cuda.to_device(w1);d2=cuda.to_device(w2)
    m1=cuda.to_device(np.zeros_like(w1));v1=cuda.to_device(np.zeros_like(w1))
    m2=cuda.to_device(np.zeros_like(w2));v2=cuda.to_device(np.zeros_like(w2))
    ids=cuda.to_device(np.zeros(batch,np.int32)); hidden=cuda.device_array((batch,width),np.float32)
    out=cuda.device_array(batch,np.float32); delta=cuda.device_array(batch,np.float32)
    dh=cuda.device_array((batch,width),np.float32)

    @cuda.jit
    def activate(x,rows,w,h):
        i,j=cuda.grid(2)
        if i<h.shape[0] and j<h.shape[1]:
            total=w[x.shape[1],j]
            for f in range(x.shape[1]):total+=x[rows[i],f]*w[f,j]
            h[i,j]=max(0,total)

    @cuda.jit
    def predict(h,w,o):
        i=cuda.grid(1)
        if i<o.size:
            value=w[h.shape[1]]
            for j in range(h.shape[1]):value+=h[i,j]*w[j]
            o[i]=value

    @cuda.jit
    def loss_delta(rows,y,weights,o,delta):
        i=cuda.grid(1)
        if i<o.size:
            error=o[i]-y[rows[i]]; pair=i^1
            pair_error=o[pair]-y[rows[pair]]
            # Within-state paired differences supervise ranking as well as
            # absolute local value. Interleaved rows come from one state.
            delta[i]=(2*weights[rows[i]]*error+.5*(error-pair_error))/o.size

    @cuda.jit
    def hidden_delta(h,delta,w,dh):
        i,j=cuda.grid(2)
        if i<dh.shape[0] and j<dh.shape[1]:dh[i,j]=delta[i]*w[j] if h[i,j]>0 else 0

    @cuda.jit
    def update1(x,rows,dh,w,m,v,step,lr):
        f,j=cuda.grid(2)
        if f<w.shape[0] and j<w.shape[1]:
            gradient=0.
            for i in range(dh.shape[0]):gradient+=dh[i,j]*(1 if f==x.shape[1] else x[rows[i],f])
            gradient=max(-10.,min(10.,gradient))
            m[f,j]=.9*m[f,j]+.1*gradient;v[f,j]=.999*v[f,j]+.001*gradient*gradient
            w[f,j]-=lr*(m[f,j]/(1-.9**step))/(math.sqrt(v[f,j]/(1-.999**step))+1e-8)

    @cuda.jit
    def update2(h,delta,w,m,v,step,lr):
        j=cuda.grid(1)
        if j<w.size:
            gradient=0.
            for i in range(delta.size):gradient+=delta[i]*(1 if j==h.shape[1] else h[i,j])
            gradient=max(-10.,min(10.,gradient))
            m[j]=.9*m[j]+.1*gradient;v[j]=.999*v[j]+.001*gradient*gradient
            w[j]-=lr*(m[j]/(1-.9**step))/(math.sqrt(v[j]/(1-.999**step))+1e-8)

    groups={g:np.flatnonzero(group==g).astype(np.int32) for g in train_groups}
    start=time.perf_counter(); history=[]
    for step in range(1,steps+1):
        selected=int(rng.choice(train_groups)); rows=rng.choice(groups[selected],batch)
        ids.copy_to_device(rows.astype(np.int32))
        activate[((batch+15)//16,(width+7)//8),(16,8)](dx,ids,d1,hidden)
        predict[(batch+127)//128,128](hidden,d2,out)
        loss_delta[(batch+127)//128,128](ids,dy,dw,out,delta)
        hidden_delta[((batch+15)//16,(width+7)//8),(16,8)](hidden,delta,d2,dh)
        update1[((nfeatures+1+7)//8,(width+7)//8),(8,8)](dx,ids,dh,d1,m1,v1,step,.001)
        update2[(width+1+63)//64,64](hidden,delta,d2,m2,v2,step,.001)
        if step%250==0 or step==steps:
            cuda.synchronize(); got=out.copy_to_host();loss=float(np.mean((got-yy[rows])**2))
            record={'step':step,'sampled_group':selected,'batch_MSE_standardized':loss,'elapsed_seconds':time.perf_counter()-start}
            history.append(record);print(json.dumps(record),flush=True)
            ww1=d1.copy_to_host();ww2=d2.copy_to_host()
            activate[((batch+15)//16,(width+7)//8),(16,8)](dx,ids,d1,hidden)
            predict[(batch+127)//128,128](hidden,d2,out)
            actual=out.copy_to_host()
            expected=np.maximum(0,xx[rows]@ww1[:-1]+ww1[-1])@ww2[:-1]+ww2[-1]
            forward_error=float(np.max(np.abs(actual-expected)))
            assert forward_error<1e-4, forward_error
            record['CUDA_CPU_forward_max_error']=forward_error
            np.savez(directory/'model.npz',w1=ww1[:-1],b1=ww1[-1],w2=ww2[:-1],b2=ww2[-1],
                     xmean=mean,xscale=scale,ymean=np.float32(ymean),yscale=np.float32(yscale))
            (directory/'train_progress.json').write_text(json.dumps({'status':'complete' if step==steps else 'running',
                'seed':261003,'device':str(cuda.get_current_device().name),'width':width,'steps':steps,'batch':batch,
                'train_groups':train_groups,'train_rows':int(training.sum()),'heldout_rows':int((~training).sum()),
                'objective':'top-decile weighted squared log-local-value plus within-state pair difference regression',
                'history':history,'elapsed_seconds':time.perf_counter()-start},indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--steps',type=int,default=2000)
    p.add_argument('--batch',type=int,default=512);p.add_argument('--width',type=int,default=64)
    a=p.parse_args();train(a.directory,a.steps,a.batch,a.width)
