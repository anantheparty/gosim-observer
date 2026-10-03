"""Global spherical pointing-box search added to a frozen strong CPU policy.

All inputs are initialize, delivered public messages and feedback. No truth
products are imported here. Search has a fixed expansion count; it is an
anytime global-domain search, not a global optimality certificate.
"""
from __future__ import annotations
import ctypes
import math
import os
from pathlib import Path
import platform
import time
import numpy as np
from .cpu_phase_candidates import CPUPhaseSpatialPlanner
from .spatial_candidates import DEG, PROGRAMS, parse_utc, local_sidereal


def load_native():
    suffix = 'darwin_arm64.dylib' if platform.system() == 'Darwin' else 'linux_x86_64.so'
    lib = ctypes.CDLL(str(Path(__file__).with_name('global_field_search_' + suffix)))
    array = np.ctypeslib.ndpointer(dtype=np.float64, flags='C_CONTIGUOUS')
    lib.global_field_search.argtypes = [ctypes.c_int, array, array, array, array]
    lib.global_field_search.restype = ctypes.c_int
    lib.global_field_mask.argtypes = [ctypes.c_double] * 6 + [ctypes.c_int, ctypes.c_double, ctypes.c_double]
    lib.global_field_mask.restype = ctypes.c_uint
    return lib


def optimistic_rates(p, frame):
    """A per-target supremum bound, before enforcing common duration/geometry.

    Negative Jain-gradient bonuses are omitted. The focus request gets an
    additional quota/remaining credit, since its own threshold can differ from
    the maximum threshold in the aggregate request arrays. Urgency >= 1 makes
    these credits dominate the exact one-request quota calculation.
    """
    _,up,k,scores,factors,mult,missing,rr,rt,rd,ub,urg,seconds,safety,focus = frame
    maximum = np.minimum(up, seconds)
    ki = np.maximum(k, 1e-300)
    peak = np.clip(1 / ki, p.tmin, np.maximum(p.tmin, maximum))
    science = np.maximum(0., p.weight * np.minimum(1., peak * k) * mult.max(axis=0) - scores) / peak
    def bonus_rate(threshold, bonus, deadline):
        earliest = np.maximum(p.tmin, np.ceil(np.maximum(0., np.asarray(threshold) - 1e-10) * safety / ki))
        return np.where((earliest <= maximum) & (earliest <= deadline), np.maximum(0., bonus) / earliest, 0.)
    bound = science
    bound += bonus_rate(p.req_threshold, missing * p.req_penalty, np.inf)
    bound += bonus_rate(p.uniform_threshold, (factors < p.uniform_threshold) * ub, np.inf)
    bound += bonus_rate(rt, rr, rd)
    bound *= np.maximum(1., urg)
    if focus is not None:
        membership, reward, left, threshold, deadline = focus
        bound += bonus_rate(threshold, membership * reward / left, deadline) * np.maximum(1., urg)
    bound = np.where((maximum >= p.tmin) & (k > 0.), bound, 0.)
    return bound + np.where(bound > 0, 1e-10, 0)


class GlobalFieldPlanner(CPUPhaseSpatialPlanner):
    def __init__(self, initial):
        super().__init__(initial)
        self.native = load_native()
        self.global_summary = dict(calls=0, searched=0, improved=0, roots=0, nodes=0,
                                  matchings=0, proposals=0, exact=0, search_seconds=0.)
        self.export_hook = None

    def choose(self, snapshot, best_scores, best_factors, env_estimate=None, active_requests=None):
        started = time.perf_counter()
        env = dict(env_estimate or {})
        env['cpu_phase_fixed_workload'] = True
        env['anchor_count'] = 24
        baseline = super().choose(snapshot, best_scores, best_factors, env, active_requests)
        self.global_summary['calls'] += 1
        frame = self._cpu_phase_frame
        if baseline is None or frame is None or os.environ.get('GLOBAL_FIELD_MODE') == 'control':
            return baseline
        if frame[14] is not None and np.any(frame[11] < 1.-1e-12):
            raise ValueError('matching upper bound requires urgency >= 1')
        upper = optimistic_rates(self, frame)
        vectors = frame[0]
        alt = np.arcsin(np.clip(vectors[:, 2], -1., 1.)) / DEG
        az = np.arctan2(vectors[:, 1], vectors[:, 0]) / DEG % 360
        useful = np.flatnonzero((alt >= self.min_alt + .04) & (frame[1] >= self.tmin) & (upper > 1e-10))
        if not len(useful):
            return baseline
        _,up,k,scores,factors,mult,missing,rr,rt,rd,ub,urg,seconds,safety,focus = frame
        membership = np.zeros(self.n)
        left,reward,threshold,deadline = 0,0.,0.,0.
        if focus is not None:
            membership,reward,left,threshold,deadline = focus
        data = np.ascontiguousarray(np.column_stack((alt[useful],az[useful],k[useful],up[useful],scores[useful],
            factors[useful],self.weight[useful],urg[useful],missing[useful],rr[useful],rt[useful],rd[useful],
            ub[useful],upper[useful],mult[:,useful].T,np.asarray(membership)[useful])), dtype=np.float64)
        base_rate = float(self.stats['selected_exact_rate'])
        keep = int(env.get('global_field_keep', 16))
        nodes = int(env.get('global_field_nodes', 1024))
        oa = float(env.get('pointing_offset_alt_deg', 0.))
        oz = float(env.get('pointing_offset_az_deg', 0.))
        lowest = max(0., oa, float(alt[useful].min()) - math.atan(self.fov / math.sqrt(2) * DEG) / DEG)
        highest = min(90., 90. + oa)
        cfg = np.ascontiguousarray([self.side,self.pitch,self.glass,self.tmin,seconds,safety,self.req_threshold,
                self.req_penalty,self.uniform_threshold,base_rate,nodes,keep,left,reward,threshold,deadline,lowest,highest], dtype=float)
        out = np.zeros((keep,3)); stats = np.zeros(5)
        search_started = time.perf_counter()
        count = self.native.global_field_search(len(data),data,cfg,out,stats)
        search_seconds = time.perf_counter()-search_started
        if count < 0:
            raise RuntimeError(f'global native search failed {count}')
        best = None
        exact = 0
        for predicted, a, z in out[:count]:
            ca = round(float(a)-oa,7)
            cz = round((float(z)-oz)%360,7)
            if not 0 <= ca <= 90:
                continue
            candidate = super()._evaluate((ca+oa,(cz+oz)%360),useful,*frame)
            exact += 1
            if candidate is not None and candidate[0] > base_rate+1e-12:
                if best is None or candidate[0] > best[0]+1e-12:
                    best = candidate
        changed = best is not None
        self.global_summary['searched'] += 1
        self.global_summary['improved'] += changed
        self.global_summary['roots'] += int(stats[0])
        self.global_summary['nodes'] += int(stats[1])
        self.global_summary['matchings'] += int(stats[4])
        self.global_summary['proposals'] += count
        self.global_summary['exact'] += exact
        self.global_summary['search_seconds'] += search_seconds
        self.stats.update(global_nodes=int(stats[1]),global_roots=int(stats[0]),global_matchings=int(stats[4]),
                          global_search_seconds=search_seconds,global_proposals=count,global_exact=exact,
                          global_improved=changed,global_base_rate=base_rate,
                          global_selected_rate=float(best[0]) if changed else base_rate,
                          planning_seconds=time.perf_counter()-started)
        if self.export_hook:
            self.export_hook(snapshot,frame,useful,upper,cfg,out[:count],self.stats,baseline,best)
        if not changed:
            return baseline
        _,center,duration,program,chosen,fibers = best
        now = parse_utc(snapshot['now_utc'])
        lst = local_sidereal(now,self.lon)
        public = self._public_quality(now,lst,alt)
        qscale = max(.005,float(env.get('quality_scale',.55)))
        bscale = max(.005,float(env.get('program_band_quality_scale',qscale/.95)))
        bands = np.where(public*bscale>=self.dark_threshold,0,np.where(public*bscale>=self.bright_threshold,1,2))
        quality = k*self.f0t0/np.maximum(self.flux,1e-12)
        tq = np.ones(self.n) if env.get('target_quality_scale') is None else np.asarray(env['target_quality_scale'])
        directional = quality/np.maximum(1e-12,public*qscale*tq)
        self.last_prediction = {self.ids[int(i)]:dict(index=int(i),fiber_id=int(f),factor=min(1.,float(k[i]*duration)),
              public_quality=float(public[i]),quality=float(quality[i]),directional_scale=float(directional[i]),
              predicted_band=PROGRAMS[int(bands[i])],alt_deg=float(alt[i]),az_deg=float(az[i])) for i,f in zip(chosen,fibers)}
        return dict(action='observe',pointing=dict(alt_deg=round(center[0]-oa,7),az_deg=round((center[1]-oz)%360,7)),
                    assignments={str(int(f)):self.ids[int(i)] for i,f in zip(chosen,fibers)},
                    duration_seconds=int(duration),program=PROGRAMS[int(program)])
