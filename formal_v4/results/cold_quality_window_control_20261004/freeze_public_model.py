"""Freeze public model tensors and a small CPU reference for CUDA parity."""
from pathlib import Path
import hashlib,json,time,zipfile
import numpy as np
from public_pilot import public_initial,build_model,SpatialPlanner,ROOT
from window_control import OutcomeModel,solve,expected_demand

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    out=Path(__file__).parent
    started=time.perf_counter()
    initial,paths=public_initial('delta');planner=SpatialPlanner(initial)
    model,geometry=build_model(planner)
    capacity=np.array([(e-s).total_seconds()*planner.nfib for s,e in planner.nights])
    np.savez_compressed(out/'delta_public_model.npz',
        normalized_score=model.normalized_score,raw_factor=model.raw_factor,
        probabilities=model.probabilities,durations=model.durations,
        weights=model.weights,required_bonus=model.required_bonus,
        threshold=np.array(model.threshold),capacity=capacity,
        public_geometry=geometry,target_ids=np.asarray(planner.ids),
        normalized_best=np.zeros(planner.n),completed_probability=np.zeros(planner.n))
    req=np.flatnonzero(planner.required)
    selected=np.unique(np.r_[np.arange(32),req[np.argsort(planner.flux[req])[:32]],
                              req[np.argsort(planner.flux[req])[-32:]],
                              np.random.default_rng(39814).choice(planner.n,32,replace=False)])
    subset=OutcomeModel(model.normalized_score[...,selected],model.raw_factor[...,selected],
        model.probabilities,model.durations,model.weights[selected],model.required_bonus[selected],model.threshold)
    prices=.00015*(1+np.sin(np.arange(38)*.37))
    initial_best=np.zeros(len(selected));initial_best[::3]=.4
    initial_complete=np.zeros(len(selected));initial_complete[::5]=.25
    result=solve(subset,prices,score_bins=25,probability_bins=9)
    demand=expected_demand(subset,result,normalized_best=initial_best,completed_probability=initial_complete)
    np.savez_compressed(out/'delta_subset_cpu_reference.npz',
        indices=selected,prices=prices,value=result['value'],policy=result['policy'],
        score_grid=result['score_grid'],probability_grid=result['probability_grid'],
        demand=demand,normalized_best=initial_best,completed_probability=initial_complete)
    origin=Path('/Users/kamico/Downloads/observer_request_exact_cache.zip')
    control=ROOT/'formal_v4/results/request_geometry_integration_20261004/control_package'
    with zipfile.ZipFile(origin) as archive:
        origin_match={name:(control/name).exists() and
            hashlib.sha256((control/name).read_bytes()).digest()==hashlib.sha256(archive.read(name)).digest()
            for name in archive.namelist() if not name.endswith('/')}
    bound=float(np.max((1.2*model.weights+model.required_bonus)/np.min(model.durations)))
    receipt=dict(model='delta_public_model.npz',model_sha256=sha(out/'delta_public_model.npz'),
        reference='delta_subset_cpu_reference.npz',reference_sha256=sha(out/'delta_subset_cpu_reference.npz'),
        reference_targets=len(selected),reference_B=25,reference_Pi=9,
        reference_nonzero_public_state=True,subset_model_full_horizon=True,
        window_control_sha256=sha(out/'window_control.py'),
        public_pilot_sha256=sha(out/'public_pilot.py'),checks_sha256=sha(out/'checks.json'),
        shapes={key:list(getattr(model,key).shape) for key in
                ['normalized_score','raw_factor','probabilities','durations','weights','required_bonus']},
        dtypes={key:str(getattr(model,key).dtype) for key in
                ['normalized_score','raw_factor','probabilities','durations','weights','required_bonus']},
        safe_price_cube_upper=bound,finite_model_price_unit='points/fiber-second',
        source_zip_sha256=sha(origin),all29_control_members_match_source=all(origin_match.values()),
        control_origin_members=origin_match,
        public_inputs={str(p.relative_to(ROOT)):sha(p) for p in paths},
        inputs_are_only_public_catalog_calendar_site_instrument_scoring=True,
        extra_cpu_seconds=time.perf_counter()-started,
        full_season=False,trained=False,deployed=False,truth_input_files_read=[])
    (out/'FROZEN_MODEL_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k not in
          ('control_origin_members','public_inputs')},indent=2))

if __name__=='__main__':main()
