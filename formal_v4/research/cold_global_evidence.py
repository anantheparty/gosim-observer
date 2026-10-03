#!/usr/bin/env python3
"""Reproducible checks and concise evidence for cold_global_search.

Reads only local public truth, own experimental output, and own cloud score files.
No environment secrets, remote service calls, or practice-card truth are used.
"""
import csv
import json
import pickle
from pathlib import Path

import numpy as np
import cold_global_search as m
from challenge.v4_scorer import WeatherTruth, score_target_exposure
from challenge.v4_fiber_map import radec_to_altaz


def verify(card):
    out=m.ROOT/"results/cold_global_search_20261003"/card
    s=m.load_scenario(m.UPSTREAM/"local-cards"/card/"config/v4_scenario.json")
    with np.load(out/"quality_oracle.npz") as data:
        q=data["quality"];edges=data["alt_edges"]
    w=WeatherTruth(s.slots,[e for e in s.events if e.event_type=="instrument_fault"])
    for f in w.faults:w.report_fault(f.actual_start_utc,s.score_config)
    rng=np.random.default_rng(12);checks=[]
    for k in rng.choice(len(s.slots),20,replace=False):
        slot=s.slots[k];visible=np.flatnonzero(edges[k].min(axis=0)>=30)
        for i in rng.choice(visible,min(len(visible),5),replace=False):
            t=s.targets[i]
            fn=lambda moment:radec_to_altaz(t["ra_deg"],t["dec_deg"],moment,s.site["latitude_deg"],s.site["longitude_deg"])
            native=score_target_exposure(t,list(w.segments(slot.start_utc,slot.end_utc)),[e for e in s.events if e.scope_type=="HORIZON_SECTOR" and e.overlaps(slot.start_utc,slot.end_utc)],w,900,1,s.score_config,slot.start_utc,fn,s.site)
            checks.append(abs(native.quality-float(q[k,i])))
    candidates=sorted(out.glob("columns*.pkl"))
    c=pickle.loads(candidates[-1].read_bytes())
    n=len(s.targets);possible=np.zeros(n+1,bool)
    np.logical_or.at(possible,c["ids"].ravel(),(c["factors"]>=.5).ravel())
    uncovered=[t["target_id"] for i,t in enumerate(s.targets) if t["required"] and not possible[i]]
    duration_counts={}
    for label in ("baseline","optimized"):
        actions=[json.loads(x) for x in (out/f"{label}_actions.jsonl").read_text().splitlines()]
        duration_counts[label]={str(d):sum(a["duration_seconds"]==d for a in actions) for d in (900,1800,2700,3600)}
    j=json.loads((out/"summary.json").read_text())
    agreement={label:abs(j[f"native_{label}"]["total"]-j[label]["score"]-j[f"native_{label}"]["components"]["report_settlement"]) for label in ("baseline","optimized")}
    return {"card":card,"quality_checks":len(checks),"quality_max_abs_error":max(checks),"quality_mean_abs_error":float(np.mean(checks)),"candidate_required_without_any_completing_column":uncovered,"candidate_pool_size":len(c["rows"]),"native_vs_model_abs_error_after_report_settlement":agreement,"duration_counts":duration_counts,"native_score_improvement":j["native_optimized"]["total"]-j["native_baseline"]["total"],"limitation":"Coverage impossibility is only for this finite candidate pool. No global upper bound or optimum is certified."}


def main():
    out=m.ROOT/"results/cold_global_search_20261003"
    data={card:verify(card) for card in ("L1","L2") if (out/card/"summary.json").exists() and "native_optimized" in json.loads((out/card/"summary.json").read_text())}
    ablation=out/"L1/ablation_single_night/summary.json"
    if ablation.exists():
        a=json.loads(ablation.read_text())
        data["L1"]["single_night_ablation"]={"seconds":a["seconds"],"iterations":a["iterations"],"single_night_native_total":a["native"]["total"],"multi_night_native_total":a["multinight_native_total"],"single_minus_multi":a["native"]["total"]-a["multinight_native_total"],"finding":"This coarse-pool equal-time experiment does not establish a benefit from multi-night destruction. Single-night throughput was substantially higher."}
    data["official_cloud_components"]={p.parent.name:json.loads(p.read_text())["components"] for p in sorted((m.ROOT/"results").glob("cloud_*_20261003/score_report.json"))}
    (out/"evidence.json").write_text(json.dumps(data,indent=2))
    print(json.dumps({k:v for k,v in data.items() if k!="official_cloud_components"},indent=2))


if __name__=="__main__":main()
