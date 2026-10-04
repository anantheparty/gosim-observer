"""Ordinary 5963->128->128->39 joint quotient-density model contract.

No fit is invoked by this module. Actor inference accepts only public encoded
arrays. Future flux, weight, declared program and best are outside the network.
"""
import math
import numpy as np
INPUT_DIM=5963
QUERY_DIM=50
TARGET_HISTORY_DIM=36
OUTPUT_DIM=39

def encode(data,state,rows,current_only=False):
    hist=np.concatenate([data['ht'][state].ravel(),data['hn'][state].ravel(),
                         data['hm'][state].ravel()])
    if current_only:hist=np.zeros_like(hist)
    shared=np.concatenate([hist,data['cn'][state],data['cm'][state]])
    out=np.concatenate([np.broadcast_to(shared,(len(rows),len(shared))),data['q'][rows]],axis=1)
    assert out.shape==(len(rows),INPUT_DIM) and np.isfinite(out).all()
    return out.astype(np.float32)

def transform(raw,logr_mean,logr_std,temperature=1.,sigma_multiplier=1.):
    raw=np.asarray(raw,np.float64)
    logits=raw[:,:15]/temperature;logits-=logits.max(axis=1,keepdims=True)
    prob=np.exp(logits);prob/=prob.sum(axis=1,keepdims=True)
    mu=logr_mean+logr_std*8*np.tanh(raw[:,15:27]/8)
    sigma=(.03+1.97*(.5+.5*np.tanh(raw[:,27:39]/2)))*sigma_multiplier
    return prob.reshape(-1,3,5),mu.reshape(-1,3,4),sigma.reshape(-1,3,4)

def normal_cdf(x):
    x=np.asarray(x,np.float64)
    return np.fromiter((.5*math.erfc(-float(v)/math.sqrt(2)) for v in x.ravel()),
                       dtype=np.float64,count=x.size).reshape(x.shape)

def gain(prob,mu,sigma,scale,weight,best,scoring):
    """All programs: expectation first, exact cap and historical best outside NN."""
    n=len(prob);a=np.asarray(scale,np.float64)[:,None,None]
    w=np.asarray(weight,np.float64)[:,None,None];b=np.asarray(best,np.float64)[:,None,None]
    output=np.zeros((n,3),np.float64)
    for declared in range(3):
        multip=np.full(3,scoring['program']['mismatch_multiplier'],np.float64)
        multip[declared]=scoring['program']['multipliers'][('DARK','BRIGHT','BACKUP')[declared]]
        wm=w*multip[None,:,None]
        lo=np.log(np.maximum(b/np.maximum(wm*a,1e-300),1e-300))
        lo=np.where(b==0,-np.inf,lo);hi=np.log(1/a)
        interval=normal_cdf((hi-mu)/sigma)-normal_cdf((lo-mu)/sigma)
        moment=np.exp(mu+.5*sigma*sigma)*(normal_cdf((hi-mu-sigma*sigma)/sigma)-normal_cdf((lo-mu-sigma*sigma)/sigma))
        tail=normal_cdf((mu-hi)/sigma)
        value=wm*a*moment-b*interval+(wm-b)*tail
        value=np.where(b>=wm,0,np.clip(value,0,wm))
        output[:,declared]=np.sum(prob[:,:,1:]*value,axis=(1,2))
    return output

def torch_model(logr_mean,logr_std):
    import torch
    from torch import nn
    class Network(nn.Module):
        def __init__(self):
            super().__init__();self.layers=nn.ModuleList([nn.Linear(INPUT_DIM,128),nn.Linear(128,128),nn.Linear(128,OUTPUT_DIM)])
        def forward(self,x):
            for layer in self.layers[:-1]:x=torch.relu(layer(x))
            return self.layers[-1](x)
        def density(self,raw):
            lp=torch.log_softmax(raw[:,:15],dim=1).reshape(-1,3,5)
            mu=logr_mean+logr_std*8*torch.tanh(raw[:,15:27]/8)
            sigma=.03+1.97*torch.sigmoid(raw[:,27:39])
            return lp,mu.reshape(-1,3,4),sigma.reshape(-1,3,4)
        def nll(self,x,r,band):
            lp,mu,sigma=self.density(self(x));rows=torch.arange(len(x),device=x.device)
            chosenlp=lp[rows,band];chosenmu=mu[rows,band];chosensigma=sigma[rows,band]
            z=torch.log(r.clamp_min(1e-30))
            normal=-torch.log(chosensigma)-.5*((z[:,None]-chosenmu)/chosensigma)**2-.5*math.log(2*math.pi)
            positive=-torch.logsumexp(chosenlp[:,1:]+normal,dim=1)+z
            return torch.where(r==0,-chosenlp[:,0],positive)
    return Network()

def numpy_forward(x,layers,input_mean=None,input_scale=None):
    x=np.asarray(x,np.float64)
    if input_mean is not None:x=(x-input_mean)/input_scale
    for j,(weight,bias) in enumerate(layers):
        x=np.einsum('bi,oi->bo',x,np.asarray(weight,np.float64),optimize=False)+bias
        if j+1<len(layers):x=np.maximum(x,0)
    return x
