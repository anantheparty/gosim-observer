"""Public-score likelihood tokens and joint quality expected utility.

No evaluator, official world labels, card identity or saved quality profile is
imported here.  All targets in a path use the same (C,Z,open) sequence.
"""
from __future__ import annotations
import math
import numpy as np

C_GRID = np.geomspace(.08, 2.6, 17)
E_GRID = np.geomspace(.10, 1., 9)
C, E = np.meshgrid(C_GRID, E_GRID, indexing='ij')
C = C.ravel(); E = E.ravel()
BASE_DIM = len(C) + 8
HISTORY = 8
HORIZON = 4

def score_token(scores, weights, flux, h, duration, program, *, elapsed_slots,
                new_night, seasonal_c, slot_fraction):
    scores=np.asarray(scores,float); weights=np.asarray(weights,float)
    flux=np.asarray(flux,float); h=np.asarray(h,float)
    y=scores/weights
    actual=np.where(C[:,None]*h>=.65,0,np.where(C[:,None]*h>=.40,1,2))
    mult=np.where(actual==int(program),[1.20,1.12,1.06][int(program)],1.)
    pred=np.minimum(1.,C[:,None]*E[:,None]*flux*duration*h/450.)*mult
    # This is a feature, not a claim that the score rounding noise is Gaussian.
    loss=np.mean(np.minimum(((pred-y)/(.025+.05*y))**2,25.),axis=1)
    loss=(loss-loss.min())/25.
    tail=[min(8.,elapsed_slots)/8.,float(new_night),math.log(max(.05,seasonal_c)),
          duration/3600.,slot_fraction,float(np.mean(y==0)),float(np.mean(y>1.)),len(y)/16.]
    return np.asarray([*loss,*tail],np.float32)

def utility_samples(c,z,opened,weights,flux,best,h_by_slot,seconds_by_slot,duration,program,
                    required=None,complete=None,required_penalty=5.):
    """Each sample is integrated then program/cap/best settled; expectation last.

    c,z,opened are Sx4.  h_by_slot is 4xF, each entry is the exact public
    <=120s-mesh geometry averaged within the corresponding slot overlap.
    """
    h=np.asarray(h_by_slot,float); seconds=np.asarray(seconds_by_slot,float)
    qband=np.einsum('sk,kf->sf',c*opened*seconds,h)/float(duration)
    qexp=np.einsum('sk,kf->sf',z*opened*seconds,h)/float(duration)
    factor=np.minimum(1.,qexp*np.asarray(flux)*float(duration)/450.)
    actual=np.where(qband>=.65,0,np.where(qband>=.40,1,2))
    mult=np.where(actual==int(program),[1.20,1.12,1.06][int(program)],1.)
    gain=np.maximum(0.,factor*mult*np.asarray(weights)-np.asarray(best))
    if required is not None:
        gain += np.asarray(required)*(1-np.asarray(complete))*required_penalty*(factor>=.5)
    return gain.sum(axis=1),factor,qband

def unpack_numpy(outputs):
    """Decode 4-mixture, 8D full covariance plus joint closure-pattern logits."""
    out=np.asarray(outputs,float)
    mix=out[:4]; mix=np.exp(mix-mix.max()); mix/=mix.sum()
    mu=out[4:36].reshape(4,8)
    tri=out[36:180].reshape(4,36)
    L=np.zeros((4,8,8)); ij=np.tril_indices(8); L[:,ij[0],ij[1]]=tri
    diag=np.arange(8)
    L[:,diag,diag]=np.logaddexp(0.,L[:,diag,diag])+.02
    # Output variables are standardized by 0.30 log units.
    closure=out[180:196]; closure=np.exp(closure-closure.max()); closure/=closure.sum()
    return mix,mu,L,closure

class NumpyPredictor:
    def __init__(self,path):
        self.data=np.load(path)
    def predict(self,x):
        x=np.asarray(x,np.float64).ravel()
        for k in range(3):
            x=np.einsum('j,ij->i',x,self.data[f'weight{k}'])+self.data[f'bias{k}']
            if k<2:x=np.maximum(0.,x)
        return x
    def samples(self,x,seasonal_c,normal,uniform_mix,uniform_close):
        mix,mu,L,closure=unpack_numpy(self.predict(x))
        component=np.searchsorted(np.cumsum(mix),uniform_mix).clip(0,3)
        y=mu[component]+np.einsum('sij,sj->si',L[component],normal)
        pattern=np.searchsorted(np.cumsum(closure),uniform_close).clip(0,15)
        opened=((pattern[:,None]>>np.arange(4))&1).astype(float)
        c=np.exp(np.clip(y[:,:4]*.3,-5,2))*seasonal_c
        z=np.exp(np.clip(y[:,4:]*.3,-5,2))*seasonal_c*.95
        return c,z,opened
