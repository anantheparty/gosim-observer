"""Two-level causal weather clock. No truth, evaluator, network, seed, or LLM."""
from __future__ import annotations
import math
import numpy as np
from research.geometry import parse_utc
from research.feedback_model import seasonal_quality

class HierarchicalClock:
    """Night latent + slot deviation, with slot deviation reset each night.

    The observation is log(C/seasonal_C). Instrument E remains the caller's
    separately fitted state. mark/prior preserve the original Policy API.
    """
    def __init__(self, nights, slot_seconds=900, initial_time=None,
                 night_variance=.03, slot_variance=.005, measurement_variance=.0025):
        self.nights = [(parse_utc(a).timestamp() if isinstance(a,str) else a.timestamp(),
                        parse_utc(b).timestamp() if isinstance(b,str) else b.timestamp())
                       for a,b in nights]
        self.slot_seconds = float(slot_seconds)
        self.vn = float(night_variance)
        self.vs = float(slot_variance)
        self.r = float(measurement_variance)
        self.mean = np.zeros(2)
        self.cov = np.diag([self.vn, self.vs])
        self.time = parse_utc(initial_time).timestamp() if isinstance(initial_time,str) else initial_time.timestamp()
        self.night = self._night(self.time)
        self.pending = None
        self.updates = 0

    def _night(self, t):
        return max(0, min(len(self.nights)-1, int(np.searchsorted([b for a,b in self.nights],t,side='right'))))

    def _advance(self, t, mean, cov, prior_time, prior_night):
        night = self._night(t)
        mean = mean.copy(); cov = cov.copy()
        if night > prior_night:
            phi = .82 ** (night-prior_night)
            mean[0] *= phi
            cov[0,0] = phi*phi*cov[0,0] + self.vn*(1-phi*phi)
            mean[1] = 0.
            cov[0,1] = cov[1,0] = 0.
            # Slot state starts at zero deviation before the first draw.
            elapsed = max(0., (t-self.nights[night][0])/self.slot_seconds)
            phi = .88 ** elapsed
            cov[1,1] = self.vs*(1-phi*phi)
        else:
            elapsed = max(0., (min(t,self.nights[night][1])-max(prior_time,self.nights[night][0]))/self.slot_seconds)
            phi = .88 ** elapsed
            mean[1] *= phi
            cov[0,1] *= phi; cov[1,0] *= phi
            cov[1,1] = phi*phi*cov[1,1] + self.vs*(1-phi*phi)
        return mean,cov,night

    def update(self, C, time, seasonal_C):
        t = time.timestamp() if hasattr(time,'timestamp') else float(time)
        mean,cov,night = self._advance(t,self.mean,self.cov,self.time,self.night)
        y = math.log(max(.02,float(C))/max(.02,float(seasonal_C)))
        h = np.ones(2)
        k = cov @ h / (float(h @ cov @ h)+self.r)
        innovation = y-float(h @ mean)
        # Guard prior against a single spatially damaged score fit.
        innovation = float(np.clip(innovation,-.6,.6))
        self.mean = mean+k*innovation
        self.cov = cov-np.outer(k,h @ cov)
        self.time,self.night = t,night
        self.updates += 1

    def mark(self, time):
        self.pending = time

    def reset(self, time):
        self.mean[:] = 0.; self.cov = np.diag([self.vn,self.vs])
        self.time = time.timestamp(); self.night = self._night(self.time)
        self.pending = None

    def prior(self, C, E, time, seasonal_C):
        if self.pending is not None:
            observed_at = self.pending
            prior_season = seasonal_quality(observed_at.timetuple().tm_yday)[0]
            self.update(C, observed_at, prior_season)
            self.pending = None
        t = time.timestamp()
        mean,cov,_ = self._advance(t,self.mean,self.cov,self.time,self.night)
        return math.exp(float(mean.sum()))*float(seasonal_C), float(np.clip(E,.025,1.))

