"""Full executable native actions and certified global-domain spatial pruning."""
from __future__ import annotations
import ctypes
import math
from pathlib import Path
import platform
import time
import numpy as np
from .cpu_phase_candidates import CPUPhaseSpatialPlanner
from .global_field_planner import optimistic_rates
from .spatial_candidates import DEG,PROGRAMS,parse_utc,local_sidereal

def load_native_v2():
    suffix='darwin_arm64.dylib' if platform.system()=='Darwin' else 'linux_x86_64.so'
    lib=ctypes.CDLL(str(Path(__file__).with_name('global_field_search_v2_'+suffix)))
    arr=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
    lib.global_field_search_v2.argtypes=[ctypes.c_int,arr,arr,arr,arr]
    lib.global_field_search_v2.restype=ctypes.c_int
    return lib

class GlobalFieldPlannerV2(CPUPhaseSpatialPlanner):
    def __init__(self,initial):
        super().__init__(initial)
        self.native=load_native_v2()
        self.global_summary=dict(calls=0,searched=0,improved=0,roots=0,nodes=0,matchings=0,
                                 native_improvements=0,root_pool_entries=0,root_full_entries=0,search_seconds=0.)
        self.export_hook=None

    def choose(self,snapshot,best_scores,best_factors,env_estimate=None,active_requests=None):
        started=time.perf_counter();env=dict(env_estimate or {})
        env['cpu_phase_fixed_workload']=True;env['anchor_count']=24
        baseline=super().choose(snapshot,best_scores,best_factors,env,active_requests)
        self.global_summary['calls']+=1
        frame=self._cpu_phase_frame
        if baseline is None or frame is None:return baseline
        _,up,k,scores,factors,mult,missing,rr,rt,rd,ub,urg,seconds,safety,focus=frame
        if np.any(urg<1.-1e-12):raise ValueError('matching bound requires urgency>=1')
        vectors=frame[0];upper=optimistic_rates(self,frame)
        alt=np.arcsin(np.clip(vectors[:,2],-1.,1.))/DEG
        az=np.arctan2(vectors[:,1],vectors[:,0])/DEG%360
        useful=np.flatnonzero((alt>=self.min_alt+.04)&(up>=self.tmin)&(upper>1e-10))
        if not len(useful):return baseline
        membership=np.zeros(self.n);left,reward,threshold,deadline=0,0.,0.,0.
        if focus is not None:membership,reward,left,threshold,deadline=focus
        data=np.ascontiguousarray(np.column_stack((alt[useful],az[useful],k[useful],up[useful],scores[useful],factors[useful],
              self.weight[useful],urg[useful],missing[useful],rr[useful],rt[useful],rd[useful],ub[useful],upper[useful],
              mult[:,useful].T,np.asarray(membership)[useful])),dtype=float)
        oa=float(env.get('pointing_offset_alt_deg',0.));oz=float(env.get('pointing_offset_az_deg',0.))
        low=max(0.,oa,float(alt[useful].min())-math.atan(self.fov/math.sqrt(2)*DEG)/DEG)
        high=min(90.,90.+oa);base_rate=float(self.stats['selected_exact_rate'])
        cfg=np.ascontiguousarray([self.side,self.pitch,self.glass,self.tmin,seconds,safety,self.req_threshold,self.req_penalty,
              self.uniform_threshold,base_rate,256,16,left,reward,threshold,deadline,low,high,oa,oz],dtype=float)
        out=np.full(22,-1.);stats=np.zeros(8)
        search_started=time.perf_counter()
        found=self.native.global_field_search_v2(len(data),data,cfg,out,stats)
        elapsed=time.perf_counter()-search_started
        if found<0:raise RuntimeError(f'global search v2 error {found}')
        self.global_summary['searched']+=1;self.global_summary['improved']+=bool(found)
        for name,index in [('roots',0),('nodes',1),('matchings',4),('native_improvements',5),('root_pool_entries',6),('root_full_entries',7)]:
            self.global_summary[name]+=int(stats[index])
        self.global_summary['search_seconds']+=elapsed
        self.stats.update(global_search_seconds=elapsed,global_nodes=int(stats[1]),global_roots=int(stats[0]),
              global_native_improvements=int(stats[5]),global_root_pool_entries=int(stats[6]),global_root_full_entries=int(stats[7]),
              global_improved=bool(found),global_base_rate=base_rate,global_selected_rate=float(out[0]) if found else base_rate,
              planning_seconds=time.perf_counter()-started)
        if self.export_hook:self.export_hook(snapshot,frame,useful,upper,data,cfg,out,stats,baseline)
        if not found:return baseline
        duration,program=int(out[3]),int(out[4])
        if not self.tmin<=duration<=seconds or not 0<=program<3:raise RuntimeError('invalid native duration/program')
        fibers=np.flatnonzero(out[6:22]>=0)
        selected_rows=out[6+fibers].astype(int)
        if np.any(selected_rows>=len(useful)):raise RuntimeError('invalid native target row')
        chosen=useful[selected_rows]
        if len(set(chosen.tolist()))!=len(chosen):raise RuntimeError('native duplicate target')
        ca=round(float(out[1])-oa,7);cz=round((float(out[2])-oz)%360,7)
        center=(ca+oa,(cz+oz)%360)
        if not 0<=ca<=90 or np.any(duration>up[chosen]):raise RuntimeError('native action outside legal time/pointing')
        classified,_,margin=self._classify(vectors[chosen],*center)
        # A few ulps at the intentional .008 shrink boundary are harmless to
        # the official glass. We require positive physical clearance and the
        # same actual fibre after the final seven-digit command rounding.
        if np.any(classified!=fibers) or np.any(margin<.008-1e-9):raise RuntimeError('native action geometry mismatch')
        now=parse_utc(snapshot['now_utc']);lst=local_sidereal(now,self.lon)
        public=self._public_quality(now,lst,alt)
        qscale=max(.005,float(env.get('quality_scale',.55)))
        bscale=max(.005,float(env.get('program_band_quality_scale',qscale/.95)))
        bands=np.where(public*bscale>=self.dark_threshold,0,np.where(public*bscale>=self.bright_threshold,1,2))
        quality=k*self.f0t0/np.maximum(self.flux,1e-12)
        tq=np.ones(self.n) if env.get('target_quality_scale') is None else np.asarray(env['target_quality_scale'])
        directional=quality/np.maximum(1e-12,public*qscale*tq)
        self.last_prediction={self.ids[int(i)]:dict(index=int(i),fiber_id=int(f),factor=min(1.,float(k[i]*duration)),
              public_quality=float(public[i]),quality=float(quality[i]),directional_scale=float(directional[i]),
              predicted_band=PROGRAMS[int(bands[i])],alt_deg=float(alt[i]),az_deg=float(az[i])) for i,f in zip(chosen,fibers)}
        return dict(action='observe',pointing=dict(alt_deg=ca,az_deg=cz),assignments={str(int(f)):self.ids[int(i)] for i,f in zip(chosen,fibers)},
                    duration_seconds=duration,program=PROGRAMS[program])
