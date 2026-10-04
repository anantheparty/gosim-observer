"""Ordinary GPU classifier; calibration and causal small quota DP."""
from __future__ import annotations
import json,time
from pathlib import Path
import numpy as np
import torch
from torch import nn
from report_core import ReportModel,build_dp
ROOT=Path(__file__).resolve().parent
torch.set_num_threads(2)

def metrics(p,y):
    p=np.clip(np.asarray(p),1e-8,1-1e-8);y=np.asarray(y)
    bins=[]
    for lo,hi in zip([0,.01,.05,.10,.20,.35,.50,.65,.80,.90,.95],[.01,.05,.10,.20,.35,.50,.65,.80,.90,.95,1.01]):
        s=(p>=lo)&(p<hi)
        if s.any():bins.append(dict(low=lo,high=hi,count=int(s.sum()),pred=float(p[s].mean()),actual=float(y[s].mean())))
    return dict(nll=float(np.mean(-y*np.log(p)-(1-y)*np.log(1-p))),brier=float(np.mean((p-y)**2)),prevalence=float(y.mean()),mean=float(p.mean()),bins=bins)

def export(model,mean,std,path,scale=1.,bias=0.):
    params={'cal_scale':scale,'cal_bias':bias}
    for k,j in enumerate([0,2,4]):
        w=model[j].weight.detach().cpu().numpy().astype(np.float64);b=model[j].bias.detach().cpu().numpy().astype(np.float64)
        if k==0:b=b-w@(mean/std);w=w/std
        params[f'weight{k}']=w;params[f'bias{k}']=b
    np.savez(path,**params)

def predict_torch(model,x,mean,std,device):
    out=[]
    with torch.no_grad():
        for j in range(0,len(x),4096):out.append(model(torch.tensor((x[j:j+4096]-mean)/std,device=device)).cpu().numpy()[:,0])
    return np.concatenate(out)

def main():
    assert torch.cuda.is_available();device=torch.device('cuda');torch.manual_seed(82191)
    started=time.time();data=np.load(ROOT/'report_dataset.npz');x=data['train_x'];mean=x.mean(0);std=np.maximum(x.std(0),.1)
    model=nn.Sequential(nn.Linear(x.shape[1],128),nn.ReLU(),nn.Linear(128,128),nn.ReLU(),nn.Linear(128,1)).to(device)
    opt=torch.optim.AdamW(model.parameters(),lr=.0007,weight_decay=1e-4)
    # Counterfactual next report labels teach exact public report information and repair dynamics.
    rng=np.random.default_rng(821);add=rng.choice(len(x),min(45000,len(x)),replace=False)
    X=np.concatenate([x,data['train_xr'][add],data['train_xw'][add]])
    Y=np.concatenate([data['train_y'],data['train_yr'][add],data['train_yw'][add]])
    XT=torch.tensor((X-mean)/std,device=device);YT=torch.tensor(Y.astype(np.float32),device=device)
    calx=data['cal_x'];caly=data['cal_y'];best=1e9;epochs=[];beststate=None
    for epoch in range(16):
        order=torch.randperm(len(XT),device=device);total=0.
        for start in range(0,len(XT),1024):
            ix=order[start:start+1024];opt.zero_grad();loss=nn.functional.binary_cross_entropy_with_logits(model(XT[ix])[:,0],YT[ix]);loss.backward();opt.step();total+=float(loss)*len(ix)
        z=predict_torch(model,calx,mean,std,device);p=1/(1+np.exp(-np.clip(z,-40,40)));m=metrics(p,caly)
        row=dict(epoch=epoch,train_nll=total/len(XT),cal_nll=m['nll'],cal_brier=m['brier'],seconds=time.time()-started);epochs.append(row);print(json.dumps(row),flush=True)
        if m['nll']<best:best=m['nll'];selected=epoch;beststate={k:v.detach().clone() for k,v in model.state_dict().items()}
    model.load_state_dict(beststate)
    z=torch.tensor(predict_torch(model,calx,mean,std,device),device=device);cy=torch.tensor(caly.astype(np.float32),device=device)
    a=torch.tensor(1.,device=device,requires_grad=True);b=torch.tensor(0.,device=device,requires_grad=True)
    optimizer=torch.optim.LBFGS([a,b],lr=.3,max_iter=60,line_search_fn='strong_wolfe')
    def closure():
        optimizer.zero_grad();loss=nn.functional.binary_cross_entropy_with_logits(z*a+b,cy);loss.backward();return loss
    optimizer.step(closure);scale=float(a.detach());bias=float(b.detach())
    export(model,mean,std,ROOT/'report_model.npz',scale,bias)
    pred=ReportModel(ROOT/'report_model.npz');cal=metrics(pred.posterior(calx),caly);val=metrics(pred.posterior(data['val_x']),data['val_y'])
    probs=[]
    for name in ['x','xw','xr']:
        v=predict_torch(model,data[f'train_{name}'],mean,std,device)
        probs.append(1/(1+np.exp(-np.clip(v*scale+bias,-40,40))))
    dp=build_dp(*probs,data['train_y'],data['train_loss'],data['train_phase'],data['train_quake'],data['train_correct'],data['train_xw'],data['train_xr'])
    np.savez_compressed(ROOT/'report_dp.npz',**dp)
    # Export gate at public features; full float64 CUDA vs NumPy outputs.
    ix=np.random.default_rng(742).choice(len(calx),128,replace=False)
    raw=predict_torch(model,calx[ix],mean,std,device);cpu=pred.logit(calx[ix]);maxerr=float(np.max(np.abs(raw-cpu)))
    result=dict(model='ordinary MLP 1568->128->128->1',gpu=torch.cuda.get_device_name(),epochs=epochs,selected_epoch=selected,
        calibration=dict(scale=scale,bias=bias),cal=cal,val=val,gate_float32_gpu_numpy_max_logit_error=maxerr,
        max_cuda_bytes=int(torch.cuda.max_memory_allocated()),seconds=time.time()-started,test_unopened=True,
        DP='1024 finite epochs; quota0/1/2; posterior15bins x quake3 x public correct_count3; causal coupled one-step kernels, shrink32')
    (ROOT/'training_result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
if __name__=='__main__':main()
