"""GPU training of an ordinary MLP joint four-slot quality distribution."""
from __future__ import annotations
import json,time,math,os
from pathlib import Path
import numpy as np
import torch
from torch import nn
from predictive_core import (HORIZON,BASE_DIM,HISTORY,C,E,unpack_numpy,utility_samples)

ROOT=Path(__file__).resolve().parent
torch.set_num_threads(2)

class Model(nn.Module):
    def __init__(self,d):
        super().__init__();self.net=nn.Sequential(nn.Linear(d,128),nn.ReLU(),nn.Linear(128,128),nn.ReLU(),nn.Linear(128,196))
        with torch.no_grad():
            self.net[-1].weight.mul_(.05);self.net[-1].bias.zero_()
            ij=np.tril_indices(8)
            for k in range(4):
                for j,(a,b) in enumerate(zip(*ij)):
                    if a==b:self.net[-1].bias[36+k*36+j]=-1.
                self.net[-1].bias[4+k*8+4:4+k*8+8]=-float(k)
            self.net[-1].bias[180+15]=3.
    def forward(self,x):return self.net(x)

def losses(out,y,mask,pat):
    batch=len(y);device=y.device
    logits=out[:,:4];mu=out[:,4:36].reshape(batch,4,8)
    tri=out[:,36:180].reshape(batch,4,36)
    L=torch.zeros((batch,4,8,8),device=device)
    ij=torch.tril_indices(8,8,device=device);L[:,:,ij[0],ij[1]]=tri
    diag=torch.arange(8,device=device)
    L[:,:,diag,diag]=torch.nn.functional.softplus(L[:,:,diag,diag])+.02
    cov=L@L.transpose(-1,-2)
    mm=mask[:,None,:,None]*mask[:,None,None,:]
    cov=cov*mm+torch.diag_embed((1-mask).expand(-1,8))[:,None,:,:]
    chol=torch.linalg.cholesky(cov+torch.eye(8,device=device)*1e-6)
    r=(y[:,None,:]-mu)*mask[:,None,:]
    solved=torch.linalg.solve_triangular(chol,r[:,:,:,None],upper=False).squeeze(-1)
    logp=-.5*(solved.square().sum(-1)+2*torch.log(torch.diagonal(chol,dim1=-2,dim2=-1)).sum(-1)+mask.sum(-1)[:,None]*math.log(2*math.pi))
    nll=-torch.logsumexp(torch.log_softmax(logits,1)+logp,1)
    closure=torch.nn.functional.cross_entropy(out[:,180:196],pat,reduction='none')
    return nll+closure

def samples(out,season,normal,um,uc):
    mix,mu,L,close=unpack_numpy(out)
    k=np.searchsorted(np.cumsum(mix),um).clip(0,3)
    y=mu[k]+np.einsum('sij,sj->si',L[k],normal)
    pattern=np.searchsorted(np.cumsum(close),uc).clip(0,15)
    op=((pattern[:,None]>>np.arange(4))&1).astype(float)
    return np.exp(np.clip(y[:,:4]*.3,-5,2))*season,np.exp(np.clip(y[:,4:]*.3,-5,2))*season*.95,op

def decision_metric(outputs,features,labels,masks,evalrows,seed=9127):
    """Public synthetic high-altitude action domain; real four-slot host labels.

    Candidate durations charge an explicit time price.  This is a finite domain
    calibration/regret check and never claimed as a complete-season score.
    """
    rng=np.random.default_rng(seed);normal=rng.normal(size=(256,8));um=(np.arange(256)+.5)/256;uc=rng.random(256)
    regrets=[];point_regrets=[];mean_regrets=[];changes=0;wins=0;losses=0
    coverage=[];means=[];truths=[];closure_brier=[]
    for n,out in enumerate(outputs):
        sc=float(evalrows[n,0]);fraction=float(evalrows[n,1]);cs,zs,ops=samples(out,sc,normal,um,uc)
        actualc=np.exp(labels[n,:4]*.3)*sc;actualz=np.exp(labels[n,4:]*.3)*sc*.95;actualop=masks[n,:4]
        # Baseline latest score-likelihood point plus weak normal-efficiency prior;
        # this is explicitly not the production strong policy.
        token=features[n,(HISTORY-1)*BASE_DIM:HISTORY*BASE_DIM]
        prior=(np.log(C/sc)/.30)**2+(np.log(E/.95)/.35)**2
        idx=np.argmin(token[:len(C)]*25+.025*prior)
        pc=float(C[idx]);pe=float(E[idx])
        cp=np.asarray([sc*(pc/sc)**(.88**(k+.5)) for k in range(4)])[None,:]
        zp=cp*pe;opp=np.ones((1,4))
        emc=cs.mean(0)[None,:];emz=zs.mean(0)[None,:];emo=ops.mean(0)[None,:]
        qlow=np.quantile(zs[:,0],.05);qhigh=np.quantile(zs[:,0],.95)
        if actualop[0]:coverage.append(qlow<=actualz[0]<=qhigh);means.append(zs[:,0].mean());truths.append(actualz[0])
        closure_brier.append((float(ops[:,0].mean())-float(actualop[0]))**2)
        candidates=[]
        price=float(rng.uniform(.001,.008))
        for field in range(4):
            h=float(rng.uniform(.2,1.))*np.clip(1+rng.normal(0,.02,16),.9,1.1)
            cls=rng.choice(5,16,p=[.34,.24,.2,.14,.08])
            f=rng.lognormal(np.log(np.asarray([.55,1.25,.35,.18,4.])[cls]),np.asarray([.4,.3,.35,.5,.25])[cls])
            w=np.asarray([1.,.45,1.,1.7,.3])[cls];best=w*rng.uniform(0.,1.,16)
            for duration in [300,900,1800]:
                seconds=np.asarray([max(0.,min(duration+fraction,(k+1)*900)-max(fraction,k*900)) for k in range(4)])
                hs=np.tile(h,(4,1))
                for program in range(3):
                    vals=[]
                    for c,z,op in [(cs,zs,ops),(cp,zp,opp),(emc,emz,emo),(actualc[None,:],actualz[None,:],actualop[None,:])]:
                        vals.append(utility_samples(c,z,op,w,f,best,hs,seconds,duration,program)[0].mean()-price*duration)
                    candidates.append(vals)
        a=np.vstack([[0,0,0,0],candidates]);oracle=a[:,3].max()
        nnchoice=int(a[:,0].argmax());pointchoice=int(a[:,1].argmax());meanchoice=int(a[:,2].argmax())
        regrets.append(oracle-a[nnchoice,3]);point_regrets.append(oracle-a[pointchoice,3]);mean_regrets.append(oracle-a[meanchoice,3])
        delta=a[nnchoice,3]-a[pointchoice,3]
        changes+=nnchoice!=pointchoice;wins+=delta>1e-8;losses+=delta<-1e-8
    return dict(regret=float(np.mean(regrets)),point_regret=float(np.mean(point_regrets)),
                plug_mean_regret=float(np.mean(mean_regrets)),samples=len(outputs),changed=int(changes),wins=int(wins),losses=int(losses),
                coverage90=float(np.mean(coverage)),closure_brier=float(np.mean(closure_brier)),
                next_z_rmse=float(np.sqrt(np.mean((np.asarray(means)-truths)**2))))

def export(model,mean,std,path):
    params={}
    for k,idx in enumerate([0,2,4]):
        w=model.net[idx].weight.detach().cpu().numpy().astype(np.float64)
        b=model.net[idx].bias.detach().cpu().numpy().astype(np.float64)
        if k==0:b=b-w@(mean/std);w=w/std[None,:]
        params[f'weight{k}']=w;params[f'bias{k}']=b
    np.savez(path,**params)

def main():
    assert torch.cuda.is_available();device=torch.device('cuda');torch.manual_seed(9104);np.random.seed(9104)
    data=np.load(ROOT/'world_dataset.npz');x=data['train_x'];mean=x.mean(0);std=x.std(0);std=np.maximum(std,.10)
    model=Model(x.shape[1]).to(device);optim=torch.optim.AdamW(model.parameters(),lr=.0005,weight_decay=1e-4)
    X=torch.tensor((x-mean)/std,device=device);Y=torch.tensor(data['train_y'],device=device);M=torch.tensor(data['train_mask'].astype(np.float32),device=device);P=torch.tensor(data['train_pattern'],device=device)
    xv=data['val_x'];valindices=np.random.default_rng(441).choice(len(xv),384,replace=False)
    XV=torch.tensor((xv-mean)/std,device=device);YV=torch.tensor(data['val_y'],device=device);MV=torch.tensor(data['val_mask'].astype(np.float32),device=device);PV=torch.tensor(data['val_pattern'],device=device)
    metrics=[];best=float('inf');t=time.time();selected=None
    for epoch in range(12):
        order=torch.randperm(len(X),device=device);model.train();total=0.
        for start in range(0,len(X),512):
            idx=order[start:start+512];optim.zero_grad();loss=losses(model(X[idx]),Y[idx],M[idx],P[idx]).mean();loss.backward();nn.utils.clip_grad_norm_(model.parameters(),5.);optim.step();total+=float(loss)*len(idx)
        model.eval()
        with torch.no_grad():out=model(XV).cpu().numpy();valnll=float(losses(torch.tensor(out,device=device),YV,MV,PV).mean())
        metric=decision_metric(out[valindices],xv[valindices],data['val_y'][valindices],data['val_mask'][valindices],data['val_evalrow'][valindices])
        row=dict(epoch=epoch,train_nll=total/len(X),val_nll=valnll,seconds=time.time()-t,**metric);metrics.append(row);print(json.dumps(row),flush=True)
        if metric['regret']<best:
            best=metric['regret'];selected=epoch;export(model,mean,std,ROOT/'joint_model.npz')
    # Test labels opened once after validation selection is finished.
    from predictive_core import NumpyPredictor
    predictor=NumpyPredictor(ROOT/'joint_model.npz')
    tx=data['test_x'];testidx=np.random.default_rng(442).choice(len(tx),1024,replace=False)
    out=np.asarray([predictor.predict(row) for row in tx[testidx]])
    test=decision_metric(out,tx[testidx],data['test_y'][testidx],data['test_mask'][testidx],data['test_evalrow'][testidx],seed=9128)
    result=dict(model='ordinary MLP 1306->128->128->196',parameters=sum(p.numel() for p in model.parameters()),
                output='four full-covariance 8D logC/logZ mixture components + joint16-pattern closure',
                checkpoint_rule='minimum val nonlinear candidate regret',epochs=metrics,selected_epoch=selected,
                test=test,seconds=time.time()-t,gpu=torch.cuda.get_device_name(),max_cuda_bytes=torch.cuda.max_memory_allocated(),
                claim='Finite synthetic candidate calibration only; no production score or fullseason improvement claim')
    (ROOT/'training_result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
if __name__=='__main__':main()
