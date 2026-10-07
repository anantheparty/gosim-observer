"""Scalable v4 observer policy: per-decision greedy field selection with a season-aware value model.

Value of observing target i for T seconds with program P:
    rho_i * [ max(0, w_i E[m|P] g_i(T) phi_i(T) - best_i) + required bonus + request bonus ]
phi discounts partial completions relative to the best completion still reachable this season,
rho = (H_now / H_best_remaining)^alpha prefers each target's own best geometry.
Field (centre, T, P) maximises sum over fibre cells of the best target value, divided by T.
"""
from __future__ import annotations

import ctypes
import re
import json
import math
import os
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

from astro import DEG, SID, airmass, fmt_utc, lst_deg, moon_state, parse_utc
try:
    import sophon_probe
except Exception:  # optional easter-egg hook
    sophon_probe = None

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
    'sophon_probe': 0,     # >0: Sophon easter-egg hook, only when the platform provides SOPHON_RUN_TOKEN
    'rq_rich': 0.0,        # >0: request bonuses x (1 + rq_rich * richness): requests are cheap when time-rich
    'rq_norho': 0,         # 1: request bonuses are not discounted by the season timing factor rho (a request
                           #    expires within days, so there is no better later geometry to wait for)
    'off_wide': 0.0,       # >0: once pointing misses appear, also fit offsets up to max(0.5 deg, off_wide x cell pitch)
                           #    on a coarse grid and move the fine grid (+-0.16 deg) to its best fit
    'rq_commit': 0.0,      # >0: a request with completed targets stays pursued while its remaining exposures fit into
                           #    this fraction of the dark time left before its deadline (default 0.5 for all)
    'rq_big': 0,           # 1: the fraction grows to 0.9 when the reward per needed hour exceeds 8x the science
                           #    value rate (all-or-nothing rewards that dwarf the science of the same time)
    'terr_hi': 0,          # 1: terrain may reach any altitude (a card parameter; reference 35-50 deg): zeros on an
                           #    open site outside announced closing events teach the terrain at any altitude, the
                           #    height prior is learned per announced direction, and a closure is only inferred
                           #    when a probe away from the announced terrain also scores zero
    'wx_adapt': 0.0,       # >0: weather process noise x clip(median normalised innovation / wx_adapt, 1, 8), learned
                           #    online (the weather variability is a card parameter); 0: fixed generator values
    'rq_urg_intra': 0.0,   # >0: request bonus x clip((1.5 h / hours the target stays observable before the
                           #    request deadline tonight) ** this, 1, 3): the members about to set go first
    'eng_aware': 0,        # 1: model the engine's time between turns (it grows with requests issued x observations
                           #    recorded, the engine re-checks every request against every observation each step)
                           #    and, when the rest of the season would not fit the hard real-time cap, use longer
                           #    exposures and closure waits (fewer engine steps and records)
    'eng_share': 0.7,      # share of the remaining real time the projected engine time may take before that
    'quick_long': 0.0,     # >0: the pool screen also keeps targets that only the longest exposure can improve (their
                           #    best came from a long exposure, so 1800 s at the current quality gains nothing);
                           #    they rank below every target an 1800 s exposure improves
    'quick_long_fill': 1.0,  # quick_long only while the recent exposures use fewer than this share of the fibres
                           #    (idle fibres: the survey has run out of targets an ordinary exposure improves)
    'quick_long_ps': 0.0,  # quick_long only while the pool is not shrunk for the time budget (pool_scale >= this):
                           #    the extra pool members cost planning time that a budget-bound run cannot spare
    'log_faults': 0,       # 1: read the handover log some cards put in observation requests (log_reader.py) and report
                           #    an instrument fault the log announces (engineering works on the guide camera at a given
                           #    time) or confirms (throughput fell, not the sky, call engineering) without waiting for
                           #    the efficiency evidence -- an earthquake at the same time can hide the drop for days
    'log_delay': 1200.0,   # report an announced fault this long after its announced start (s)
    'log_retry': 5400.0,   # a false report on an announced fault is retried once this long after the start (s)
    'log_false_max': 3,    # stop log-driven reports after this many of them were false (the log is not understood)
    'log_occ_win': 108000.0,  # a confirmed fault without a time: skip it if a report was correct this recently (s)
    'log_stale': 864000.0,    # forget a logged fault not reported this long after it was due (s)
    'log_llm': 0,          # 1: log lines that look fault-related but match no parser pattern go to the language model
                           #    (llm_strategist.LogAnalyst); its items count only if their quote occurs in the log and
                           #    an announced time also occurs in that quote; one false report switches it off
    'log_llm_calls': 40,   # at most this many log questions per run
    'anchor_sep': 0.3,     # minimum anchor spacing as a fraction of the field width (0.3 keeps at least one fibre
                           #    pitch; smaller values allow closer anchors, 0 none): on crowded cards with sparse fibre
                           #    fill the best field is often anchored on a lower-ranked target near a better one
    'guider': 0,           # 1: read guider-camera jobs and flat-lamp tests from the log (guider_log.GuiderLog): report a
                           #    stated job g_delay s after its time, probe unsure / rain-postponed times with a short
                           #    exposure, wait out the flat-lamp windows, keep fault / test data out of the belief, and
                           #    report a run of near-zero throughput that no test window explains
    'g_delay': 120.0,      # report a stated guider job this long after its time (s)
    'g_blind': 1,          # report an uncertain guider time (rain postponement, relative to another job, model only)
                           # once at its time while fewer than this many false reports were made since the last
                           # correct one (they are free up to the scoring allowance); the probe still watches after
    'g_blind_win': 72000.0,  # ... but only this soon after the candidate time (s)
    'zf': 1,               # 1: a field that scored zero everywhere while the site was open (an unannounced sector
                           #    closure, e.g. wind, or unknown terrain) is avoided for a while: near its azimuth and up
                           #    to zf_up deg above it the expected throughput is scaled by zf_conf once confirmed (a
                           #    field >= zf_sep deg away scored within zf_win s, in the same weather slot or after a
                           #    second zero there in another slot); not yet confirmed, by zf_unconf at any altitude
    'zf_hours': 2.0,       # confirmed zero fields are avoided this long (h); unconfirmed ones zf_hours / 3
    'zf_az': 20.0,         # azimuth half-width of the avoided zone (deg) ...
    'zf_az_closure': 35.0,   # ... and of a confirmed sector closure (wind closes 90-135 deg wide sectors)
    'zf_up': 3.0,          # the zone reaches this far above the zero field (deg) when terrain may explain it ...
    'zf_closure_alt': 52.0,  # ... but all altitudes when the zero cannot be terrain: the field was this high, or
                           #    that azimuth scored lower down before (a sector closure, e.g. wind)
    'log_sector': 1,       # 1: a direction the duty log says will be closed (wind etc.; read by the model, code words
                           #    included) is avoided like an announced rocket-launch closure, from 20 min before
                           #    the written start to its end; whole-site closures stay with the weather logic
    'zf_conf': 0.05,
    'zf_unconf': 0.5,
    'zf_sep': 30.0,
    'zf_win': 1200.0,
    'g_probe_T': 120,      # exposure cap while probing a candidate time or watching near-zero data (s)
    'g_low': 0.6,          # probe: throughput ratio below this confirms the job
    'g_low_llm': 0.5,      # the same for a time only the language model reported (precursors, code words: be stricter)
    'g_dead': 0.03,        # throughput ratio below this is 'dead' (a guider fault past its first hour, or a test;
                           # thick cloud leaves 0.03-0.1, a fault ~0.005)
    'g_step': 0.6,         # probe: the drop must also be this deep against the hour before the candidate time
    'g_many_correct': 7,   # this many correct reports mark a fault-rich card even if its log says nothing
                           # (the original cards had at most 6 faults a season; the belief caps at 8)
    'g_dead_wait': 2100.0, # with no free false report left, report dead data only after it lasted this long (s)
    'duty_llm': 0,         # 1: a language model reads every duty-log section when it arrives (llm_strategist.DutyReader,
                           #    synchronous: waiting for the model does not count against the CPU budget); its fault
                           #    times are cross-checked with guider_log and confirmed on the throughput before a report
    'duty_wall': 2700.0,   # real seconds the duty-log model may take in total on one card
    'duty_calls': 400,     # model questions the duty log may take on one card (a long log is read to the end)
    'real_cap': 7200.0,    # the card's real-time safety limit (s); no model question starts close to it
    'ev_wide': 0.0,        # >0: prior sd floor of an announced all-sky event's log effect (the event multipliers are
                           #    card parameters), shrinking with the episodes seen; its mean is learned across episodes
    'sector_freeze': 0,    # 1: no fault evidence while an announced directional weather event is in force (its
                           #    width and height are card parameters, so 'unaffected' targets may be affected)
    'quake_tau': 0,        # 1: learn the earthquake recovery time (decay_nights, a hidden card parameter; reference 4)
                           #    from the efficiency on the nights after each shock instead of assuming 4 nights
    'ev_excuse': 0,        # 1: no fault report while an announced weather event that began with the efficiency drop
                           #    is still active (event effects are card parameters; a fault outlasts the event)
    'off_search': 0,       # 1: when nearly every assigned target misses its fibre (a pointing offset beyond the
                           #    fitted range), test many offset hypotheses per short exposure over the full legal
                           #    range (|offset| < 0.1 rad), one hypothesis per group of fibres
    'unif_bonus': 0.0,     # >0: add the RA-band uniformity term to target values (scale x marginal penalty reduction)
    'rep_cost_scale': 0,   # 1: the cap on penalised fault reports scales with 150 / |false_penalty|, their evidence
                           #    streak with |false_penalty| / 150 (at most x4)
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
D0_GRID_WIDE = np.concatenate((D0_GRID, [0.97, 0.985, 0.995]))   # quake_tau: shocks that also hit the sky
TAU_GRID = np.array([1.5, 2.0, 3.0, 4.0, 5.5, 7.5, 10.0, 14.0, 20.0])
TAU_LW0 = -0.5 * (np.log(TAU_GRID / 4.0) / 0.6) ** 2      # prior: the reference 4 nights, x/1.8
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
        self.tau_learn = False
        self.tau_lw = TAU_LW0.copy()
        self.d0_grid = D0_GRID
        self.ev_sd_floor = 0.0         # >0: ev_wide
        self.ev_sum = {k: 0.0 for k in EV_KEYS}
        self.ev_cnt = {k: 0 for k in EV_KEYS}
        self.nu = deque(maxlen=300)    # normalised innovations of the most probable branch
        self.nu_ref = 0.0              # >0: adapt the process noise to their median (wx_adapt)
        self.noise_f = 1.0
        self.sn2_0, self.ss2_0 = self.sn2, self.ss2
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

    def ev_prior(self, key):
        """(mean, sd) of an announced all-sky event's log effect: the generator reference, or (ev_wide) a wide prior
        whose mean is pooled with the effects learned in earlier episodes."""
        m0, s0 = EV_PRIOR[key]
        if self.ev_sd_floor <= 0:
            return m0, s0
        n = self.ev_cnt[key]
        m = (m0 + self.ev_sum[key]) / (1.0 + n)
        # episodes differ in severity: a learned effect far from the reference keeps a proportionally wide prior
        return m, max(s0, self.ev_sd_floor / math.sqrt(1.0 + n), 0.3 * abs(m - m0))

    def _set_events(self, act):
        for j, key in enumerate(EV_KEYS):
            c = 3 + j
            on = act[j] > 0
            if on and not self.ev_on[j]:
                m0, s0 = self.ev_prior(key)
                self.x[:, c] = m0
                self.P[:, c, :] = 0.0
                self.P[:, :, c] = 0.0
                self.P[:, c, c] = s0 ** 2
                self.ev_sd0 = getattr(self, 'ev_sd0', {})
                self.ev_sd0[key] = s0
            elif not on and self.ev_on[j]:
                if self.ev_sd_floor > 0:
                    k = int(np.argmax(self.w))
                    s0 = getattr(self, 'ev_sd0', {}).get(key, EV_PRIOR[key][1])
                    if self.P[k, c, c] < 0.25 * s0 * s0:
                        # the episode's effect was measured: pool it into the next episode's prior mean
                        self.ev_sum[key] += float(self.x[k, c])
                        self.ev_cnt[key] += 1
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
        lw = np.zeros(len(self.d0_grid))
        self.quakes.append({'t': t, 'night': night, 'lw': lw})

    def _d0_hat(self, q):
        w = np.exp(q['lw'] - q['lw'].max())
        return float(np.sum(w * self.d0_grid) / w.sum())

    def tau_hat(self):
        if not self.tau_learn:
            return 4.0
        w = np.exp(self.tau_lw - self.tau_lw.max())
        return float(np.exp(np.sum(w * np.log(TAU_GRID)) / w.sum()))

    def quake_factor(self, start, T, night, override=None, tau=None):
        """Exposure-average efficiency factor of all known quakes; override=(quake, d0) for one quake."""
        f = 1.0
        end = start + T
        tau = self.tau_hat() if tau is None else tau
        for q in self.quakes:
            if end <= q['t'] or night < q['night']:
                continue
            d0 = override[1] if override is not None and override[0] is q else self._d0_hat(q)
            frac = min(1.0, (end - max(start, q['t'])) / max(1.0, T))
            f *= 1.0 - frac * d0 * math.exp(-(night - q['night']) / tau)
        return max(0.003 if self.tau_learn else 0.03, f)

    def learning_quake(self, night):
        """Fault evidence is frozen while a fresh shock's degradation is still being learned (with tau learning: the
        shock night and the whole next night, which first shows the recovery rate)."""
        for q in self.quakes:
            if night == q['night'] or (night == q['night'] + 1 and (q.get('n', 0) < 3 or self.tau_learn)):
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
                               for d in self.d0_grid])
                ll = self._loglik(X, le, lk0, lH, ly, P, lom, lwo)
                lp = -0.5 * (X - mx[kmap]) ** 2 / vx[kmap]
                lz = ll + lp[None, :]
                mm = lz.max(axis=1, keepdims=True)
                q['lw'] = q['lw'] + (mm[:, 0] + np.log(np.exp(lz - mm).sum(axis=1)))
                q['lw'] -= q['lw'].max()
                q['n'] = q.get('n', 0) + 1
        if self.tau_learn and any(1 <= night - q['night'] <= 30 and q.get('n', 0) >= 3 for q in self.quakes):
            # recovery time: the shocks' learned strengths fix the first nights, the following nights the decay
            le = np.array([self.leta + self.lmu[kmap] + math.log(self.quake_factor(start, T, night, tau=tc))
                           for tc in TAU_GRID])
            ll = self._loglik(X, le, lk0, lH, ly, P, lom, lwo)
            lp = -0.5 * (X - mx[kmap]) ** 2 / vx[kmap]
            lz = ll + lp[None, :]
            mm = lz.max(axis=1, keepdims=True)
            self.tau_lw = self.tau_lw + 0.3 * (mm[:, 0] + np.log(np.exp(lz - mm).sum(axis=1)))
            self.tau_lw -= self.tau_lw.max()
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
        kb0 = int(np.argmax(self.w))
        if pvar[kb0] < vx[kb0] * 0.995:
            R0 = 1.0 / (1.0 / pvar[kb0] - 1.0 / vx[kb0])
            z0 = R0 * (pmean[kb0] / pvar[kb0] - mx[kb0] / vx[kb0])
            self.nu.append(min(25.0, (z0 - mx[kb0]) ** 2 / (vx[kb0] + R0)))
            if len(self.nu) >= 100 and self.n_upd % 25 == 0:
                med = float(np.median(self.nu))
                if self.nu_ref > 0:
                    fn = float(np.clip(med / self.nu_ref, 1.0, 8.0))
                    self.noise_f = 0.7 * self.noise_f + 0.3 * fn
                    self.sn2, self.ss2 = self.sn2_0 * self.noise_f, self.ss2_0 * self.noise_f
                if os.environ.get('OBS2_DEBUG_NU') or (self.n_upd % 400 == 0):
                    _log({'event': 'nu', 'med': round(med, 3), 'f': round(self.noise_f, 2), 'n': self.n_upd})
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
                a = act[j] if self.ev_sd_floor > 0 else 1.0     # ev_wide: overlapping events of one kind compound
                if self.ev_on[j]:
                    c = 3 + j
                    mean += a * x[0, c]
                    var += a * a * P[0, c, c] + 2 * a * (P[0, c, 0] + P[0, c, 1] + P[0, c, 2])
                else:
                    m0, s0 = self.ev_prior(key)
                    mean += a * m0
                    var += (a * s0) ** 2
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
        self.mult_max = float(np.max(self.mult))   # best attainable program multiplier (DARK on the standard cards)
        rq = sc.get('required', {})
        self.req_pen = float(rq.get('penalty_per_missing', 50))
        self.req_thr = float(rq.get('observed_factor_threshold', 0.5))
        rep = sc.get('reporting', {})
        self.free_reports = int(rep.get('false_report_free_allowance', 2))
        self.max_consec = int(rep.get('max_consecutive_reports', 32))
        try:
            self.false_pen = abs(float(rep.get('false_penalty', -150)))
        except (TypeError, ValueError):
            self.false_pen = 150.0
        un = sc.get('uniformity', {}) or {}
        try:
            self.unif_w = max(0.0, float(un.get('weight', 0.0)))
            self.unif_bw = max(1e-3, float(un.get('ra_band_width_deg', 10.0)))
            self.unif_thr = min(1.0, max(1e-3, float(un.get('observed_factor_threshold', 0.5))))
        except (TypeError, ValueError):
            self.unif_w, self.unif_bw, self.unif_thr = 0.0, 10.0, 0.5
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
        # RA bands of the uniformity term (the scorer bins every catalogue target by floor(ra / width))
        self.unif_band = np.floor(self.ra / self.unif_bw).astype(int)
        self.unif_band -= int(self.unif_band.min()) if self.n else 0
        self.unif_cnt = np.bincount(self.unif_band).astype(float) if self.n else np.zeros(1)
        # state
        self.best = np.zeros(self.n)          # realised best score
        self.gl = np.zeros(self.n)            # lower bound on max raw factor
        self.ledger = []                      # list of (observe_index, idx, score, g_lower)
        self.pending = None
        self.req_done_ids = set()
        self.terrain_dirs = set()
        self.blocked = []                     # (time, alt, az, kind)
        self.zfields = []                     # all-zero fields: [time, alt, az, confirmed]
        self.last_closed_until = -1e18          # (not -1: seasons before 1970 have negative timestamps)
        # weather / instrument belief
        self.eta_nom = 0.95
        self.mseason = np.array([self._season_mean(a) for a, _ in self.nights] + [0.0])
        self.bel = Belief(self.nights, self.slot, self.q0, self.f0t0, self.mult, self.mismatch, self.band_dark,
                          self.band_bright, self.mseason, eta_nom=self.eta_nom, infl=self.p['wx_infl'],
                          p_window=self.p['fault_window_mass'])
        self.bel.absorb_false = bool(self.p['false_absorb'])
        self.bel.tau_learn = bool(self.p['quake_tau'])
        if self.bel.tau_learn:
            self.bel.d0_grid = D0_GRID_WIDE
        self.bel.nu_ref = float(self.p['wx_adapt'])
        self.bel.ev_sd_floor = float(self.p['ev_wide'])
        self.upd_at_false = -10 ** 9
        self.stress_seen = False
        if self.p['fault_counts']:
            self.bel.set_fault_prior(self.p['fault_counts'])
        self.logZ_mean = float(self.mseason[0])
        self.probe = 0                        # >0: short probe exposures after a closure
        self.zero_pending = []
        self.thmax = {d: 50.0 for d in DIR_AZ}  # learned terrain top per announced direction (prior 50 deg)
        self.probe_fail = 0
        self.pf_prev = 0.0
        self.bul_t = 0.0
        self.quake_notice = False
        self.drop_t = None
        self.ev_onset = {}                      # (kind, direction) -> [onset_lo, onset_hi, end or None]
        self.prev_decide_t = None
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
        self.off_c = (0.0, 0.0)                 # centre of the fine offset grid
        self.off_hist = deque(maxlen=2000)      # (cmd_alt, cmd_az, tv, fib, hit) of recent calibrations
        self.offw_alt = self.offw_az = self.offw_ll = None
        self.offw_n = 0
        self.hitrec = deque(maxlen=12)          # (assigned, hit) of recent observes
        self.off_big = False                    # the wide grid spans the full legal offset range
        self.searches = 0
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
        # engine-time model: steps x a + k x (requests checked x ledger records), fitted from the real time
        # between our turns; S holds the forgetting sums [n2, nX, X2, n dt, X dt] (seeded with a weak prior)
        self.rq_seen = set()
        self.n_entries = 0
        self._eng = {'wr': None, 'tau': 0.0, 'chunks': 0, 'n': 0,
                     'S': np.array([40.0, 4.0e7, 8.0e13, 40.0 * 0.03 + 4.0e7 * 1.5e-7, 4.0e7 * 0.03 + 8.0e13 * 1.5e-7])}
        self._eng_obsT = deque(maxlen=400)
        self._eng_wait = deque(maxlen=400)
        self._eng_tobs, self._eng_twait = 0.0, 0.0
        self._eng_hits = 12.0
        self._eng_level = 0
        self.eng_floor, self.eng_wait_k = 0.0, 1
        self._eng_left = None
        self._eng_err = False
        self._probe_now = False
        self._eng_hist = []          # (dark fraction elapsed, records, observes) every 25 decisions
        self._eng_nwait = 0          # in-night wait steps so far
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
        self.sprobe = None
        if (self.p.get('sophon_probe', 0) > 0 and sophon_probe is not None
                and os.environ.get('SOPHON_RUN_TOKEN')):
            try:
                self.sprobe = sophon_probe.Probe(init, self)
            except Exception:
                self.sprobe = None
        # handover log: faults it announces or confirms
        self.logr = None
        self.log_q = []
        self.log_false = 0
        self.log_err = False
        self.last_correct_t = -1e18
        self.log_llm = None
        self.log_llm_meta = {}
        self.log_llm_off = False
        self.glog = None
        self.g_done = set()           # guider candidate keys handled (reported or dismissed)
        self.g_probe = {}             # key -> candidate being probed (time passed, no verdict yet)
        self.g_blind = set()          # uncertain candidate keys already reported once without looking
        self.g_report = None          # report requested by the probe / dead-data check
        self.g_dead_since = None
        self.g_dead_hold = -1e18      # no dead-data report before this time (after a false one)
        self.g_dead_false = 0         # false dead-data reports since the last correct report (the hold doubles)
        self.g_dead_n = 0             # consecutive near-zero exposures (an all-zero closure exposure resets it)
        self.g_hist = []              # recent (start, end, ratio) of exposures outside known test windows
        self.g_correct = 0
        self.g_false = 0
        self.g_err = False
        self.g_skip = 0
        self.dlm = None
        self.t_real0 = time.monotonic()
        if self.p['log_faults'] > 0:
            try:
                from log_reader import LogReader
                self.logr = LogReader(float(site.get('utc_offset_hours', 0.0) or 0.0),
                                      float(self.night_starts[0]) if len(self.night_starts) else None, self.survey_end)
                self.log_off_s = float(site.get('utc_offset_hours', 0.0) or 0.0) * 3600.0
                if self.p['guider'] > 0:
                    from guider_log import GuiderLog
                    self.glog = GuiderLog(float(site.get('utc_offset_hours', 0.0) or 0.0),
                                          float(self.night_starts[0]) if len(self.night_starts) else None,
                                          self.survey_end)
                    self.glog.sun_cb = self._sun_event
                    self.logr.skip_new = True
                    if self.p['duty_llm'] > 0:
                        from llm_strategist import DutyReader
                        self.dlm = DutyReader(wall_cap=float(self.p['duty_wall']), max_calls=int(self.p['duty_calls']))
                        if not self.dlm.enabled:
                            self.dlm = None
                if self.p['log_llm'] > 0:
                    from llm_strategist import LogAnalyst
                    self.log_llm = LogAnalyst(max_calls=int(self.p['log_llm_calls']))
                    if not self.log_llm.enabled:
                        self.log_llm = None
            except Exception:
                import traceback
                traceback.print_exc(file=sys.stderr)
                self.logr = None
                self.log_llm = None
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

    def _vis_hours(self, a, b, idx):
        """Hours in [a, b_i] (per-target end times) that each target spends above the altitude limit."""
        sd, cd, ra, tr = self.sdec[idx], self.cdec[idx], self.ra[idx], self.transit_alt[idx]
        c = (np.sin((self.min_alt + 1.0) * DEG) - self.sin_lat * sd) / np.maximum(self.cos_lat * cd, 1e-9)
        hau = np.where(c <= -1.0, 180.0, np.where(c >= 1.0, 0.0, np.arccos(np.clip(c, -1.0, 1.0)) / DEG))
        hau = np.where(tr < self.min_alt + 1.0, 0.0, hau)
        ha0 = (lst_deg(a, self.lon) - ra + 180.0) % 360.0 - 180.0
        span = SID * np.maximum(0.0, b - a) / 86400.0
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
        pb = np.zeros(len(alt))
        for d in self.terrain_dirs:
            if d in DIR_AZ:
                pb = np.maximum(pb, self._dir_prob(az, d, self._tab_terrain) * np.clip((self.thmax[d] - alt) / 15.0, 0.0, 1.0))
        pb = np.where(alt >= self.tclear[azb] - 0.5, 0.0, pb)
        pb = np.where(alt <= self.tblock[azb] + 0.5, 1.0, pb)
        return pb

    def _terrain_pb2d(self, alts, az):
        """_terrain_pb for an (samples x n) altitude array at fixed per-target azimuths."""
        self._init_tables()
        if not self.terrain_dirs:
            return np.zeros_like(alts)
        azb = np.floor(az).astype(int) % 360
        pb = np.zeros_like(alts)
        for d in self.terrain_dirs:
            if d in DIR_AZ:
                pb = np.maximum(pb, self._dir_prob(az, d, self._tab_terrain)[None, :]
                                * np.clip((self.thmax[d] - alts) / 15.0, 0.0, 1.0))
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
        if self.p['zf'] > 0 and self.zfields:
            life = self.p['zf_hours'] * 3600.0
            keep = []
            for z in self.zfields:
                age = t - z[0]
                if age < (life if z[3] else life / 3.0):
                    keep.append(z)
                    da = np.abs((az - z[2] + 180.0) % 360.0 - 180.0)
                    # not yet confirmed: steer the next probes to another direction at any altitude
                    top = (91.0 if z[6] else z[1] + self.p['zf_up']) if z[3] else 91.0
                    wz = self.p['zf_az_closure'] if (z[3] and z[6]) else self.p['zf_az']
                    f *= np.where((da <= wz) & (alt <= top),
                                  self.p['zf_conf'] if z[3] else self.p['zf_unconf'], 1.0)
                elif age < life:
                    keep.append(z)          # kept for a late confirmation; it no longer steers
            self.zfields = keep[-60:]
        return f

    def _zf_update(self, now, calt, caz, all_zero, scored_az, s0, s1):
        """Book an all-zero field; a scoring field clears the zero fields in its own direction and confirms one in
        another direction when it shows that the site was open then: it scored inside the same weather slot (an
        unannounced closure of the whole site lasts whole slots), or that direction scored zero in two different
        slots. Confirmed fields are avoided (_directional_factor)."""
        if self.p['zf'] <= 0 or calt is None or caz is None:
            return
        if all_zero:
            closure = calt >= self.p['zf_closure_alt']
            if not closure and hasattr(self, 'tclear'):
                b = int(math.floor(float(caz))) % 360
                closure = min(float(self.tclear[(b + k) % 360]) for k in (-1, 0, 1)) < float(calt) - 1.0
            self.zfields.append([now, float(calt), float(caz) % 360.0, False, int(s0), int(s1), bool(closure)])
            return
        if not self.zfields:
            return
        sep, win, wz = self.p['zf_sep'], self.p['zf_win'], self.p['zf_az']

        def apart(a, b):
            return abs((a - b + 180.0) % 360.0 - 180.0)
        keep = []
        for z in self.zfields:
            da = apart(float(caz), z[2])
            own = any(apart(a, z[2]) <= wz for a in scored_az)
            if da <= wz * 0.5 or (own and da <= wz):
                continue                    # this direction scores again
            keep.append(z)
        self.zfields = keep
        life = self.p['zf_hours'] * 3600.0
        for z in self.zfields:
            if z[3] or apart(float(caz), z[2]) < sep or now - z[0] > win:
                continue
            same_slot = s0 == s1 and z[4] <= s0 <= z[5]
            twice = any(y is not z and apart(y[2], z[2]) <= wz and (y[5] < z[4] or y[4] > z[5]) and abs(y[0] - z[0]) <= life
                        for y in self.zfields)
            # zeros in two directions far apart at about the same time: the whole site was closed then
            wide = any(y is not z and not y[3] and abs(y[0] - z[0]) <= win and apart(y[2], z[2]) >= sep
                       for y in self.zfields)
            if same_slot or (twice and not wide):
                z[3] = True
                self.zf_conf_n = getattr(self, 'zf_conf_n', 0) + 1
                if self.zf_conf_n <= 60:
                    _log({'event': 'zf', 't': fmt_utc(now), 'alt': round(z[1], 1), 'az': round(z[2], 1),
                          'by': round(float(caz), 1), 'slot': bool(same_slot), 'closure': z[6]})

    def _zf_same_dir(self, now, az):
        """All recent unconfirmed zero fields (before the latest one) lie in the direction az: a failed high probe
        there does not show a closed site."""
        if self.p['zf'] <= 0 or az is None:
            return False
        prev = [z for z in self.zfields[:-1] if not z[3] and now - z[0] <= self.p['zf_win']]
        return bool(prev) and all(abs((float(az) - z[2] + 180.0) % 360.0 - 180.0) <= self.p['zf_az'] for z in prev)

    def _learn_terrain(self, alt, az, scored, force=False):
        """Update the static terrain map from one hit: scored>0 -> clear at (az, >=alt); 0 -> blocked at (az, <=alt).
        force: a zero that only terrain explains (open site, no announced closing event there), at any altitude."""
        if not hasattr(self, 'tclear'):
            return
        b = int(math.floor(az)) % 360
        if scored:
            for k in range(-1, 2):
                j = (b + k) % 360
                self.tclear[j] = min(self.tclear[j], alt)
        else:
            if alt < 55.0 or force:
                self.tblock[b] = max(self.tblock[b], alt)
            if force:
                for d in self.terrain_dirs:
                    if d in DIR_AZ and float(self._dir_prob(np.array([az]), d, self._tab_terrain)[0]) >= 0.5:
                        self.thmax[d] = max(self.thmax[d], min(89.0, alt + 2.0))

    def _terr_away(self, alt, az):
        """(alt, az) lies outside the announced terrain directions or above their learned height."""
        self._init_tables()
        for d in self.terrain_dirs:
            if d in DIR_AZ and float(self._dir_prob(np.array([az]), d, self._tab_terrain)[0]) >= 0.3 \
                    and alt < self.thmax[d] + 3.0:
                return False
        return True

    def _terr_away_vec(self, alts, azs):
        self._init_tables()
        ok = np.ones(len(alts), dtype=bool)
        for d in self.terrain_dirs:
            if d in DIR_AZ:
                ok &= ~((self._dir_prob(azs, d, self._tab_terrain) >= 0.3) & (alts < self.thmax[d] + 3.0))
        return ok

    @staticmethod
    def _zero_event(az, notices):
        """An announced event that zeroes targets (rocket launch, rain, storm) may cover azimuth az."""
        for n in notices:
            if n.get('event_kind') in ('rocket_launch', 'rocket', 'rain', 'storm', 'rainy', 'tornado'):
                d = n.get('direction')
                if d not in DIR_AZ or abs((az - DIR_AZ[d] + 180.0) % 360.0 - 180.0) <= 100.0:
                    return True
        return False

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
            gq = pend.get('guider') if pend else None
            if gq is not None:
                self._g_outcome(gq, bool(res.get('correct')), now)
                self.pf_prev = 0.0
                _log({'event': 'report_result', 'correct': res.get('correct'), 't': fmt_utc(now), 'g': gq.get('why')})
                return
            lq = pend.get('log') if pend else None
            if lq is not None:
                self._log_outcome(lq, bool(res.get('correct')), now)
            if res.get('correct'):
                self.correct_reports += 1
                self.false_since_correct = 0
                self.last_correct_t = now
                onset = lq['t'] if lq is not None and lq['t'] is not None else None
                self.bel.fault_found(onset if onset else (self.drop_t if self.drop_t else now), now)
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
        if self.sprobe is not None:
            try:
                self.sprobe.on_result(pend, hits, self._night_index(start), fmt_utc(start))
            except Exception:
                pass
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
        th = self.p['terr_hi'] > 0
        notes = list(pend.get('notices', []) or []) + list((snap.get('latest_bulletin') or {}).get('notices', []) or [])
        s0, s1 = int(start // self.slot), int((start + T - 1e-6) // self.slot)
        try:
            self._zf_update(now, pend.get('calt'), pend.get('caz'), bool(np.all(zero)),
                            [float(amap[int(i)][1]) for i, z in zip(idx, zero) if not z and int(i) in amap], s0, s1)
        except Exception:
            pass
        if np.all(zero):
            self.g_dead_n = 0           # a closed site, not an instrument fault
            self.g_dead_since = None
            if len(idx) >= 1:
                high = all(amap.get(int(i), (90, 0))[0] >= 55.0 for i in idx)
                away = (not th) or self.probe_fail >= 2 or all(self._terr_away(*amap[int(i)]) for i in idx if int(i) in amap)
                if self.probe > 0 and high and away and not self._zf_same_dir(now, pend.get('caz')):
                    # a high-altitude probe (away from the announced terrain) also failed: the site is closed
                    self.last_closed_until = (math.floor(now / self.slot) + 1) * self.slot
                    self.zero_pending = []
                    self.probe = 2
                    self.probe_fail = 0
                    self.zfields = [z for z in self.zfields if z[3]]   # the recent zeros were the closed site
                else:
                    if self.probe > 0:
                        self.probe_fail += 1
                    new = [(amap[int(i)][0], amap[int(i)][1], s0, s1, int(i)) for i in idx if int(i) in amap]
                    self.zero_pending = (self.zero_pending + new)[-300:] if th else new
                    self.probe = 2
            return
        self.probe_fail = 0
        if self.zero_pending:
            # the site is open: the previous all-zero field was obstructed terrain
            for (a0, z0, p0, p1, i0) in self.zero_pending:
                if a0 < 52.0:
                    self._learn_terrain(a0, z0, False)
                elif th and p0 <= s1 and s0 <= p1 and self.w[i0] * self.flux[i0] > 0 and not self._zero_event(z0, notes):
                    # open within the same weather slot: only terrain explains those zeros
                    self._learn_terrain(a0, z0, False, force=True)
            self.zero_pending = []
        if self.probe > 0:
            self.probe = 0
        for i, zflag in zip(idx, zero):
            a, z = amap.get(int(i), (None, None))
            if a is None:
                continue
            force = th and bool(zflag) and self.w[i] * self.flux[i] > 0 and not self._zero_event(z, notes)
            self._learn_terrain(a, z, not zflag, force=force)
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
        if self.glog is not None and (self.glog.active or self.glog.flats or self._g_many()):
            try:
                if self._guider_obs(start, T, now, night, idx[sel], y[sel], H, P, act):
                    return          # guider-fault or flat-lamp data: keep it out of the belief
            except Exception:
                if not self.g_err:
                    self.g_err = True
                    import traceback
                    traceback.print_exc(file=sys.stderr)
        omegas, wprior = self._omega_options(start, T)
        freeze = self.bel.learning_quake(night)
        if self.p['sector_freeze'] > 0 and not freeze:
            # a directional weather event of unknown extent may affect the 'unaffected' targets
            for n_ in list(pend.get('notices', []) or []) + list((snap.get('latest_bulletin') or {}).get('notices', []) or []):
                if n_.get('event_kind') in WEATHER_KINDS and n_.get('direction') in DIR_AZ:
                    freeze = True
                    break
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
        # overlapping events of one kind compound (multiplicative truth -> additive log effect)
        return [min(3.0 if self.p['ev_wide'] > 0 else 1.0, v) for v in act]

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
        self.hitrec.append((len(hitv), int(hitv.sum())))
        if self.off_confident and np.all(hitv == 1):
            return
        tv = pend['tv']
        fib = pend['fib']
        if self.p['off_wide'] > 0:
            self.off_hist.append((pend['cmd_alt'], pend['cmd_az'], tv, fib, hitv))
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
        if self.p['off_wide'] > 0:
            self._calib_wide(pend, tv, fib, hitv)
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

    def _offset_ll(self, oalt, oaz, last=300):
        """Log-likelihood of each candidate offset over the most recent stored calibrations."""
        ll = np.zeros(len(oalt))
        hist = list(self.off_hist)[-last:]
        for ca, cz, tv, fib, hit in hist:
            ag = self.kern.offset_agree(oalt, oaz, ca, cz, tv, fib, hit, self.side, self.pitch)
            ll += -2.5 * (len(hit) - ag)
        return ll

    def _calib_wide(self, pend, tv, fib, hitv):
        """Coarse offset fit over max(0.5 deg, off_wide x pitch): when its best fit lies outside the fine grid and
        is clearly better than the fit near the current estimate, move the fine grid there (the reference stress
        config draws offsets within +-0.11 deg, but the bound is a card parameter)."""
        if self.offw_ll is None:
            R = max(0.5, float(self.p['off_wide']) * self.pitch)
            g = np.linspace(-R, R, 41)
            self.offw_alt, self.offw_az = [a.ravel() for a in np.meshgrid(g, g, indexing='ij')]
            self.offw_ll = self._offset_ll(self.offw_alt, self.offw_az)
        else:
            ag = self.kern.offset_agree(self.offw_alt, self.offw_az, pend['cmd_alt'], pend['cmd_az'], tv, fib, hitv,
                                        self.side, self.pitch)
            self.offw_ll += -2.5 * (len(hitv) - ag)
        self.offw_n += 1
        if self.offw_n % 4 != 1 and not self.off_big:
            return
        sc = self.offw_ll
        if self.off_big:
            sc = sc - 1e-3 * np.hypot(self.offw_alt, self.offw_az)   # untested ties: the smallest offset first
        bw = int(np.argmax(sc))
        wa, wz = float(self.offw_alt[bw]), float(self.offw_az[bw])
        ea, ez = self.off_est
        kn = int(np.argmin((self.offw_alt - ea) ** 2 + (self.offw_az - ez) ** 2))
        ca, cz = self.off_c
        thr = 4.0 if self.off_big else 6.0
        if (abs(wa - ca) > 0.12 or abs(wz - cz) > 0.12) and self.offw_ll[bw] > self.offw_ll[kn] + thr:
            self._move_fine(round(wa, 3), round(wz, 3), float(self.offw_ll[bw] - self.offw_ll[kn]))

    def _move_fine(self, ca, cz, gain):
        """Re-centre the fine offset grid (+-0.16 deg, or +-0.6 cell pitch after a full-range search)."""
        S = max(0.16, 0.6 * self.pitch) if self.off_big else 0.16
        g = np.linspace(-S, S, 33)
        oa, oz = [a.ravel() for a in np.meshgrid(ca + g, cz + g, indexing='ij')]
        self.off_alt, self.off_az, self.off_c = oa, oz, (ca, cz)
        self.off_ll = self._offset_ll(oa, oz)
        self.off_confident = False
        _log({'event': 'calib_move', 'centre': [ca, cz], 'gain': round(gain, 1), 'obs': self.off_obs})

    def _lost(self):
        """Nearly every recently assigned target missed its fibre: the offset lies outside the fitted range."""
        if self.misses_total == 0 or len(self.hitrec) < 4:
            return False
        rec = list(self.hitrec)[-6:]
        na = sum(a for a, _ in rec)
        nh = sum(h for _, h in rec)
        if na < min(12, 4 * self.nfib) or nh > 0.05 * na:
            return False
        if self.off_big and nh > 0:
            ll = self.offw_ll
            near = ll >= ll.max() - 1.0
            if np.count_nonzero(near) <= 36 and max(np.ptp(self.offw_alt[near]), np.ptp(self.offw_az[near])) <= 1.5 * self.pitch:
                # the hits pin the offset down: resume normal pointing with the fine grid there
                wa, wz = float(np.mean(self.offw_alt[near])), float(np.mean(self.offw_az[near]))
                if max(abs(wa - self.off_c[0]), abs(wz - self.off_c[1])) > 0.25 * self.pitch:
                    self._move_fine(round(wa, 3), round(wz, 3), float(ll.max() - np.median(ll)))
                self.hitrec.clear()
                _log({'event': 'offset_found', 'centre': [round(wa, 3), round(wz, 3)], 'searches': self.searches})
                return False
        return True

    def _offset_search(self, now, left, tvall, altall, notices):
        """Lost pointing: one short exposure whose fibre pairs each test a different offset hypothesis (actual
        centre = commanded + offset), drawn from the untested part of the full legal range, smallest first."""
        if not self.off_big:
            R = math.degrees(0.1) + 0.05
            step = max(0.5 * self.pitch, 2.0 * R / 120.0)
            K = int(math.ceil(R / step))
            g = step * np.arange(-K, K + 1)
            self.offw_alt, self.offw_az = [a.ravel() for a in np.meshgrid(g, g, indexing='ij')]
            self.offw_ll = self._offset_ll(self.offw_alt, self.offw_az)
            self.off_big = True
            _log({'event': 'offset_search', 't': fmt_utc(now), 'grid': len(g), 'step': round(step, 4)})
        T = int(min(self.tmax, max(self.tmin, 60), int(left)))
        if T < self.tmin:
            return None
        vis = np.flatnonzero(altall >= self.min_alt + 1.0)
        if len(vis) < 2:
            return None
        pool = vis[self.best[vis] < self.w[vis] * self.mult_max * 0.999]
        if len(pool) < max(2, self.nfib):
            pool = vis
        tv = np.ascontiguousarray(tvall[pool])
        alt_p = altall[pool]
        # hypotheses: untested (maximum-likelihood) offsets, smallest first, at least ~one cell apart
        ll = self.offw_ll
        cand = np.flatnonzero(ll >= float(ll.max()) - 1.0)
        cand = cand[np.argsort(np.hypot(self.offw_alt[cand], self.offw_az[cand]), kind='stable')]
        fpm = 2 if self.nfib >= 4 else 1
        M = max(1, self.nfib // fpm)
        sep = 0.9 * self.pitch
        H = np.zeros((0, 2))
        for k in cand:
            h = np.array([self.offw_alt[k], self.offw_az[k]])
            if len(H) == 0 or np.min(np.max(np.abs(H - h), axis=1)) >= sep:
                H = np.vstack([H, h])
                if len(H) >= 3 * M:
                    break
        # commanded pointing: the densest of a few visible targets, low enough for the hypotheses to stay below 90
        rng = np.random.default_rng(self.searches + 7)
        bidx = rng.choice(len(pool), min(40, len(pool)), replace=False)
        okb = bidx[(alt_p[bidx] <= 84.0) & (alt_p[bidx] >= self.min_alt + 3.0)]
        if len(okb) == 0:
            okb = bidx
        cosr = math.cos(math.radians(min(60.0, self.fov / 2.0 + 6.0)))
        dens = (tv[okb] @ tv.T >= cosr).sum(axis=1)
        b = int(okb[int(np.argmax(dens))])
        base_alt = float(alt_p[b])
        base_az = float(np.degrees(np.arctan2(tv[b, 1], tv[b, 0])) % 360.0)
        ones = np.ones((len(pool), 1, 3), dtype=np.float32)
        margin = 0.2 * self.pitch + 0.5 * self.gap
        cos_r = math.cos((self.fov * 0.75 + 0.05) * DEG)
        groups = []
        for ha, hz in H:
            if not 0.0 <= base_alt + ha <= 89.5:
                continue
            out_t, _ = self.kern.assign(base_alt + ha, (base_az + hz) % 360.0, tv, ones, self.side, self.pitch,
                                        margin, cos_r, 0, 0)
            cells = np.flatnonzero(out_t >= 0)
            if len(cells):
                groups.append([(int(f), int(out_t[f])) for f in cells])
        used, used_t, got = {}, set(), []
        for gi, grp in enumerate(groups):          # round 1: one fibre for each of the first M hypotheses
            if len(got) >= M:
                break
            for f, t in grp:
                if f not in used and t not in used_t:
                    used[f] = t; used_t.add(t); got.append(gi)
                    break
        for _r in range(fpm - 1):                  # further rounds: a second fibre for the same hypotheses
            for gi in got:
                for f, t in groups[gi]:
                    if f not in used and t not in used_t:
                        used[f] = t; used_t.add(t)
                        break
        for gi in range(len(groups)):              # leftover fibres: more hypotheses, one fibre each
            if gi in got:
                continue
            for f, t in groups[gi]:
                if f not in used and t not in used_t:
                    used[f] = t; used_t.add(t)
                    break
        if not used:
            return None
        cells = np.array(sorted(used), dtype=np.int32)
        tsel = np.array([used[f] for f in cells], dtype=int)
        idx = pool[tsel]
        az_t = np.degrees(np.arctan2(tv[tsel, 1], tv[tsel, 0])) % 360.0
        self.pending = {'kind': 'observe', 't': now, 'T': float(T), 'P': 0, 'idx': idx, 'fib': cells,
                        'tv': tv[tsel], 'calt': base_alt, 'caz': base_az, 'cmd_alt': base_alt, 'cmd_az': base_az,
                        'alt': altall[idx], 'alt_end': altall[idx], 'az': az_t, 'notices': list(notices),
                        'bul_t': self.bul_t, 'dirf': None}
        self.searches += 1
        if self.searches % 10 == 1:
            _log({'event': 'search', 't': fmt_utc(now), 'n': self.searches, 'hyps': len(groups), 'fibres': len(used),
                  'nearest': [round(float(H[0, 0]), 3), round(float(H[0, 1]), 3)] if len(H) else None})
        return {'action': 'observe', 'pointing': {'alt_deg': round(base_alt, 6), 'az_deg': round(base_az, 6)},
                'assignments': {str(int(f)): self.ids[int(i)] for f, i in zip(cells, idx)}, 'duration_seconds': T,
                'program': PROGRAMS[0], 'decision_source': 'optimizer'}

    def _unif_gain(self):
        """Reduction of the uniformity penalty weight x (1 - Jain index of the per-RA-band completed fractions)
        from completing one more target in each band (as if the season ended now; gains only)."""
        done = np.bincount(self.unif_band[self.gl >= self.unif_thr], minlength=len(self.unif_cnt)).astype(float)
        ok = self.unif_cnt > 0
        K = float(ok.sum())
        if K <= 0:
            return np.zeros(len(self.unif_cnt))
        r = np.where(ok, done / np.maximum(self.unif_cnt, 1.0), 0.0)
        S1, S2 = float(r.sum()), float((r * r).sum())
        J = S1 * S1 / (K * S2) if S2 > 0 else 0.0
        d = np.where(ok, 1.0 / np.maximum(self.unif_cnt, 1.0), 0.0)
        S1n = S1 + d
        S2n = S2 + 2.0 * r * d + d * d
        Jn = S1n * S1n / (K * np.maximum(S2n, 1e-12))
        return np.where(ok, np.maximum(0.0, self.unif_w * (Jn - J)), 0.0)

    def _max_paid(self):
        """Cap on penalised fault reports, scaled by the card's false-report penalty when rep_cost_scale is on."""
        mp = int(self.p['max_paid'])
        if self.p['rep_cost_scale'] > 0:
            if self.false_pen <= 1e-9:
                return 3 * mp
            return int(min(3 * mp, max(1, round(mp * 150.0 / self.false_pen))))
        return mp

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
                for k, v in (('req_moon', 0), ('req_urg', 0.0), ('opt_value', 0.0), ('season_rho', 0.0),
                             ('off_search', 0), ('terr_hi', 0), ('ev_excuse', 0), ('rq_commit', 0.0), ('rq_big', 0),
                             ('zf', 0), ('log_sector', 0)):
                    self.p[k] = v
                try:
                    self.bel.tau_learn = False
                    self.bel.nu_ref = 0.0
                    self.bel.sn2, self.bel.ss2 = self.bel.sn2_0, self.bel.ss2_0
                except Exception:
                    pass
                self._safe = True
                _log({'event': 'safe_mode'})
        self.decisions += 1
        wdt = time.perf_counter() - w0
        self.turn_wall += wdt
        if self.p['eng_aware'] > 0:
            try:
                self._eng_note(act, snap, wdt)
            except Exception:
                if not self._eng_err:
                    self._eng_err = True
                    import traceback
                    traceback.print_exc(file=sys.stderr)
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
            elif rt == 'observation_request' and self.logr is not None and len(m.get('reason') or '') > 30:
                self._log_read(m)
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
        if self.sprobe is not None:
            try:
                self.sprobe.on_snap(snap, snap.get('now_utc'))
            except Exception:
                pass
        self._ingest(snap, now)
        if self.p['eng_aware'] > 0:
            try:
                self._eng_measure(snap, now)
            except Exception:
                if not self._eng_err:
                    self._eng_err = True
                    import traceback
                    traceback.print_exc(file=sys.stderr)
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
        if self.log_llm is not None and not self.log_llm_off:
            self._log_llm_poll()
        g_cap = None
        if self.glog is not None:
            try:
                act, g_cap = self._guider_step(now, night)
            except Exception:
                act, g_cap = None, None
                if not self.g_err:
                    self.g_err = True
                    import traceback
                    traceback.print_exc(file=sys.stderr)
            if act is not None:
                return act
        if self.logr is not None and self.log_q:
            act = self._log_report(now)
            if act is not None:
                return act
        left = self.night_ends[night] - now
        if g_cap is not None and g_cap < left:
            if g_cap < self.tmin:
                # waits by duration must last 60-3600 s; a wait until a later moment has no minimum
                return {'action': 'wait', 'until_utc': fmt_utc(now + max(1.0, math.ceil(g_cap)))}
            left = g_cap
        if left < self.tmin:
            nxt = self.night_starts[self.night_starts > now]
            target = float(nxt[0]) if len(nxt) else self.survey_end
            return {'action': 'wait', 'until_utc': fmt_utc(target)}
        lb = snap.get('latest_bulletin') or {}
        notices = lb.get('notices', []) or []
        self.quake_notice = any(n.get('event_kind') == 'earthquake' for n in notices)
        try:
            notices = list(notices) + self._log_sector_notices(now)
        except Exception:
            pass
        try:
            self.bul_t = parse_utc(lb['issued_at_utc']) if lb.get('issued_at_utc') else now
        except Exception:
            self.bul_t = now
        if self.p['ev_excuse'] > 0:
            self._track_events(notices, now)
        self.prev_decide_t = now
        if any(n.get('event_kind') in CLOSE_KINDS and n.get('direction') in (None, 'ALL') for n in notices) or now < self.last_closed_until:
            nxt = (math.floor(now / self.slot) + 1) * self.slot
            if nxt - now < self.tmin:
                nxt += self.slot
            if self.eng_wait_k > 1:
                nxt += (self.eng_wait_k - 1) * self.slot
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

    # ------------------------------------------------------------------ duty log read by the language model
    def _duty_read(self, text, issued):
        try:
            from guider_log import prep
            from log_reader import decode_english, _INVIS, _FW
            all_lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
            complete = len(all_lines) <= 400
            lines = all_lines[:400]
            if not lines:
                return
            hints = {}
            for i, raw in enumerate(lines):
                if len(raw) > 12000:
                    complete = False
                    continue
                r0 = raw.translate(_INVIS).translate(_FW)
                e = prep(raw)
                if decode_english(r0) != r0 or re.findall(r'\d{1,2}:\d{2}', e) != re.findall(r'\d{1,2}:\d{2}', r0):
                    hints[str(i)] = re.sub(r'^\s*【[^】]{1,8}】', '', e)[:300]
            off_s = self.log_off_s

            def loc(t):
                return time.strftime('%m/%d %H:%M', time.gmtime(t + off_s))
            known = self.glog.known_summary(issued, loc)
            real_left = float(self.p['real_cap']) - (time.monotonic() - self.t_real0)
            res = self.dlm.read(lines, hints, time.strftime('%Y-%m-%d %H:%M (%A)', time.gmtime(issued + off_s)),
                                off_s / 3600.0, known, real_left=real_left, issued=issued)
            if res:
                if not complete:
                    res = dict(res, _complete=False)
                n = self.glog.add_llm(res, issued, lines=lines)
                _log(dict({'event': 'duty', 't': fmt_utc(issued)}, **n))
        except Exception:
            if not self.g_err:
                self.g_err = True
                import traceback
                traceback.print_exc(file=sys.stderr)

    # ------------------------------------------------------------------ guider-camera jobs (guider_log)
    def _g_key(self, c):
        return int(round(c['t'] / 60.0))

    def _guider_step(self, now, night):
        """Report due guider jobs, arm probes, wait out flat-lamp windows; returns (action or None, exposure cap)."""
        gl = self.glog
        if not (gl.active or gl.flats or self._g_many()):
            return None, None
        if self.g_report is not None:
            why, self.g_report = self.g_report, None
            if self.consec_reports < 2:
                return self._g_report(now, why), None
        for c in gl.due():
            k = self._g_key(c)
            if k in self.g_done or c['t'] + self.p['g_delay'] > now:
                continue
            self.g_done.add(k)
            self.g_probe.pop(k, None)
            if self.last_correct_t >= c['t'] - 60.0:
                continue            # repaired since by another report
            return self._g_report(now, {'why': 'job', 'job_t': fmt_utc(c['t']), 'src': c['src'][:48]}), None
        if self.p['g_blind'] > 0 and self.consec_reports < 2 and \
                self.false_since_correct < min(self.free_reports, int(self.p['g_blind'])):
            # an uncertain job time costs nothing to report while a free false report is left: a probe needs usable
            # data after the time (clouds, closures and dawn often deny it), the report does not
            for c in gl.probes():
                k = self._g_key(c)
                if k in self.g_done or k in self.g_blind or c['t'] + self.p['g_delay'] > now:
                    continue
                if now - c['t'] > self.p['g_blind_win'] or self.last_correct_t >= c['t'] - 60.0:
                    continue
                self.g_blind.add(k)
                return self._g_report(now, {'why': 'blind', 'job_t': fmt_utc(c['t']), 'st': c['st'], 'key': k}), None
        for c in gl.probes():
            k = self._g_key(c)
            if k in self.g_done or k in self.g_probe or c['t'] > now:
                continue
            if now - c['t'] > 3 * 86400.0:
                self.g_done.add(k)
                continue
            self.g_probe[k] = c
        for k, c in list(self.g_probe.items()):
            if c.get('void') or self.last_correct_t >= c['t'] - 60.0 or (
                    now - c['t'] > 3 * 3600.0 and c.get('looks', 0) >= 6):
                self.g_probe.pop(k, None)
                self.g_done.add(k)
        w = gl.in_flat(now)
        if w is not None:
            return {'action': 'wait', 'until_utc': fmt_utc(min(w[1] + 1.0, float(self.night_ends[night])))}, None
        cap = None
        nf = gl.next_flat_start(now)
        if nf is not None:
            cap = nf - now
        for c in gl.due() + gl.probes():
            if self._g_key(c) in self.g_done:
                continue
            if c['t'] > now:
                lim = c['t'] - now
            elif (c['st'] == 'official' or self.p['g_blind'] > 0) and now < c['t'] + self.p['g_delay']:
                lim = c['t'] + self.p['g_delay'] - now
            else:
                continue
            cap = lim if cap is None else min(cap, lim)
        if self.g_probe or self.g_dead_since is not None:
            cap = float(self.p['g_probe_T']) if cap is None else min(cap, float(self.p['g_probe_T']))
        return None, cap

    def _g_report(self, now, why):
        self.reports += 1
        if self.false_since_correct >= self.free_reports:
            self.paid_reports += 1
        self.last_report_t = now
        self.pending = {'kind': 'report', 'guider': why}
        _log(dict({'event': 'report', 'why': 'guider', 't': fmt_utc(now)}, **{('g_' + k): v for k, v in why.items()}))
        return {'action': 'report'}

    def _g_outcome(self, why, correct, now):
        if correct:
            self.g_correct += 1
            self.false_since_correct = 0
            self.last_correct_t = now
            if self.bel.w[1:].sum() > 0.5:
                self.bel.report_result(True)
            else:
                # the fault's data never reached the belief: keep its no-fault branch
                self.bel.x[:] = self.bel.x[0]
                self.bel.P[:] = self.bel.P[0]
                self.bel.w[:] = 0.0
                self.bel.w[0] = 1.0
            self.drop_t = None
            self.g_dead_since = None
            self.g_dead_n = 0
            self.g_dead_false = 0
            for k, c in list(self.g_probe.items()):
                if c['t'] <= now:
                    self.g_probe.pop(k, None)
                    self.g_done.add(k)
            if why.get('why') == 'blind' and why.get('key') is not None:
                self.g_done.add(why['key'])
        else:
            self.g_false += 1
            self.false_since_correct += 1
            if why.get('why') == 'probe':
                # the probed time was not a fault: never report it again (the same dim data would repeat it)
                k = why.get('key')
                if k is None and why.get('job_t'):
                    try:
                        k = int(round(parse_utc(why['job_t']) / 60.0))
                    except Exception:
                        k = None
                if k is not None:
                    self.g_probe.pop(k, None)
                    self.g_done.add(k)
            if why.get('why') == 'dead':
                self.g_dead_hold = now + min(8 * 3600.0, self.p['g_dead_wait'] * 2.0 ** min(1023, self.g_dead_false))
                self.g_dead_false += 1
                self.g_dead_since = None
                self.g_dead_n = 0

    def _g_many(self):
        """Faults are frequent on this card: the duty log announces many jobs or test windows, or the data has
        already shown more real faults than a season of the original cards ever had (a silent log)."""
        if self.glog is None:
            return False
        if self.glog.busy:
            return True
        try:
            raw = self.p.get('g_many_correct', DEFAULTS['g_many_correct'])
            threshold = float(raw)
            if isinstance(raw, bool) or not math.isfinite(threshold) or threshold < 1 or not threshold.is_integer():
                raise ValueError('g_many_correct must be a positive integer')
            threshold = int(threshold)
        except (TypeError, ValueError, OverflowError):
            threshold = DEFAULTS['g_many_correct']
        return self.correct_reports >= threshold

    def _g_precursor(self, since):
        """The exposures just before a near-zero run show the dimmed (~0.3) first hour of a fault: the two
        exposures that ended in the 20 minutes before it are both dimmed (a cloud dip an hour earlier is not)."""
        pre = [r for (a, b, r) in self.g_hist
               if self.last_correct_t <= a < since and since - 1200.0 <= b <= since + 1.0]
        return len(pre) >= 2 and all(0.1 <= r <= 0.55 for r in pre[-2:])

    def _g_sudden_dark(self, now):
        """A near-zero run that began less than g_dead_wait ago without the dimmed first hour of a fault
        (an unannounced test window looks like this): not evidence for a fault report yet."""
        return (self._g_many() and self.g_dead_since is not None
                and now - self.g_dead_since < self.p['g_dead_wait'] and not self._g_precursor(self.g_dead_since))

    def _obs_ratio(self, start, T, night, idx, y, H, P, act):
        """Median observed / expected score of the hits under the no-fault efficiency (1 = as predicted)."""
        mid = start + 0.5 * T
        m, _ = self.bel.peek(mid, night, act)
        leta = self.bel.leta + math.log(max(1e-6, self.bel.quake_factor(mid, 1.0, night)))
        if not math.isfinite(m + leta) or m + leta > 700:
            return None
        k0 = self.flux[idx] * T * H / (self.q0 * self.f0t0)
        pred = np.minimum(1.0, k0 * math.exp(m + leta))
        finite = np.isfinite(pred) & np.isfinite(y) & (y >= 0)
        if not math.isfinite(self.mult[P]) or self.mult[P] <= 0:
            return None
        ok = finite & (pred > 1e-3) & (pred < 0.9)
        if np.count_nonzero(ok) < 2:
            ok = finite & (pred > 1e-3)
        if not np.any(ok):
            return None
        ratios = y[ok] / (self.mult[P] * pred[ok])
        ratios = ratios[np.isfinite(ratios)]
        return float(np.median(ratios)) if len(ratios) else None

    def _guider_obs(self, start, T, now, night, idx, y, H, P, act):
        """Probe verdicts and the near-zero check for one exposure; True keeps it out of the belief."""
        gl = self.glog
        end = start + T
        flat = gl.overlaps_flat(start, end)
        skip = flat
        for c in gl.due():
            if c['t'] < end and start < c['t'] + self.p['g_delay'] + 600.0 and self.last_correct_t < c['t'] - 60.0:
                skip = True
        r = self._obs_ratio(start, T, night, idx, y, H, P, act)
        if r is None:
            return skip
        if not flat:
            self.g_hist.append((start, end, r))
            if len(self.g_hist) > 60:
                del self.g_hist[:-60]
            for k, c in list(self.g_probe.items()):
                if c['t'] > start + 1.0:
                    continue
                c['looks'] = c.get('looks', 0) + 1
                # a fault is a step at the candidate time (x0.3, then x0.005); cloud dims the data before it too:
                # compare with the exposures of the hour before the candidate when there are any
                ref = c.get('ref')
                if ref is None and 'ref' not in c:
                    pre = [x for (a, b, x) in self.g_hist if c['t'] - 3600.0 <= b <= c['t'] + 1.0]
                    ref = c['ref'] = float(np.median(pre)) if pre else None
                low = self.p['g_low_llm'] if c['st'] == 'llm' else self.p['g_low']
                if r < low and (ref is None or r < self.p['g_step'] * ref):
                    skip = True
                    if self.g_report is None:
                        self.g_report = {'why': 'probe', 'job_t': fmt_utc(c['t']), 'st': c['st'], 'r': round(r, 3),
                                         'key': k}
                elif r > 0.8 or (ref is not None and r >= 0.75 * ref and c['looks'] >= 2):
                    self.g_probe.pop(k, None)
                    self.g_done.add(k)
                    _log({'event': 'g_probe', 'verdict': 'none', 'job_t': fmt_utc(c['t']), 'r': round(r, 3),
                          'ref': None if ref is None else round(ref, 3)})
        if r < self.p['g_dead'] and not flat and self._g_many():
            skip = True
            if self.g_dead_since is None:
                self.g_dead_since = start
            self.g_dead_n += 1
            free = self.false_since_correct < self.free_reports
            # two near-zero exposures in a row (an exposure running into a closed slot is near zero only once)
            # a guider fault dims the data to ~0.3 for an hour before it goes dark; a test lamp or a closed
            # cover goes dark at once and is over within half an hour: report a sudden darkness only if it lasts
            if self.g_report is None and now >= self.g_dead_hold and self.g_dead_n >= 2 and (
                    self._g_precursor(self.g_dead_since) or end - self.g_dead_since >= self.p['g_dead_wait']):
                self.g_report = {'why': 'dead', 'since': fmt_utc(self.g_dead_since), 'r': round(r, 4)}
        elif flat or r >= self.p['g_dead']:
            # A test window or a non-dead measurement breaks the consecutive
            # unexplained near-zero run; do not join separate dark dips.
            self.g_dead_since = None
            self.g_dead_n = 0
        if skip:
            self.g_skip += 1
        return skip

    # ------------------------------------------------------------------ handover log
    def _log_read(self, m):
        """Feed one request's log text to the reader; queue the faults it announces or confirms."""
        try:
            issued = parse_utc(m['issued_at_utc']) if m.get('issued_at_utc') else (self.prev_decide_t or 0.0)
            evs = self.logr.read(m.get('reason') or '', issued)
            if self.glog is not None:
                try:
                    self.glog.read(m.get('reason') or '', issued)
                except Exception:
                    if not self.g_err:
                        self.g_err = True
                        import traceback
                        traceback.print_exc(file=sys.stderr)
                if self.dlm is not None and issued < self.survey_end - 3600.0:
                    self._duty_read(m.get('reason') or '', issued)
            if self.log_llm is not None and not self.log_llm_off and self.logr.last_unread and m.get('request_id') \
                    and issued < self.survey_end - 86400.0:
                loc = time.strftime('%Y-%m-%d %H:%M', time.gmtime(issued + self.log_off_s))
                if self.log_llm.submit(m['request_id'], self.logr.last_unread[:8], loc):
                    self.log_llm_meta[m['request_id']] = (issued, list(self.logr.last_unread[:8]))
            for ev in evs:
                t = ev['t']
                if ev['kind'] == 'occurred' and t is not None:
                    # a confirmed drop happens in the dark: an onset outside every night is a misread time
                    j = int(np.searchsorted(self.night_starts, t + 3600.0, side='right')) - 1
                    if j < 0 or t > self.night_ends[j] + 3600.0:
                        t = None
                due = t + self.p['log_delay'] if ev['kind'] == 'planned' else issued
                self.log_q.append({'t': t, 'kind': ev['kind'], 'due': due, 'seen': issued, 'tries': 0,
                                   'done': False, 'ev': ev})
                _log({'event': 'log_fault', 'kind': ev['kind'], 'onset': fmt_utc(t) if t is not None else None,
                      'seen': fmt_utc(issued)})
        except Exception:
            if not self.log_err:
                self.log_err = True
                import traceback
                traceback.print_exc(file=sys.stderr)

    def _log_llm_poll(self):
        """Fault items the language model found in log lines the parser left unread, checked against the text."""
        try:
            from log_reader import quote_in, normalise, TIME, DATE
            for key, items in self.log_llm.results():
                meta = self.log_llm_meta.pop(key, None)
                if meta is None or self.log_llm_off:
                    continue
                issued, lines = meta
                for it in items:
                    kind = it.get('kind')
                    if kind not in ('planned', 'occurred') or not quote_in(it.get('quote'), lines):
                        continue
                    t = None
                    if kind == 'planned':
                        qn = normalise(it['quote'])
                        tm = TIME.search(normalise(it.get('time') or ''))
                        if not tm or (int(tm.group(1)), int(tm.group(2))) not in {
                                (int(a), int(b)) for a, b in TIME.findall(qn)}:
                            continue        # the announced time must be written in the quoted words
                        dm = DATE.search(normalise(it.get('date') or ''))
                        qd = {(int(a), int(b)) for a, b in DATE.findall(qn)}
                        if qd and (not dm or (int(dm.group(1)), int(dm.group(2))) not in qd):
                            continue
                        t = self.logr.onset_from_parts('planned', '' if not qd else it.get('date'), it.get('time'), issued,
                                                       it['quote'])
                        if t is None or not (issued - 6 * 3600 <= t <= issued + 20 * 86400) or any(
                                q['kind'] == 'planned' and q['t'] is not None and abs(q['t'] - t) < 7200
                                for q in self.log_q):
                            continue
                    due = t + self.p['log_delay'] if kind == 'planned' else issued
                    ev = {'t': t, 'kind': kind, 'src': str(it.get('quote'))[:120], 'seen': issued}
                    self.log_q.append({'t': t, 'kind': kind, 'due': due, 'seen': issued, 'tries': 0, 'done': False,
                                       'ev': ev, 'llm': True})
                    _log({'event': 'log_fault', 'kind': kind, 'llm': True,
                          'onset': fmt_utc(t) if t is not None else None, 'seen': fmt_utc(issued)})
        except Exception:
            if not self.log_err:
                self.log_err = True
                import traceback
                traceback.print_exc(file=sys.stderr)

    def _log_report(self, now):
        """A fault the log announced (now past its start) or confirmed, not yet repaired by a correct report."""
        try:
            if self.log_false >= int(self.p['log_false_max']) or now >= self.survey_end - 60:
                return None
            if self.consec_reports >= min(3, max(1, self.max_consec - 1)):
                return None
            for q in self.log_q:
                if q['done'] or now < q['due']:
                    continue
                if q['ev'].get('void'):
                    q['done'] = True
                    continue
                ref = q['t'] - 2700.0 if q['t'] is not None else q['seen'] - self.p['log_occ_win']
                if self.last_correct_t >= ref:
                    q['done'] = True        # repaired since it began
                    continue
                if now - q['due'] > self.p['log_stale']:
                    q['done'] = True
                    continue
                q['tries'] += 1
                q['done'] = True            # a false planned report re-arms it once (_log_outcome)
                self.reports += 1
                if self.false_since_correct >= self.free_reports:
                    self.paid_reports += 1
                self.last_report_t = now
                self.pending = {'kind': 'report', 'log': q}
                _log({'event': 'report', 'why': 'log', 't': fmt_utc(now), 'kind': q['kind'],
                      'onset': fmt_utc(q['t']) if q['t'] is not None else None, 'pf': round(self.bel.p_fault(), 3)})
                return {'action': 'report'}
        except Exception:
            if not self.log_err:
                self.log_err = True
                import traceback
                traceback.print_exc(file=sys.stderr)
        return None

    def _log_outcome(self, q, correct, now):
        if correct:
            if q.get('llm'):
                self.log_llm_false = 0
            return
        self.log_false += 1
        if q.get('llm'):
            # one wrong model reading costs that item only; only a run of three wrong ones stops its reports
            self.log_llm_false = getattr(self, 'log_llm_false', 0) + 1
            if self.log_llm_false >= 3:
                self.log_llm_off = True
                for o in self.log_q:
                    if o.get('llm'):
                        o['done'] = True
            return
        if q['kind'] == 'planned' and q['tries'] < 2 and q['t'] is not None:
            # the work may have started a little late: try once more
            q['done'] = False
            q['due'] = max(now + 1800.0, q['t'] + self.p['log_retry'])

    def _sun_event(self, kind, nd):
        """UTC epoch of sunset / dusk / dawn / sunrise of the local night nd = (y, m, d), for duty-log times written
        relative to them: dusk and dawn are the night's observing start and end, sunset and sunrise the moments the
        Sun's centre crosses -0.833 deg; None when the Sun does not cross (polar day or night)."""
        cache = getattr(self, '_sun_cache', None)
        if cache is None:
            cache = self._sun_cache = {}
        key = (kind, tuple(nd))
        if key in cache:
            return cache[key]
        import calendar
        from astro import sun_alt
        off = float(getattr(self, 'log_off_s', 0.0))
        mid = calendar.timegm((int(nd[0]), int(nd[1]), int(nd[2]), 0, 0, 0)) + 86400.0 - off   # local midnight after
        out = None
        if kind in ('dusk', 'dawn'):
            for (a, b) in self.nights:
                if abs(a - mid) < 14 * 3600.0 and abs(b - mid) < 14 * 3600.0 and a < b:
                    out = a if kind == 'dusk' else b
                    break
        if kind in ('moonrise', 'moonset'):
            # the Moon's upper limb at the horizon (refraction, semi-diameter and parallax: about +0.13 deg); of the
            # crossings within 14 h of local midnight the one nearest to it
            from astro import moon_state
            ts = np.arange(mid - 14 * 3600.0, mid + 14 * 3600.0 + 1.0, 300.0)
            hs = np.array([moon_state(float(t), self.lat, self.lon)[2] for t in ts]) > 0.13
            want_up = kind == 'moonrise'
            idx = [k for k in range(len(ts) - 1) if hs[k] != hs[k + 1] and bool(hs[k + 1]) == want_up]
            if idx:
                k = min(idx, key=lambda k: abs(ts[k] - mid))
                lo, hi = float(ts[k]), float(ts[k + 1])
                for _ in range(10):
                    m = 0.5 * (lo + hi)
                    if (moon_state(m, self.lat, self.lon)[2] > 0.13) == bool(hs[k]):
                        lo = m
                    else:
                        hi = m
                out = 0.5 * (lo + hi)
            cache[key] = out
            return out
        if out is None:
            h0 = -0.833 if kind in ('sunset', 'sunrise') else -18.0
            step = 120.0
            ts = np.arange(mid - 14 * 3600.0, mid + 14 * 3600.0 + 1.0, step)
            hs = np.array([sun_alt(float(t), self.lat, self.lon) for t in ts])
            above = hs > h0
            if kind in ('sunset', 'dusk'):
                idx = [k for k in range(len(ts) - 1) if above[k] and not above[k + 1] and ts[k] <= mid]
                k = idx[-1] if idx else None
            else:
                idx = [k for k in range(len(ts) - 1) if not above[k] and above[k + 1] and ts[k + 1] >= mid]
                k = idx[0] if idx else None
            if k is not None:
                lo, hi = float(ts[k]), float(ts[k + 1])
                for _ in range(12):
                    m = 0.5 * (lo + hi)
                    if (sun_alt(m, self.lat, self.lon) > h0) == bool(above[k]):
                        lo = m
                    else:
                        hi = m
                out = 0.5 * (lo + hi)
        cache[key] = out
        return out

    def _log_sector_notices(self, now):
        """Rocket-launch-like notices for the directions the duty log closes now (or within 20 min)."""
        gl = self.glog
        if self.p['log_sector'] <= 0 or gl is None or not getattr(gl, 'sector_closures', None):
            return []
        out, seen = [], set()
        for (a, b, ds, src) in gl.sector_closures[-60:]:
            if a - 1200.0 <= now <= b:
                key = (a, b, ds)
                if key not in getattr(self, '_ls_logged', set()):
                    self._ls_logged = getattr(self, '_ls_logged', set()) | {key}
                    if len(self._ls_logged) <= 40:
                        _log({'event': 'log_sector', 't': fmt_utc(now), 'from': fmt_utc(a), 'to': fmt_utc(b),
                              'dirs': list(ds), 'src': src})
                for d in ds:
                    if d in DIR_AZ and d not in seen:
                        seen.add(d)
                        out.append({'event_kind': 'rocket_launch', 'direction': d, 'source': 'duty_log'})
        return out

    def _track_events(self, notices, now):
        """Onset window and end of each announced weather event (kind, direction) seen in the bulletins."""
        cur = set()
        lo = self.prev_decide_t if self.prev_decide_t is not None else now
        for n in notices:
            k = n.get('event_kind')
            if k in WEATHER_KINDS:
                key = (k, n.get('direction') or 'ALL')
                cur.add(key)
                e = self.ev_onset.get(key)
                if e is None or e[2] is not None:
                    self.ev_onset[key] = [min(lo, now), now, None]
        for key, e in list(self.ev_onset.items()):
            if key not in cur and e[2] is None:
                e[2] = now
            if e[2] is not None and now - e[2] > 6 * 3600:
                del self.ev_onset[key]

    def _excused(self, now):
        """The efficiency drop began with an announced weather event that is still active or ended < 3 h ago."""
        if self.drop_t is None:
            return False
        for lo, hi, end in self.ev_onset.values():
            if lo - 3600 <= self.drop_t <= hi + 7200 and (end is None or now - end < 3 * 3600):
                return True
        return False

    def _should_report(self, now, night):
        if self.consec_reports >= min(3, max(1, self.max_consec - 1)):
            return False
        if self._g_sudden_dark(now):
            return False
        if self.p['ev_excuse'] > 0 and self._excused(now):
            return False
        if self.bel.learning_quake(night):
            return False
        pf = self.bel.p_fault()
        if self.correct_reports >= (len(self.bel.pc) if self.bel.multi else self.p['max_faults']) and not \
                self._g_many():
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
        if not free and self.p['rep_cost_scale'] > 0:
            # a costlier false report asks for a longer run of evidence (a real fault persists, a dip does not)
            k = int(round(k * min(4.0, max(1.0, self.false_pen / 150.0))))
        # each false report since the last correct one asks for a longer run of evidence: a real fault
        # persists for the rest of the season, a directional cloud or a weather dip does not
        k += int(round(self.p['rep_esc'] * self.false_since_correct))
        if len(hist) < max(2, k) or any(h < 0.5 * thr for h in hist[-max(2, k):-1]):
            return False
        if not free:
            mp = self._max_paid()
            if self.paid_reports >= mp:
                # the paid budget is spent: only a long run of near-certain evidence (a real fault persists
                # for the rest of the season) still gets reported
                ko = int(self.p['rep_override'])
                if (ko <= 0 or self.paid_reports >= mp + 2 or len(hist) < ko
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
        if self.p['eng_aware'] > 0 and self._eng_left is not None:
            eng_left = max(eng_left, 1.05 * self._eng_left)
        lim = max(0.0, (wr - eng_left - 0.05 * wr0) / f)
        if lim < float(wc.get('remaining_seconds', lim)) and not getattr(self, '_wall_logged', False):
            self._wall_logged = True
            _log({'event': 'wall_bound', 'wall_remaining': round(wr, 1), 'engine': round(engine, 1),
                  'eng_left': round(eng_left, 1), 'limit': round(lim, 1)})
        return lim

    def _eng_measure(self, snap, now):
        """Fit the engine's real time between our turns: each runner step re-checks every expired request (and,
        before a decision, every active one and the best-score table) against every ledger record."""
        res = snap.get('last_result') or {}
        if res.get('action') == 'observe':
            nh = int(res.get('hit_count', len(res.get('hits', []) or [])))
            self.n_entries += nh
            self._eng_hits = 0.97 * self._eng_hits + 0.03 * nh
        act = snap.get('active_requests') or []
        for r in act:
            rid = r.get('request_id')
            if rid:
                self.rq_seen.add(rid)
        for m in snap.get('new_messages', []) or []:
            if m.get('record_type') == 'observation_request' and m.get('request_id'):
                self.rq_seen.add(m['request_id'])
        wr = (snap.get('wallclock') or {}).get('wall_remaining_seconds')
        if wr is None:
            return
        wr = float(wr)
        e = self._eng
        R, Ra = len(self.rq_seen), len(act)
        if e['wr'] is not None:
            dt = (e['wr'] - wr) - e['tau']
            if 0.0 <= dt < 300.0:
                n_it = e['chunks'] + 1.0
                X = (e['chunks'] * max(0, R - Ra) + R + 1.0) * float(self.n_entries)
                S = e['S']
                S *= 0.997
                S += np.array([n_it * n_it, n_it * X, X * X, n_it * dt, X * dt])
                e['n'] += 1
        e['wr'] = wr
        if self._wall_total is None:
            self._wall_total = wr
        if self.decisions % 25 == 0:
            obs_left = float(np.sum(np.maximum(0.0, self.night_ends - np.maximum(self.night_starts, now))))
            obs_total = float(np.sum(self.night_ends - self.night_starts))
            tau = 1.0 - obs_left / max(obs_total, 1.0)
            if tau > 0.0:
                self._eng_hist.append((tau, float(self.n_entries), float(self.observes)))
            # early exposures are short (bright targets first) and the record count grows concavely: wait until
            # 15% of the dark time has passed before extrapolating it over the season
            if e['n'] >= 40 and tau >= 0.15:
                self._eng_update(now, wr, R, Ra)

    _wall_total = None

    def _eng_note(self, act, snap, wdt):
        """Remember what our action implies for the runner: wait-until is expanded in steps of at most the
        longest exposure, each a full engine step."""
        e = self._eng
        e['tau'] = wdt
        e['chunks'] = 0
        try:
            now = parse_utc(snap['now_utc'])
        except Exception:
            return
        kind = act.get('action')
        night = self._night_index(now)
        if kind == 'observe':
            T = float(act.get('duration_seconds', 0) or 0)
            if T > 0:
                if self._eng_level == 0:
                    # the planner's own choice (a raised floor would bias the projection of the lower levels)
                    self._eng_obsT.append(T)
                self._eng_tobs = 0.995 * self._eng_tobs + T
        elif kind == 'wait':
            if 'until_utc' in act:
                u = parse_utc(act['until_utc'])
                e['chunks'] = max(0, int(math.ceil((u - now) / max(float(self.tmax), 60.0) - 1e-9)))
                adv = u - now
            else:
                adv = float(act.get('duration_seconds', 0) or 0)
            if night >= 0 and adv > 0:
                adv = min(adv, self.night_ends[night] - now)
                if adv > 0:
                    self._eng_wait.append(adv)
                    self._eng_twait = 0.995 * self._eng_twait + adv
                    self._eng_nwait += 1

    def _eng_coef(self):
        # a persistent weak prior of 0.02 s per step at no request load keeps the per-step constant from being
        # absorbed into the request x record term when the request load hardly varies
        S = self._eng['S'] + np.array([30.0, 0.0, 0.0, 30.0 * 0.02, 0.0])
        det = S[0] * S[2] - S[1] * S[1]
        a = k = None
        if det > 1e-9 * S[0] * S[2]:
            a = (S[2] * S[3] - S[1] * S[4]) / det
            k = (S[0] * S[4] - S[1] * S[3]) / det
        if a is None or a < 0 or k is None or k < 0:
            if a is not None and a < 0:
                a, k = 0.0, S[4] / max(S[2], 1e-30)
            else:
                k = 0.0 if k is None or k < 0 else k
                a = (S[3] - k * S[1]) / max(S[0], 1e-9)
        return max(0.0, a), max(0.0, k)

    ENG_LEVELS = ((0.0, 1), (300.0, 1), (600.0, 2), (900.0, 2), (1200.0, 3), (1800.0, 3), (2700.0, 4), (3600.0, 4))

    def _eng_growth(self, tau_now):
        """Local exponents of records and observes against the elapsed dark fraction (both grow concavely:
        bright targets first, longer exposures later), blended with a prior of 0.6 until 30% of the season."""
        out = []
        pts = [h for h in self._eng_hist if h[0] >= max(0.02, 0.5 * tau_now)]
        for col in (1, 2):
            g = None
            if len(pts) >= 4:
                x = np.log([h[0] for h in pts])
                y = np.log([max(h[col], 1.0) for h in pts])
                vx = float(np.var(x))
                if vx > 1e-6:
                    g = float(np.mean((x - x.mean()) * (y - y.mean())) / vx)
            w = min(1.0, tau_now / 0.3) if g is not None else 0.0
            out.append(float(np.clip(w * (g if g is not None else 0.6) + (1.0 - w) * 0.6, 0.3, 1.0)))
        return out

    def _eng_project(self, now, R, Ra, a, k, level):
        """Engine seconds for the rest of the season if exposures last at least the level's floor and closure
        waits span its number of slots."""
        floor, wk = self.ENG_LEVELS[level]
        ot = np.array(self._eng_obsT) if self._eng_obsT else np.array([600.0])
        wt = np.array(self._eng_wait) if self._eng_wait else np.array([float(self.slot)])
        mo0 = float(np.mean(np.minimum(ot, self.tmax)))
        moL = float(np.mean(np.maximum(np.minimum(ot, self.tmax), min(floor, self.tmax))))
        sc = mo0 / max(moL, 1.0)                                     # observes (and records) kept at this level
        mw0 = float(np.mean(wt))
        sw = mw0 / max(mw0 + (wk - 1) * float(self.slot), 1.0)      # closure wait steps kept
        dark = np.maximum(0.0, self.night_ends - self.night_starts)
        obs_total = float(np.sum(dark))
        left_n = np.maximum(0.0, self.night_ends - np.maximum(self.night_starts, now))
        tau_now = max(1e-3, 1.0 - float(np.sum(left_n)) / max(obs_total, 1.0))
        alpha, beta = self._eng_growth(tau_now)
        season = float(self.night_ends[-1]) - float(self.night_starts[0])
        rho = (R + 0.6) / (max(now - float(self.night_starts[0]), 0.0) + 0.1 * season)   # prior: 6 per season
        E0, N0, W0 = float(self.n_entries), float(max(self.observes, 1)), float(self._eng_nwait)
        E = E0
        tot = 0.0
        prev_end = now
        stepmax = max(float(self.tmax), 60.0)
        tau_s = tau_now
        for s_, e_, ln in zip(self.night_starts, self.night_ends, left_n):
            if e_ <= now or ln <= 0:
                continue
            a0 = max(s_, now)
            Rg = R + rho * (a0 - now)
            if s_ > prev_end:
                ch = math.ceil((s_ - prev_end) / stepmax)
                tot += ch * (a + k * max(0.0, Rg - Ra) * E) + a + k * (Rg + 1.0) * E
            tau_e = tau_s + ln / max(obs_total, 1.0)
            dE = E0 * ((tau_e / tau_now) ** alpha - (tau_s / tau_now) ** alpha) * sc
            dN = N0 * ((tau_e / tau_now) ** beta - (tau_s / tau_now) ** beta) * sc
            dW = W0 * (tau_e - tau_s) / tau_now * sw
            Rm = R + rho * (0.5 * (a0 + e_) - now)
            tot += (dN + dW) * (a + k * (Rm + 1.0) * (E + 0.5 * dE))
            E += dE
            tau_s = tau_e
            prev_end = e_
        return tot

    def _eng_update(self, now, wr, R, Ra):
        if R < 12:
            # few requests (the A-D cards have 6): the engine's per-step time hardly grows, the c26 rules apply
            self._eng_left = None
            if self._eng_level:
                _log({'event': 'eng_level', 't': fmt_utc(now), 'level': 0, 'R': R})
            self._eng_level = 0
            self.eng_floor, self.eng_wait_k = self.ENG_LEVELS[0]
            return
        a, k = self._eng_coef()
        lim = self.p['eng_share'] * max(0.0, wr - 0.03 * (self._wall_total or wr) - 20.0)
        cur = self._eng_level
        proj = [None] * len(self.ENG_LEVELS)
        proj[0] = self._eng_project(now, R, Ra, a, k, 0)
        lev = 0
        if proj[0] > lim:
            lev = len(self.ENG_LEVELS) - 1
            for L in range(1, len(self.ENG_LEVELS)):
                proj[L] = self._eng_project(now, R, Ra, a, k, L)
                if proj[L] <= lim:
                    lev = L
                    break
        obs_left = float(np.sum(np.maximum(0.0, self.night_ends - np.maximum(self.night_starts, now))))
        tau = 1.0 - obs_left / max(float(np.sum(self.night_ends - self.night_starts)), 1.0)
        # the engine's time concentrates late in the season (records and requests accumulate): early levels buy
        # little and cost science, so cap them while the projection is still uncertain
        lev = min(lev, 2 if tau < 0.3 else 4 if tau < 0.5 else len(self.ENG_LEVELS) - 1)
        if lev > cur:
            # step up gradually and only on a repeated finding (the projection is noisy)
            self._eng_up = getattr(self, '_eng_up', 0) + 1
            lev = min(lev, cur + 2) if self._eng_up >= 2 else cur
        else:
            self._eng_up = 0
        if lev < cur:
            # relax one level at a time, on a repeated finding with a clear margin (no flapping)
            if proj[cur - 1] is None:
                proj[cur - 1] = self._eng_project(now, R, Ra, a, k, cur - 1)
            self._eng_down = getattr(self, '_eng_down', 0) + 1
            lev = cur - 1 if (self._eng_down >= 2 and proj[cur - 1] <= 0.75 * lim) else cur
            if lev < cur:
                self._eng_down = 0
        else:
            self._eng_down = 0
        if proj[lev] is None:
            proj[lev] = self._eng_project(now, R, Ra, a, k, lev)
        self._eng_left = proj[lev]
        if lev != cur:
            _log({'event': 'eng_level', 't': fmt_utc(now), 'level': lev, 'floor': self.ENG_LEVELS[lev][0],
                  'wait_k': self.ENG_LEVELS[lev][1], 'proj0': round(proj[0], 1), 'proj': round(proj[lev], 1),
                  'lim': round(lim, 1), 'a': round(a, 4), 'k': float('%.3g' % k), 'R': R, 'E': self.n_entries})
        self._eng_level = lev
        self.eng_floor, self.eng_wait_k = self.ENG_LEVELS[lev]

    def _richness(self, now, night):
        """0 (capacity-limited) .. 1 (time-rich): remaining demand of fibre time (incomplete targets,
        at the recent fill) against the remaining dark time; cached for 25 decisions."""
        if self.decisions % 25 != 0 and hasattr(self, '_rich_cache'):
            return self._rich_cache
        inc = self.best < self.w * self.mult_max * 0.98
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
        if self.p['off_search'] > 0 and self._lost():
            act = self._offset_search(now, left, tvall, altall, notices)
            if act is not None:
                return act
        # candidate pool
        vis = altall >= self.min_alt + 0.3
        maxval = self.w * self.mult_max
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
                feas = self._request_feasible(cand, now, dl, remaining_n, float(r.get('completion_factor_threshold', 0.5)), night,
                                              reward=float(r.get('completion_reward', 0.0)), committed=len(done) > 0)
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
        ub_all = None
        if self.p['unif_bonus'] > 0 and self.unif_w > 0:
            ub_all = self.p['unif_bonus'] * self._unif_gain()[self.unif_band]
            ub_all = np.where(self.gl < self.unif_thr, ub_all, 0.0)
        potential = (self.best < maxval * 0.999) | incomplete_req | (reqbonus_active > 0)
        if ub_all is not None:
            potential |= ub_all > 0
        pool = np.flatnonzero(vis & potential)
        if self.probe > 0:
            hp = pool[altall[pool] >= 56.0]
            if self.p['terr_hi'] > 0 and len(hp) and self.terrain_dirs:
                azp = np.degrees(np.arctan2(tvall[hp, 1], tvall[hp, 0])) % 360.0
                aw = self._terr_away_vec(altall[hp], azp)
                if aw.any():
                    hp = hp[aw]
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
        if self.eng_floor > 0 and len(tg) > 1 and not self.probe:
            tg = tg[tg >= min(self.eng_floor, float(tg[-1]))]
        if emergency and len(tg) > 1:
            # spread the decisions the remaining budget affords over the remaining dark time
            obs_left = float(np.sum(np.maximum(0.0, self.night_ends - np.maximum(self.night_starts, now))))
            n_aff = 0.8 * remaining / max(getattr(self, '_cost_ema', 0.02), 1e-3)
            t_floor = min(float(tg[-1]), max(600.0, obs_left / max(n_aff, 1.0)))
            tg = tg[tg >= t_floor]
        self._probe_now = self.probe > 0
        if self.probe > 0:
            tg = tg[tg <= 180] if np.any(tg <= 180) else tg[:1]
            self.probe -= 1
        nt = len(tg)
        # coarse priority to cap the pool size
        hnow_air = self._hfac(alt_now)
        kk = self.flux[pool] * Zp * hnow_air / (self.q0 * self.f0t0)
        quick = self.w[pool] * self.mult_max * np.minimum(1.0, kk * 1800) - self.best[pool]
        if (self.p['quick_long'] > 0 and float(tg[-1]) > 1800 and self.pool_scale >= self.p['quick_long_ps']
                and self.fill_ema < max(self.p['quick_long_fill'] * self.nfib, 1.5)):
            if not getattr(self, '_ql_logged', False):
                self._ql_logged = True
                _log({'event': 'quick_long_on', 't': fmt_utc(now), 'fill': round(self.fill_ema, 2)})
            qlong = self.w[pool] * self.mult_max * np.minimum(1.0, kk * float(tg[-1]) * self.p['quick_long']) - self.best[pool]
            quick = np.where(quick > 1e-9, quick, 1e-3 * np.maximum(qlong, 0.0))
        quick = np.maximum(quick, 0) + incomplete_req[pool] * self.req_pen * np.minimum(1.0, kk * 3600 / self.req_thr) ** 4 + reqbonus_active[pool]
        if ub_all is not None:
            quick = quick + ub_all[pool] * np.minimum(1.0, kk * 3600 / self.unif_thr) ** 4
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
        if self.p['rq_urg_intra'] > 0:
            jq0 = np.flatnonzero(rqb > 0)
            if len(jq0):
                # request members that leave the sky (or the request window) soonest go first
                hl = self._vis_hours(now, np.minimum(dl_rq[jq0], self.night_ends[night]), pool[jq0])
                rqb = rqb.copy()
                rqb[jq0] *= np.clip((1.5 / np.maximum(hl, 0.2)) ** self.p['rq_urg_intra'], 1.0, 3.0)
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

        ubon = ub_all[pool] if ub_all is not None else None

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
            if ubon is not None:
                ju = np.flatnonzero(ubon[a:b] > 0)
                if len(ju):
                    p_u = 0.5 * (1 + _erf((lg[:, ju] - math.log(self.unif_thr) - math.log(self.p['req_safety'])) / (sg * sqrt2)))
                    rv[:, ju] += p_u * ubon[a:b][ju][None, :]
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
                jo = np.flatnonzero((best_ > 1e-9) & (best_ < self.w[p_] * self.mult_max * 0.995))
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
                if self.p['rq_norho'] > 0:
                    v = (sci + rv) * urg_[None, :] * rho_[None, :] + extra_r
                else:
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
        sep = self.p['anchor_sep']
        min_sep = math.cos(max(sep * self.fov, self.pitch if sep >= 0.3 else sep * self.fov) * DEG) if sep > 0 else 2.0
        cand_a = order[: max(200, anchors_n * 8)]
        cand_a = cand_a[solo[cand_a] > 0]
        if len(cand_a) and min_sep > 1.0:
            anchors = [int(a) for a in cand_a[:anchors_n]]
        elif len(cand_a):
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
        if self._probe_now and self.p['eng_aware'] > 0 and len(cells) > 4 and self._eng_level > 0:
            # a closure probe only has to show whether the site reopened: with many requests every ledger
            # record slows each later engine step, so probe with the four best fibres
            keep = np.sort(np.argsort(-out_v[cells])[:4])
            cells = cells[keep]
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

    def _sci_rate(self, now):
        """Remaining attainable science per remaining dark hour (an upper bound, cached per decision)."""
        if getattr(self, '_sr_t', None) == now:
            return self._sr_v
        pot = float(np.sum(np.maximum(0.0, self.w * self.mult_max - self.best)))
        hrs = float(np.sum(np.maximum(0.0, self.night_ends - np.maximum(self.night_starts, now)))) / 3600.0
        self._sr_t, self._sr_v = now, pot / max(hrs, 1.0)
        return self._sr_v

    def _request_feasible(self, cand, now, deadline, need=1, thr=0.5, night=None, reward=0.0, committed=False):
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
        frac = 0.5
        if self.p['rq_big'] > 0 and reward > 0:
            ratio = reward / max(tsum / 3600.0, 0.1) / max(self._sci_rate(now), 1e-6)
            frac = 0.5 + 0.4 * float(np.clip((math.log2(max(ratio, 1e-9)) - 3.0) / 3.0, 0.0, 1.0))
        if committed and self.p['rq_commit'] > 0:
            frac = max(frac, float(self.p['rq_commit']))
        if tsum > frac * avail:
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
            sci = float(np.sum(self.best)) / max(1e-9, float(np.sum(self.w * self.mult_max)))
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
        if getattr(self, 'sprobe', None) is not None:
            try:
                self.sprobe.final()
            except Exception:
                pass
        g = {}
        if getattr(self, 'glog', None) is not None:
            gl = self.glog
            g = {'g_correct': self.g_correct, 'g_false': self.g_false, 'g_skip': self.g_skip,
                 'g_jobs': len(gl.due()), 'g_probes': len(gl.probes()), 'g_flats': len(gl.flats),
                 'g_void': sum(1 for c in gl.cands.values() if c['void']), 'g_unparsed': len(gl.unparsed)}
        return {'decisions': self.decisions, 'observes': self.observes, 'reports': self.reports, **g,
                'correct_reports': self.correct_reports + self.g_correct,
                'false_reports': self.reports - self.correct_reports - self.g_correct,
                'dec_cpu': round(self.dec_cpu, 2), 'init_cpu': round(self.init_cpu, 2),
                'charge_ratio': round(self._charge_ratio, 3), 'turn_wall': round(self.turn_wall, 1),
                'offset_est': [round(self.off_est[0], 4), round(self.off_est[1], 4)], 'offset_obs': self.off_obs,
                'misses': self.misses_total, 'logZ_mean': round(self.logZ_mean, 3), 'kernel': self.kern.lib is not None,
                'pf': round(self.bel.p_fault(), 4), 'quakes': [round(self.bel._d0_hat(q), 3) for q in self.bel.quakes], 'bad': getattr(self.bel, 'n_bad', 0), 'cap': None if self.cap_ratio is None else round(self.cap_ratio, 3), 't0': round(getattr(self, '_t0_cache', 0.0), 1), 'rich': round(getattr(self, '_rich_cache', 0.0), 3), 'pool_scale': round(self.pool_scale, 3), 'nfault': self.bel.nfault, 'pc': [round(float(x), 3) for x in self.bel.pc], 'stress': self.stress_seen, 'zf_conf': getattr(self, 'zf_conf_n', 0), 'anchor_cost': None if self.anchor_cost is None else [round(self.anchor_cost[0], 4), round(self.anchor_cost[1], 5)],
                'llm': self.strategist.summary() if self.strategist is not None else None,
                'eng': {'level': self._eng_level, 'entries': self.n_entries, 'requests': len(self.rq_seen),
                        'coef': [float('%.4g' % c) for c in self._eng_coef()],
                        'left': None if self._eng_left is None else round(self._eng_left, 1)}}


def _erf(x):
    # vectorised erf (Abramowitz-Stegun 7.1.26), |err| < 1.5e-7
    s = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-a * a)
    return s * y


def make(payload):
    return Policy(payload)
