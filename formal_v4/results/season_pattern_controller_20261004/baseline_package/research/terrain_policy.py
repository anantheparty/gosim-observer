"""Opt-in Policy subclass sharing one online terrain state with future planners.

Importing this module does not alter the stable Policy. The install function
returns a subclass; a candidate entrypoint must explicitly instantiate it.
"""
from __future__ import annotations

import numpy as np

from .terrain_version_space import TerrainVersionSpace,altaz_at,DIRECTIONS
from .spatial_candidates import parse_utc

TEMPORARY_KINDS={'overcast','haze','cloud','cloud_cover','dust','rocket','rocket_launch'}


def temporary_weather_scale(notices,moment,alt,az):
    """Existing local qualitative-weather scenario, excluding static terrain.

    Caller controls published time support (current slot / forecast). This
    explicitly conditional amplitude model preserves the previous .55 scenario,
    rather than treating a coarse notice as a known numeric weather quantity.
    It affects raw factor only. ``alt`` is supplied for API consistency.
    """
    az=np.asarray(az,dtype=float);scale=np.ones_like(az);seen=set()
    for n in notices:
        kind,direction=n.get('event_kind'),n.get('direction')
        if (kind,direction) in seen or kind not in TEMPORARY_KINDS or direction not in DIRECTIONS:continue
        seen.add((kind,direction))
        delta=np.abs((az-DIRECTIONS[direction]+180)%360-180)
        scale*=np.where(delta<30,.55,1.)
    return scale


def install_terrain_policy(BasePolicy):
    """Return an opt-in subclass; leave BasePolicy and stable entrypoints intact."""
    class TerrainPolicy(BasePolicy):
        def __init__(self,initial):
            super().__init__(initial)
            p=self.planner
            # This range is an explicit scenario assumption, not cloud metadata.
            if self.config.get('terrain_reference_prior',True):
                self.terrain_model=TerrainVersionSpace.reference_prior([],p.lat,p.lon)
            else:
                self.terrain_model=TerrainVersionSpace([],p.lat,p.lon)
            self.terrain_seen_observe=set()
            self.terrain_feedback_exposures=0
            self.planner.terrain_model=self.terrain_model
            self.planner.terrain_empirical_blocks=self.blocked_spots

        def _ingest_result(self,snapshot):
            result=snapshot.get('last_result') or {}
            pending=self.pending
            if result.get('action')=='observe' and pending and pending.get('action',{}).get('action')=='observe':
                observe_index=result.get('observe_index')
                # Explicit engine indices provide idempotence across waits/resync.
                if observe_index is not None and int(observe_index) not in self.terrain_seen_observe:
                    start=parse_utc(pending['start']);now=parse_utc(snapshot['now_utc'])
                    duration=min(float(pending['action']['duration_seconds']),(now-start).total_seconds())
                    if duration>0:
                        p=self.planner
                        for hit in result.get('hits',[]):
                            i=p.index.get(str(hit.get('target_id')))
                            if i is None:continue
                            score=float(hit.get('score',0))
                            if score>0:
                                self.terrain_model.observe_positive(p.ra[i],p.dec[i],start,duration,score)
                            else:
                                self.terrain_model.observe_zero()
                        self.terrain_feedback_exposures+=1
                        self.terrain_seen_observe.add(int(observe_index))
            # The stable implementation clears self.pending. All physical
            # terrain evidence above was captured before that mutation.
            return super()._ingest_result(snapshot)

        def _messages(self,snapshot):
            result=super()._messages(snapshot)
            self.terrain_model.add_directions(self.terrain)
            return result

        def _target_scale(self,now):
            p=self.planner
            alt,az=altaz_at(parse_utc(now).timestamp(),p.ra,p.dec,p.lat,p.lon)
            scale=self.terrain_model.expected_clear_fraction(alt,az)
            scale*=temporary_weather_scale(self.notices,now,alt,az)
            for issued,_,z in self.blocked_spots:
                elapsed=(parse_utc(now)-parse_utc(issued)).total_seconds()
                if 0<=elapsed<1200:
                    delta=np.abs((az-z+180)%360-180)
                    scale*=np.where(delta<10,.5,1.)
            return scale

        def summary(self):
            return {**super().summary(),'terrain':self.terrain_model.snapshot(),
                    'terrain_feedback_exposures':self.terrain_feedback_exposures}

    TerrainPolicy.__name__='TerrainPolicy'
    return TerrainPolicy
