"""Authorized stage2 GPU training/calibration/finite validation. No test rescue or season claim."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import json,hashlib,shutil,time,argparse
from pathlib import Path
import numpy as np
import torch
from torch_helper.train_helper import train_model,load_world_arrays,TrainConfig,PUBLIC_KEYS
from torch_helper.score_distribution_model import masked_soft_cross_entropy,logits_to_joint_pmf,JointScoreDistributionModel
from torch_helper.numpy_score_distribution import NumpyJointScoreDistributionModel
from finite_evaluator import evaluate_prob,bootstrap_pair,finite_oracle
ROOT=Path(os.environ.get('DIRECT_SCORE_ROOT',Path(__file__).resolve().parent)).resolve()
TEMPERATURES=[.8,1.,1.2,1.5,2.]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def verify_source():
    lock=json.loads((ROOT/'SOURCE_FREEZE.json').read_text())
    for rel,h in lock['files'].items():
        if sha(ROOT/rel)!=h:raise RuntimeError('frozen source mismatch '+rel)
    gate=json.loads((ROOT/'MECHANICAL_GATE_SUMMARY.json').read_text());assert gate['passed']
    return lock

def worlds(split):
    lo,hi={'cal':(962000,962015),'val':(963000,963023),'test':(964000,964023)}[split];out=[]
    for seed in range(lo,hi+1):
        path=ROOT/'datasets'/split/f'{seed}.npz'
        with np.load(path,allow_pickle=False) as z:data={k:z[k].copy() for k in z.files}
        out.append((seed,data))
    return out

def tensor_batch(data,a,z,device):
    return [torch.as_tensor(data[k][a:z],dtype=torch.float32,device=device) for k in PUBLIC_KEYS]

def calibration(model,cal):
    # Each world averages the same 128 equally sampled states, then all worlds equally.
    values={T:[] for T in TEMPERATURES};device=next(model.parameters()).device
    for seed,data in cal:
        losses={T:[] for T in TEMPERATURES}
        for a in range(0,128,8):
            logits=model(*tensor_batch(data,a,a+8,device));F=torch.as_tensor(data['F'][a:a+8],device=device);b=torch.as_tensor(data['b'][a:a+8],device=device);mask=torch.as_tensor(data['mask'][a:a+8],device=device)
            for T in TEMPERATURES:losses[T].append(float(masked_soft_cross_entropy(logits/T,F,b,mask,state_balanced=True)))
        for T in TEMPERATURES:values[T].append(float(np.mean(losses[T])))
    means={T:float(np.mean(v)) for T,v in values.items()};T=min(TEMPERATURES,key=lambda t:(means[t],abs(t-1),t))
    return T,dict(temperature=T,world_balanced_soft_ce=means[T],grid_world_balanced_soft_ce={str(t):v for t,v in means.items()},world_soft_ce=values[T])

def validation(model,val,T,scoring):
    device=next(model.parameters()).device;rows=[]
    for seed,data in val:
        predicted=[]
        for a in range(0,128,8):
            prob=logits_to_joint_pmf(model(*tensor_batch(data,a,a+8,device)),T).cpu().numpy();small={k:(v[a:a+8] if isinstance(v,np.ndarray) and v.shape[0]==128 else v) for k,v in data.items()};result=evaluate_prob(prob,small,scoring);predicted.append(result)
        actual=np.concatenate([r['actual_rate'] for r in predicted]);point=np.concatenate([r['point_actual_rate'] for r in predicted]);oracle=finite_oracle(data,scoring)
        rows.append(dict(seed=seed,actual_rate=float(actual.mean()),point_rate=float(point.mean()),delta_point=float((actual-point).mean()),finite_oracle_rate=float(oracle.mean()),finite_oracle_regret=float((oracle-actual).mean()),public_wait_states=int(data['public_wait'].sum())))
    return dict(worlds=rows,worldmean_actual_rate=float(np.mean([r['actual_rate'] for r in rows])),worldmean_delta_point=float(np.mean([r['delta_point'] for r in rows])))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--test',action='store_true');args=parser.parse_args();freeze=verify_source();torch.set_num_threads(4);torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    if not torch.cuda.is_available():raise RuntimeError('actual PRO6000 CUDA fit required; no silent CPU training fallback')
    scoring=json.loads((ROOT/'v4_score_config.json').read_text());out=ROOT/'gpu_fit';out.mkdir(exist_ok=True)
    if args.test:
        lock=json.loads((ROOT/'SELECTED_MODEL_LOCK.json').read_text());assert lock['validation_gate']['positive_launch_gate'];npz=ROOT/lock['model_npz'];assert sha(npz)==lock['model_sha256'];model=JointScoreDistributionModel(lock['context_mode']).cuda();checkpoint=torch.load(ROOT/lock['model_pt'],map_location='cuda',weights_only=False);model.load_state_dict(checkpoint['model_state_dict']);model.eval()
        if (out/'TEST_RESULT.json').exists():raise RuntimeError('test already read once; immutable result')
        with torch.inference_mode():result=validation(model,worlds('test'),lock['temperature'],scoring)
        point=[r['point_rate'] for r in result['worlds']];learned=[r['actual_rate'] for r in result['worlds']];result.update(selected_lock_sha256=sha(ROOT/'SELECTED_MODEL_LOCK.json'),paired_vs_original_point=bootstrap_pair(learned,point),scope='One finite science-rate test of selected fixed model only. No model swap or season claim.');dump(out/'TEST_RESULT.json',result);print(json.dumps(result),flush=True);return
    if (out/'SELECTION_RESULT.json').exists():raise RuntimeError('fit selection exists; no silent rerun')
    begin=time.perf_counter();environment=dict(torch=torch.__version__,numpy=np.__version__,cuda=torch.cuda.is_available(),device=torch.cuda.get_device_name(0),device_total_memory=torch.cuda.get_device_properties(0).total_memory,source_freeze_sha256=sha(ROOT/'SOURCE_FREEZE.json'),source_files=freeze['files'],tf32=False,actual_gpu_training=True);dump(out/'GPU_ENVIRONMENT.json',environment);print(json.dumps(environment),flush=True)
    trainpaths=[ROOT/'datasets/train'/f'{s}.npz' for s in range(961000,961096)];train=load_world_arrays(trainpaths);cal=worlds('cal');val=worlds('val');all_records=[]
    for mode in ['fullhistory','current-public-only']:
        def callback(model,epoch):
            T,calstats=calibration(model,cal);valstats=validation(model,val,T,scoring);result=dict(context_mode=mode,epoch=epoch,calibration=calstats,validation=valstats);dump(out/mode/f'epoch_{epoch:02d}_evaluation.json',result);return result
        _,records=train_model(train,out/mode,mode,TrainConfig(device='cuda',preload_device=True),callback)
        all_records.extend((mode,r) for r in records)
    # Fixed choice across both architectures and all checkpoints by all-world rate.
    mode,record=min(all_records,key=lambda mr:(-mr[1]['checkpoint_metrics']['validation']['worldmean_actual_rate'],mr[1]['epoch'],0 if mr[0]=='current-public-only' else 1));metrics=record['checkpoint_metrics'];valrows=metrics['validation']['worlds'];learned=[r['actual_rate'] for r in valrows];point=[r['point_rate'] for r in valrows];gate=bootstrap_pair(learned,point)
    best_by_mode={m:min([r for mm,r in all_records if mm==m],key=lambda r:(-r['checkpoint_metrics']['validation']['worldmean_actual_rate'],r['epoch'])) for m in ['fullhistory','current-public-only']}
    full=[r['actual_rate'] for r in best_by_mode['fullhistory']['checkpoint_metrics']['validation']['worlds']];current=[r['actual_rate'] for r in best_by_mode['current-public-only']['checkpoint_metrics']['validation']['worlds']]
    selected=out/'selected_model.npz';selected_pt=out/'selected_model.pt';src=out/mode/f"epoch_{record['epoch']:02d}.npz";srcpt=src.with_suffix('.pt');shutil.copyfile(src,selected);shutil.copyfile(srcpt,selected_pt)
    # Public-only deployment parity for selected trained weights: use fresh public feature tensors, no labels.
    arrays={k:train[k][:8] for k in PUBLIC_KEYS};npmodel=NumpyJointScoreDistributionModel(selected);np_logits=npmodel.forward(*(arrays[k] for k in PUBLIC_KEYS));torch_model=JointScoreDistributionModel(mode).cuda();ck=torch.load(selected_pt,map_location='cuda',weights_only=False);torch_model.load_state_dict(ck['model_state_dict']);torch_model.eval()
    with torch.inference_mode():torch_logits=torch_model(*(torch.as_tensor(arrays[k],device='cuda') for k in PUBLIC_KEYS)).cpu().numpy()
    parity=float(np.max(abs(np_logits-torch_logits)));assert parity<3e-5
    result=dict(selected_context_mode=mode,selected_epoch=record['epoch'],temperature=metrics['calibration']['temperature'],validation_gate=gate,history_increment_vs_current_only=bootstrap_pair(full,current),selected_vs_best_control_world=bootstrap_pair(learned,np.maximum(point,current)),best_by_architecture={m:dict(epoch=r['epoch'],temperature=r['checkpoint_metrics']['calibration']['temperature'],worldmean_actual_rate=r['checkpoint_metrics']['validation']['worldmean_actual_rate']) for m,r in best_by_mode.items()},selected_model_sha256=sha(selected),numpy_torch_selected_public_logits_max_difference=parity,total_training_calibration_validation_seconds=time.perf_counter()-begin,scope='Finite additive science/actual-second model selection only; original full-season ZIP and controllers unchanged; all24 checkpoints archived; no test read yet.');dump(out/'SELECTION_RESULT.json',result)
    lock=dict(context_mode=mode,epoch=record['epoch'],temperature=metrics['calibration']['temperature'],validation_gate=gate,model_npz=str(selected.relative_to(ROOT)),model_pt=str(selected_pt.relative_to(ROOT)),model_sha256=sha(selected),model_pt_sha256=sha(selected_pt),source_freeze_sha256=sha(ROOT/'SOURCE_FREEZE.json'),sampling_lock_sha256=sha(ROOT/'SAMPLING_SELECT_LOCK.json'),test_rule='Only this selected version can read 964000..964023 once; no alternate model or temperature after test',test_not_read=True);dump(ROOT/'SELECTED_MODEL_LOCK.json',lock);print(json.dumps(result),flush=True)
if __name__=='__main__':main()
