"""Read ONLY L1/L2 members from the accepted fit/validation archive.

Descriptive causal-training diagnostics; no fitting, runner, remote operation,
actor/source mutation or L3/L4 member extraction. Every payload read is logged.
"""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
from collections import Counter
from datetime import datetime
import numpy as np

FORMAL=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(FORMAL))
sys.path.insert(0,str(FORMAL/"upstream/gosim-observer-examples/runner"))
from research.structured_student_features import build_public_features, canonical_action, utc
from challenge.v4_fiber_map import altaz_to_radec

OUT=Path(__file__).resolve().parent
ARCHIVE=FORMAL/"results/structured_student_dataset_20261004/actual/fit_validation.tar.gz"
EPS=1e-6
COMPONENTS=("sum_best_scores","required_penalty","uniformity_penalty","observation_request_reward","report_settlement")
LOCKED=sorted((FORMAL/"research").glob("structured_student*.py"))+sorted((FORMAL/"research").glob("policy_iteration*.py"))
LOCKED+=sorted((FORMAL/"upstream/gosim-observer-examples/runner/challenge").glob("v4_*.py"))


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def source_hashes(): return {str(p.relative_to(FORMAL)):sha(p) for p in LOCKED}
def sign(v): return "positive" if v>EPS else "negative" if v<-EPS else "tie"
def stats(values):
    v=np.asarray(values,float)
    if not len(v): return dict(count=0)
    return dict(count=len(v),mean=float(v.mean()),median=float(np.median(v)),minimum=float(v.min()),maximum=float(v.max()),
                q25=float(np.quantile(v,.25)),q75=float(np.quantile(v,.75)),sum=float(v.sum()))
def angle(p,q):
    a,z=np.radians([p["alt_deg"],p["az_deg"]]); b,w=np.radians([q["alt_deg"],q["az_deg"]])
    return float(np.degrees(np.arccos(np.clip(np.sin(a)*np.sin(b)+np.cos(a)*np.cos(b)*np.cos(z-w),-1,1))))


def main():
    locked=source_hashes()
    reads=[]
    groups=[]
    inits={}
    with tarfile.open(ARCHIVE,"r:gz") as archive:
        def read(name):
            allowed=(name in ("public/L1_initialize_public.json","public/L2_initialize_public.json")
                     or name.startswith("groups/L1_") or name.startswith("groups/L2_"))
            if not allowed: raise RuntimeError("Refuse non-training payload: "+name)
            payload=archive.extractfile(name).read()
            reads.append(dict(member=name,sha256=hashlib.sha256(payload).hexdigest(),bytes=len(payload)))
            return payload
        for card in ("L1","L2"):
            initial=json.loads(read(f"public/{card}_initialize_public.json"))
            inits[card]=initial.get("payload",initial)
        # Header enumeration is not a payload read; do not open manifest/outcomes/L3.
        names=sorted(n for n in archive.getnames() if (n.startswith("groups/L1_") or n.startswith("groups/L2_")) and n.endswith("/pair_audit.json"))
        for name in names:
            root=name.rsplit("/",1)[0]
            audit=json.loads(read(name))
            capture=json.loads(read(root+"/control/public_capture/capture.json"))
            availability=json.loads(read(root+"/availability.json"))
            blob=read(root+"/control/public_capture/public_features.npz")
            with np.load(io.BytesIO(blob),allow_pickle=False) as z:
                arrays={k:z[k].copy() for k in z.files}
            assert audit["card"] in ("L1","L2") and audit["split"]=="train" and audit["passed"]
            assert capture["feature_blob_sha256"]==hashlib.sha256(blob).hexdigest()
            assert all(audit["gates"].values())
            assert set(audit["available_cases"])==set(capture["actions"])==set(availability["available_cases"])
            f=build_public_features(inits[audit["card"]],capture,arrays)
            groups.append(dict(audit=audit,capture=capture,features=f,card=audit["card"],group_id=audit["group_id"]))
    assert len(groups)==32 and Counter(g["card"] for g in groups)==Counter({"L1":16,"L2":16})
    rows=[]
    summaries=[]
    for g in groups:
        a,c,f=g["audit"],g["capture"],g["features"]
        features={x.name:x for x in f.actions}
        control=c["actions"]["control"]
        control_ids=set(control["assignments"].values())
        table=inits[g["card"]]["targets"]
        col=table["columns"]
        weights={str(v[col.index("target_id")]):float(v[col.index("science_weight")]) for v in table["rows"]}
        scoring=inits[g["card"]]["scoring"]["program"]
        multiplier=lambda declared,actual: scoring["multipliers"][declared] if declared==actual else scoring["mismatch_multiplier"]
        req=c["snapshot"].get("active_requests",[])
        start=utc(inits[g["card"]]["survey"]["start_utc"]); end=utc(inits[g["card"]]["survey"]["end_utc"])
        season=(utc(c["now_utc"])-start).total_seconds()/(end-start).total_seconds()
        for label in a["labels"]:
            case=label["case"]
            action=c["actions"][case]
            assert canonical_action(action)==canonical_action(label["action_pair"][1])
            assert canonical_action(control)==canonical_action(label["action_pair"][0])
            value=float(label["advantage"])
            comps={k:float(label["component_delta"][k]) for k in COMPONENTS}
            assert abs(value-sum(comps.values()))<1e-5
            ids=set(action["assignments"].values())
            immediate=features[case].coarse_utility-features["control"].coarse_utility
            rate=features[case].gain_per_second-features["control"].gain_per_second
            item=dict(card=g["card"],group_id=g["group_id"],rank=a["rank"],season_fraction=season,case=case,advantage=value,
                sign=sign(value),components=comps,immediate_coarse_delta=immediate,immediate_rate_delta=rate,
                continuation_plus_physics_residual=value-immediate,pointing_separation_deg=angle(control["pointing"],action["pointing"]),
                target_jaccard=len(ids&control_ids)/len(ids|control_ids),targets_added=len(ids-control_ids),targets_removed=len(control_ids-ids),
                assignment_count=len(ids),duration=action["duration_seconds"],duration_ratio=action["duration_seconds"]/control["duration_seconds"],
                program=action["program"],native_utility_available=features[case].native_utility is not None,
                aligned_action_divergences=label.get("aligned_action_divergences"),observe_count_delta=label["branch_observe_count"]-label["baseline_observe_count"],
                action_count_delta=label["action_count_delta"],terminal_required_missing=label["counts"]["required_missing"],
                terminal_requests_completed=label["counts"]["observation_requests_completed"],active_requests=len(req),
                active_requests_unfinished=sum(r["remaining_count"]>0 for r in req),
                notices=[n["event_kind"] for n in c.get("notices",[])],C=c["C"],E=c["E"])
            if case=="program":
                assert {k:v for k,v in action.items() if k!="program"}=={k:v for k,v in control.items() if k!="program"}
                diffs=[multiplier(action["program"],b)-multiplier(control["program"],b) for b in ("DARK","BRIGHT","BACKUP")]
                total_weight=sum(weights[t] for t in control_ids)
                lo,hi=min(diffs)*total_weight,max(diffs)*total_weight
                item.update(frozen_physical_suffix_science_delta_lower=lo,frozen_physical_suffix_science_delta_upper=hi,
                    science_outside_frozen_suffix_bound=not lo-1e-5<=comps["sum_best_scores"]<=hi+1e-5,
                    factor_dependent_jain_changed=abs(comps["uniformity_penalty"])>EPS,
                    minimum_science_suffix_effect=max(0,lo-comps["sum_best_scores"],comps["sum_best_scores"]-hi))
            rows.append(item)
        local=[r for r in rows if r["group_id"]==g["group_id"]]
        best=max(local,key=lambda r:r["advantage"])
        best_value=max(0,best["advantage"])
        best_case=best["case"] if best_value>EPS else "control"
        alternatives={"control":0.,**{r["case"]:r["advantage"] for r in local}}
        summaries.append(dict(card=g["card"],group_id=g["group_id"],rank=a["rank"],season_fraction=season,
            best_case=best_case,best_advantage=best_value,best_components=best["components"] if best_case!="control" else {k:0 for k in COMPONENTS},
            advantages=alternatives,baseline_total=a["baseline_total"],active_requests=len(req),
            active_requests_unfinished=sum(r["remaining_count"]>0 for r in req),notices=[n["event_kind"] for n in c.get("notices",[])],
            cases=len(c["actions"]),distinct_pointings=len({json.dumps(x["pointing"],sort_keys=True) for x in c["actions"].values()}),
            control_program=control["program"],control_duration=control["duration_seconds"],control_assignments=len(control_ids),
            prefix_hash=c["prefix_sha256"],public_history_rows=len(c["public_history"])))
    by_case={case:dict(advantages=stats([r["advantage"] for r in rows if r["case"]==case]),
        signs=dict(Counter(r["sign"] for r in rows if r["case"]==case)),
        best_states=sum(s["best_case"]==case for s in summaries),
        geometry=stats([r["pointing_separation_deg"] for r in rows if r["case"]==case]),
        target_jaccard=stats([r["target_jaccard"] for r in rows if r["case"]==case]),
        duration_ratio=stats([r["duration_ratio"] for r in rows if r["case"]==case])) for case in ("field","short","long","program")}
    highest=sorted(summaries,key=lambda s:s["best_advantage"],reverse=True)
    oracle=sum(s["best_advantage"] for s in summaries)
    top_fracs={str(k):sum(s["best_advantage"] for s in highest[:k])/oracle if oracle else 0. for k in (1,3,5,8,16)}
    card_stats={card:dict(states=sum(s["card"]==card for s in summaries),
        signs=dict(Counter(r["sign"] for r in rows if r["card"]==card)),
        best_cases=dict(Counter(s["best_case"] for s in summaries if s["card"]==card)),
        best_advantage=stats([s["best_advantage"] for s in summaries if s["card"]==card]),
        season_fraction=stats([s["season_fraction"] for s in summaries if s["card"]==card])) for card in ("L1","L2")}
    behavior={}
    for card in ("L1","L2"):
        latest=max((g for g in groups if g["card"]==card),key=lambda g:g["audit"]["rank"])
        history=latest["capture"]["public_history"]
        actions=[h["action"] for h in history if h.get("action")]
        observed=[x for x in actions if x["action"]=="observe"]
        duration_counts=Counter(x["duration_seconds"] for x in observed)
        observed_target_union=set(t for x in observed for t in x["assignments"].values())
        catalog=inits[card]["targets"]["rows"]
        baselines=[]
        for g in groups:
            if g["card"]!=card: continue
            earlier=g["capture"]["public_history"]
            # History at each cut excludes that cut's prospective current action.
            n=min(len(earlier),len(history))
            baselines.append(all(canonical_action(earlier[i])==canonical_action(history[i]) for i in range(n)))
        behavior[card]=dict(history_rows=len(history),action_kinds=dict(Counter(x["action"] for x in actions)),
            observed_actions=len(observed),unique_exact_observe_actions=len({canonical_action(x) for x in observed}),
            programs=dict(Counter(x["program"] for x in observed)),durations=stats([x["duration_seconds"] for x in observed]),
            distinct_durations=len(duration_counts),top10_durations=duration_counts.most_common(10),
            top5_duration_frequency=sum(v for _,v in duration_counts.most_common(5))/len(observed),
            assignment_counts=stats([len(x["assignments"]) for x in observed]),catalog_targets=len(catalog),
            prefix_assigned_distinct_targets=len(observed_target_union),all_cut_public_histories_are_prefixes=all(baselines))
    signs=Counter(r["sign"] for r in rows)
    flips=[r for r in rows if sign(r["immediate_coarse_delta"])!="tie" and r["sign"]!="tie" and sign(r["immediate_coarse_delta"])!=r["sign"]]
    active=Counter((s["active_requests"]>0,s["active_requests_unfinished"]>0) for s in summaries)
    components={k:dict(nonzero=sum(abs(r["components"][k])>EPS for r in rows),
        positive=sum(r["components"][k]>EPS for r in rows),negative=sum(r["components"][k]<-EPS for r in rows),
        all_branch_deltas=stats([r["components"][k] for r in rows]),
        oracle_selected_sum=sum(s["best_components"][k] for s in summaries)) for k in COMPONENTS}
    grand_mean=np.mean([r["advantage"] for r in rows]); total_variance=sum((r["advantage"]-grand_mean)**2 for r in rows)
    between=0.
    for s in summaries:
        values=[v for k,v in s["advantages"].items() if k!="control"]
        between+=len(values)*(np.mean(values)-grand_mean)**2
    program_rows=[r for r in rows if r["case"]=="program"]
    common_modes={card:dict(all_alternatives_positive=sum(all(v>EPS for k,v in s["advantages"].items() if k!="control") for s in summaries if s["card"]==card),
        all_alternatives_nonpositive=sum(all(v<=EPS for k,v in s["advantages"].items() if k!="control") for s in summaries if s["card"]==card),
        mean_alternative_effect=stats([np.mean([v for k,v in s["advantages"].items() if k!="control"]) for s in summaries if s["card"]==card])) for card in ("L1","L2")}
    assert source_hashes()==locked
    report=dict(schema="train-only-causal-learning-signal-diagnostic-v1",archive_sha256=sha(ARCHIVE),
        diagnostic_source_sha256=sha(Path(__file__)),read_members=reads,
        source_sha256=locked,group_count=len(groups),label_count=len(rows),signs=dict(signs),card_statistics=card_stats,
        by_case=by_case,best_cases=dict(Counter(s["best_case"] for s in summaries)),
        oracle_single_intervention_gain_sum=oracle,oracle_top_state_share=top_fracs,top_training_states=highest[:10],
        components=components,behavior_prefix=behavior,active_request_group_count=sum(s["active_requests"]>0 for s in summaries),
        unfinished_request_group_count=sum(s["active_requests_unfinished"]>0 for s in summaries),
        unique_prefix_count=len({(s["card"],s["prefix_hash"]) for s in summaries}),
        native_utility_available_alternative_count=sum(r["native_utility_available"] for r in rows),
        immediate_coarse_sign_reversals=len(flips),coarse_sign_reversal_examples=sorted(flips,key=lambda r:abs(r["advantage"]),reverse=True)[:10],
        aligned_action_divergences=stats([r["aligned_action_divergences"] for r in rows]),
        zero_suffix_divergences=sum(r["aligned_action_divergences"]==0 for r in rows),
        state_common_mode_variance_share=float(between/total_variance),common_modes=common_modes,
        program_only_physical_intervention=dict(groups=len(program_rows),
            science_bound_violations=sum(r["science_outside_frozen_suffix_bound"] for r in program_rows),
            jain_changes=sum(r["factor_dependent_jain_changed"] for r in program_rows),
            minimum_science_suffix_effect=stats([r["minimum_science_suffix_effect"] for r in program_rows]),
            examples=sorted(program_rows,key=lambda r:r["minimum_science_suffix_effect"],reverse=True)[:5],
            proof="Only declared program changes. Same pointing/duration/assignments gives identical raw factors; fixed physical suffix has identical max-factor/REQ/Jain. Science max is 1-Lipschitz, so its change lies between sum(w)*min_band(mult_alt-mult_control) and corresponding max. Violations prove downstream effects, not their cause or expected benefit."),
        observe_count_delta=stats([r["observe_count_delta"] for r in rows]),
        scope="L1/L2 training labels only. 32 nested prefixes of two fixed natural policies/worlds; correlated candidates and states. Oracle sums across counterfactual single-state branches are not an achievable whole-policy gain.")
    (OUT/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    (OUT/"training_branch_rows.json").write_text(json.dumps(rows,indent=2)+"\n")
    (OUT/"training_state_rows.json").write_text(json.dumps(summaries,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ("group_count","label_count","signs","best_cases","oracle_single_intervention_gain_sum","oracle_top_state_share","active_request_group_count","unfinished_request_group_count","immediate_coarse_sign_reversals","components","behavior_prefix")},indent=2))


if __name__=="__main__": main()
