"""Time support of published directional evidence for a request window.

Geometry is public. Terrain prediction is conditional on its supplied posterior.
Bulletins/forecasts provide no numeric weather amplitude: a weather callback is
an explicit conditional scenario, not future truth. Program-band quality is
deliberately separate; this module only returns a raw-factor directional scale.
"""
from __future__ import annotations

import copy
from datetime import timedelta

import numpy as np

from .spatial_candidates import parse_utc,_wrap180
from .terrain_version_space import altaz_at


class PublishedFutureField:
    """Frozen public evidence, evaluated at future horizon coordinates.

    ``terrain_model.expected_clear_fraction(alt,az)`` is copied at construction.
    ``weather_scenario(notices,moment,alt,az)`` optionally maps qualitative
    current/forecast evidence to a numeric conditional scale. With no callback,
    weather amplitude remains the caller's frozen global C/E estimate: forecast
    support is available via notices_at(), without inventing a probability.
    """

    def __init__(self,planner,snapshot,terrain_model,*,weather_scenario=None,
                 empirical_blocks=(),empirical_ttl_seconds=1200):
        self.planner=planner
        self.now=parse_utc(snapshot['now_utc'])
        self.terrain=copy.deepcopy(terrain_model)
        self.weather_scenario=weather_scenario
        self.blocks=tuple((parse_utc(t),float(a),float(z)) for t,a,z in empirical_blocks)
        self.ttl=float(empirical_ttl_seconds)
        self.nights=[(parse_utc(n['observing_start_utc']),parse_utc(n['observing_end_utc']),n['night_date'])
                     for n in planner.init['survey']['nights']]
        self.bulletin=copy.deepcopy(snapshot.get('latest_bulletin') or {})
        self.forecast=copy.deepcopy(snapshot.get('latest_forecast') or {})
        self.slot_end=None
        if self.bulletin.get('issued_at_utc'):
            issued=parse_utc(self.bulletin['issued_at_utc'])
            if issued>self.now:raise ValueError('unpublished bulletin')
            slot_seconds=int(planner.init['survey'].get('slot_seconds',900))
            self.slot_end=issued+timedelta(seconds=slot_seconds)
        if self.forecast.get('issued_at_utc') and parse_utc(self.forecast['issued_at_utc'])>self.now:
            raise ValueError('unpublished forecast')

    def night_date_at(self,moment):
        moment=parse_utc(moment)
        return next((date for a,b,date in self.nights if a<=moment<b),None)

    def notices_at(self,moment):
        """Current slot evidence replaces, rather than duplicates, forecast."""
        moment=parse_utc(moment)
        if moment<self.now:raise ValueError('future field queried before freeze')
        if self.slot_end is not None and moment<self.slot_end:
            notices=self.bulletin.get('notices',[])
            source='current_slot'
        else:
            notices=[];source='baseline'
            a,b=self.forecast.get('coverage_start_utc'),self.forecast.get('coverage_end_utc')
            date=self.night_date_at(moment)
            if a and b and parse_utc(a)<=moment<parse_utc(b):
                notices=[n for n in self.forecast.get('notices',[]) if date in n.get('nights',[])]
                source='published_forecast'
        result=[];seen=set()
        for notice in notices:
            key=notice.get('event_kind'),notice.get('direction')
            if key[0]=='terrain_obstruction' or key in seen:continue
            seen.add(key);result.append(copy.deepcopy(notice))
        return source,tuple(result)

    def raw_scale_at(self,moment,idx=None):
        """Dimensionless conditional raw scale; no program multiplier or C/E."""
        moment=parse_utc(moment)
        if idx is None:idx=np.arange(self.planner.n)
        idx=np.asarray(idx,dtype=int)
        alt,az=altaz_at(moment.timestamp(),self.planner.ra[idx],self.planner.dec[idx],self.planner.lat,self.planner.lon)
        scale=np.asarray(self.terrain.expected_clear_fraction(alt,az),dtype=float)
        _,notices=self.notices_at(moment)
        if self.weather_scenario is not None:
            scale*=np.asarray(self.weather_scenario(notices,moment,alt,az),dtype=float)
        for issued,_,direction in self.blocks:
            if 0<=(moment-issued).total_seconds()<self.ttl:
                scale*=np.where(np.abs(_wrap180(az-direction))<10,.5,1.)
        if not np.all(np.isfinite(scale)):raise ValueError('nonfinite future field scale')
        return np.clip(scale,0.,1.)

    def summary(self):
        return {'frozen_at_utc':self.now.isoformat(),'current_slot_end_utc':self.slot_end.isoformat() if self.slot_end else None,
                'weather_amplitude_model':type(self.weather_scenario).__name__ if self.weather_scenario else 'frozen global C/E only',
                'empirical_ttl_seconds':self.ttl,'terrain_posterior':self.terrain.snapshot()}
