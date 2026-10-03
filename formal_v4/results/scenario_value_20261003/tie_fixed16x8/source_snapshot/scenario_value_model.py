"""Causal finite-path exposure value; no truth, evaluator, network or LLM.

Order within each path: <=120s public geometry and slot weather integration,
program band classification, raw-factor saturation, best-score positive part,
required threshold, then expectation. Only the unchanged source mean estimate
and public feedback freshness define the approximate conditional path law.
"""
from __future__ import annotations
import math
import time
from datetime import timedelta
import numpy as np
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
from research.spatial_candidates import DEG, PROGRAMS, _sun_moon, parse_utc, local_sidereal

PARAMS = dict(paths=16, fields=8, quantiles=(.75,.90), seed=909817,
              observation_log_sigma=.06, slot_log_sigma=.08,
              night_log_sigma=.19, slot_phi=.88, efficiency_log_sigma=.0304)


def finite_paths(slot_ids, sigma_current, integrated=False):
    """Fixed antithetic paths, normalized to the source mean in every slot.

    Log C follows the public reference's slot correlation. Efficiency jitter
    has the reference uniform jitter's log standard deviation. These are a
    moment approximation, not an exact posterior over three clipped fields.
    """
    n = 1 if integrated else PARAMS['paths']
    if integrated:
        return np.ones((n,len(slot_ids))),np.ones((n,len(slot_ids)))
    rng = np.random.default_rng(PARAMS['seed'])
    z = rng.standard_normal((n//2,2*len(slot_ids)))
    z = np.concatenate((z,-z),axis=0)
    c = np.empty((n,len(slot_ids)))
    e = np.empty_like(c)
    state = sigma_current*z[:,0]
    phi = PARAMS['slot_phi']
    innovation = PARAMS['slot_log_sigma']*math.sqrt(1-phi*phi)
    for j in range(len(slot_ids)):
        if j:
            state = phi*state+innovation*z[:,j]
        c[:,j] = np.exp(state)
        c[:,j] /= c[:,j].mean()
        e[:,j] = np.exp(PARAMS['efficiency_log_sigma']*z[:,len(slot_ids)+j])
        e[:,j] /= e[:,j].mean()
    return c,e


class ScenarioValuePlanner(CPUPhaseSpatialPlanner):
    def __init__(self,initial):
        super().__init__(initial)
        self.scenario_mode='baseline'
        self.scenario_sigma=math.hypot(PARAMS['night_log_sigma'],PARAMS['slot_log_sigma'])
        self.scenario_stats=dict(calls=0,changes=0,seconds=0.,fields=0,actions=0,
                                 duration_changes=0,program_changes=0,assignment_changes=0)

    def _evaluate(self,center,pool,*frame):
        c=super()._evaluate(center,pool,*frame)
        if getattr(self,'_scenario_capture',False) and c is not None:
            self._scenario_candidates.append(c)
        return c

    def _public_subset(self,moment,idx):
        """The source's public formula evaluated only for local targets."""
        lst=local_sidereal(moment,self.lon)
        hh=((lst-self.ra[idx]+180)%360-180)*DEG
        sine=self.sin_lat*self.sin_dec[idx]+self.cos_lat*self.cos_dec[idx]*np.cos(hh)
        alt=np.arcsin(np.clip(sine,-1,1))/DEG
        zenith=90.-np.maximum(alt,1.)
        raw=1./(np.cos(zenith*DEG)+.50572*(96.07995-zenith)**-1.6364)
        airmass=raw/(1./(1.+.50572*96.07995**-1.6364))
        moon,illumination=_sun_moon(moment)
        mdec=math.asin(float(np.clip(moon[2],-1,1)))
        mra=math.atan2(moon[1],moon[0])/DEG%360
        malt=math.asin(self.sin_lat*math.sin(mdec)+self.cos_lat*math.cos(mdec)*math.cos(((lst-mra+180)%360-180)*DEG))
        lunar=np.ones(len(idx))
        if malt>0:
            separation=np.arccos(np.clip(self.eq_vectors[idx]@moon,-1,1))/DEG
            penalty=float(self.lunar.get('maximum_penalty',.5))*illumination*math.sin(malt)**float(self.lunar.get('altitude_exponent',1))
            lunar-=penalty*np.exp(-separation/float(self.lunar.get('angular_decay_scale_deg',40)))
        return np.clip(lunar,0,1)/(self.q0*airmass**self.airmass_exponent)

    def _integrals(self,now,night,idx,durations,env):
        """Exposure pieces split at slot boundaries and then every <=120s.

        Geometry is shared by all paths; the path coefficients remain inside
        the weighted sum. The final partial piece uses its own midpoint.
        """
        maximum=max(durations)
        anchor=self.nights[night][0]
        slot_seconds=int(self.init['survey'].get('slot_seconds',900))
        elapsed=(now-anchor).total_seconds()
        current_slot=int(math.floor(elapsed/slot_seconds))
        cuts=[0.]
        piece_slots=[]
        cursor=0.
        while cursor<maximum:
            slot=int(math.floor((elapsed+cursor+1e-7)/slot_seconds))
            slot_end=(slot+1)*slot_seconds-elapsed
            stop=min(float(maximum),slot_end,cursor+120.)
            cuts.append(stop);piece_slots.append(slot-current_slot)
            cursor=stop
        cuts=np.asarray(cuts)
        c,e=finite_paths(range(max(piece_slots)+1),self.scenario_sigma,self.scenario_mode=='integrated')
        band_scale=float(env['program_band_quality_scale'])
        quality_scale=float(env['quality_scale'])
        target_scale=np.ones(self.n) if env.get('target_quality_scale') is None else np.asarray(env['target_quality_scale'])
        geometry=np.stack([self._public_subset(now+timedelta(seconds=float((a+b)/2)),idx)
                           for a,b in zip(cuts[:-1],cuts[1:])])
        spans=np.diff(cuts)
        paths_c=c[:,piece_slots]
        paths_e=e[:,piece_slots]
        band_pieces=paths_c[:,:,None]*geometry[None,:,:]*spans[None,:,None]*band_scale
        quality_pieces=paths_c[:,:,None]*paths_e[:,:,None]*geometry[None,:,:]*spans[None,:,None]*quality_scale*target_scale[idx][None,None,:]
        band_prefix=np.concatenate((np.zeros((len(c),1,len(idx))),np.cumsum(band_pieces,axis=1)),axis=1)
        quality_prefix=np.concatenate((np.zeros((len(c),1,len(idx))),np.cumsum(quality_pieces,axis=1)),axis=1)
        answer={}
        for duration in durations:
            j=int(np.searchsorted(cuts,duration,side='right')-1)
            qb=band_prefix[:,j,:].copy();qe=quality_prefix[:,j,:].copy()
            if j<len(piece_slots) and duration>cuts[j]+1e-9:
                length=duration-cuts[j]
                h=self._public_subset(now+timedelta(seconds=float((cuts[j]+duration)/2)),idx)
                s=piece_slots[j]
                qb+=c[:,s,None]*h[None,:]*length*band_scale
                qe+=c[:,s,None]*e[:,s,None]*h[None,:]*length*quality_scale*target_scale[idx][None,:]
            answer[int(duration)]=(qb/duration,qe/duration)
        return answer

    def _action_value(self,idx,fibers,duration,program,raw,science,terminal,frame,focus,force_idx=None):
        """Choose one target per fibre from expected additive marginal value.

        The focus request replaces its distributed price with pathwise quota
        completion, or the source's capped rolling progress price.
        """
        _,_,_,_,_,_,_,_,_,_,_,urgency,_,_,_=frame
        path_value=(science[:,program,:]+terminal)*urgency[idx][None,:]
        means=path_value.mean(axis=0)
        selected=[]
        if force_idx is None:
            for f in range(self.nfib):
                js=np.flatnonzero(fibers==f)
                if len(js):
                    j=int(js[np.argmax(means[js])])
                    if means[j]>0:selected.append(j)
        else:
            positions={int(i):j for j,i in enumerate(idx)}
            selected=[positions[int(i)] for i in force_idx if int(i) in positions]
        if not selected:return None
        selected=np.asarray(selected,dtype=int)
        path_totals=path_value[:,selected].sum(axis=1)
        if focus is not None:
            membership,reward,left,threshold,deadline=focus
            complete=(raw[:,selected]>=threshold)&membership[idx[selected]][None,:]&(duration<=deadline)
            progress=complete.sum(axis=1)
            # The official reward event is represented exactly when this field
            # meets the remaining quota; partial pricing is a continuation proxy.
            path_totals+=reward*np.minimum(progress/left,1.)
        return float(path_totals.mean()/duration),idx[selected],fibers[selected]

    def choose(self,snapshot,best_scores,best_factors,env_estimate=None,active_requests=None):
        self._scenario_candidates=[];self._scenario_capture=self.scenario_mode!='baseline'
        env=dict(env_estimate or {})
        env.update(cpu_phase_mode='phase',cpu_phase_fixed_workload=True,anchor_count=24,
                   cpu_phase_top_count=4,cpu_phase_local_target_count=50,
                   cpu_phase_boundary_target_count=24,cpu_phase_exact_count=16)
        base=super().choose(snapshot,best_scores,best_factors,env,active_requests)
        self._scenario_capture=False
        if self.scenario_mode=='baseline' or base is None or not self._cpu_phase_frame:return base
        started=time.perf_counter();frame=self._cpu_phase_frame
        vectors,up,k,scores,factors,multiplier,missing,rr,rt,rd,ub,urgency,seconds,safety,focus=frame
        now=parse_utc(snapshot['now_utc'])
        night=next(i for i,(a,b) in enumerate(self.nights) if a<=now<b)
        ea=float(env.get('pointing_offset_alt_deg',0));ez=float(env.get('pointing_offset_az_deg',0))
        base_idx=np.asarray([self.index[t] for t in base['assignments'].values()],dtype=int)
        base_f=np.asarray([int(f) for f in base['assignments']],dtype=int)
        center=(base['pointing']['alt_deg']+ea,(base['pointing']['az_deg']+ez)%360)
        base_candidate=(float(self.stats.get('selected_exact_rate',1e9)),center,base['duration_seconds'],PROGRAMS.index(base['program']),base_idx,base_f)
        fields=[base_candidate]
        for candidate in sorted(self._scenario_candidates,key=lambda x:-x[0]):
            if all(abs(candidate[1][0]-old[1][0])+abs((candidate[1][1]-old[1][1]+180)%360-180)>.04*self.pitch for old in fields):
                fields.append(candidate)
            if len(fields)>=PARAMS['fields']:break
        local=[];all_durations=set();union=set()
        for candidate in fields:
            _,c,d,program,chosen,_=candidate
            fiber,valid,_=self._classify(vectors,*c)
            idx=np.flatnonzero(valid&(up>=self.tmin))
            if not len(idx):continue
            durations={int(d)}
            required_chosen=chosen[missing[chosen]]
            crossing=max(self.req_threshold/np.maximum(k[required_chosen],1e-12)) if len(required_chosen) else float(d)
            for z in (.6744897501960817,1.2815515655446004):
                durations.add(int(np.clip(math.ceil(crossing*math.exp(z*self.scenario_sigma)),self.tmin,seconds)))
            local.append((c,idx,fiber[idx],durations,chosen))
            union.update(idx.tolist());all_durations.update(durations)
        union=np.asarray(sorted(union),dtype=int)
        if not len(union):return base
        positions={int(i):j for j,i in enumerate(union)}
        integrated=self._integrals(now,night,union,sorted(all_durations),env)
        best=None;counter=0
        for c,idx,fibers,durations,source_idx in local:
            take=np.asarray([positions[int(i)] for i in idx])
            for duration in sorted(durations):
                allowed=duration<=up[idx]
                ii=idx[allowed];ff=fibers[allowed];jj=take[allowed]
                if not len(ii):continue
                qb,qe=integrated[duration];qb=qb[:,jj];qe=qe[:,jj]
                raw=np.minimum(1.,self.flux[ii][None,:]*duration*qe/self.f0t0)
                actual=np.where(qb>=self.dark_threshold,0,np.where(qb>=self.bright_threshold,1,2))
                mm=np.where(actual[:,None,:]==np.arange(3)[None,:,None],self.multipliers[None,:,None],self.mismatch)
                science=np.maximum(0.,self.weight[ii][None,None,:]*raw[:,None,:]*mm-scores[ii][None,None,:])
                terminal=(missing[ii][None,:]&(raw>=self.req_threshold))*self.req_penalty
                terminal=terminal+(factors[ii][None,:]<self.uniform_threshold)*(raw>=self.uniform_threshold)*ub[ii][None,:]
                rq=(rr[ii][None,:]>0)&(raw>=rt[ii][None,:])&(duration<=rd[ii][None,:])
                terminal=terminal+rq*rr[ii][None,:]
                if focus is not None:
                    member,reward,left,threshold,deadline=focus
                    terminal=terminal-((raw>=threshold)&member[ii][None,:]&(duration<=deadline))*(reward/left)
                for program in range(3):
                    for forced in (None,source_idx):
                        result=self._action_value(ii,ff,duration,program,raw,science,terminal,frame,focus,forced)
                        counter+=1
                        tie_tolerance=1e-10*max(1.,result[0]) if result is not None else 0.
                        improves=result is not None and (best is None or result[0]>best[0]+tie_tolerance)
                        plateau=result is not None and best is not None and abs(result[0]-best[0])<=tie_tolerance and result[0]*duration>best[0]*best[2]
                        if improves or plateau:
                            best=(result[0],c,duration,program,result[1],result[2])
        self.scenario_stats['calls']+=1;self.scenario_stats['fields']+=len(local);self.scenario_stats['actions']+=counter
        self.scenario_stats['seconds']+=time.perf_counter()-started
        if best is None:return base
        _,center,duration,program,idx,fibers=best
        action=dict(action='observe',pointing=dict(alt_deg=round(center[0]-ea,7),az_deg=round((center[1]-ez)%360,7)),
                    assignments={str(int(f)):self.ids[int(i)] for i,f in zip(idx,fibers)},duration_seconds=int(duration),program=PROGRAMS[program])
        self.scenario_stats['changes']+=int(action!=base)
        self.scenario_stats['duration_changes']+=int(duration!=base['duration_seconds'])
        self.scenario_stats['program_changes']+=int(action['program']!=base['program'])
        self.scenario_stats['assignment_changes']+=int(action['assignments']!=base['assignments'])
        alt,az,_,_=self._altaz(local_sidereal(now,self.lon))
        self.last_prediction={self.ids[int(i)]:dict(index=int(i),fiber_id=int(f),alt_deg=float(alt[i]),az_deg=float(az[i]))
                              for i,f in zip(idx,fibers)}
        return action


def install_policy(BasePolicy,mode):
    class ScenarioPolicy(BasePolicy):
        def __init__(self,initial):
            super().__init__(initial)
            self.planner.scenario_mode=mode
            self.config.update(cpu_phase_mode='phase',cpu_phase_fixed_workload=True,anchor_count=24,
                cpu_phase_top_count=4,cpu_phase_local_target_count=50,cpu_phase_boundary_target_count=24,cpu_phase_exact_count=16)

        def _ingest_result(self,snapshot):
            super()._ingest_result(snapshot)
            now=parse_utc(snapshot['now_utc'])
            fresh=self.last_feedback is not None and self._night(self.last_feedback-timedelta(seconds=1))==self._night(now)
            gap=max(0.,(now-self.last_feedback).total_seconds()/self.slot_seconds) if fresh else float('inf')
            variance=PARAMS['observation_log_sigma']**2+PARAMS['slot_log_sigma']**2*(1-PARAMS['slot_phi']**(2*gap))
            if not fresh:variance+=PARAMS['night_log_sigma']**2
            self.planner.scenario_sigma=math.sqrt(variance)

        def summary(self):
            return {**super().summary(),'cpu_phase':self.planner.cpu_phase_summary,
                    'scenario_value':self.planner.scenario_stats,'scenario_mode':mode,'scenario_params':PARAMS}
    return ScenarioPolicy
