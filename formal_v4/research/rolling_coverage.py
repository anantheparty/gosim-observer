"""Public-data rolling interval/maximum-coverage optimizer.

Independent choose route. Geometry/quality are frozen over each short horizon;
the finite pool is not exhaustive and its LP is not a global competition bound.
SciPy/HiGHS is required. No truth input or remote service is accessed.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import timedelta
import math
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import coo_matrix

from .geometry import format_utc
from .spatial_candidates import SpatialPlanner, PROGRAMS, SIDEREAL_SPEED, _shift_altaz, local_sidereal, parse_utc


class RollingCoveragePlanner(SpatialPlanner):
    def __init__(self, initial, horizon=7200, step=900, centers=6, solve_seconds=.35, commit=2):
        super().__init__(initial)
        self.horizon, self.step, self.centers = int(horizon), int(step), int(centers)
        self.solve_seconds, self.commit = float(solve_seconds), int(commit)
        self.slot_seconds = int(initial['survey'].get('slot_seconds', 900))
        self.plan = []
        self.plan_signature = None
        self.plan_executed = 0
        self.total_rebuilds = self.total_mip_incumbents = self.total_fallbacks = 0
        self.total_model_seconds = 0.
        self.max_columns = self.max_layers = 0
        self.max_solver_seconds = 0.
        self.last_model_summary = {}

    def _H(self, start, duration, night_start):
        cursor, end, total = start, start + timedelta(seconds=duration), np.zeros(self.n)
        while cursor < end:
            slot = math.floor((cursor-night_start).total_seconds()/self.slot_seconds)
            stop = min(end, night_start+timedelta(seconds=(slot+1)*self.slot_seconds), cursor+timedelta(seconds=120))
            midpoint = cursor + (stop-cursor)/2
            lst = local_sidereal(midpoint, self.lon)
            alt = self._altaz(lst)[0]
            total += (stop-cursor).total_seconds()*self._public_quality(midpoint, lst, alt)*self.q0
            cursor = stop
        return total / duration

    def _quality_prefix(self, start, maximum, night_start):
        """Shared exact <=120s mesh prefixes, with an exact final partial piece."""
        cursor,end=start,start+timedelta(seconds=maximum)
        seconds=[0.];sums=[np.zeros(self.n)]
        while cursor < end:
            slot=math.floor((cursor-night_start).total_seconds()/self.slot_seconds)
            stop=min(end,night_start+timedelta(seconds=(slot+1)*self.slot_seconds),cursor+timedelta(seconds=120))
            mid=cursor+(stop-cursor)/2;lst=local_sidereal(mid,self.lon);alt=self._altaz(lst)[0]
            sums.append(sums[-1]+(stop-cursor).total_seconds()*self._public_quality(mid,lst,alt)*self.q0)
            seconds.append((stop-start).total_seconds());cursor=stop
        cache={}
        def integrated(duration):
            if duration not in cache:
                k=bisect_right(seconds,duration)-1
                total=sums[k]
                if seconds[k] < duration:
                    mid=start+timedelta(seconds=(seconds[k]+duration)/2)
                    lst=local_sidereal(mid,self.lon);alt=self._altaz(lst)[0]
                    total=total+(duration-seconds[k])*self._public_quality(mid,lst,alt)*self.q0
                cache[duration]=total/duration
            return cache[duration]
        return integrated

    def _requests(self, requests, now):
        result = []
        for r in requests or []:
            left = max(0, int(r.get('remaining_count', int(r.get('minimum_completed', 0))-int(r.get('completed_count', 0)))))
            done = set(r.get('completed_target_ids', []))
            targets = {self.index[str(t)] for t in r.get('target_ids', []) if str(t) in self.index and str(t) not in done}
            end = (parse_utc(r['deadline_utc'])-now).total_seconds()
            issued = (parse_utc(r.get('issued_at_utc', format_utc(now)))-now).total_seconds()
            if left and end >= self.tmin and targets:
                result.append({'id': str(r.get('request_id')), 'targets': targets, 'left': left,
                               'threshold': float(r.get('completion_factor_threshold', .5)),
                               'reward': float(r.get('completion_reward', 0)), 'issued': issued, 'end': end})
        return result

    def _columns(self, now, night, scores, factors, env, requests):
        end = min(self.nights[night][1], now+timedelta(seconds=self.horizon))
        length = int((end-now).total_seconds())
        C = max(.005, float(env.get('program_band_quality_scale', .68))/self.q0)
        E = max(.005, float(env.get('quality_scale', .6))/max(.005, float(env.get('program_band_quality_scale', .68))))
        target_scale = np.asarray(env.get('target_quality_scale', np.ones(self.n)), dtype=float)
        safety = max(1., float(env.get('duration_safety', 1.1)))
        req_missing = self.required & (factors < self.req_threshold)
        request_reward, request_threshold = np.zeros(self.n), np.zeros(self.n)
        for r in requests:
            idx = np.asarray(list(r['targets']), dtype=int)
            request_reward[idx] += r['reward']/r['left']
            request_threshold[idx] = np.maximum(request_threshold[idx], r['threshold'])
        columns = []
        for second in range(0, length-self.tmin+1, self.step):
            start = now+timedelta(seconds=second)
            alt, az, hour, vectors = self._altaz(local_sidereal(start, self.lon))
            up = np.where(self.hmax >= 180, 1e9, (self.hmax-hour)/SIDEREAL_SPEED)-1
            visible = (alt >= self.min_alt+.04) & (up >= self.tmin)
            H0 = self._public_quality(start, local_sidereal(start, self.lon), alt)*self.q0
            k0 = self.flux*C*E*H0*target_scale/self.f0t0
            potential = np.maximum(0, self.weight*np.minimum(1, k0*np.minimum(up, self.tmax))*self.multipliers.max()-scores)
            priority = visible*(potential+req_missing*self.req_penalty+request_reward)
            bins = np.bincount(self.space_bins, weights=priority, minlength=self.bin_count)
            anchors = []
            for b in np.argsort(bins)[-12:][::-1]:
                members = np.flatnonzero((self.space_bins == b) & (priority > 1e-9))
                if len(members):
                    anchors.append(int(members[np.argmax(priority[members])]))
            useful = np.flatnonzero(visible & (priority > 1e-9))
            centers = {}
            for anchor in anchors:
                for f in range(self.nfib):
                    row, col = divmod(f, self.side)
                    center = _shift_altaz(float(alt[anchor]), float(az[anchor]),
                        -(row-(self.side-1)/2)*self.pitch, -(col-(self.side-1)/2)*self.pitch)
                    if not 0 <= center[0] <= 90:
                        continue
                    a, z = math.radians(center[0]), math.radians(center[1])
                    vec = np.array([math.cos(a)*math.cos(z), math.cos(a)*math.sin(z), math.sin(a)])
                    near = useful[np.sum(vectors[useful]*vec, axis=1) >= math.cos(math.radians(self.fov*math.sqrt(2)/2+.05))]
                    fibers, valid, _ = self._classify(vectors[near], *center)
                    idx, fibers = near[valid], fibers[valid]
                    maxima = np.zeros(self.nfib)
                    np.maximum.at(maxima, fibers, priority[idx])
                    centers[tuple(round(x, 7) for x in center)] = (float(maxima.sum()), idx, fibers)
            ranked = sorted(centers.items(), key=lambda item:-item[1][0])[:self.centers]
            integrated=self._quality_prefix(start,min(self.tmax,length-second),self.nights[night][0])
            for center, (_, idx, fibers) in ranked:
                max_d = min(self.tmax, length-second, int(np.max(up[idx]))) if len(idx) else 0
                if max_d < self.tmin:
                    continue
                # Public target-derived breakpoints plus fixed coarse durations.
                thresholds = np.maximum(self.req_threshold*req_missing[idx], request_threshold[idx])
                times = [self.tmin, min(max_d, 900), min(max_d, 1800), max_d]
                positive = k0[idx] > 1e-12
                breaks = np.concatenate((safety/np.maximum(k0[idx][positive], 1e-12),
                                         thresholds[positive]*safety/np.maximum(k0[idx][positive], 1e-12)))
                breaks = breaks[(breaks >= self.tmin) & (breaks <= max_d)]
                if len(breaks):
                    times.extend(np.quantile(breaks, [0, .5, 1]).tolist())
                durations = sorted({min(max_d, max(self.tmin, int(math.ceil(t)))) for t in times})
                for duration in durations:
                    H = integrated(duration)
                    raw = np.minimum(1, self.flux*duration*C*E*H*target_scale/self.f0t0)
                    conservative = raw/safety
                    bands = np.where(C*H >= self.dark_threshold, 0, np.where(C*H >= self.bright_threshold, 1, 2))
                    eligible = up[idx] >= duration
                    ids, fs = idx[eligible], fibers[eligible]
                    for program in range(3):
                        values = self.weight[ids]*raw[ids]*np.where(bands[ids] == program, self.multipliers[program], self.mismatch)
                        gains = np.maximum(0, values-scores[ids])
                        local = gains+self.req_penalty*req_missing[ids]*(conservative[ids] >= self.req_threshold)
                        for r in requests:
                            if second >= r['issued'] and second+duration <= r['end']:
                                local += np.asarray([i in r['targets'] for i in ids])* (conservative[ids] >= r['threshold'])*r['reward']/r['left']
                        chosen = [int(avail[np.argmax(local[avail])]) for f in np.unique(fs)
                                  if len(avail := np.flatnonzero(fs == f)) and float(np.max(local[avail])) > 1e-9]
                        if not chosen:
                            continue
                        selected = ids[chosen]
                        columns.append({'start': second, 'end': second+duration, 'center': center,
                            'program': program, 'targets': selected.tolist(), 'fibers': fs[chosen].tolist(),
                            'gains': gains[chosen].tolist(), 'factors': conservative[selected].tolist(),
                            'raw': raw[selected].tolist(), 'H': H[selected].tolist(),
                            'target_scale': target_scale[selected].tolist(),
                            'science_floor': scores[selected].tolist(), 'predicted_scores': values[chosen].tolist(),
                            'alt': alt[selected].tolist(), 'az': az[selected].tolist(),
                            'band': bands[selected].tolist()})
        return columns, C, E, req_missing

    def _model(self, columns, req_missing, requests):
        levels = {}
        for c in columns:
            for i, g in zip(c['targets'], c['gains']):
                if g > 1e-10:
                    levels.setdefault(i, set()).add(float(g))
        layers, weight, sci = [], [], {}
        for i, vals in sorted(levels.items()):
            vals = sorted(vals)
            # Keep at most eight science levels: a lower approximation for each
            # candidate gain. Actual candidate schedules are evaluated unrounded.
            if len(vals) > 8:
                vals = [vals[k] for k in np.unique(np.rint(np.linspace(0, len(vals)-1, 8)).astype(int))]
            previous = 0.
            sci[i] = []
            for value in vals:
                sci[i].append((value, len(layers))); layers.append(('s', i)); weight.append(value-previous); previous=value
        required = {}
        for i in sorted({i for c in columns for i in c['targets'] if req_missing[i]}):
            required[i] = len(layers); layers.append(('r', i)); weight.append(self.req_penalty)
        request_layers, quotas = [], []
        for r in requests:
            mapping = {i:len(layers)+k for k, i in enumerate(sorted(r['targets']))}
            layers.extend(('q', (r['id'], i)) for i in sorted(r['targets']))
            weight.extend([0.]*len(mapping)); request_layers.append(mapping); quotas.append(r)
        covered = []
        for c in columns:
            js = []
            for i, g, f in zip(c['targets'], c['gains'], c['factors']):
                js.extend(j for v,j in sci.get(i, []) if v <= g)
                if i in required and f >= self.req_threshold:
                    js.append(required[i])
                for r, mapping in zip(quotas, request_layers):
                    if i in mapping and f >= r['threshold'] and c['start'] >= r['issued'] and c['end'] <= r['end']:
                        js.append(mapping[i])
            covered.append(js)
        endpoints = sorted({v for c in columns for v in (c['start'], c['end'])})
        mids = [(a+b)/2 for a,b in zip(endpoints,endpoints[1:])]
        ne,nl,nq = len(columns),len(layers),len(quotas)
        rows,cols,data=[],[],[]
        times=[]
        for e,(c,js) in enumerate(zip(columns,covered)):
            rows.extend(js);cols.extend([e]*len(js));data.extend([-1.]*len(js))
            ts=[t for t,v in enumerate(mids) if c['start'] <= v < c['end']];times.append(ts)
            rows.extend(nl+t for t in ts);cols.extend([e]*len(ts));data.extend([1.]*len(ts))
        rows.extend(range(nl));cols.extend(ne+j for j in range(nl));data.extend([1.]*nl)
        for q,(r,mapping) in enumerate(zip(quotas,request_layers)):
            row=nl+len(mids)+q
            rows.extend([row]*len(mapping));cols.extend(ne+j for j in mapping.values());data.extend([-1.]*len(mapping))
            rows.append(row);cols.append(ne+nl+q);data.append(float(r['left']))
        A=coo_matrix((data,(rows,cols)),shape=(nl+len(mids)+nq,ne+nl+nq)).tocsr()
        rhs=np.concatenate((np.zeros(nl),np.ones(len(mids)),np.zeros(nq)))
        obj=-np.concatenate((np.zeros(ne),np.asarray(weight),np.asarray([r['reward'] for r in quotas])))
        return A,rhs,obj,np.asarray(weight),covered,times,nl,nq

    def _value(self, selected, columns, req_missing, requests):
        gains, factors=np.zeros(self.n),np.zeros(self.n)
        reached=[set() for _ in requests]
        for e in selected:
            c=columns[e];np.maximum.at(gains,c['targets'],c['gains']);np.maximum.at(factors,c['targets'],c['factors'])
            for q,r in enumerate(requests):
                if c['start'] >= r['issued'] and c['end'] <= r['end']:
                    reached[q].update(i for i,f in zip(c['targets'],c['factors']) if i in r['targets'] and f >= r['threshold'])
        return float(gains.sum()+self.req_penalty*np.count_nonzero(req_missing & (factors >= self.req_threshold))
                     +sum(r['reward'] for r,s in zip(requests,reached) if len(s) >= r['left']))

    def _dp(self, columns, values):
        order=sorted(range(len(columns)),key=lambda e:columns[e]['end'])
        ends=[columns[e]['end'] for e in order];best=[0.]*(len(order)+1);take=[False]*len(order);pred=[]
        for k,e in enumerate(order):
            p=bisect_right(ends,columns[e]['start'],0,k);pred.append(p)
            if best[p]+values[e] > best[k]:
                best[k+1]=best[p]+values[e];take[k]=True
            else:best[k+1]=best[k]
        chosen=[];k=len(order)
        while k:
            if take[k-1]:chosen.append(order[k-1]);k=pred[k-1]
            else:k-=1
        return sorted(chosen,key=lambda e:columns[e]['start'])

    def _solve(self, columns, req_missing, requests):
        A,rhs,obj,weights,covered,times,nl,nq=self._model(columns,req_missing,requests)
        ne=len(columns);nv=len(obj);solutions=[]
        solver_start=time.perf_counter()
        lp=linprog(obj,A_ub=A,b_ub=rhs,bounds=(0,1),method='highs',options={'time_limit':self.solve_seconds})
        if lp.success:
            prices=np.maximum(0,-lp.ineqlin.marginals[:nl])
            solutions.append(self._dp(columns,[sum(prices[j] for j in js) for js in covered]))
        solutions.append(self._dp(columns,[sum(weights[j] for j in js) for js in covered]))
        mip=milp(obj,integrality=np.concatenate((np.ones(ne),np.zeros(nl),np.ones(nq))),
            bounds=Bounds(np.zeros(nv),np.ones(nv)),constraints=LinearConstraint(A,-np.inf,rhs),
            options={'time_limit':self.solve_seconds,'mip_rel_gap':.025})
        if mip.x is not None and np.max(np.abs(mip.x[:ne]-np.rint(mip.x[:ne]))) < 1e-5:
            solutions.append(sorted(np.flatnonzero(mip.x[:ne]>.5).tolist(),key=lambda e:columns[e]['start']))
            self.total_mip_incumbents+=1
        else:self.total_fallbacks+=1
        selected=max(solutions,key=lambda s:self._value(s,columns,req_missing,requests))
        assert all(columns[a]['end'] <= columns[b]['start'] for a,b in zip(selected,selected[1:]))
        seconds=time.perf_counter()-solver_start
        self.max_solver_seconds=max(self.max_solver_seconds,seconds)
        self.max_columns=max(self.max_columns,ne);self.max_layers=max(self.max_layers,nl)
        self.last_model_summary={'columns':ne,'layers':nl,'nonzeros':int(A.nnz),'solver_seconds':seconds,
            'lp_success':bool(lp.success),'mip_status':int(mip.status),'mip_incumbent':mip.x is not None,
            'feasible_frozen_utility':self._value(selected,columns,req_missing,requests)}
        return [columns[e] for e in selected]

    def choose(self,snapshot,best_scores,best_factors,env_estimate=None,active_requests=None):
        started=time.perf_counter();env=env_estimate or {};now=parse_utc(snapshot['now_utc'])
        night=next((k for k,(a,b) in enumerate(self.nights) if a <= now < b),None)
        if night is None:return None
        scores,factors=self._array(best_scores),self._array(best_factors)
        requests=self._requests(active_requests if active_requests is not None else snapshot.get('active_requests',[]),now)
        C=float(env.get('program_band_quality_scale',.68))/self.q0
        E=float(env.get('quality_scale',.6))/max(.005,float(env.get('program_band_quality_scale',.68)))
        signature=(night,tuple((r['id'],r['left']) for r in requests),C,E,
                   float(scores.sum()),float(factors.sum()),float(env.get('pointing_offset_alt_deg',0)),float(env.get('pointing_offset_az_deg',0)))
        old=self.plan_signature
        changed=old is None or signature[:2] != old[:2] or abs(C-old[2]) > .35*max(.1,old[2]) or abs(E-old[3]) > .15
        changed=changed or (old is not None and (signature[4]<old[4]-1e-7 or signature[5]<old[5]-1e-7 or abs(signature[6]-old[6])+abs(signature[7]-old[7])>.03))
        changed=changed or any(m.get('record_type') == 'state_resync' for m in snapshot.get('new_messages',[]))
        if self.plan and self.plan[0]['absolute_start'] < now:changed=True
        if not self.plan or changed or self.plan_executed >= self.commit:
            columns,C,E,missing=self._columns(now,night,scores,factors,env,requests)
            self.plan=self._solve(columns,missing,requests) if columns else []
            for c in self.plan:
                c['absolute_start']=now+timedelta(seconds=c['start'])
                c['frozen_C'],c['frozen_E']=C,E
            self.plan_signature=signature;self.plan_executed=0;self.total_rebuilds+=1
        self.stats={'planning_seconds':time.perf_counter()-started,**self.last_model_summary,'rolling_rebuilds':self.total_rebuilds}
        self.total_model_seconds+=self.stats['planning_seconds']
        self.last_prediction={}
        if not self.plan:return None
        c=self.plan[0]
        if c['absolute_start'] > now:
            return {'action':'wait','until_utc':format_utc(c['absolute_start'])}
        self.plan.pop(0);self.plan_executed+=1
        C,E=c['frozen_C'],c['frozen_E']
        offset_alt=float(env.get('pointing_offset_alt_deg',0));offset_az=float(env.get('pointing_offset_az_deg',0))
        if not 0 <= c['center'][0]-offset_alt <= 90:return None
        self.last_prediction={self.ids[i]:{'index':int(i),'fiber_id':int(f),'factor':float(raw),
            'public_quality':float(H/self.q0),'quality':float(C*E*H*scale),
            'frozen_C':float(C),'frozen_E':float(E),'target_scale':float(scale),
            'science_floor_at_build':float(floor),'science_floor_now':float(scores[i]),'predicted_score':float(value),
            'alt_deg':float(alt),'az_deg':float(az),'predicted_band':PROGRAMS[int(band)]}
            for i,f,raw,H,scale,floor,value,alt,az,band in zip(c['targets'],c['fibers'],c['raw'],c['H'],c['target_scale'],
                c['science_floor'],c['predicted_scores'],c['alt'],c['az'],c['band'])}
        return {'action':'observe','pointing':{'alt_deg':round(c['center'][0]-offset_alt,7),'az_deg':round((c['center'][1]-offset_az)%360,7)},
            'assignments':{str(f):self.ids[i] for i,f in zip(c['targets'],c['fibers'])},
            'duration_seconds':int(c['end']-c['start']),'program':PROGRAMS[c['program']]}

    def rolling_summary(self):
        return {'rebuilds':self.total_rebuilds,'mip_incumbents':self.total_mip_incumbents,'dp_fallbacks':self.total_fallbacks,
                'max_columns':self.max_columns,'max_layers':self.max_layers,'max_solver_seconds':self.max_solver_seconds,
                'total_planning_seconds':self.total_model_seconds,'configuration':{'horizon':self.horizon,'step':self.step,
                'centers':self.centers,'solve_seconds':self.solve_seconds,'commit':self.commit}}
