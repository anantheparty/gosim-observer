"""Bounded public-schema, permutation, full-ledger and NumPy export checks.

No teacher labels are read, no optimization is run, and no season is launched.
--device cuda optionally verifies Torch/NumPy parity in the isolated GPU env.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tempfile
import time

import numpy as np

from research.structured_student_features import (FEATURE_SCHEMA, TARGET_SOURCE_NAMES, SchemaError,
                                                  build_public_features, load_public)
from research.structured_student_model import (NumpyValue, StructuredValue, export_numpy,
                                              identity_normalizer, torch)


def synthetic_public():
    ids=["A","B","C","D"]
    initial=dict(targets=dict(columns=["target_id","ra_deg","dec_deg","feature_flux","science_weight","required"],
                    rows=[[t,10+i*12,-10+i,.5+i*.1,1+i*.2,i%2==0] for i,t in enumerate(ids)]),
                 survey=dict(start_utc="2026-11-02T00:00:00Z",end_utc="2026-11-03T04:00:00Z",
                             nights=[dict(observing_start_utc="2026-11-02T00:00:00Z",observing_end_utc="2026-11-02T04:00:00Z")]),
                 instrument=dict(n_fibers=4,grid_side=2,pitch_deg=.5,exposure=dict(min_duration_seconds=60,max_duration_seconds=3600)),
                 scoring=dict(program=dict(multipliers=dict(DARK=1.2,BRIGHT=1.12,BACKUP=1.06),mismatch_multiplier=1.),
                              required=dict(observed_factor_threshold=.5,penalty_per_missing=50),
                              uniformity=dict(observed_factor_threshold=.5,weight=200,ra_band_width_deg=10)))
    def action(duration):
        return dict(action="observe",pointing=dict(alt_deg=60,az_deg=80),duration_seconds=duration,
                    program="DARK",assignments={"0":"A","1":"B"})
    history=[]
    for i in range(4):
        history.append(dict(now_utc=f"2026-11-02T00:0{i}:00Z",observe_action_index=i,action=action(60),
                            last_result=dict(action="observe",observe_index=i-1,hits=[]) if i else None,new_messages=[]))
    request=dict(request_id="R",target_ids=["A","B"],completed_target_ids=[],minimum_completed=2,
                 completion_factor_threshold=.5,completion_reward=100,issued_at_utc="2026-11-02T00:01:00Z",deadline_utc="2026-11-02T00:10:00Z")
    capture=dict(feature_schema="public-target-ledger-v1",target_ids=ids,target_feature_names=list(TARGET_SOURCE_NAMES),
                 rank=3,now_utc=history[-1]["now_utc"],snapshot=dict(now_utc=history[-1]["now_utc"],observe_action_index=3,running_total=.6,active_requests=[request]),
                 C=.55,E=.95,false_since_correct=0,calibrator_estimate=[0,0],notices=[],public_history=history,
                 actions=dict(control=action(60),long=action(120)),candidate_predictions={},candidate_utilities=dict(control=1.,long=None))
    source=np.array([[10/360,-10/90,.5,1,1,.2,.15,.2,.25,60/90,np.sin(np.radians(80)),np.cos(np.radians(80)),1,.5],
                     [22/360,-9/90,.6,1.2,0,.4,.3,.4,.5,60/90,np.sin(np.radians(80)),np.cos(np.radians(80)),1,.5],
                     [34/360,-8/90,.7,1.4,1,0,0,0,0,60/90,np.sin(np.radians(80)),np.cos(np.radians(80)),1,.5],
                     [46/360,-7/90,.8,1.6,0,0,0,0,0,60/90,np.sin(np.radians(80)),np.cos(np.radians(80)),1,.5]],np.float32)
    arrays=dict(target_features=source,scores=source[:,5].copy(),factor_lower=source[:,6].copy(),factor_estimate=source[:,7].copy(),
                ledger_rank=np.array([0,1,2,2]),ledger_target=np.array([0,1,0,1]),ledger_score=np.array([.15,.3,.2,.4]),
                ledger_factor_estimate=np.array([.15,.3,.2,.4]),ledger_lower=np.array([.1,.2,.15,.3]),ledger_valid=np.array([True,False,True,True]),
                control_assignment=np.array([[0,0],[1,1]],np.int32),long_assignment=np.array([[0,0],[1,1]],np.int32))
    for name in capture["actions"]:
        capture["candidate_predictions"][name]={t:dict(index=i,fiber_id=i,factor=.6 if name=="long" else .3,public_quality=.9,
                    quality=.8,directional_scale=1.,predicted_band="DARK",alt_deg=60,az_deg=80) for i,t in enumerate(ids[:2])}
    return initial,capture,arrays


def permute_public(capture,arrays,seed=21):
    """Relabel target indices and reorder every raw ledger/assignment row."""
    rng=np.random.default_rng(seed)
    cap,arr=copy.deepcopy(capture),{k:v.copy() for k,v in arrays.items()}
    order=rng.permutation(len(arr["target_features"]))
    inverse=np.argsort(order)
    cap["target_ids"]=[cap["target_ids"][i] for i in order]
    for key in ("target_features","scores","factor_lower","factor_estimate"):
        arr[key]=arr[key][order]
    arr["ledger_target"]=inverse[arr["ledger_target"]]
    ledger_order=rng.permutation(len(arr["ledger_rank"]))
    for key in tuple(arr):
        if key.startswith("ledger_"):
            arr[key]=arr[key][ledger_order]
        if key.endswith("_assignment"):
            arr[key][:,1]=inverse[arr[key][:,1]]
            arr[key]=arr[key][rng.permutation(len(arr[key]))]
    for predictions in cap["candidate_predictions"].values():
        for prediction in predictions.values():
            prediction["index"]=int(inverse[prediction["index"]])
    return cap,arr


def random_numpy_export(features,path,seed=21):
    rng=np.random.default_rng(seed)
    dims=dict(target_dim=features.target_nodes.shape[1],edge_dim=features.actions[0].edges.shape[1],
              global_dim=features.global_features.size,scalar_dim=features.actions[0].scalars.size,latent=8,hidden=16,output_dim=6)
    arrays={"normalizer."+k:v for k,v in identity_normalizer(features).items()}
    for prefix,inputs,outputs in (("target.0",dims["target_dim"],16),("target.2",16,8),
                                  ("edge.0",8+dims["edge_dim"],16),("edge.2",16,8),
                                  ("head.0",48+dims["global_dim"]+dims["scalar_dim"],16),("head.2",16,6)):
        arrays["weight."+prefix+".weight"]=rng.normal(0,.03,(outputs,inputs)).astype(np.float32)
        arrays["weight."+prefix+".bias"]=rng.normal(0,.01,outputs).astype(np.float32)
    arrays["config_json"]=np.asarray(json.dumps(dict(schema=FEATURE_SCHEMA,model_kind="structured",model_config=dims,output_scale=1.,
                                                   metadata=dict(deployment_calibrated=False,untrained_audit_only=True))))
    np.savez_compressed(path,**arrays)


def audit(args):
    initial,capture,arrays=synthetic_public()
    synthetic=build_public_features(initial,capture,arrays)
    # Ledger rank matters even when per-target current maxima remain unchanged.
    changed={k:v.copy() for k,v in arrays.items()}
    changed["ledger_rank"][0]=1
    ledger_changed=build_public_features(initial,capture,changed)
    if np.allclose(synthetic.target_nodes,ledger_changed.target_nodes) and np.allclose(synthetic.global_features,ledger_changed.global_features):
        raise AssertionError("Full ledger rank disappeared from features")
    # Missing target ordering/prediction metadata must fail closed.
    failures=[]
    for missing in ("target_ids","candidate_predictions"):
        invalid=copy.deepcopy(capture)
        invalid.pop(missing)
        try:
            build_public_features(initial,invalid,arrays)
        except SchemaError:
            failures.append(missing)
        else:
            raise AssertionError("Missing required public metadata accepted")
    real=False
    if args.capture is not None:
        if args.initial is None or args.public_features is None:
            raise ValueError("Real-public audit needs initial/capture/public-features together")
        initial,capture,arrays=load_public(args.initial,args.capture,args.public_features)
        real=True
    before=time.perf_counter()
    features=build_public_features(initial,capture,arrays)
    feature_seconds=time.perf_counter()-before
    permuted_capture,permuted_arrays=permute_public(capture,arrays)
    permuted=build_public_features(initial,permuted_capture,permuted_arrays)
    with tempfile.TemporaryDirectory(prefix="structured-student-audit-") as temp:
        export=Path(temp)/"untrained.npz"
        random_numpy_export(features,export)
        runtime=NumpyValue(export)
        before=time.perf_counter()
        prediction=runtime.predict(features)
        numpy_seconds=time.perf_counter()-before
        permutation_error=float(np.max(np.abs(prediction-runtime.predict(permuted))))
        if not np.allclose(prediction,runtime.predict(permuted),rtol=2e-5,atol=2e-4):
            raise AssertionError("Target/ledger/assignment permutation changed action values")
        if runtime.choose(features)!="control":
            raise AssertionError("Uncalibrated runtime must abstain to native control")
        result=dict(schema="structured-student-bounded-audit-v1",passed=True,real_public_features=real,
                    label_files_read=0,optimization_steps=0,seasons_launched=0,untrained_random_weights=True,
                    target_shape=list(features.target_nodes.shape),edge_dim=len(features.edge_names),global_dim=len(features.global_names),
                    scalar_dim=len(features.scalar_names),flat_dim=features.flat().shape[1],feature_seconds=feature_seconds,
                    numpy_inference_seconds=numpy_seconds,permutation_max_absolute_error=permutation_error,
                    raw_ledger_rank_sensitivity=True,missing_metadata_rejected=failures,uncalibrated_returns_control=True,
                    torch_requested=args.device!="none",warnings=features.warnings)
        if args.device!="none":
            if torch is None:
                raise RuntimeError("Torch audit requested but Torch unavailable")
            torch.set_num_threads(1)
            torch.manual_seed(21)
            model=StructuredValue(features.target_nodes.shape[1],features.actions[0].edges.shape[1],features.global_features.size,features.actions[0].scalars.size).to(args.device)
            normalizer=identity_normalizer(features)
            torch_values=model.forward_group(features,normalizer)
            # Synthetic objective exercises backprop only, with NO teacher labels/optimizer.
            torch_values.square().mean().backward()
            gradients_finite=all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters())
            export_numpy(model,normalizer,export,metadata=dict(deployment_calibrated=False,untrained_audit_only=True))
            runtime=NumpyValue(export)
            expected=torch_values.detach().cpu().numpy()
            actual=runtime.predict(features)
            parity=float(np.max(np.abs(expected-actual)))
            if not gradients_finite or not np.allclose(expected,actual,rtol=5e-5,atol=5e-4):
                raise AssertionError("Torch/NumPy export or finite gradient audit failed")
            result.update(torch_version=torch.__version__,device=args.device,torch_numpy_max_absolute_error=parity,
                          gradient_finite=gradients_finite,parameters=sum(p.numel() for p in model.parameters()))
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial",type=Path)
    parser.add_argument("--capture",type=Path)
    parser.add_argument("--public-features",type=Path)
    parser.add_argument("--device",choices=("none","cpu","cuda"),default="none")
    parser.add_argument("--out",type=Path)
    audit(parser.parse_args())


if __name__=="__main__":
    main()
