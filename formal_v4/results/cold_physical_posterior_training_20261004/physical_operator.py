"""Independent finite-path score operator: exact official <=120-second mesh."""
from datetime import datetime,timedelta,timezone
import numpy as np
from physical_core import *
from challenge.v4_fiber_map import radec_to_altaz,min_altitude_during,FiberGrid,altaz_to_radec
from challenge.v4_scorer import lunar_quality_factor,_normalized_airmass

def mesh(w,start,end,ra,dec,cuts):
    initial=w.design['initial'];lat=initial['site']['latitude_deg'];lon=initial['site']['longitude_deg'];pieces=[]
    for l,r in zip(cuts,cuts[1:]):
        cursor=l
        while cursor<r-1e-9:
            right=min(r,cursor+120);mid=(cursor+right)/2;t=datetime.fromtimestamp(mid,timezone.utc)
            aa=np.asarray([radec_to_altaz(float(a),float(b),t,lat,lon) for a,b in zip(ra,dec)])
            h=np.asarray([_normalized_airmass(float(alt))**(-initial['scoring']['airmass_exponent'])*lunar_quality_factor(float(a),float(b),t,initial['site'],initial['scoring']) for a,b,alt in zip(ra,dec,aa[:,0])])
            pieces.append((right-cursor,mid,aa[:,0],aa[:,1],h));cursor=right
    return pieces

def qualities(w,j,ra,dec,duration,paths):
    a=w.design['actions'][j];start=a['start'];origin=w.design['slots'][int(a['slots'][0])].timestamp_utc.timestamp();end=start+duration
    cuts=sorted({start,end,*[origin+900*k for k in range(1,6) if start<origin+900*k<end]})
    bandmesh=mesh(w,start,end,ra,dec,cuts);cc=np.asarray([p['c'] for p in paths]);ee=np.asarray([p['e'] for p in paths]);oo=np.asarray([p['o'] for p in paths])
    qb=np.zeros((len(paths),len(ra)));qz=np.zeros_like(qb)
    max_events=max(1,max(len(p['events']) for p in paths));evmat=np.zeros((len(paths),max_events,7));evmat[:,:,6]=1.
    for z,p in enumerate(paths):
        for r,ev in enumerate(p['events']):evmat[z,r]=[ev['start'],ev['end'],ev['alt0'],ev['alt1'],ev['az0'],ev['az1'],ev['mult']]
    for span,t,alt,az,h in bandmesh:
        k=min(4,int((t-origin)//900));qb+=span*cc[:,k,None]*oo[:,k,None]*h[None,:]/duration
    # Group paths by boundary signatures: do not change one path's quadrature
    # by inserting a different path's irrelevant off-grid event boundaries.
    groups={}
    for z,p in enumerate(paths):
        boundaries=tuple(sorted({*cuts,*[origin+ev[t] for ev in p['events'] for t in ['start','end'] if start<origin+ev[t]<end]}));groups.setdefault(boundaries,[]).append(z)
    for bounds,index in groups.items():
        em=evmat[index];es,et,al,ah,az0,az1,mult=[em[:,:,k,None] for k in range(7)]
        for span,t,alt,az,h in mesh(w,start,end,ra,dec,bounds):
            k=min(4,int((t-origin)//900));delta=t-origin
            inside=np.where(az0<=az1,(az[None,None,:]>=az0)&(az[None,None,:]<=az1),(az[None,None,:]>=az0)|(az[None,None,:]<=az1))
            cover=(delta>=es)&(delta<et)&(alt[None,None,:]>=al)&(alt[None,None,:]<=ah)&inside
            att=np.where(cover,mult,1.).prod(axis=1)
            qz[index]+=span*cc[index,k,None]*ee[index,k,None]*oo[index,k,None]*h[None,:]*att/duration
    return qb,qz

def contributions(qb,qz,flux,weight,duration,program):
    band=np.where(qb>=.65,0,np.where(qb>=.4,1,2));factor=np.minimum(1.,flux[None,:]*duration*qz/450.)
    mult=np.where(band==program,[1.2,1.12,1.06][program],1.)
    return factor*weight[None,:]*mult

def gate():
    from challenge.v4_scorer import SlotTruth,WeatherTruth,ScoreEvent,program_multiplier,program_band,score_target_exposure
    rows=[];err=0.;checks=0
    for seed in [909000,909001,909002,909003]:
        w=World(seed);rng=np.random.default_rng(seed)
        for j in rng.choice(len(w.geometry),12,replace=False):
            a=w.geometry[j];p=path(w,int(j),set());qb,qz=qualities(w,int(j),a['ra'],a['dec'],a['duration'],[p])
            # This comparison includes new independent geometry hits and all
            # directional events; official functions reconstruct their own mesh.
            slots=[]
            for r,s in zip(w.rows,w.design['slots']):
                yes=r['is_observable']=='true';slots.append(SlotTruth(s.slot_id,s.timestamp_utc,s.end_utc,yes,*[float(r[k]) if yes else 0. for k in ['seeing_arcsec','transparency','sky_quality','instrument_efficiency']]))
            events=[ScoreEvent(e.event_id,e.event_type,e.actual_start_utc,e.actual_end_utc,e.scope_type,e.azimuth_start_deg,e.azimuth_end_deg,e.min_altitude_deg,e.max_altitude_deg,e.seeing_multiplier,e.transparency_multiplier,e.sky_quality_multiplier,e.instrument_efficiency_multiplier,e.force_close) for e in w.events]
            weather=WeatherTruth(slots,[e for e in events if e.event_type=='instrument_fault']);start=datetime.fromtimestamp(a['start'],timezone.utc);end=datetime.fromtimestamp(a['end'],timezone.utc);sc=w.design['initial']['scoring'];site=w.design['initial']['site']
            for z,(ra,dec,idx) in enumerate(zip(a['ra'],a['dec'],a['ids'])):
                at=lambda t,ra=ra,dec=dec:radec_to_altaz(float(ra),float(dec),t,site['latitude_deg'],site['longitude_deg'])
                bandq=weather.band_quality(start,end,sc,lambda t:at(t)[0],lambda t,ra=ra,dec=dec:lunar_quality_factor(float(ra),float(dec),t,site,sc));err=max(err,abs(bandq-qb[0,z]))
                target=dict(target_id=str(idx),ra_deg=float(ra),dec_deg=float(dec),feature_flux=float(w.flux[idx]),science_weight=float(w.weight[idx]))
                for program in range(3):
                    score=score_target_exposure(target,list(weather.segments(start,end)),[e for e in events if e.scope_type=='HORIZON_SECTOR' and e.overlaps(start,end)],weather,a['duration'],program_multiplier(['DARK','BRIGHT','BACKUP'][program],program_band(bandq,sc),sc),sc,start,at,site)
                    expected=contributions(qb,qz,w.flux[a['ids']],w.weight[a['ids']],a['duration'],program)[0,z];err=max(err,abs(score.score-expected),abs(score.quality-qz[0,z]));checks+=1
            rows.append(dict(seed=int(seed),j=int(j),hits=len(a['ids']),duration=a['duration'],slots=int(len(np.unique(a['slots']))),directional_events=len(p['events'])))
    result=dict(checks=checks,max_error=float(err),pass_gate=bool(err<1e-10),rows=rows)
    (ROOT/'operator_gate.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='rows'}))
    assert result['pass_gate']
if __name__=='__main__':gate()
