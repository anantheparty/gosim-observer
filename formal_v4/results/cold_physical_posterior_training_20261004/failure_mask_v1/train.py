"""Actual ordinary CUDA MLP for the new physical joint path class posterior."""
import json,time,hashlib
from pathlib import Path
import numpy as np
import torch
from torch import nn
ROOT=Path(__file__).resolve().parent
XDIM=2736;TOKEN_DIM=330;HISTORY=8
SEED=915441
def dense(ix,w,k):
    a=np.zeros((len(ix),k),np.float32)
    for r in range(len(ix)):a[r,ix[r]]=w[r]
    return a
def main():
    assert torch.cuda.is_available();torch.set_num_threads(2);torch.manual_seed(SEED);start=time.time();device='cuda'
    data=np.load(ROOT/'fit_data.npz');x=data['train_x'];mean=x.mean(0);std=np.maximum(x.std(0),.05);bank=json.loads((ROOT/'physical_bank.json').read_text());K=len(bank);healthy=np.asarray([p['fault'][0]==0 for p in bank])
    model=nn.Sequential(nn.Linear(XDIM,128),nn.ReLU(),nn.Linear(128,128),nn.ReLU(),nn.Linear(128,K)).to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=.0007,weight_decay=.0001)
    X=torch.tensor((x-mean)/std,device=device);Y=torch.tensor(dense(data['train_ix'],data['train_y'],K),device=device);same=torch.tensor(x[:,HISTORY*TOKEN_DIM+9]>.5,device=device)
    CX=torch.tensor((data['cal_x']-mean)/std,device=device);CY=torch.tensor(dense(data['cal_ix'],data['cal_y'],K),device=device);CS=torch.tensor(data['cal_x'][:,HISTORY*TOKEN_DIM+9]>.5,device=device);healthy_t=torch.tensor(healthy,device=device)
    def logits(xx,ss):return model(xx).masked_fill(ss[:,None]&~healthy_t[None,:],-1e6)
    best=float('inf');epochs=[]
    for epoch in range(40):
        order=torch.randperm(len(X),device=device);total=0.
        for j in range(0,len(X),512):
            ix=order[j:j+512];optimizer.zero_grad();z=logits(X[ix],same[ix]);loss=-(Y[ix]*z.log_softmax(-1)).sum(-1).mean();loss.backward();optimizer.step();total+=float(loss.detach())*len(ix)
        with torch.no_grad():cal=float(-(CY*logits(CX,CS).log_softmax(-1)).sum(-1).mean())
        record=dict(epoch=epoch,train_soft_nll=total/len(X),cal_soft_nll=cal,seconds=time.time()-start);epochs.append(record);print(json.dumps(record),flush=True)
        if cal<best:best=cal;selected=epoch;state={k:v.detach().clone() for k,v in model.state_dict().items()}
    model.load_state_dict(state)
    with torch.no_grad():cz=logits(CX,CS).detach()
    logt=torch.tensor(0.,device=device,requires_grad=True);opt=torch.optim.LBFGS([logt],lr=.3,max_iter=40,line_search_fn='strong_wolfe')
    def closure():
        opt.zero_grad();loss=-(CY*(cz/logt.exp()).log_softmax(-1)).sum(-1).mean();loss.backward();return loss
    opt.step(closure);temp=float(logt.detach().exp());params=dict(mean=mean.astype(np.float64),std=std.astype(np.float64),temperature=temp,healthy=healthy)
    for k,i in enumerate([0,2,4]):params[f'w{k}']=model[i].weight.detach().cpu().numpy().astype(np.float64);params[f'b{k}']=model[i].bias.detach().cpu().numpy().astype(np.float64)
    np.savez(ROOT/'physical_model.npz',**params)
    metrics={}
    for name in ['cal','val']:
        xx=data[name+'_x'];yy=dense(data[name+'_ix'],data[name+'_y'],K)
        with torch.no_grad():p=logits(torch.tensor((xx-mean)/std,device=device),torch.tensor(xx[:,HISTORY*TOKEN_DIM+9]>.5,device=device)).div(temp).softmax(-1).cpu().numpy()
        prior=(Y.mean(0).cpu().numpy()+1e-5);prior/=prior.sum()
        metrics[name]=dict(soft_nll=float(np.mean(-np.sum(yy*np.log(np.maximum(p,1e-12)),axis=1))),constant_prior_soft_nll=float(np.mean(-np.sum(yy*np.log(prior),axis=1))),prob_sum_error=float(np.max(np.abs(p.sum(1)-1))))
    result=dict(gpu=torch.cuda.get_device_name(),model=f'ordinary MLP {XDIM}->128->128->{K}',parameter_count=sum(p.numel() for p in model.parameters()),selected_epoch=selected,temperature=temp,epochs=epochs,metrics=metrics,seconds=time.time()-start,max_cuda_bytes=int(torch.cuda.max_memory_allocated()),test_unopened=True,model_sha256=hashlib.sha256((ROOT/'physical_model.npz').read_bytes()).hexdigest())
    (ROOT/'training_result.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='epochs'}),flush=True)
if __name__=='__main__':main()
