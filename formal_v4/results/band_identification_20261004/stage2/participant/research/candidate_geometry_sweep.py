"""All-target weighted translation arrangement; spherical action refinement.

Research backend: NumPy + Numba, with no future truth or remote service. The
event sweep is exact only for additive utility in a fixed tangent plane. Final
pointings, full exposure breakpoints, and request quotas use the frozen parent
SpatialPlanner. This does not certify spherical/global optimality.
"""
from __future__ import annotations

import math
import time
import numpy as np
from research.geometry_native import weighted_sweep

from research.spatial_candidates import SpatialPlanner, DEG, PROGRAMS, parse_utc, local_sidereal


def basis(seed):
    a, z = np.asarray(seed) * DEG
    return (np.array([math.cos(a)*math.cos(z), math.cos(a)*math.sin(z), math.sin(a)]),
            np.array([-math.sin(a)*math.cos(z), -math.sin(a)*math.sin(z), math.cos(a)]),
            np.array([-math.sin(z), math.cos(z), 0.]))




def utility_matrix(p, frame, pool, durations):
    _,up,k,scores,factors,multiplier,missing,rr,rt,rd,ub,urgency,_,safety,_=frame
    t=np.asarray(durations)[:,None]; kp=k[pool]
    raw=np.minimum(1.,t*kp); robust=np.minimum(1.,t*kp/safety)
    terminal=missing[pool]*(robust+1e-10>=p.req_threshold)*p.req_penalty
    terminal+=(factors[pool]<p.uniform_threshold)*(robust+1e-10>=p.uniform_threshold)*ub[pool]
    terminal+=(rr[pool]>0)*(robust+1e-10>=rt[pool])*(t<=rd[pool])*rr[pool]
    science=np.maximum(0.,p.weight[pool][None,None,:]*raw[:,None,:]*multiplier[:,pool][None,:,:]-scores[pool][None,None,:])
    value=(science+terminal[:,None,:])*urgency[pool][None,None,:]
    value=np.where(t[:,None,:]<=up[pool][None,None,:],value,0.)
    return np.maximum(0.,value/t[:,None,:]).reshape(-1,len(pool))


def assignment_interior(x,y,values,xx,yy,pitch,glass,side):
    """Recover max-utility assignment and centre its common feasible box.

    Unselected faint targets may create arbitrarily thin arrangement cells.
    The intersection of the winners' placement boxes is the full region in
    which this constructive assignment remains possible. Its midpoint
    maximizes the smallest axis clearance of these chosen target placements.
    """
    col=np.floor((x-xx)/pitch+side/2).astype(int)
    row=np.floor((y-yy)/pitch+side/2).astype(int)
    dc=(col-(side-1)/2)*pitch;dr=(row-(side-1)/2)*pitch
    half=glass/2-.008
    ok=(col>=0)&(col<side)&(row>=0)&(row<side)&(np.abs(x-xx-dc)<half)&(np.abs(y-yy-dr)<half)
    selected=[]
    for f in range(side*side):
        idx=np.flatnonzero(ok&(row*side+col==f))
        if len(idx):
            i=idx[np.argmax(values[idx])]
            if values[i]>0:selected.append(i)
    chosen=np.asarray(selected,dtype=int)
    if not len(chosen):return xx,yy,chosen,np.empty(0,int)
    sx=x[chosen]-dc[chosen];sy=y[chosen]-dr[chosen]
    return (float((sx.max()+sx.min())/2),float((sy.max()+sy.min())/2),
            chosen,row[chosen]*side+col[chosen])


def spherical_assignment_repair(vectors,center,fibers,pitch,glass,side,iterations=3):
    """Continuous correction of the common pointing for a chosen assignment."""
    half=glass/2-.008
    for _ in range(iterations):
        c,n,e=basis(center);depth=np.einsum('ij,j->i',vectors,c)
        dn=np.einsum('ij,j->i',vectors,n)/depth/DEG
        de=np.einsum('ij,j->i',vectors,e)/depth/DEG
        residual_n=dn-(fibers//side-(side-1)/2)*pitch
        residual_e=de-(fibers%side-(side-1)/2)*pitch
        yn=float((residual_n.max()+residual_n.min())/2)
        xe=float((residual_e.max()+residual_e.min())/2)
        if max(abs(yn),abs(xe))<1e-8:break
        shifted=c+yn*DEG*n+xe*DEG*e;shifted/=np.linalg.norm(shifted)
        center=(math.asin(float(shifted[2]))/DEG,math.atan2(float(shifted[1]),float(shifted[0]))/DEG%360)
    return center


class CandidateGeometryPlanner(SpatialPlanner):
    def __init__(self,initial):
        super().__init__(initial)
        self.geometry_summary={"calls":0,"sweeps":0,"arrangement_cells":0,"improvements":0,"sweep_seconds":0.,"exact_seconds":0.}
        self.export_hook=None

    def _evaluate(self,center,pool,*frame):
        result=super()._evaluate(center,pool,*frame)
        if getattr(self,"capture",False):
            self.frame=frame
            if result is not None:self.baseline_candidates.append(result)
        return result

    def choose(self,snapshot,scores,factors,env_estimate=None,active_requests=None):
        start=time.perf_counter();env=dict(env_estimate or {})
        env["planning_budget_seconds"]=30.
        self.capture=True;self.frame=None;self.baseline_candidates=[]
        try:base=super().choose(snapshot,scores,factors,env,active_requests)
        finally:self.capture=False
        self.geometry_summary["calls"]+=1
        if base is None or self.frame is None or env.get("candidate_geometry_mode")=="bypass":return base
        frame=self.frame;vectors=frame[0]
        ordered=sorted(self.baseline_candidates,key=lambda a:-a[0])
        best=ordered[0]; baseline_rate=best[0]
        seeds=[]
        for candidate in ordered:
            seed=candidate[1];sv=basis(seed)[0]
            if all(np.sum(sv*basis(old)[0])<math.cos(.45*self.pitch*DEG) for old in seeds):seeds.append(seed)
            if len(seeds)>=int(env.get("candidate_geometry_seeds",2)):break
        seconds=frame[12]
        durations=np.unique(np.clip(np.asarray([self.tmin,240,400,900,1800,seconds,base["duration_seconds"]]),self.tmin,seconds))
        radius=float(env.get("candidate_geometry_radius",1.))*self.pitch
        merit=(vectors[:,2]>=math.sin((self.min_alt+.04)*DEG))&(frame[1]>=self.tmin)
        future=np.minimum(1.,frame[2]*np.minimum(frame[1],seconds)/frame[13])
        merit&=(np.maximum(0.,self.weight*future*frame[5].max(axis=0)-frame[3])+frame[6]*self.req_penalty+frame[7])>1e-10
        useful=np.flatnonzero(merit)
        proposals=[];exports=[];sweep_start=time.perf_counter();cells=0
        for seed in seeds:
            c,n,e=basis(seed)
            cap=math.atan(self.fov/math.sqrt(2)*DEG)+math.atan(radius*math.sqrt(2)*DEG)+1e-8
            pool=useful[np.einsum('ij,j->i',vectors[useful],c)>=math.cos(cap)]
            if not len(pool):continue
            depth=np.einsum('ij,j->i',vectors[pool],c)
            x=np.einsum('ij,j->i',vectors[pool],e)/depth/DEG;y=np.einsum('ij,j->i',vectors[pool],n)/depth/DEG
            values=utility_matrix(self,frame,pool,durations)
            bx,by,bv,visited=weighted_sweep(x,y,values,self.pitch,self.glass,self.side,radius,int(env.get("candidate_geometry_keep",2)))
            cells+=int(visited);self.geometry_summary["sweeps"]+=1
            interior_x=np.zeros_like(bx);interior_y=np.zeros_like(by)
            for q in range(len(values)):
                for j in range(bx.shape[1]):
                    xx,yy,v=bx[q,j],by[q,j],bv[q,j]
                    rx,ry,chosen,fibers=assignment_interior(x,y,values[q],xx,yy,self.pitch,self.glass,self.side)
                    interior_x[q,j]=rx;interior_y[q,j]=ry
                    shifted=c+rx*DEG*e+ry*DEG*n;shifted/=np.linalg.norm(shifted)
                    center=(math.asin(float(shifted[2]))/DEG,math.atan2(float(shifted[1]),float(shifted[0]))/DEG%360)
                    if len(chosen):center=spherical_assignment_repair(vectors[pool[chosen]],center,fibers,self.pitch,self.glass,self.side)
                    proposals.append((float(v),center,pool))
            exports.append(dict(seed=np.asarray(seed),pool=pool,x=x,y=y,values=values,durations=durations,bx=bx,by=by,bv=bv,
                                interior_x=interior_x,interior_y=interior_y,radius=radius))
        sweep_seconds=time.perf_counter()-sweep_start
        exact_start=time.perf_counter();seen=set();evaluated=0
        for _,center,pool in sorted(proposals,key=lambda a:-a[0]):
            oa=float(env.get("pointing_offset_alt_deg",0));oz=float(env.get("pointing_offset_az_deg",0))
            cmd_alt=round(center[0]-oa,7);cmd_az=round((center[1]-oz)%360,7)
            if not 0<=cmd_alt<=90:continue
            center=(cmd_alt+oa,(cmd_az+oz)%360)
            key=tuple(round(x,7) for x in center)
            if key in seen:continue
            seen.add(key)
            result=super()._evaluate(center,pool,*frame);evaluated+=1
            if result is not None and result[0]>best[0]+1e-12:best=result
            if evaluated>=int(env.get("candidate_geometry_exact",24)):break
        self.geometry_summary["arrangement_cells"]+=cells
        self.geometry_summary["sweep_seconds"]+=sweep_seconds
        self.geometry_summary["exact_seconds"]+=time.perf_counter()-exact_start
        changed=best[0]>baseline_rate+1e-12
        self.geometry_summary["improvements"]+=int(changed)
        self.stats.update(geometry_cells=cells,geometry_sweep_seconds=sweep_seconds,geometry_exact=evaluated,
                          geometry_improved=changed,base_exact_rate=baseline_rate,selected_exact_rate=best[0],planning_seconds=time.perf_counter()-start)
        if self.export_hook:self.export_hook(snapshot,exports,self.stats,base,best)
        if not changed:return base
        _,center,duration,program,chosen,fibers=best
        now=parse_utc(snapshot["now_utc"]);lst=local_sidereal(now,self.lon)
        alt=np.arcsin(np.clip(vectors[:,2],-1,1))/DEG;az=np.arctan2(vectors[:,1],vectors[:,0])/DEG%360
        public=self._public_quality(now,lst,alt)
        quality_scale=max(.005,float(env.get("quality_scale",.55)))
        band_scale=max(.005,float(env.get("program_band_quality_scale",quality_scale/.95)))
        bands=np.where(public*band_scale>=self.dark_threshold,0,np.where(public*band_scale>=self.bright_threshold,1,2))
        quality=frame[2]*self.f0t0/np.maximum(self.flux,1e-12)
        tq=np.ones(self.n) if env.get("target_quality_scale") is None else np.asarray(env["target_quality_scale"])
        directional=quality/np.maximum(1e-12,public*quality_scale*tq)
        self.last_prediction={self.ids[int(i)]:dict(index=int(i),fiber_id=int(f),factor=min(1.,float(frame[2][i]*duration)),
             public_quality=float(public[i]),quality=float(quality[i]),directional_scale=float(directional[i]),
             predicted_band=PROGRAMS[int(bands[i])],alt_deg=float(alt[i]),az_deg=float(az[i])) for i,f in zip(chosen,fibers)}
        oa=float(env.get("pointing_offset_alt_deg",0));oz=float(env.get("pointing_offset_az_deg",0))
        return dict(action="observe",pointing=dict(alt_deg=round(center[0]-oa,7),az_deg=round((center[1]-oz)%360,7)),
                    assignments={str(int(f)):self.ids[int(i)] for i,f in zip(chosen,fibers)},duration_seconds=int(duration),program=PROGRAMS[int(program)])
