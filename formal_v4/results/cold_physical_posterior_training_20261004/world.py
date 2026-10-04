"""CPU host independent worlds under fixed *public* physical sampling designs."""
from __future__ import annotations
import copy,json,pickle,sys,time,hashlib,math
from pathlib import Path
import numpy as np
from public_design import ROOT,OFFICIAL,utc
BASE_DIM=0;HISTORY=8
from challenge.v4_weather_simulator import generate_events,generate_weather,generate_bulletins,generate_forecasts,generate_stress_events
from challenge.v4_fiber_map import FiberGrid
KINDS=['earthquake','overcast','haze','cold_snap','rain','storm','rocket_launch','terrain_obstruction']
DIRECTIONS={k:45*j for j,k in enumerate(['N','NE','E','SE','S','SW','W','NW'])}
TOKEN_DIM=BASE_DIM+3*len(KINDS)+4
TAIL_DIM=8+3*len(KINDS)+len(KINDS)
XDIM=8*TOKEN_DIM+16+TAIL_DIM
_designs=None
def designs():
    global _designs
    if _designs is None:
        with (ROOT/'public_design_cache.pkl').open('rb') as f:_designs=pickle.load(f)
    return _designs
def season(day):
    a=math.sin(2*math.pi*(day-210)/365.2425);return (.88-.07*a)*(1-.12*a)/((1.1+.15*a)*.68)
def notice_features(notices,az):
    rows=[]
    for kind in KINDS:
        items=[n for n in notices if n['event_kind']==kind]
        allscope=any(n['direction']=='ALL' for n in items)
        cosine=max([math.cos(math.radians((az-DIRECTIONS[n['direction']]+180)%360-180)) for n in items if n['direction'] in DIRECTIONS],default=-1.)
        rows.extend([float(bool(items)),float(allscope),cosine if items else -1.])
    return np.asarray(rows)
def sector(az,start,end):return (az>=start)&(az<=end) if start<=end else (az>=start)|(az<=end)

class World:
    def __init__(self,seed,card=None):
        self.seed=seed;self.card=card or ['L1','L2'][seed%2];self.design=designs()[self.card];d=self.design
        cfg=json.loads((OFFICIAL/'challenge/reference/v4/v4_weather_config.json').read_text());cfg['seed']=int(seed);cfg['seed_derivation']='sha256-v1'
        rng=np.random.default_rng(seed+777)
        cfg['instrument_fault']['count']=int(rng.choice([0,1,2],p=[.25,.5,.25]));cfg['earthquake']['count']=int(rng.integers(0,3))
        for definition in cfg['weather_events']['conditions'].values():definition['count']=int(rng.integers(0,4))
        self.events,self.effects=generate_events(cfg,d['nights'],d['slots'])
        cfg['stress_tests']['enabled']=True
        self.stress=generate_stress_events(cfg,self.events)
        offset=next(x for x in self.stress if x['event_type']=='pointing_offset')
        self.offset=(math.degrees(float(offset['alt_offset_rad'])),math.degrees(float(offset['az_offset_rad'])))
        self.rows=generate_weather(cfg,d['nights'],d['slots'],self.events,self.effects)
        self.bulletins=[json.loads(s) for s in generate_bulletins(cfg,d['nights'],d['slots'],self.events,self.effects)]
        self.forecasts=[json.loads(s) for s in generate_forecasts(cfg,d['nights'],self.events)]
        self.cc=np.zeros(len(self.rows));self.eff=np.zeros(len(self.rows))
        for i,r in enumerate(self.rows):
            if r['is_observable']=='true':self.cc[i]=float(r['transparency'])*float(r['sky_quality'])/(float(r['seeing_arcsec'])*.68);self.eff[i]=float(r['instrument_efficiency'])
        self.faults=[e for e in self.events if e.event_type=='instrument_fault'];self.geometry=[]
        grid=FiberGrid(float(d['initial']['instrument']['fiber_area_deg2']),float(d['initial']['instrument']['gap_deg']),16)
        lat=float(d['initial']['site']['latitude_deg']);lon=float(d['initial']['site']['longitude_deg'])
        for original in d['actions']:
            from datetime import datetime,timezone
            hits=grid.assigned_hits(dict(zip(original['fibers'],original['target_ids'])),dict(zip(original['target_ids'],zip(original['ra'],original['dec']))),datetime.fromtimestamp(original['start'],timezone.utc),*original['pointing'],lat,lon,*self.offset)
            mask=np.asarray([hits[s] for s in original['target_ids']]);a=dict(original)
            for key in ['ids','fibers','ra','dec','h_public','nominal_hits']:a[key]=original[key][mask]
            a['target_ids']=[s for s,h in zip(original['target_ids'],mask) if h]
            for key in ['H','alt','az']:a[key]=original[key][:,mask]
            self.geometry.append(a)
        self.directional=[]
        directions=[e for e in self.events if e.scope_type=='HORIZON_SECTOR']
        for a in self.geometry:
            factor=np.ones(a['H'].shape)
            for e in directions:
                active=(a['times']>=e.actual_start_utc.timestamp())&(a['times']<e.actual_end_utc.timestamp())
                hit=active[:,None]&(a['alt']>=e.min_altitude_deg)&(a['alt']<=e.max_altitude_deg)&sector(a['az'],e.azimuth_start_deg,e.azimuth_end_deg)
                mult=0. if e.force_close or e.event_type in ['rocket_launch','terrain_obstruction'] else e.transparency_multiplier*e.sky_quality_multiplier*e.instrument_efficiency_multiplier/e.seeing_multiplier
                factor[hit]*=mult
            self.directional.append(factor)
        self.flux=d['flux'];self.weight=d['weight']
    def active(self,t,repaired):return next((f for f in self.faults if f.actual_start_utc.timestamp()<=t<f.actual_end_utc.timestamp() and f.event_id not in repaired),None)
    def score(self,j,repaired):
        a=self.geometry[j];eff=self.eff[a['slots']].copy()
        for f in self.faults:
            if f.event_id in repaired:
                active=(a['times']>=f.actual_start_utc.timestamp())&(a['times']<f.actual_end_utc.timestamp());eff[active]=np.minimum(1.,eff[active]/f.instrument_efficiency_multiplier)
        c=self.cc[a['slots']];qb=a['seconds']@(c[:,None]*a['H'])/a['duration']
        qz=a['seconds']@(c[:,None]*eff[:,None]*a['H']*self.directional[j])/a['duration']
        ids=a['ids'];factor=np.minimum(1.,self.flux[ids]*a['duration']*qz/450.);band=np.where(qb>=.65,0,np.where(qb>=.4,1,2));mult=np.where(band==a['program'],[1.2,1.12,1.06][a['program']],1.)
        return np.round(factor*self.weight[ids]*mult,6),factor,qb,qz

