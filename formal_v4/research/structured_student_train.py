"""Groupwise raw-return advantage learning. No season runner or network calls.

Requires a separately accepted, hash-locked dataset manifest. Fits on L1/L2,
selects epochs/hyperparameters on L3, and never opens L4 labels in train mode.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from research.structured_student_features import COMPONENTS, SchemaError, build_public_features, canonical_action, load_public, sha
from research.structured_student_model import (FlatValue, StructuredValue, export_numpy,
                                              fit_normalizer, torch)


MANIFEST_SCHEMA = "structured-student-accepted-labels-v1"
AUDIT_SCHEMA = "policy-iteration-full-season-pair-audit-v2"
REQUIRED_V2_GATES = {
    "control_exists", "control_protocol", "control_ready_score", "control_ready_all_actions",
    "accelerated_control_identical_actions", "all_sources_unchanged", "all_protocol_complete",
    "all_one_capture", "all_post_feedback", "all_same_public_prefix", "all_same_public_state_features",
    "all_natural_suffix", "no_participant_truth_mount", "canonical_natural_ready_source_valid",
    "canonical_natural_rank64", "complete_declared_inventory", "distinct_declared_action_inventory",
    "availability_frozen_before_terminal", "availability_matches_actual_public_candidates",
    "strict_past_public_prefix", "all_teacher_valid", "all_same_complete_public_capture",
    "all_gate_identity_matches_plan", "all_same_predeclared_cut", "all_selected_predeclared_actions",
    "all_submitted_prefix_and_cut_actions", "source_files_unchanged", "full_inputs_unchanged",
}


def _unique_object(pairs):
    result = {}
    for name,value in pairs:
        if name in result:
            raise SchemaError("Duplicate JSON object key: " + str(name))
        result[name] = value
    return result


def _read_json(path):
    return json.loads(Path(path).read_text(),object_pairs_hook=_unique_object)


def _finite_number(value,name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value):
        raise SchemaError("Missing/non-finite declared terminal return: " + name)
    return float(value)


def _candidate_contract(capture,audit):
    """Reject ambiguity before dictionary conversion; preserve control-only inventory."""
    actions = capture.get("actions",{})
    if not isinstance(actions,dict):
        raise SchemaError("Candidate actions must be an object")
    names = list(actions)
    available = audit.get("available_cases")
    if not isinstance(available,list) or not all(isinstance(n,str) for n in available):
        raise SchemaError("Audit lacks a declared available action inventory")
    if names.count("control")!=1 or available.count("control")!=1:
        raise SchemaError("Exactly one native control is required")
    if len(available)!=len(set(available)) or len(names)!=len(available) or set(names)!=set(available):
        raise SchemaError("Declared available inventory differs from public actions")
    hashes = [canonical_action(actions[name]) for name in names]
    if len(hashes)!=len(set(hashes)):
        raise SchemaError("Distinct candidate names contain the same canonical action")
    raw_labels = audit.get("labels")
    if not isinstance(raw_labels,list) or not all(isinstance(label,dict) and isinstance(label.get("case"),str) for label in raw_labels):
        raise SchemaError("Teacher labels must be a case-record list")
    cases = [label["case"] for label in raw_labels]
    if len(cases)!=len(set(cases)):
        raise SchemaError("Duplicate teacher label case before dictionary conversion")
    if len(cases)!=len(names)-1 or set(cases)!=set(names)-{"control"}:
        raise SchemaError("Teacher labels must preserve the entire distinct candidate inventory")
    baseline = _finite_number(audit.get("baseline_total"),"audit.baseline_total")
    labels = dict(zip(cases,raw_labels))
    for name,label in labels.items():
        prior = _finite_number(label.get("baseline_total"),name+".baseline_total")
        branch = _finite_number(label.get("branch_total"),name+".branch_total")
        advantage = _finite_number(label.get("advantage"),name+".advantage")
        if abs(prior-baseline)>1e-6:
            raise SchemaError("Group labels disagree with the authoritative control baseline")
        if abs(advantage-(branch-baseline))>1e-5:
            raise SchemaError("Teacher advantage differs from declared branch/control returns")
        action_pair = label.get("action_pair",[])
        if len(action_pair)!=2 or canonical_action(action_pair[0])!=hashes[names.index("control")] or canonical_action(action_pair[1])!=hashes[names.index(name)]:
            raise SchemaError("Teacher return belongs to a different declared action")
    trainable = len(names)>=2
    if audit.get("trainable") is not trainable or not isinstance(audit.get("trainable_reason"),str) or not audit["trainable_reason"]:
        raise SchemaError("Declared trainability differs from candidate availability")
    return names,labels,baseline,trainable


def _availability_contract(availability,audit,capture,record,paths):
    if availability.get("schema")!="policy-iteration-public-availability-v1":
        raise SchemaError("Missing public preterminal availability contract")
    if audit.get("availability_sha256")!=sha(paths["availability"]):
        raise SchemaError("V2 audit is bound to a different availability file")
    if (availability.get("planned_group_id")!=record["group_id"] or availability.get("card")!=record["card"]
            or int(availability.get("rank",-1))!=int(capture["rank"])):
        raise SchemaError("Availability identity differs from the accepted group/cut")
    if availability.get("frozen_before_terminal") is not True or availability.get("control_was_running") is not True:
        raise SchemaError("Candidate availability was not frozen before terminal feedback")
    if availability.get("capture_sha256")!=sha(paths["capture"]) or availability.get("feature_blob_sha256")!=sha(paths["public_features"]):
        raise SchemaError("Availability is bound to different public capture/features")
    if availability.get("available_cases")!=audit["available_cases"]:
        raise SchemaError("Availability and audit inventories differ")
    if availability.get("absent_cases",[])!=audit.get("absent_cases",[]):
        raise SchemaError("Absent candidate records differ from preterminal availability")
    declared=availability.get("action_hashes",{})
    if set(declared)!=set(capture["actions"]) or any(declared[name]!=canonical_action(action) for name,action in capture["actions"].items()):
        raise SchemaError("Availability exact action hashes differ from public candidates")
    snapshot={k:v for k,v in capture["snapshot"].items() if k!="wallclock"}
    if availability.get("cut_snapshot_sha256")!=canonical_action(snapshot):
        raise SchemaError("Availability belongs to a different public decision snapshot")
    public_state={k:v for k,v in capture.items() if k not in ("case","selected_action")}
    public_state["snapshot"]=snapshot
    if availability.get("public_capture_state_sha256")!=canonical_action(public_state):
        raise SchemaError("Availability public state hash differs from accepted capture")


def card_split(card):
    if card in ("L1", "L2"):
        return "train"
    if card == "L3":
        return "validation"
    if card == "L4":
        return "test"
    raise SchemaError("Unknown card; a whole-card split must be declared")


def resolve(root, path):
    path = Path(path)
    return path if path.is_absolute() else root/path


def accepted_groups(manifest_path, *, include_test=False):
    """No automatic acceptance, terminal relabeling, sign/tie/error filtering."""
    manifest_path = Path(manifest_path)
    manifest = _read_json(manifest_path)
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("accepted") is not True or not manifest.get("acceptance_note"):
        raise SchemaError("An explicitly accepted, documented dataset manifest is required")
    seen, prefixes, out = set(), set(), []
    test_count = 0
    for record in manifest["groups"]:
        group_id = str(record["group_id"])
        if group_id in seen:
            raise SchemaError("Duplicate whole-state group_id")
        seen.add(group_id)
        split = card_split(record["card"])
        if split == "test" and not include_test:
            test_count += 1
            continue  # Do not even open L4 captures, audits, initializations, or features.
        if "availability" not in record:
            raise SchemaError("Accepted v2 groups must hash-lock a preterminal availability file")
        paths = {name:resolve(manifest_path.parent,record[name]) for name in ("capture","public_features","public_initial","pair_audit","availability")}
        hashes = record.get("sha256",{})
        if any(hashes.get(name) != sha(path) for name,path in paths.items()):
            raise SchemaError("Accepted dataset file hash drift: " + group_id)
        audit = _read_json(paths["pair_audit"])
        gates=audit.get("gates",{})
        if audit.get("schema")!=AUDIT_SCHEMA or audit.get("passed") is not True or not REQUIRED_V2_GATES<=set(gates) or not all(value is True for value in gates.values()):
            raise SchemaError("Full natural-continuation teacher audit failed: " + group_id)
        if audit.get("archive_complete") is not True:
            raise SchemaError("Teacher episode archives are incomplete; acceptance requires reviewed repair")
        if audit["card"] != record["card"] or audit.get("group_id")!=group_id or audit.get("split")!=split:
            raise SchemaError("V2 audit identity/split differs from declared whole-state group")
        _read_json(paths["capture"])  # Refuse duplicate action keys before normal public adapter decoding.
        initial,capture,arrays = load_public(paths["public_initial"],paths["capture"],paths["public_features"])
        if initial.get("task_card",{}).get("card_id") != record["card"]:
            raise SchemaError("Public initialization card differs from accepted split")
        if int(capture["rank"]) != int(audit["rank"]):
            raise SchemaError("Public state and teacher label rank differ")
        state_key = (record["card"],int(capture["rank"]),capture["prefix_sha256"])
        if state_key in prefixes:
            raise SchemaError("Repeated state prefix disguised as a new group")
        prefixes.add(state_key)
        names,labels,baseline,trainable = _candidate_contract(capture,audit)
        availability = _read_json(paths["availability"])
        _availability_contract(availability,audit,capture,record,paths)
        features = build_public_features(initial,capture,arrays)
        feature_names = [a.name for a in features.actions]
        if feature_names!=names or feature_names.count("control")!=1 or (trainable and len(feature_names)<2):
            raise SchemaError("Features do not preserve a trainable distinct-control candidate group")
        returns = np.zeros((len(names),len(COMPONENTS)+1),np.float32)
        for row,name in enumerate(names):
            if name == "control":
                continue
            label = labels[name]
            if label.get("valid_full_season_pair") is not True or label.get("advantage") is None:
                raise SchemaError("Incomplete/failed branch is not silently discarded: " + group_id + "/" + name)
            raw_row = [label["advantage"]]+[label["component_delta"][k] for k in COMPONENTS]
            if abs(float(raw_row[0])-sum(map(float,raw_row[1:])))>1e-5:
                raise SchemaError("Official total/component deltas disagree")
            returns[row] = raw_row
        if not np.isfinite(returns).all():
            raise SchemaError("Non-finite return label")
        out.append(dict(group_id=group_id,card=record["card"],rank=int(capture["rank"]),split=split,
                        features=features,labels=returns,state_key=state_key,trainable=trainable,
                        baseline_total=baseline,available_cases=list(audit["available_cases"]),absent_cases=audit.get("absent_cases",[]),
                        trainable_reason=audit["trainable_reason"],untrainable_reason=None if trainable else audit["trainable_reason"],
                        availability_sha256=audit["availability_sha256"]))
    return out,dict(manifest_sha256=sha(manifest_path),untouched_test_group_count=test_count,
                    group_count=len(out),trainable_group_count=sum(g["trainable"] for g in out),
                    control_only_availability_record_count=sum(not g["trainable"] for g in out),
                    untrainable_availability_records=[{k:g[k] for k in ("group_id","card","rank","split","available_cases","absent_cases","untrainable_reason","availability_sha256")} for g in out if not g["trainable"]],
                    acceptance_note=manifest["acceptance_note"])


def pair_loss(prediction,labels, *, anchor_weight=.01,aux_weight=.1):
    """Each group contributes one mean; all O(K²) comparisons remain correlated."""
    count = len(labels)
    if count<2 or len(prediction)!=count:
        raise SchemaError("Pairwise advantage loss requires at least two aligned distinct candidate actions")
    left,right = torch.triu_indices(count,count,1,device=prediction.device)
    error = (prediction[left]-prediction[right])-(labels[left]-labels[right])
    huber = torch.nn.functional.huber_loss(error,torch.zeros_like(error),delta=1.,reduction="none")
    control_anchor = prediction[0].square().mean()  # caller places control first
    return huber[:,0].mean()+aux_weight*huber[:,1:].mean()+anchor_weight*control_anchor


def _predict(model,group,normalizer,scale):
    with torch.no_grad():
        prediction=model.forward_group(group["features"],normalizer).detach().cpu().numpy()*scale
    control=[a.name for a in group["features"].actions].index("control")
    return prediction-prediction[control]


def _baseline_scores(group,name):
    actions=group["features"].actions
    if name=="native_control":
        return np.array([1. if a.name=="control" else 0 for a in actions])
    if name=="public_gain_per_second":
        return np.array([a.gain_per_second for a in actions])
    if name=="public_terminal_components_one_step":
        return np.array([a.coarse_utility for a in actions])
    raise ValueError(name)


def group_metrics(groups,predictions, *, raw_return_predictions=True):
    selected,regrets,errors,correct,ranks,signs = [],[],[],[],[],[]
    for group,prediction in zip(groups,predictions):
        values=group["labels"][:,0]
        control=[a.name for a in group["features"].actions].index("control")
        prediction=np.asarray(prediction)
        prediction=prediction-prediction[control]
        winner=int(np.argmax(prediction))
        selected.append(float(values[winner]))
        regrets.append(float(values.max()-values[winner]))
        errors.extend((prediction-values).tolist())
        left,right=np.triu_indices(len(values),1)
        delta=values[left]-values[right]
        guessed=prediction[left]-prediction[right]
        ranks.extend((np.sign(delta)==np.sign(guessed))[np.abs(delta)>1e-6].tolist())
        correct.append(values[winner]>=values.max()-1e-6)
        signs.extend(values[np.arange(len(values))!=control].tolist())
    if not groups:
        return {"groups":0}
    return dict(groups=len(groups),selected_teacher_advantage_mean=float(np.mean(selected)),
                selected_teacher_advantage_sum=float(np.sum(selected)),teacher_regret_mean=float(np.mean(regrets)),
                teacher_regret_max=float(np.max(regrets)),best_candidate_fraction=float(np.mean(correct)),
                raw_advantage_mae=float(np.mean(np.abs(errors))) if raw_return_predictions else None,
                scores_in_raw_teacher_return_units=raw_return_predictions,
                pair_sign_accuracy=float(np.mean(ranks)) if ranks else None,
                candidate_positive=sum(v>1e-6 for v in signs),candidate_negative=sum(v<-1e-6 for v in signs),
                candidate_tie=sum(abs(v)<=1e-6 for v in signs),
                note="Single-state candidate teacher-return metrics; not a deployed whole-season score.")


def fit_pair_ridge(train,validation,ridge=10.):
    """Convex flat baseline; group-weighted pair rows prevent action-count weighting."""
    flats=[g["features"].flat().astype(np.float64) for g in train]
    joined=np.concatenate(flats)
    mean,std=joined.mean(0),np.maximum(joined.std(0),1e-3)
    xrows,yrows=[],[]
    for group,flat in zip(train,flats):
        flat=np.clip((flat-mean)/std,-10,10)
        left,right=np.triu_indices(len(flat),1)
        norm=np.sqrt(len(left))
        xrows.extend((flat[left]-flat[right])/norm)
        yrows.extend((group["labels"][left,0]-group["labels"][right,0])/norm)
    x,y=np.asarray(xrows),np.asarray(yrows)
    # Solve in pair space, bounded by <=320 correlated pair rows in the first batch.
    dual=np.linalg.solve(x@x.T+ridge*np.eye(len(x)),y)
    weight=x.T@dual
    predictions=[np.clip((g["features"].flat()-mean)/std,-10,10)@weight for g in validation]
    return predictions,dict(weight=weight.astype(np.float32),mean=mean.astype(np.float32),std=std.astype(np.float32))


def validation_calibration(groups,predictions,coverage=.95):
    # A group is the sampling unit. Max errors account for choosing among candidates.
    errors=[]
    for group,prediction in zip(groups,predictions):
        control=[a.name for a in group["features"].actions].index("control")
        delta=prediction[:,0]-prediction[control,0]
        errors.append(float(np.max(np.abs(delta-group["labels"][:,0]))))
    quantile=int(np.ceil((len(errors)+1)*coverage))
    sufficient=0<quantile<=len(errors)
    return dict(group_count=len(errors),coverage=coverage,finite_sample_order=quantile,
                group_max_error_threshold=sorted(errors)[quantile-1] if sufficient else None,
                finite_sample_quantile_available=sufficient,
                deployment_calibrated=False,
                note="Validation uses the same card/realized world, so exchangeability and policy-wide calibration are unproved; full official policy gates still required.")


def decision_selection_key(metrics):
    """Fixed candidate-set regret first; numerical error only breaks ties.

    Mean regret equals a checkpoint-independent oracle return minus selected
    return. This selects decisions, rather than improving unused bad actions.
    It remains a realized single-state teacher metric, not a season score.
    """
    key=(float(metrics["teacher_regret_mean"]),float(metrics["raw_advantage_mae"]))
    if not np.isfinite(key).all():
        raise SchemaError("Non-finite validation decision-selection criterion")
    return key


def train(args):
    if torch is None:
        raise RuntimeError("Training requires Torch; NumPy runtime/feature audits do not")
    groups,provenance=accepted_groups(args.manifest)
    fitting=[g for g in groups if g["split"]=="train" and g["trainable"]]
    validation=[g for g in groups if g["split"]=="validation" and g["trainable"]]
    if len(fitting)<2 or not validation:
        raise SchemaError("Need at least two complete L1/L2 groups and a separate L3 validation group; one pilot is plumbing only")
    args.out.mkdir(parents=True,exist_ok=True)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.set_num_threads(args.cpu_threads)
    device="cuda" if args.device=="cuda" else "cpu"
    if device=="cuda" and not torch.cuda.is_available():
        raise RuntimeError("Requested CUDA device unavailable")
    normalizer=fit_normalizer([g["features"] for g in fitting])
    f=fitting[0]["features"]
    model=StructuredValue(f.target_nodes.shape[1],f.actions[0].edges.shape[1],f.global_features.size,f.actions[0].scalars.size)
    if args.model=="flat":
        flats=[g["features"].flat() for g in fitting]
        joined=np.concatenate(flats)
        normalizer=dict(flat_mean=joined.mean(0).astype(np.float32),flat_std=np.maximum(joined.std(0),1e-3).astype(np.float32))
        model=FlatValue(f.flat().shape[1])
    model=model.to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=args.learning_rate,weight_decay=args.weight_decay)
    raw_values=np.concatenate([g["labels"][:,0] for g in fitting])
    # One common unit scale preserves relative raw component magnitudes and score deltas.
    scale=max(float(np.median(np.abs(raw_values[np.abs(raw_values)>1e-6]))) if np.any(np.abs(raw_values)>1e-6) else 1.,1.)
    best,best_epoch,best_state=(float("inf"),float("inf")),0,None
    history=[]
    for epoch in range(1,args.epochs+1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss_total=0.
        for group in fitting:
            prediction=model.forward_group(group["features"],normalizer)
            labels=torch.as_tensor(group["labels"]/scale,device=device,dtype=torch.float32)
            control=[a.name for a in group["features"].actions].index("control")
            order=[control]+[i for i in range(len(labels)) if i!=control]
            loss=pair_loss(prediction[order],labels[order])/len(fitting)
            loss.backward()
            loss_total+=float(loss.detach().cpu())
        torch.nn.utils.clip_grad_norm_(model.parameters(),5.)
        optimizer.step()
        model.eval()
        predictions=[_predict(model,g,normalizer,scale) for g in validation]
        metrics=group_metrics(validation,[p[:,0] for p in predictions])
        # Predeclared selection criterion, no L4 access or score-chasing selection.
        criterion=decision_selection_key(metrics)
        history.append(dict(epoch=epoch,groupwise_train_loss=loss_total,validation=metrics,
                            decision_selection_key=criterion))
        if criterion<best:
            best,best_epoch,best_state=criterion,epoch,copy.deepcopy(model.state_dict())
        if epoch-best_epoch>=args.patience:
            break
    model.load_state_dict(best_state)
    model.eval()
    predictions=[_predict(model,g,normalizer,scale) for g in validation]
    comparisons={name:group_metrics(validation,[_baseline_scores(g,name) for g in validation],raw_return_predictions=False)
                 for name in ("native_control","public_gain_per_second","public_terminal_components_one_step")}
    ridge_predictions,ridge_model=fit_pair_ridge(fitting,validation)
    comparisons["flat_pair_ridge"]=group_metrics(validation,ridge_predictions)
    comparisons[args.model]=group_metrics(validation,[p[:,0] for p in predictions])
    np.savez_compressed(args.out/"flat_pair_ridge.npz",**ridge_model)
    calibration=validation_calibration(validation,predictions)
    report=dict(schema="structured-student-training-report-v1",provenance=provenance,train_groups=len(fitting),validation_groups=len(validation),
                broad_claim_minimum_training_states=256,broad_claim_minimum_met=len(fitting)>=256,
                training_cards=["L1","L2"],validation_card="L3",untouched_test_card="L4",model=args.model,
                parameters=sum(p.numel() for p in model.parameters()),best_epoch=best_epoch,output_scale=scale,
                checkpoint_selection=dict(primary="validation teacher_regret_mean",tie_break="validation raw_advantage_mae",
                    scope="Same fixed candidate sets; realized single-state teacher returns, not deployed whole-season value"),
                baseline_comparisons=comparisons,calibration=calibration,history=history,
                effective_independent_unit="whole state group; within-card futures are also dependent",
                full_season_policy_score_evaluated=False,per_target_auxiliary_training=False,
                note="Five official terminal components are groupwise auxiliary outputs. Rounded sparse target factors are intentionally not reinterpreted as exact threshold labels.")
    export_numpy(model,normalizer,args.out/"student_numpy.npz",output_scale=scale,
                 metadata=dict(deployment_calibrated=False,manifest_sha256=provenance["manifest_sha256"],model=args.model,
                               calibration=calibration,feature_names=dict(target=f.target_names,edge=f.edge_names,global_features=f.global_names,scalar=f.scalar_names)))
    (args.out/"training_report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ("train_groups","validation_groups","parameters","best_epoch","baseline_comparisons","calibration")},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--model",choices=("structured","flat"),default="structured")
    parser.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    parser.add_argument("--epochs",type=int,default=200)
    parser.add_argument("--patience",type=int,default=30)
    parser.add_argument("--learning-rate",type=float,default=1e-3)
    parser.add_argument("--weight-decay",type=float,default=1e-2)
    parser.add_argument("--cpu-threads",type=int,default=1)
    parser.add_argument("--seed",type=int,default=20261004)
    args=parser.parse_args()
    train(args)


if __name__=="__main__":
    main()
