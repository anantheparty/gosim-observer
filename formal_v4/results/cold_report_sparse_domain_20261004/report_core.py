"""Public-only calibrated posterior and projected quota Bellman lookup."""
from __future__ import annotations
import numpy as np
from pathlib import Path
PGRID=np.asarray([0.,.005,.01,.025,.05,.10,.20,.35,.50,.65,.80,.90,.95,.98,1.])
NP=len(PGRID);NST=NP*9
def bucket(p):return np.searchsorted((PGRID[:-1]+PGRID[1:])/2,p).clip(0,NP-1)
def state_index(p,quake,correct):return (np.asarray(correct).clip(0,2)*3+np.asarray(quake).clip(0,2))*NP+bucket(p)
def nuisance_from_features(x):
    # 8 public scalars, 24 directional notice scalars, 8 forecast scalars.
    tail=np.asarray(x)[...,-40:]
    qa=tail[...,6]*20
    quake=np.where(qa<=0,0,np.where(qa<=4,1,2)).astype(int)
    correct=np.rint(tail[...,5]*2).astype(int).clip(0,2)
    return quake,correct
class ReportModel:
    def __init__(self,path=None):
        with np.load(path or Path(__file__).with_name('report_model.npz')) as archive:
            self.data={k:archive[k] for k in archive.files}
    def logit(self,x):
        x=np.asarray(x,dtype=np.float64)
        for k in range(3):
            # Some macOS Accelerate builds set spurious floating-point flags
            # for finite GEMM results. Explicit finite check is the real gate.
            with np.errstate(all='ignore'):
                x=x@self.data[f'weight{k}'].T+self.data[f'bias{k}']
            if not np.all(np.isfinite(x)):raise FloatingPointError('nonfinite report NN output')
            if k<2:x=np.maximum(x,0)
        return x[...,0]
    def posterior(self,x):
        z=np.clip(self.logit(x)*float(self.data['cal_scale'])+float(self.data['cal_bias']),-40,40)
        p=1/(1+np.exp(-z))
        # A report result is exact information at its timestamp.
        features=np.asarray(x)
        return np.where((features[...,-33]>.5)|(features[...,-35]>=1.),0.,p)
class ReportDP:
    def __init__(self,path=None):
        with np.load(path or Path(__file__).with_name('report_dp.npz')) as archive:
            self.data={k:archive[k] for k in archive.files}
    def delta(self,p,quota,phase,nuisance,step,total):
        horizon=int(self.data['horizon']);i=min(horizon-1,max(0,int(horizon*step/max(1,total))))
        s=int(state_index(p,*nuisance));return float(self.data['delta'][i,max(0,min(2,quota)),s])
    def report(self,p,quota,phase,nuisance,step,total):
        return nuisance[1]<2 and p>0 and self.delta(p,quota,phase,nuisance,step,total)>0

def build_dp(p,pw,pr,y,loss,phase,quake,correct,xw,xr,horizon=1024,shrink=32.):
    """Counterfactual causal transitions, projected onto public posterior states.

    Each source record supplies shared-weather wait and report next histories.
    True and false outcomes retain their own kernels; correct_count is public.
    """
    state=state_index(p,quake,correct);qw,cw=nuisance_from_features(xw);qr,cr=nuisance_from_features(xr)
    nextw=state_index(pw,qw,cw);nextr=state_index(pr,qr,cr)
    kernels=[];losses=[];support=[]
    for ph in range(8):
        select=phase==ph
        phasekern=[]
        for kind in range(3):
            # wait; report correct; report false.
            keep=select if kind==0 else select&(y==(1 if kind==1 else 0))
            dest=nextw if kind==0 else nextr
            counts=np.zeros((NST,NST));np.add.at(counts,(state[keep],dest[keep]),1.)
            pooled=np.zeros((9,NST))
            for n in range(9):pooled[n]=counts[n*NP:(n+1)*NP].sum(0)
            globalpool=counts.sum(0)
            for s in range(NST):
                n=s//NP;row=pooled[n]
                if row.sum()<1:row=globalpool
                if row.sum()<1:row=np.eye(NST)[s]
                # A sparse fallback cannot roll back an exactly public count.
                # Quake/p bins may be pooled, but count has a deterministic update.
                target_count=min(2,s//(3*NP)+(kind==1))
                mapped=np.zeros(NST)
                pooled_bins=row.reshape(3,3*NP).sum(0)
                mapped[target_count*3*NP:(target_count+1)*3*NP]=pooled_bins
                base=mapped/mapped.sum();counts[s]=(counts[s]+shrink*base)/(counts[s].sum()+shrink)
                if s//(3*NP)==2:
                    # Max-two-fault prior: after two publicly correct repairs,
                    # the repairable-fault state is exactly healthy forever.
                    row=counts[s].reshape(3,3,NP).sum(2)
                    counts[s]=0.
                    for quake_bin in range(3):counts[s,6*NP+quake_bin*NP]=row[2,quake_bin]
                wanted=np.arange(NST)//(3*NP)==target_count
                assert np.sum(counts[s,~wanted])<1e-12
            phasekern.append(counts)
        l=np.zeros(NST);cnt=np.zeros(NST);sums=np.zeros(NST)
        keep=select&(y==1);np.add.at(cnt,state[keep],1);np.add.at(sums,state[keep],loss[keep])
        globalmean=float(loss[keep].mean()) if keep.any() else 0.
        for s in range(NST):
            n=s//NP;mask=keep&(state//NP==n);mean=float(loss[mask].mean()) if mask.any() else globalmean
            l[s]=PGRID[s%NP]*(sums[s]+shrink*mean)/(cnt[s]+shrink)
        l[6*NP:]=0.
        kernels.append(phasekern);losses.append(l);support.append(cnt)
    k=np.asarray(kernels);l=np.asarray(losses)
    V=np.zeros((horizon+1,3,NST));D=np.zeros((horizon,3,NST));pp=np.tile(PGRID,9)
    # This reference-world domain has <=2 faults. Exhausted-count nodes cannot
    # create fictitious repeated +100 rewards in unsupported posterior bins.
    pp[6*NP:]=0.
    for i in range(horizon-1,-1,-1):
        ph=min(7,int(8*i/horizon))
        # Continuation follows one actual sensor exposure, not another zero-time report.
        for q in range(3):
            wait=-l[ph]+k[ph,0]@V[i+1,q]
            report=pp*(100+k[ph,1]@V[i+1,2])+(1-pp)*(-150*(q==0)+k[ph,2]@V[i+1,max(0,q-1)])
            D[i,q]=report-wait
            V[i,q]=np.maximum(wait,report)
            V[i,q,::NP]=wait[::NP] # current F=0: same-time reporting is dominated.
    return dict(delta=D,value=V,kernels=k,loss=l,support=np.asarray(support),horizon=horizon,pgrid=PGRID,shrink=shrink)
