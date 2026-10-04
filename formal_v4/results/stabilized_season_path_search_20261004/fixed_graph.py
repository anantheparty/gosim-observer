"""Read the frozen public coefficient graph; exact deterministic path assignment.

No actor, feedback, calendar generator, or hidden-world module is imported.
Native price_shared/compress_intervals are copied from the prior public graph
experiment; every price change rescans all allowed action alternatives.
"""
from __future__ import annotations
import csv
import ctypes
import json
import platform
from pathlib import Path
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import min_weight_full_bipartite_matching

HERE = Path(__file__).resolve().parent
P = ctypes.c_void_p
def ptr(a): return P(a.ctypes.data)

class FixedGraph:
    def __init__(self, graph, catalogue, scoring, fiber_config):
        with np.load(graph, allow_pickle=False) as z:
            for name in z.files:
                setattr(self, name, np.ascontiguousarray(z[name]))
        with Path(catalogue).open() as h:
            self.rows = list(csv.DictReader(h))
        self.ids = [r['target_id'] for r in self.rows]
        self.weight = np.ascontiguousarray([float(r['science_weight']) for r in self.rows])
        config = json.loads(Path(scoring).read_text())['program']
        self.programs = ('DARK', 'BRIGHT', 'BACKUP')
        self.mult = np.ascontiguousarray([config['multipliers'][p] for p in self.programs], dtype=float)
        self.mismatch = float(config['mismatch_multiplier'])
        self.n = len(self.weight); self.ns, self.nd, n = self.factor.shape
        if n != self.n: raise ValueError('catalogue order/length disagrees with coefficient bank')
        self.nf = int(json.loads(Path(fiber_config).read_text())['field']['n_fibers']); self.na = len(self.af)
        if len(self.fiber) and int(self.fiber.max()) >= self.nf: raise ValueError('fiber domain')
        self.group = np.ascontiguousarray(self.field_start[self.af] * self.nd + self.ad, dtype=np.int32)
        lib = HERE / ('oracle.dylib' if platform.system() == 'Darwin' else 'oracle.so')
        self.lib = ctypes.CDLL(str(lib))
        self.lib.price_shared.argtypes = [ctypes.c_int] * 4 + [P] * 12 + [ctypes.c_double] + [P] * 7
        self.lib.compress_intervals.argtypes = [ctypes.c_int] * 2 + [P] * 4
        self.lib.price_shared.restype = None; self.lib.compress_intervals.restype = None
        self._edge_cache = {}

    def edges(self, e):
        e = int(e)
        if e not in self._edge_cache:
            f = int(self.af[e]); s = int(self.field_start[f]); d = int(self.ad[e]); p = int(self.ap[e])
            lo, hi = self.offset[f:f+2]; ids = self.target[lo:hi]; fib = self.fiber[lo:hi]
            use = self.eligible[s, d, ids].astype(bool)
            ids, fib = ids[use], fib[use]
            score = self.weight[ids] * self.factor[s, d, ids] * np.where(self.band[s, d, ids] == p, self.mult[p], self.mismatch)
            self._edge_cache[e] = (ids, fib, score)
        return self._edge_cache[e]

    def pattern(self, e, b, sigma):
        ids, fib, score = self.edges(e); reduced = np.maximum(0., score - b[ids]) - sigma[ids]
        chosen = []
        for f in range(self.nf):
            k = np.flatnonzero(fib == f)
            if len(k):
                j = k[np.argmax(reduced[k])]
                if reduced[j] > 0.: chosen.append(int(j))
        chosen = np.asarray(chosen, dtype=int)
        return ids[chosen], score[chosen]

    def interval_path(self, values, allowed):
        winner = np.empty(self.ns * self.nd, dtype=np.int32)
        self.lib.compress_intervals(self.na, len(winner), ptr(values), ptr(self.group), ptr(allowed), ptr(winner))
        arcs = winner[winner >= 0]
        arcs = arcs[np.lexsort((arcs, self.starts[arcs], self.ends[arcs]))]
        previous = np.searchsorted(self.ends[arcs], self.starts[arcs], side='right')
        V = np.zeros(len(arcs) + 1); take = np.zeros(len(arcs), dtype=bool)
        for k, e in enumerate(arcs):
            v = values[e] + V[previous[k]]
            if v > V[k] + 1e-10: V[k+1] = v; take[k] = True
            else: V[k+1] = V[k]
        path = []; k = len(arcs)
        while k:
            if take[k-1]: path.append(int(arcs[k-1])); k = int(previous[k-1])
            else: k -= 1
        return float(V[-1]), tuple(reversed(path))

    def oracle(self, b, sigma, blocked, window=None):
        allowed = self.starts >= blocked - 1e-7
        if window is not None: allowed &= (self.starts >= window[0] - 1e-7) & (self.ends <= window[1] + 1e-7)
        allowed = np.ascontiguousarray(allowed, dtype=np.uint8)
        values = np.empty(self.na); witness = np.empty(self.n, dtype=np.int32); gmax = np.empty(self.n)
        time_cost = np.zeros(self.na)
        self.lib.price_shared(self.n, self.nf, self.na, self.nd,
            ptr(self.offset), ptr(self.target), ptr(self.fiber), ptr(self.field_start),
            ptr(self.af), ptr(self.ad), ptr(self.ap), ptr(self.factor), ptr(self.band), ptr(self.eligible),
            ptr(self.weight), ptr(self.mult), self.mismatch, ptr(b), ptr(sigma), ptr(time_cost),
            ptr(allowed), ptr(values), ptr(witness), ptr(gmax))
        value, path = self.interval_path(values, allowed)
        counts = np.zeros(self.n); raw = 0.
        for e in path:
            ids, score = self.pattern(e, b, sigma)
            counts[ids] += 1.; raw += float(np.maximum(0., score-b[ids]).sum())
        upper = float(sigma.sum() + value)
        if abs(upper - (sigma.sum() + raw - counts @ sigma)) > 1e-6: raise AssertionError('dual decomposition')
        return dict(upper=upper, path=path, counts=counts, raw=raw, gmax=gmax)

    def match(self, b, path):
        path = tuple(sorted(set(int(e) for e in path), key=lambda e: (self.starts[e], self.ends[e], e)))
        if any(self.starts[z] < self.ends[a] - 1e-7 for a, z in zip(path, path[1:])):
            raise ValueError('overlapping path')
        m = len(path) * self.nf
        ledger = b.copy()
        if not m: return dict(increment=0., path=path, schedule=[], ledger=ledger)
        rr = []; cc = []; vv = []
        for k, e in enumerate(path):
            ids, fib, scores = self.edges(e); gains = scores - b[ids]; use = gains > 0.
            rr.extend((k * self.nf + fib[use]).tolist()); cc.extend(ids[use].tolist()); vv.extend((1. + gains[use]).tolist())
        # Each resource has its own dummy, and every chosen edge receives the
        # same +1. Full matching therefore maximizes gains with empty allowed.
        rr.extend(range(m)); cc.extend((self.n + np.arange(m)).tolist()); vv.extend([1.] * m)
        matrix = coo_matrix((vv, (rr, cc)), shape=(m, self.n+m)).tocsr()
        # A target belongs to one fiber in a field. Duplicate physical incidence
        # would sum rewards in CSR and must never be silently tolerated.
        if matrix.nnz != len(vv): raise ValueError('duplicate resource-target edge')
        r, c = min_weight_full_bipartite_matching(matrix, maximize=True)
        assignment = c[c < self.n]; resources = r[c < self.n]
        if len(np.unique(assignment)) != len(assignment): raise AssertionError('matching repeats target')
        schedule = []
        for k, e in enumerate(path):
            use = resources // self.nf == k; ids = assignment[use]; fibers = resources[use] % self.nf
            ei, ef, es = self.edges(e); scores = []
            for i, f in zip(ids, fibers):
                j = np.flatnonzero((ei == i) & (ef == f))
                if len(j) != 1: raise AssertionError('matching edge absent')
                scores.append(float(es[j[0]]))
            scores = np.asarray(scores); ledger[ids] = np.maximum(ledger[ids], scores)
            schedule.append(dict(action=int(e), start=float(self.starts[e]), end=float(self.ends[e]),
                                 targets=ids.tolist(), fibers=fibers.tolist(), scores=scores.tolist()))
        return dict(increment=float((ledger-b).sum()), path=path, schedule=schedule, ledger=ledger)

    def validate(self, b, control, blocked):
        ledger = b.copy(); seen = set(); previous = blocked; assignments = 0
        if tuple(row['action'] for row in control['schedule']) != control['path']:
            raise AssertionError('empty exposure/time capacity was removed')
        for row in control['schedule']:
            e = row['action']; ids = np.asarray(row['targets'],dtype=int); fib = np.asarray(row['fibers'],dtype=int); score = np.asarray(row['scores'],dtype=float)
            if row['start'] < previous - 1e-7 or row['start'] != self.starts[e] or row['end'] != self.ends[e]: raise AssertionError('time feasibility')
            previous = row['end']
            if len(set(fib)) != len(fib) or any(int(i) in seen for i in ids): raise AssertionError('resource capacity')
            seen.update(int(i) for i in ids)
            ei, ef, es = self.edges(e)
            for i, f, s in zip(ids, fib, score):
                j = np.flatnonzero((ei == i) & (ef == f))
                if len(j) != 1 or abs(es[j[0]]-s) > 1e-10: raise AssertionError('score/eligibility')
            ledger[ids] = np.maximum(ledger[ids], score); assignments += len(ids)
        error = max(abs(float((ledger-b).sum())-control['increment']), float(np.max(np.abs(ledger-control['ledger']))))
        if error > 1e-8: raise AssertionError('max ledger disagreement')
        return dict(nonoverlap=True, fibers=True, unique_winner_target=True, exact_fixed_coefficient_scores=True,
                    max_ledger_error=error, exposures=len(control['schedule']), assignments=assignments)
