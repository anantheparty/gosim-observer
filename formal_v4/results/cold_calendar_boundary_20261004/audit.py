"""Small public/synthetic calendar audit; no scenario truth is loaded.

Only the official Scenario loader is substituted with a validated in-memory
synthetic Scenario. Official action normalization, runner, fiber geometry,
weather integration, ledger, and final settlement run without edits.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import time
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
UP = ROOT / "formal_v4/upstream/gosim-observer-examples"
sys.dont_write_bytecode = True
sys.path.insert(0, str(UP / "runner"))
from challenge import v4_runner as vr
from challenge import v4_scorer as vs
from challenge.v4_config_check import validate_scenario
from challenge.v4_fiber_map import FiberGrid, altaz_to_radec, radec_to_altaz, min_altitude_during
from challenge.v4_workflow import V4Workflow

CARD = UP / "local-cards/L1"
fiber = json.loads((CARD / "config/v4_fiber_config.json").read_text())
score = json.loads((CARD / "config/v4_score_config.json").read_text())
site = dict(fiber["site"], sun_altitude_limit_deg=-18.0)
grid = FiberGrid.from_config(fiber)
lat, lon = site["latitude_deg"], site["longitude_deg"]
utc = vr._parse_utc
fmt = vr._format_utc
OUT.mkdir(parents=True, exist_ok=True)
footprint = OUT / "synthetic_footprint.csv"
footprint.write_text("component_id,vertex_index,ra_deg,dec_deg\nA,0,0,-60\nA,1,360,-60\nA,2,360,30\nA,3,0,30\n")


def target_at(target_id, alt, az, moment, flux=.5, weight=1., required=False):
    ra, dec = altaz_to_radec(alt, az, moment, lat, lon)
    return dict(target_id=target_id, ra_deg=ra, dec_deg=dec,
                target_class="ELG", feature_flux=flux,
                science_weight=weight, required=required)


def ray_target(target_id, center_alt, center_az, da, dz, moment, **kwargs):
    a, z = math.radians(center_alt), math.radians(center_az)
    center = (math.cos(a)*math.cos(z), math.cos(a)*math.sin(z), math.sin(a))
    up = (-math.sin(a)*math.cos(z), -math.sin(a)*math.sin(z), math.cos(a))
    right = (-math.sin(z), math.cos(z), 0.)
    vec = tuple(center[j]+math.radians(da)*up[j]+math.radians(dz)*right[j] for j in range(3))
    norm = math.sqrt(sum(x*x for x in vec))
    alt = math.degrees(math.asin(vec[2]/norm))
    az = math.degrees(math.atan2(vec[1], vec[0])) % 360
    return target_at(target_id, alt, az, moment, **kwargs)


def slots(start, end, prefix="N_SYN", observable=True, seeing=1.5):
    result = []
    cursor = start
    while cursor < end:
        stop = min(end, cursor+timedelta(seconds=900))
        result.append(vs.SlotTruth(f"{prefix}-S{len(result)+1:03d}", cursor, stop,
                                   observable, seeing, 1., 1., 1.))
        cursor = stop
    return result


def scenario(name, targets, slot_list, requests=(), events=(), stress=()):
    cfg = dict(schema_version="v4-scenario-v1", name=name, site=site,
               minimum_altitude_deg=30., products={"footprint_csv": "synthetic_footprint.csv"},
               stress={"enabled": bool(stress)})
    sc = vr.Scenario(cfg, OUT, site, fiber, score, targets, slot_list,
                     list(events), [], [], list(requests), list(stress),
                     slot_list[0].start_utc, slot_list[-1].end_utc)
    validate_scenario(sc)
    return sc


def action_for(targets, start, center_ra, center_dec, duration, program="BACKUP"):
    alt, az = radec_to_altaz(center_ra, center_dec, start, lat, lon)
    assign = {}
    for t in targets:
        c = grid.classify_target(t["ra_deg"], t["dec_deg"], start, alt, az, lat, lon)
        if c.region == "glass" and c.fiber_id not in assign:
            assign[c.fiber_id] = t["target_id"]
    return {"action": "observe", "pointing": {"alt_deg": alt, "az_deg": az},
            "assignments": assign, "duration_seconds": duration, "program": program}


def official_run(name, sc, schedule):
    schedule = list(schedule)
    snapshots = []
    def factory(_):
        def agent(snapshot):
            snapshots.append(snapshot)
            return schedule.pop(0) if schedule else {"action": "finish"}
        return agent
    stub = OUT / f"{name}_scenario_stub.json"
    stub.write_text(json.dumps({"synthetic_in_memory": name}, sort_keys=True)+"\n")
    with patch.object(vr, "load_scenario", return_value=sc):
        report = vr.run_scenario(stub, factory, OUT / name)
    report.pop("organizer_only", None)
    (OUT/name/"snapshots.json").write_text(json.dumps(snapshots, indent=2)+"\n")
    return report


def protocol_valid(action, sc, now):
    env = dict(action, protocol_version="participant-agent-protocol-v4",
               message_type="decision_response", decision_sequence=1)
    a = V4Workflow.action_from_response(env, 1)
    vr.normalize_action(a, sc, {t["target_id"]:t for t in sc.targets}, now)


def last_observation(case):
    return list(csv.DictReader((OUT/case/"observations.csv").open()))[-1]


def gap_tests():
    a = utc("2026-11-03T00:30:00Z")
    # Deterministic geometry search only, independent of any weather/old labels.
    early = a-timedelta(seconds=2700)
    found = None
    for alt in (65,70,75,80,85,88):
        for az in range(0,360,15):
            center_ra, center_dec = altaz_to_radec(alt,az,a,lat,lon)
            ts=[ray_target(f"SYN_PAIR_{j}",alt,az,d,0.,a) for j,d in enumerate((-1.4,1.4))]
            if min(min_altitude_during(t["ra_deg"],t["dec_deg"],early,a+timedelta(seconds=900),{"site":site}) for t in ts)<30:
                continue
            first=action_for(ts,early,center_ra,center_dec,3600)
            later=action_for(ts,a,center_ra,center_dec,900)
            if len(first["assignments"])==2 and len(later["assignments"])<2:
                found=(ts,center_ra,center_dec,first,later,alt,az)
                break
        if found:
            break
    assert found is not None
    ts,ra,dec,first,later,alt,az=found
    ss=slots(a-timedelta(seconds=86400),a-timedelta(seconds=57600),"N_PREV",False)
    ss+=slots(a,a+timedelta(seconds=900),"N_NEXT",True,4.)
    sc=scenario("gap_orientation",ts,ss)
    pre=official_run("gap_orientation_pre",sc,[{"action":"wait","until_utc":fmt(early)},first])
    late=official_run("gap_orientation_late_same_center",sc,[{"action":"wait","until_utc":fmt(a)},later])
    protocol_valid(first,sc,early)
    # Identical target/fiber track, padding is exactly zero photon contribution.
    one=[ts[0]]
    sc1=scenario("gap_padding",one,ss)
    p=action_for(one,early,ra,dec,3600)
    # Pointing on its own position centers it at both starts, ensuring matched hits.
    p=action_for(one,early,one[0]["ra_deg"],one[0]["dec_deg"],3600)
    q=action_for(one,a,one[0]["ra_deg"],one[0]["dec_deg"],900)
    rpre=official_run("gap_padding_pre",sc1,[{"action":"wait","until_utc":fmt(early)},p])
    rlate=official_run("gap_padding_late",sc1,[{"action":"wait","until_utc":fmt(a)},q])
    # Entire exposure in gap: accepted and hits, but exactly no science.
    rzero=official_run("gap_only_zero",sc1,[{"action":"wait","until_utc":fmt(a-timedelta(seconds=4000))},
                   action_for(one,a-timedelta(seconds=4000),one[0]["ra_deg"],one[0]["dec_deg"],60)])
    assert rzero["components"]["sum_best_scores"]==0
    assert abs(rpre["components"]["sum_best_scores"]-rlate["components"]["sum_best_scores"])<1e-6
    assert pre["total"]>late["total"]
    # Certify every within-night center/time schedule, not only same-center.
    # Any hit lies within spherical cap R around the field center. This bounds
    # the center's azimuth separation from either high-altitude target by zmax.
    # Their vertical gnomonic coordinate difference therefore exceeds g(t).
    radius=math.atan(math.sqrt(2)*math.radians(grid.fov_side_deg/2))
    maximum_alt=max(radec_to_altaz(t["ra_deg"],t["dec_deg"],a,lat,lon)[0] for t in ts)
    zmax=math.asin(math.sin(radius)/math.cos(math.radians(maximum_alt)))
    cmin=math.cos(zmax)
    lows=[]
    for second in range(901):
        alts=[radec_to_altaz(t["ra_deg"],t["dec_deg"],a+timedelta(seconds=second),lat,lon)[0] for t in ts]
        lows.append(alts[1]-math.degrees(math.atan(math.tan(math.radians(alts[0]))/cmin)))
    omega=360.98564736629/86400
    lip=omega*(1+1/cmin)
    certified_span_lower=min(lows)-.5*lip-1e-7
    maximum_field_span=2*math.degrees(math.atan(math.radians(grid.fov_side_deg/2)))
    assert certified_span_lower>maximum_field_span
    # The synthetic seeing=4 implies q_band <=1/(4*q0)<BRIGHT.
    # Every inside-night action thus gets at most BACKUP bonus, and <=one hit.
    # Arbitrary repeated visits and starts have <=900 total weather seconds.
    inside_science_upper=score["program"]["multipliers"]["BACKUP"]/(4*score["q0"])
    assert inside_science_upper<pre["components"]["sum_best_scores"]
    weather=vs.WeatherTruth(ss,None)
    qpre=weather.band_quality(early,a+timedelta(seconds=900),score,
         lambda tm:radec_to_altaz(one[0]["ra_deg"],one[0]["dec_deg"],tm,lat,lon)[0],
         lambda tm:vs.lunar_quality_factor(one[0]["ra_deg"],one[0]["dec_deg"],tm,site,score))
    qlate=weather.band_quality(a,a+timedelta(seconds=900),score,
         lambda tm:radec_to_altaz(one[0]["ra_deg"],one[0]["dec_deg"],tm,lat,lon)[0],
         lambda tm:vs.lunar_quality_factor(one[0]["ra_deg"],one[0]["dec_deg"],tm,site,score))
    return dict(center_at_night_start={"alt_deg":alt,"az_deg":az},early_start=fmt(early),
         night_start=fmt(a),targets=ts,pre_action=first,later_same_center_action=later,
         orientation_pre=pre,orientation_late_same_center=late,
         padding_pre=rpre,padding_late=rlate,qband_pre=qpre,qband_late=qlate,
         padding_factor_pre=last_observation("gap_padding_pre")["factor"],
         padding_factor_late=last_observation("gap_padding_late")["factor"],gap_zero=rzero,
         all_inside_night_certificate={"grid_radius_deg":math.degrees(radius),
             "maximum_target_altitude_deg":maximum_alt,"az_separation_bound_deg":math.degrees(zmax),
             "minimum_integer_grid_span_deg":min(lows),"lipschitz_deg_per_second":lip,
             "certified_span_lower_deg":certified_span_lower,"field_span_upper_deg":maximum_field_span,
             "arbitrary_inside_schedule_science_upper":inside_science_upper,
             "gap_action_science":pre["components"]["sum_best_scores"],
             "certified_science_advantage":pre["components"]["sum_best_scores"]-inside_science_upper})


def tail_tests():
    end=utc("2026-11-03T08:30:00Z")
    start=end-timedelta(seconds=30)
    t=ray_target("SYN_TAIL",70,30,-.3,-.3,start)
    sc=scenario("tail",[t],slots(end-timedelta(seconds=900),end))
    act=action_for([t],start,*altaz_to_radec(70,30,start,lat,lon),60,"DARK")
    wait=official_run("tail_wait",sc,[{"action":"wait","until_utc":fmt(start)}, {"action":"wait","until_utc":fmt(end)}])
    obs=official_run("tail_observe60_actual30",sc,[{"action":"wait","until_utc":fmt(start)},act])
    protocol_valid(act,sc,start)
    assert obs["total"]>wait["total"]
    row=list(csv.DictReader((OUT/"tail_observe60_actual30/decisions.csv").open()))[-1]
    assert row["duration_seconds"]=="30"
    # A request at night start refuses the otherwise equal padded observation.
    a=utc("2026-11-03T00:30:00Z")
    early=a-timedelta(seconds=2700)
    reqtarget=target_at("SYN_REQ",70,30,a,flux=2.)
    req={"schema_version":"v4-observation-request-v1","record_type":"observation_request","request_id":"REQ_SYN",
         "issued_at_utc":a,"deadline_utc":a+timedelta(seconds=900),"target_ids":["SYN_REQ"],
         "minimum_completed":1,"completion_factor_threshold":.5,"completion_reward":100.,"reason":"synthetic"}
    ss=slots(a-timedelta(seconds=86400),a-timedelta(seconds=57600),"N_PREV",False)+slots(a,a+timedelta(seconds=900),"N_NEXT")
    scq=scenario("request_padding",[reqtarget],ss,[req])
    p=action_for([reqtarget],early,reqtarget["ra_deg"],reqtarget["dec_deg"],3600,"BACKUP")
    q=action_for([reqtarget],a,reqtarget["ra_deg"],reqtarget["dec_deg"],900,"DARK")
    rp=official_run("request_padding_pre",scq,[{"action":"wait","until_utc":fmt(early)},p])
    rq=official_run("request_padding_late",scq,[{"action":"wait","until_utc":fmt(a)},q])
    assert rp["components"]["observation_request_reward"]==0
    assert rq["components"]["observation_request_reward"]==100
    return dict(tail_action=act,tail_wait=wait,tail_observe=obs,actual_duration=30,
                tail_increment=round(obs["total"]-wait["total"],6),
                request_pre=rp,request_late=rq)


def public_prefix_opportunity():
    # Read only public history through the fixed L1/rank858 capture.
    cap_path=ROOT/"formal_v4/results/policy_iteration_20261004/late_control/L1/rank_0858/control/public_capture/capture.json"
    cap=json.loads(cap_path.read_text())
    history=cap["public_history"]
    nights=list(csv.DictReader((CARD/"public/v4_night_calendar.csv").open()))
    ends=[utc(n["observing_end_utc"]) for n in nights]
    chosen=None
    best={}
    for h in history:
        for hit in (h.get("last_result") or {}).get("hits",[]):
            best[hit["target_id"]]=max(best.get(hit["target_id"],0),hit["score"])
        now=utc(h["now_utc"])
        end=next((b for b in ends if 0<(b-now).total_seconds()<60),None)
        # First >=30s omitted tail, chosen using public time only.
        if end and (end-now).total_seconds()>=30:
            chosen=(h,now,end,dict(best))
            break
    assert chosen is not None
    h,now,end,best=chosen
    cat=[]
    for row in csv.DictReader((CARD/"public/targets.csv").open()):
        cat.append(dict(target_id=row["target_id"],ra_deg=float(row["ra_deg"]),dec_deg=float(row["dec_deg"]),
             target_class=row["target_class"],feature_flux=float(row["feature_flux"]),
             science_weight=float(row["science_weight"]),required=row["required"]=="true"))
    eligible=[t for t in cat if best.get(t["target_id"],0)==0 and min_altitude_during(t["ra_deg"],t["dec_deg"],now,end,{"site":site})>=30]
    # Candidate chosen from public catalog/geometry, without future/weather/label.
    # Maximum sum(flux*weight) over 100 deterministic celestial target anchors.
    trial=eligible[::max(1,len(eligible)//100)][:100]
    candidate=None
    nominal=-1.
    for center in trial:
        act=action_for(eligible,now,center["ra_deg"],center["dec_deg"],60,"BACKUP")
        ids=set(act["assignments"].values())
        value=sum(t["feature_flux"]*t["science_weight"] for t in eligible if t["target_id"] in ids)
        if value>nominal:
            nominal=value
            candidate=act
    selected=[t for t in eligible if t["target_id"] in candidate["assignments"].values()]
    assert selected
    sc=scenario("public_prefix_tail_conditional",cat,slots(now-timedelta(seconds=900),end,"N_PUBLIC",True,1.5))
    protocol_valid(candidate,sc,now)
    # Synthetic future is disclosed; its values are not actual practice weather.
    tiny=official_run("public_catalog_tail_synthetic_weather",sc,[{"action":"wait","until_utc":fmt(now)},candidate])
    assert tiny["components"]["sum_best_scores"]>0
    rows=list(csv.DictReader((OUT/"public_catalog_tail_synthetic_weather/observations.csv").open()))
    assert all(float(r["factor"])<.5 for r in rows)
    # Any true old prefix ledger consistent with these zero public best scores is
    # unchanged outside selected IDs. Since each new factor <.5, all completion
    # bits/Jain/requests stay fixed; delta is exactly these new science values,
    # unless a later data-loss trigger reinterprets the changed observe ranks.
    step=next(i for i,x in enumerate(history) if x is h)
    old=h["action"]
    assert old["action"]=="wait"
    messages=[msg for snap in history[:step+1] for msg in snap.get("new_messages",[])]
    issued_requests=[msg for msg in messages if msg.get("record_type")=="observation_request"]
    resyncs=[msg for msg in messages if msg.get("record_type")=="state_resync"]
    assert not resyncs
    issued_requests=[dict(msg,issued_at_utc=utc(msg["issued_at_utc"]),deadline_utc=utc(msg["deadline_utc"])) for msg in issued_requests]
    report_constant=sum((snap.get("last_result") or {}).get("score_delta",0.) for snap in history[:step+1]
                        if (snap.get("last_result") or {}).get("action")=="report")
    byid={t["target_id"]:t for t in cat}
    w=vs.WeatherTruth(sc.slots,None)
    new_scores=[]
    for t in selected:
        position=lambda tm,t=t:radec_to_altaz(t["ra_deg"],t["dec_deg"],tm,lat,lon)
        bandq=w.band_quality(now,end,score,lambda tm:position(tm)[0],
                 lambda tm,t=t:vs.lunar_quality_factor(t["ra_deg"],t["dec_deg"],tm,site,score))
        mult=vs.program_multiplier(candidate["program"],vs.program_band(bandq,score),score)
        actual=vs.score_target_exposure(t,list(w.segments(now,end)),[],w,int((end-now).total_seconds()),mult,score,now,position,site)
        new_scores.append(actual)
    def settle(ledger):
        bests=ledger.best()
        factors=ledger.max_factors()
        _,req=vs.required_penalty(cat,factors,score)
        _,unif=vs.uniformity_penalty(cat,factors,score)
        _,reqreward=vs.settle_observation_requests(issued_requests,ledger)
        return {"science":sum(v[1] for v in bests.values()),"required":-req,"uniformity":-unif,
                "observation_request_reward":reqreward,"report_settlement":report_constant}
    # Original raw factors are not public. Verify both score-implied endpoint
    # ledgers; the symbolic unchanged-completion argument covers every interior.
    ledger_audits=[]
    for endpoint in ("lower","upper"):
        ledger=vs.BestLedger()
        for n,snap in enumerate(history[:step+1]):
            result=snap.get("last_result") or {}
            if result.get("action")!="observe":
                continue
            prev=history[n-1]
            declared=prev["action"]["program"]
            bonus=score["program"]["multipliers"][declared]
            for hit in result["hits"]:
                target=byid[hit["target_id"]]
                normalized=hit["score"]/target["science_weight"]
                factor=normalized/bonus if endpoint=="lower" else min(1.,normalized)
                ledger.record(result["observe_index"],target["target_id"],min(1.,factor),hit["score"],utc(prev["now_utc"]),utc(snap["now_utc"]))
        before=settle(ledger)
        for actual in new_scores:
            ledger.record(h["observe_action_index"],actual.target_id,actual.factor,actual.score,now,end)
        after=settle(ledger)
        delta={key:after[key]-before[key] for key in before}
        assert abs(delta["science"]-tiny["components"]["sum_best_scores"])<1e-6
        assert delta["required"]==delta["uniformity"]==0
        ledger_audits.append(dict(endpoint=endpoint,before=before,after=after,delta=delta))
    return dict(capture_source=str(cap_path),capture_sha256=hashlib.sha256(cap_path.read_bytes()).hexdigest(),
        prefix_steps=step+1,now_utc=fmt(now),night_end_utc=fmt(end),observe_rank=h["observe_action_index"],
        actual_seconds=int((end-now).total_seconds()),original_action=old,candidate=candidate,
        targets=selected,public_previous_best_scores={t["target_id"]:best.get(t["target_id"],0) for t in selected},
        conditional_synthetic_weather={"seeing_arcsec":1.5,"transparency":1.,"sky_quality":1.,"instrument_efficiency":1.},
        conditional_science_delta=tiny["components"]["sum_best_scores"],
        conditional_factors={r["target_id"]:float(r["factor"]) for r in rows},
        actual_weather_evaluated=False,full_season_replayed=False,
        full_ledger_delta_under_no_future_loss=tiny["components"]["sum_best_scores"],
        score_implied_endpoint_ledger_audits=ledger_audits,
        public_issued_request_count=len(issued_requests),public_resync_count=len(resyncs),
        actual_factor_columns_or_teacher_labels_read=False)


def boundary_limits():
    a=utc("2026-11-03T00:30:00Z")
    early=a-timedelta(seconds=2700)
    rising=target_at("SYN_RISING",31,90,a)
    ss=slots(a-timedelta(seconds=86400),a-timedelta(seconds=57600),"N_PREV",False)+slots(a,a+timedelta(seconds=900),"N_NEXT")
    sc=scenario("altitude_padding",[rising],ss)
    pre=official_run("altitude_padding_pre",sc,[{"action":"wait","until_utc":fmt(early)},
        action_for([rising],early,rising["ra_deg"],rising["dec_deg"],3600,"BACKUP")])
    late=official_run("altitude_padding_late",sc,[{"action":"wait","until_utc":fmt(a)},
        action_for([rising],a,rising["ra_deg"],rising["dec_deg"],900,"BACKUP")])
    assert pre["components"]["sum_best_scores"]==0 and late["components"]["sum_best_scores"]>0
    # A positive-science short tail can worsen the final Jain term.
    tail=utc("2026-11-03T08:29:30Z")
    begin=tail-timedelta(seconds=1800)
    ra,dec=altaz_to_radec(70,30,tail,lat,lon)
    extra=.1 if (ra%10)<9.8 else -.1
    ts=[dict(target_at("SYN_A1",70,30,tail,flux=2.)),
        dict(target_at("SYN_A2",70,30,tail,flux=20.)),
        dict(target_at("SYN_B1",70,30,tail,flux=2.)),
        dict(target_at("SYN_B2",70,30,tail,flux=2.))]
    ts[1]["ra_deg"]=ra+extra
    ts[2]["ra_deg"]=ts[3]["ra_deg"]=(ra+20)%360
    scj=scenario("jain_tail",ts,slots(begin,tail+timedelta(seconds=30)))
    prefix=[action_for([ts[0]],begin,ts[0]["ra_deg"],ts[0]["dec_deg"],900,"DARK"),
            action_for([ts[2]],begin+timedelta(seconds=900),ts[2]["ra_deg"],ts[2]["dec_deg"],900,"DARK")]
    rw=official_run("jain_tail_wait",scj,prefix+[{"action":"wait","until_utc":fmt(scj.survey_end)}])
    ro=official_run("jain_tail_observe",scj,prefix+[action_for([ts[1]],tail,ts[1]["ra_deg"],ts[1]["dec_deg"],60,"DARK")])
    assert ro["components"]["sum_best_scores"]>rw["components"]["sum_best_scores"] and ro["total"]<rw["total"]
    # Added observe changes N and moves the retrospective deletion window.
    start=utc("2026-11-03T06:00:00Z")
    end=start+timedelta(seconds=1200)
    trigger=end+timedelta(seconds=1200)
    high=target_at("SYN_LOSS_HIGH",70,30,start,flux=2.)
    stress=[{"event_id":"DL_SYN","event_type":"data_loss","trigger_mode":"fixed_date",
        "trigger_ref":fmt(trigger),"window_start_fraction":"0.4","window_end_fraction":"0.6",
        "window_max_fraction":"0.2"}]
    scl=scenario("tail_loss_rank",[high],slots(start,end,"N_FIRST")+slots(trigger,trigger+timedelta(seconds=60),"N_SECOND"),stress=stress)
    empty=lambda d:{"action":"observe","pointing":{"alt_deg":70.,"az_deg":30.},"assignments":{},"duration_seconds":d,"program":"BACKUP"}
    prefix=[empty(60),empty(60),action_for([high],start+timedelta(seconds=120),high["ra_deg"],high["dec_deg"],900,"DARK"),empty(60),
            {"action":"wait","until_utc":fmt(end-timedelta(seconds=30))}]
    base=official_run("loss_tail_wait",scl,prefix+[{"action":"wait","until_utc":fmt(trigger)}])
    more=official_run("loss_tail_observe",scl,prefix+[empty(60),{"action":"wait","until_utc":fmt(trigger)}])
    assert more["total"]<base["total"]
    # A trigger during the final tail is never processed: after end==survey_end
    # there is no next while iteration/decision. The final settlement has no
    # separate data-loss trigger. Test both action kinds with the actual runner.
    terminal_stress=[dict(stress[0],trigger_ref=fmt(end-timedelta(seconds=15)))]
    sct=scenario("terminal_pending_loss",[high],slots(start,end,"N_FIRST"),stress=terminal_stress)
    tw=official_run("terminal_pending_loss_wait",sct,prefix+[{"action":"wait","until_utc":fmt(end)}])
    to=official_run("terminal_pending_loss_observe",sct,prefix+[empty(60)])
    assert tw["invalidations"]==to["invalidations"]==[] and tw["total"]==to["total"]
    return dict(rising_pre=pre,rising_late=late,
        rising_min_pre=min_altitude_during(rising["ra_deg"],rising["dec_deg"],early,a+timedelta(seconds=900),{"site":site}),
        rising_min_late=min_altitude_during(rising["ra_deg"],rising["dec_deg"],a,a+timedelta(seconds=900),{"site":site}),
        jain_tail_wait=rw,jain_tail_observe=ro,jain_tail_delta=round(ro["total"]-rw["total"],6),
        loss_wait=base,loss_extra_observe=more,loss_rank_delta=round(more["total"]-base["total"],6),
        terminal_pending_loss_wait=tw,terminal_pending_loss_observe=to,
        terminal_added_rank_has_no_history_effect=True)


def main():
    started=time.monotonic()
    baseline=Path("/Users/kamico/Downloads/observer_request_exact_cache.zip")
    with zipfile.ZipFile(baseline) as z:
        policy=z.read("policy.py").decode()
        files=len(z.namelist())
    result=dict(baseline_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(),baseline_files=files,
        baseline_gap_guard="if night < 0:" in policy,
        baseline_tail_guard="if remaining < p.tmin:" in policy,
        gap=gap_tests(),tail=tail_tests(),public_prefix=public_prefix_opportunity(),limits=boundary_limits())
    result["elapsed_seconds"]=time.monotonic()-started
    (OUT/"summary.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"gap_same_center_delta":result["gap"]["orientation_pre"]["total"]-result["gap"]["orientation_late_same_center"]["total"],
        "tail_delta":result["tail"]["tail_increment"],"public_conditional_delta":result["public_prefix"]["conditional_science_delta"],
        "seconds":result["elapsed_seconds"]},indent=2))


if __name__=="__main__":
    main()
