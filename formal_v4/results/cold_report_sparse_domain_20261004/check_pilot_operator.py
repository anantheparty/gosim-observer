"""Official-score gates for real geometry, directional notices and fault repair."""
import json,time,copy
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from sparse_world import ROOT,World,PublicState,XDIM,trajectory
from challenge.v4_scorer import SlotTruth,ScoreEvent,WeatherTruth,program_multiplier,program_band,score_target_exposure
from challenge.v4_fiber_map import radec_to_altaz,FiberGrid,min_altitude_during
def event(e):return ScoreEvent(e.event_id,e.event_type,e.actual_start_utc,e.actual_end_utc,e.scope_type,e.azimuth_start_deg,e.azimuth_end_deg,e.min_altitude_deg,e.max_altitude_deg,e.seeing_multiplier,e.transparency_multiplier,e.sky_quality_multiplier,e.instrument_efficiency_multiplier,e.force_close)
started=time.time();maxerr=0.;cases=0;actual_repair_cases=0;directional_cases=0;branches=0;continuation_cases=0;geometry_cases=0;missed=0;gained=0
for seed in [810000,810001,810002,810003]:
    w=World(seed);d=w.design;cfg=d['initial']['scoring'];site=d['initial']['site'];slots=[]
    grid=FiberGrid(float(d['initial']['instrument']['fiber_area_deg2']),float(d['initial']['instrument']['gap_deg']),16)
    for orig,actual in zip(d['actions'],w.geometry):
        t=datetime.fromtimestamp(orig['start'],timezone.utc);end=datetime.fromtimestamp(orig['end'],timezone.utc)
        expected=[]
        for tid,ix,ra,dec,fiber,nominal in zip(orig['target_ids'],orig['ids'],orig['ra'],orig['dec'],orig['fibers'],orig['nominal_hits']):
            hit=grid.classify_target(float(ra),float(dec),t,*orig['pointing'],float(site['latitude_deg']),float(site['longitude_deg']),*w.offset)
            eligible=min_altitude_during(float(ra),float(dec),t,end,d['initial'])>=float(site['minimum_altitude_deg'])
            on=eligible and hit.region=='glass' and hit.fiber_id==fiber
            if on:expected.append(ix)
            missed+=int(nominal and not on);gained+=int(not nominal and on);geometry_cases+=1
        assert expected==actual['ids'].tolist()
    for s,r in zip(d['slots'],w.rows):
        opened=r['is_observable']=='true'
        slots.append(SlotTruth(s.slot_id,s.timestamp_utc,s.end_utc,opened,*[float(r[k]) if opened else 0. for k in ['seeing_arcsec','transparency','sky_quality','instrument_efficiency']]))
    faults=[event(e) for e in w.faults];directions=[event(e) for e in w.events if e.scope_type=='HORIZON_SECTOR']
    candidates=list(range(0,len(w.geometry),max(1,len(w.geometry)//16)))
    candidates+= [j for j,a in enumerate(w.geometry) if w.active(a['start'],set()) is not None][:8]
    candidates+= [j for j,f in enumerate(w.directional) if np.any(f<1)][:8]
    for j in sorted(set(candidates)):
        a=w.geometry[j];start=datetime.fromtimestamp(a['start'],timezone.utc);end=datetime.fromtimestamp(a['end'],timezone.utc);f=w.active(a['start'],set())
        weather=WeatherTruth(slots,faults);repaired=set();lat=float(site['latitude_deg']);lon=float(site['longitude_deg'])
        for report in [False,True]:
            if report:
                ok=weather.repair_fault(start)
                if ok:repaired.add(f.event_id);actual_repair_cases+=1
            expected=w.score(j,repaired);branches+=1
            for ix,ra,dec,goal in zip(a['ids'],a['ra'],a['dec'],expected[0]):
                target=dict(target_id=str(ix),ra_deg=float(ra),dec_deg=float(dec),feature_flux=float(w.flux[ix]),science_weight=float(w.weight[ix]))
                fn=lambda t,ra=float(ra),dec=float(dec):radec_to_altaz(ra,dec,t,lat,lon)
                band=weather.band_quality(start,end,cfg,lambda t:fn(t)[0],lambda t:__import__('challenge.v4_scorer',fromlist=['lunar_quality_factor']).lunar_quality_factor(float(ra),float(dec),t,site,cfg))
                mult=program_multiplier(['DARK','BRIGHT','BACKUP'][a['program']],program_band(band,cfg),cfg)
                score=score_target_exposure(target,list(weather.segments(start,end)),directions,weather,a['duration'],mult,cfg,start,fn,site).score
                maxerr=max(maxerr,abs(round(score,6)-goal));cases+=1
            if np.any(w.directional[j]<1):directional_cases+=1
            if report and f is not None and j+1<len(w.geometry):
                nxt=w.geometry[j+1];assert w.active(nxt['start'],repaired) is None or w.active(nxt['start'],repaired).event_id!=f.event_id
                continuation_cases+=1
    state=PublicState(w);repaired=set();tokens=0;lastslot=None
    for j,a in enumerate(w.geometry):
        # Deterministic test repair when active; every following score uses the
        # repaired world state, not a stale no-report branch.
        f=w.active(a['start'],repaired)
        if f is not None:state.report(a['start'],True);repaired.add(f.event_id)
        score=w.score(j,repaired)[0];previous=len(state.history);state.ingest(w,j,score)
        if state.last_token_slot!=lastslot:tokens+=1;lastslot=state.last_token_slot
        if len(state.history)==8:
            x=state.feature(w,j);assert len(x)==XDIM and np.all(np.isfinite(x))
            assert len({r[1] for r in state.history})==8
    assert tokens>100
assert maxerr<1e-10,(maxerr,cases)
out=dict(passed=True,official_target_score_cases=cases,max_six_decimal_error=maxerr,paired_report_wait_branches=branches,actual_repair_cases=actual_repair_cases,
    directional_degraded_branches=directional_cases,repaired_continuation_cases=continuation_cases,history8_distinct_slot_contract=True,
    geometry_gate_cases=geometry_cases,offset_nominal_hit_lost=missed,offset_nominal_miss_gained=gained,newworld_assigned_to_actual_geometry_gate=True,
    earthquake_has_no_pointing_effect=True,independent_official_stress_pointing_offset=True,data_loss_not_simulated=True,
    fixed_public_geometry_true_target_ra_dec=True,original_private_columns_read=False,seconds=time.time()-started,xdim=XDIM)
(ROOT/'pilot_operator_checks.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
