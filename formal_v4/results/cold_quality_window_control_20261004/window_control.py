"""Public-information best-ledger continuation prototype, not a deployed actor.

Inputs are finite future action outcome models, not truth schedules. A target's
state is its public best score / science weight and P(max raw factor >= threshold).
Latent outcome raw factors are used ONLY as hypothesized model outcomes; observable
six-decimal scores are grouped before the completion posterior is updated.
The finite model allows one service choice per target per opportunity window.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass
class OutcomeModel:
    # [window, action, latent outcome, target], score divided by target weight.
    normalized_score: np.ndarray
    raw_factor: np.ndarray
    probabilities: np.ndarray  # [window, latent outcome]
    durations: np.ndarray  # [window, action], 0 is not an action; skip is implicit.
    weights: np.ndarray
    required_bonus: np.ndarray
    threshold: float = .5

    def validate(self):
        c, g = self.normalized_score, self.raw_factor
        if c.shape != g.shape or c.ndim != 4:
            raise ValueError('outcomes must be equal [W,A,S,N] arrays')
        w, a, s, n = c.shape
        if self.probabilities.shape != (w, s) or self.durations.shape != (w, a):
            raise ValueError('probability/duration shape mismatch')
        if self.weights.shape != (n,) or self.required_bonus.shape != (n,):
            raise ValueError('target shape mismatch')
        if np.any(c < 0) or np.any(g < 0) or np.any(g > 1) or np.any(self.weights <= 0):
            raise ValueError('invalid modeled outcome')
        if not np.allclose(self.probabilities.sum(1), 1) or np.any(self.probabilities < 0):
            raise ValueError('probabilities must be nonnegative and sum to one')


def observable_posteriors(model: OutcomeModel, window: int, action: int):
    """Return publicly rounded normalized score and P(raw>=threshold|score).

    Multiple latent regimes may give one public score. Repeating that observed
    group in the outer expectation is harmless: each latent probability remains
    present once, while every member receives exactly the same posterior.
    """
    score = np.round(model.normalized_score[window, action] * model.weights, 6)
    hit = model.raw_factor[window, action] >= model.threshold
    p = model.probabilities[window, :, None]
    tau = np.empty_like(score)
    for r in range(len(p)):
        same = score == score[r:r+1]
        denom = (same * p).sum(0)
        tau[r] = np.divide((same * hit * p).sum(0), denom,
                           out=np.zeros_like(denom), where=denom > 0)
    return score / model.weights, tau


def _grid_coordinates(values, grid):
    # Linear interpolation in score and threshold-belief state; finite-grid
    # approximation, not a claim that it is exact for the original POMDP.
    x = np.clip(values / (grid[-1] / (len(grid)-1)), 0, len(grid)-1)
    lo = np.floor(x).astype(np.int32)
    hi = np.minimum(lo+1, len(grid)-1)
    return lo, hi, x-lo


def _transition(value, score, tau, score_grid, probability_grid):
    n = len(score)
    next_b = np.maximum(score[:, None], score_grid[None, :])
    bl, bh, bw = _grid_coordinates(next_b, score_grid)
    next_p = probability_grid[None, :] + (1-probability_grid[None, :]) * tau[:, None]
    pl, ph, pw = _grid_coordinates(next_p, probability_grid)
    rows = np.arange(n)[:, None, None]
    v00 = value[rows, bl[:, :, None], pl[:, None, :]]
    v01 = value[rows, bl[:, :, None], ph[:, None, :]]
    v10 = value[rows, bh[:, :, None], pl[:, None, :]]
    v11 = value[rows, bh[:, :, None], ph[:, None, :]]
    low = v00 * (1-pw[:, None, :]) + v01 * pw[:, None, :]
    high = v10 * (1-pw[:, None, :]) + v11 * pw[:, None, :]
    return low * (1-bw[:, :, None]) + high * bw[:, :, None]


def solve(model, prices, *, score_bins=13, probability_bins=5,
          keep_suffix=False, keep_policy=True):
    """Backward Bellman sweep with fiber-second prices, all targets vectorized.

    H_k = max(H_{k+1}, max_a E[H_{k+1}(public-score/posterior update)]-mu_k*d_a).
    A future observation is chosen before its latent outcome is drawn; max and
    expectation are not interchanged. Duration 0 is the skip action.
    """
    model.validate()
    w, a, s, n = model.normalized_score.shape
    prices = np.asarray(prices, dtype=float)
    if prices.shape != (w,) or np.any(prices < 0):
        raise ValueError('prices must be a nonnegative window vector')
    bg = np.linspace(0, 1.2, score_bins)
    pg = np.linspace(0, 1, probability_bins)
    value = (model.weights[:, None, None]*bg[None, :, None] +
             model.required_bonus[:, None, None]*pg[None, None, :])
    value = np.broadcast_to(value, (n, score_bins, probability_bins)).copy()
    policy = np.zeros((w, n, score_bins, probability_bins), np.uint8) if keep_policy else None
    suffix = np.empty((w+1, n, score_bins, probability_bins), np.float32) if keep_suffix else None
    if suffix is not None:
        suffix[w] = value
    for k in range(w-1, -1, -1):
        nxt, current = value, value.copy()
        choices = np.zeros_like(current, dtype=np.uint8)
        for j in range(a):
            observed, tau = observable_posteriors(model, k, j)
            option = np.zeros_like(current)
            for r in range(s):
                if model.probabilities[k, r] > 0:
                    option += model.probabilities[k, r] * _transition(nxt, observed[r], tau[r], bg, pg)
            option -= prices[k] * model.durations[k, j]
            better = option > current + 1e-10
            current[better], choices[better] = option[better], j+1
        value = current
        if policy is not None:
            policy[k] = choices
        if suffix is not None:
            suffix[k] = value
    return dict(value=value, policy=policy, suffix=suffix, score_grid=bg,
                probability_grid=pg)


def expected_demand(model, solved, *, normalized_best=None, completed_probability=None):
    """Expected selected fiber seconds from the supplied public ledger belief.

    Propagates the same bilinear state projection as the Bellman sweep. Demand is
    the subgradient of THIS finite interpolation model except at policy ties.
    """
    policy = solved['policy']
    if policy is None:
        raise ValueError('demand requires stored policy')
    w, a, s, n = model.normalized_score.shape
    bg, pg = solved['score_grid'], solved['probability_grid']
    mass = np.zeros((n, len(bg), len(pg)), dtype=float)
    best = np.zeros(n) if normalized_best is None else np.asarray(normalized_best, dtype=float)
    complete = np.zeros(n) if completed_probability is None else np.asarray(completed_probability, dtype=float)
    if best.shape != (n,) or complete.shape != (n,):
        raise ValueError('initial public state must be target vectors')
    rows = np.arange(n)
    bl, bh, bw = _grid_coordinates(best, bg)
    pl, ph, pw = _grid_coordinates(complete, pg)
    for bx, wx in ((bl, 1-bw), (bh, bw)):
        for px, wy in ((pl, 1-pw), (ph, pw)):
            np.add.at(mass, (rows, bx, px), wx*wy)
    demand = np.zeros(w)
    for k in range(w):
        rows, bi, pi = np.nonzero(mass > 1e-15)
        prob = mass[rows, bi, pi]
        action = policy[k, rows, bi, pi]
        output = np.zeros_like(mass)
        skip = action == 0
        np.add.at(output, (rows[skip], bi[skip], pi[skip]), prob[skip])
        for j in range(a):
            take = action == j+1
            if not np.any(take):
                continue
            rn, bn, pn, mn = rows[take], bi[take], pi[take], prob[take]
            demand[k] += mn.sum() * model.durations[k, j]
            observed, tau = observable_posteriors(model, k, j)
            for r in range(s):
                if model.probabilities[k, r] <= 0:
                    continue
                bl, bh, bw = _grid_coordinates(np.maximum(bg[bn], observed[r, rn]), bg)
                pl, ph, pw = _grid_coordinates(pg[pn]+(1-pg[pn])*tau[r, rn], pg)
                mr = mn * model.probabilities[k, r]
                for bx, wx in ((bl, 1-bw), (bh, bw)):
                    for px, wy in ((pl, 1-pw), (ph, pw)):
                        np.add.at(output, (rn, bx, px), mr*wx*wy)
        mass = output
    return demand


def query(value, normalized_best, completed_probability, score_grid, probability_grid):
    """Query common-action belief value without exposing a hidden threshold bit."""
    rows = np.arange(len(normalized_best))
    bl, bh, bw = _grid_coordinates(np.asarray(normalized_best), score_grid)
    pl, ph, pw = _grid_coordinates(np.asarray(completed_probability), probability_grid)
    return ((value[rows, bl, pl]*(1-pw)+value[rows, bl, ph]*pw)*(1-bw) +
            (value[rows, bh, pl]*(1-pw)+value[rows, bh, ph]*pw)*bw)


def priced_iterations(model, capacity, *, iterations=3, step=.0005,
                      score_bins=13, probability_bins=5,
                      normalized_best=None, completed_probability=None):
    """Projected subgradient, best dual iterate retained; no reservation output."""
    capacity = np.asarray(capacity, dtype=float)
    prices = np.zeros(len(capacity))
    n = len(model.weights)
    best = np.zeros(n) if normalized_best is None else np.asarray(normalized_best, dtype=float)
    complete = np.zeros(n) if completed_probability is None else np.asarray(completed_probability, dtype=float)
    logs, incumbent = [], None
    for iteration in range(iterations):
        result = solve(model, prices, score_bins=score_bins,
                       probability_bins=probability_bins)
        demand = expected_demand(model, result, normalized_best=best, completed_probability=complete)
        dual = float(query(result['value'], best, complete, result['score_grid'],
                           result['probability_grid']).sum()+prices@capacity)
        log = dict(iteration=iteration, dual=dual,
                   total_demand=float(demand.sum()), total_capacity=float(capacity.sum()),
                   max_load_ratio=float(np.max(demand/np.maximum(1, capacity))),
                   priced_windows=int(np.count_nonzero(prices)),
                   prices=prices.tolist(), demand=demand.tolist())
        logs.append(log)
        if incumbent is None or dual < incumbent[0]:
            incumbent = dual, prices.copy()
        prices = np.maximum(0, prices + step/np.sqrt(iteration+1) *
                            (demand-capacity)/np.maximum(1, capacity))
    return incumbent[1], logs
