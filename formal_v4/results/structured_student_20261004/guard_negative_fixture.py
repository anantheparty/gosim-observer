"""One bounded acceptance-guard check, using fabricated values in temporary files.

No actual teacher label file is read and no fitting/model optimization is run.
Invoke from formal_v4 with PYTHONPATH=. in the existing NumPy environment.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile

import numpy as np

from research.structured_student_audit import synthetic_public
from research.structured_student_features import COMPONENTS, SchemaError, canonical_action, sha
from research.structured_student_train import (AUDIT_SCHEMA, MANIFEST_SCHEMA, REQUIRED_V2_GATES,
                                              _read_json, accepted_groups, pair_loss)


def run_fixture():
    initial,capture,arrays=synthetic_public()
    initial["task_card"]={"card_id":"L1"}
    capture["prefix_sha256"]="fabricated_fixture_public_prefix"
    capture["case"]="control"
    capture["baseline_action"]=copy.deepcopy(capture["actions"]["control"])
    capture["selected_action"]=copy.deepcopy(capture["actions"]["control"])
    audit=dict(schema=AUDIT_SCHEMA,passed=True,archive_complete=True,card="L1",rank=3,group_id="synthetic_fixture_L1",split="train",
               baseline_total=100.,trainable=True,trainable_reason="complete_available_full_season_pairs",gates={name:True for name in REQUIRED_V2_GATES},available_cases=["control","long"],absent_cases=[],
               labels=[dict(case="long",valid_full_season_pair=True,baseline_total=100.,branch_total=101.,advantage=1.,
                            component_delta={name:1. if i==0 else 0. for i,name in enumerate(COMPONENTS)},
                            action_pair=[capture["actions"]["control"],capture["actions"]["long"]])])
    checked=[]
    with tempfile.TemporaryDirectory(prefix="structured-student-guard-fixture-") as directory:
        root=Path(directory)
        paths={name:root/(name+suffix) for name,suffix in (("capture",".json"),("public_initial",".json"),("public_features",".npz"),("pair_audit",".json"),("availability",".json"))}
        np.savez_compressed(paths["public_features"],**arrays)
        capture["feature_blob_sha256"]=sha(paths["public_features"])
        paths["public_initial"].write_text(json.dumps(initial))

        def write(cap,pair,availability_mutation=None):
            paths["capture"].write_text(json.dumps(cap,separators=(",",":")))
            snapshot={k:v for k,v in cap["snapshot"].items() if k!="wallclock"}
            state={k:v for k,v in cap.items() if k not in ("case","selected_action")}
            state["snapshot"]=snapshot
            availability=dict(schema="policy-iteration-public-availability-v1",planned_group_id="synthetic_fixture_L1",card="L1",rank=3,
                              source_lock_sha256="fabricated_fixture_source",frozen_before_terminal=True,control_was_running=True,
                              available_cases=pair["available_cases"],absent_cases=[],action_hashes={name:canonical_action(action) for name,action in cap["actions"].items()},
                              capture_sha256=sha(paths["capture"]),feature_blob_sha256=sha(paths["public_features"]),
                              cut_snapshot_sha256=canonical_action(snapshot),public_capture_state_sha256=canonical_action(state))
            if availability_mutation:
                availability_mutation(availability)
            paths["availability"].write_text(json.dumps(availability))
            pair["availability_sha256"]=sha(paths["availability"])
            paths["pair_audit"].write_text(json.dumps(pair))
            record=dict(group_id="synthetic_fixture_L1",card="L1",**{name:str(path) for name,path in paths.items()},
                        sha256={name:sha(path) for name,path in paths.items()})
            manifest=root/"accepted_synthetic_fixture.json"
            manifest.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA,accepted=True,
                                acceptance_note="Fabricated guard fixture only; never a real accepted teacher dataset",groups=[record])))
            return manifest

        def reject(name,mutate_cap=None,mutate_pair=None,mutate_availability=None):
            cap,pair=copy.deepcopy(capture),copy.deepcopy(audit)
            if mutate_cap:mutate_cap(cap)
            if mutate_pair:mutate_pair(pair)
            manifest=write(cap,pair,mutate_availability)
            try:
                accepted_groups(manifest)
            except SchemaError as error:
                checked.append(dict(case=name,rejected=True,reason=str(error)))
            else:
                raise AssertionError("Guard defect was accepted: "+name)

        reject("duplicate_label_case",mutate_pair=lambda a:a["labels"].append(copy.deepcopy(a["labels"][0])))
        reject("duplicate_canonical_action",mutate_cap=lambda c:c["actions"].__setitem__("long",copy.deepcopy(c["actions"]["control"])))
        def conflicting_baseline(a):
            a["labels"][0].update(baseline_total=200.,branch_total=201.)
        reject("label_baseline_differs_from_control",mutate_pair=conflicting_baseline)
        reject("declared_branch_delta_inconsistent",mutate_pair=lambda a:a["labels"][0].__setitem__("branch_total",102.))
        reject("duplicate_control_inventory",mutate_pair=lambda a:a["available_cases"].append("control"))
        reject("missing_v2_inventory_gate",mutate_pair=lambda a:a["gates"].pop("complete_declared_inventory"))
        reject("v1_audit_not_accepted",mutate_pair=lambda a:a.__setitem__("schema","policy-iteration-full-season-pair-audit-v1"))
        reject("incomplete_episode_archives",mutate_pair=lambda a:a.__setitem__("archive_complete",False))
        reject("availability_action_hash_mismatch",mutate_availability=lambda a:a["action_hashes"].__setitem__("long","fabricated_wrong_hash"))
        cap,pair=copy.deepcopy(capture),copy.deepcopy(audit)
        cap["actions"]={"control":cap["actions"]["control"]}
        pair.update(available_cases=["control"],labels=[],trainable=False,trainable_reason="control_only_no_distinct_alternative")
        records,provenance=accepted_groups(write(cap,pair))
        assert len(records)==1 and records[0]["trainable"] is False and records[0]["labels"].shape==(1,6)
        assert provenance["control_only_availability_record_count"]==1 and provenance["trainable_group_count"]==0
        checked.append(dict(case="control_only_preserved_without_pair_training",preserved=True,trainable=False))
        for count in (0,1):
            try:
                pair_loss(np.zeros((count,6)),np.zeros((count,6)))
            except SchemaError:
                checked.append(dict(case=f"pair_loss_{count}_actions",rejected=True))
            else:raise AssertionError("Empty/single-control pair loss was accepted")
        duplicate_json=root/"duplicate_action_keys.json"
        duplicate_json.write_text('{"actions":{"control":{},"control":{}}}')
        try:_read_json(duplicate_json)
        except SchemaError:checked.append(dict(case="duplicate_json_control_key",rejected=True))
        else:raise AssertionError("Duplicate raw control key was accepted")
    return dict(schema="structured-student-guard-negative-fixture-v1",passed=True,synthetic_only=True,
                actual_teacher_label_files_read=0,optimization_steps=0,seasons_launched=0,checks=checked)


if __name__=="__main__":
    result=run_fixture()
    output=Path(__file__).with_name("guard_negative_fixture_result.json")
    output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
