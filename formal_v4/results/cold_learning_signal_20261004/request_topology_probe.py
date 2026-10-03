"""Exact feature collision with two legal, tiny official-score continuations.

No runner, training, bulk label loading, network, or scenario simulation.
The two request graphs are public input; deterministic synthetic weather is
used only by the official per-exposure scorer and terminal ledger settlement.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

FORMAL = Path(__file__).resolve().parents[2]
UPSTREAM = FORMAL / "upstream/gosim-observer-examples"
sys.path[:0] = [str(FORMAL), str(UPSTREAM / "runner")]
from research.structured_student_features import TARGET_SOURCE_NAMES, build_public_features
from challenge.v4_fiber_map import FiberGrid, altaz_to_radec, radec_to_altaz, min_altitude_during, validate_action
from challenge.v4_scorer import (BestLedger, SlotTruth, WeatherTruth, lunar_quality_factor,
    program_band, program_multiplier, score_target_exposure, required_penalty,
    uniformity_penalty, settle_observation_requests)
from challenge.tile_geometry_simulator import _sun_equatorial_deg
from challenge.v4_runner import normalize_action

OUT = Path(__file__).resolve().parent
LOCK_PATHS = [FORMAL / ("research/" + name) for name in
              ("structured_student_features.py", "structured_student_model.py", "structured_student_train.py",
               "structured_student_runtime.py", "structured_student_audit.py")]
LOCK_PATHS += [UPSTREAM / ("runner/challenge/" + name) for name in
               ("v4_runner.py", "v4_scorer.py", "v4_fiber_map.py", "tile_geometry_simulator.py")]
LOCK_PATHS += [UPSTREAM / ("local-cards/L1/config/" + name) for name in
               ("v4_score_config.json", "v4_fiber_config.json")]
LOCK_PATHS += [Path(__file__).resolve()]


def hashes():
    return {str(p.relative_to(FORMAL)): hashlib.sha256(p.read_bytes()).hexdigest() for p in LOCK_PATHS}


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_target(tid, fiber, center, t, grid, site):
    """Inverse gnomonic point at the official fiber cell centre, away from seams."""
    alt, az = map(math.radians, center)
    north, east = grid.fiber_center_offset(fiber)
    c = np.array([math.cos(alt)*math.cos(az), math.cos(alt)*math.sin(az), math.sin(alt)])
    e = np.array([-math.sin(az), math.cos(az), 0.])
    n = np.array([-math.sin(alt)*math.cos(az), -math.sin(alt)*math.sin(az), math.cos(alt)])
    u = c + math.radians(east)*e + math.radians(north)*n
    u /= np.linalg.norm(u)
    ta = math.degrees(math.asin(u[2]))
    tz = math.degrees(math.atan2(u[1],u[0])) % 360
    ra, dec = altaz_to_radec(ta, tz, t, site["latitude_deg"], site["longitude_deg"])
    return dict(target_id=tid, ra_deg=ra, dec_deg=dec, target_class="Star",
                feature_flux=100., science_weight=1., required=False)


def public_request(number, members, start, end):
    return dict(schema_version="v4-observation-request-v1", record_type="observation_request",
                request_id=f"Q{number}", issued_at_utc=iso(start), deadline_utc=iso(end),
                target_ids=members, minimum_completed=2, completion_factor_threshold=.5,
                completion_reward=100., reason="synthetic topology probe", completed_target_ids=[],
                completed_count=0, remaining_count=2)


def arrays_equal(a, b):
    checks = {"target_nodes": np.array_equal(a.target_nodes,b.target_nodes),
              "global_features": np.array_equal(a.global_features,b.global_features),
              "flat": np.array_equal(a.flat(),b.flat())}
    for x,y in zip(a.actions,b.actions):
        assert x.name == y.name
        checks[x.name+".target_index"] = np.array_equal(x.target_index,y.target_index)
        checks[x.name+".edges"] = np.array_equal(x.edges,y.edges)
        checks[x.name+".scalars"] = np.array_equal(x.scalars,y.scalars)
        checks[x.name+".coarse_utility"] = x.coarse_utility == y.coarse_utility
        checks[x.name+".gain_per_second"] = x.gain_per_second == y.gain_per_second
        checks[x.name+".native_utility"] = x.native_utility == y.native_utility
    assert all(checks.values()), checks
    return {k:bool(v) for k,v in checks.items()}


def main():
    before = hashes()
    score_cfg = json.loads((UPSTREAM/"local-cards/L1/config/v4_score_config.json").read_text())
    fiber_cfg = json.loads((UPSTREAM/"local-cards/L1/config/v4_fiber_config.json").read_text())
    site = {**fiber_cfg["site"],"minimum_altitude_deg":30.,"sun_altitude_limit_deg":-18.}
    grid = FiberGrid.from_config(fiber_cfg)
    prefix_start = datetime(2026,11,2,0,30,tzinfo=timezone.utc)
    start = prefix_start+timedelta(seconds=900)
    middle, end = start+timedelta(seconds=900), start+timedelta(seconds=1800)
    # Choose a field wholly inside one occupied RA band, so Jain is identical.
    center = None
    for az in range(60,121):
        trial=(60.,float(az))
        trial_targets=[make_target(tid,f,trial,start,grid,site) for tid,f in zip("abcd",(0,4,1,5))]
        if len({int(t["ra_deg"]//10) for t in trial_targets}) == 1:
            center,targets=trial,trial_targets
            break
    assert center is not None
    by_id={t["target_id"]:t for t in targets}
    center_ra,center_dec=altaz_to_radec(*center,start,site["latitude_deg"],site["longitude_deg"])
    p=dict(alt_deg=center[0],az_deg=center[1])
    actions={"control":dict(action="observe",pointing=p.copy(),duration_seconds=900,program="DARK",assignments={"0":"a"}),
             "field":dict(action="observe",pointing=p.copy(),duration_seconds=900,program="DARK",assignments={"1":"c"})}
    b_alt,b_az=radec_to_altaz(center_ra,center_dec,middle,site["latitude_deg"],site["longitude_deg"])
    cls=grid.classify_target(by_id["b"]["ra_deg"],by_id["b"]["dec_deg"],middle,b_alt,b_az,
                             site["latitude_deg"],site["longitude_deg"])
    assert cls.region=="glass"
    continuation=dict(action="observe",pointing=dict(alt_deg=b_alt,az_deg=b_az),duration_seconds=900,
                      program="DARK",assignments={str(cls.fiber_id):"b"})
    prefix_alt,prefix_az=radec_to_altaz(center_ra,center_dec,prefix_start,site["latitude_deg"],site["longitude_deg"])
    dcls=grid.classify_target(by_id["d"]["ra_deg"],by_id["d"]["dec_deg"],prefix_start,prefix_alt,prefix_az,
                              site["latitude_deg"],site["longitude_deg"])
    assert dcls.region=="glass"
    prefix_action=dict(action="observe",pointing=dict(alt_deg=prefix_alt,az_deg=prefix_az),duration_seconds=900,
                       program="DARK",assignments={str(dcls.fiber_id):"d"})
    columns=["target_id","ra_deg","dec_deg","target_class","feature_flux","science_weight","required"]
    initial=dict(schema_version="v4-initialize-v1",site=site,
                 task_card=dict(card_id="synthetic",scenario_slug="request-topology",phase="local"),
                 targets=dict(columns=columns,rows=[[t[k] for k in columns] for t in targets]),scoring=score_cfg,
                 survey=dict(start_utc=iso(prefix_start),end_utc=iso(end),slot_seconds=900,nights=[dict(night_id="N20261101",
                     night_date="2026-11-01",observing_start_utc=iso(prefix_start),observing_end_utc=iso(end),slot_count=3)]),
                 instrument=dict(n_fibers=16,grid_side=4,pitch_deg=grid.pitch_deg,fiber_area_deg2=.4,gap_deg=0.,
                     glass_side_deg=grid.fiber_side_deg,fov_side_deg=grid.fov_side_deg,exposure=fiber_cfg["exposure"]),
                 limits=dict(global_wallclock_seconds=900,max_consecutive_reports=32,response_max_bytes=524288,
                             decision_timeout="global only (no per-decision timeout)"))
    ra0,ra1=min(t["ra_deg"] for t in targets)-.5,max(t["ra_deg"] for t in targets)+.5
    dec0,dec1=min(t["dec_deg"] for t in targets)-.5,max(t["dec_deg"] for t in targets)+.5
    initial["footprint"]=[dict(component_id="C00",vertices=[[ra0,dec0],[ra1,dec0],[ra1,dec1],[ra0,dec1]])]
    source=[]
    for t in targets:
        alt,az=radec_to_altaz(t["ra_deg"],t["dec_deg"],start,site["latitude_deg"],site["longitude_deg"])
        source.append([t["ra_deg"]/360,t["dec_deg"]/90,t["feature_flux"],t["science_weight"],0,
                       0,0,0,0,alt/90,math.sin(math.radians(az)),math.cos(math.radians(az)),1,1])
    arrays={"target_features":np.array(source),"scores":np.zeros(4),"factor_lower":np.zeros(4),"factor_estimate":np.zeros(4),
            "ledger_rank":np.array([0],int),"ledger_target":np.array([3],int),"ledger_score":np.array([0.]),
            "ledger_factor_estimate":np.array([0.]),"ledger_lower":np.array([0.]),"ledger_valid":np.array([True]),
            "control_assignment":np.array([[0,0]]),"field_assignment":np.array([[1,2]])}
    # Constant public prior predictions; these do not read official scorer outputs.
    predictions={name:{tid:dict(index="abcd".index(tid),fiber_id=int(fiber),factor=1.,public_quality=1.,quality=1.,
                               directional_scale=1.,predicted_band="DARK") for fiber,tid in action["assignments"].items()}
                 for name,action in actions.items()}
    common=dict(feature_schema="public-target-ledger-v1",target_ids=list("abcd"),target_feature_names=list(TARGET_SOURCE_NAMES),
                rank=1,now_utc=iso(start),actions=actions,candidate_predictions=predictions,
                public_history=[dict(now_utc=iso(prefix_start),observe_action_index=0,action=prefix_action,last_result=None),
                                dict(now_utc=iso(start),observe_action_index=1,last_result=dict(action="observe",observe_index=0,
                                     assigned_count=1,hit_count=1,hits=[dict(target_id="d",score=0.)]))],C=1.,E=1.,
                notices=[],terrain=[],snapshot=dict(now_utc=iso(start),survey_end_utc=iso(end),observe_action_index=1,
                    running_total=0.,latest_bulletin=None,latest_forecast=None,new_messages=[],
                    last_result=dict(action="observe",observe_index=0,assigned_count=1,hit_count=1,hits=[dict(target_id="d",score=0.)])))
    graphs={"ab_cd":[["a","b"],["c","d"]],"ad_bc":[["a","d"],["b","c"]]}
    captures={}
    features={}
    for world,membership in graphs.items():
        cap=copy.deepcopy(common)
        cap["snapshot"]["active_requests"]=[public_request(i+1,m,start,end) for i,m in enumerate(membership)]
        captures[world]=cap
        features[world]=build_public_features(initial,cap,arrays)
    equality=arrays_equal(*features.values())
    slots=[SlotTruth("N20261101-S001",prefix_start,start,False,0.,0.,0.,0.)]
    slots += [SlotTruth(f"N20261101-S{i+2:03}",s,e,True,1.,1.,1.,1.) for i,(s,e) in enumerate([(start,middle),(middle,end)])]
    weather=WeatherTruth(slots,None)
    rows=[]
    totals={}
    sun_alts=[radec_to_altaz(*_sun_equatorial_deg(t),t,site["latitude_deg"],site["longitude_deg"])[0] for t in (prefix_start,start,middle,end)]
    assert max(sun_alts)<-18, sun_alts
    for world,cap in captures.items():
        totals[world]={}
        for name,first in actions.items():
            ledger=BestLedger()
            for rank,(action,t0,t1) in enumerate([(prefix_action,prefix_start,start),(first,start,middle),(continuation,middle,end)]):
                normalize_action(action,SimpleNamespace(fiber_config=fiber_cfg),by_id,t0)
                validate_action({k:v for k,v in action.items() if k!="program"},fiber_cfg)
                fiber,tid=next(iter(action["assignments"].items()))
                target=by_id[tid]
                pt=action["pointing"]
                hit=grid.classify_target(target["ra_deg"],target["dec_deg"],t0,pt["alt_deg"],pt["az_deg"],
                                         site["latitude_deg"],site["longitude_deg"])
                min_alt=min_altitude_during(target["ra_deg"],target["dec_deg"],t0,t1,dict(site=site))
                assert hit.region=="glass" and hit.fiber_id==int(fiber) and min_alt>=30
                altaz=lambda t,target=target: radec_to_altaz(target["ra_deg"],target["dec_deg"],t,site["latitude_deg"],site["longitude_deg"])
                lunar=lambda t,target=target: lunar_quality_factor(target["ra_deg"],target["dec_deg"],t,site,score_cfg)
                band=program_band(weather.band_quality(t0,t1,score_cfg,lambda t:altaz(t)[0],lunar),score_cfg)
                mult=program_multiplier(action["program"],band,score_cfg)
                scored=score_target_exposure(target,list(weather.segments(t0,t1)),[],weather,900,mult,score_cfg,t0,altaz,site)
                assert scored.factor==(0. if rank==0 else 1.)
                ledger.record(rank,tid,scored.factor,scored.score,t0,t1)
                rows.append(dict(world=world,candidate=name,rank=rank,target_id=tid,assigned_fiber=int(fiber),
                                 actual_fiber=hit.fiber_id,min_altitude=min_alt,band=band,factor=scored.factor,score=scored.score))
            best=sum(s for _,s in ledger.best().values())
            missing,reqcost=required_penalty(targets,ledger.max_factors(),score_cfg)
            bands,unicost=uniformity_penalty(targets,ledger.max_factors(),score_cfg)
            request_rows,reward=settle_observation_requests([{**r,"issued_at_utc":start,"deadline_utc":end}
                                                          for r in cap["snapshot"]["active_requests"]],ledger)
            total=best-reqcost-unicost+reward
            totals[world][name]=dict(sum_best_scores=best,required_penalty=-reqcost,uniformity_penalty=-unicost,
                                     observation_request_reward=reward,report_settlement=0.,total=total,
                                     completed_requests=[r["request_id"] for r in request_rows if r["completed"]],uniformity_bands=bands)
    assert totals["ab_cd"]["control"]["total"]>totals["ab_cd"]["field"]["total"]
    assert totals["ad_bc"]["control"]["total"]<totals["ad_bc"]["field"]["total"]
    # A tiny explicit membership statistic breaks the collision under this known pi:
    # reward for requests jointly covered by this action and the b continuation.
    relation={w:{a:sum(100. for req in caps["snapshot"]["active_requests"]
                     if set(req["target_ids"])<=set(action["assignments"].values())|{"b"})
                 for a,action in actions.items()} for w,caps in captures.items()}
    # Minimal supplementary request nodes + member joins. IDs remain join keys;
    # no numeric request/target ID is used as a learned feature. In this fixed pi,
    # b's continuation support is a public policy fact, not a hidden truth label.
    relation_arrays={}
    supplemented_checks={}
    for world,cap in captures.items():
        requests=cap["snapshot"]["active_requests"]
        relation_arrays[world+"_request_nodes"]=np.array([[r["minimum_completed"],r["completed_count"],
            (end-start).total_seconds(),r["completion_factor_threshold"],r["completion_reward"]] for r in requests])
        relation_arrays[world+"_request_member_index"]=np.array([[j,"abcd".index(t)]
            for j,r in enumerate(requests) for t in r["target_ids"]],int)
        for name,action in actions.items():
            assigned=set(action["assignments"].values())
            # Apply request-local threshold BEFORE pooling over different requests.
            pool=np.array([[sum(t in assigned for t in r["target_ids"]),sum(t=="b" for t in r["target_ids"]),
                            sum(t in assigned and t=="b" for t in r["target_ids"]),r["remaining_count"]]
                           for r in requests],float)
            relation_arrays[world+"_"+name+"_request_local_pool"]=pool
            score=float(np.sum((pool[:,0]+pool[:,1]-pool[:,2]>=pool[:,3])*100.))
            assert score==relation[world][name]
    supplemented_checks["request_members_differ"]=not np.array_equal(relation_arrays["ab_cd_request_member_index"],
                                                                       relation_arrays["ad_bc_request_member_index"])
    for name in actions:
        supplemented_checks[name+"_request_local_pool_differs"]=not np.array_equal(
            relation_arrays["ab_cd_"+name+"_request_local_pool"],relation_arrays["ad_bc_"+name+"_request_local_pool"])
    assert all(supplemented_checks.values())
    after=hashes()
    assert before==after
    report=dict(schema="request-topology-exact-feature-collision-v1",source_sha256=before,
                upstream_student_sources_unchanged=True,features_all_equal=equality,official_legal_exposures=rows,
                sun_altitudes=sun_alts,official_settlement=totals,request_relation_statistic=relation,
                minimal_request_supplement_breaks_collision=supplemented_checks,
                unavoidable_mean_regret_on_equal_world_mixture=50.,
                scope="Existence/representation proof: one identical closed-slot prefix + two legal open-slot exposures, fixed public pi observes b next; no runner or training. Not actual L1-L4 benefit.",
                bulk_active_requests="Not inspected or counted. No bulk labels/captures were loaded.")
    (OUT/"probe_report.json").write_text(json.dumps(report,indent=2)+"\n")
    (OUT/"synthetic_inputs.json").write_text(json.dumps(dict(initial=initial,captures=captures,continuation=continuation),indent=2)+"\n")
    np.savez_compressed(OUT/"synthetic_source_arrays.npz",**arrays)
    matrices={}
    for world,f in features.items():
        matrices[world+"_target"]=f.target_nodes
        matrices[world+"_global"]=f.global_features
        matrices[world+"_flat"]=f.flat()
        for a in f.actions:
            for key in ("target_index","edges","scalars"):
                matrices[world+"_"+a.name+"_"+key]=getattr(a,key)
    np.savez_compressed(OUT/"exact_builder_outputs.npz",**matrices)
    np.savez_compressed(OUT/"minimal_request_relation_outputs.npz",**relation_arrays)
    print(json.dumps(dict(features_all_equal=all(equality.values()),totals={w:{a:r["total"] for a,r in t.items()} for w,t in totals.items()},
                          explicit_relation=relation,report=str(OUT/"probe_report.json")),indent=2))


if __name__=="__main__":
    main()
