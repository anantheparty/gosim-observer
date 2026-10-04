"""Public current-action ledger under the explicit conditional C/E field model."""
import math
from datetime import timedelta
import numpy as np
from research.spatial_candidates import local_sidereal,PROGRAMS
from research.feedback_model import seasonal_quality

def score_action(graph,action,env,b):
 p=graph.p;now=graph.now;actor=graph.actor;ledger=b.copy()
 if not action or action.get('action')!='observe':return ledger
 ids=np.asarray([p.index[t] for t in action['assignments'].values()],dtype=int)
 d=int(action['duration_seconds']);pr=PROGRAMS.index(action['program']);start=now;end=start+timedelta(seconds=d)
 a,z=next((a,z) for a,z in p.nights if a<=start<z)
 if end>z:raise ValueError('uncanonical night-clipped action')
 alt,az,hour,vectors=p._altaz(local_sidereal(start,p.lon));center=(float(action['pointing']['alt_deg'])+float(env.get('pointing_offset_alt_deg',0)),float(action['pointing']['az_deg'])+float(env.get('pointing_offset_az_deg',0)))
 fi,hit,_=p._classify(vectors[ids],*center)
 if not np.all(hit):raise ValueError('assigned target outside guarded predicted fibre')
 if list(map(int,action['assignments'].keys()))!=fi.tolist():raise ValueError('assigned fibre mismatches guarded predicted geometry')
 raw=np.zeros(len(ids));qb=np.zeros(len(ids));cursor=start
 while cursor<end:
  slot=math.floor((cursor-a).total_seconds()/actor.slot_seconds);e=min(end,a+timedelta(seconds=(slot+1)*actor.slot_seconds),cursor+timedelta(seconds=120));mid=cursor+(e-cursor)/2
  lst=local_sidereal(mid,p.lon);ma=p._altaz(lst)[0];geo=p._public_quality(mid,lst,ma)[ids]*p.q0
  C,E=actor.belief_clock.prior(actor.C,actor.E,mid,seasonal_quality(mid.timetuple().tm_yday,p.q0)[0]);scale=graph.field.raw_scale_at(mid,ids) if graph.field else np.ones(len(ids));dt=(e-cursor).total_seconds()
  raw+=dt*C*E*geo*scale;qb+=dt*C*geo;cursor=e
 factor=np.minimum(1,p.flux[ids]*raw/p.f0t0);band=np.where(qb/d>=p.dark_threshold,0,np.where(qb/d>=p.bright_threshold,1,2));score=p.weight[ids]*factor*np.where(band==pr,p.multipliers[pr],p.mismatch)
 ledger[ids]=np.maximum(ledger[ids],score);return ledger
