"""Finite-column full-deadline request scheduling over an exact small-mask DAG.

Quality and the opportunity price are frozen estimates, not global certificates.
The DP counts distinct request targets and sums scientific regret, never science.
"""
from __future__ import annotations

import math
import time
from datetime import timedelta

import numpy as np

from .spatial_candidates import (SpatialPlanner, DEG, PROGRAMS, parse_utc,
                                 local_sidereal, SIDEREAL_SPEED, _shift_altaz, _sun_moon, _wrap180)
from .request_mask_dp import RequestColumn, solve_request_columns, compare_request_reward


class _SciencePricePlanner(SpatialPlanner):
    """Fixed-size CPU science-only candidate family for a time price estimate."""
    def __init__(self, initial):
        super().__init__(initial)
        self.req_penalty = self.uniform_weight = 0.
        self.frame = None
        self.fixed_k = self.fixed_multiplier = None

    def _evaluate(self, *args, **kwargs):
        if self.frame is None:
            self.frame = args[2:]
        if self.fixed_k is not None:
            args = list(args)
            args[4] = self.fixed_k
            args[7] = self.fixed_multiplier
            args[13] = np.ones(self.n)
            args = tuple(args)
        return super()._evaluate(*args, **kwargs)

    def fixed_value(self,now,duration,scores,factors,env,public_quality):
        """Fixed finite baseline family, same integrated Q and duration as REQ."""
        scale = np.full(self.n,max(.005,float(env.get("quality_scale",.55))))
        if env.get("target_quality_scale") is not None:scale*=np.asarray(env["target_quality_scale"])
        self.fixed_k = self.flux*public_quality*scale/self.f0t0
        band_scale = max(.005,float(env.get("program_band_quality_scale",float(env.get("quality_scale",.55))/.95)))
        bands = np.where(public_quality*band_scale>=self.dark_threshold,0,np.where(public_quality*band_scale>=self.bright_threshold,1,2))
        self.fixed_multiplier = np.asarray([np.where(bands==p,self.multipliers[p],self.mismatch) for p in range(3)])
        original = self.tmin,self.tmax
        self.tmin=self.tmax=int(duration)
        try:
            action = super().choose({"now_utc":now.isoformat()},scores,factors,
                {**env,"anchor_count":int(env.get("request_dp_price_anchors",2)),"planning_budget_seconds":10000},[])
            if action is None:return 0.
            idx = np.asarray([self.index[t] for t in action["assignments"].values()],dtype=int)
            program = PROGRAMS.index(action["program"])
            raw = np.minimum(1.,self.fixed_k[idx]*duration)
            return float(np.maximum(0.,self.weight[idx]*raw*self.fixed_multiplier[program,idx]-scores[idx]).sum())
        finally:
            self.tmin,self.tmax=original
            self.fixed_k=self.fixed_multiplier=None

    def price(self, now, scores, factors, env):
        self.frame = None
        action = super().choose({"now_utc":now.isoformat()}, scores, factors,
                                {**env,"anchor_count":int(env.get("request_dp_price_anchors",2)),
                                 "planning_budget_seconds":10000}, [])
        if action is None:
            if self.frame is None:
                lst = local_sidereal(now,self.lon)
                alt,az,hour,vectors = self._altaz(lst)
                up = np.where(self.hmax>=180,1e9,(self.hmax-hour)/SIDEREAL_SPEED)
                scale = np.full(self.n,max(.005,float(env.get("quality_scale",.55))))
                if env.get("target_quality_scale") is not None:scale*=np.asarray(env["target_quality_scale"])
                k = self.flux*self._public_quality(now,lst,alt)*scale/self.f0t0
                self.frame = (vectors,np.maximum(0.,up-1),k)
            return 0., self.frame
        ids = list(action["assignments"].values())
        idx = np.asarray([self.index[t] for t in ids],dtype=int)
        program = PROGRAMS.index(action["program"])
        multipliers = self.frame[5]
        raw = np.asarray([self.last_prediction[t]["factor"] for t in ids])
        gain = np.maximum(0.,self.weight[idx]*raw*multipliers[program,idx]-scores[idx]).sum()
        return float(gain/action["duration_seconds"]), self.frame


class RequestDeadlineMixin:
    """Same choose interface; request_dp_mode='bypass' retains the baseline.

    Public future geometry is deterministic; scalar weather/instrument quality
    and per-target direction scales are frozen at column construction. Event
    starts use public night slots plus the current instant. Cached columns are
    re-solved with actual quota progress and refreshed after quality drift.
    """
    def __init__(self, initial):
        super().__init__(initial)
        self._price_planner = _SciencePricePlanner(initial)
        self._request_pools = {}
        self._build_geometry = self._build_quality = None
        self._request_counts = {"builds":0,"build_seconds":0.,"dp_solves":0,"dp_seconds":0.,
                                "request_observes":0,"boundary_waits":0,"clipped_baselines":0,
                                "rejected_by_cost":0,"infeasible":0,"forecast_failures":0}

    def _subset_public_quality(self, moment, idx):
        lst = local_sidereal(moment,self.lon)
        hour = _wrap180(lst-self.ra[idx])
        sin_alt = self.sin_lat*self.sin_dec[idx]+self.cos_lat*self.cos_dec[idx]*np.cos(hour*DEG)
        alt = np.arcsin(np.clip(sin_alt,-1,1))/DEG
        zenith = 90-np.maximum(alt,1.)
        raw = 1/(np.cos(zenith*DEG)+.50572*(96.07995-zenith)**-1.6364)
        zenith_raw = 1/(1+.50572*96.07995**-1.6364)
        airmass = raw/zenith_raw
        moon,illumination = _sun_moon(moment)
        mdec = math.asin(float(np.clip(moon[2],-1,1)))
        mra = math.atan2(moon[1],moon[0])/DEG%360
        malt = math.asin(self.sin_lat*math.sin(mdec)+self.cos_lat*math.cos(mdec)*math.cos(_wrap180(lst-mra)*DEG))
        lunar = np.ones(len(idx))
        if malt>0:
            sep = np.arccos(np.clip(self.eq_vectors[idx]@moon,-1,1))/DEG
            lunar -= float(self.lunar.get("maximum_penalty",.5))*illumination*math.sin(malt)**float(self.lunar.get("altitude_exponent",1))*np.exp(-sep/float(self.lunar.get("angular_decay_scale_deg",40)))
        return np.clip(lunar,0,1)/(self.q0*airmass**self.airmass_exponent)

    def _average_public_quality(self,start,duration,idx):
        key = (start.timestamp(),int(duration))
        if self._build_quality is not None:
            if key not in self._build_quality:
                self._build_quality[key] = self._integrated_public_quality(start,duration,np.arange(self.n))
            return self._build_quality[key][idx]
        return self._integrated_public_quality(start,duration,idx)

    def _integrated_public_quality(self,start,duration,idx):
        night = next(k for k,(a,b) in enumerate(self.nights) if a<=start<b)
        anchor = self.nights[night][0]
        end = start+timedelta(seconds=duration)
        cursor,total = start,np.zeros(len(idx))
        slot_seconds = int(self.init["survey"].get("slot_seconds",900))
        while cursor<end:
            slot = math.floor((cursor-anchor).total_seconds()/slot_seconds)
            segment_end = min(end,anchor+timedelta(seconds=(slot+1)*slot_seconds))
            while cursor<segment_end:
                piece_end = min(segment_end,cursor+timedelta(seconds=120))
                total += (piece_end-cursor).total_seconds()*self._subset_public_quality(cursor+(piece_end-cursor)/2,idx)
                cursor = piece_end
        return total/duration

    def _geometry(self,start):
        key = start.timestamp()
        if self._build_geometry is not None and key in self._build_geometry:
            return self._build_geometry[key]
        lst = local_sidereal(start,self.lon)
        alt,az,hour,vectors = self._altaz(lst)
        up = np.where(self.hmax>=180,1e9,(self.hmax-hour)/SIDEREAL_SPEED)
        result = alt,az,up,vectors
        if self._build_geometry is not None:self._build_geometry[key]=result
        return result

    def _quality_scales(self,env):
        scale = np.full(self.n,max(.005,float(env.get("quality_scale",.55))))
        if env.get("target_quality_scale") is not None:
            scale *= np.asarray(env["target_quality_scale"],dtype=float)
        return scale

    def _fill(self,start,center,duration,pool,scores,factors,env,request_idx,threshold,
              forced,prefer_request=False,program=None):
        alt,az,up,vectors = self._geometry(start)
        # Public altitude constraint holds throughout the fixed-pointing exposure.
        pool = np.asarray(pool,dtype=int)
        pool = pool[(alt[pool]>=self.min_alt+.04)&(up[pool]>=duration+1)]
        fiber,valid,_ = self._classify(vectors[pool],*center)
        idx,fiber = pool[valid],fiber[valid]
        if not len(idx) or not set(forced).issubset(set(idx.tolist())):
            return []
        h = self._average_public_quality(start,duration,idx)
        scale = self._quality_scales(env)[idx]
        quality = h*scale
        coefficient = self.flux[idx]*quality/self.f0t0
        raw = np.minimum(1.,coefficient*duration)
        safety = max(1.,float(env.get("duration_safety",1.1)))
        robust = np.minimum(1.,coefficient*duration/safety)
        band_scale = max(.005,float(env.get("program_band_quality_scale",float(env.get("quality_scale",.55))/.95)))
        bands = np.where(h*band_scale>=self.dark_threshold,0,np.where(h*band_scale>=self.bright_threshold,1,2))
        req_positions = {int(i):bit for bit,i in enumerate(request_idx)}
        eligible = np.asarray([int(i) in req_positions for i in idx])&(robust+1e-10>=threshold)
        # Execution may consume the safety margin after a mild forecast change.
        if any(raw[np.flatnonzero(idx==i)[0]]+1e-10<threshold for i in forced):
            return []
        forced_fibers = {int(fiber[np.flatnonzero(idx==i)[0]]):int(i) for i in forced}
        if len(forced_fibers)!=len(forced):
            return []
        night = next(k for k,(a,b) in enumerate(self.nights) if a<=start<b)
        required_price = self.req_penalty/np.maximum(1,self.future_nights[night,idx])
        output = []
        for prog in (range(3) if program is None else (program,)):
            mult = np.where(bands==prog,self.multipliers[prog],self.mismatch)
            science = np.maximum(0.,self.weight[idx]*raw*mult-scores[idx])
            selection = science+self.required[idx]*(factors[idx]<self.req_threshold)*(robust>=self.req_threshold)*required_price
            selected,fibers = [],[]
            for f in range(self.nfib):
                choices = np.flatnonzero(fiber==f)
                if not len(choices):continue
                if f in forced_fibers:
                    j = int(np.flatnonzero(idx==forced_fibers[f])[0])
                else:
                    request_choices = choices[eligible[choices]]
                    use = request_choices if prefer_request and len(request_choices) else choices
                    j = int(use[np.argmax(selection[use])])
                    if selection[j]<=1e-12 and not (prefer_request and eligible[j]):continue
                selected.append(j);fibers.append(f)
            selected = np.asarray(selected,dtype=int)
            mask = 0
            for j in selected:
                if eligible[j]:mask |= 1<<req_positions[int(idx[j])]
            prediction = {self.ids[int(idx[j])]:{"index":int(idx[j]),"fiber_id":int(f),"factor":float(raw[j]),
                "public_quality":float(h[j]),"quality":float(quality[j]),
                "directional_scale":float(quality[j]/max(1e-12,h[j]*float(env.get("quality_scale",.55)))),
                "predicted_band":PROGRAMS[int(bands[j])],"alt_deg":float(alt[idx[j]]),"az_deg":float(az[idx[j]])}
                for j,f in zip(selected,fibers)}
            output.append({"center":tuple(center),"duration":int(duration),"program":int(prog),
                           "chosen":idx[selected],"fibers":fibers,"mask":mask,
                           "science_gain":float(science[selected].sum()),
                           "tie_utility":float(selection[selected].sum()),"prediction":prediction})
        return output

    def _build_pool(self,request,now,scores,factors,env):
        started = time.perf_counter()
        deadline = parse_utc(request["deadline_utc"])
        request_idx = np.asarray([self.index[t] for t in request["target_ids"] if t in self.index],dtype=int)
        threshold = float(request.get("completion_factor_threshold",.5))
        step = max(60,int(env.get("request_dp_step_seconds",900)))
        starts = {now}
        for a,b in self.nights:
            if b<=now or a>=deadline:continue
            cursor = a
            while cursor<min(b,deadline):
                if cursor>=now:starts.add(cursor)
                cursor += timedelta(seconds=step)
        scales = self._quality_scales(env)
        safety = max(1.,float(env.get("duration_safety",1.1)))
        deduplicated = {}
        price_records = []
        self._build_geometry,self._build_quality = {},{}
        for start in sorted(starts):
            night = next((k for k,(a,b) in enumerate(self.nights) if a<=start<b),None)
            if night is None:continue
            limit = min(self.tmax,int((min(self.nights[night][1],deadline)-start).total_seconds()))
            if limit<self.tmin:continue
            price,frame = self._price_planner.price(start,scores,factors,env)
            if frame is None:continue
            vectors,up,k,*_ = frame
            alt,az,_,_ = self._geometry(start)
            price_records.append((start.timestamp(),price))
            fixed_baselines = {}
            for anchor in request_idx:
                if alt[anchor]<self.min_alt+.04:continue
                duration = max(self.tmin,int(math.ceil(threshold*safety/max(k[anchor],1e-12))))
                for _ in range(4):
                    if duration>min(limit,up[anchor]):break
                    h = self._average_public_quality(start,duration,np.asarray([anchor]))[0]
                    coefficient = self.flux[anchor]*h*scales[anchor]/self.f0t0
                    needed = max(self.tmin,int(math.ceil(threshold*safety/max(coefficient,1e-12))))
                    if needed<=duration:break
                    duration = needed
                if duration>min(limit,up[anchor]):continue
                if duration not in fixed_baselines:
                    h_all = self._average_public_quality(start,duration,np.arange(self.n))
                    fixed_baselines[duration] = self._price_planner.fixed_value(start,duration,scores,factors,env,h_all)
                pool = np.flatnonzero((vectors[:,2]>=math.sin((self.min_alt+.04)*DEG))&(up>=duration+1)&
                                      ((self.eq_vectors@self.eq_vectors[anchor])>=math.cos(2*self.fov*DEG)))
                for f in range(self.nfib):
                    row,col = divmod(f,self.side)
                    center = _shift_altaz(float(alt[anchor]),float(az[anchor]),-(row-(self.side-1)/2)*self.pitch,-(col-(self.side-1)/2)*self.pitch)
                    for prefer in (False,True):
                        for tag in self._fill(start,center,duration,pool,scores,factors,env,request_idx,threshold,[int(anchor)],prefer):
                            if not tag["mask"]:continue
                            key = (start.timestamp(),duration,tag["mask"])
                            # Background fibers remain productive. We price the difference,
                            # not an entire telescope exposure. Frozen ledger prices are
                            # approximate across columns; DP never adds their science gains.
                            cost = max(0.,fixed_baselines[duration]-tag["science_gain"])
                            if key not in deduplicated or (cost,-tag["tie_utility"])<(deduplicated[key].opportunity_cost,-deduplicated[key].tag["tie_utility"]):
                                deduplicated[key] = RequestColumn(start.timestamp(),start.timestamp()+duration,
                                    tag["mask"],cost,tag)
        columns = list(deduplicated.values())
        self._build_geometry=self._build_quality=None
        elapsed = time.perf_counter()-started
        self._request_counts["builds"]+=1;self._request_counts["build_seconds"]+=elapsed
        return {"columns":columns,"idx":request_idx,"threshold":threshold,"deadline":deadline,
                "scale":scales[request_idx].copy(),"band_scale":float(env.get("program_band_quality_scale",.55/.95)),
                "prices":price_records,"build_seconds":elapsed}

    def _request_action(self,tag,now,pool_info,scores,factors,env,completed_mask):
        forced = [int(i) for bit,i in enumerate(pool_info["idx"]) if tag["mask"]&(1<<bit) and not completed_mask&(1<<bit)]
        lst = local_sidereal(now,self.lon)
        alt,_,_,vectors = self._altaz(lst)
        center = tag["center"]
        a,z = center[0]*DEG,center[1]*DEG
        cvec = np.asarray([math.cos(a)*math.cos(z),math.cos(a)*math.sin(z),math.sin(a)])
        pool = np.flatnonzero((alt>=self.min_alt+.04)&((vectors@cvec)>=math.cos(self.fov*DEG)))
        filled = self._fill(now,center,tag["duration"],pool,scores,factors,env,pool_info["idx"],pool_info["threshold"],forced,False,tag["program"])
        if not filled:return None
        chosen = filled[0]
        cmd_alt = center[0]-float(env.get("pointing_offset_alt_deg",0))
        if not 0<=cmd_alt<=90:return None
        self.last_prediction = chosen["prediction"]
        return {"action":"observe","pointing":{"alt_deg":round(cmd_alt,7),"az_deg":round((center[1]-float(env.get("pointing_offset_az_deg",0)))%360,7)},
                "duration_seconds":tag["duration"],"program":PROGRAMS[tag["program"]],
                "assignments":{str(f):self.ids[int(i)] for i,f in zip(chosen["chosen"],chosen["fibers"])}}

    def choose(self,snapshot,best_scores,best_factors,env_estimate=None,active_requests=None):
        env = dict(env_estimate or {})
        started = time.perf_counter()
        baseline = super().choose(snapshot,best_scores,best_factors,env,active_requests)
        if env.get("request_dp_mode","deadline")=="bypass":return baseline
        now = parse_utc(snapshot["now_utc"])
        scores,factors = self._array(best_scores),self._array(best_factors)
        selections = []
        for req in active_requests or []:
            done = set(req.get("completed_target_ids",[]))
            quorum = int(req.get("minimum_completed",0))
            if len(done)>=quorum:continue
            if len(req.get("target_ids",[]))>8:continue
            if parse_utc(req["deadline_utc"])<=now:continue
            rid = req["request_id"]
            info = self._request_pools.get(rid)
            req_idx = np.asarray([self.index[t] for t in req["target_ids"] if t in self.index],dtype=int)
            scale = self._quality_scales(env)[req_idx]
            tolerance = float(env.get("request_dp_quality_tolerance",.15))
            changed = info is not None and (np.max(np.abs(scale/np.maximum(info["scale"],1e-12)-1))>tolerance or abs(float(env.get("program_band_quality_scale",.55/.95))/max(info["band_scale"],1e-12)-1)>tolerance)
            if info is None or changed:
                if float((snapshot.get("wallclock") or {}).get("remaining_seconds",900))<30:continue
                info = self._build_pool(req,now,scores,factors,env);self._request_pools[rid]=info
            completed_mask = sum(1<<bit for bit,i in enumerate(info["idx"]) if self.ids[int(i)] in done)
            dstart = time.perf_counter()
            plan = solve_request_columns(info["columns"],target_count=len(info["idx"]),quorum=quorum,
                                         completed_mask=completed_mask,now=now.timestamp(),deadline=info["deadline"].timestamp())
            self._request_counts["dp_solves"]+=1;self._request_counts["dp_seconds"]+=time.perf_counter()-dstart
            decision = compare_request_reward(plan,float(req.get("completion_reward",100)))
            if not plan.feasible:self._request_counts["infeasible"]+=1
            elif not decision.pursue:self._request_counts["rejected_by_cost"]+=1
            if decision.pursue and plan.chosen_indices:
                first = info["columns"][plan.chosen_indices[0]]
                selections.append((first.start,req,info,completed_mask,plan,first))
        if not selections:
            self.stats.update(request_dp_active=False,planning_seconds=time.perf_counter()-started)
            return baseline
        _,req,info,completed_mask,plan,first = min(selections,key=lambda item:item[0])
        self.stats.update(request_dp_active=True,request_dp_id=req["request_id"],request_dp_cost=plan.min_cost,
                          request_dp_columns=len(info["columns"]),request_dp_first_utc=first.start,
                          planning_seconds=time.perf_counter()-started)
        delay = first.start-now.timestamp()
        if delay<=.5:
            action = self._request_action(first.tag,now,info,scores,factors,env,completed_mask)
            if action:
                self._request_counts["request_observes"]+=1
                self.stats["planning_seconds"]=time.perf_counter()-started
                return action
            self._request_counts["forecast_failures"]+=1
            self._request_pools.pop(req["request_id"],None)
            return baseline
        if delay<self.tmin:
            self._request_counts["boundary_waits"]+=1;self.last_prediction={}
            return {"action":"wait","until_utc":(now+timedelta(seconds=delay)).isoformat().replace("+00:00","Z")}
        if baseline is None:
            self._request_counts["boundary_waits"]+=1;self.last_prediction={}
            return {"action":"wait","until_utc":(now+timedelta(seconds=min(900,delay))).isoformat().replace("+00:00","Z")}
        if baseline and baseline.get("action")=="observe" and baseline["duration_seconds"]>delay:
            original = self.tmax
            try:
                self.tmax=min(original,int(math.floor(delay)))
                cropped = super().choose(snapshot,best_scores,best_factors,env,active_requests)
            finally:self.tmax=original
            self._request_counts["clipped_baselines"]+=1
            self.stats["planning_seconds"]=time.perf_counter()-started
            if cropped:return cropped
            self.last_prediction={}
            return {"action":"wait","until_utc":(now+timedelta(seconds=delay)).isoformat().replace("+00:00","Z")}
        return baseline

    def request_dp_summary(self):
        return {**self._request_counts,"cached_requests":len(self._request_pools),
                "model":"full-deadline finite columns; frozen same-duration scientific regret"}
