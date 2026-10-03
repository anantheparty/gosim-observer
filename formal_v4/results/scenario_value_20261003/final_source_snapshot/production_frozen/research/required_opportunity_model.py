"""Required-target single-exposure opportunity model using public data only.

Raw factor is always capped at one. A cap on normalized Q or on the site scalar
Z=efficiency*transparency*sky/seeing is an explicit assumption, not a public fact.
Geometry upper envelopes enclose the official <=120s midpoint integration.
Frozen predictions and exact checked candidate starts remain conditional models.
"""
from __future__ import annotations

import csv,json,math
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np

DEG=math.pi/180
SPEED=360.98564736629/86400


def parse(value):
    return value if isinstance(value,datetime) else datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)


def stamp(seconds):
    return datetime.fromtimestamp(float(seconds),timezone.utc).isoformat().replace('+00:00','Z')


def public_initial(card):
    card=Path(card)
    scenario=json.loads((card/'config/v4_scenario.json').read_text())
    fiber=json.loads((card/'config/v4_fiber_config.json').read_text())
    score=json.loads((card/'config/v4_score_config.json').read_text())
    rows=list(csv.DictReader((card/'public/targets.csv').open()))
    nights=list(csv.DictReader((card/'public/v4_night_calendar.csv').open()))
    columns=list(rows[0])
    site={**scenario['site'],'minimum_altitude_deg':scenario['minimum_altitude_deg']}
    return {'site':site,'targets':{'columns':columns,'rows':[[row[c] for c in columns] for row in rows]},
            'instrument':{'exposure':fiber['exposure']},'scoring':score,
            'survey':{'nights':nights,'slot_seconds':900}}


class RequiredOpportunityModel:
    def __init__(self,initial,*,grid_seconds=60):
        self.initial=initial
        self.grid_seconds=int(grid_seconds)
        site=initial['site']
        self.latitude=float(site['latitude_deg']);self.longitude=float(site['longitude_deg'])
        self.minimum_altitude=float(site.get('minimum_altitude_deg',30))
        self.sinlat,self.coslat=math.sin(self.latitude*DEG),math.cos(self.latitude*DEG)
        data=initial['targets'];columns={name:i for i,name in enumerate(data['columns'])}
        rows=[row for row in data['rows'] if str(row[columns['required']]).lower() in ('true','1')]
        self.ids=[str(row[columns['target_id']]) for row in rows];self.index={tid:i for i,tid in enumerate(self.ids)}
        self.ra=np.array([float(row[columns['ra_deg']]) for row in rows]);self.dec=np.array([float(row[columns['dec_deg']]) for row in rows])
        self.flux=np.array([float(row[columns['feature_flux']]) for row in rows])
        self.sin_dec,self.cos_dec=np.sin(self.dec*DEG),np.cos(self.dec*DEG)
        score=initial['scoring'];self.score=score;self.q0=float(score['q0'])
        self.f0t0=float(score['flux_zero_point'])*float(score['exposure_zero_point_seconds'])
        self.beta=float(score['airmass_exponent']);self.lunar=score['lunar_model']
        self.threshold=float(score['required']['observed_factor_threshold'])
        exposure=initial['instrument']['exposure'];self.tmin=int(exposure['min_duration_seconds']);self.tmax=int(exposure['max_duration_seconds'])
        self.nights=[(parse(row['observing_start_utc']).timestamp(),parse(row['observing_end_utc']).timestamp()) for row in initial['survey']['nights']]
        self.night_dates=[row.get('night_date',str(row.get('night_id',i))) for i,row in enumerate(initial['survey']['nights'])]
        self.slot_seconds=int(initial['survey'].get('slot_seconds',900))
        value=(math.sin(self.minimum_altitude*DEG)-self.sinlat*self.sin_dec)/(self.coslat*self.cos_dec)
        self.hmax=np.arccos(np.clip(value,-1,1))/DEG
        self.hmax[value>=1]=0;self.hmax[value<=-1]=180
        self._cache={}

    def _lst(self,times):
        days=np.asarray(times)/86400+2440587.5-2451545
        return (280.46061837+360.98564736629*days+self.longitude)%360

    def _alt(self,times,indices):
        indices=np.asarray(indices,dtype=int)
        hour=(self._lst(np.asarray(times))[:,None]-self.ra[indices][None,:]+180)%360-180
        sine=self.sinlat*self.sin_dec[indices][None,:]+self.coslat*self.cos_dec[indices][None,:]*np.cos(hour*DEG)
        return np.arcsin(np.clip(sine,-1,1))/DEG

    def _air_quality(self,alt):
        zenith=90-np.maximum(alt,1.)
        raw=1/(np.cos(zenith*DEG)+.50572*(96.07995-zenith)**-1.6364)
        norm=1/(1+.50572*96.07995**-1.6364)
        return 1/(self.q0*(raw/norm)**self.beta)

    def public_quality(self,times,indices):
        """H/q0 = lunar/(q0*airmass**beta), matrix [time,target]."""
        times=np.asarray(times,dtype=float);indices=np.asarray(indices,dtype=int)
        days=times/86400+2440587.5-2451545
        solar_mean=(280.460+.9856474*days)%360
        anomaly=((357.528+.9856003*days)%360)*DEG
        slon=(solar_mean+1.915*np.sin(anomaly)+.020*np.sin(2*anomaly))*DEG
        ob=(23.439-.0000004*days)*DEG
        sun=np.stack((np.cos(slon),np.sin(slon)*np.cos(ob),np.sin(slon)*np.sin(ob)),axis=1)
        lon=((218.316+13.176396*days)%360)*DEG+6.289*DEG*np.sin(((134.963+13.064993*days)%360)*DEG)
        lat=5.128*DEG*np.sin(((93.272+13.229350*days)%360)*DEG)
        moon=np.stack((np.cos(lon)*np.cos(lat),np.sin(lon)*np.cos(lat)*np.cos(ob)-np.sin(lat)*np.sin(ob),
                       np.sin(lon)*np.cos(lat)*np.sin(ob)+np.sin(lat)*np.cos(ob)),axis=1)
        illum=(1-np.sum(sun*moon,axis=1))/2
        mdec=np.arcsin(np.clip(moon[:,2],-1,1));mra=np.arctan2(moon[:,1],moon[:,0])/DEG%360
        malt=np.arcsin(np.clip(self.sinlat*np.sin(mdec)+self.coslat*np.cos(mdec)*np.cos(((self._lst(times)-mra+180)%360-180)*DEG),-1,1))
        vectors=np.stack((self.cos_dec[indices]*np.cos(self.ra[indices]*DEG),self.cos_dec[indices]*np.sin(self.ra[indices]*DEG),self.sin_dec[indices]),axis=1)
        sep=np.arccos(np.clip(np.einsum('ij,kj->ik',moon,vectors),-1,1))/DEG
        lunar=1-float(self.lunar['maximum_penalty'])*illum[:,None]*np.maximum(0,np.sin(malt))[:,None]**float(self.lunar['altitude_exponent'])*np.exp(-sep/float(self.lunar['angular_decay_scale_deg']))
        lunar[malt<=0]=1
        return np.clip(lunar,0,1)*self._air_quality(self._alt(times,indices))

    def windows(self,index,night,now=None):
        a,b=self.nights[night]
        if now is not None:a=max(a,parse(now).timestamp() if isinstance(now,(str,datetime)) else float(now))
        if a>=b or self.hmax[index]<=0:return []
        if self.hmax[index]>=180:return [(a,b)]
        anchor=self.nights[night][0];span=(b-anchor)*SPEED
        rise=(self.ra[index]-self.hmax[index]-float(self._lst([anchor])[0]))%360
        result=[]
        for offset in (rise-360,rise,rise+360):
            left=max(a,anchor+offset/SPEED);right=min(b,anchor+(offset+2*self.hmax[index])/SPEED)
            if right-left>=self.tmin:result.append((float(left),float(right)))
        return sorted(result)

    def _night_cache(self,night):
        if night in self._cache:return self._cache[night]
        a,b=self.nights[night]
        nodes=np.unique(np.r_[np.arange(a,b,self.grid_seconds),b])
        mid=(nodes[:-1]+nodes[1:])/2
        indices=np.arange(len(self.ids))
        predicted=self.public_quality(mid,indices)
        # A scoring midpoint lies <=60s from each time that its weight represents.
        left,right=nodes[:-1]-60,nodes[1:]+60
        al=self._alt(left,indices);ar=self._alt(right,indices)
        peak=np.maximum(al,ar)
        rising=(self.ra[None,:]-self._lst(left)[:,None])%360
        crosses=rising<=(right-left)[:,None]*SPEED
        culmination=90-np.abs(self.latitude-self.dec)
        peak=np.where(crosses,np.maximum(peak,culmination[None,:]),peak)
        upper=self._air_quality(peak)+1e-12 # lunar<=1; slight numerical guard
        widths=np.diff(nodes)[:,None]
        prediction_prefix=np.vstack((np.zeros(len(indices)),np.cumsum(widths*predicted,axis=0)))
        upper_prefix=np.vstack((np.zeros(len(indices)),np.cumsum(widths*upper,axis=0)))
        self._cache[night]=(nodes,prediction_prefix,upper_prefix)
        return self._cache[night]

    def exact_integrals(self,index,night,starts,durations):
        """Exactly match official public slot/<=120s midpoint partitions."""
        starts=np.asarray(starts,dtype=float);durations=np.asarray(durations,dtype=float)
        cursor=starts.copy();end=starts+durations;totals=np.zeros(len(starts))
        anchor=self.nights[night][0]
        while np.any(cursor<end-1e-9):
            active=np.flatnonzero(cursor<end-1e-9)
            c=cursor[active]
            slot=np.floor((c-anchor)/self.slot_seconds)
            segment_end=np.minimum(end[active],anchor+(slot+1)*self.slot_seconds)
            piece_end=np.minimum(segment_end,c+120)
            width=piece_end-c
            if np.any(width<=0):raise ValueError('midpoint partition failed to advance')
            quality=self.public_quality((c+piece_end)/2,[index])[:,0]
            totals[active]+=width*quality
            cursor[active]=piece_end
        return totals

    def profile(self,index,night,*,site_scale=.55,duration_safety=1.,site_scale_cap=1.,now=None,exact_refine=False):
        """Upper certificate (conditional cap) plus frozen prediction/lower sample.

        latest_upper is an upper bound on possible starts under site_scale_cap.
        latest_checked is a checked feasible start under frozen site_scale/safety.
        A grid/exact checked maximum is a lower bound on frozen model optimum.
        """
        nodes,prefix,upper=self._night_cache(night)
        factor_coeff=self.flux[index]/self.f0t0
        threshold_mass=self.threshold/max(factor_coeff*site_scale/duration_safety,1e-300)
        upper_need=self.threshold/max(factor_coeff*site_scale_cap,1e-300)
        wins=self.windows(index,night,now)
        result={'target_id':self.ids[index],'night':night,'night_date':self.night_dates[night],
                'windows_utc':[[stamp(a),stamp(b)] for a,b in wins],'visible_seconds':sum(b-a for a,b in wins),
                'raw_factor_upper':1. if wins else 0.,'normalized_Q_le1_assumption_upper':0.,
                'site_cap_geometry_upper':0.,'frozen_grid_factor':0.,'frozen_checked_factor':0.,
                'frozen_grid_mass_seconds':0.,'frozen_checked_mass_seconds':0.,'geometry_upper_mass_seconds':0.,
                'latest_upper_start_utc':None,'latest_grid_start_utc':None,'latest_checked_start_utc':None,
                'max_duration_start_utc':None,'max_duration_seconds':0,
                'checked_max_start_utc':None,'checked_max_duration_seconds':0}
        latest_upper=latest_grid=latest_checked=None
        candidates=[]
        for a,b in wins:
            duration=min(self.tmax,b-a)
            result['normalized_Q_le1_assumption_upper']=max(result['normalized_Q_le1_assumption_upper'],min(1.,factor_coeff*duration))
            upper_starts=np.unique(np.r_[a,b-self.tmin,np.clip(nodes,a,b-self.tmin),np.clip(nodes-self.tmax,a,b-self.tmin),np.clip(b-self.tmax,a,b-self.tmin)])
            upper_duration=np.minimum(self.tmax,b-upper_starts)
            ub=np.interp(upper_starts+upper_duration,nodes,upper[:,index])-np.interp(upper_starts,nodes,upper[:,index])
            result['site_cap_geometry_upper']=max(result['site_cap_geometry_upper'],float(min(1.,factor_coeff*site_scale_cap*max(ub))))
            result['geometry_upper_mass_seconds']=max(result['geometry_upper_mass_seconds'],float(max(ub)))
            upper_ok=np.flatnonzero(ub>=upper_need)
            if len(upper_ok):
                j=int(upper_ok[-1]);last=upper_starts[j]
                if j+1<len(upper_starts) and ub[j]>ub[j+1]:
                    last+=float((ub[j]-upper_need)/(ub[j]-ub[j+1])*(upper_starts[j+1]-upper_starts[j]))
                latest_upper=max(latest_upper or a,math.floor(last+1e-8))
            # Checked predictions use integer-second feasible starts and ends.
            ia,ib=math.ceil(a),math.floor(b)
            if ib-ia<self.tmin:continue
            starts=np.unique(np.r_[ia,ib-self.tmin,np.clip(nodes,ia,ib-self.tmin),np.clip(nodes-self.tmax,ia,ib-self.tmin),np.clip(ib-self.tmax,ia,ib-self.tmin)])
            durations=np.minimum(self.tmax,ib-starts)
            good=(self._alt(starts,[index])[:,0]>=self.minimum_altitude)&(self._alt(starts+durations,[index])[:,0]>=self.minimum_altitude)
            starts,durations=starts[good],durations[good]
            if not len(starts):continue
            predicted=np.interp(starts+durations,nodes,prefix[:,index])-np.interp(starts,nodes,prefix[:,index])
            best=int(np.argmax(predicted))
            raw=factor_coeff*predicted*site_scale/duration_safety
            result['frozen_grid_mass_seconds']=max(result['frozen_grid_mass_seconds'],float(max(predicted)))
            if raw[best]>result['frozen_grid_factor']:
                result['frozen_grid_factor']=float(min(1.,raw[best]));result['max_duration_start_utc']=stamp(starts[best]);result['max_duration_seconds']=int(durations[best])
            feasible=np.flatnonzero(predicted>=threshold_mass)
            if len(feasible):latest_grid=max(latest_grid or a,starts[feasible[-1]])
            if exact_refine:
                peaks=starts[np.argsort(predicted)[-min(3,len(starts)):]]
                seeds=list(peaks)
                if len(feasible):seeds.append(starts[feasible[-1]])
                refined=np.unique(np.concatenate([starts]+[np.arange(max(ia,s-self.grid_seconds),min(ib-self.tmin,s+self.grid_seconds)+1,5) for s in seeds]))
                refined=np.unique(np.floor(refined)).astype(float)
                refined=refined[(refined>=ia)&(refined<=ib-self.tmin)]
                checked_duration=np.minimum(self.tmax,ib-refined)
                good=(self._alt(refined,[index])[:,0]>=self.minimum_altitude)&(self._alt(refined+checked_duration,[index])[:,0]>=self.minimum_altitude)
                refined,checked_duration=refined[good],checked_duration[good]
                integral=self.exact_integrals(index,night,refined,checked_duration)
                checked=factor_coeff*integral*site_scale/duration_safety
                result['frozen_checked_mass_seconds']=max(result['frozen_checked_mass_seconds'],float(max(integral)))
                checked_best=int(np.argmax(checked))
                if float(min(1.,checked[checked_best]))>result['frozen_checked_factor']:
                    result['frozen_checked_factor']=float(min(1.,checked[checked_best]))
                    result['checked_max_start_utc']=stamp(refined[checked_best])
                    result['checked_max_duration_seconds']=int(checked_duration[checked_best])
                exact_ok=np.flatnonzero(checked>=self.threshold)
                if len(exact_ok):
                    last=refined[exact_ok[-1]]
                    tail=np.arange(last,min(ib-self.tmin,last+5)+1)
                    vals=factor_coeff*self.exact_integrals(index,night,tail,np.minimum(self.tmax,ib-tail))*site_scale/duration_safety
                    good=tail[vals>=self.threshold]
                    latest_checked=max(latest_checked or a,float(max(good)))
        result['latest_upper_start_utc']=stamp(latest_upper) if latest_upper is not None else None
        result['latest_grid_start_utc']=stamp(latest_grid) if latest_grid is not None else None
        result['latest_checked_start_utc']=stamp(latest_checked) if latest_checked is not None else None
        result['frozen_grid_feasible']=result['frozen_grid_factor']>=self.threshold
        result['frozen_checked_feasible']=result['frozen_checked_factor']>=self.threshold if exact_refine else None
        return result

    def seasonal_profiles(self,indices=None,**kwargs):
        indices=range(len(self.ids)) if indices is None else indices
        return [self.profile(i,n,**kwargs) for i in indices for n in range(len(self.nights))]
