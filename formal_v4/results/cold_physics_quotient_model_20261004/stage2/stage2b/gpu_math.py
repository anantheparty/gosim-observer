"""Torch float64 form of the same joint density and analytic capped G kernel."""
import math
import torch

def distribution(raw,mean,std,temperature=1.,sigma_multiplier=1.):
    raw=raw.to(torch.float64)
    lp=torch.log_softmax(raw[:,:15]/temperature,dim=1).reshape(-1,3,5)
    mu=(mean+std*8*torch.tanh(raw[:,15:27]/8)).reshape(-1,3,4)
    sigma=((.03+1.97*torch.sigmoid(raw[:,27:39]))*sigma_multiplier).reshape(-1,3,4)
    return lp,mu,sigma

def density_nll(raw,r,band,mean,std,temperature=1.,sigma_multiplier=1.):
    lp,mu,sigma=distribution(raw,mean,std,temperature,sigma_multiplier)
    r=r.to(torch.float64);band=band.to(torch.long);rows=torch.arange(len(r),device=raw.device)
    p=lp[rows,band];u=mu[rows,band];s=sigma[rows,band]
    z=torch.log(r.clamp_min(1e-30))
    normal=-torch.log(s)-.5*((z[:,None]-u)/s)**2-.5*math.log(2*math.pi)
    positive=-torch.logsumexp(p[:,1:]+normal,dim=1)+z
    return torch.where(r==0,-p[:,0],positive)

def gain(raw,scale,weight,best,scoring,mean,std,temperature=1.,sigma_multiplier=1.):
    lp,mu,sigma=distribution(raw,mean,std,temperature,sigma_multiplier)
    prob=lp.exp();a=scale.to(torch.float64)[:,None,None]
    w=weight.to(torch.float64)[:,None,None];b=best.to(torch.float64)[:,None,None]
    values=[]
    cdf=lambda x:.5*torch.erfc(-x/math.sqrt(2))
    for declared in range(3):
        multip=torch.full((3,),scoring['program']['mismatch_multiplier'],device=raw.device,dtype=torch.float64)
        multip[declared]=scoring['program']['multipliers'][('DARK','BRIGHT','BACKUP')[declared]]
        wm=w*multip[None,:,None]
        lo=torch.log((b/(wm*a).clamp_min(1e-300)).clamp_min(1e-300))
        lo=torch.where(b==0,torch.full_like(lo,-torch.inf),lo);hi=torch.log(1/a)
        interval=cdf((hi-mu)/sigma)-cdf((lo-mu)/sigma)
        moment=torch.exp(mu+.5*sigma*sigma)*(cdf((hi-mu-sigma*sigma)/sigma)-cdf((lo-mu-sigma*sigma)/sigma))
        tail=cdf((mu-hi)/sigma);value=wm*a*moment-b*interval+(wm-b)*tail
        value=torch.where(b>=wm,torch.zeros_like(value),torch.minimum(torch.maximum(value,torch.zeros_like(value)),wm))
        values.append((prob[:,:,1:]*value).sum(dim=(1,2)))
    return torch.stack(values,dim=1)
