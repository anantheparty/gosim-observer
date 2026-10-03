"""Online nonoverlapping reservations for single-exposure required jobs.

Only initialization, revealed messages, catalogue geometry and caller belief are
used. The matching is exact for a conservative hour-block calendar; weather and
the sampled single-exposure durations are conditional predictions. This is a
scheduling construction, not a whole-survey bound or scalar urgency rule.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import numpy as np

from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
from research.spatial_candidates import DEG, PROGRAMS, parse_utc, local_sidereal, _shift_altaz


def rectangular_assignment(cost):
    """Shortest augmenting paths for a rectangular minimum-cost matching.

    Rows <= columns. The vectorized potentials implementation needs only NumPy.
    Returns the unique selected column of each row, including supplied dummies.
    """
    cost = np.asarray(cost, dtype=float)
    nr, nc = cost.shape
    if nr > nc:
        raise ValueError("assignment needs at least as many columns as rows")
    u = np.zeros(nr + 1)
    v = np.zeros(nc + 1)
    p = np.zeros(nc + 1, dtype=int)
    way = np.zeros(nc + 1, dtype=int)
    for i in range(1, nr + 1):
        p[0] = i
        j0 = 0
        minimum = np.full(nc + 1, np.inf)
        used = np.zeros(nc + 1, dtype=bool)
        while True:
            used[j0] = True
            i0 = p[j0]
            unused = np.flatnonzero(~used[1:]) + 1
            cur = cost[i0 - 1, unused - 1] - u[i0] - v[unused]
            improve = cur < minimum[unused]
            js = unused[improve]
            minimum[js] = cur[improve]
            way[js] = j0
            j1 = int(unused[np.argmin(minimum[unused])])
            delta = minimum[j1]
            u[p[used]] += delta
            v[used] -= delta
            minimum[~used] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    answer = np.full(nr, -1, dtype=int)
    for j in range(1, nc + 1):
        if p[j]:
            answer[p[j] - 1] = j - 1
    return answer


class RequiredCalendar:
    def __init__(self, planner, *, favorable_scale=.85, hard_duration=1200,
                 scarce_blocks=6, start_step=300, safety=1.12, early_cost=120.):
        self.p = planner
        self.required = np.flatnonzero(planner.required)
        self.favorable_scale = float(favorable_scale)
        self.hard_duration = float(hard_duration)
        self.scarce_blocks = int(scarce_blocks)
        self.start_step = int(start_step)
        self.safety = float(safety)
        self.early_cost = float(early_cost)
        self.blocks = []
        # Anchor from dawn backwards: a late rising target receives a full final
        # block, rather than an arbitrary short remainder at the end of a night.
        for night, (a, b) in enumerate(planner.nights):
            a, b = a.timestamp(), b.timestamp()
            edges = sorted(set([a, b] + np.arange(b - 3600, a, -3600).tolist()))
            self.blocks.extend((night, x, y) for x, y in zip(edges, edges[1:]))
        self.blocks = np.asarray(self.blocks, dtype=float)
        self.profiles = [self._profile(k) for k in range(len(planner.nights))]
        self.duration = None
        self.start = None
        self.profile_efficiency = None
        self.blocked = set()
        self.plan = []
        self.last_night = -1
        self.summary = dict(graph_builds=0, matches=0, hard_jobs=0, reservations=0,
                            unmatched=0, force_actions=0, barriers=0, failed_due=0,
                            build_seconds=0., matching_seconds=0., forced_ids=[])
        self.history = []

    def _altitude(self, times):
        p = self.p
        t = np.asarray(times, dtype=float)
        lst = (280.46061837 + 360.98564736629 * (t / 86400 + 2440587.5 - 2451545) + p.lon) % 360
        hour = (lst[:, None] - p.ra[self.required][None, :] + 180) % 360 - 180
        sine = p.sin_lat * p.sin_dec[self.required][None, :] + p.cos_lat * p.cos_dec[self.required][None, :] * np.cos(hour * DEG)
        return np.arcsin(np.clip(sine, -1, 1)) / DEG

    def _quality(self, times):
        """Public lunar/airmass quality, vectorized only over required targets."""
        p = self.p
        times = np.asarray(times, dtype=float)
        days = times / 86400 + 2440587.5 - 2451545
        solar_mean = (280.460 + .9856474 * days) % 360
        anomaly = ((357.528 + .9856003 * days) % 360) * DEG
        slon = (solar_mean + 1.915 * np.sin(anomaly) + .020 * np.sin(2 * anomaly)) * DEG
        ob = (23.439 - .0000004 * days) * DEG
        sun = np.stack((np.cos(slon), np.sin(slon) * np.cos(ob), np.sin(slon) * np.sin(ob)), axis=1)
        lon = ((218.316 + 13.176396 * days) % 360) * DEG + 6.289 * DEG * np.sin(((134.963 + 13.064993 * days) % 360) * DEG)
        lat = 5.128 * DEG * np.sin(((93.272 + 13.229350 * days) % 360) * DEG)
        moon = np.stack((np.cos(lon) * np.cos(lat), np.sin(lon) * np.cos(lat) * np.cos(ob) - np.sin(lat) * np.sin(ob),
                         np.sin(lon) * np.cos(lat) * np.sin(ob) + np.sin(lat) * np.cos(ob)), axis=1)
        illumination = (1 - np.sum(sun * moon, axis=1)) / 2
        mdec = np.arcsin(np.clip(moon[:, 2], -1, 1))
        mra = np.arctan2(moon[:, 1], moon[:, 0]) / DEG % 360
        lst = (280.46061837 + 360.98564736629 * days + p.lon) % 360
        malt = np.arcsin(np.clip(p.sin_lat * np.sin(mdec) + p.cos_lat * np.cos(mdec) * np.cos(((lst - mra + 180) % 360 - 180) * DEG), -1, 1))
        sep = np.arccos(np.clip(np.einsum('ij,kj->ik', moon, p.eq_vectors[self.required]), -1, 1)) / DEG
        lunar = 1 - float(p.lunar['maximum_penalty']) * illumination[:, None] * np.maximum(0, np.sin(malt))[:, None] ** float(p.lunar['altitude_exponent']) * np.exp(-sep / float(p.lunar['angular_decay_scale_deg']))
        lunar[malt <= 0] = 1
        alt = self._altitude(times)
        zenith = 90 - np.maximum(alt, 1.)
        airmass = (1 / (np.cos(zenith * DEG) + .50572 * (96.07995 - zenith) ** -1.6364)) / (1 / (1 + .50572 * 96.07995 ** -1.6364))
        return np.clip(lunar, 0, 1) / (p.q0 * airmass ** p.airmass_exponent)

    def _profile(self, night):
        a, b = (t.timestamp() for t in self.p.nights[night])
        nodes = np.unique(np.r_[np.arange(a, b, 120), b])
        q = self._quality((nodes[:-1] + nodes[1:]) / 2)
        prefix = np.vstack((np.zeros(len(self.required)), np.cumsum(np.diff(nodes)[:, None] * q, axis=0)))
        return nodes, prefix

    def _prefix_at(self, nodes, prefix, t):
        j = max(0, min(len(nodes) - 2, int(np.searchsorted(nodes, t, side='right')) - 1))
        return prefix[j] + (prefix[j + 1] - prefix[j]) * (t - nodes[j]) / (nodes[j + 1] - nodes[j])

    def build(self, efficiency):
        started = time.perf_counter()
        p = self.p
        nr, nb = len(self.required), len(self.blocks)
        self.duration = np.full((nr, nb), np.inf)
        self.start = np.full((nr, nb), np.inf)
        scale = self.favorable_scale * max(.35, float(efficiency)) / .95
        need = p.req_threshold * p.f0t0 * self.safety / (p.flux[self.required] * scale)
        for bindex, (night, a, b) in enumerate(self.blocks):
            nodes, prefix = self.profiles[int(night)]
            right = int(np.searchsorted(nodes, b, side='right'))
            for start in np.arange(a, b - p.tmin + 1, self.start_step):
                mass = self._prefix_at(nodes, prefix, start) + need
                left = max(0, int(np.searchsorted(nodes, start, side='right')) - 1)
                piece = prefix[left:right]
                offsets = np.sum(piece < mass[None, :], axis=0)
                good = (offsets > 0) & (offsets < len(piece))
                jobs = np.flatnonzero(good)
                if not len(jobs):
                    continue
                hi = left + offsets[jobs]
                lo = hi - 1
                ends = nodes[lo] + (mass[jobs] - prefix[lo, jobs]) / np.maximum(1e-12, prefix[hi, jobs] - prefix[lo, jobs]) * (nodes[hi] - nodes[lo])
                duration = np.ceil(ends - start)
                end_alt = np.diag(self._altitude(start + duration)[:, jobs])
                start_alt = self._altitude([start])[0, jobs]
                feasible = (duration >= p.tmin) & (duration <= p.tmax) & (start + duration <= b + 1e-7) & (start_alt >= p.min_alt + .04) & (end_alt >= p.min_alt + .04)
                jobs, duration = jobs[feasible], duration[feasible]
                better = duration < self.duration[jobs, bindex]
                self.duration[jobs[better], bindex] = duration[better]
                self.start[jobs[better], bindex] = start
        self.profile_efficiency = efficiency
        self.summary['graph_builds'] += 1
        self.summary['build_seconds'] += time.perf_counter() - started

    def match(self, now, factors, efficiency):
        started = time.perf_counter()
        if self.duration is None or abs(efficiency - self.profile_efficiency) > .08:
            self.build(efficiency)
        p = self.p
        remaining = self.blocks[:, 2] > now
        feasible = np.isfinite(self.duration) & remaining[None, :]
        for j, b in self.blocked:
            feasible[j, b] = False
        minimum = np.min(np.where(feasible, self.duration, np.inf), axis=1)
        alternatives = feasible.sum(axis=1)
        missing = factors[self.required] + 1e-8 < p.req_threshold
        hard = np.flatnonzero(missing & (alternatives > 0) & ((minimum >= self.hard_duration) | (alternatives <= self.scarce_blocks)))
        if not len(hard):
            self.plan = []
            return
        blocks = np.flatnonzero(remaining & np.any(feasible[hard], axis=0))
        duration = self.duration[np.ix_(hard, blocks)]
        earliest = np.maximum(0., self.blocks[blocks, 1] - now) / 86400
        # The dummy price first maximizes scheduled jobs. Among full matchings,
        # shorter exposures and earlier opportunities reduce weather risk.
        cost = np.where(feasible[np.ix_(hard, blocks)], duration + self.early_cost * earliest[None, :], 1e9)
        dummies = np.full((len(hard), len(hard)), 1e7)
        assignment = rectangular_assignment(np.c_[cost, dummies])
        plan = []
        for row, col in enumerate(assignment):
            if col < len(blocks) and cost[row, col] < 1e7:
                j, b = int(hard[row]), int(blocks[col])
                plan.append(dict(job=j, target=int(self.required[j]), block=b,
                                 start=float(self.start[j, b]), end=float(self.start[j, b] + self.duration[j, b]),
                                 duration=int(self.duration[j, b]), night=int(self.blocks[b, 0])))
        self.plan = sorted(plan, key=lambda x: (x['start'], x['target']))
        self.summary.update(hard_jobs=len(hard), reservations=len(plan), unmatched=len(hard) - len(plan))
        self.summary['matches'] += 1
        self.summary['matching_seconds'] += time.perf_counter() - started
        self.history.append(dict(now=now, hard_jobs=len(hard), matched=len(plan), unmatched=len(hard) - len(plan),
                                 reservations=[dict(x, target_id=p.ids[x['target']]) for x in self.plan]))


class RequiredAllocationPlanner(CPUPhaseSpatialPlanner):
    """Keep the complete CPUPhase action, execute matched reservation barriers."""
    def __init__(self, initial_payload, config=None):
        super().__init__(initial_payload)
        self.calendar = RequiredCalendar(self, **(config or {}))

    def _complete_in(self, action, frame, target):
        return (action is not None and self.ids[target] in action.get('assignments', {}).values()
                and action['duration_seconds'] * frame[2][target] / self.calendar.safety >= self.req_threshold - 1e-10)

    def _forced(self, snapshot, frame, target, env, barrier=None):
        vectors, up, k = frame[:3]
        limit = frame[12] if barrier is None else min(frame[12], int(barrier))
        if k[target] <= 0 or math.ceil(self.req_threshold * self.calendar.safety / k[target]) > min(up[target], limit):
            return None
        alt = np.arcsin(np.clip(vectors[:, 2], -1, 1)) / DEG
        az = np.arctan2(vectors[:, 1], vectors[:, 0]) / DEG % 360
        pool = np.flatnonzero((vectors[:, 2] >= math.sin((self.min_alt + .04) * DEG)) &
                              (vectors @ vectors[target] >= math.cos((self.fov * math.sqrt(2) + .3) * DEG)))
        forced_frame = list(frame)
        forced_frame[11] = frame[11].copy()
        forced_frame[11][target] *= 1e6
        forced_frame[12] = limit
        forced_frame[13] = max(float(frame[13]), self.calendar.safety)
        best = None
        for f in range(self.nfib):
            r, c = divmod(f, self.side)
            center = _shift_altaz(alt[target], az[target], -(r - (self.side - 1) / 2) * self.pitch, -(c - (self.side - 1) / 2) * self.pitch)
            if not 0 <= center[0] - float(env.get('pointing_offset_alt_deg', 0.)) <= 90:
                continue
            candidate = super(CPUPhaseSpatialPlanner, self)._evaluate(center, pool, *forced_frame)
            if candidate is not None and target in candidate[4] and (best is None or candidate[0] > best[0]):
                best = candidate
        if best is None:
            return None
        _, center, duration, program, chosen, fibers = best
        now = parse_utc(snapshot['now_utc'])
        public_quality = self._public_quality(now, local_sidereal(now, self.lon), alt)
        scale = max(.005, float(env.get('quality_scale', .55)))
        band_scale = max(.005, float(env.get('program_band_quality_scale', scale / .95)))
        actual = np.where(public_quality * band_scale >= self.dark_threshold, 0, np.where(public_quality * band_scale >= self.bright_threshold, 1, 2))
        target_scale = np.ones(self.n) if env.get('target_quality_scale') is None else np.asarray(env['target_quality_scale'], dtype=float)
        quality = k * self.f0t0 / np.maximum(self.flux, 1e-12)
        directional = quality / np.maximum(1e-12, public_quality * scale * target_scale)
        self.last_prediction = {self.ids[int(i)]: dict(index=int(i), fiber_id=int(f), factor=min(1., float(k[i] * duration)),
                              public_quality=float(public_quality[i]), quality=float(quality[i]), directional_scale=float(directional[i]),
                              predicted_band=PROGRAMS[int(actual[i])], alt_deg=float(alt[i]), az_deg=float(az[i])) for i, f in zip(chosen, fibers)}
        return dict(action='observe', pointing=dict(alt_deg=round(center[0] - float(env.get('pointing_offset_alt_deg', 0.)), 7),
                    az_deg=round((center[1] - float(env.get('pointing_offset_az_deg', 0.))) % 360, 7)),
                    assignments={str(int(f)): self.ids[int(i)] for i, f in zip(chosen, fibers)}, duration_seconds=int(duration), program=PROGRAMS[int(program)])

    def choose(self, snapshot, scores, factors, env_estimate=None, active_requests=None):
        started = time.perf_counter()
        env = dict(env_estimate or {})
        action = super().choose(snapshot, scores, factors, env, active_requests)
        frame = self._cpu_phase_frame
        if action is None or frame is None:
            return action
        factors = self._array(factors)
        now = parse_utc(snapshot['now_utc']).timestamp()
        night = next(k for k, (a, b) in enumerate(self.nights) if a.timestamp() <= now < b.timestamp())
        efficiency = float(env.get('quality_scale', .55)) / max(.005, float(env.get('program_band_quality_scale', .55 / .95)))
        cal = self.calendar
        if night != cal.last_night:
            cal.blocked = {(j, b) for j, b in cal.blocked if cal.blocks[b, 2] > now}
            cal.match(now, factors, efficiency)
            cal.last_night = night
        cal.plan = [x for x in cal.plan if factors[x['target']] + 1e-8 < self.req_threshold and cal.blocks[x['block'], 2] > now]
        for attempt in range(2):
            relevant = [x for x in cal.plan if x['night'] == night]
            if not relevant:
                break
            reserved = relevant[0]
            target = reserved['target']
            if self._complete_in(action, frame, target):
                break
            gap = int(math.floor(reserved['start'] - now))
            if gap >= self.tmin:
                if action['duration_seconds'] > gap:
                    action = {**action, 'duration_seconds': gap}
                    for row in self.last_prediction.values():
                        row['factor'] = min(1., float(frame[2][row['index']] * gap))
                    cal.summary['barriers'] += 1
                break
            next_barrier = min([x['start'] - now for x in relevant[1:]] or [frame[12]])
            forced = self._forced(snapshot, frame, target, env, next_barrier)
            if forced is not None:
                action = forced
                cal.summary['force_actions'] += 1
                cal.summary['forced_ids'].append(dict(target_id=self.ids[target], now_utc=snapshot['now_utc'], duration=action['duration_seconds']))
                break
            cal.blocked.add((reserved['job'], reserved['block']))
            cal.summary['failed_due'] += 1
            cal.match(now, factors, efficiency)
        self.stats['planning_seconds'] = time.perf_counter() - started
        return action
