"""Actor-safe direct (factor, band) projection; no hidden weather reconstruction."""
from __future__ import annotations
import numpy as np

PROGRAMS = ("DARK", "BRIGHT", "BACKUP")
K = 64
GRID = np.linspace(0., 1., K + 1)

def multiplier_matrix(score_config):
    out = np.full((3, 3), float(score_config['program']['mismatch_multiplier']))
    for j, p in enumerate(PROGRAMS):
        out[j, j] = float(score_config['program']['multipliers'][p])
    return out

def soft_label(g, band, k=K):
    """Mean-preserving deposition on adjacent factor knots, including 0 and 1."""
    g = np.asarray(g, dtype=float)
    band = np.asarray(band, dtype=int)
    if np.any(~np.isfinite(g)) or np.any((g < 0) | (g > 1)):
        raise ValueError('factor labels must be finite in [0,1]')
    x = g * k
    left = np.minimum(np.floor(x).astype(int), k - 1)
    right_weight = x - left
    out = np.zeros(g.shape + (3, k + 1))
    flat = out.reshape((-1, 3, k + 1))
    rows = np.arange(g.size)
    flat[rows, band.ravel(), left.ravel()] += 1 - right_weight.ravel()
    flat[rows, band.ravel(), left.ravel() + 1] += right_weight.ravel()
    return out

def moments(prob):
    """mu_b=E[g 1_band=b], mu=sum_b mu_b; exactly retained by deposition."""
    prob = np.asarray(prob, dtype=float)
    grid = np.linspace(0, 1, prob.shape[-1])
    by_band = np.einsum('...bk,k->...b', prob, grid)
    return by_band.sum(axis=-1), by_band

def expected_gain(prob, weight, best, score_config):
    """All three declared program gains, expectation before assignment."""
    prob = np.asarray(prob, dtype=float)
    weight = np.asarray(weight, dtype=float)
    best = np.asarray(best, dtype=float)
    grid = np.linspace(0, 1, prob.shape[-1])
    mult = multiplier_matrix(score_config)
    hinge = np.maximum(0, weight[..., None, None, None] * mult[None, :, :, None]
                       * grid[None, None, None, :] - best[..., None, None, None])
    return np.einsum('...bk,...pbk->...p', prob, hinge)

def first_gain(prob, weight, score_config):
    mu, mu_b = moments(prob)
    return np.asarray(weight)[..., None] * np.einsum('...b,pb->...p', mu_b,
                                                               multiplier_matrix(score_config))

def public_result(action, hit_scores):
    """Whitelisted public token data; assigned miss is distinct from hit with zero."""
    assigned = list(action['assignments'].values())
    hits = {str(h['target_id']): float(h['score']) for h in hit_scores}
    return [dict(target_id=tid, actual_hit=tid in hits,
                 score_six_decimal=hits.get(tid), declared_program=action['program'],
                 duration_seconds=int(action['duration_seconds'])) for tid in assigned]

class PublicHistory:
    """Loss invalidates best ledger while retaining old measurements for inference."""
    def __init__(self):
        self.observations = []
        self.reports = []

    def observe(self, action_index, action, hit_scores):
        tokens = public_result(action, hit_scores)
        self.observations.append(dict(action_index=int(action_index), action=dict(action),
                                     tokens=tokens, valid=True))
        return tokens

    def report(self, issued_at_utc, result):
        self.reports.append(dict(issued_at_utc=issued_at_utc,
                                 correct=bool(result['correct']),
                                 repaired=bool(result['repaired']),
                                 score_delta=float(result['score_delta'])))

    def resync(self, message):
        window = message['invalidated_window']
        for obs in self.observations:
            if window['action_index_start'] <= obs['action_index'] < window['action_index_end_exclusive']:
                obs['valid'] = False

    def best(self):
        result = {}
        for obs in self.observations:
            if obs['valid']:
                for tok in obs['tokens']:
                    if tok['actual_hit']:
                        result[tok['target_id']] = max(result.get(tok['target_id'], 0.), tok['score_six_decimal'])
        return result
