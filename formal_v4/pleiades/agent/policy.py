"""Scalable v4 observer policy: per-decision greedy field selection with a season-aware value model.

Value of observing target i for T seconds with program P:
    rho_i * [ max(0, w_i E[m|P] g_i(T) phi_i(T) - best_i) + required bonus + request bonus ]
phi discounts partial completions relative to the best completion still reachable this season,
rho = (H_now / H_best_remaining)^alpha prefers each target's own best geometry.
Field (centre, T, P) maximises sum over fibre cells of the best target value, divided by T.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

from astro import DEG, SID, airmass, fmt_utc, lst_deg, moon_state, parse_utc

PROGRAMS = ('DARK', 'BRIGHT', 'BACKUP')
CLOSE_KINDS = ('rain', 'storm', 'rainy', 'tornado')
EXCUSE_KINDS = ('overcast', 'haze', 'cloudy', 'smoggy', 'rain', 'storm', 'rainy', 'tornado')
WEATHER_KINDS = ('overcast', 'haze', 'cloudy', 'smoggy', 'cold_snap', 'cold_wave', 'rain', 'storm', 'rainy', 'tornado')
DIR_AZ = {'N': 0.0, 'NE': 45.0, 'E': 90.0, 'SE': 135.0, 'S': 180.0, 'SW': 225.0, 'W': 270.0, 'NW': 315.0}

DEFAULTS = {
    'gamma': 1.0,          # partial-completion discount exponent
    'alpha': 2.0,          # timing exponent
    'zref_scale': 1.0,     # gmax reference quality relative to mean Z
    'req_safety': 1.1,     # required/request completion safety on predicted factor
    'g_sigma': 0.10,       # model log-uncertainty of a predicted completion factor
    'fault_drop': 0.22,    # log drop of efficiency below expectation that counts as low
    'fault_streak': 2,     # consecutive low informative exposures before a report
    'fault_prior': 0.03,
    'req_bonus_scale': 1.0,
    'request_scale': 0.9,
    'anchors': 24,
    'refine_top': 3,
    'margin_frac': 0.02,   # minimum distance to a cell boundary, fraction of pitch
    'band_sigma': 0.08,
    'pool_max': 5000,
    'min_value_frac': 0.02,
    'budget_safety': 0.80,
    'wx_infl': 1.1,        # inflation of the weather process noise
    'fault_window_mass': 0.8,
    'rep_free': 0.4,       # fault posterior that triggers a free report
    'rep_paid': 0.7,       # ... a paid report
    'max_faults': 1,       # instrument faults per season (generator default)
    'max_paid': 4,         # cap on penalised (non-free) reports
    'urgency': 0.0,        # exponent of the remaining-visibility priority
    't0_max': 0.0,         # virtual exposure overhead (s) for time-rich surveys
    'refine_iter': 0,      # >0: iterative pattern-search rounds for the field centre
    'req_scrit': 0.0,      # >0: required bonus scaled by min(1, req_scrit / remaining good hours)
    'zref_rich': 1.0,      # >1: reference quality multiplier for partial completions when time-rich
    'season_rho': 0.0,     # >0: timing factor includes the seasonal sky quality when time-rich (blend weight)
    'gamma_rich': 0.0,     # >0: partial-completion exponent when time-rich (blended with gamma by richness)
    'margin_clean': -1.0,  # >=0: cell-edge margin (fraction of pitch) once 20 exposures showed no pointing miss
    't0_const': 0.0,       # constant virtual per-field overhead (s) in value / (T + T0)
    'alpha_rich': -1.0,    # >=0: timing exponent when time-rich (blended with alpha by richness): observe early, retry later
    'false_absorb': 0,     # 1: a false report folds the explained drop into the weather state
    'report_gap': 0,       # >0: informative exposures required after a false report before the next report
    'rich_cap_lo': 0.2,    # capacity ratio at/below which the survey is fully time-rich
    'rich_cap_hi': 0.6,    # capacity ratio at/above which it is capacity-limited (richness 0)
    'req_hard': 0.0,       # >0: log-SD of sky quality; req_scrit counts only hours good enough for each target
    'budget_front': 0.0,   # >0: per-decision budget boost early in the season (1 + x * fraction of season left)
    'pool_floor': 0.1,     # lower bound of the adaptive candidate-pool scale
    'pool_floor_min': 0.02,  # ... and below it when the budget is nearly gone with much of the season left
    'dec_T_floor': 120.0,  # lower bound of the mean exposure used to project the decisions left
    'opt_value': 0.0,      # >0: (time-rich) value repeats by their expected improvement over the best so far
    'fault_counts': [],    # belief over the number of instrument faults (c = 1, 2, ...); empty: single fault
    'fault_counts_stress': [],   # ... switched to once the card shows stress signs (pointing misses, data loss)
    'min_hits': 2,         # unobstructed hits an exposure needs to update the weather / instrument belief
    'req_moon': 0,         # 1: req_scrit counts the expected hours (Moon, airmass, season, sky scatter) in which
                           #    one max-length exposure completes each required target
    'req_moon_m': 8,       # samples per night for that count
    'req_moon_sig': 0.37,  # log-SD of the sky quality of a future night
    'req_moon_urg': 0,     # 1: the urgency of incomplete required targets uses those completion hours too
    'req_floor': 0.1,      # lower clip of the req_scrit bonus scale
    'req_urg': 0.0,        # >0: urgency exponent of incomplete required targets (cap req_urg_cap)
    'req_urg_cap': 6.0,
    'omega_mid': 0,        # 1: the closure likelihood also allows closed whole slots inside an exposure
    'rep_streak': 2,       # belief updates with an elevated fault posterior needed before a free report
    'rep_streak_paid': 2,  # ... before a paid report
    'rq_rich': 0.0,        # >0: request bonuses x (1 + rq_rich * richness): requests are cheap when time-rich
    'refine_scale': 0,     # 1: refinement starts shrink with the budget-capped anchor count
    'front_gate': 0,       # 1: the early-season budget boost applies only while spending is at or below
                           #    the linear pace (remaining budget fraction >= remaining dark-time fraction)
    'pool_grow_anchors': 0,  # >0: the candidate pool regrows once twice this many anchors fit the budget
                             #     (0: twice 'anchors'); keeps the pool ahead of extra anchors on heavy cards
    'rep_esc': 0.0,        # extra belief updates of evidence required per false report since the last correct one
    'threads': 2,          # worker threads for the field search and the per-target values (the platform charges
                           #     a turn's CPU of all threads, at most the turn's real time; the container has 2 cores)
    'rep_override': 0,     # >0: past max_paid, still report (at most twice) after this many consecutive updates
                           #     with p_fault >= 0.9
    'llm': 1,              # 1: a language model plans the season strategy (llm_strategist.py: mission analysis at
                           #    initialisation, weekly plan review); 0: the rule-based default strategy only
}

TGRID = np.array([60, 120, 180, 240, 300, 420, 540, 660, 780, 900, 1080, 1260, 1500, 1800,
                  2100, 2400, 2700, 3000, 3300, 3600], dtype=float)


def _log(obj):
    try:
        # one write per line: the LLM strategist logs from its own thread
        sys.stderr.write(json.dumps(obj, separators=(',', ':'), default=str) + '\n')
        sys.stderr.flush()
    except Exception:
        pass


class Kernel:
    def __init__(self):
        self.lib = None
        self.groups = False
        here = Path(__file__).resolve().parent
        for name in ('libkern_linux_x86_64.so', 'libkern.so'):
            p = here / name
            if p.exists():
                try:
                    lib = ctypes.CDLL(str(p))
                    P, I, D = ctypes.c_void_p, ctypes.c_int, ctypes.c_double
                    lib.eval_centers.argtypes = [I, P, P, I, P, I, P, P, I, D, D, D, P, P, P, P]
                    lib.eval_centers.restype = None
                    lib.assign_center.argtypes = [D, D, I, P, I, P, I, D, D, D, I, I, P, P]
                    lib.assign_center.restype = None
                    lib.offset_consistency.argtypes = [I, P, P, D, D, I, P, P, P, I, D, P]
                    lib.offset_consistency.restype = None
                    if hasattr(lib, 'eval_groups'):
                        lib.eval_groups.argtypes = [I, P, P, P, P, P, I, P, I, P, P, I, D, D, D, D, P, P, D, P, P, P, P]
                        lib.eval_groups.restype = None
                        self.groups = True
                    self.lib = lib
                    break
                except OSError:
                    self.lib = None

    # ---- numpy fallbacks share the exact classification rule ----
    @staticmethod
    def _classify_np(calt, caz, tv, side, pitch, margin_min, cos_r):
        a, z = calt * DEG, caz * DEG
        c = np.array([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])
        up = np.array([-math.sin(a) * math.cos(z), -math.sin(a) * math.sin(z), math.cos(a)])
        rt = np.array([-math.sin(z), math.cos(z), 0.0])
        depth = tv @ c
        ok = depth >= cos_r
        dep = np.where(ok, depth, 1.0)
        dal = (tv @ up) / dep / DEG
        daz = (tv @ rt) / dep / DEG
        half = side * pitch / 2.0
        ok &= (np.abs(dal) <= half) & (np.abs(daz) <= half)
        row = np.clip(np.floor(dal / pitch + side / 2.0), 0, side - 1).astype(int)
        col = np.clip(np.floor(daz / pitch + side / 2.0), 0, side - 1).astype(int)
        cn = (row - (side - 1) / 2.0) * pitch
        ce = (col - (side - 1) / 2.0) * pitch
        m = pitch / 2.0 - np.maximum(np.abs(dal - cn), np.abs(daz - ce))
        ok &= m >= margin_min
        return np.flatnonzero(ok), (row * side + col)[ok], m[ok]

    def eval_centers(self, calt, caz, tv, val, tgrid, side, pitch, margin_min, cos_r):
        nc = len(calt)
        rate = np.zeros(nc)
        bt = np.zeros(nc, dtype=np.int32)
        bp = np.zeros(nc, dtype=np.int32)
        tot = np.zeros(nc)
        if self.lib is not None:
            calt = np.ascontiguousarray(calt, dtype=np.float64)
            caz = np.ascontiguousarray(caz, dtype=np.float64)
            tv = np.ascontiguousarray(tv, dtype=np.float64)
            val = np.ascontiguousarray(val, dtype=np.float32)
            tg = np.ascontiguousarray(tgrid, dtype=np.float64)
            self.lib.eval_centers(nc, calt.ctypes.data, caz.ctypes.data, len(tv), tv.ctypes.data, len(tg),
                                  val.ctypes.data, tg.ctypes.data, side, pitch, margin_min, cos_r,
                                  rate.ctypes.data, bt.ctypes.data, bp.ctypes.data, tot.ctypes.data)
            return rate, bt, bp, tot
        F = side * side
        nt = len(tgrid)
        for k in range(nc):
            idx, cell, _ = self._classify_np(calt[k], caz[k], tv, side, pitch, margin_min, cos_r)
            cells = np.zeros((nt, 3, F))
            if len(idx):
                v = val[idx].transpose(1, 2, 0)  # nt,3,n
                np.maximum.at(cells, (slice(None), slice(None), cell), np.maximum(v, 0))
            totals = cells.sum(axis=2)
            rates = totals / tgrid[:, None]
            j = int(np.argmax(rates))
            bt[k], bp[k] = divmod(j, 3)
            rate[k] = rates.flat[j]
            tot[k] = totals.flat[j]
        return rate, bt, bp, tot

    def assign(self, calt, caz, tv, val, side, pitch, margin_min, cos_r, t, p):
        F = side * side
        out_t = np.full(F, -1, dtype=np.int32)
        out_v = np.zeros(F)
        if self.lib is not None:
            tv = np.ascontiguousarray(tv, dtype=np.float64)
            val = np.ascontiguousarray(val, dtype=np.float32)
            self.lib.assign_center(float(calt), float(caz), len(tv), tv.ctypes.data, val.shape[1], val.ctypes.data,
                                   side, pitch, margin_min, cos_r, int(t), int(p), out_t.ctypes.data, out_v.ctypes.data)
            return out_t, out_v
        idx, cell, marg = self._classify_np(calt, caz, tv, side, pitch, margin_min, cos_r)
        bm = np.full(F, -1.0)
        for j, f, m in zip(idx, cell, marg):
            x = float(val[j, t, p])
            if x > 0 and (x > out_v[f] + 1e-12 or (abs(x - out_v[f]) <= 1e-12 and m > bm[f])):
                out_v[f], out_t[f], bm[f] = x, j, m
        return out_t, out_v

    def offset_agree(self, oalt, oaz, calt, caz, tv, fib, hit, side, pitch):
        no = len(oalt)
        out = np.zeros(no, dtype=np.int32)
        if self.lib is not None:
            oalt = np.ascontiguousarray(oalt, dtype=np.float64)
            oaz = np.ascontiguousarray(oaz, dtype=np.float64)
            tv = np.ascontiguousarray(tv, dtype=np.float64)
            fib = np.ascontiguousarray(fib, dtype=np.int32)
            hit = np.ascontiguousarray(hit, dtype=np.int32)
            self.lib.offset_consistency(no, oalt.ctypes.data, oaz.ctypes.data, float(calt), float(caz), len(tv),
                                        tv.ctypes.data, fib.ctypes.data, hit.ctypes.data, side, pitch, out.ctypes.data)
            return out
        for k in range(no):
            idx, cell, _ = self._classify_np(calt + oalt[k], caz + oaz[k], tv, side, pitch, -1e9, 0.0)
            pred = np.zeros(len(tv), dtype=np.int32)
            pred[idx] = (cell == fib[idx]).astype(np.int32)
            out[k] = int(np.sum(pred == hit))
        return out


# ---------------------------------------------------------------------- weather / instrument belief
SIG_N, SIG_S, PHI_N, PHI_S = 0.189, 0.078, 0.82, 0.88       # log site-quality AR(1) structure (generator)
EV_KEYS = ('overcast', 'haze', 'cold_snap')
EV_ALIAS = {'cloudy': 'overcast', 'overcast': 'overcast', 'smoggy': 'haze', 'haze': 'haze',
            'cold_wave': 'cold_snap', 'cold_snap': 'cold_snap'}
EV_PRIOR = {'overcast': (-0.92, 0.22), 'haze': (-0.64, 0.15), 'cold_snap': (-0.085, 0.03)}
MU_GRID = np.array([1.0, 0.30, 0.36, 0.43, 0.51, 0.61, 0.73])
D0_GRID = np.exp(np.linspace(math.log(0.17), math.log(0.95), 17))
CM_NODES = np.array([-math.sqrt(3.0), 0.0, math.sqrt(3.0)])     # 3-point Gauss-Hermite
CM_LW = np.log(np.array([1.0 / 6.0, 2.0 / 3.0, 1.0 / 6.0]))


class Belief:
    """Bank of Kalman filters on log site quality C, one per instrument-fault hypothesis.

    log C(t) = m(night) + b + n + s + sum_j a_j e_j
      b: site bias (static), n: night-level AR(1) deviation, s: slot-level AR(1) deviation,
      e_j: log offset of an announced all-sky weather event (overcast / haze / cold snap).
    Hypothesis k: efficiency eta = eta_nom * quake(t) * MU[k]  (MU[0] = 1: no fault).
    Fault onsets follow the generator prior: uniform within +-200 slots of the mid-season slot,
    plus a small background hazard.  Evidence of each exposure is computed on a grid of log C.
    """
    D = 6

    def __init__(self, nights, slot, q0, f0t0, mult, mismatch, band_dark, band_bright, mseason,
                 eta_nom=0.95, infl=1.1, p_window=0.8, window=200):
        self.nights = nights
        self.night_start = np.array([a for a, _ in nights])
        self.slot = float(slot)
        self.q0, self.f0t0 = q0, f0t0
        self.lmult = np.log(mult)
        self.lmis = math.log(mismatch)
        self.ld, self.lbr = math.log(band_dark), math.log(band_bright)
        self.mseason = mseason
        self.leta = math.log(eta_nom)
        self.sn2, self.ss2 = (SIG_N * infl) ** 2, (SIG_S * infl) ** 2
        K = len(MU_GRID)
        self.K = K
        self.lmu = np.log(MU_GRID)
        self.x = np.zeros((K, self.D))
        self.P = np.zeros((K, self.D, self.D))
        self.P[:, 0, 0] = 0.12 ** 2
        self.P[:, 1, 1] = self.sn2
        self.P[:, 2, 2] = self.ss2
        self.w = np.zeros(K)
        self.w[0] = 1.0
        self.t = None
        self.night = None
        self.ev_on = [False, False, False]
        self.haz_scale = 1.0
        st = []
        for a, b in nights:
            n = int(round((b - a) / self.slot))
            st.extend(a + self.slot * np.arange(n))
        self.slot_t = np.array(st, dtype=float)
        N = max(1, len(st))
        self.N, self.win, self.p_window = N, window, p_window
        # number of instrument faults c: the generator puts fault k (1-based) at k*N/(c+1) +- window slots;
        # each fault persists until reported. pc is the belief over c = 1..len(pc).
        self.pc = np.array([1.0])
        self.nfault = 0
        self.multi = False
        self._build_prior(0)
        self.quakes = []          # dicts: t, night, lw (D0_GRID log-weights)
        eps = 0.04
        self.l_in = math.log(1.0 - eps) - math.log(0.012 * math.sqrt(2.0 * math.pi))
        self.l_out = math.log(eps) - math.log(4.0)
        self.pf_hist = []
        self.n_upd = 0
        self.absorb_false = False

    # ---------------------------------------------------------------- dynamics
    def set_fault_prior(self, pc, from_t=None):
        """Belief over the number of faults per season (pc[c-1]); rebuild the next-fault onset prior."""
        self.pc = np.asarray(pc, dtype=float) / float(np.sum(pc))
        self.multi = len(self.pc) > 1
        self.jnext = np.ones(len(self.pc), dtype=int)
        k = 0 if from_t is None else int(np.searchsorted(self.slot_t, from_t, side='right'))
        self._build_prior(k)

    def _window(self, j, c):
        centre = int(j * self.N / (c + 1))
        return max(0, centre - self.win), min(self.N - 1, centre + self.win)

    def _build_prior(self, k0):
        """Onset prior of the next fault on slots >= k0 (fault j of count c sits at j*N/(c+1) +- window),
        plus the probability mass of 'no further fault'."""
        N = self.N
        if not hasattr(self, 'jnext'):
            self.jnext = np.ones(len(self.pc), dtype=int)
        pm = np.zeros(N)
        p_more = 0.0
        for ci, w in enumerate(self.pc):
            c = ci + 1
            j = int(self.jnext[ci])
            if w <= 0 or j > c:
                continue
            lo, hi = self._window(j, c)
            lo2 = max(lo, k0)
            if hi >= lo2:
                pm[lo2:hi + 1] += self.p_window * w / (hi - lo + 1)
            p_more += w
        eps = 0.02 if self.nfault > 0 else 0.0          # faults the count model does not explain
        bg = (1.0 - self.p_window) * p_more + eps * (1.0 - p_more)
        if k0 < N:
            pm[k0:] += bg / (N - k0)
        p_never = 0.0 if (self.nfault == 0 and not self.multi) else max(0.0, (1.0 - p_more) * (1.0 - eps))
        self.surv = np.concatenate((np.cumsum(pm[::-1])[::-1], [0.0])) + p_never
        self.prior_k0 = k0

    def fault_found(self, onset_t, now_t):
        """A correct report: match the onset slot to each count's fault windows, update the count belief
        and prepare the next fault's prior (robust to an earlier fault that went unnoticed)."""
        if self.multi:
            s_on = int(np.searchsorted(self.slot_t, onset_t, side='right')) - 1
            like = np.zeros(len(self.pc))
            for ci in range(len(self.pc)):
                c = ci + 1
                hit = None
                for j in range(1, c + 1):
                    lo, hi = self._window(j, c)
                    if lo - 40 <= s_on <= hi + 20:
                        hit = (j, hi - lo + 1)
                        break
                if hit is not None:
                    like[ci] = self.p_window / hit[1] + (1.0 - self.p_window) / self.N
                    # an earlier fault of this count would have had to go unnoticed (it persists until reported,
                    # so the detector would have seen it): penalise each skipped fault
                    like[ci] *= 0.05 ** max(0, hit[0] - int(self.jnext[ci]))
                    self.jnext[ci] = hit[0] + 1
                else:
                    like[ci] = (1.0 - self.p_window) / self.N
                    nxt = [j for j in range(1, c + 1) if self._window(j, c)[0] > s_on]
                    self.jnext[ci] = nxt[0] if nxt else c + 1
            post = self.pc * like
            if post.sum() > 0:
                self.pc = post / post.sum()
        self.nfault += 1
        self._build_prior(int(np.searchsorted(self.slot_t, now_t, side='right')))

    def _hazard(self, t1, t2):
        sa = int(np.searchsorted(self.slot_t, t1, side='right'))
        sb = int(np.searchsorted(self.slot_t, t2, side='right'))
        S = self.surv[sa]
        if S <= 1e-15 or sb <= sa:
            return 0.0
        return float(min(1.0, (S - self.surv[sb]) / S)) * self.haz_scale

    def _advance(self, x, P, t, night):
        if self.t is None:
            return
        if night == self.night:
            r = PHI_S ** (max(0.0, t - self.t) / self.slot)
            x[:, 2] *= r
            P[:, 2, :] *= r
            P[:, :, 2] *= r
            P[:, 2, 2] += self.ss2 * (1.0 - r * r)
        else:
            a = PHI_N ** max(1, night - (self.night if self.night is not None else night - 1))
            x[:, 1] *= a
            P[:, 1, :] *= a
            P[:, :, 1] *= a
            P[:, 1, 1] += self.sn2 * (1.0 - a * a)
            x[:, 2] = 0.0
            P[:, 2, :] = 0.0
            P[:, :, 2] = 0.0
            k = math.floor(max(0.0, t - self.night_start[night]) / self.slot) + 1
            P[:, 2, 2] = self.ss2 * (1.0 - PHI_S ** (2 * k))

    def _set_events(self, act):
        for j, key in enumerate(EV_KEYS):
            c = 3 + j
            on = act[j] > 0
            if on and not self.ev_on[j]:
                self.x[:, c] = EV_PRIOR[key][0]
                self.P[:, c, :] = 0.0
                self.P[:, :, c] = 0.0
                self.P[:, c, c] = EV_PRIOR[key][1] ** 2
            elif not on and self.ev_on[j]:
                self.x[:, c] = 0.0
                self.P[:, c, :] = 0.0
                self.P[:, :, c] = 0.0
            self.ev_on[j] = on

    def predict_to(self, t, night):
        if self.t is not None:
            h = self._hazard(self.t, t)
        else:
            h = 0.0
        self._advance(self.x, self.P, t, night)
        new = h * self.w[0] / (self.K - 1)
        # prune fault branches whose history explains the data no better than a fresh onset: they
        # re-enter as "fault starts now" with the no-fault state (prevents drifting zombie states)
        for k in range(1, self.K):
            if self.w[k] < max(1e-6, 3.0 * new):
                self.w[k] = 0.0
                self.x[k] = self.x[0]
                self.P[k] = self.P[0]
        if h > 0.0:
            w0 = self.w[0]
            for k in range(1, self.K):
                wk = self.w[k]
                tot = wk + new
                if tot <= 0:
                    continue
                if wk <= 1e-12 * new:
                    self.x[k] = self.x[0]
                    self.P[k] = self.P[0]
                else:
                    xm = (wk * self.x[k] + new * self.x[0]) / tot
                    d1, d0 = self.x[k] - xm, self.x[0] - xm
                    self.P[k] = (wk * (self.P[k] + np.outer(d1, d1)) + new * (self.P[0] + np.outer(d0, d0))) / tot
                    self.x[k] = xm
                self.w[k] = tot
            self.w[0] = w0 * (1.0 - h)
            self.w /= self.w.sum()
        self.t, self.night = t, night

    # ---------------------------------------------------------------- quakes
    def add_quake(self, t, night):
        lw = np.zeros(len(D0_GRID))
        self.quakes.append({'t': t, 'night': night, 'lw': lw})

    def _d0_hat(self, q):
        w = np.exp(q['lw'] - q['lw'].max())
        return float(np.sum(w * D0_GRID) / w.sum())

    def quake_factor(self, start, T, night, override=None):
        """Exposure-average efficiency factor of all known quakes; override=(quake, d0) for one quake."""
        f = 1.0
        end = start + T
        for q in self.quakes:
            if end <= q['t'] or night < q['night']:
                continue
            d0 = override[1] if override is not None and override[0] is q else self._d0_hat(q)
            frac = min(1.0, (end - max(start, q['t'])) / max(1.0, T))
            f *= 1.0 - frac * d0 * math.exp(-(night - q['night']) / 4.0)
        return max(0.03, f)

    def learning_quake(self, night):
        """Fault evidence is frozen while a fresh shock's degradation is still being learned."""
        for q in self.quakes:
            if night == q['night'] or (night == q['night'] + 1 and q.get('n', 0) < 3):
                return True
        return False

    # ---------------------------------------------------------------- measurement
    def _loglik(self, X, leta, lk0, lH, ly, P, lom, lwo):
        """log p(y | X, eta) for each log-efficiency in leta (E,) on grid X (G,) -> (E, G)."""
        sb, st = 0.02, 0.012
        E = len(leta)
        Xg = X[None, None, :, None]                                   # 1,1,G,1
        cm = (CM_NODES * 0.035)[None, :, None, None]                  # common-mode shift (slot-to-slot C, jitter)
        out = None
        for om_l, wl in zip(lom, lwo):
            lB = Xg + om_l + lH[None, None, None, :]                  # 1,1,G,n (eta jitter does not enter the band)
            pdk = 0.5 * (1.0 + _erf((lB - self.ld) / (sb * math.sqrt(2.0))))
            pbr = 0.5 * (1.0 + _erf((lB - self.lbr) / (sb * math.sqrt(2.0))))
            pm = pdk if P == 0 else (pbr - pdk if P == 1 else 1.0 - pbr)
            pm = np.clip(pm, 1e-9, 1.0 - 1e-9)
            lg = np.minimum(0.0, lk0[None, None, None, :] + Xg + om_l + leta[:, None, None, None] + cm)   # E,C,G,n
            r1 = ly[None, None, None, :] - self.lmult[P] - lg
            r0 = ly[None, None, None, :] - self.lmis - lg
            lp = np.logaddexp(np.log(pm) - 0.5 * (r1 / st) ** 2, np.log(1.0 - pm) - 0.5 * (r0 / st) ** 2)
            # per-target outliers (partial terrain / sector obstruction): broad component in log y
            lp = np.logaddexp(lp + self.l_in, self.l_out)
            ll = lp.sum(axis=3) + CM_LW[None, :, None]                # E,C,G
            m = ll.max(axis=1, keepdims=True)
            ll = (m + np.log(np.exp(ll - m).sum(axis=1, keepdims=True)))[:, 0, :] + wl
            out = ll if out is None else np.logaddexp(out, ll)
        return out

    def _outlier_frac(self, X0, leta, lk0, lH, ly, P, lom):
        """Mean posterior responsibility of the outlier component at log C = X0 (best open fraction)."""
        sb, st = 0.02, 0.012
        best = None
        for om_l in lom:
            lB = X0 + om_l + lH
            pdk = 0.5 * (1.0 + _erf((lB - self.ld) / (sb * math.sqrt(2.0))))
            pbr = 0.5 * (1.0 + _erf((lB - self.lbr) / (sb * math.sqrt(2.0))))
            pm = np.clip(pdk if P == 0 else (pbr - pdk if P == 1 else 1.0 - pbr), 1e-9, 1.0 - 1e-9)
            lg = np.minimum(0.0, lk0 + X0 + om_l + leta)
            r1 = ly - self.lmult[P] - lg
            r0 = ly - self.lmis - lg
            lin = np.logaddexp(np.log(pm) - 0.5 * (r1 / st) ** 2, np.log(1.0 - pm) - 0.5 * (r0 / st) ** 2) + self.l_in
            tot = np.logaddexp(lin, self.l_out)
            if best is None or tot.sum() > best[0]:
                best = (tot.sum(), float(np.mean(np.exp(self.l_out - tot))))
        return best[1]

    def observe(self, t_mid, night, start, f, H, y, T, P, omegas, wprior, act, freeze=False):
        self.predict_to(t_mid, night)
        self._set_events(act)
        h = np.array([1.0, 1.0, 1.0, act[0], act[1], act[2]])
        m = self.mseason[night]
        mx = m + self.x @ h
        vx = np.maximum(np.einsum('i,kij,j->k', h, self.P, h), 1e-6)
        sd = np.sqrt(vx)
        lo = min(float(np.min(mx - 5.0 * sd)), float(mx[0]) - 1.0)
        hi = max(float(np.max(mx + 5.0 * sd)), float(mx[0]) + 0.6)
        G = int(min(241, max(101, (hi - lo) / 0.014)))
        X = np.linspace(lo, hi, G)
        dx = X[1] - X[0]
        k0 = f * T * H / (self.q0 * self.f0t0)
        lk0 = np.log(np.maximum(k0, 1e-12))
        lH = np.log(H) - math.log(self.q0)
        ly = np.log(np.maximum(y, 1e-9))
        lom = np.log(np.asarray(omegas, dtype=float))
        lwo = np.log(np.asarray(wprior, dtype=float))
        # quake efficiency: learn the shock degradation first (shock night and the next)
        kmap = int(np.argmax(self.w))
        for q in self.quakes:
            if 0 <= night - q['night'] <= 1 and start + T > q['t']:
                le = np.array([self.leta + self.lmu[kmap] + math.log(self.quake_factor(start, T, night, (q, d)))
                               for d in D0_GRID])
                ll = self._loglik(X, le, lk0, lH, ly, P, lom, lwo)
                lp = -0.5 * (X - mx[kmap]) ** 2 / vx[kmap]
                lz = ll + lp[None, :]
                mm = lz.max(axis=1, keepdims=True)
                q['lw'] = q['lw'] + (mm[:, 0] + np.log(np.exp(lz - mm).sum(axis=1)))
                q['lw'] -= q['lw'].max()
                q['n'] = q.get('n', 0) + 1
        qf = self.quake_factor(start, T, night)
        leta = self.leta + math.log(qf) + self.lmu
        ll = self._loglik(X, leta, lk0, lH, ly, P, lom, lwo)              # K,G
        lpost = ll - 0.5 * (X[None, :] - mx[:, None]) ** 2 / vx[:, None] - 0.5 * np.log(2 * math.pi * vx)[:, None]
        mm = lpost.max(axis=1, keepdims=True)
        pw = np.exp(lpost - mm)
        Z = pw.sum(axis=1)
        logZ = mm[:, 0] + np.log(Z) + math.log(dx)
        pw /= Z[:, None]
        pmean = pw @ X
        pvar = np.maximum(pw @ (X * X) - pmean ** 2, (dx * 0.5) ** 2)
        # contaminated exposure (e.g. targets entering terrain mid-exposure): the best explanation still
        # needs many per-target outliers -> do not learn from it
        kb = int(np.argmax(np.log(np.maximum(self.w, 1e-300)) + logZ))
        ofrac = self._outlier_frac(pmean[kb], leta[kb], lk0, lH, ly, P, lom)
        if ofrac > 0.3 and len(y) >= 3:
            self.n_bad = getattr(self, 'n_bad', 0) + 1
            return {'mx': [round(float(v), 3) for v in mx[:1]], 'post': round(float(pmean[0]), 3),
                    'pf': round(self.p_fault(), 4), 'kmap': self.kmap(), 'qf': round(qf, 3), 'bad': round(ofrac, 2)}
        for k in range(self.K):
            if pvar[k] >= vx[k] * 0.995:
                continue
            R = 1.0 / (1.0 / pvar[k] - 1.0 / vx[k])
            z = R * (pmean[k] / pvar[k] - mx[k] / vx[k])
            Ph = self.P[k] @ h
            S = vx[k] + R
            Kg = Ph / S
            self.x[k] = self.x[k] + Kg * (z - mx[k])
            self.P[k] = self.P[k] - np.outer(Kg, Ph)
            self.P[k] = 0.5 * (self.P[k] + self.P[k].T)
        if not freeze and np.isfinite(logZ).all():
            lw = np.log(np.maximum(self.w, 1e-300)) + logZ
            lw -= lw.max()
            self.w = np.exp(lw)
            self.w /= self.w.sum()
        self.n_upd += 1
        pf = self.p_fault()
        self.pf_hist.append(pf)
        return {'mx': [round(float(v), 3) for v in mx[:1]], 'post': round(float(pmean[0]), 3),
                'pf': round(pf, 4), 'kmap': int(np.argmax(self.w)), 'qf': round(qf, 3)}

    # ---------------------------------------------------------------- queries
    def p_fault(self):
        return float(1.0 - self.w[0])

    def kmap(self):
        return int(np.argmax(self.w))

    def peek(self, t, night, act):
        """Predicted (mean, var) of log C at time t under the most probable hypothesis."""
        k = self.kmap()
        x = self.x[k:k + 1].copy()
        P = self.P[k:k + 1].copy()
        if self.t is not None and (night != self.night or t >= self.t):
            self._advance(x, P, t, night)
        mean = self.mseason[night] + x[0, 0] + x[0, 1] + x[0, 2]
        var = P[0, 0, 0] + P[0, 1, 1] + P[0, 2, 2] + 2 * (P[0, 0, 1] + P[0, 0, 2] + P[0, 1, 2])
        for j, key in enumerate(EV_KEYS):
            if act[j] > 0:
                if self.ev_on[j]:
                    c = 3 + j
                    mean += x[0, c]
                    var += P[0, c, c] + 2 * (P[0, c, 0] + P[0, c, 1] + P[0, c, 2])
                else:
                    mean += EV_PRIOR[key][0]
                    var += EV_PRIOR[key][1] ** 2
        return float(mean), float(max(var, 1e-6))

    def leta_plan(self, t, night):
        return self.leta + math.log(self.quake_factor(t, 1.0, night)) + self.lmu[self.kmap()]

    def clim(self, night):
        k = self.kmap()
        return float(self.mseason[night] + self.x[k, 0])

    def absorb_as_quake(self, t, night):
        """Explain the current efficiency drop as a new (merged-notice) earthquake starting at t."""
        self.report_result(True, keep_hazard=True)
        self.add_quake(t, night)

    def report_result(self, correct, keep_hazard=False):
        if correct:
            wf = self.w[1:].copy()
            if wf.sum() <= 0:
                wf = np.ones(self.K - 1)
            wf /= wf.sum()
            xm = wf @ self.x[1:]
            Pm = np.zeros((self.D, self.D))
            for k in range(1, self.K):
                d = self.x[k] - xm
                Pm += wf[k - 1] * (self.P[k] + np.outer(d, d))
            self.x[:] = xm
            self.P[:] = Pm
            if not keep_hazard and not self.multi:
                self.haz_scale = 0.05
        elif self.absorb_false and self.w[1:].sum() > 0.5:
            # no instrument fault: the drop the fault branches explained is weather -> fold the most likely
            # branch's multiplier into the night deviation (with extra uncertainty) instead of resetting
            k = 1 + int(np.argmax(self.w[1:]))
            xk, Pk = self.x[k].copy(), self.P[k].copy()
            xk[1] += self.lmu[k]
            Pk[1, 1] += 0.15 ** 2
            self.x[:] = xk
            self.P[:] = Pk
        else:
            self.x[:] = self.x[0]
            self.P[:] = self.P[0]
        self.w[:] = 0.0
        self.w[0] = 1.0


class Policy:
    def __init__(self, init, params=None):
        self.p = dict(DEFAULTS)
        cfg_path = Path(__file__).resolve().parent / 'policy_params.json'
        if cfg_path.exists():
            try:
                self.p.update(json.loads(cfg_path.read_text()))
            except Exception:
                pass
        env = os.environ.get('OBS2_PARAMS')
        if env:
            try:
                self.p.update(json.loads(env))
            except Exception:
                pass
        if params:
            self.p.update(params)
        self.cpu0 = time.process_time()
        self.kern = Kernel()
        site = init['site']
        self.lat = float(site['latitude_deg'])
        self.lon = float(site['longitude_deg'])
        self.min_alt = float(site.get('minimum_altitude_deg', 30.0))
        self.sin_lat, self.cos_lat = math.sin(self.lat * DEG), math.cos(self.lat * DEG)
        ins = init['instrument']
        self.nfib = int(ins['n_fibers'])
        self.side = int(ins.get('grid_side', math.isqrt(self.nfib)))
        glass = float(ins.get('glass_side_deg', math.sqrt(float(ins.get('fiber_area_deg2', 0.4)))))
        self.pitch = float(ins.get('pitch_deg', glass + float(ins.get('gap_deg', 0.0))))
        self.gap = max(0.0, self.pitch - glass)   # blind strip between cells (0 on the official grids)
        self.fov = self.side * self.pitch
        ex = ins.get('exposure', {})
        self.tmin = int(ex.get('min_duration_seconds', 60))
        self.tmax = int(ex.get('max_duration_seconds', 3600))
        sc = init['scoring']
        self.q0 = float(sc.get('q0', 0.68))
        self.f0t0 = float(sc.get('flux_zero_point', 0.5)) * float(sc.get('exposure_zero_point_seconds', 900))
        self.beta = float(sc.get('airmass_exponent', 0.6))
        lm = sc.get('lunar_model', {})
        self.lun_pm = float(lm.get('maximum_penalty', 0.75))
        self.lun_ge = float(lm.get('altitude_exponent', 1.0))
        self.lun_th = float(lm.get('angular_decay_scale_deg', 35.0))
        pr = sc.get('program', {})
        bands = pr.get('bands', {})
        self.band_dark = float(bands.get('DARK', 0.65))
        self.band_bright = float(bands.get('BRIGHT', 0.40))
        mult = pr.get('multipliers', {})
        self.mult = np.array([float(mult.get('DARK', 1.2)), float(mult.get('BRIGHT', 1.12)), float(mult.get('BACKUP', 1.06))])
        self.mismatch = float(pr.get('mismatch_multiplier', 1.0))
        rq = sc.get('required', {})
        self.req_pen = float(rq.get('penalty_per_missing', 50))
        self.req_thr = float(rq.get('observed_factor_threshold', 0.5))
        rep = sc.get('reporting', {})
        self.free_reports = int(rep.get('false_report_free_allowance', 2))
        self.max_consec = int(rep.get('max_consecutive_reports', 32))
        surv = init['survey']
        self.slot = int(surv.get('slot_seconds', 900))
        self.nights = [(parse_utc(n['observing_start_utc']), parse_utc(n['observing_end_utc'])) for n in surv['nights']]
        self.survey_end = parse_utc(surv['end_utc'])
        self.night_starts = np.array([a for a, _ in self.nights])
        self.night_ends = np.array([b for _, b in self.nights])
        lim = init.get('limits', {})
        self.budget_total = float(lim.get('global_wallclock_seconds', 900))
        tg = init['targets']
        col = {c: k for k, c in enumerate(tg['columns'])}
        rows = tg['rows']
        self.ids = [str(r[col['target_id']]) for r in rows]
        self.index = {t: i for i, t in enumerate(self.ids)}
        self.n = len(self.ids)
        self.ra = np.array([float(r[col['ra_deg']]) for r in rows])
        self.dec = np.array([float(r[col['dec_deg']]) for r in rows])
        self.flux = np.array([float(r[col['feature_flux']]) for r in rows])
        self.w = np.array([float(r[col['science_weight']]) for r in rows])
        self.req = np.array([str(r[col['required']]).lower() in ('true', '1') for r in rows])
        self.sdec, self.cdec = np.sin(self.dec * DEG), np.cos(self.dec * DEG)
        self.eqv = np.column_stack((self.cdec * np.cos(self.ra * DEG), self.cdec * np.sin(self.ra * DEG), self.sdec))
        self.transit_alt = 90.0 - np.abs(self.dec - self.lat)
        # state
        self.best = np.zeros(self.n)          # realised best score
        self.gl = np.zeros(self.n)            # lower bound on max raw factor
        self.ledger = []                      # list of (observe_index, idx, score, g_lower)
        self.pending = None
        self.req_done_ids = set()
        self.terrain_dirs = set()
        self.blocked = []                     # (time, alt, az, kind)
        self.last_closed_until = -1.0
        # weather / instrument belief
        self.eta_nom = 0.95
        self.mseason = np.array([self._season_mean(a) for a, _ in self.nights] + [0.0])
        self.bel = Belief(self.nights, self.slot, self.q0, self.f0t0, self.mult, self.mismatch, self.band_dark,
                          self.band_bright, self.mseason, eta_nom=self.eta_nom, infl=self.p['wx_infl'],
                          p_window=self.p['fault_window_mass'])
        self.bel.absorb_false = bool(self.p['false_absorb'])
        self.upd_at_false = -10 ** 9
        self.stress_seen = False
        if self.p['fault_counts']:
            self.bel.set_fault_prior(self.p['fault_counts'])
        self.logZ_mean = float(self.mseason[0])
        self.probe = 0                        # >0: short probe exposures after a closure
        self.zero_pending = []
        self.pf_prev = 0.0
        self.bul_t = 0.0
        self.quake_notice = False
        self.drop_t = None
        # reports
        self.false_since_correct = 0
        self.correct_reports = 0
        self.reports = 0
        self.consec_reports = 0
        self.paid_reports = 0
        self.last_report_t = -1e18
        self.quake_seen_t = -1e18
        # pointing offset calibration
        g = np.linspace(-0.16, 0.16, 33)
        self.off_alt, self.off_az = [a.ravel() for a in np.meshgrid(g, g, indexing='ij')]
        self.off_ll = np.zeros(len(self.off_alt))
        self.off_est = (0.0, 0.0)
        self.off_confident = False
        self.off_obs = 0
        self.misses_total = 0
        # timing
        self.avg_T = 900.0
        self.fill_ema = float(self.nfib) * 0.5
        self.anchor_cost = None
        self.pool_scale = 1.0
        self._cost_stats = [0.0, 0.0, 0.0, 0.0, 0]
        self._anchors_used = None
        self.cap_ratio = None
        self.decisions = 0
        self.observes = 0
        self.dec_cpu = 0.0
        self.turn_wall = 0.0      # real seconds spent inside decide()
        self._charge_ratio = 1.0  # platform charge / own cost estimate of recent turns
        self._last_el, self._last_pred = None, 0.0
        self._wall0 = None        # (wall remaining, dark time left, turn_wall) at the first planning decision
        self.mode_counts = {}
        grid = np.arange(0.0, 90.0 + 1e-9, 0.005)
        self._hf_tab = np.append(airmass(grid) ** (-self.beta), airmass(90.0) ** (-self.beta))
        self._precompute_best_geometry()
        self._precompute_hours()
        if self.p['req_moon'] > 0 or self.p['llm'] > 0:
            self._precompute_req_moon()
        # season strategist (language model): mission analysis now, plan review with every weekly forecast
        self.strategist = None
        self._safe = False
        self._forecast = None
        self._weekly_due = False
        if self.p['llm'] > 0:
            try:
                from llm_strategist import Strategist
                self.strategist = Strategist()
                brief = self._mission_brief(init)
                self.strategist.set_rule_default((brief.get('capacity') or {}).get('demand_over_supply'))
                self._apply_strategy()
                if self.strategist.enabled:
                    self.strategist.submit('mission', brief)
                _log({'event': 'llm_init', 'enabled': self.strategist.enabled, 'model': self.strategist.client.model,
                      'mock': self.strategist.mock, 'strategy': self.strategist.strategy})
            except Exception:
                import traceback
                traceback.print_exc(file=sys.stderr)
                self.strategist = None
        self.init_cpu = time.process_time() - self.cpu0

    # ------------------------------------------------------------------ geometry
    def _horizon(self, t, idx=None):
        """Horizon unit vectors (x north, y east, z up) and altitude (deg) at time t."""
        lst = lst_deg(t, self.lon)
        ra = self.ra if idx is None else self.ra[idx]
        sd = self.sdec if idx is None else self.sdec[idx]
        cd = self.cdec if idx is None else self.cdec[idx]
        ha = ((lst - ra + 180.0) % 360.0 - 180.0) * DEG
        z = self.sin_lat * sd + self.cos_lat * cd * np.cos(ha)
        y = -cd * np.sin(ha)
        x = (sd - z * self.sin_lat) / self.cos_lat
        alt = np.arcsin(np.clip(z, -1, 1)) / DEG
        return np.column_stack((x, y, z)), alt, ha / DEG

    def _hfac(self, alt):
        """airmass(alt) ** -beta by table interpolation (|rel err| < 1e-7)."""
        x = np.clip(alt, 0.0, 90.0) * 200.0
        i = x.astype(np.int64)
        f = x - i
        t = self._hf_tab
        return t[i] + f * (t[i + 1] - t[i])

    def _alt_after(self, ha_deg, dt, idx):
        ha = (ha_deg + SID * dt / 86400.0) * DEG
        z = self.sin_lat * self.sdec[idx] + self.cos_lat * self.cdec[idx] * np.cos(ha)
        return np.arcsin(np.clip(z, -1, 1)) / DEG

    def _precompute_best_geometry(self):
        """Per-night best airmass factor (no Moon), suffix max over remaining nights."""
        N = len(self.nights)
        self._suf_dtype = np.float16 if (N + 1) * self.n > 10_000_000 else np.float32
        best = np.zeros((N + 1, self.n), dtype=self._suf_dtype)
        for k, (a, b) in enumerate(self.nights):
            ha0 = (lst_deg(a, self.lon) - self.ra + 180.0) % 360.0 - 180.0
            span = SID * (b - a) / 86400.0
            to_transit = (-ha0) % 360.0
            alt0 = self._alt_from_ha(ha0)
            alt1 = self._alt_from_ha(ha0 + span)
            amax = np.where(to_transit <= span, self.transit_alt, np.maximum(alt0, alt1))
            h = np.where(amax >= self.min_alt + 0.5, airmass(amax) ** (-self.beta), 0.0)
            best[k] = h
        if self.p['season_rho'] > 0:
            # same with the seasonal mean sky quality of each night (relative to the season maximum)
            ms = self.mseason[:N]
            rel = np.exp(ms - ms.max())
            hz = np.zeros((N + 1, self.n), dtype=self._suf_dtype)
            for k in range(N):
                hz[k] = best[k] * rel[k]
            for k in range(N - 1, -1, -1):
                np.maximum(hz[k], hz[k + 1], out=hz[k])
            self.hbz_suffix = hz
            self.mseason_rel = rel
        for k in range(N - 1, -1, -1):
            np.maximum(best[k], best[k + 1], out=best[k])
        self.hbest_suffix = best

    def _good_hours(self, a, b, idx=None):
        """Hours in [a, b] that each target spends in the upper half of its altitude range."""
        sd = self.sdec if idx is None else self.sdec[idx]
        cd = self.cdec if idx is None else self.cdec[idx]
        ra = self.ra if idx is None else self.ra[idx]
        tr = self.transit_alt if idx is None else self.transit_alt[idx]
        alt_u = np.maximum(self.min_alt + 3.0, self.min_alt + 0.5 * (tr - self.min_alt))
        c = (np.sin(alt_u * DEG) - self.sin_lat * sd) / np.maximum(self.cos_lat * cd, 1e-9)
        hau = np.where(c <= -1.0, 180.0, np.where(c >= 1.0, 0.0, np.arccos(np.clip(c, -1.0, 1.0)) / DEG))
        hau = np.where(tr < self.min_alt + 0.5, 0.0, hau)
        ha0 = (lst_deg(a, self.lon) - ra + 180.0) % 360.0 - 180.0
        span = SID * max(0.0, b - a) / 86400.0
        ov = np.maximum(0.0, np.minimum(ha0 + span, hau) - np.maximum(ha0, -hau))
        ov += np.maximum(0.0, np.minimum(ha0 + span, 360.0 + hau) - np.maximum(ha0, 360.0 - hau))
        return ov * 24.0 / SID

    def _precompute_hours(self):
        N = len(self.nights)
        suf = np.zeros((N + 1, self.n), dtype=getattr(self, '_suf_dtype', np.float32))
        run = np.zeros(self.n)
        for k in range(N - 1, -1, -1):
            a, b = self.nights[k]
            run += self._good_hours(a, b)
            suf[k] = run
        self.hours_suffix = suf

    def _precompute_req_moon(self):
        """Required targets: log(Moon x airmass factor) at M samples of every night while the target is in the
        upper part of its altitude range (-30 otherwise), and the log sky quality each needs for completion
        in one max-length exposure."""
        ridx = np.flatnonzero(self.req)
        self.rq_pos = np.full(self.n, -1, dtype=np.int64)
        self.rq_pos[ridx] = np.arange(len(ridx))
        N = len(self.nights)
        M = max(2, int(self.p['req_moon_m']))
        lg = np.full((N, M, len(ridx)), -30.0, dtype=np.float32)
        ts = np.zeros((N, M))
        dth = np.zeros(N)
        if len(ridx):
            sd, cd, ra = self.sdec[ridx], self.cdec[ridx], self.ra[ridx]
            tr = self.transit_alt[ridx]
            alt_u = np.maximum(self.min_alt + 3.0, self.min_alt + 0.5 * (tr - self.min_alt))
            eq = self.eqv[ridx]
            for k, (a, b) in enumerate(self.nights):
                dth[k] = (b - a) / M / 3600.0
                for j in range(M):
                    t = a + (j + 0.5) * (b - a) / M
                    ts[k, j] = t
                    ha = (lst_deg(t, self.lon) - ra + 180.0) % 360.0 - 180.0
                    alt = np.arcsin(np.clip(self.sin_lat * sd + self.cos_lat * cd * np.cos(ha * DEG), -1.0, 1.0)) / DEG
                    ok = alt >= alt_u
                    if not np.any(ok):
                        continue
                    v = np.log(np.maximum(self._hfac(np.maximum(alt, 0.0)) * self._lunar(eq, t), 1e-9))
                    lg[k, j] = np.where(ok, v, -30.0)
        self.rq_lg, self.rq_ts, self.rq_dth = lg, ts, dth
        self.rq_need = np.log(self.req_thr * self.p['req_safety'] * self.q0 * self.f0t0
                              / np.maximum(self.flux[ridx] * self.tmax, 1e-12))
        self.rq_S, self.rq_S_night = None, -2

    def _req_dark_hours(self, now, night, pos):
        """Expected remaining hours in which a max-length exposure completes each required target (positions pos)."""
        N = len(self.nights)
        sig = self.p['req_moon_sig']
        c = self.logZ_mean - float(self.mseason[night]) + self.bel.leta
        if self.rq_S_night != night:
            S = np.zeros(self.rq_lg.shape[2])
            for k0 in range(night + 1, N, 32):
                k1 = min(N, k0 + 32)
                z = (self.rq_lg[k0:k1] + (self.mseason[k0:k1] + c)[:, None, None] - self.rq_need[None, None, :]) / sig
                S += np.einsum('kmi,k->i', 0.5 * (1.0 + _erf(z / math.sqrt(2.0))), self.rq_dth[k0:k1])
            self.rq_S, self.rq_S_night = S, night
        out = self.rq_S[pos].copy()
        later = self.rq_ts[night] >= now
        if np.any(later):
            lzc = self.logZ_mean + self.bel.leta_plan(now, night)
            z = (self.rq_lg[night][later][:, pos] + lzc - self.rq_need[pos][None, :]) / (0.5 * sig)
            out += self.rq_dth[night] * np.sum(0.5 * (1.0 + _erf(z / math.sqrt(2.0))), axis=0)
        return out

    def _alt_from_ha(self, ha_deg):
        z = self.sin_lat * self.sdec + self.cos_lat * self.cdec * np.cos(ha_deg * DEG)
        return np.arcsin(np.clip(z, -1, 1)) / DEG

    @staticmethod
    def _season_mean(t):
        """Generator seasonal mean of log(transparency * sky / seeing) for the night starting at t."""
        doy = time.gmtime(t - 12 * 3600).tm_yday
        ph = 2 * math.pi * (doy - 210) / 365.2425
        sn = math.sin(ph)
        return math.log((0.88 - 0.07 * sn) * (1.0 - 0.12 * sn) / (1.10 + 0.15 * sn))

    def _night_index(self, t):
        k = int(np.searchsorted(self.night_starts, t, side='right')) - 1
        if 0 <= k < len(self.nights) and t < self.night_ends[k]:
            return k
        return -1

    def _hbest_remaining(self, t, night, idx):
        """Best airmass factor over the rest of tonight and all later nights."""
        later = self.hbest_suffix[night + 1, idx].astype(float) if night + 1 <= len(self.nights) else np.zeros(len(idx))
        end = self.night_ends[night]
        ha0 = (lst_deg(t, self.lon) - self.ra[idx] + 180.0) % 360.0 - 180.0
        span = SID * max(0.0, end - t) / 86400.0
        to_transit = (-ha0) % 360.0
        z0 = self.sin_lat * self.sdec[idx] + self.cos_lat * self.cdec[idx] * np.cos(ha0 * DEG)
        z1 = self.sin_lat * self.sdec[idx] + self.cos_lat * self.cdec[idx] * np.cos((ha0 + span) * DEG)
        amax = np.where(to_transit <= span, self.transit_alt[idx],
                        np.arcsin(np.clip(np.maximum(z0, z1), -1, 1)) / DEG)
        tonight = np.where(amax >= self.min_alt + 0.5, airmass(amax) ** (-self.beta), 0.0)
        self._tonight_best = tonight
        return np.maximum(later, tonight)

    def _lunar(self, eqv_idx, t):
        mv, illum, malt = moon_state(t, self.lat, self.lon)
        if malt <= 0:
            return np.ones(len(eqv_idx))
        sep = np.arccos(np.clip(eqv_idx @ mv, -1, 1)) / DEG
        pen = self.lun_pm * illum * math.sin(malt * DEG) ** self.lun_ge * np.exp(-sep / self.lun_th)
        return np.clip(1.0 - pen, 0.0, 1.0)

    def _exact_H(self, start, dur, idx):
        """Exposure-average Moon*airmass factor on the engine's slot/120 s mesh."""
        if dur <= 0 or len(idx) == 0:
            return np.ones(len(idx))
        end = start + dur
        cursor = start
        acc = np.zeros(len(idx))
        lst0 = lst_deg(start, self.lon)
        ha0 = (lst0 - self.ra[idx] + 180.0) % 360.0 - 180.0
        eq = self.eqv[idx]
        while cursor < end - 1e-9:
            slot_end = (math.floor(cursor / self.slot + 1e-9) + 1) * self.slot
            seg_end = min(end, slot_end)
            piece = cursor
            while piece < seg_end - 1e-9:
                pe = min(seg_end, piece + 120.0)
                mid = 0.5 * (piece + pe)
                alt = self._alt_after(ha0, mid - start, idx)
                acc += (pe - piece) * self._lunar(eq, mid) * airmass(alt) ** (-self.beta)
                piece = pe
            cursor = seg_end
        return acc / dur

    # ------------------------------------------------------------------ belief
    @staticmethod
    def _sector_az_prob(wmin, wmax):
        """P(azimuth offset x from the announced 8-point direction lies in a sector), x in -180..179 deg."""
        x = np.arange(-180, 180, dtype=float)
        ws = np.linspace(wmin, wmax, 9)
        cs = np.linspace(-22.5, 22.5, 19)
        p = np.zeros_like(x)
        for w in ws:
            for c in cs:
                d = np.abs((x - c + 180.0) % 360.0 - 180.0)
                p += d <= w / 2.0
        return p / (len(ws) * len(cs))

    def _dir_prob(self, az, d, table):
        x = ((az - DIR_AZ[d] + 180.0) % 360.0 - 180.0)
        return table[np.clip(np.floor(x + 180.0).astype(int), 0, 359)]

    def _init_tables(self):
        if not hasattr(self, '_tab_terrain'):
            self._tab_terrain = self._sector_az_prob(30.0, 70.0)
            self._tab_rocket = self._sector_az_prob(40.0, 80.0)
            self._tab_weather = self._sector_az_prob(40.0, 120.0)
            self.tclear = np.full(360, 91.0)    # lowest altitude seen unobstructed per azimuth degree
            self.tblock = np.full(360, -1.0)    # highest altitude seen obstructed per azimuth degree

    def _terrain_pb(self, alt, az):
        """Probability that a static terrain sector obstructs (alt, az)."""
        self._init_tables()
        if not self.terrain_dirs:
            return np.zeros(len(alt))
        azb = np.floor(az).astype(int) % 360
        pt = np.zeros(len(alt))
        for d in self.terrain_dirs:
            if d in DIR_AZ:
                pt = np.maximum(pt, self._dir_prob(az, d, self._tab_terrain))
        ph = np.clip((50.0 - alt) / 15.0, 0.0, 1.0)
        pb = pt * ph
        pb = np.where(alt >= self.tclear[azb] - 0.5, 0.0, pb)
        pb = np.where(alt <= self.tblock[azb] + 0.5, 1.0, pb)
        return pb

    def _terrain_pb2d(self, alts, az):
        """_terrain_pb for an (samples x n) altitude array at fixed per-target azimuths."""
        self._init_tables()
        if not self.terrain_dirs:
            return np.zeros_like(alts)
        azb = np.floor(az).astype(int) % 360
        pt = np.zeros(len(az))
        for d in self.terrain_dirs:
            if d in DIR_AZ:
                pt = np.maximum(pt, self._dir_prob(az, d, self._tab_terrain))
        pb = pt[None, :] * np.clip((50.0 - alts) / 15.0, 0.0, 1.0)
        pb = np.where(alts >= self.tclear[azb][None, :] - 0.5, 0.0, pb)
        pb = np.where(alts <= self.tblock[azb][None, :] + 0.5, 1.0, pb)
        return pb

    def _directional_factor(self, alt, az, notices, t, terrain=True):
        f = np.ones(len(alt))
        self._init_tables()
        for nt in notices:
            kind, d = nt.get('event_kind'), nt.get('direction')
            if d not in DIR_AZ:
                continue
            if kind in ('rocket_launch', 'rocket'):
                pa = self._dir_prob(az, d, self._tab_rocket)
                ph = np.clip((60.0 - alt) / 30.0, 0.0, 1.0)
                f *= 1.0 - pa * ph
            elif kind in ('overcast', 'haze', 'cloudy', 'smoggy'):
                pa = self._dir_prob(az, d, self._tab_weather)
                ph = np.clip((80.0 - alt) / 40.0, 0.0, 1.0)
                f *= 1.0 - 0.55 * pa * ph
            elif kind in ('rain', 'storm', 'rainy', 'tornado'):
                pa = self._dir_prob(az, d, self._tab_weather)
                ph = np.clip((80.0 - alt) / 40.0, 0.0, 1.0)
                f *= 1.0 - pa * ph
        if terrain and self.terrain_dirs:
            f *= 1.0 - self._terrain_pb(alt, az)
        keep = []
        for (bt, balt, baz, kind) in self.blocked:
            if kind != 'terrain' and t - bt < 2400:
                keep.append((bt, balt, baz, kind))
                da = np.abs((az - baz + 180.0) % 360.0 - 180.0)
                f *= np.where((da <= 15.0) & (np.abs(alt - balt) <= 15.0), 0.3, 1.0)
        self.blocked = keep[-200:]
        return f

    def _learn_terrain(self, alt, az, scored):
        """Update the static terrain map from one hit: scored>0 -> clear at (az, >=alt); 0 -> blocked at (az, <=alt)."""
        if not hasattr(self, 'tclear'):
            return
        b = int(math.floor(az)) % 360
        if scored:
            for k in range(-1, 2):
                j = (b + k) % 360
                self.tclear[j] = min(self.tclear[j], alt)
        else:
            if alt < 55.0:
                self.tblock[b] = max(self.tblock[b], alt)

    # ------------------------------------------------------------------ messages/results
    def _apply_resync(self, msg):
        try:
            self._stress_signal(parse_utc(msg.get('issued_at_utc')), 'data_loss')
        except Exception:
            pass
        win = msg.get('invalidated_window', {}) or {}
        a = int(win.get('action_index_start', 0))
        b = int(win.get('action_index_end_exclusive', 0))
        self.ledger = [e for e in self.ledger if not (a <= e[0] < b)]
        self.best[:] = 0.0
        self.gl[:] = 0.0
        for _, idx, sc, gl in self.ledger:
            np.maximum.at(self.best, idx, sc)
            np.maximum.at(self.gl, idx, gl)
        canon = np.zeros(self.n)
        for item in msg.get('best_scores', []) or []:
            if isinstance(item, dict) and item.get('target_id') in self.index:
                canon[self.index[item['target_id']]] = float(item.get('best_score', 0.0))
        self.best = canon
        _log({'event': 'resync', 'window': [a, b], 'ledger': len(self.ledger)})

    def _ingest(self, snap, now):
        res = snap.get('last_result') or {}
        pend, self.pending = self.pending, None
        kind = res.get('action')
        if kind == 'report':
            self.consec_reports += 1
            if res.get('correct'):
                self.correct_reports += 1
                self.false_since_correct = 0
                self.bel.fault_found(self.drop_t if self.drop_t else now, now)
                self.bel.report_result(True)
                self.drop_t = None
                if self.bel.multi:
                    _log({'event': 'faults', 'pc': [round(float(x), 3) for x in self.bel.pc], 'jnext': [int(x) for x in self.bel.jnext]})
            else:
                self.false_since_correct += 1
                self.upd_at_false = self.bel.n_upd
                if self.quake_notice and self.bel.p_fault() > 0.5:
                    # a sudden efficiency drop under a persisting earthquake notice: a new shock
                    nq = self._night_index(now)
                    self.bel.absorb_as_quake(self.drop_t if self.drop_t else now, nq if nq >= 0 else 0)
                    _log({'event': 'quake_merged', 't': fmt_utc(now)})
                else:
                    self.bel.report_result(False)
            self.pf_prev = 0.0
            _log({'event': 'report_result', 'correct': res.get('correct'), 't': fmt_utc(now)})
            return
        if kind in ('wait', 'observe'):
            self.consec_reports = 0
        if kind != 'observe' or not pend or pend.get('kind') != 'observe':
            return
        start = pend['t']
        T = max(1.0, min(pend['T'], now - start))
        assigned = pend['idx']
        hits = [(self.index[h['target_id']], float(h.get('score', 0.0))) for h in res.get('hits', []) if h.get('target_id') in self.index]
        hit_set = {i for i, _ in hits}
        # pointing calibration evidence
        if len(assigned):
            hitv = np.array([1 if i in hit_set else 0 for i in assigned], dtype=np.int32)
            self._calibrate(pend, hitv)
        if not hits:
            return
        idx = np.array([i for i, _ in hits], dtype=int)
        sc = np.array([s for _, s in hits])
        P = pend['P']
        M = self.mult[P]
        y = sc / self.w[idx]
        glow = np.minimum(1.0, y / max(M, self.mismatch))
        np.maximum.at(self.best, idx, sc)
        np.maximum.at(self.gl, idx, glow)
        obs_index = int(res.get('observe_index', self.observes))
        self.ledger.append((obs_index, idx, sc, glow))
        self.observes += 1
        # closures / blocked directions
        zero = sc <= 1e-12
        alt_s, az_s = pend['alt'], pend['az']
        alt_e = pend.get('alt_end', alt_s)
        amap = {i: (max(alt_s[k], alt_e[k]), az_s[k]) for k, i in enumerate(assigned)}
        if np.all(zero):
            if len(idx) >= 1:
                high = all(amap.get(int(i), (90, 0))[0] >= 55.0 for i in idx)
                if self.probe > 0 and high:
                    # a high-altitude probe also failed: the site is closed
                    self.last_closed_until = (math.floor(now / self.slot) + 1) * self.slot
                    self.zero_pending = []
                    self.probe = 2
                else:
                    self.zero_pending = [amap[int(i)] for i in idx if int(i) in amap]
                    self.probe = 2
            return
        if self.zero_pending:
            # the site is open: the previous all-zero field was obstructed terrain
            for (a0, z0) in self.zero_pending:
                if a0 < 52.0:
                    self._learn_terrain(a0, z0, False)
            self.zero_pending = []
        if self.probe > 0:
            self.probe = 0
        for i, zflag in zip(idx, zero):
            a, z = amap.get(int(i), (None, None))
            if a is None:
                continue
            self._learn_terrain(a, z, not zflag)
            if zflag and a >= 55.0:
                self.blocked.append((now, a, z, 'temp'))
        # weather / efficiency belief update from the unobstructed hits
        use = (~zero) & (y > 1e-6)
        if pend.get('dirf') is not None:
            use &= pend['dirf_hit'](idx) > 0.99
        if np.count_nonzero(use) < self.p['min_hits']:
            return
        sel = np.flatnonzero(use)
        H = self._exact_H(start, T, idx[sel])
        if len(sel) > 24:
            kk0 = self.flux[idx[sel]] * H
            o = np.argsort(kk0)[:24]          # dimmest hits carry the most information
            sel, H = sel[o], H[o]
        night = self._night_index(start)
        if night < 0:
            return
        mid = start + T / 2.0
        act = self._event_activity(pend, snap, start, T)
        omegas, wprior = self._omega_options(start, T)
        freeze = self.bel.learning_quake(night)
        pf0 = self.bel.p_fault()
        info = self.bel.observe(mid, night, start, self.flux[idx[sel]], H, y[sel], T, P, omegas, wprior, act, freeze=freeze)
        if pf0 < 0.2 <= self.bel.p_fault():
            self.drop_t = start
        self.logZ_mean = self.bel.clim(night)
        if os.environ.get('OBS2_DEBUG_Z'):
            _log({'m': fmt_utc(start), 'T': T, 'n': int(len(sel)), 'act': [round(a, 2) for a in act], 'fz': freeze, **info})

    def _event_activity(self, pend, snap, start, T):
        """Fraction of the exposure covered by announced all-sky weather events, per event kind."""
        end = start + T
        tl = [(pend.get('bul_t', start), pend.get('notices', []))]
        for m in snap.get('new_messages', []) or []:
            if m.get('record_type') == 'bulletin' and not m.get('initial'):
                try:
                    tl.append((parse_utc(m['issued_at_utc']), m.get('notices', []) or []))
                except Exception:
                    continue
        tl.sort(key=lambda z: z[0])
        act = [0.0, 0.0, 0.0]
        for k, (tb, notes) in enumerate(tl):
            a = max(start, tb)
            b = min(end, tl[k + 1][0]) if k + 1 < len(tl) else end
            if b <= a:
                continue
            for n in notes:
                key = EV_ALIAS.get(n.get('event_kind'))
                if key is not None and n.get('direction') in (None, 'ALL'):
                    act[EV_KEYS.index(key)] += (b - a) / T
        return [min(1.0, v) for v in act]

    def _omega_options(self, start, T):
        """Open fractions for a closure covering a head or tail run of whole weather slots."""
        end = start + T
        bounds = []
        b = (math.floor(start / self.slot) + 1) * self.slot
        while b < end - 1e-6:
            bounds.append(b)
            b += self.slot
        om = [1.0]
        for b in bounds:
            om.append((b - start) / T)      # closed from b to the end
            om.append((end - b) / T)        # closed from the start to b
        if self.p['omega_mid'] > 0:
            # closed for whole slots inside the exposure, open at both ends
            for i in range(len(bounds)):
                for j in range(i + 1, len(bounds)):
                    om.append(1.0 - (bounds[j] - bounds[i]) / T)
        om = np.array(om)
        pr = np.full(len(om), 0.08 / max(1, len(om) - 1))
        pr[0] = 0.92
        keep = om > 0.02
        return om[keep], pr[keep]

    def _stress_signal(self, t, why):
        if self.stress_seen:
            return
        self.stress_seen = True
        if self.p['fault_counts_stress'] and self.bel.nfault == 0:
            self.bel.set_fault_prior(self.p['fault_counts_stress'], from_t=t)
            _log({'event': 'stress', 'why': why, 't': fmt_utc(t)})

    def _calibrate(self, pend, hitv):
        if self.off_confident and np.all(hitv == 1):
            return
        tv = pend['tv']
        fib = pend['fib']
        agree = self.kern.offset_agree(self.off_alt, self.off_az, pend['cmd_alt'], pend['cmd_az'], tv, fib, hitv,
                                       self.side, self.pitch)
        n = len(hitv)
        self.off_ll += -2.5 * (n - agree)
        self.off_obs += 1
        self.misses_total += int(n - hitv.sum())
        if self.misses_total > 0:
            self._stress_signal(pend['t'], 'pointing')
        if self.misses_total == 0:
            return
        best = int(np.argmax(self.off_ll))
        top = self.off_ll[best]
        # confidence: all offsets within 3 log-units lie in a compact region
        near = self.off_ll >= top - 3.0
        spread = max(np.ptp(self.off_alt[near]), np.ptp(self.off_az[near]))
        w = np.exp(self.off_ll[near] - top)
        est = (float(np.sum(self.off_alt[near] * w) / w.sum()), float(np.sum(self.off_az[near] * w) / w.sum()))
        self.off_est = est
        self.off_confident = spread <= 0.05 or self.off_obs >= 12
        if self.off_obs % 10 == 1:
            _log({'event': 'calib', 'est': [round(est[0], 4), round(est[1], 4)], 'spread': round(spread, 3), 'obs': self.off_obs})

    # ------------------------------------------------------------------ decision
    def decide(self, snap):
        t0 = time.process_time()
        w0 = time.perf_counter()
        self._anchors_used = None
        try:
            act = self._decide(snap)
            self._fails = 0
        except Exception as exc:  # never crash the run
            import traceback
            traceback.print_exc(file=sys.stderr)
            self.pending = None
            act = self._safe_wait(snap)
            self._fails = getattr(self, '_fails', 0) + 1
            if self._fails == 3:
                # persistent failure: switch the optional planning features off
                for k, v in (('req_moon', 0), ('req_urg', 0.0), ('opt_value', 0.0), ('season_rho', 0.0)):
                    self.p[k] = v
                self._safe = True
                _log({'event': 'safe_mode'})
        self.decisions += 1
        wdt = time.perf_counter() - w0
        self.turn_wall += wdt
        dt = min(time.process_time() - t0, wdt)
        # the budget is in charged seconds (this machine's seconds / speed factor): cost the decision the same way,
        # scaled by what the platform actually charged for recent turns (transport overhead, and how it counts
        # the CPU of several threads): elapsed_seconds grows by exactly the previous turn's charge
        dtc = dt / self._speed_factor(snap)
        try:
            el = float(((snap or {}).get('wallclock') or {}).get('elapsed_seconds'))
        except (TypeError, ValueError, AttributeError):
            el = None
        if el is not None and self._last_el is not None and self._last_pred > 0.005:
            r = (el - self._last_el) / self._last_pred
            if 0.0 <= r < 10.0:
                self._charge_ratio = min(3.0, max(0.5, 0.95 * self._charge_ratio + 0.05 * r))
        self._last_el, self._last_pred = el, dtc
        dtc *= self._charge_ratio
        self.dec_cpu += dt
        self._cost_ema = dtc if not hasattr(self, '_cost_ema') else 0.9 * self._cost_ema + 0.1 * dtc
        if self.decisions % 500 == 0:
            _log({'prog': snap.get('now_utc'), 'cpu': round(self.dec_cpu, 1), 'cap': None if self.cap_ratio is None else round(self.cap_ratio, 3),
                  'rich': round(getattr(self, '_rich_cache', -1.0), 3), 'pool_scale': round(self.pool_scale, 3), 'nfault': self.bel.nfault, 'pc': [round(float(x), 3) for x in self.bel.pc], 'stress': self.stress_seen,
                  'anchors': self._anchors_used, 'fill': round(self.fill_ema, 2)})
        if self._anchors_used and act.get('action') == 'observe':
            # running regression of decision cost on anchors used: cost = fixed + per_a * anchors
            a = float(self._anchors_used)
            st = self._cost_stats
            st[0] = 0.97 * st[0] + 0.03 * a
            st[1] = 0.97 * st[1] + 0.03 * dtc
            st[2] = 0.97 * st[2] + 0.03 * a * a
            st[3] = 0.97 * st[3] + 0.03 * a * dtc
            st[4] += 1
            if st[4] >= 30:
                var = st[2] - st[0] ** 2
                per_a = (st[3] - st[0] * st[1]) / var if var > 1.0 else st[1] / max(st[0], 1.0) * 0.8
                per_a = max(per_a, 0.3 * st[1] / max(st[0], 1.0))
                fixed = max(0.0, st[1] - per_a * st[0])
                self.anchor_cost = (fixed, per_a)
                # the fixed part grows with the candidate pool: keep it well inside the per-decision budget
                pd_ = getattr(self, '_per_dec', None)
                if pd_:
                    afford = (0.85 * pd_ - fixed) / max(per_a, 1e-6)
                    if afford < 12:
                        # the fixed (pool) part leaves too little for the field search: shrink the pool
                        # (a true budget emergency is handled by the hard caps on per-decision time)
                        floor = self.p['pool_floor']
                        if (afford < 6 and self.pool_scale <= floor * 1.0001 and getattr(self, '_rem_frac', 1.0) < 0.15
                                and getattr(self, '_obs_left_frac', 0.0) > 0.25):
                            # a very slow machine: the budget is nearly gone with much of the season left, so
                            # keep shrinking the pool rather than run out
                            floor = self.p['pool_floor_min']
                        self.pool_scale = max(floor, self.pool_scale * 0.93)
                    elif afford > 2.0 * (self.p['pool_grow_anchors'] or self.p['anchors']) and fixed < 0.3 * pd_:
                        self.pool_scale = min(1.0, self.pool_scale * 1.02)
        if act.get('action') != 'report':
            self.consec_reports = 0
        return act

    def _safe_wait(self, snap):
        try:
            now = parse_utc(snap['now_utc'])
            k = self._night_index(now)
            if k < 0:
                nxt = [a for a in self.night_starts if a > now]
                if not nxt:
                    return {'action': 'finish'}
                return {'action': 'wait', 'until_utc': fmt_utc(min(nxt))}
            return {'action': 'wait', 'duration_seconds': int(max(self.tmin, min(900, self.tmax)))}
        except Exception:
            return {'action': 'wait', 'duration_seconds': 900}

    def _messages(self, snap):
        for m in snap.get('new_messages', []) or []:
            rt = m.get('record_type')
            if rt == 'forecast':
                self._forecast = m
                self._weekly_due = True
            elif rt == 'state_resync':
                self._apply_resync(m)
            elif rt == 'bulletin' and m.get('initial'):
                for n in m.get('notices', []) or []:
                    if n.get('event_kind') == 'terrain_obstruction' and n.get('direction'):
                        self.terrain_dirs.add(n['direction'])
            elif rt == 'bulletin':
                for n in m.get('notices', []) or []:
                    if n.get('event_kind') == 'earthquake':
                        t_q = parse_utc(m.get('issued_at_utc', '1970-01-01T00:00:00Z'))
                        if t_q - self.quake_seen_t > 20 * 3600:
                            nq = self._night_index(t_q)
                            if nq >= 0:
                                self.bel.add_quake(t_q, nq)
                                _log({'event': 'quake', 't': fmt_utc(t_q)})
                        self.quake_seen_t = max(self.quake_seen_t, t_q)

    def _decide(self, snap):
        now = parse_utc(snap['now_utc'])
        self._messages(snap)
        self._ingest(snap, now)
        if self._weekly_due:
            self._weekly_due = False
            self._submit_weekly(snap, now)
        if now >= self.survey_end - 1:
            return {'action': 'finish'}
        night = self._night_index(now)
        if night < 0:
            nxt = self.night_starts[self.night_starts > now]
            if not len(nxt):
                return {'action': 'finish'}
            return {'action': 'wait', 'until_utc': fmt_utc(float(nxt[0]))}
        left = self.night_ends[night] - now
        if left < self.tmin:
            nxt = self.night_starts[self.night_starts > now]
            target = float(nxt[0]) if len(nxt) else self.survey_end
            return {'action': 'wait', 'until_utc': fmt_utc(target)}
        lb = snap.get('latest_bulletin') or {}
        notices = lb.get('notices', []) or []
        self.quake_notice = any(n.get('event_kind') == 'earthquake' for n in notices)
        try:
            self.bul_t = parse_utc(lb['issued_at_utc']) if lb.get('issued_at_utc') else now
        except Exception:
            self.bul_t = now
        if any(n.get('event_kind') in CLOSE_KINDS and n.get('direction') in (None, 'ALL') for n in notices) or now < self.last_closed_until:
            nxt = (math.floor(now / self.slot) + 1) * self.slot
            if nxt - now < self.tmin:
                nxt += self.slot
            nxt = min(nxt, self.night_ends[night])
            if nxt - now < self.tmin:
                return {'action': 'wait', 'duration_seconds': int(self.tmin)}
            return {'action': 'wait', 'until_utc': fmt_utc(nxt)}
        # fault report
        if self._should_report(now, night):
            self.reports += 1
            if self.false_since_correct >= self.free_reports:
                self.paid_reports += 1
            self.last_report_t = now
            self.pending = {'kind': 'report'}
            _log({'event': 'report', 't': fmt_utc(now), 'pf': round(self.bel.p_fault(), 3), 'kmap': self.bel.kmap()})
            return {'action': 'report'}
        try:
            act = self._plan(snap, now, night, left, notices)
        except Exception:
            if int(self.p['threads']) <= 1:
                raise
            # a failure on the threaded path: plan again and stay single-threaded from now on
            import traceback
            traceback.print_exc(file=sys.stderr)
            self.p['threads'] = 1
            _log({'event': 'threads_off'})
            act = self._plan(snap, now, night, left, notices)
        if act is None:
            return {'action': 'wait', 'duration_seconds': int(min(max(self.tmin, 600), max(self.tmin, left)))}
        return act

    def _should_report(self, now, night):
        if self.consec_reports >= min(3, self.max_consec - 1):
            return False
        if self.bel.learning_quake(night):
            return False
        pf = self.bel.p_fault()
        if self.correct_reports >= (len(self.bel.pc) if self.bel.multi else self.p['max_faults']):
            if pf > 0.9 and self.quake_notice:
                self.bel.absorb_as_quake(self.drop_t if self.drop_t else now, night)
                _log({'event': 'quake_merged', 't': fmt_utc(now)})
            elif pf > 0.9:
                self.bel.report_result(False)
            return False
        hist = self.bel.pf_hist
        if self.p['report_gap'] > 0 and self.bel.n_upd - self.upd_at_false < self.p['report_gap']:
            return False
        free = self.false_since_correct < self.free_reports
        thr = self.p['rep_free'] if free else self.p['rep_paid']
        if pf < thr:
            return False
        k = int(self.p['rep_streak'] if free else self.p['rep_streak_paid'])
        # each false report since the last correct one asks for a longer run of evidence: a real fault
        # persists for the rest of the season, a directional cloud or a weather dip does not
        k += int(round(self.p['rep_esc'] * self.false_since_correct))
        if len(hist) < max(2, k) or any(h < 0.5 * thr for h in hist[-max(2, k):-1]):
            return False
        if not free:
            if self.paid_reports >= self.p['max_paid']:
                # the paid budget is spent: only a long run of near-certain evidence (a real fault persists
                # for the rest of the season) still gets reported
                ko = int(self.p['rep_override'])
                if (ko <= 0 or self.paid_reports >= self.p['max_paid'] + 2 or len(hist) < ko
                        or min(hist[-ko:]) < 0.9):
                    return False
            left = float(np.sum(np.maximum(0.0, self.night_ends - np.maximum(self.night_starts, now))))
            total = float(np.sum(self.night_ends - self.night_starts))
            if left < 0.04 * total:
                return False
        return True

    def _budget_scale(self, snap, now, night):
        wc = snap.get('wallclock') or {}
        remaining = float(wc.get('remaining_seconds', self.budget_total))
        obs_left = float(np.sum(np.maximum(0.0, self.night_ends - np.maximum(self.night_starts, now))))
        if wc.get('wall_remaining_seconds') is not None:
            remaining = min(remaining, self._wall_budget(wc, obs_left))
        dec_left = obs_left / max(self.p['dec_T_floor'], self.avg_T) * 1.15 + 5
        per = self.p['budget_safety'] * remaining / dec_left
        if self.p['budget_front'] > 0:
            # early decisions face the largest candidate pools; later ones are cheaper. The allowance is
            # recomputed from the remaining budget at every decision, so early spending is self-correcting.
            obs_total = float(np.sum(self.night_ends - self.night_starts))
            frac_o = obs_left / max(obs_total, 1.0)
            if self.p['front_gate'] > 0:
                # a slower machine spends faster than planned: then drop the boost (scaled by the overspend)
                pace = (remaining / max(self.budget_total, 1.0)) / max(frac_o, 1e-3)
                per *= 1.0 + self.p['budget_front'] * frac_o * float(np.clip(2.0 * pace - 1.0, 0.0, 1.0))
            else:
                per *= 1.0 + self.p['budget_front'] * frac_o
        obs_total = float(np.sum(self.night_ends - self.night_starts))
        self._rem_frac = remaining / max(self.budget_total, 1.0)
        self._obs_left_frac = obs_left / max(obs_total, 1.0)
        return per, remaining

    @staticmethod
    def _speed_factor(snap):
        """The platform's speed factor (this machine's CPU seconds per charged second); 1 when not given."""
        try:
            f = float(((snap or {}).get('wallclock') or {}).get('speed_factor') or 1.0)
        except (TypeError, ValueError, AttributeError):
            return 1.0
        return f if 0.1 <= f <= 10.0 else 1.0

    def _wall_budget(self, wc, obs_left):
        """Charged seconds that still fit into the hard real-time cap: our future turns take charged x speed
        factor real seconds, and the engine's time between turns (measured so far, extrapolated over the dark
        time left) comes on top."""
        try:
            wr = float(wc['wall_remaining_seconds'])
            f = max(0.1, float(wc.get('speed_factor') or 1.0))
        except (TypeError, ValueError):
            return float('inf')
        if self._wall0 is None:
            self._wall0 = (wr, obs_left, self.turn_wall)
            return float('inf')
        wr0, ol0, tw0 = self._wall0
        engine = max(0.0, (wr0 - wr) - (self.turn_wall - tw0))   # engine, transport and calibration time
        done = ol0 - obs_left
        if done < 0.05 * ol0:
            # too little of the season seen to extrapolate the engine's time (a speed sample alone would
            # dominate it); the cap cannot bind this early anyway
            return float('inf')
        eng_left = 1.1 * engine * obs_left / done
        lim = max(0.0, (wr - eng_left - 0.05 * wr0) / f)
        if lim < float(wc.get('remaining_seconds', lim)) and not getattr(self, '_wall_logged', False):
            self._wall_logged = True
            _log({'event': 'wall_bound', 'wall_remaining': round(wr, 1), 'engine': round(engine, 1),
                  'eng_left': round(eng_left, 1), 'limit': round(lim, 1)})
        return lim

    def _richness(self, now, night):
        """0 (capacity-limited) .. 1 (time-rich): remaining demand of fibre time (incomplete targets,
        at the recent fill) against the remaining dark time; cached for 25 decisions."""
        if self.decisions % 25 != 0 and hasattr(self, '_rich_cache'):
            return self._rich_cache
        inc = self.best < self.w * self.mult[0] * 0.98
        q = math.exp(self.bel.clim(night) + self.bel.leta_plan(now, night)) / self.q0 * 0.85
        tneed = np.minimum(self.tmax, self.f0t0 / np.maximum(self.flux[inc] * q, 1e-9))
        demand = float(tneed.sum()) / max(1.0, self.fill_ema)
        supply = 0.85 * float(np.sum(np.maximum(0.0, self.night_ends - np.maximum(self.night_starts, now))))
        cap = demand / max(1.0, supply)
        self.cap_ratio = cap
        # only clearly time-rich surveys (demand well below supply, e.g. the D card at cap ~0.1-0.25) count as
        # rich: capacity-limited cards sit near cap ~1 and their estimate fluctuates with the recent fill
        self._rich_cache = float(np.clip((self.p['rich_cap_hi'] - cap) / (self.p['rich_cap_hi'] - self.p['rich_cap_lo']), 0.0, 1.0))
        return self._rich_cache

    def _capacity_t0(self, now, night):
        """Virtual per-exposure overhead for time-rich surveys: when the remaining demand of fibre time
        is far below the remaining dark time, prefer exposures long enough to complete the faint targets
        instead of the best instantaneous rate."""
        if self.p['t0_max'] <= 0:
            return 0.0
        self._t0_cache = self.p['t0_max'] * self._richness(now, night)
        return self._t0_cache

    def _hbz_remaining(self, t, night, idx, tonight):
        """Best (airmass factor x relative seasonal sky quality) over the rest of tonight and later nights."""
        later = self.hbz_suffix[night + 1, idx].astype(float) if night + 1 <= len(self.nights) else np.zeros(len(idx))
        return np.maximum(later, tonight * self.mseason_rel[night])

    def _plan(self, snap, now, night, left, notices):
        self._apply_strategy()
        per_dec, remaining = self._budget_scale(snap, now, night)
        # budget emergency (e.g. a much slower machine): minimal search and long exposures, so that the
        # remaining decisions fit into what is left of the global wall clock
        emergency = remaining < max(20.0, 0.03 * self.budget_total)
        if emergency:
            per_dec = min(per_dec, 0.002)
            if not getattr(self, '_emerg_logged', False):
                self._emerg_logged = True
                _log({'event': 'budget_emergency', 't': fmt_utc(now), 'remaining': round(remaining, 1)})
        self._per_dec = per_dec
        tvall, altall, haall = self._horizon(now)
        lc, vc = self.bel.peek(now, night, self._event_activity({'t': now, 'notices': notices}, {}, now, 1.0))
        Cp = math.exp(lc)
        Zp = Cp * math.exp(self.bel.leta_plan(now, night))
        sig = math.sqrt(vc + 0.03 ** 2)
        # candidate pool
        vis = altall >= self.min_alt + 0.3
        maxval = self.w * self.mult[0]
        incomplete_req = self.req & (self.gl < self.req_thr)
        reqbonus_active = np.zeros(self.n)
        req_deadline = np.full(self.n, np.inf)
        req_thr = np.zeros(self.n)
        for r in snap.get('active_requests', []) or []:
            try:
                remaining_n = int(r.get('remaining_count', 0))
                if remaining_n <= 0:
                    continue
                dl = parse_utc(r['deadline_utc'])
                if dl - now < self.tmin:
                    continue
                done = set(r.get('completed_target_ids', []) or [])
                cand = [self.index[t] for t in r.get('target_ids', []) if t in self.index and t not in done]
                if not cand:
                    continue
                cand = np.array(cand, dtype=int)
                feas = self._request_feasible(cand, now, dl, remaining_n, float(r.get('completion_factor_threshold', 0.5)), night)
                if feas < remaining_n:
                    continue
                bonus = float(r.get('completion_reward', 0.0)) / remaining_n * self.p['request_scale']
                if self.p['rq_rich'] > 0:
                    bonus *= 1.0 + self.p['rq_rich'] * self._richness(now, night)
                reqbonus_active[cand] += bonus
                req_deadline[cand] = np.minimum(req_deadline[cand], dl)
                req_thr[cand] = np.maximum(req_thr[cand], float(r.get('completion_factor_threshold', 0.5)))
            except Exception:
                continue
        potential = (self.best < maxval * 0.999) | incomplete_req | (reqbonus_active > 0)
        pool = np.flatnonzero(vis & potential)
        if self.probe > 0:
            hp = pool[altall[pool] >= 56.0]
            if len(hp):
                pool = hp
        if len(pool) == 0:
            return None
        # how long can each pool target stay above the limit (from now)
        alt_now = altall[pool]
        ha_now = haall[pool]
        tg = TGRID[TGRID <= left + 1e-6]
        if len(tg) == 0 or tg[-1] < min(left, self.tmax) - 30:
            tg = np.append(tg, float(int(min(left, self.tmax))))
        tg = np.unique(np.clip(tg, self.tmin, min(self.tmax, int(left))))
        if emergency and len(tg) > 1:
            # spread the decisions the remaining budget affords over the remaining dark time
            obs_left = float(np.sum(np.maximum(0.0, self.night_ends - np.maximum(self.night_starts, now))))
            n_aff = 0.8 * remaining / max(getattr(self, '_cost_ema', 0.02), 1e-3)
            t_floor = min(float(tg[-1]), max(600.0, obs_left / max(n_aff, 1.0)))
            tg = tg[tg >= t_floor]
        if self.probe > 0:
            tg = tg[tg <= 180] if np.any(tg <= 180) else tg[:1]
            self.probe -= 1
        nt = len(tg)
        # coarse priority to cap the pool size
        hnow_air = self._hfac(alt_now)
        kk = self.flux[pool] * Zp * hnow_air / (self.q0 * self.f0t0)
        quick = self.w[pool] * self.mult[0] * np.minimum(1.0, kk * 1800) - self.best[pool]
        quick = np.maximum(quick, 0) + incomplete_req[pool] * self.req_pen * np.minimum(1.0, kk * 3600 / self.req_thr) ** 4 + reqbonus_active[pool]
        pool_cap = int(self.p['pool_max'] * self.pool_scale)
        if emergency:
            pool_cap = min(pool_cap, 300)
        elif per_dec < 0.004:
            pool_cap = min(pool_cap, 600)
        elif per_dec < 0.010:
            pool_cap = min(pool_cap, 1500)
        pool_cap = max(pool_cap, 400)
        if len(pool) > pool_cap:
            keep = np.argsort(-quick)[:pool_cap]
            pool, alt_now, ha_now, hnow_air, quick = pool[keep], alt_now[keep], ha_now[keep], hnow_air[keep], quick[keep]
        keep = quick > 1e-9
        pool, alt_now, ha_now, hnow_air = pool[keep], alt_now[keep], ha_now[keep], hnow_air[keep]
        if len(pool) == 0:
            return None
        n = len(pool)
        # time samples: 0 and each duration in tg
        samples = np.concatenate(([0.0], tg))
        dts = np.diff(samples)
        ns = len(samples)
        # per-pool quantities with side effects or pool-wide statistics stay in this thread
        self._init_tables()
        az_now = (np.arctan2(tvall[pool, 1], tvall[pool, 0]) / DEG) % 360.0
        dirf = self._directional_factor(alt_now, az_now, notices, now, terrain=False)
        terrain = bool(self.terrain_dirs)
        # season-aware quantities
        hb = self._hbest_remaining(now, night, pool)
        zref = math.exp(self.logZ_mean) * self.p['zref_scale']
        rich = 0.0
        if self.p['zref_rich'] > 1.0 or self.p['season_rho'] > 0 or self.p['gamma_rich'] > 0 or self.p['alpha_rich'] >= 0 or self.p['opt_value'] > 0:
            rich = self._richness(now, night)
            if self.p['zref_rich'] > 1.0 and rich > 0:
                # time-rich: partial completions are judged against good (not average) conditions,
                # including the best remaining season
                lz_best = float(np.max(self.mseason[night:len(self.nights)]))
                zref *= math.exp(rich * max(0.0, lz_best - float(self.mseason[night])))
                zref *= 1.0 + (self.p['zref_rich'] - 1.0) * rich
        gam = self.p['gamma']
        if self.p['gamma_rich'] > 0:
            gam = gam + (self.p['gamma_rich'] - gam) * rich
        alpha = self.p['alpha']
        if self.p['alpha_rich'] >= 0:
            alpha = alpha + (self.p['alpha_rich'] - alpha) * rich
        ws = self.p['season_rho'] * rich
        hbz = None
        if ws > 0 and alpha > 0:
            # time-rich: also wait for the better part of the season (seasonal mean sky quality)
            hbz = self._hbz_remaining(now, night, pool, self._tonight_best)
        S = None
        jr = np.flatnonzero(incomplete_req[pool])
        S_dk = None
        if self.p['urgency'] > 0 or self.p['req_scrit'] > 0:
            # remaining good-altitude hours this season: targets about to leave the sky get priority
            S = self.hours_suffix[night + 1, pool].astype(float) + self._good_hours(now, self.night_ends[night], pool)
            if self.p['req_moon'] > 0 and len(jr):
                S_dk = self._req_dark_hours(now, night, self.rq_pos[pool[jr]])
        if self.p['urgency'] > 0:
            Sref = max(0.5, float(np.median(S)))
            S_u = S
            if S_dk is not None and self.p['req_moon_urg'] > 0:
                S_u = S.copy()
                S_u[jr] = np.minimum(S[jr], S_dk)
            urg = np.clip((Sref / np.maximum(S_u, 0.25)) ** self.p['urgency'], 0.33, 3.0)
            if self.p['req_urg'] > 0 and len(jr):
                urg[jr] = np.clip((Sref / np.maximum(S_u[jr], 0.25)) ** self.p['req_urg'], 0.33, self.p['req_urg_cap'])
        else:
            urg = np.ones(n)
        scrit = None
        if S is not None and self.p['req_scrit'] > 0:
            # a required target with many good hours left will most likely be completed later anyway --
            # unless it needs better-than-typical conditions: count only the hours good enough for it
            S_eff = S
            if S_dk is not None:
                S_eff = S.copy()
                S_eff[jr] = S_dk
            elif self.p['req_hard'] > 0:
                zc = math.exp(self.logZ_mean + self.bel.leta_plan(now, night))
                gmt = self.flux[pool] * zc * np.maximum(hb, 1e-6) * self.tmax / (self.q0 * self.f0t0)
                lr = np.log(self.req_thr * self.p['req_safety'] / np.maximum(gmt, 1e-9))
                pok = 1.0 - 0.5 * (1.0 + _erf(lr / (self.p['req_hard'] * math.sqrt(2.0))))
                S_eff = S * np.maximum(pok, 0.02)
            scrit = np.clip(self.p['req_scrit'] / np.maximum(S_eff, 0.25), self.p['req_floor'], 1.0)
        rqb = reqbonus_active[pool]
        thr_rq = np.maximum(req_thr[pool], 1e-3)
        dl_rq = req_deadline[pool]
        sigb = max(self.p['band_sigma'], sig)
        sg = math.sqrt(sig * sig + self.p['g_sigma'] ** 2)
        wopt = self.p['opt_value'] * rich
        dbg = bool(os.environ.get('OBS2_DEBUG'))
        # per-target arrays, filled slice by slice (each target's values depend only on its own inputs)
        alts = np.empty((ns, n))
        valid = np.empty((nt, n), dtype=bool)
        tf = np.empty((ns, n)) if terrain else None
        tbar = np.empty((nt, n)) if terrain else np.ones((nt, n))
        g = np.empty((nt, n))
        rho = np.empty(n)
        reqv = np.zeros((nt, n))
        val = np.zeros((n, nt, 3), dtype=np.float32)
        solo = np.empty(n)
        B = np.empty((nt, n)) if dbg else None
        pd = np.empty((nt, n)) if dbg else None
        sqrt2 = math.sqrt(2.0)

        def values(a, b):
            p_ = pool[a:b]
            m_ = b - a
            al = alts[:, a:b]
            for s, dt in enumerate(samples):
                al[s] = self._alt_after(ha_now[a:b], dt, p_) if dt > 0 else alt_now[a:b]
            cummin = np.minimum.accumulate(al, axis=0)
            vd = cummin[1:] >= self.min_alt + 0.05            # nt x m
            valid[:, a:b] = vd
            eq = self.eqv[p_]
            lun = np.empty((ns, m_))
            for s, dt in enumerate(samples):
                lun[s] = self._lunar(eq, now + dt)
            Hs = lun * self._hfac(al)
            # trapezoid cumulative average
            seg = 0.5 * (Hs[1:] + Hs[:-1]) * dts[:, None]
            Hbar = np.cumsum(seg, axis=0) / samples[1:, None]       # nt x m
            if terrain:
                # expected unobstructed fraction along each target's track (setting targets may enter terrain)
                tf_ = 1.0 - self._terrain_pb2d(al, az_now[a:b])
                tf[:, a:b] = tf_
                tb = np.cumsum(0.5 * (tf_[1:] + tf_[:-1]) * dts[:, None], axis=0) / samples[1:, None]   # nt x m
                tbar[:, a:b] = tb
            else:
                tb = tbar[:, a:b]
            kfac = self.flux[p_] * Zp * dirf[a:b] / (self.q0 * self.f0t0)
            g_ = np.minimum(1.0, kfac[None, :] * Hbar * tg[:, None] * tb)  # nt x m
            g[:, a:b] = g_
            hb_ = hb[a:b]
            gmax = np.minimum(1.0, self.flux[p_] * zref * np.maximum(hb_, 1e-6) * self.tmax / (self.q0 * self.f0t0))
            gmax = np.maximum(gmax, 1e-3)
            phi = np.minimum(1.0, g_ / gmax[None, :]) ** gam if gam > 0 else np.ones_like(g_)
            hcur = Hs[0] * 1.0
            rho_ = np.minimum(1.0, hcur / np.maximum(hb_, 1e-6)) ** alpha if alpha > 0 else np.ones(m_)
            if hbz is not None:
                rho_s = np.minimum(1.0, hcur * self.mseason_rel[night] / np.maximum(hbz[a:b], 1e-6)) ** alpha
                rho_ = rho_ ** (1.0 - ws) * rho_s ** ws
            rho[a:b] = rho_
            # program expected multipliers
            B_ = Cp * Hbar / self.q0
            lb = np.log(np.maximum(B_, 1e-9))
            pd_ = 0.5 * (1 + _erf((lb - math.log(self.band_dark)) / (sigb * sqrt2)))
            pbb = 0.5 * (1 + _erf((lb - math.log(self.band_bright)) / (sigb * sqrt2)))
            if dbg:
                B[:, a:b] = B_
                pd[:, a:b] = pd_
            probs = [pd_, pbb - pd_, 1 - pbb]
            base_sci = self.w[p_][None, :] * g_ * phi
            lg = np.log(np.maximum(g_, 1e-9))
            rv = reqv[:, a:b]
            jr_ = jr[(jr >= a) & (jr < b)] - a
            if len(jr_):
                p_req = 0.5 * (1 + _erf((lg[:, jr_] - math.log(self.req_thr) - math.log(self.p['req_safety'])) / (sg * sqrt2)))
                rv[:, jr_] = p_req * self.req_pen * self.p['req_bonus_scale']
            if scrit is not None:
                rv *= scrit[a:b][None, :]
            rqb_ = rqb[a:b]
            extra_r = np.zeros((nt, m_))
            jq = np.flatnonzero(rqb_ > 0)
            if len(jq):
                p_rq = 0.5 * (1 + _erf((lg[:, jq] - np.log(thr_rq[a:b][jq])[None, :] - math.log(self.p['req_safety'])) / (sg * sqrt2)))
                rq_ok = now + tg[:, None] <= dl_rq[a:b][jq][None, :]
                extra_r[:, jq] = rq_ok * p_rq * rqb_[jq][None, :]
            best_ = self.best[p_]
            if wopt > 0:
                # only the best exposure counts: a repeat has an upside from the scatter of the realised quality
                # (expected improvement of a lognormal outcome over the current best, as a call option)
                jo = np.flatnonzero((best_ > 1e-9) & (best_ < self.w[p_] * self.mult[0] * 0.995))
                so = max(sg, 0.05)
            urg_ = urg[a:b]
            vl = val[a:b]
            for P in range(3):
                m = self.mismatch + (self.mult[P] - self.mismatch) * probs[P]
                sci = np.maximum(0.0, base_sci * m - best_[None, :])
                if wopt > 0 and len(jo):
                    F = np.maximum(base_sci[:, jo] * m[:, jo], 1e-12)
                    K = best_[jo][None, :]
                    d1 = (np.log(F / K) + 0.5 * so * so) / so
                    call = F * 0.5 * (1.0 + _erf(d1 / sqrt2)) - K * 0.5 * (1.0 + _erf((d1 - so) / sqrt2))
                    cap = np.maximum(0.0, self.w[p_][jo][None, :] * self.mult[P] - K)
                    call = np.clip(call, sci[:, jo], np.maximum(cap, sci[:, jo]))
                    sci[:, jo] = sci[:, jo] + wopt * (call - sci[:, jo])
                v = ((sci + rv) * urg_[None, :] + extra_r) * rho_[None, :]
                v = np.where(vd, v, 0.0)
                vl[:, :, P] = v.T
            solo[a:b] = (vl.max(axis=2) / tg[None, :]).max(axis=1)

        self._split(values, n, 2000)
        # candidate centres
        order = np.argsort(-solo)
        if os.environ.get('OBS2_DEBUG_TGT'):
            if not hasattr(self, '_dbg_tgt'):
                self._dbg_tgt = {self.index[t] for t in open(os.environ['OBS2_DEBUG_TGT']).read().split() if t in self.index}
            rank = np.empty(n, dtype=int); rank[order] = np.arange(n)
            jj = [j for j in range(n) if int(pool[j]) in self._dbg_tgt]
            if jj:
                Sd = S if S is not None else np.zeros(n)
                _log({'dtop': fmt_utc(now), 'top': [(self.ids[int(pool[j])], bool(self.req[pool[j]]), round(float(self.flux[pool[j]]), 2),
                                                     round(float(alt_now[j]), 1), round(float(solo[j]), 3), round(float(reqv[:, j].max()), 1),
                                                     round(float(rqb[j]), 1), round(float(urg[j]), 2), round(float(Sd[j]), 1),
                                                     round(float(rho[j]), 2)) for j in order[:8]]})
                _log({'dtgt': fmt_utc(now), 'n': n, 'top_solo': round(float(solo[order[0]]), 4),
                      'tg': [(self.ids[int(pool[j])], round(float(alt_now[j]), 1), int(rank[j]), round(float(solo[j]), 4),
                              round(float(reqv[:, j].max()), 2), round(float(rho[j]), 2), round(float(urg[j]), 2),
                              int(valid[:, j].sum()), round(float(g[-1, j]), 2)) for j in jj]})
        if os.environ.get('OBS2_DEBUG_REQ') and np.any(rqb > 0):
            jj = np.flatnonzero(rqb > 0)
            rank = np.empty(n, dtype=int); rank[order] = np.arange(n)
            _log({'dreq': fmt_utc(now), 'n': n, 'req': [(self.ids[int(pool[j])], round(float(alt_now[j]), 1), round(float(rqb[j]), 1), round(float(solo[j]), 4), int(rank[j]), round(float(rho[j]), 2), round(float(g[-1, j]), 2)) for j in jj], 'top_solo': round(float(solo[order[0]]), 4)})
        anchors_n = int(self.p['anchors'])
        if emergency:
            anchors_n = 2
        elif per_dec < 0.004:
            anchors_n = 4
        elif per_dec < 0.010:
            anchors_n = max(6, anchors_n // 3)
        elif per_dec < 0.020:
            anchors_n = max(10, anchors_n // 2)
        if self.anchor_cost is not None:
            # measured planning cost: fixed part + per-anchor part; keep the projection within budget
            fixed, per_a = self.anchor_cost
            afford = int((0.85 * per_dec - fixed) / max(per_a, 1e-6))
            anchors_n = int(min(anchors_n, max(6, afford)))
        self._anchors_used = anchors_n
        tv = tvall[pool]
        anchors = []
        min_sep = math.cos(max(0.3 * self.fov, self.pitch) * DEG)
        cand_a = order[: max(200, anchors_n * 8)]
        cand_a = cand_a[solo[cand_a] > 0]
        if len(cand_a):
            Ua = np.ascontiguousarray(tv[cand_a])
            blocked = np.zeros(len(cand_a), dtype=bool)
            for i in range(len(cand_a)):
                if blocked[i]:
                    continue
                anchors.append(int(cand_a[i]))
                if len(anchors) >= anchors_n:
                    break
                blocked |= Ua @ Ua[i] >= min_sep
        if not anchors:
            return None
        calt, caz = self._anchor_centres(tv, anchors)
        cos_r = math.cos((self.fov * 0.75 + 0.05) * DEG)
        margin = self.p['margin_frac'] * self.pitch
        if not self.off_confident and self.misses_total > 0:
            margin = max(margin, 0.12 * self.pitch)
        elif self.misses_total == 0 and self.off_obs >= 20 and self.p['margin_clean'] >= 0:
            # no pointing offset seen: cells tile the field, only the seam itself is ambiguous
            margin = self.p['margin_clean'] * self.pitch
        margin += 0.5 * self.gap
        t0v = self._capacity_t0(now, night) + self.p['t0_const']
        tg_eff = tg + t0v
        mblk = len(calt) // len(anchors)
        rate, bt, bp, tot = self._eval_local(calt, caz, tv, val, tg_eff, margin, cos_r,
                                             [(i * mblk, (i + 1) * mblk, tv[j]) for i, j in enumerate(anchors)])
        best_k = int(np.argmax(rate))
        # local refinement (pattern search) around the best few
        if per_dec >= 0.006 and self.p['refine_iter'] > 0:
            # iterative pattern search, all starts in parallel: move to the best neighbour or halve the step
            n_top = int(self.p['refine_top'])
            if self.p['refine_scale'] > 0 and anchors_n < self.p['anchors']:
                # the budget capped the field search: cut the refinement in proportion
                n_top = max(2, int(round(n_top * anchors_n / max(1.0, float(self.p['anchors'])))))
            top = list(np.argsort(-rate)[:n_top])
            ca, cz, cr = calt[top].copy(), caz[top].copy(), rate[top].copy()
            ct, cp_, cto = bt[top].copy(), bp[top].copy(), tot[top].copy()
            step = np.full(len(top), 0.5 * self.pitch)
            dirs = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1))
            for _it in range(int(self.p['refine_iter'])):
                act_ = np.flatnonzero(step >= 0.06 * self.pitch)
                if len(act_) == 0:
                    break
                nd = len(dirs)
                dv = np.array(dirs, dtype=float)
                ra_, za_ = self._shift_vec(np.repeat(ca[act_], nd), np.repeat(cz[act_], nd),
                                           (dv[:, 0][None, :] * step[act_][:, None]).ravel(),
                                           (dv[:, 1][None, :] * step[act_][:, None]).ravel())
                r2, t2, p2, tot2 = self._eval_local(ra_, za_, tv, val, tg_eff, margin, cos_r,
                                                    [(i * nd, (i + 1) * nd, self._unit(ca[k], cz[k])) for i, k in enumerate(act_)])
                r2 = r2.reshape(len(act_), len(dirs))
                for a_i, k in enumerate(act_):
                    j = int(np.argmax(r2[a_i]))
                    if r2[a_i, j] > cr[k] * (1 + 1e-9):
                        q = a_i * len(dirs) + j
                        ca[k], cz[k], cr[k] = ra_[q], za_[q], r2[a_i, j]
                        ct[k], cp_[k], cto[k] = t2[q], p2[q], tot2[q]
                    else:
                        step[k] *= 0.5
            j = int(np.argmax(cr))
            if cr[j] > rate[best_k]:
                calt = np.append(calt, ca[j]); caz = np.append(caz, cz[j])
                rate = np.append(rate, cr[j]); bt = np.append(bt, ct[j]); bp = np.append(bp, cp_[j]); tot = np.append(tot, cto[j])
                best_k = len(rate) - 1
        elif per_dec >= 0.006:
            top = list(np.argsort(-rate)[: int(self.p['refine_top'])])
            cands = []
            for k in top:
                for frac in (0.5, 0.25, 0.12):
                    for da, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                        cands.append(self._shift(calt[k], caz[k], da * frac * self.pitch, dz * frac * self.pitch))
            if cands:
                ra_, za_ = np.array([c[0] for c in cands]), np.array([c[1] for c in cands])
                per = len(cands) // len(top)
                r2, t2, p2, tot2 = self._eval_local(ra_, za_, tv, val, tg_eff, margin, cos_r,
                                                    [(i * per, (i + 1) * per, self._unit(calt[k], caz[k])) for i, k in enumerate(top)])
                j = int(np.argmax(r2))
                if r2[j] > rate[best_k]:
                    calt = np.append(calt, ra_[j]); caz = np.append(caz, za_[j])
                    rate = np.append(rate, r2[j]); bt = np.append(bt, t2[j]); bp = np.append(bp, p2[j]); tot = np.append(tot, tot2[j])
                    best_k = len(rate) - 1
        if rate[best_k] <= 1e-9:
            return None
        ti, Pi = int(bt[best_k]), int(bp[best_k])
        out_t, out_v = self.kern.assign(calt[best_k], caz[best_k], tv, val, self.side, self.pitch, margin, cos_r, ti, Pi)
        cells = np.flatnonzero(out_t >= 0)
        if len(cells) == 0:
            return None
        chosen = out_t[cells]
        T = int(tg[ti])
        assignments = {str(int(f)): self.ids[int(pool[j])] for f, j in zip(cells, chosen)}
        oa, oz = self.off_est if self.off_confident or self.misses_total > 0 else (0.0, 0.0)
        cmd_alt = float(calt[best_k]) - oa
        cmd_az = (float(caz[best_k]) - oz) % 360.0
        if not (0.0 <= cmd_alt <= 90.0):
            cmd_alt = min(90.0, max(0.0, cmd_alt))
        chosen_pool = pool[chosen]
        dirf_map = {int(pool[j]): float(dirf[j] * min(tbar[ti, j], tf[0, j] if self.terrain_dirs else 1.0)) for j in chosen}
        self.pending = {
            'kind': 'observe', 't': now, 'T': float(T), 'P': Pi, 'idx': chosen_pool,
            'fib': cells.astype(np.int32), 'tv': tv[chosen], 'calt': float(calt[best_k]), 'caz': float(caz[best_k]),
            'cmd_alt': cmd_alt, 'cmd_az': cmd_az,
            'alt': alt_now[chosen], 'alt_end': alts[ti + 1][chosen], 'az': az_now[chosen], 'C': Cp, 'sig': sigb, 'notices': list(notices),
            'bul_t': self.bul_t, 'dirf': True,
            'dirf_hit': (lambda ids, m=dirf_map: np.array([m.get(int(i), 1.0) for i in ids])),
        }
        self.avg_T = 0.95 * self.avg_T + 0.05 * T
        self.fill_ema = len(chosen) if self.observes == 0 else 0.97 * self.fill_ema + 0.03 * len(chosen)
        if os.environ.get('OBS2_DEBUG'):
            _log({'d': fmt_utc(now), 'Zp': round(Zp, 3), 'Cp': round(Cp, 3), 'sig': round(sig, 3), 'P': PROGRAMS[Pi], 'T': T,
                  'n': len(chosen), 'B': [round(float(B[ti, j]), 3) for j in chosen[:5]], 'pd': [round(float(pd[ti, j]), 2) for j in chosen[:5]],
                  'rate': round(float(rate[best_k]), 5), 'pf': round(self.bel.p_fault(), 3), 'zmean': round(self.logZ_mean, 3)})
        src = 'optimizer+llm-strategy' if self.strategist is not None and self.strategist.source == 'llm' else 'optimizer'
        return {'action': 'observe', 'pointing': {'alt_deg': round(cmd_alt, 6), 'az_deg': round(cmd_az % 360.0, 6)},
                'assignments': assignments, 'duration_seconds': T, 'program': PROGRAMS[Pi], 'decision_source': src}

    def _request_feasible(self, cand, now, deadline, need=1, thr=0.5, night=None):
        """Number of request targets that can reach the completion threshold before the deadline
        (above the altitude limit, and a single exposure <= tmax suffices at climatological quality);
        returns 0 when the cheapest `need` exposures do not fit into half of the remaining dark time."""
        k = self._night_index(now)
        ks = [k] if k >= 0 else []
        ks += [j for j in range(len(self.nights)) if self.night_starts[j] > now and self.night_starts[j] < deadline]
        hbest = np.zeros(len(cand))
        avail = 0.0
        for j in ks:
            a = max(now, self.night_starts[j])
            b = min(deadline, self.night_ends[j])
            if b - a < self.tmin:
                continue
            avail += b - a
            h0 = (lst_deg(a, self.lon) - self.ra[cand] + 180.0) % 360.0 - 180.0
            span = SID * (b - a) / 86400.0
            to_tr = (-h0) % 360.0
            z0 = self.sin_lat * self.sdec[cand] + self.cos_lat * self.cdec[cand] * np.cos(h0 * DEG)
            z1 = self.sin_lat * self.sdec[cand] + self.cos_lat * self.cdec[cand] * np.cos((h0 + span) * DEG)
            amax = np.where(to_tr <= span, self.transit_alt[cand], np.arcsin(np.clip(np.maximum(z0, z1), -1, 1)) / DEG)
            hbest = np.maximum(hbest, np.where(amax >= self.min_alt + 1.0, airmass(amax) ** (-self.beta), 0.0))
        nn = night if night is not None and night >= 0 else max(0, k)
        q = math.exp(self.bel.clim(nn) + self.bel.leta_plan(now, nn)) / self.q0
        tneed = np.where(hbest > 0, thr * 1.15 * self.f0t0 / np.maximum(self.flux[cand] * q * np.maximum(hbest, 1e-6), 1e-9), np.inf)
        ok = tneed <= self.tmax
        if int(ok.sum()) < need:
            return int(ok.sum())
        tsum = float(np.sum(np.sort(np.maximum(tneed[ok], self.tmin))[:need]))
        if tsum > 0.5 * avail:
            return 0
        return int(ok.sum())

    # ------------------------------------------------------------------ threads
    def _workers(self):
        """Executor with the second worker thread (created on first use); None when single-threaded."""
        if int(self.p['threads']) <= 1:
            return None
        if getattr(self, '_exec', None) is None:
            from concurrent.futures import ThreadPoolExecutor
            self._exec = ThreadPoolExecutor(max_workers=1)
        return self._exec

    def _split(self, fn, n, min_n=2):
        """fn(a, b) over [0, n): the upper half in the worker thread while this thread does the lower half
        (numpy and the kernel release the GIL, so the halves run on both cores)."""
        ex = self._workers() if n >= max(2, min_n) else None
        if ex is None:
            fn(0, n)
            return
        h = n // 2
        fut = ex.submit(fn, h, n)
        try:
            fn(0, h)
        finally:
            fut.result()

    def _eval_local(self, calt, caz, tv, val, tg_eff, margin, cos_r, group=None):
        """eval_centers restricted to the pool targets near each group of centres (same result, less work).
        group: list of (start, end, unit vector) blocks of centres sharing a neighbourhood."""
        nc = len(calt)
        rate = np.zeros(nc); bt = np.zeros(nc, dtype=np.int32); bp = np.zeros(nc, dtype=np.int32); tot = np.zeros(nc)
        cos_sub = math.cos(min(179.0, 1.6 * self.fov + 0.3) * DEG)
        if self.kern.groups and len(group):
            # one kernel call per half of the groups (alternate groups, so both halves see similar sky)
            calt = np.ascontiguousarray(calt, dtype=np.float64)
            caz = np.ascontiguousarray(caz, dtype=np.float64)
            tv = np.ascontiguousarray(tv, dtype=np.float64)
            val = np.ascontiguousarray(val, dtype=np.float32)
            tg = np.ascontiguousarray(tg_eff, dtype=np.float64)
            gs = np.array([g_[0] for g_ in group], dtype=np.int32)
            ge = np.array([g_[1] for g_ in group], dtype=np.int32)
            gu = np.ascontiguousarray(np.array([g_[2] for g_ in group], dtype=np.float64).reshape(len(group), 3))
            nh = 2 if int(self.p['threads']) > 1 and len(group) >= 2 else 1
            parts = [(np.ascontiguousarray(gs[h::nh]), np.ascontiguousarray(ge[h::nh]), np.ascontiguousarray(gu[h::nh]))
                     for h in range(nh)]
            lib = self.kern.lib
            # pool order by altitude (once per pool): each group scans only the band that can reach it
            zc = getattr(self, '_zorder', None)
            if zc is None or zc[0] is not tv:
                zo = np.ascontiguousarray(np.argsort(tv[:, 2], kind='stable'), dtype=np.int32)
                zc = (tv, zo, np.ascontiguousarray(tv[zo, 2]))
                self._zorder = zc
            zo, zs = zc[1], zc[2]
            th_sub = min(179.0, 1.6 * self.fov + 0.3) * DEG

            def run(a, b):
                for s_, e_, u_ in parts[a:b]:
                    lib.eval_groups(len(s_), s_.ctypes.data, e_.ctypes.data, u_.ctypes.data, calt.ctypes.data,
                                    caz.ctypes.data, len(tv), tv.ctypes.data, len(tg), val.ctypes.data, tg.ctypes.data,
                                    self.side, self.pitch, margin, cos_r, cos_sub, zo.ctypes.data, zs.ctypes.data,
                                    th_sub, rate.ctypes.data, bt.ctypes.data, bp.ctypes.data, tot.ctypes.data)
            self._split(run, nh)
            return rate, bt, bp, tot
        for a, b, u in group:
            sub = np.flatnonzero(tv @ u >= cos_sub)
            if len(sub) == 0:
                continue
            r_, t_, p_, o_ = self.kern.eval_centers(calt[a:b], caz[a:b], tv[sub], val[sub], tg_eff, self.side, self.pitch,
                                                     margin, cos_r)
            rate[a:b], bt[a:b], bp[a:b], tot[a:b] = r_, t_, p_, o_
        return rate, bt, bp, tot

    @staticmethod
    def _unit(alt, az):
        a, z = alt * DEG, az * DEG
        return np.array([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])

    def _anchor_centres(self, tv, anchors):
        side, pitch = self.side, self.pitch
        mid = (side - 1) / 2.0
        if side <= 5:
            cells = [(r, c) for r in range(side) for c in range(side)]
        else:
            pick = sorted(set(int(round(x)) for x in np.linspace(0, side - 1, 5)))
            cells = [(r, c) for r in pick for c in pick]
        du = np.array([0.0] + [-(r - mid) * pitch for r, c in cells])
        dr = np.array([0.0] + [-(c - mid) * pitch for r, c in cells])
        U = tv[np.asarray(anchors, dtype=int)]
        alt = np.arcsin(np.clip(U[:, 2], -1.0, 1.0))
        az = np.arctan2(U[:, 1], U[:, 0])
        ca, sa, cz, sz = np.cos(alt), np.sin(alt), np.cos(az), np.sin(az)
        c = np.stack((ca * cz, ca * sz, sa), axis=1)
        up = np.stack((-sa * cz, -sa * sz, ca), axis=1)
        rt = np.stack((-sz, cz, np.zeros_like(sz)), axis=1)
        v = (c[:, None, :] + np.tan(du * DEG)[None, :, None] * up[:, None, :]
             + np.tan(dr * DEG)[None, :, None] * rt[:, None, :])
        v /= np.linalg.norm(v, axis=2, keepdims=True)
        calt = np.arcsin(np.clip(v[:, :, 2], -1.0, 1.0)) / DEG
        caz = (np.arctan2(v[:, :, 1], v[:, :, 0]) / DEG) % 360.0
        return calt.ravel(), caz.ravel()

    @staticmethod
    def _shift_vec(alt, az, d_up, d_right):
        """Vectorised _shift: arrays of centres and tangent-plane offsets (deg)."""
        a, z = alt * DEG, az * DEG
        ca, sa, cz, sz = np.cos(a), np.sin(a), np.cos(z), np.sin(z)
        tu, tr = np.tan(d_up * DEG), np.tan(d_right * DEG)
        vx = ca * cz + tu * (-sa * cz) + tr * (-sz)
        vy = ca * sz + tu * (-sa * sz) + tr * cz
        vz = sa + tu * ca
        nrm = np.sqrt(vx * vx + vy * vy + vz * vz)
        return np.arcsin(np.clip(vz / nrm, -1.0, 1.0)) / DEG, (np.arctan2(vy, vx) / DEG) % 360.0

    @staticmethod
    def _shift(alt, az, d_up, d_right):
        a, z = alt * DEG, az * DEG
        c = np.array([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])
        up = np.array([-math.sin(a) * math.cos(z), -math.sin(a) * math.sin(z), math.cos(a)])
        rt = np.array([-math.sin(z), math.cos(z), 0.0])
        v = c + math.tan(d_up * DEG) * up + math.tan(d_right * DEG) * rt
        v /= np.linalg.norm(v)
        return math.asin(max(-1.0, min(1.0, v[2]))) / DEG, (math.atan2(v[1], v[0]) / DEG) % 360.0

    # ------------------------------------------------------------------ season strategist (language model)
    def _apply_strategy(self):
        """Set the policy parameters of the season strategy currently chosen by the strategist."""
        st = self.strategist
        if st is None or self._safe:
            return
        from llm_strategist import STRATEGIES
        for k, v in STRATEGIES.get(st.strategy, {}).items():
            self.p[k] = v

    def _mission_brief(self, init):
        """Task card digest for the strategist's mission analysis: the free-text descriptions, the rules,
        and catalogue, visibility and capacity statistics."""
        brief = {'date': fmt_utc(self.night_starts[0])[:10] if len(self.night_starts) else None}
        try:
            site = init.get('site', {}) or {}
            ins = init.get('instrument', {}) or {}
            sc = init.get('scoring', {}) or {}
            tg = init.get('targets', {}) or {}
            cols = {c: k for k, c in enumerate(tg.get('columns', []))}
            classes = {}
            if 'target_class' in cols:
                for r in tg.get('rows', []):
                    c = str(r[cols['target_class']])
                    classes[c] = classes.get(c, 0) + 1
            dark_h = float(np.sum(self.night_ends - self.night_starts)) / 3600.0
            ridx = np.flatnonzero(self.req)
            req = {'count': int(len(ridx))}
            if len(ridx) and hasattr(self, 'rq_pos'):
                S = self._req_dark_hours(float(self.night_starts[0]), 0, self.rq_pos[ridx])
                req.update({'season_hours_in_which_one_exposure_completes_them': {
                    'median': round(float(np.median(S)), 1), 'targets_below_1h': int(np.sum(S < 1)),
                    'below_5h': int(np.sum(S < 5)), 'below_20h': int(np.sum(S < 20))},
                    'flux_quantiles_10_50_90': [round(float(x), 3) for x in np.percentile(self.flux[ridx], [10, 50, 90])]})
            q = math.exp(self.bel.clim(0) + self.bel.leta_plan(float(self.night_starts[0]), 0)) / self.q0 * 0.85
            tneed = np.minimum(self.tmax, self.f0t0 / np.maximum(self.flux * q, 1e-9))
            demand_h = float(tneed.sum()) / max(1.0, 0.5 * self.nfib) / 3600.0
            lim = init.get('limits', {}) or {}
            brief.update({
                'task_card': init.get('task_card'),
                'site': {'name': site.get('name'), 'latitude_deg': self.lat, 'longitude_deg': self.lon,
                         'minimum_altitude_deg': self.min_alt},
                'survey': {'start_utc': (init.get('survey') or {}).get('start_utc'), 'end_utc': fmt_utc(self.survey_end),
                           'nights': len(self.nights), 'dark_hours_total': round(dark_h)},
                'instrument': {'n_fibers': self.nfib, 'grid_side': self.side, 'field_of_view_deg': round(self.fov, 3),
                               'layout': ins.get('layout'), 'exposure_seconds_min_max': [self.tmin, self.tmax]},
                'limits': {k: lim.get(k) for k in ('global_wallclock_seconds', 'decision_timeout', 'max_consecutive_reports')},
                'scoring': {k: sc.get(k) for k in ('required', 'reporting', 'program', 'observation_requests', 'uniformity')},
                'catalogue': {'targets': self.n, 'classes': classes,
                              'flux_quantiles_10_50_90': [round(float(x), 3) for x in np.percentile(self.flux, [10, 50, 90])],
                              'required': req},
                'capacity': {'telescope_hours_to_complete_every_target_at_typical_sky': round(demand_h),
                             'dark_hours_available': round(dark_h),
                             'demand_over_supply': round(demand_h / max(1.0, 0.85 * dark_h), 2),
                             'note': 'above ~0.6 capacity-limited, below ~0.2 time-rich'}})
        except Exception as e:
            brief['error'] = type(e).__name__
        return brief

    def _submit_weekly(self, snap, now):
        """Weekly plan review: forecast, Moon and progress for the strategist (asynchronous)."""
        st = self.strategist
        if st is None or not st.enabled or self._safe:
            return
        try:
            N = len(self.nights)
            night = int(np.searchsorted(self.night_starts, now, side='right')) - 1
            night = min(max(night, 0), N - 1)
            inc = np.flatnonzero(self.req & (self.gl < self.req_thr))
            req = {'total': int(self.req.sum()), 'completed': int(self.req.sum()) - int(len(inc)), 'remaining': int(len(inc))}
            if len(inc) and hasattr(self, 'rq_pos'):
                S = self._req_dark_hours(now, night, self.rq_pos[inc])
                req['remaining_by_completion_hours_left'] = {'below_1h': int(np.sum(S < 1)), 'below_5h': int(np.sum(S < 5)),
                                                             'below_20h': int(np.sum(S < 20))}
            fc = self._forecast or {}
            notices = [{'event': n.get('event_kind'), 'direction': n.get('direction'), 'nights': n.get('nights')}
                       for n in (fc.get('notices') or [])][:40]
            moon = []
            for k in range(night, min(N, night + 7)):
                a, b = self.nights[k]
                ms = [moon_state(a + (b - a) * (j + 0.5) / 6.0, self.lat, self.lon) for j in range(6)]
                moon.append({'night': fmt_utc(a)[:10], 'illumination': round(float(np.mean([m[1] for m in ms])), 2),
                             'fraction_of_night_moon_up': round(sum(1 for m in ms if m[2] > 0) / 6.0, 2)})
            wc = snap.get('wallclock') or {}
            try:
                cpu_left = round(float(wc.get('remaining_seconds')) / max(1.0, self.budget_total), 3)
            except (TypeError, ValueError):
                cpu_left = None
            sci = float(np.sum(self.best)) / max(1e-9, float(np.sum(self.w * self.mult[0])))
            brief = {'date': fmt_utc(now)[:10],
                     'season': {'night': night + 1, 'nights': N, 'fraction_elapsed': round(night / max(1, N), 3)},
                     'science_fraction_of_maximum': round(sci, 3),
                     'required_targets': req,
                     'observation_requests_active': len(snap.get('active_requests') or []),
                     'instrument_faults': {'reports': self.reports, 'correct': self.correct_reports,
                                           'fault_probability_now': round(self.bel.p_fault(), 3)},
                     'time_budget': {'cpu_budget_left_fraction': cpu_left,
                                     'real_time_left_s': wc.get('wall_remaining_seconds')},
                     'forecast_next_7_nights': notices, 'moon_next_7_nights': moon}
            st.submit('weekly', brief, wall_left=wc.get('wall_remaining_seconds'))
        except Exception:
            import traceback
            traceback.print_exc(file=sys.stderr)

    def summary(self):
        return {'decisions': self.decisions, 'observes': self.observes, 'reports': self.reports,
                'correct_reports': self.correct_reports, 'false_reports': self.reports - self.correct_reports,
                'dec_cpu': round(self.dec_cpu, 2), 'init_cpu': round(self.init_cpu, 2),
                'charge_ratio': round(self._charge_ratio, 3), 'turn_wall': round(self.turn_wall, 1),
                'offset_est': [round(self.off_est[0], 4), round(self.off_est[1], 4)], 'offset_obs': self.off_obs,
                'misses': self.misses_total, 'logZ_mean': round(self.logZ_mean, 3), 'kernel': self.kern.lib is not None,
                'pf': round(self.bel.p_fault(), 4), 'quakes': [round(self.bel._d0_hat(q), 3) for q in self.bel.quakes], 'bad': getattr(self.bel, 'n_bad', 0), 'cap': None if self.cap_ratio is None else round(self.cap_ratio, 3), 't0': round(getattr(self, '_t0_cache', 0.0), 1), 'rich': round(getattr(self, '_rich_cache', 0.0), 3), 'pool_scale': round(self.pool_scale, 3), 'nfault': self.bel.nfault, 'pc': [round(float(x), 3) for x in self.bel.pc], 'stress': self.stress_seen, 'anchor_cost': None if self.anchor_cost is None else [round(self.anchor_cost[0], 4), round(self.anchor_cost[1], 5)],
                'llm': self.strategist.summary() if self.strategist is not None else None}


def _erf(x):
    # vectorised erf (Abramowitz-Stegun 7.1.26), |err| < 1.5e-7
    s = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-a * a)
    return s * y


def make(payload):
    return Policy(payload)
