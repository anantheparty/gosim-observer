"""Isolated NN continuation hook; preserves production geometry/scoring mechanics.

This module does not import evaluator/truth code. Training/model validity does not
imply score improvement; use same-source official full-season comparisons.
"""
from __future__ import annotations

import math
import time
from datetime import timedelta
from pathlib import Path
import numpy as np

from research.spatial_candidates import SpatialPlanner
from research.geometry import local_sidereal_deg, parse_utc


class ContinuationNN:
    def __init__(self,path):
        self.p={k:v for k,v in np.load(path).items()}
    def __call__(self,x):
        p=self.p;x=(x-p["mean"])/p["std"]
        # Some macOS Accelerate builds set spurious floating exception flags in
        # GEMM. Finite output is checked explicitly rather than trusting flags.
        with np.errstate(divide="ignore",over="ignore",invalid="ignore"):
            for i in range(3):
                x=x@p[f"w{i}"].T+p[f"b{i}"]
                if i<2:x=np.maximum(x,0)
            out=1/(1+np.exp(-np.clip(x,-30,30)))
        if not np.isfinite(out).all():
            raise ValueError("nonfinite continuation prediction")
        return out


class NeuralContinuationSpatialPlanner(SpatialPlanner):
    def __init__(self,initial_payload):
        super().__init__(initial_payload)
        self.nn=ContinuationNN(Path(__file__).with_name("cold_neural_model.npz"))
        times=[]
        for start,end in self.nights:
            while start<end:
                times.append(start);start+=timedelta(seconds=900)
        self.nn_times=times
        self.nn_stamps=np.array([t.timestamp() for t in times])
        altitude=np.stack([self._altaz(local_sidereal_deg(t,self.lon))[0] for t in times]).astype(np.float32)
        endalt=np.stack([self._altaz(local_sidereal_deg(t+timedelta(seconds=900),self.lon))[0] for t in times]).astype(np.float32)
        vis=np.minimum(altitude,endalt)>=30
        self.nn_alt=altitude
        self.nn_future=np.flip(np.cumsum(np.flip(vis,axis=0),axis=0),axis=0).astype(np.float32)
        z=90-np.maximum(altitude,0)
        airmass=1/(np.cos(np.radians(z))+.50572*np.maximum(96.07995-z,.01)**(-1.6364))
        zen=1/(1+.50572*96.07995**(-1.6364))
        geom=(airmass/zen)**(-self.airmass_exponent)*vis
        self.nn_peak=np.flip(np.maximum.accumulate(np.flip(geom,axis=0),axis=0),axis=0).astype(np.float32)
        decbin=np.floor((self.dec+90)/3).astype(int)
        key=decbin*1000+np.floor(self.ra*np.cos(np.radians(decbin*3-88.5))/3).astype(int)
        _,self.nn_group=np.unique(key,return_inverse=True)
        self.nn_groups=int(self.nn_group.max()+1)
        self.nn_strength=.3
        self.nn_prediction=np.ones((self.n,2),np.float32)
        self.nn_seconds=0.;self.nn_calls=0

    def _nn_features(self,now,scores,factors):
        t=int(np.clip(np.searchsorted(self.nn_stamps,now.timestamp(),side="right")-1,0,len(self.nn_times)-1))
        done=factors>=.5
        required=np.bincount(self.nn_group,weights=self.required&~done,minlength=self.nn_groups)
        missing=np.bincount(self.nn_group,weights=~done,minlength=self.nn_groups)
        bd=np.bincount(self.ra_bands,weights=done,minlength=len(self.band_sizes))
        fraction=np.divide(bd,self.band_sizes,out=np.zeros(len(self.band_sizes)),where=self.band_sizes>0)
        future=self.nn_future[t];local=required[self.nn_group]
        return np.column_stack([np.log1p(self.flux),self.weight,self.required,factors,
            scores/np.maximum(self.weight*1.2,1e-6),np.log1p(future)/np.log1p(len(self.nn_times)),
            self.nn_peak[t],self.nn_alt[t]/90,np.log1p(local)/np.log(101),local/(1+future/10),
            fraction[self.ra_bands],np.full(self.n,done.mean()),
            np.full(self.n,(len(self.nn_times)-t)/len(self.nn_times)),
            np.log1p(missing[self.nn_group])/np.log(101)]).astype(np.float32)

    def choose(self,snapshot,best_scores,best_factors,env_estimate=None,active_requests=None):
        env=dict(env_estimate or {})
        self.nn_strength=float(env.get("neural_continuation_strength",.3))
        start=time.perf_counter()
        scores,factors=self._array(best_scores),self._array(best_factors)
        self.nn_prediction=self.nn(self._nn_features(parse_utc(snapshot["now_utc"]),scores,factors))
        self.nn_seconds+=time.perf_counter()-start;self.nn_calls+=1
        action=super().choose(snapshot,best_scores,best_factors,env,active_requests)
        return action

    def _evaluate(self,center,pool,vectors,up,k,scores,factors,multiplier,req_missing,
                  request_reward,request_threshold,request_deadline,uniform_bonus,urgency,
                  seconds_left,safety,focus_request=None):
        neural_urgency=urgency*(1+self.nn_strength*req_missing*(1-self.nn_prediction[:,0]))
        return super()._evaluate(center,pool,vectors,up,k,scores,factors,multiplier,req_missing,
            request_reward,request_threshold,request_deadline,uniform_bonus,neural_urgency,
            seconds_left,safety,focus_request)

