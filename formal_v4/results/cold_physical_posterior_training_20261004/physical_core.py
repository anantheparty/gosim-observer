"""Finite joint physical five-slot posterior. Inputs contain public records only."""
from __future__ import annotations
import json,math,hashlib
from pathlib import Path
import numpy as np
from world import ROOT,World,KINDS,DIRECTIONS,designs

HISTORY=8
DIRS=['ALL','N','NE','E','SE','S','SW','W','NW']
TARGET_DIM=15
TOKEN_DIM=16*TARGET_DIM+10+len(KINDS)*len(DIRS)
TAIL_DIM=16+len(KINDS)*len(DIRS)*2
XDIM=HISTORY*TOKEN_DIM+TAIL_DIM
PROBE_ALT=np.array([20.,40.,60.,85.])
PROBE_AZ=np.arange(8)*45.

def notices_vector(notices):
    v=np.zeros((len(KINDS),len(DIRS)))
    for n in notices:
        if n['event_kind'] in KINDS and n['direction'] in DIRS:v[KINDS.index(n['event_kind']),DIRS.index(n['direction'])]=1
    return v.ravel()

def path(w,j,repaired):
    """Host truth label; never part of a model input."""
    a=w.design['actions'][j];origin=int(a['slots'][0]);slot=w.design['slots'][origin]
    anchor=slot.timestamp_utc.timestamp();night=slot.night_id
    c=np.zeros(5);e=np.zeros(5);o=np.zeros(5,dtype=np.uint8);fault=np.zeros(5,dtype=np.uint8)
    for k in range(5):
        si=origin+k
        if si>=len(w.rows) or w.design['slots'][si].night_id!=night:continue
        c[k]=w.cc[si];e[k]=w.eff[si];o[k]=int(c[k]>0)
        fault[k]=int(w.active(anchor+900*k,repaired) is not None)
        for f in w.faults:
            if f.event_id in repaired and f.actual_start_utc.timestamp()<=anchor+900*k<f.actual_end_utc.timestamp():e[k]=min(1.,e[k]/f.instrument_efficiency_multiplier)
    ev=[]
    for f in w.events:
        if f.scope_type!='HORIZON_SECTOR' or f.actual_start_utc.timestamp()>=anchor+4500 or f.actual_end_utc.timestamp()<=anchor:continue
        ev.append(dict(kind=f.event_type,start=max(0.,f.actual_start_utc.timestamp()-anchor),end=min(4500.,f.actual_end_utc.timestamp()-anchor),az0=f.azimuth_start_deg,az1=f.azimuth_end_deg,alt0=f.min_altitude_deg,alt1=f.max_altitude_deg,
            mult=0. if f.force_close or f.event_type in ['terrain_obstruction','rocket_launch'] else f.transparency_multiplier*f.sky_quality_multiplier*f.instrument_efficiency_multiplier/f.seeing_multiplier))
    return dict(c=c.tolist(),e=e.tolist(),o=o.tolist(),fault=fault.tolist(),events=ev)

def attenuation(p,t,alt,az):
    z=np.ones(np.broadcast_shapes(np.shape(t),np.shape(alt),np.shape(az)))
    for ev in p['events']:
        inside=(az>=ev['az0'])&(az<=ev['az1']) if ev['az0']<=ev['az1'] else (az>=ev['az0'])|(az<=ev['az1'])
        cover=(t>=ev['start'])&(t<ev['end'])&(alt>=ev['alt0'])&(alt<=ev['alt1'])&inside
        z=np.where(cover,z*ev['mult'],z)
    return z

def path_feature(p):
    o=np.asarray(p['o']);c=np.asarray(p['c']);e=np.asarray(p['e'])
    tt=np.arange(5)[:,None,None]*900+450
    aa=PROBE_ALT[None,:,None];zz=PROBE_AZ[None,None,:]
    return np.concatenate([3*o,np.log(np.maximum(c,.001))*o,2*e*o,np.asarray(p['fault']),.5*attenuation(p,tt,aa,zz).ravel()]).astype(np.float32)

def label_weights(p,bank_features,allowed=None):
    f=path_feature(p);dist=np.sum((bank_features-f)**2,axis=1)
    if allowed is not None:dist=np.where(allowed,dist,np.inf)
    idx=np.argsort(dist,kind='stable')[:8];z=np.exp(-(dist[idx]-dist[idx[0]])/.5);z/=z.sum()
    return idx.astype(np.int16),z.astype(np.float32),float(dist[idx[0]])

class PublicHistory:
    def __init__(self,w):
        self.tokens=[];self.last_report=None;self.last_outcome=0.;self.correct=0;self.false=0;self.resync_count=0
        self.terrain=[n for n in w.bulletins[0]['notices'] if n['event_kind']=='terrain_obstruction']
    def report(self,t,correct):
        self.last_report=t;self.last_outcome=1. if correct else -1.;self.correct+=int(correct);self.false=0 if correct else self.false+1
    def ingest(self,w,j,scores):
        a=w.design['actions'][j];actual=w.geometry[j];lookup=dict(zip(actual['target_ids'],scores));hit=set(actual['target_ids'])
        rows=np.zeros((16,TARGET_DIM));origin=int(a['slots'][0]);hours=np.zeros((5,len(a['ids'])))
        for q in range(len(a['seconds'])):hours[int(a['slots'][q])-origin]+=a['seconds'][q]*a['H'][q]/a['duration']
        for z,(tid,idx,fiber) in enumerate(zip(a['target_ids'],a['ids'],a['fibers'])):
            ra=math.radians(a['ra'][z]);dec=math.radians(a['dec'][z]);az=math.radians(a['az'][0,z])
            rows[int(fiber)]=[1.,float(tid in hit),lookup.get(tid,0.)/w.weight[idx],math.log(max(w.flux[idx],1e-6)),math.sin(ra),math.cos(ra),math.sin(dec),*hours[:,z],a['alt'][0,z]/90,math.sin(az),math.cos(az)]
        n=a['night'];night=w.design['nights'][n];notice=[]
        # Exposure records keep the start bulletin; later delivered slot notices
        # are in the current query tail, never guessed from future events.
        notice.extend(w.bulletins[origin]['notices']);notice.extend(self.terrain)
        az=math.radians(a['pointing'][1]);doy=night.night_date.timetuple().tm_yday
        meta=[a['duration']/3600,*[float(a['program']==k) for k in range(3)],a['pointing'][0]/90,math.sin(az),math.cos(az),n/38,(a['start']-night.observing_start_utc.timestamp())/night.night_seconds,doy/366]
        token=np.concatenate([rows.ravel(),meta,notices_vector(notice)]).astype(np.float32)
        assert len(token)==TOKEN_DIM
        self.tokens.append((token,a['end'],n));self.tokens=self.tokens[-HISTORY:]
    def feature(self,w,j):
        if len(self.tokens)<HISTORY:return None
        a=w.design['actions'][j];n=a['night'];night=w.design['nights'][n];t=a['start'];si=int(a['slots'][0])
        forecast=next((f for f in reversed(w.forecasts) if wutc(f['issued_at_utc'])<=t),{})
        fn=[f for f in forecast.get('notices',[]) if night.night_date.isoformat() in f.get('nights',[])]
        age=192. if self.last_report is None else min(192.,(t-self.last_report)/900)
        ages=[min(192.,max(0.,(t-r[1])/900))/64 for r in self.tokens]
        nightages=[min(38,n-r[2])/38 for r in self.tokens]
        doy=night.night_date.timetuple().tm_yday
        meta=[doy/366,n/38,(t-night.observing_start_utc.timestamp())/night.night_seconds,(t-night.observing_start_utc.timestamp())%900/900,age/64,self.last_outcome,self.correct/4,self.false/4,self.resync_count/4,float(self.last_report==t),math.sin(doy*2*math.pi/365.2425),math.cos(doy*2*math.pi/365.2425),*ages[:2],*nightages[:2]]
        # RA/Dec, date, night fraction, duration and five H weights are retained.
        # Float32 feature rounding is a representation approximation; raw public
        # sampling design remains available for exact reconstruction and scoring.
        tail=np.concatenate([meta,notices_vector([*w.bulletins[si]['notices'],*self.terrain]),notices_vector(fn)])
        x=np.concatenate([np.concatenate([r[0] for r in self.tokens]),tail]).astype(np.float32)
        assert len(x)==XDIM and np.isfinite(x).all();return x

def wutc(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()

class Predictor:
    def __init__(self,p):
        z=np.load(p);self.mean=z['mean'];self.std=z['std'];self.temp=float(z['temperature']);self.healthy=z['healthy'].astype(bool);self.weights=[z[f'w{k}'] for k in range(3)];self.bias=[z[f'b{k}'] for k in range(3)]
    def probabilities(self,x):
        raw=np.asarray(x);same_report=raw[...,HISTORY*TOKEN_DIM+9]>0.5
        x=(raw-self.mean)/self.std
        for k in range(3):
            x=x@self.weights[k].T+self.bias[k]
            if k<2:x=np.maximum(x,0)
        x=x/self.temp;x-=x.max(axis=-1,keepdims=True);x=np.exp(x)
        x=np.where(np.asarray(same_report)[...,None]&~self.healthy,0.,x)
        return x/x.sum(axis=-1,keepdims=True)
