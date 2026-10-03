"""Small official-engine positive controls for terrain inference soundness."""
import json,math,sys,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'upstream/gosim-observer-examples/runner'))
from challenge.v4_fiber_map import radec_to_altaz,altaz_to_radec
from challenge.v4_scorer import SlotTruth,ScoreEvent,WeatherTruth,score_target_exposure
from terrain_version_space import TerrainVersionSpace,altaz_at,trajectory_envelope


def checks():
    rng=np.random.default_rng(20261003)
    start=datetime(2026,10,25,1,tzinfo=timezone.utc);lat,lon=-29.2567,-70.7346
    score=json.loads((Path(__file__).resolve().parents[1]/'practice_cards/delta/delta/config/v4_score_config.json').read_text())
    slots=[SlotTruth(str(i),start+timedelta(seconds=900*i),start+timedelta(seconds=900*(i+1)),True,1.,1.,1.,1.) for i in range(6)]
    weather=WeatherTruth(slots,None)
    maximum_error=0.;positive_controls=0;removed=0
    for _ in range(150):
        az=float(rng.uniform(0,360));alt=float(rng.uniform(33,83));d=int(rng.integers(60,3500))
        ra,dec=altaz_to_radec(alt,az,start,lat,lon)
        c=float(rng.uniform(22.5,67.5));w=float(rng.uniform(30,70));h=float(rng.uniform(35,50))
        event=ScoreEvent('test','terrain_obstruction',start,start+timedelta(hours=3),'HORIZON_SECTOR',(c-w/2)%360,(c+w/2)%360,0.,h,1.,1.,1.,1.,False)
        t={'target_id':'test','feature_flux':.2,'science_weight':1.,'ra_deg':ra,'dec_deg':dec}
        result=score_target_exposure(t,list(weather.segments(start,start+timedelta(seconds=d))),[event],weather,d,1.,score,start,
                 lambda m:radec_to_altaz(ra,dec,m,lat,lon),{'latitude_deg':lat,'longitude_deg':lon})
        model=TerrainVersionSpace.reference_prior(['NE'],lat,lon)
        if result.score>0:
            removed+=model.observe_positive(ra,dec,start,d,result.score);positive_controls+=1
            truecell=(model.c_lo<=c-45)&(c-45<=model.c_hi)&(model.w_lo<=w)&(w<=model.w_hi)&(model.h_lo<=h)&(h<=model.h_hi)
            assert np.any(truecell & model.active['NE']),'true generated sector incorrectly removed'
        points=np.linspace(start.timestamp(),start.timestamp()+d,151)
        av,zv=altaz_at(points,ra,dec,lat,lon)
        for j in (0,75,150):
            aa,zz=radec_to_altaz(ra,dec,datetime.fromtimestamp(points[j],timezone.utc),lat,lon)
            maximum_error=max(maximum_error,abs(aa-av[j]),abs((zz-zv[j]+180)%360-180))
        env=trajectory_envelope(ra,dec,start,d,lat,lon)
        assert np.max(av)<=env['alt_max']+1e-7
        assert np.min(av)>=env['alt_min']-1e-7
    assert maximum_error<1e-8
    # A long track enters and leaves a sector: positive != midpoint clear.
    ra,dec=altaz_to_radec(40,67,start,lat,lon)
    model=TerrainVersionSpace.reference_prior(['NE'],lat,lon)
    long_event=ScoreEvent('long','terrain_obstruction',start,start+timedelta(hours=3),
                         'HORIZON_SECTOR',15.,75.,0.,49.5,1.,1.,1.,1.,False)
    mid_alt,mid_az=radec_to_altaz(ra,dec,start+timedelta(seconds=1800),lat,lon)
    assert long_event.covers_altaz(mid_alt,mid_az)
    target={'target_id':'long','feature_flux':.2,'science_weight':1.,'ra_deg':ra,'dec_deg':dec}
    long_result=score_target_exposure(target,list(weather.segments(start,start+timedelta(seconds=3600))),[long_event],weather,3600,1.,score,start,
                 lambda m:radec_to_altaz(ra,dec,m,lat,lon),{'latitude_deg':lat,'longitude_deg':lon})
    assert long_result.score>0
    model.observe_positive(ra,dec,start,3600,long_result.score)
    truecell=(model.c_lo<=0)&(0<=model.c_hi)&(model.w_lo<=60)&(60<=model.w_hi)&(model.h_lo<=49.5)&(49.5<=model.h_hi)
    assert np.any(truecell & model.active['NE'])
    before=model.snapshot();model.observe_zero(ra,dec,start,3600)
    assert before['remaining_boxes']==model.snapshot()['remaining_boxes']
    assert np.all(model.certified_clear([51,70],[45,90]))
    assert not bool(model.certified_clear(40,45))
    # Future positions recompute geometry; high-altitude terrain is never penalized.
    assert float(model.terrain_scale(70,45))==1.
    query=np.linspace(30,85,9400);az=np.arange(9400)%360
    model._map=None
    began=time.perf_counter();model.terrain_scale(query,az);cold=time.perf_counter()-began
    began=time.perf_counter();model.terrain_scale(query,az);warm=time.perf_counter()-began
    return {'schema':'terrain-version-space-checks-v1','official_positive_controls':positive_controls,
            'parameter_boxes_removed':removed,'true_generated_box_preserved':True,
            'official_geometry_max_error_deg':maximum_error,'zero_no_hard_update':True,
            'high_altitude_clear':True,'9400_query_cold_seconds':cold,'9400_query_warm_seconds':warm,
            'long_positive_with_midpoint_blocked_true_cell_preserved':True,
            'scope':'synthetic official engine controls only; reference prior conditional domain'}


if __name__=='__main__':
    result=checks();print(json.dumps(result,indent=2))
    Path(__file__).with_name('terrain_version_space_checks_result.json').write_text(json.dumps(result,indent=2)+'\n')
