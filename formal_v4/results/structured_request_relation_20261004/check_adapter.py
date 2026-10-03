"""Small representation checks against the previously fixed synthetic fixture.

No teacher labels, training, runner calls, remote operations, or new seasons.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import sys
import types
import numpy as np

FORMAL=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(FORMAL))
from research.structured_request_relation import build_request_relations, SchemaError
from research.structured_student_features import build_public_features

OUT=Path(__file__).resolve().parent
FIXTURE=FORMAL/"results/cold_learning_signal_20261004/synthetic_inputs.json"
LOCKED=sorted((FORMAL/"research").glob("policy_iteration*.py"))
LOCKED+=sorted((FORMAL/"research").glob("structured_student*.py"))
LOCKED+=list((FORMAL/"upstream/gosim-observer-examples/runner/challenge").glob("v4_*.py"))


def hashes(paths):
    return {str(p.relative_to(FORMAL)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def comparable(rel,values):
    pooled=rel.pool_members(values,action_name="control")
    order=np.argsort(rel.request_ids)
    return rel.request_nodes[order],pooled[order]


def fixed_pi_reward(rel,name):
    support=np.array([float(t=="b") for t in rel.target_ids])
    counts=rel.conditional_completion_counts(name,support)
    return float(np.sum((counts[:,:3].sum(1)>=rel.request_nodes[:,0])*rel.request_nodes[:,5]))


def main():
    before=hashes(LOCKED)
    fixture=json.loads(FIXTURE.read_text())
    initial,captures=fixture["initial"],fixture["captures"]
    relations={w:build_request_relations(initial,c) for w,c in captures.items()}
    checks={}
    checks["same_request_nodes"]=np.array_equal(relations["ab_cd"].request_nodes,relations["ad_bc"].request_nodes)
    checks["different_request_member_joins"]=not np.array_equal(relations["ab_cd"].member_index,relations["ad_bc"].member_index)
    rewards={w:{a:fixed_pi_reward(r,a) for a in r.actions} for w,r in relations.items()}
    checks["same_fixed_collision_is_distinguished"]=(rewards=={"ab_cd":{"control":100.,"field":0.},"ad_bc":{"control":0.,"field":100.}})
    cap=captures["ab_cd"]
    rel=relations["ab_cd"]
    # Numeric target values represent public target attributes; IDs stay joins.
    cols=initial["targets"]["columns"]
    table={str(row[cols.index("target_id")]):row for row in initial["targets"]["rows"]}
    values=np.array([[table[t][cols.index(k)] for k in ("ra_deg","dec_deg","feature_flux","science_weight")] for t in rel.target_ids])
    original=comparable(rel,values)
    permuted=copy.deepcopy(cap)
    permuted["target_ids"]=list(reversed(permuted["target_ids"]))
    permuted["snapshot"]["active_requests"].reverse()
    for r in permuted["snapshot"]["active_requests"]:
        r["target_ids"].reverse()
    perm_init=copy.deepcopy(initial)
    perm_init["targets"]["rows"].reverse()
    perm_rel=build_request_relations(perm_init,permuted)
    perm_values=np.array([values[rel.target_ids.index(t)] for t in perm_rel.target_ids])
    changed=comparable(perm_rel,perm_values)
    checks["target_request_member_reorder_preserves_local_pool"]=all(np.allclose(a,b,rtol=0,atol=1e-12) for a,b in zip(original,changed))
    checks["reorder_preserves_quota_semantics"]=(fixed_pi_reward(perm_rel,"control")==100. and fixed_pi_reward(perm_rel,"field")==0.)
    # Rename every ID to opaque arbitrary text, maintaining only joins.
    renamed=copy.deepcopy(cap)
    rename={t:"opaque-key-"+str(31-i*7) for i,t in enumerate(rel.target_ids)}
    renamed["target_ids"]=[rename[t] for t in renamed["target_ids"]]
    renamed_init=copy.deepcopy(initial)
    for row in renamed_init["targets"]["rows"]:
        row[cols.index("target_id")]=rename[row[cols.index("target_id")]]
    for i,r in enumerate(renamed["snapshot"]["active_requests"]):
        r["request_id"]="opaque-request-"+str(999-i*123)
        r["target_ids"]=[rename[t] for t in r["target_ids"]]
        r["completed_target_ids"]=[rename[t] for t in r["completed_target_ids"]]
    for action in renamed["actions"].values():
        action["assignments"]={f:rename[t] for f,t in action["assignments"].items()}
    renamed["candidate_predictions"]={a:{rename[t]:p for t,p in predictions.items()} for a,predictions in renamed["candidate_predictions"].items()}
    ren_rel=build_request_relations(renamed_init,renamed)
    checks["ids_have_only_join_semantics"]=(np.array_equal(rel.request_nodes,ren_rel.request_nodes)
        and np.array_equal(rel.member_index,ren_rel.member_index) and np.array_equal(rel.member_features,ren_rel.member_features)
        and all(np.array_equal(rel.actions[a].member_features,ren_rel.actions[a].member_features)
                and np.array_equal(rel.actions[a].request_features,ren_rel.actions[a].request_features) for a in rel.actions))
    empty=copy.deepcopy(cap)
    empty["rank"]=0
    empty["public_history"]=[]
    empty["snapshot"]["observe_action_index"]=0
    empty["snapshot"]["last_result"]=None
    # No ledger parameter is needed for active request nodes at rank0.
    empty_rel=build_request_relations(initial,empty)
    checks["empty_ledger_with_active_requests"]=(empty_rel.request_nodes.shape==(2,8) and empty_rel.member_index.shape==(4,2))
    empty["snapshot"]["active_requests"]=[]
    no_req=build_request_relations(initial,empty)
    checks["no_requests_empty_ledger"]=(no_req.request_nodes.shape==(0,8) and no_req.member_index.shape==(0,2)
        and no_req.member_features.shape==(0,1) and no_req.pool_members(values,action_name="control").shape==(0,10)
        and no_req.conditional_completion_counts("control",np.zeros(4)).shape==(0,4))
    # Reproduce the old adapter's rank0 exception and validate ONLY the proposed
    # one-keyword change in an isolated in-memory module; no source file edited.
    with np.load(FIXTURE.parent/"synthetic_source_arrays.npz") as archive:
        raw={k:archive[k].copy() for k in archive.files}
    for k in ("ledger_rank","ledger_target","ledger_score","ledger_factor_estimate","ledger_lower","ledger_valid"):
        raw[k]=raw[k][:0]
    old_empty=copy.deepcopy(cap)
    old_empty.update(rank=0,public_history=[])
    old_empty["snapshot"].update(observe_action_index=0,last_result=None)
    try:
        build_public_features(initial,old_empty,raw)
        checks["original_empty_ledger_dtype_exception_reproduced"]=False
    except TypeError as error:
        checks["original_empty_ledger_dtype_exception_reproduced"]="bitwise_and" in str(error)
    source_path=FORMAL/"research/structured_student_features.py"
    text=source_path.read_text()
    old_line="eligible = np.array([issued <= exposure_times[int(r)][0] and exposure_times[int(r)][1] <= deadline for r in lr]) & lv"
    assert text.count(old_line)==1
    new_line=old_line.replace("for r in lr])","for r in lr], dtype=bool)")
    isolated=types.ModuleType("_request_empty_ledger_fix_probe")
    isolated.__file__=str(source_path)
    sys.modules[isolated.__name__]=isolated
    exec(compile(text.replace(old_line,new_line),str(source_path),"exec"),isolated.__dict__)
    try:
        repaired=isolated.build_public_features(initial,old_empty,raw)
        checks["one_keyword_fix_accepts_same_empty_ledger_fixture"]=(repaired.target_nodes.shape==(4,44) and len(repaired.actions)==2)
    finally:
        del sys.modules[isolated.__name__]
    # Official requests accept whole actual exposure, including night truncation.
    truncated=copy.deepcopy(initial)
    truncated["survey"]["end_utc"]="2026-11-02T00:46:00Z"
    truncated["survey"]["nights"][0]["observing_end_utc"]="2026-11-02T00:46:00Z"
    early=copy.deepcopy(cap)
    for r in early["snapshot"]["active_requests"]:
        r["deadline_utc"]="2026-11-02T00:46:00Z"
    trim=build_request_relations(truncated,early)
    checks["request_window_uses_actual_night_clipped_end"]=(np.all(trim.actions["control"].request_features[:,0]==1)
        and np.all(trim.actions["control"].request_features[:,1]==60))
    shared=copy.deepcopy(cap)
    shared["snapshot"]["active_requests"][0].update(completed_target_ids=["a"],completed_count=1,remaining_count=1)
    shared["snapshot"]["active_requests"][1]["target_ids"]=["a","c"]
    shared_rel=build_request_relations(initial,shared)
    checks["overlapping_requests_keep_distinct_public_progress"]=(shared_rel.actions["control"].request_features[:,2].tolist()==[0.,1.])
    separate=copy.deepcopy(cap)
    separate["snapshot"]["active_requests"][1]["completion_factor_threshold"]=.8
    separate_rel=build_request_relations(initial,separate)
    try:
        separate_rel.conditional_completion_counts("control",np.zeros(4))
        checks["different_request_thresholds_refuse_shared_support_vector"]=False
    except SchemaError:
        checks["different_request_thresholds_refuse_shared_support_vector"]=True
    matrix=np.zeros((2,4))
    matrix[0,1]=1.
    checks["request_specific_support_matrix_keeps_local_semantics"]=(separate_rel.conditional_completion_counts("control",matrix)[:,2].tolist()==[1.,0.])
    for case in ("unknown_member","duplicate_member","inconsistent_completion"):
        invalid=copy.deepcopy(cap)
        r=invalid["snapshot"]["active_requests"][0]
        if case=="unknown_member": r["target_ids"][0]="nonexistent"
        if case=="duplicate_member": r["target_ids"][1]=r["target_ids"][0]
        if case=="inconsistent_completion": r["completed_count"]=1
        try:
            build_request_relations(initial,invalid)
            checks[case+"_rejected"]=False
        except SchemaError:
            checks[case+"_rejected"]=True
    checks["five_student_teacher_and_runner_sources_unchanged"]=before==hashes(LOCKED)
    original_hashes=json.loads((FIXTURE.parent/"probe_report.json").read_text())["source_sha256"]
    checks["five_student_modules_match_original_collision_source_lock"]=all(before[k]==v for k,v in original_hashes.items()
        if k.startswith("research/structured_student"))
    assert all(checks.values()),checks
    report=dict(schema="structured-request-relation-representation-check-v1",checks={k:bool(v) for k,v in checks.items()},
        passed=True,fixed_collision_request_rewards=rewards,locked_source_sha256=before,
        adapter_sha256=hashes([FORMAL/"research/structured_request_relation.py"]),fixture_sha256=hashes([FIXTURE]),
        observed_public_coverage=dict(source="root public-only inspection of 64 frozen control captures; supplied by parent",
            training_groups=32,with_active_requests=4,with_remaining_request_deficit=3),
        limits="Representation checks only; request coverage is too small for generalization claims. No labels, training, new season or deployment changes.")
    (OUT/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    arrays={}
    for w,r in relations.items():
        for key in ("request_nodes","member_index","member_features"):
            arrays[w+"_"+key]=getattr(r,key)
        for a in r.actions:
            arrays[w+"_"+a+"_member_features"]=r.actions[a].member_features
            arrays[w+"_"+a+"_request_features"]=r.actions[a].request_features
    np.savez_compressed(OUT/"collision_relation_outputs.npz",**arrays)
    print(json.dumps(dict(passed=True,checks=len(checks),collision_rewards=rewards),indent=2))


if __name__=="__main__": main()
