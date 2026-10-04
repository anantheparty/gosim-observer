"""Proximal bundle in cut coordinates, and exact-ledger block reconstruction."""
from __future__ import annotations
import time
import numpy as np
from scipy.optimize import minimize

def simplex(v):
    u = np.sort(np.asarray(v))[::-1]; c = np.cumsum(u) - 1.
    k = np.flatnonzero(u - c / np.arange(1, len(u)+1) > 0)[-1]
    return np.maximum(v - c[k]/(k+1), 0.)

def prox_trial(center, t, box, counts, raw, warm=None, maxiter=40, ftol=1e-10):
    """Dual of min sum(s)+max_j(raw_j-n_j*s)+||s-center||²/(2t).

    lambda is a simplex point. Minimizing over the boxed prices is analytic;
    all optimizer variables are cut weights, never an 8600-square Hessian.
    An incomplete QP is permitted as a trial generator, with its gap reported.
    """
    N = np.asarray(counts); r = np.asarray(raw); k = len(r)
    initial = np.full(k, 1./k) if warm is None or len(warm) != k else simplex(warm)
    last_x = None; last = None
    def fg(lam):
        nonlocal last_x, last
        if last_x is None or not np.array_equal(lam, last_x):
            d = 1. - N.T @ lam; s = np.clip(center - t*d, 0., box)
            dual = float(r @ lam + d @ s + np.square(s-center).sum()/(2.*t))
            last_x = lam.copy(); last = (-dual, -(r - N @ s))
        return last
    result = minimize(lambda x: fg(x)[0], initial, jac=lambda x: fg(x)[1], method='SLSQP',
        bounds=[(0., 1.)] * k,
        constraints=[dict(type='eq', fun=lambda x: x.sum()-1., jac=lambda x: np.ones(k))],
        options=dict(maxiter=maxiter, ftol=ftol, disp=False))
    lam = simplex(result.x) if np.all(np.isfinite(result.x)) else initial
    d = 1. - N.T @ lam; trial = np.clip(center - t*d, 0., box)
    cut_value = r - N @ trial
    model = float(trial.sum() + cut_value.max())
    primal = model + float(np.square(trial-center).sum()/(2.*t))
    dual = float(r @ lam + d @ trial + np.square(trial-center).sum()/(2.*t))
    return trial, lam, dict(model=model, prox_primal=primal, prox_dual=dual,
        qp_gap=max(0., primal-dual), qp_success=bool(result.success), qp_iterations=int(result.nit), cuts=k)

class Bundle:
    def __init__(self, graph, branch):
        self.g = graph; self.branch = branch; self.center = np.zeros(graph.n)
        self.box = None; self.t = None; self.t0 = None; self.center_value = None
        self.center_cut = None; self.cuts = [(np.zeros(graph.n),0.)]; self.warm = None; self.nulls = 0
        self.best_upper = float('inf'); self.rounds = 0; self.trace = []

    def append(self, count, raw):
        self.cuts.append((count.copy(), float(raw)))
        if len(self.cuts) > 64:
            # A convex combination of old cuts remains a valid lower support.
            # Preserve the center's exact support and recent oracle supports.
            old = self.cuts[:-1]
            w = self.warm if self.warm is not None and len(self.warm) == len(old) else np.full(len(old), 1./len(old))
            aggregate = (np.asarray([v[0] for v in old]).T @ w,
                         float(np.asarray([v[1] for v in old]) @ w))
            self.cuts = [aggregate, self.center_cut, (np.zeros(self.g.n),0.), *self.cuts[-61:]]
            self.warm = None
        elif self.warm is not None and len(self.warm)+1 == len(self.cuts):
            self.warm = np.r_[self.warm, 0.]
        else:
            self.warm = None

    def step(self):
        started = time.perf_counter()
        if self.box is None:
            s = self.center.copy(); detail = dict(model=None, qp_gap=None, cuts=0)
        else:
            s, lam, detail = prox_trial(self.center, self.t, self.box,
                [v[0] for v in self.cuts], [v[1] for v in self.cuts], self.warm)
            self.warm = lam
        z = self.g.oracle(self.branch['first'], s, self.branch['blocked'])
        self.best_upper = min(self.best_upper, z['upper']); self.rounds += 1
        if self.box is None:
            self.box = z['gmax'].copy(); gradient = 1. - z['counts']
            self.t0 = max(1e-5, float(np.linalg.norm(self.box)/max(1., np.linalg.norm(gradient))))
            self.t = self.t0; serious = True; predicted = None; reduction = None
        else:
            predicted = self.center_value - detail['model']; reduction = self.center_value - z['upper']
            serious = reduction > 1e-8 and reduction >= .2 * max(0., predicted)
        if serious:
            self.center = s.copy(); self.center_value = z['upper']; self.center_cut = (z['counts'].copy(), z['raw'])
            self.nulls = 0
            if reduction is not None and reduction >= .7 * max(1e-8, predicted): self.t = min(16.*self.t0, self.t*1.5)
        else:
            self.nulls += 1
            if self.nulls % 6 == 0: self.t = max(self.t0/16., self.t*.5)
        self.append(z['counts'], z['raw'])
        row = dict(round=self.rounds, branch=self.branch['name'], upper=z['upper'], best_upper=self.best_upper,
            serious=serious, predicted_reduction=predicted, actual_reduction=reduction, center_upper=self.center_value,
            prox_t=self.t, price_l2=float(np.linalg.norm(s)), path_exposures=len(z['path']),
            seconds=time.perf_counter()-started, **detail)
        self.trace.append(row)
        return z['path'], row

def outside_ledger(branch, control, window):
    """Keep the incumbent's actual winning assignments wholly outside block."""
    b = branch['first'].copy(); outside = []
    for row in control['schedule']:
        if row['end'] <= window[0] + 1e-7 or row['start'] >= window[1] - 1e-7:
            ids = np.asarray(row['targets'],dtype=int); b[ids] = np.maximum(b[ids], row['scores'])
            outside.append(row['action'])
    return b, outside

def rebuild(graph, branch, control, window, sigma):
    b, outside = outside_ledger(branch, control, window)
    z = graph.oracle(b, sigma, max(branch['blocked'], window[0]), window)
    # Crossing exposures are removed entirely, so no overlap can survive at
    # either block edge. Full matching can then change assignments everywhere.
    path = tuple(sorted(set(outside).union(z['path']), key=lambda e: (graph.starts[e], graph.ends[e], e)))
    return path, dict(local_dual_surrogate=z['upper'], outside_exposures=len(outside), replacement_exposures=len(z['path']))
