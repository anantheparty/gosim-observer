"""Independent finite past-output prior and batch column pricing; no agent hook.

Only compact measured interval cells are loaded. No interpolation, NNLS curve,
hidden product, random seed or fitted E/W decomposition is used. These are
validated predictive priors, not unconditional future weather certificates.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from required_opportunity_model import RequiredOpportunityModel, parse
from quality_profile_inversion import all_target_model, load_messages, sha256

PUBLIC_FILES=('config/v4_scenario.json','config/v4_fiber_config.json','config/v4_score_config.json',
              'public/targets.csv','public/footprint.csv','public/v4_night_calendar.csv')
TARGET_COLUMNS=('target_id','ra_deg','dec_deg','target_class','feature_flux','science_weight','required')
NUMERIC_TARGETS=('ra_deg','dec_deg','feature_flux','science_weight')


def _canonical_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def public_projection(initial):
    """Exactly the common public information visible in initialize and six files.

    The raw six-file SHA digest cannot be recovered from initialize (dusk/dawn,
    scenario product paths etc are omitted). Never claim that semantic identity
    verifies hidden products or the entire raw source bundle.
    """
    site=initial['site'];survey=initial['survey'];inst=initial['instrument']
    columns={k:i for i,k in enumerate(initial['targets']['columns'])}
    rows=[]
    for row in initial['targets']['rows']:
        item={k:row[columns[k]] for k in TARGET_COLUMNS}
        for k in NUMERIC_TARGETS:item[k]=float(item[k])
        item['required']=str(item['required']).strip().lower() in ('true','1')
        rows.append([item[k] for k in TARGET_COLUMNS])
    return {'site':{**{k:float(site[k]) for k in ('latitude_deg','longitude_deg','utc_offset_hours','minimum_altitude_deg')},
                    'sun_altitude_limit_deg':float(site.get('sun_altitude_limit_deg',-18.))},
            'survey':{'start_utc':survey['start_utc'],'end_utc':survey['end_utc'],'slot_seconds':int(survey['slot_seconds']),
                      'nights':[{k:(int(n[k]) if k=='slot_count' else n[k]) for k in
                                 ('night_id','night_date','observing_start_utc','observing_end_utc','slot_count')}
                                for n in survey['nights']]},
            'instrument':{'n_fibers':int(inst['n_fibers']),'fiber_area_deg2':float(inst['fiber_area_deg2']),
                          'gap_deg':float(inst['gap_deg']),'exposure':{k:int(inst['exposure'][k]) for k in
                             ('min_duration_seconds','max_duration_seconds')}},
            'scoring':initial['scoring'],
            'footprint':[{'component_id':c['component_id'],'vertices':[[float(x),float(y)] for x,y in c['vertices']]}
                         for c in sorted(initial['footprint'],key=lambda c:c['component_id'])],
            'targets':{'columns':list(TARGET_COLUMNS),'rows':rows}}


def public_protocol_initial(card):
    """Reconstruct only initialize's public fields without instantiating engine."""
    card=Path(card)
    scenario=json.loads((card/'config/v4_scenario.json').read_text())
    fiber=json.loads((card/'config/v4_fiber_config.json').read_text())
    score=json.loads((card/'config/v4_score_config.json').read_text())
    targets=list(csv.DictReader((card/'public/targets.csv').open()))
    nights=list(csv.DictReader((card/'public/v4_night_calendar.csv').open()))
    footprint={}
    for row in sorted(csv.DictReader((card/'public/footprint.csv').open()),key=lambda r:(r['component_id'],int(r['vertex_index']))):
        footprint.setdefault(row['component_id'],[]).append([float(row['ra_deg']),float(row['dec_deg'])])
    slot=int(round((parse(nights[0]['observing_end_utc'])-parse(nights[0]['observing_start_utc'])).total_seconds()/int(nights[0]['slot_count'])))
    return {'task_card':scenario.get('task_card',{}),'site':{**scenario['site'],'minimum_altitude_deg':scenario['minimum_altitude_deg']},
        'survey':{'start_utc':nights[0]['observing_start_utc'],'end_utc':nights[-1]['observing_end_utc'],
                  'slot_seconds':slot,'nights':nights},
        'instrument':{**fiber['field'],'exposure':fiber['exposure']},'scoring':score,
        'footprint':[{'component_id':c,'vertices':v} for c,v in footprint.items()],
        'targets':{'columns':list(TARGET_COLUMNS),'rows':[[r[c] for c in TARGET_COLUMNS] for r in targets]}}


def build_registry(destination,formal_root=None):
    """Create four small prior NPZ files with public/output provenance only."""
    root=Path(formal_root or Path(__file__).resolve().parents[1]);destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    registry={'schema':'past-output-finite-profile-registry-v1','cards':[],
              'scope':'six-file provenance plus initialize-visible semantic identity; predictive interval prior only'}
    for card_id in ('alpha','beta','gamma','delta'):
        card=root/'practice_cards'/card_id/card_id
        source=root/'research'/f'quality_profile_{card_id}_result.npz'
        summary=json.loads(source.with_suffix('.json').read_text())
        old=np.load(source)
        file_hash={name:sha256(card/name) for name in PUBLIC_FILES}
        initial=public_protocol_initial(card)
        item={'card_id':card_id,'public_projection_digest':_canonical_digest(public_projection(initial)),
              'public_six_file_sha256':file_hash,'public_six_file_digest':_canonical_digest(file_hash),
              'old_repairs_utc':summary['repair_timestamps_utc'],'source_profile_sha256':sha256(source),
              'source_output_input_sha256':summary['input_sha256'],'profile_file':f'{card_id}.npz',
              'max_width':1e-4,'reference_clean_domain':summary['geometry_reference_bounds'],
              'validated_cross_run_result_sha256':sha256(root/'research'/f'quality_profile_{card_id}_cross_run_result.json')}
        np.savez_compressed(destination/item['profile_file'],**{k:old[k] for k in
                            ('cell_start','cell_end','lower','upper','support')})
        item['profile_sha256']=sha256(destination/item['profile_file'])
        registry['cards'].append(item)
    (destination/'registry.json').write_text(json.dumps(registry,indent=2)+'\n')
    return registry


class ProfileRegistry:
    def __init__(self,path):
        self.path=Path(path);self.root=self.path.parent
        self.registry=json.loads(self.path.read_text())

    def identify(self,initial):
        digest=_canonical_digest(public_projection(initial))
        matches=[c for c in self.registry['cards'] if c['public_projection_digest']==digest]
        if len(matches)!=1:return None
        card=matches[0]
        if sha256(self.root/card['profile_file'])!=card['profile_sha256']:
            raise ValueError('profile artifact SHA mismatch')
        return FiniteQualityPrior(initial,card,self.root/card['profile_file'])


def _all_model(initial):
    copy={**initial,'targets':{**initial['targets'],'rows':[list(r) for r in initial['targets']['rows']]}}
    required=copy['targets']['columns'].index('required')
    for row in copy['targets']['rows']:row[required]=True
    return RequiredOpportunityModel(copy)


def _paired_public_quality(model,times,indices):
    """Diagonal [time, target-per-column] official H/q0; never a K×KF matrix."""
    times=np.asarray(times);idx=np.asarray(indices,int)
    days=times/86400+2440587.5-2451545
    deg=math.pi/180
    sl=(280.460+.9856474*days)%360
    anomaly=((357.528+.9856003*days)%360)*deg
    slon=(sl+1.915*np.sin(anomaly)+.020*np.sin(2*anomaly))*deg
    ob=(23.439-.0000004*days)*deg
    sun=np.stack((np.cos(slon),np.sin(slon)*np.cos(ob),np.sin(slon)*np.sin(ob)),axis=1)
    lon=((218.316+13.176396*days)%360)*deg+6.289*deg*np.sin(((134.963+13.064993*days)%360)*deg)
    lat=5.128*deg*np.sin(((93.272+13.229350*days)%360)*deg)
    moon=np.stack((np.cos(lon)*np.cos(lat),np.sin(lon)*np.cos(lat)*np.cos(ob)-np.sin(lat)*np.sin(ob),
                   np.sin(lon)*np.cos(lat)*np.sin(ob)+np.sin(lat)*np.cos(ob)),axis=1)
    illum=(1-np.sum(sun*moon,axis=1))/2
    mdec=np.arcsin(np.clip(moon[:,2],-1,1));mra=np.arctan2(moon[:,1],moon[:,0])/deg%360
    lst=model._lst(times)
    malt=np.arcsin(np.clip(model.sinlat*np.sin(mdec)+model.coslat*np.cos(mdec)*np.cos(((lst-mra+180)%360-180)*deg),-1,1))
    ra=model.ra[idx]*deg;sd=model.sin_dec[idx];cd=model.cos_dec[idx]
    cosine=moon[:,0,None]*cd*np.cos(ra)+moon[:,1,None]*cd*np.sin(ra)+moon[:,2,None]*sd
    sep=np.arccos(np.clip(cosine,-1,1))/deg
    lunar=1-float(model.lunar['maximum_penalty'])*illum[:,None]*np.maximum(0,np.sin(malt))[:,None]**float(model.lunar['altitude_exponent'])*np.exp(-sep/float(model.lunar['angular_decay_scale_deg']))
    lunar[malt<=0]=1
    hour=((lst[:,None]-model.ra[idx]+180)%360-180)*deg
    alt=np.arcsin(np.clip(model.sinlat*sd+model.coslat*cd*np.cos(hour),-1,1))/deg
    return np.clip(lunar,0,1)*model._air_quality(alt)


class FiniteQualityPrior:
    def __init__(self,initial,card,path):
        self.card=card;self.model=_all_model(initial)
        with np.load(path) as a:
            self.starts=a['cell_start'].copy();self.ends=a['cell_end'].copy()
            self.lower=a['lower'].copy();self.upper=a['upper'].copy();self.support=a['support'].copy()
        self.old_repairs=np.array([parse(t).timestamp() for t in card['old_repairs_utc']])
        self.current_repairs=[];self.disabled_cells=set();self.feedback_records=[]
        self.live_compatible=False
        columns={k:i for i,k in enumerate(self.model.initial['targets']['columns'])}
        self.weights=np.array([float(r[columns['science_weight']]) for r in self.model.initial['targets']['rows']])
        self.night_start=np.array([a for a,b in self.model.nights]);self.night_end=np.array([b for a,b in self.model.nights])

    def note_report(self,moment,correct):
        if correct:
            time=float(moment) if isinstance(moment,(int,float,np.number)) else parse(moment).timestamp()
            if time not in self.current_repairs:self.current_repairs.append(time);self.current_repairs.sort()
            self.live_compatible=False

    def lookup(self,times,*,now,allow_historical=False,require_live_compatibility=True):
        """Finite cells and confirmed repair epoch match. No future repair assumed."""
        times=np.asarray(times,float);now=float(now)
        cell=np.searchsorted(self.starts,times,side='right')-1
        safe=np.clip(cell,0,len(self.starts)-1)
        valid=(cell>=0)&(times<self.ends[safe])&(self.support[safe]>0)&(self.upper[safe]>=self.lower[safe])
        valid&=(self.upper[safe]-self.lower[safe]<=float(self.card['max_width']))
        current=np.asarray(self.current_repairs)
        if allow_historical:
            current_count=np.searchsorted(current,times,side='right')
        else:
            # Pricing the future knows only reports already confirmed at now.
            current_count=np.searchsorted(current,np.minimum(times,now),side='right')
        old_count=np.searchsorted(self.old_repairs,times,side='right')
        valid&=old_count==current_count
        if require_live_compatibility:valid&=self.live_compatible
        if self.disabled_cells:valid&=~np.isin(safe,np.fromiter(self.disabled_cells,int))
        low=np.where(valid,self.lower[safe],np.nan);high=np.where(valid,self.upper[safe],np.nan)
        return {'cell':cell,'supported':valid,'lower':low,'upper':high,'midpoint':(low+high)/2,
                'scope':'finite predictive interval prior with matched confirmed repair epoch'}

    def price_columns(self,starts,durations,target_indices,*,now,direction_scale=None,fallback_Z=None,
                      program=None,require_live_compatibility=True):
        """CPU batch API. Arrays: starts/durations[K], indices[K,F], F usually 16.

        Returns raw quality/factor intervals for wholly supported columns, base
        science weight*factor, and generic program bounds [mismatch,max match].
        direction_scale[K,F] is an explicitly conditional model, not a proof.
        Unsupported quality is NaN; optional caller fallback supplies point only.
        """
        starts=np.asarray(starts,float);durations=np.asarray(durations,float);idx=np.asarray(target_indices,int)
        if idx.ndim==1:idx=idx[:,None]
        if starts.shape!=durations.shape or idx.shape[0]!=len(starts):raise ValueError('column shape mismatch')
        if np.any(durations<=0) or np.any(idx<0) or np.any(idx>=len(self.model.ids)):raise ValueError('invalid column')
        night=np.searchsorted(self.night_end,starts,side='right')
        if np.any(night>=len(self.night_start)):raise ValueError('outside night')
        anchor=self.night_start[night]
        if np.any(starts<anchor) or np.any(starts+durations>self.night_end[night]+1e-7):raise ValueError('column crosses daylight')
        lower=np.zeros(idx.shape);upper=np.zeros(idx.shape);point=np.zeros(idx.shape)
        supported=np.ones(len(starts),bool);cursor=starts.copy();end=starts+durations
        while np.any(cursor<end-1e-7):
            active=np.flatnonzero(cursor<end-1e-7);c=cursor[active]
            slot_end=anchor[active]+(np.floor((c-anchor[active])/self.model.slot_seconds)+1)*self.model.slot_seconds
            right=np.minimum(np.minimum(end[active],slot_end),c+120)
            if np.any(right<=c):raise ValueError('midpoint failed to advance')
            mid=(c+right)/2;lookup=self.lookup(mid,now=now,require_live_compatibility=require_live_compatibility)
            h=_paired_public_quality(self.model,mid,idx[active])*(right-c)[:,None]
            supported[active]&=lookup['supported']
            lower[active]+=h*np.nan_to_num(lookup['lower'])[:,None]
            upper[active]+=h*np.nan_to_num(lookup['upper'])[:,None]
            z=lookup['midpoint']
            if fallback_Z is not None:
                fallback=np.broadcast_to(np.asarray(fallback_Z,float),starts.shape)[active]
                z=np.where(lookup['supported'],z,fallback)
            point[active]+=h*z[:,None]
            cursor[active]=right
        scale=np.ones(idx.shape) if direction_scale is None else np.broadcast_to(direction_scale,idx.shape)
        if np.any(~np.isfinite(scale)) or np.any(scale<0) or np.any(scale>1):raise ValueError('direction scale must be in [0,1]')
        for values in (lower,upper,point):values*=scale/durations[:,None]
        lower[~supported]=np.nan;upper[~supported]=np.nan
        coefficient=self.model.flux[idx]*durations[:,None]/self.model.f0t0
        flo=np.minimum(1,coefficient*lower);fhi=np.minimum(1,coefficient*upper);fp=np.minimum(1,coefficient*point)
        weights=self.weights[idx]
        multipliers=self.model.score['program']['multipliers'];mismatch=float(self.model.score['program']['mismatch_multiplier'])
        max_mult=np.full((len(starts),1),max(mismatch,*multipliers.values()))
        min_mult=np.full((len(starts),1),min(mismatch,*multipliers.values()))
        if program is not None:
            declared=np.broadcast_to(program,starts.shape)
            matches=np.array([float(multipliers[p]) for p in declared])[:,None]
            max_mult=np.maximum(mismatch,matches);min_mult=np.minimum(mismatch,matches)
        return {'supported_column':supported,'quality_lower':lower,'quality_upper':upper,'quality_point':point,
                'factor_lower':flo,'factor_upper':fhi,'factor_point':fp,
                'base_science_lower':weights*flo,'base_science_upper':weights*fhi,
                'science_generic_lower':weights*flo*min_mult,
                'science_generic_upper':weights*fhi*max_mult,
                'identity_matches_public_projection':True,'live_feedback_compatible':self.live_compatible,
                'scope':'conditional unobstructed/scaled-direction prior; unsupported bounds NaN, no W/E decomposition'}

    def feedback_ratio(self,start,duration,target_indices,scores,weights,flux,program,*,clean_mask=None,now=None):
        """Score-only feedback tests whether source Z is compatible; never fits E.

        A target has two possible multipliers (declared-match or mismatch). For
        each non-saturated branch derive an interval for q_current/q_old. Intersect
        unions across explicitly clean targets. Saturated alternatives carry no
        useful upper bound; omitted from ratio identification. No future rescale.
        """
        idx=np.asarray(target_indices,int);scores=np.asarray(scores,float);weights=np.asarray(weights,float);flux=np.asarray(flux,float)
        mask=np.zeros(len(idx),bool) if clean_mask is None else np.asarray(clean_mask,bool)
        now=float(start+duration if now is None else now)
        priced=self.price_columns([start],[duration],idx[None,:],now=now,require_live_compatibility=False)
        if not priced['supported_column'][0]:return {'usable':False,'reason':'unsupported prior or unmatched repair epoch'}
        low,high=priced['quality_lower'][0],priced['quality_upper'][0]
        multipliers=self.model.score['program'];branches=sorted(set((float(multipliers['multipliers'][program]),float(multipliers['mismatch_multiplier']))))
        intersection=[(0.,float('inf'))];used=0;saturated_only=0
        for j in np.flatnonzero(mask & (scores>0) & (low>0)):
            intervals=[]
            for mult in branches:
                flo=max(0,(scores[j]-.500001e-6)/(weights[j]*mult));fhi=(scores[j]+.500001e-6)/(weights[j]*mult)
                if flo>1:continue
                if fhi>=1:
                    intervals.append((max(0,flo*self.model.f0t0/(flux[j]*duration)/high[j]),float('inf')))
                    continue
                qlo,qhi=self.model.f0t0/(flux[j]*duration)*flo,self.model.f0t0/(flux[j]*duration)*fhi
                intervals.append((qlo/high[j],qhi/low[j]))
            if not intervals:continue
            if all(math.isinf(b) for a,b in intervals):saturated_only+=1;continue
            used+=1
            intersection=[(max(a,c),min(b,d)) for a,b in intersection for c,d in intervals if max(a,c)<=min(b,d)]
            # Merge overlapping union components to avoid exponential duplicate
            # branches, especially when a capped branch is a half-infinite ray.
            merged=[]
            for lo,hi in sorted(intersection):
                if merged and lo<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],hi))
                else:merged.append((lo,hi))
            intersection=merged
            if not intersection:break
        result={'usable':used>0,'usable_clean_hits':used,'saturated_only_hits':saturated_only,
                'profile_ratio_intervals':[[float(a),None if math.isinf(b) else float(b)] for a,b in intersection] if used else [],
                'compatible_with_unit_ratio':any(a<=1<=b for a,b in intersection) if used else None,
                'bounded_unit_ratio_evidence':any(a<=1<=b and math.isfinite(b) for a,b in intersection) if used else False,
                'scope':'effective profile ratio only; cannot distinguish weather, E, or remaining direction error; no future rescaling'}
        if used and not result['compatible_with_unit_ratio']:
            # Conservatively invalidate touched source cells; do not modify E/W.
            self.disabled_cells.update(np.flatnonzero((self.starts<start+duration)&(self.ends>start)))
            result['fallback']='disable touched cells; use caller belief for them'
            self.live_compatible=False
        elif used and result['bounded_unit_ratio_evidence']:
            self.live_compatible=True
            result['activation']='positive clean feedback compatible; still an empirical same-realization prior'
        self.feedback_records.append(result)
        return result


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('destination');args=p.parse_args()
    r=build_registry(args.destination)
    print(json.dumps({'cards':len(r['cards']),'destination':args.destination,'bytes':sum(p.stat().st_size for p in Path(args.destination).iterdir())}))
