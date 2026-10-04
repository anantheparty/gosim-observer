"""Full public catalogue, finite season pattern graph with shared incidence.

This is a fixed conditional deterministic science surrogate, not E[max] under
unknown weather. All public target rows are loaded; future grids are declared
geometric candidates, not the complete continuous pointing/action domain.
"""
from __future__ import annotations
import ctypes,math,time,resource,sys
from pathlib import Path
from datetime import timedelta
import numpy as np
from scipy.spatial import cKDTree
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from research.spatial_candidates import local_sidereal,_shift_altaz,SIDEREAL_SPEED,PROGRAMS
from research.feedback_model import seasonal_quality

ROOT=Path(__file__).resolve().parent
LIB=ctypes.CDLL(str(ROOT/('shared_oracle.dylib' if sys.platform=='darwin' else 'shared_oracle.so')))
P=ctypes.c_void_p;I=ctypes.c_int
LIB.price_shared.argtypes=[I,I,I,I]+[P]*12+[ctypes.c_double]+[P]*7
LIB.price_shared.restype=None
def ptr(a):return a.ctypes.data
def rss():
 r=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
 return int(r if sys.platform=='darwin' else r*1024)

class CostStop(RuntimeError):pass
class Budget:
 def __init__(self,seconds=20,rss_mb=1536):self.start=time.perf_counter();self.limit=seconds;self.rss_limit=rss_mb*1024**2;self.stages=[]
 def remaining(self):return max(.001,self.limit-(time.perf_counter()-self.start))
 def check(self):
  if self.remaining()<=.001:raise CostStop('declared selector wall budget exhausted')
  if rss()>self.rss_limit:raise CostStop('declared RSS budget exhausted')
 def stage(self,name,t,**kw):self.stages.append(dict(stage=name,seconds=time.perf_counter()-t,rss_bytes=rss(),**kw));self.check()

class SharedGraph:
 durations=(900,1800,3600)
 def __init__(self,actor,snapshot,budget,current=True,step=3600):
  self.actor=actor;self.p=p=actor.planner;self.n=p.n;self.nfib=p.nfib;self.nd=len(self.durations);self.budget=budget
  self.now=now=__import__('research.spatial_candidates',fromlist=['parse_utc']).parse_utc(snapshot['now_utc'])
  self.field=p._future_field(snapshot,actor.config)
  self.step=step;self.patterns=[];self.seen=set();self.trace=[]
  t=time.perf_counter()
  # One weight/flux-independent representative nearest each spatial-bin centroid.
  reps=[]
  for k in range(p.bin_count):
   ids=np.flatnonzero(p.space_bins==k);v=p.eq_vectors[ids].mean(axis=0);v/=np.linalg.norm(v)
   reps.append(int(ids[np.argmax(p.eq_vectors[ids]@v)]))
  self.reps=np.asarray(reps,dtype=np.int32);self.tree=cKDTree(p.eq_vectors)
  starts=[now]
  for a,b in p.nights:
   cursor=max(a,now)
   if cursor<=now:cursor=a+timedelta(seconds=math.ceil(max(0,(now-a).total_seconds())/step)*step)
   while cursor<b:
    if cursor>=now and cursor not in starts:starts.append(cursor)
    cursor+=timedelta(seconds=step)
  self.moments=sorted(starts);self.ts=np.asarray([x.timestamp() for x in self.moments]);self.ns=len(starts)
  budget.stage('catalogue_geometric_representatives',t,representatives=len(reps),public_targets=p.n,start_count=self.ns)
  t=time.perf_counter();factor=[];band=[];eligible=[];fields=[];targets=[];fibers=[];offset=[0];field_start=[]
  # Angular radius enclosing every corner of the square tangent field, plus
  # one corner-fiber phase. KDTree is only a conservative candidate filter.
  radius=2*math.sin(math.atan(math.sqrt(2)*p.fov*math.pi/180)/2)
  for si,start in enumerate(self.moments):
   budget.check();a,b=next((a,b) for a,b in p.nights if a<=start<b)
   alt,az,hour,vectors=p._altaz(local_sidereal(start,p.lon))
   sf=[];sb=[];se=[]
   for d in self.durations:
    if start+timedelta(seconds=d)>b:
     sf.append(np.zeros(p.n));sb.append(np.full(p.n,2,dtype=np.uint8));se.append(np.zeros(p.n,dtype=np.uint8));continue
    raw=np.zeros(p.n);qband=np.zeros(p.n);cursor=start;end=start+timedelta(seconds=d)
    while cursor<end:
     slot=math.floor((cursor-a).total_seconds()/actor.slot_seconds)
     e=min(end,a+timedelta(seconds=(slot+1)*actor.slot_seconds),cursor+timedelta(seconds=120));mid=cursor+(e-cursor)/2
     lst=local_sidereal(mid,p.lon);malt=p._altaz(lst)[0]
     geo=p._public_quality(mid,lst,malt)*p.q0
     C,E=actor.belief_clock.prior(actor.C,actor.E,mid,seasonal_quality(mid.timetuple().tm_yday,p.q0)[0])
     scale=self.field.raw_scale_at(mid) if self.field is not None else np.ones(p.n)
     dt=(e-cursor).total_seconds();raw+=dt*C*E*geo*scale;qband+=dt*C*geo;cursor=e
    f=np.minimum(1.,p.flux*raw/p.f0t0)
    ba=np.where(qband/d>=p.dark_threshold,0,np.where(qband/d>=p.bright_threshold,1,2)).astype(np.uint8)
    h1=hour+SIDEREAL_SPEED*d;mc=np.minimum(np.cos(np.deg2rad(hour)),np.cos(np.deg2rad(h1)))
    critical=180+360*np.ceil((hour-180)/360);mc=np.where(critical<=h1,-1.,mc)
    mi=np.rad2deg(np.arcsin(np.clip(p.sin_lat*p.sin_dec+p.cos_lat*p.cos_dec*mc,-1.,1.)))
    sf.append(f);sb.append(ba);se.append((mi>=p.min_alt+.04).astype(np.uint8))
   factor.append(sf);band.append(sb);eligible.append(se)
   candidate_ids=np.flatnonzero(alt>=p.min_alt+.04) if current and start==now else self.reps[alt[self.reps]>=p.min_alt+.04]
   phases=(0,3,12,15) if current and start==now else (0,15)
   seen=set()
   for i in candidate_ids:
    near=np.asarray(self.tree.query_ball_point(p.eq_vectors[i],radius),dtype=np.int32)
    for phase in phases:
     row,col=divmod(phase,p.side);center=_shift_altaz(float(alt[i]),float(az[i]),-(row-(p.side-1)/2)*p.pitch,-(col-(p.side-1)/2)*p.pitch)
     key=tuple(round(float(x),7) for x in center)
     if key in seen or not 0<=center[0]<=90:continue
     seen.add(key);fi,hit,_=p._classify(vectors[near],*key);ids=near[hit];fi=fi[hit]
     if not len(ids):continue
     order=np.argsort(ids);ids=ids[order];fi=fi[order]
     fields.append(key);targets.append(ids);fibers.append(fi.astype(np.uint8));offset.append(offset[-1]+len(ids));field_start.append(si)
   if si%8==0:budget.check()
  self.factor=np.ascontiguousarray(factor);self.band=np.ascontiguousarray(band,dtype=np.uint8);self.eligible=np.ascontiguousarray(eligible,dtype=np.uint8)
  self.centers=np.asarray(fields);self.target=np.concatenate(targets).astype(np.int32);self.fiber=np.concatenate(fibers).astype(np.uint8)
  self.offset=np.asarray(offset,dtype=np.int32);self.field_start=np.asarray(field_start,dtype=np.int32);self.nfields=len(fields)
  # No score/fiber/target arrays are duplicated per duration or program.
  af=[];ad=[];ap=[]
  for f,s in enumerate(self.field_start):
   end=next(b for a,b in p.nights if a<=self.moments[s]<b)
   for d,dur in enumerate(self.durations):
    if self.moments[s]+timedelta(seconds=dur)>end:continue
    for pr in range(3):af.append(f);ad.append(d);ap.append(pr)
  self.af=np.asarray(af,dtype=np.int32);self.ad=np.asarray(ad,dtype=np.uint8);self.ap=np.asarray(ap,dtype=np.uint8);self.na=len(af)
  self.starts=self.ts[self.field_start[self.af]];self.ends=self.starts+np.asarray(self.durations)[self.ad]
  self.endpoints=np.unique(np.r_[self.starts,self.ends]);self.nt=len(self.endpoints)-1
  self.left=np.searchsorted(self.endpoints,self.starts).astype(np.int32);self.right=np.searchsorted(self.endpoints,self.ends).astype(np.int32)
  budget.stage('shared_whole_season_geometry_incidence_and_action_index',t,**self.metadata())
 def metadata(self):
  arr=['factor','band','eligible','centers','target','fiber','offset','field_start','af','ad','ap','starts','ends','endpoints','left','right']
  return dict(public_targets=self.n,starts=self.ns,fields=self.nfields,actions=self.na,shared_incidence_edges=len(self.target),
   materialized_program_duration_edges=0,referenced_edges=sum((self.offset[self.af+1]-self.offset[self.af]).tolist()),
   target_coverage=int(len(np.unique(self.target))),time_atoms=self.nt,bank_bytes=self.factor.nbytes+self.band.nbytes+self.eligible.nbytes,
   graph_array_bytes=sum(getattr(self,k).nbytes for k in arr),patterns=len(self.patterns))
 def scores(self,e,ids):
  f=int(self.af[e]);s=int(self.field_start[f]);d=int(self.ad[e]);pr=int(self.ap[e]);p=self.p
  return p.weight[ids]*self.factor[s,d,ids]*np.where(self.band[s,d,ids]==pr,p.multipliers[pr],p.mismatch)
 def pattern(self,e,b,sigma):
  f=int(self.af[e]);s=int(self.field_start[f]);d=int(self.ad[e]);sl=slice(self.offset[f],self.offset[f+1]);ids=self.target[sl];fib=self.fiber[sl]
  gain=np.maximum(0.,self.scores(e,ids)-b[ids])-sigma[ids];gain=np.where(self.eligible[s,d,ids],gain,-np.inf)
  chosen=[]
  for k in range(self.nfib):
   q=np.flatnonzero(fib==k)
   if not len(q):continue
   j=q[np.argmax(gain[q])]
   if gain[j]>0:chosen.append(int(ids[j]))
  return tuple(chosen)
 def oracle(self,b,sigma,lam,allowed):
  pref=np.r_[0.,np.cumsum(lam)];tc=np.ascontiguousarray(pref[self.right]-pref[self.left])
  out=np.empty(self.na);wit=np.empty(self.n,dtype=np.int32);bg=np.empty(self.n)
  LIB.price_shared(self.n,self.nfib,self.na,self.nd,ptr(self.offset),ptr(self.target),ptr(self.fiber),ptr(self.field_start),ptr(self.af),ptr(self.ad),ptr(self.ap),
   ptr(self.factor),ptr(self.band),ptr(self.eligible),ptr(self.p.weight),ptr(self.p.multipliers),self.p.mismatch,
   ptr(np.ascontiguousarray(b)),ptr(np.ascontiguousarray(sigma)),ptr(tc),ptr(np.ascontiguousarray(allowed,dtype=np.uint8)),ptr(out),ptr(wit),ptr(bg))
  return out,wit
 def add(self,e,ids):
  key=int(e),tuple(ids)
  if not ids or key in self.seen:return False
  self.seen.add(key);self.patterns.append(key);return True
 def seed(self,b,allowed):
  t=time.perf_counter();r,w=self.oracle(b,np.zeros(self.n),np.zeros(self.nt),allowed)
  selected=set(map(int,w[w>=0]));group=self.left*self.nd+self.ad
  order=np.lexsort((np.arange(self.na),-r,group));_,first=np.unique(group[order],return_index=True);selected.update(map(int,order[first]))
  for e in sorted(selected):
   if allowed[e]:self.add(e,self.pattern(e,b,np.zeros(self.n)))
  self.budget.stage('full_catalogue_seed_patterns',t,seed_patterns=len(self.patterns))
 def solve(self,b,blocked_until,seconds=4,relative_gap=.005,decision_margin=None):
  start=time.perf_counter();deadline=min(self.budget.start+self.budget.limit,start+seconds)
  allowed=(self.starts>=blocked_until-1e-7).astype(np.uint8)
  if not self.patterns:self.seed(b,allowed)
  last=None;support=[]
  while time.perf_counter()<deadline:
   self.budget.check();rows=[];cols=[];values=[];active=[]
   for e,ids in self.patterns:
    if not allowed[e]:continue
    c=len(active);active.append((e,ids));atoms=range(int(self.left[e]),int(self.right[e]))
    rows.extend(ids);rows.extend(self.n+j for j in atoms);cols.extend([c]*(len(ids)+self.right[e]-self.left[e]))
    values.append(float(np.maximum(0.,self.scores(e,np.asarray(ids))-b[list(ids)]).sum()))
   if not active:break
   A=coo_matrix((np.ones(len(rows)),(rows,cols)),shape=(self.n+self.nt,len(active))).tocsr()
   lp=linprog(-np.asarray(values),A_ub=A,b_ub=np.ones(self.n+self.nt),bounds=(0,None),method='highs',options={'threads':1,'time_limit':max(.001,deadline-time.perf_counter())})
   if not lp.success:
    self.trace.append(dict(status='restricted_master_incomplete',message=lp.message,seconds=time.perf_counter()-start));break
   sigma=np.maximum(0.,-lp.ineqlin.marginals[:self.n]);lam=np.maximum(0.,-lp.ineqlin.marginals[self.n:]);t=time.perf_counter()
   residual,_=self.oracle(b,sigma,lam,allowed);repair=np.zeros(self.nt);np.maximum.at(repair,self.left[allowed!=0],np.maximum(0.,residual[allowed!=0]))
   lower=float(-lp.fun);upper=float(sigma.sum()+lam.sum()+repair.sum());gap=upper-lower
   support=[dict(action=active[q][0],targets=list(active[q][1]),fraction=float(lp.x[q])) for q in np.flatnonzero(lp.x>1e-9)]
   last=dict(lower=lower,upper=upper,gap=gap,residual=max(0.,float(np.max(residual))),sigma=sigma,lam=lam,support=support,rounds=len(self.trace)+1)
   row=dict(lower=lower,upper=upper,gap=gap,max_residual=last['residual'],patterns=len(active),matrix_nonzeros=A.nnz,pricing_seconds=time.perf_counter()-t,elapsed_seconds=time.perf_counter()-start)
   self.trace.append(row)
   # Adaptive termination uses a certified finite-graph bound, not a fixed round count.
   if gap<=max(1e-7,relative_gap*max(1.,lower)) or (decision_margin is not None and gap<decision_margin):row['stop']='certified_gap';break
   eligible=np.flatnonzero(residual>1e-7);order=eligible[np.lexsort((eligible,-residual[eligible],self.left[eligible]))];groups={};added=0
   # More columns where the entire interval class is still expensive. This is
   # a memory/elapsed-budget algorithm choice; all actions are still priced.
   for e in order:
    g=int(self.left[e]);cnt=groups.get(g,0)
    if cnt>=8:continue
    if self.add(e,self.pattern(e,b,sigma)):groups[g]=cnt+1;added+=1
   row['added']=added
   if not added:row['stop']='no_new_pattern';break
  if last is not None:last['elapsed_seconds']=time.perf_counter()-start;last['stop']=self.trace[-1].get('stop','time_budget')
  return last
 def greedy(self,b,support):
  # A serialized actual deterministic max-ledger schedule. The ordering is
  # fixed from the fractional support, then each selected pattern is revalued.
  candidates=[]
  for row in support:
   e=row['action'];ids=np.asarray(row['targets'],dtype=int);gain=np.maximum(0.,self.scores(e,ids)-b[ids]).sum()
   candidates.append((-gain/(self.ends[e]-self.starts[e]),-row['fraction'],e,ids))
  candidates.sort(key=lambda r:r[:3]);ledger=b.copy();intervals=[];schedule=[]
  for _,_,e,ids in candidates:
   a,z=self.starts[e],self.ends[e]
   if any(a<v and u<z for u,v in intervals):continue
   c=self.scores(e,ids);keep=c>ledger[ids]+1e-10;ids=ids[keep];c=c[keep]
   if not len(ids):continue
   ledger[ids]=np.maximum(ledger[ids],c);intervals.append((a,z));schedule.append(dict(action=e,targets=ids.tolist(),scores=c.tolist(),start=float(a),end=float(z)))
  return dict(increment=float((ledger-b).sum()),schedule=schedule)
 def action(self,e,b,sigma,env):
  ids=self.pattern(e,b,sigma);f=int(self.af[e]);s=int(self.field_start[f]);d=int(self.ad[e]);pr=int(self.ap[e]);center=self.centers[f]
  commanded=(float(center[0])-float(env.get('pointing_offset_alt_deg',0)),(float(center[1])-float(env.get('pointing_offset_az_deg',0)))
  if not ids or not 0<=commanded[0]<=90:return None,None
  sl=slice(self.offset[f],self.offset[f+1]);lookup={int(i):int(q) for i,q in zip(self.target[sl],self.fiber[sl])}
  a=dict(action='observe',duration_seconds=self.durations[d],program=PROGRAMS[pr],pointing=dict(alt_deg=round(commanded[0],7),az_deg=round(commanded[1]%360,7)),assignments={str(lookup[i]):self.p.ids[i] for i in ids})
  alt,az,_,_=self.p._altaz(local_sidereal(self.moments[s],self.p.lon));c=self.scores(e,np.asarray(ids))
  pred={self.p.ids[i]:dict(index=i,fiber_id=lookup[i],factor=float(self.factor[s,d,i]),science_gain=float(max(0,c[j]-b[i])),predicted_band=PROGRAMS[int(self.band[s,d,i])],alt_deg=float(alt[i]),az_deg=float(az[i])) for j,i in enumerate(ids)}
  return a,pred
