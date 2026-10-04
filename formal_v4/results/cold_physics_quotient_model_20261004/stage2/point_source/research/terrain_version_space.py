"""Public coarse terrain notices + positive feedback, without weather truth.

Continuous parameter boxes provide conservative *conditional-domain* exclusion.
The expected-clear map is a midpoint quadrature prediction, not a certificate.
Zero feedback is deliberately not used as hard terrain evidence.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
import numpy as np

DEG = math.pi / 180.0
SPEED = 360.98564736629 / 86400.0
DIRECTIONS = dict(zip(('N','NE','E','SE','S','SW','W','NW'), range(0,360,45)))


def _seconds(value):
    if isinstance(value, (float,int,np.number)):
        return float(value)
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value).replace('Z','+00:00'))
    return value.astimezone(timezone.utc).timestamp()


def _wrap(value):
    return (value + 180.) % 360. - 180.


def altaz_at(times, ra, dec, latitude, longitude):
    """Official public geometry, broadcasting all arguments together."""
    times,ra,dec=np.asarray(times),np.asarray(ra),np.asarray(dec)
    lst=(280.46061837+360.98564736629*(times/86400+2440587.5-2451545)+longitude)%360
    hour=_wrap(lst-ra)*DEG
    sd,cd=np.sin(dec*DEG),np.cos(dec*DEG)
    sp,cp=math.sin(latitude*DEG),math.cos(latitude*DEG)
    sine=sp*sd+cp*cd*np.cos(hour)
    alt=np.arcsin(np.clip(sine,-1,1))
    az=np.arctan2(-np.sin(hour)*cd,sd*cp-cd*sp*np.cos(hour))/DEG%360
    return alt/DEG,az


def trajectory_envelope(ra,dec,start,duration,latitude,longitude,piece_seconds=60):
    """Conservative continuous-track bounds, including hidden integration cuts.

    |az'| <= sidereal_speed/cos(max_alt) follows from the horizon-coordinate
    metric ds^2=dalt^2+cos(alt)^2*daz^2 and sky speed <= sidereal_speed.
    Culminations give each piece's exact altitude maximum. At a zenith passage
    azimuth is unbounded; a 180-degree radius disables azimuth exclusions.
    """
    start=_seconds(start);duration=float(duration)
    if duration<=0: raise ValueError('positive exposure duration required')
    edges=np.r_[np.arange(start,start+duration,piece_seconds),start+duration]
    left,right=edges[:-1],edges[1:]
    mid=(left+right)/2
    al,_=altaz_at(left,ra,dec,latitude,longitude)
    ar,_=altaz_at(right,ra,dec,latitude,longitude)
    _,az=altaz_at(mid,ra,dec,latitude,longitude)
    lst_left=(280.46061837+360.98564736629*(left/86400+2440587.5-2451545)+longitude)%360
    hleft=lst_left-ra
    until_culmination=(-hleft)%360
    crosses=until_culmination <= (right-left)*SPEED+1e-7
    peak=np.where(crosses,np.maximum(np.maximum(al,ar),90-abs(latitude-dec)),np.maximum(al,ar))
    until_lower=(180-hleft)%360
    crosses_lower=until_lower <= (right-left)*SPEED+1e-7
    lower=np.degrees(np.arcsin(np.clip(math.sin(latitude*DEG)*math.sin(dec*DEG)-
                    math.cos(latitude*DEG)*math.cos(dec*DEG),-1,1)))
    floor=np.where(crosses_lower,np.minimum(np.minimum(al,ar),lower),np.minimum(al,ar))-1e-7
    # Numerical guard is in degrees, much larger than floating point rounding.
    peak=np.minimum(90.,peak+1e-7)
    extreme=np.maximum(np.abs(peak),np.abs(floor))
    radius=np.minimum(180.,SPEED*(right-left)/2/np.maximum(np.cos(extreme*DEG),1e-12)+1e-7)
    return {'az_samples':az,'az_radii':radius,'alt_max':float(max(peak)),
            'alt_min':float(min(floor)),
            'start_seconds':start,'duration_seconds':duration}


class TerrainVersionSpace:
    """Families of possible sectors, one family per deduplicated compass notice.

    Notice D constrains the centre to D+-22.5 degrees. Multiple real sectors may
    share D: individual-positive exclusions and possible-clear certificates
    remain valid; independent one-sector expected probabilities are a model.

    Universal domains are the default. ``reference_prior`` explicitly chooses
    the published example generator's width/height domain for prediction.
    """
    def __init__(self,directions,latitude,longitude,*,width_range=(0.,360.),
                 altitude_range=(0.,90.),center_bins=9,width_bins=12,height_bins=9):
        self.latitude=float(latitude);self.longitude=float(longitude)
        self.width_range=tuple(map(float,width_range));self.altitude_range=tuple(map(float,altitude_range))
        self.directions=tuple(dict.fromkeys(d for d in directions if d in DIRECTIONS))
        ce=np.linspace(-22.5,22.5,center_bins+1)
        we=np.linspace(*self.width_range,width_bins+1)
        he=np.linspace(*self.altitude_range,height_bins+1)
        ci,wi,hi=np.meshgrid(np.arange(center_bins),np.arange(width_bins),np.arange(height_bins),indexing='ij')
        ci,wi,hi=ci.ravel(),wi.ravel(),hi.ravel()
        self.c_lo,self.c_hi=ce[ci],ce[ci+1]
        self.w_lo,self.w_hi=we[wi],we[wi+1]
        self.h_lo,self.h_hi=he[hi],he[hi+1]
        self.volume=(self.c_hi-self.c_lo)*(self.w_hi-self.w_lo)*(self.h_hi-self.h_lo)
        self.active={d:np.ones(len(ci),bool) for d in self.directions}
        self.positive_count=0;self.zero_ignored_count=0;self.domain_conflicts=[]
        self._map=None

    @classmethod
    def reference_prior(cls,directions,latitude,longitude,**kwargs):
        return cls(directions,latitude,longitude,width_range=(30.,70.),
                   altitude_range=(35.,50.),height_bins=5,**kwargs)

    def add_directions(self,directions):
        """Add newly published families without erasing previous exclusions."""
        added=tuple(dict.fromkeys(d for d in directions if d in DIRECTIONS and d not in self.active))
        for d in added:self.active[d]=np.ones(len(self.c_lo),bool)
        if added:
            self.directions+=added
            self._map=None
        return added

    def observe_positive(self,ra,dec,start,duration,score=1.):
        """Eliminate only boxes universally covering the whole continuous track."""
        if float(score)<=0:
            self.zero_ignored_count+=1
            return 0
        track=trajectory_envelope(float(ra),float(dec),start,duration,self.latitude,self.longitude)
        # Terrain min_altitude=0; a hypothetical positive below the horizon must
        # not eliminate sectors that do not cover its complete trajectory.
        if track['alt_min'] < 0:
            self.positive_count+=1
            return 0
        removed=0
        center_mid=(self.c_lo+self.c_hi)/2
        center_radius=(self.c_hi-self.c_lo)/2
        for direction,active in self.active.items():
            mask=active & (self.h_lo>=track['alt_max'])
            if not np.any(mask):continue
            idx=np.flatnonzero(mask)
            # The triangle inequality on the circle over-encloses every real az.
            distance=np.abs(_wrap(track['az_samples'][:,None]-(DIRECTIONS[direction]+center_mid[idx])[None,:]))
            worst=np.max(distance+track['az_radii'][:,None]+center_radius[idx][None,:],axis=0)
            impossible=idx[worst<=self.w_lo[idx]/2-1e-7]
            if len(impossible):
                active[impossible]=False;removed+=len(impossible)
                if not np.any(active) and direction not in self.domain_conflicts:
                    self.domain_conflicts.append(direction)
        self.positive_count+=1
        if removed:self._map=None
        return removed

    def observe_zero(self,*args,**kwargs):
        """No hard inference: weather/fault/other events also produce zero."""
        self.zero_ignored_count+=1

    def _build_map(self):
        # Midpoint quadrature over continuous boxes; unit grid of horizon angles.
        clear=np.ones((91,360))
        for direction,active in self.active.items():
            if not np.any(active):continue # inconsistent conditional domain: fail open
            cm=(DIRECTIONS[direction]+(self.c_lo[active]+self.c_hi[active])/2)%360
            wm=(self.w_lo[active]+self.w_hi[active])/2
            hm=(self.h_lo[active]+self.h_hi[active])/2
            weights=self.volume[active]/self.volume[active].sum()
            # Horizontal sector coverage at each grid azimuth, then height CDF.
            covered=np.abs(_wrap(np.arange(360)[None,:]-cm[:,None]))<=wm[:,None]/2
            blocked=np.zeros_like(clear)
            for h in range(91):
                keep=hm>=h
                if np.any(keep):blocked[h]=np.sum(weights[keep,None]*covered[keep],axis=0)
            clear*=1-np.clip(blocked,0,1)
        self._map=clear

    def expected_clear_fraction(self,alt,az):
        """One-sector-per-notice, independent numerical prediction in [0,1]."""
        if self._map is None:self._build_map()
        alt,az=np.broadcast_arrays(np.asarray(alt,dtype=float),np.asarray(az,dtype=float))
        a=np.clip(alt,0,90);z=az%360
        i=np.minimum(a.astype(int),89);j=z.astype(int)
        da,dz=a-i,z-j
        result=((1-da)*((1-dz)*self._map[i,j]+dz*self._map[i,(j+1)%360])+
                da*((1-dz)*self._map[i+1,j]+dz*self._map[i+1,(j+1)%360]))
        return np.where(alt<0,1.,result)

    terrain_scale=expected_clear_fraction

    def certified_clear(self,alt,az):
        """True iff no remaining box can cover the point, conditional on domain.

        Supports arbitrarily many sectors sharing a published direction. False
        means unknown, not certified blocked. No numerical posterior is used.
        """
        alt,az=np.broadcast_arrays(np.asarray(alt,dtype=float),np.asarray(az,dtype=float))
        shape=alt.shape;a,z=alt.ravel(),az.ravel();result=np.ones(len(a),bool)
        if self.domain_conflicts:return np.zeros(shape,bool)
        for direction,active in self.active.items():
            cm=DIRECTIONS[direction]+(self.c_lo[active]+self.c_hi[active])/2
            cr=(self.c_hi[active]-self.c_lo[active])/2
            wm=self.w_hi[active]/2;hm=self.h_hi[active]
            for left in range(0,len(a),512):
                sl=slice(left,left+512)
                possible=(np.abs(_wrap(z[sl,None]-cm[None,:]))<=wm[None,:]+cr[None,:]+1e-7)&(a[sl,None]<=hm[None,:]+1e-7)&(a[sl,None]>=-1e-7)
                result[sl]&=~np.any(possible,axis=1)
        return result.reshape(shape)

    def quality_model(self,times,ra,dec):
        """Future geometry -> raw-factor terrain scale, never program-band scale."""
        times=np.asarray([_seconds(t) for t in np.atleast_1d(times)])
        alt,az=altaz_at(times[:,None],np.asarray(ra)[None,:],np.asarray(dec)[None,:],self.latitude,self.longitude)
        return self.expected_clear_fraction(alt,az)

    def snapshot(self):
        return {'schema':'terrain-positive-version-space-v1','directions':list(self.directions),
                'width_range':self.width_range,'altitude_range':self.altitude_range,
                'boxes_per_family':len(self.c_lo),'remaining_boxes':{d:int(a.sum()) for d,a in self.active.items()},
                'positive_count':self.positive_count,'zero_feedback_ignored':self.zero_ignored_count,
                'conditional_domain_conflicts':list(self.domain_conflicts),
                'prediction_assumption':'independent one sector per deduplicated direction; midpoint quadrature'}
