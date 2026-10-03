"""Held-out ranking, baseline comparison and NumPy deployment cost gates."""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
import numpy as np
from nn_proposal_train import numpy_predict


def evaluate(directory):
    directory=Path(directory);data=np.load(directory/'dataset.npz'); model=dict(np.load(directory/'model.npz'))
    manifest=json.loads((directory/'data_manifest.json').read_text()); progress=json.loads((directory/'train_progress.json').read_text())
    assert progress['status']=='complete'
    x,y,group,coarse=data['x'],data['y'],data['group'],data['coarse']
    predicted_log=numpy_predict(x,model); assert np.all(np.isfinite(predicted_log))
    groups=[]
    for g in manifest['groups']:
        indices=np.flatnonzero(group==g['group']); nn=np.argsort(-predicted_log[indices],kind='stable')
        comparison=np.argsort(-coarse[indices],kind='stable'); exact=y[indices]
        split='train' if g['group'] in progress['train_groups'] else ('validation_card' if g['card']=='L3' else 'test_card' if g['card']=='L4' else 'heldout_night')
        best=float(exact.max()); nn16=float(exact[nn[:16]].max()); coarse16=float(exact[comparison[:16]].max())
        groups.append({**g,'split':split,'MSE_log_local_value':float(np.mean((predicted_log[indices]-np.log1p(exact))**2)),
            'NN_top1_exact':float(exact[nn[0]]),'NN_top16_exact':nn16,'wide_coarse_top16_exact':coarse16,
            'NN_top16_relative_regret':0. if best==0 else float(1-nn16/best),
            'coarse_top16_relative_regret':0. if best==0 else float(1-coarse16/best),
            'NN_retaining_baseline_exact':max(float(g['CPUPhase_exact_rate']),nn16),
            'coarse_retaining_baseline_exact':max(float(g['CPUPhase_exact_rate']),coarse16),
            'NN_beats_CPUPhase':bool(nn16>g['CPUPhase_exact_rate']+1e-6),
            'wide_oracle_beats_CPUPhase':bool(best>g['CPUPhase_exact_rate']+1e-6)})
    aggregates={}
    for split in ('train','heldout_night','validation_card','test_card'):
        subset=[g for g in groups if g['split']==split]
        assert subset
        aggregates[split]={'states':len(subset),'rows':sum(g['candidates'] for g in subset),
            'mean_log_MSE':float(np.mean([g['MSE_log_local_value'] for g in subset])),
            'NN_top16_mean_relative_regret':float(np.mean([g['NN_top16_relative_regret'] for g in subset])),
            'coarse_top16_mean_relative_regret':float(np.mean([g['coarse_top16_relative_regret'] for g in subset])),
            'NN_beats_CPUPhase_states':sum(g['NN_beats_CPUPhase'] for g in subset),
            'wide_oracle_beats_CPUPhase_states':sum(g['wide_oracle_beats_CPUPhase'] for g in subset),
            'NN_retaining_baseline_mean_local_rate':float(np.mean([g['NN_retaining_baseline_exact'] for g in subset])),
            'CPUPhase_mean_local_rate':float(np.mean([g['CPUPhase_exact_rate'] for g in subset])),
            'coarse_retaining_baseline_mean_local_rate':float(np.mean([g['coarse_retaining_baseline_exact'] for g in subset]))}
    bench=[]
    for count in (768,32768):
        xx=x[np.arange(count)%len(x)];numpy_predict(xx,model);samples=[]
        for _ in range(7):
            started=time.perf_counter();values=numpy_predict(xx,model);top=np.argpartition(-values,16)[:16]
            samples.append(time.perf_counter()-started)
        assert len(top)==16
        bench.append({'candidate_rows':count,'median_NN_inference_plus_top16_seconds':float(np.median(samples)),
                      'minimum_seconds':min(samples),'maximum_seconds':max(samples),
                      'excludes_geometry_features_and_exact_refinement':True})
    # An actual unseen-card frame rebuild, feature reconstruction and exact
    # top16 evaluation. This also measures costs hidden by the NN-only timer.
    import math
    from nn_proposal_data import public_initialization,local_ledger,center_features
    from cpu_phase_candidates import CPUPhaseSpatialPlanner
    from spatial_candidates import SpatialPlanner,parse_utc,DEG
    g=next(g for g in manifest['groups'] if g['card']=='L4' and g['night']==0)
    initial,_=public_initialization('L4');p=CPUPhaseSpatialPlanner(initial);now=parse_utc(g['now_utc'])
    scores,factors,_=local_ledger('L4',p,now)
    started=time.perf_counter();p.choose({'now_utc':g['now_utc'],'latest_bulletin':{'notices':[]}},scores,factors,
        {'quality_scale':.35,'program_band_quality_scale':.35/.95,'cpu_phase_fixed_workload':True,
         'use_bulletin_directional_prior':False},[])
    baseline_seconds=time.perf_counter()-started;frame=p._cpu_phase_frame
    useful=np.flatnonzero(p._merit(frame)>1e-10);indices=np.flatnonzero(group==g['group']);centers=data['centers'][indices]
    xx=[];pools=[];started=time.perf_counter()
    for center in centers:
        v=np.array([math.cos(center[0]*DEG)*math.cos(center[1]*DEG),math.cos(center[0]*DEG)*math.sin(center[1]*DEG),math.sin(center[0]*DEG)])
        pool=useful[np.einsum('ij,j->i',frame[0][useful],v)>=math.cos(p.fov*DEG)];pools.append(pool)
        feature,_=center_features(p,center,pool,frame,.35,(now-p.nights[0][0]).total_seconds()/(p.nights[0][1]-p.nights[0][0]).total_seconds(),False)
        xx.append(feature)
    feature_seconds=time.perf_counter()-started;assert np.array_equal(np.asarray(xx),x[indices])
    started=time.perf_counter();ranks=np.argsort(-numpy_predict(np.asarray(xx),model),kind='stable')[:16]
    inference_seconds=time.perf_counter()-started;best=float(p.stats['selected_exact_rate']);errors=[]
    started=time.perf_counter()
    for j in ranks:
        candidate=SpatialPlanner._evaluate(p,tuple(centers[j]),pools[j],*frame)
        rate=0. if candidate is None else candidate[0];errors.append(abs(float(y[indices[j]])-rate));best=max(best,rate)
        if candidate is not None:
            fibres,valid,_=p._classify(frame[0][candidate[4]],*candidate[1])
            assert np.all(valid) and np.array_equal(fibres,candidate[5])
    refinement_seconds=time.perf_counter()-started;assert max(errors)<1e-6
    actual_gate={'card':'L4','night':0,'candidates':len(centers),'reconstructed_features_exact':True,
        'top16_oracle_label_max_error':max(errors),'geometry_assignments_valid':True,'baseline_seconds':baseline_seconds,
        'feature_seconds':feature_seconds,'inference_seconds':inference_seconds,'exact16_seconds':refinement_seconds,
        'NN_extra_seconds':feature_seconds+inference_seconds+refinement_seconds,
        'baseline_local_rate':float(p.stats['selected_exact_rate']),'with_NN_proposals_local_rate':best}
    report={'schema':'NN-proposal-heldout-v1','status':'TRAINED_OFFLINE_NOT_DEPLOYED_OR_SCORED',
            'official_score_measured':False,'network_or_service_changes':0,'hidden_platform_files_opened':0,
            'label':'bounded spherical frozen local utility, not actual final score or global optimality',
            'training':progress,'aggregates':aggregates,'CPU_numpy_inference':bench,'groups':groups,
            'actual_unseen_card_CPU_gate':actual_gate,
            'model_bytes':(directory/'model.npz').stat().st_size,
            'model_sha256':hashlib.sha256((directory/'model.npz').read_bytes()).hexdigest(),
            'dataset_sha256':hashlib.sha256((directory/'dataset.npz').read_bytes()).hexdigest(),
            'feature_dim':x.shape[1],'teacher_is_incumbent_imitation':False,'teacher_is_season_DP':False}
    (directory/'heldout_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('status','aggregates','CPU_numpy_inference','model_bytes','model_sha256')}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');evaluate(p.parse_args().directory)
