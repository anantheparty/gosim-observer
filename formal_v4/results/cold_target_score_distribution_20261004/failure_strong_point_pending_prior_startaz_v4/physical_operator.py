"""Vector official-equivalent host labels. Public meshes do not know weather or hit.
A hidden boundary can refine host integration only; it never enters query features.
"""
from datetime import timedelta
import math
import numpy as np
from challenge.v4_fiber_map import min_altitude_during
from challenge.v4_scorer import DIRECTIONAL_MULTIPLIER_TYPES, _lunar_geometry
from challenge.tile_geometry_simulator import _local_sidereal_deg
from public_features import clip_duration,utc

D=math.pi/180
class PublicPhysics:
    def __init__(self,initial,planner):
        self.initial=initial;self.p=planner;self.cache={};self.calls=0;self.hits=0
    def at(self,indices,moment):
        p=self.p;i=np.asarray(indices,int);h=((_local_sidereal_deg(moment,p.lon)-p.ra[i]+180)%360-180)*D
        sd=p.sin_dec[i];cd=p.cos_dec[i]
        sa=p.sin_lat*sd+p.cos_lat*cd*np.cos(h);alt=np.arcsin(np.clip(sa,-1,1))/D;ca=np.maximum(1e-12,np.cos(alt*D))
        az=np.arctan2(-np.sin(h)*cd/ca,(sd-sa*p.sin_lat)/(ca*p.cos_lat))/D%360
        zen=90-np.maximum(alt,1e-10);air=(1/(np.cos(zen*D)+.50572*(96.07995-zen)**-1.6364))/(1/(1+.50572*96.07995**-1.6364))
        mr,md,illum,ma=_lunar_geometry(moment,p.lat,p.lon);lunar=np.ones(len(i))
        if ma>0:
            sep=np.arccos(np.clip(np.sin(p.dec[i]*D)*math.sin(md*D)+np.cos(p.dec[i]*D)*math.cos(md*D)*np.cos((p.ra[i]-mr)*D),-1,1))/D
            cfg=self.initial['scoring']['lunar_model'];lunar-=cfg['maximum_penalty']*illum*math.sin(ma*D)**cfg['altitude_exponent']*np.exp(-sep/cfg['angular_decay_scale_deg'])
        H=np.clip(lunar,0,1)/air**self.initial['scoring']['airmass_exponent']
        H=np.where(alt>0,H,0)
        return H,alt,az
    def mesh(self,start,duration,indices):
        duration=clip_duration(self.initial,start,duration);idx=tuple(map(int,indices));key=(start.isoformat(),duration,idx)
        self.calls+=1
        if key in self.cache:self.hits+=1;return self.cache[key]
        if duration<=0:raise ValueError('nonpositive canonical duration')
        night=next(n for n in self.initial['survey']['nights'] if utc(n['observing_start_utc'])<=start<utc(n['observing_end_utc']))
        anchor=utc(night['observing_start_utc']);slotsecs=self.initial['survey']['slot_seconds'];cursor=start;end=start+timedelta(seconds=duration)
        seconds=[];times=[];slots=[];H=[];alts=[];azs=[]
        while cursor<end:
            si=int((cursor-anchor).total_seconds()//slotsecs);right=min(end,anchor+timedelta(seconds=(si+1)*slotsecs));piece=cursor
            while piece<right:
                pe=min(right,piece+timedelta(seconds=120));t=piece+(pe-piece)/2;h,a,z=self.at(idx,t)
                seconds.append((pe-piece).total_seconds());times.append(t);slots.append(si);H.append(h);alts.append(a);azs.append(z);piece=pe
            cursor=right
        result=dict(start=start,duration=duration,indices=np.asarray(idx),night=night,seconds=np.asarray(seconds),times=times,slots=np.asarray(slots),H=np.asarray(H),alt=np.asarray(alts),az=np.asarray(azs))
        self.cache[key]=result;return result
    def query(self,mesh):
        idx=mesh['indices'];start=mesh['start'];d=mesh['duration'];p=self.p;seconds=mesh['seconds'];out=np.zeros((len(idx),51),np.float32)
        for slotj,si in enumerate(dict.fromkeys(mesh['slots'])):
            keep=mesh['slots']==si;w=seconds[keep];h=mesh['H'][keep];a=mesh['alt'][keep];z=mesh['az'][keep]*D
            out[:,slotj*8:(slotj+1)*8]=np.column_stack([w@h/w.sum(),h.min(0),h.max(0),a.min(0)/90,a.max(0)/90,w@np.sin(z)/w.sum(),w@np.cos(z)/w.sum(),np.full(len(idx),w.sum()/d)])
        _,a,z=self.at(idx,start);_,ae,ze=self.at(idx,start+timedelta(seconds=d))
        # The scalar official exact minimum admits targets; endpoints and possible lower transit.
        mins=np.array([min_altitude_during(p.ra[i],p.dec[i],start,start+timedelta(seconds=d),{'site':self.initial['site']}) for i in idx])
        season=(start-utc(self.initial['survey']['start_utc'])).total_seconds()/(utc(self.initial['survey']['end_utc'])-utc(self.initial['survey']['start_utc'])).total_seconds()
        phase=(start-utc(mesh['night']['observing_start_utc'])).total_seconds()/self.initial['survey']['slot_seconds']%1
        out[:,40:]=np.column_stack([np.log(np.maximum(.001,p.flux[idx]))/4,np.full(len(idx),d/p.tmax),a/90,mins/90,np.sin(z*D),np.cos(z*D),ae/90,np.sin(ze*D),np.cos(ze*D),np.full(len(idx),season),np.full(len(idx),phase)])
        return out

def host_factor(mesh,physics,scenario,weather):
    """F/b physically independent of pointing, assignment, weight and declared program."""
    start=mesh['start'];duration=mesh['duration'];end=start+timedelta(seconds=duration);idx=mesh['indices'];events=[e for e in scenario.events if e.scope_type=='HORIZON_SECTOR' and e.overlaps(start,end)]
    pieces=list(weather.segments(start,end));qb=np.zeros(len(idx));raw=np.zeros(len(idx));cursor=start;sample_index=0
    for seconds,truth in pieces:
        se=cursor+timedelta(seconds=seconds);cuts={cursor,se}
        for event in events:
            if cursor<event.actual_start_utc<se:cuts.add(event.actual_start_utc)
            if cursor<event.actual_end_utc<se:cuts.add(event.actual_end_utc)
        # Band mesh is public slot-overlap <=120s, excludes directional events.
        piece=cursor
        while piece<se:
            pe=min(se,piece+timedelta(seconds=120));t=piece+(pe-piece)/2
            if t in mesh['times']:
                sj=mesh['times'].index(t);h=mesh['H'][sj]
            else:h,_,_=physics.at(idx,t)
            if truth is not None and truth.is_observable:qb+=(pe-piece).total_seconds()*truth.transparency*truth.sky_quality/truth.seeing_arcsec/scenario.score_config['q0']*h
            piece=pe
        boundaries=sorted(cuts)
        for left,right in zip(boundaries,boundaries[1:]):
            piece=left
            while piece<right:
                pe=min(right,piece+timedelta(seconds=120));t=piece+(pe-piece)/2
                if t in mesh['times']:
                    sj=mesh['times'].index(t);h=mesh['H'][sj];alt=mesh['alt'][sj];az=mesh['az'][sj]
                else:h,alt,az=physics.at(idx,t)
                if truth is not None and truth.is_observable:
                    attenuation=np.ones(len(idx))
                    for event in events:
                        if not event.actual_start_utc<=t<event.actual_end_utc:continue
                        azkeep=((az>=event.azimuth_start_deg)&(az<=event.azimuth_end_deg)) if event.azimuth_start_deg<=event.azimuth_end_deg else ((az>=event.azimuth_start_deg)|(az<=event.azimuth_end_deg))
                        cover=azkeep&(alt>=event.min_altitude_deg)&(alt<=event.max_altitude_deg)
                        if event.force_close or event.event_type in ('terrain_obstruction','rocket_launch'):attenuation[cover]=0
                        elif event.event_type in DIRECTIONAL_MULTIPLIER_TYPES:attenuation[cover]*=event.transparency_multiplier*event.sky_quality_multiplier*event.instrument_efficiency_multiplier/event.seeing_multiplier
                    scale=truth.transparency*truth.sky_quality/truth.seeing_arcsec*weather._apply_fault(truth,t)/scenario.score_config['q0']
                    raw+=(pe-piece).total_seconds()*h*scale*attenuation
                piece=pe
        cursor=se
    cfg=scenario.score_config;b=np.where(qb/duration>=cfg['program']['bands']['DARK'],0,np.where(qb/duration>=cfg['program']['bands']['BRIGHT'],1,2))
    F=np.minimum(1,physics.p.flux[idx]*raw/(cfg['flux_zero_point']*cfg['exposure_zero_point_seconds']))
    return F,b
