"""Continuous quotient output kernel for an optional ordinary NN density head.

No neural network or weights are fitted here. A positive quotient R is lognormal;
band/mixture probabilities are supplied jointly by a future fitted model.
"""
from __future__ import annotations
import math


def normal_cdf(x):
    return .5*math.erfc(-x/math.sqrt(2.))


def lognormal_gain(weight, multiplier, scale, best, mu, sigma):
    """E[(w*m*min(scale*R,1)-best)+], log(R)~N(mu,sigma^2)."""
    if sigma <= 0 or min(weight,multiplier,scale) <= 0 or best < 0:
        raise ValueError('invalid gain parameters')
    wm = weight*multiplier
    if best >= wm:
        return 0.
    lo = -math.inf if best == 0 else math.log(best/(wm*scale))
    hi = math.log(1/scale)
    interval_probability = normal_cdf((hi-mu)/sigma)-normal_cdf((lo-mu)/sigma)
    truncated_mean = math.exp(mu+.5*sigma*sigma)*(
        normal_cdf((hi-mu-sigma*sigma)/sigma)-
        normal_cdf((lo-mu-sigma*sigma)/sigma))
    tail_probability = normal_cdf((mu-hi)/sigma)
    return max(0., wm*scale*truncated_mean-best*interval_probability+
               (wm-best)*tail_probability)


def joint_gain(components, weight, scale, best, declared, scoring):
    """Each tuple is (probability, actual_band, log_mu, log_sigma).

    A sigma of None marks an R=0 atom. Components are physical law parameters;
    best, weight, future flux scaling and declared program stay outside the head.
    """
    if abs(sum(c[0] for c in components)-1.) > 1e-10:
        raise ValueError('component probabilities must sum to one')
    total = 0.
    program = scoring['program']
    for probability, band, mu, sigma in components:
        if probability < 0:
            raise ValueError('negative probability')
        if sigma is None:
            continue
        multiplier = float(program['multipliers'][declared] if band == declared
                           else program['mismatch_multiplier'])
        total += probability*lognormal_gain(weight,multiplier,scale,best,mu,sigma)
    return total
