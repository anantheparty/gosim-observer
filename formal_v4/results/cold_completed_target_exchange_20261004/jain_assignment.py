"""Exact finite assignment with best-only science and RA-count Jain settlement.

Fixed exposure, known conditional contributions and completion flags. This
operator has no future weather, scheduling, loss, or request model.
"""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Option:
    target: int
    fiber: int
    gain: float
    band: int = -1  # -1: this option adds no newly completed target


def jain(counts, sizes):
    sizes = np.asarray(sizes, float)
    r = np.asarray(counts, float)[sizes > 0] / sizes[sizes > 0]
    q = float(r @ r)
    return 0. if not q else float(r.sum() ** 2 / (len(r) * q))


def gradient(counts, sizes):
    sizes = np.asarray(sizes, float)
    r = np.divide(counts, sizes, out=np.zeros(len(sizes)), where=sizes > 0)
    s, q, K = float(r.sum()), float(r @ r), int((sizes > 0).sum())
    if not q: return np.zeros(len(sizes))
    g = 2*s/(K*q) - 2*s*s*r/(K*q*q)
    return np.divide(g, sizes, out=np.zeros(len(sizes)), where=sizes > 0)


def settle(options, counts, sizes, weight):
    added = np.zeros(len(sizes), int)
    for o in options:
        if o.band >= 0: added[o.band] += 1
    return float(sum(o.gain for o in options) + weight*(jain(np.asarray(counts)+added, sizes)-jain(counts,sizes)))


def linear_select(options, counts, sizes, weight):
    g = weight*gradient(counts,sizes)
    result = []
    for f in sorted({o.fiber for o in options}):
        best = None; bestv = 0.
        for o in options:
            if o.fiber != f: continue
            value = o.gain+(g[o.band] if o.band >= 0 else 0.)
            if value > bestv:
                best, bestv = o, value
        if best is not None: result.append(best)
    return result


def exact_select(options, counts, sizes, weight, max_active_bands=2):
    """Sparse cardinality DP, preserving exact completion-count coupling.

    Within one fiber and one added-band signature, retain the largest gain.
    The idle option is always available. Distinct fibers cannot share a target:
    this must follow from the fixed official classification at ingress.
    Each state stores counts for the bands touched by completion candidates.
    """
    seen = {}
    for o in options:
        if o.target in seen and seen[o.target] != o.fiber:
            raise ValueError('one target appears in different fibers')
        seen[o.target] = o.fiber
    active = sorted({o.band for o in options if o.band >= 0})
    if max_active_bands is not None and len(active) > max_active_bands:
        return None
    pos = {b:k for k,b in enumerate(active)}
    states = {(0,)*len(active):(0., ())}
    peak = 1
    for f in sorted({o.fiber for o in options}):
        signatures = {}
        for o in options:
            if o.fiber != f: continue
            old = signatures.get(o.band)
            if old is None or o.gain > old.gain: signatures[o.band] = o
        nxt = {}
        for state,(v,path) in states.items():
            for o in [None]+list(signatures.values()):
                key = state; nv = v; npth = path
                if o is not None:
                    k = list(state)
                    if o.band >= 0: k[pos[o.band]] += 1
                    key=tuple(k);nv=v+o.gain;npth=path+(o,)
                if key not in nxt or nv > nxt[key][0]: nxt[key]=(nv,npth)
        states=nxt;peak=max(peak,len(states))
    b0=jain(counts,sizes)
    best=(-np.inf,())
    for state,(v,path) in states.items():
        added=np.zeros(len(sizes),int)
        for b,k in pos.items(): added[b]=state[k]
        value=v+weight*(jain(np.asarray(counts)+added,sizes)-b0)
        if value > best[0]: best=(float(value),path)
    return {'value':best[0], 'chosen':list(best[1]), 'active_bands':active,
            'states':len(states), 'peak_states':peak}
