"""Read-only diagnostics of the retained failed fit; no source/gate changes."""
import json
import hashlib
from pathlib import Path
import numpy as np
import torch
from torch_helper.train_helper import PUBLIC_KEYS
from torch_helper.score_distribution_model import JointScoreDistributionModel, logits_to_joint_pmf as torch_pmf
from torch_helper.numpy_score_distribution import NumpyJointScoreDistributionModel, logits_to_joint_pmf as numpy_pmf
from target_core import expected_gain
from finite_evaluator import bootstrap_pair, select

root=Path(__file__).resolve().parent
torch.set_num_threads(4)
torch.backends.cuda.matmul.allow_tf32=False
torch.backends.cudnn.allow_tf32=False
records=[]
best_by_mode={}
for mode in ['fullhistory','current-public-only']:
    rows=[json.loads(x) for x in (root/'gpu_fit'/mode/'training_log.jsonl').read_text().splitlines()]
    assert len(rows)==12
    best_by_mode[mode]=min(rows,key=lambda r:(-r['checkpoint_metrics']['validation']['worldmean_actual_rate'],r['epoch']))
    records.extend((mode,r) for r in rows)
mode,record=min(records,key=lambda mr:(-mr[1]['checkpoint_metrics']['validation']['worldmean_actual_rate'],mr[1]['epoch'],0 if mr[0]=='current-public-only' else 1))
metrics=record['checkpoint_metrics']
temperature=metrics['calibration']['temperature']
with np.load(root/'datasets/train/961000.npz',allow_pickle=False) as z:
    arrays={k:z[k][:8].copy() for k in PUBLIC_KEYS}
    public={k:z[k][:8].copy() for k in ['best','weight','mask','fiber','duration','public_wait']}
npmodel=NumpyJointScoreDistributionModel(root/'gpu_fit/selected_model.npz')
assert npmodel.context_mode==mode
np_logits=npmodel.forward(*(arrays[k] for k in PUBLIC_KEYS))
model=JointScoreDistributionModel(mode).cuda()
checkpoint=torch.load(root/'gpu_fit/selected_model.pt',map_location='cuda',weights_only=False)
model.load_state_dict(checkpoint['model_state_dict']);model.eval()
with torch.inference_mode():
    gpu_logits=model(*(torch.as_tensor(arrays[k],device='cuda') for k in PUBLIC_KEYS)).cpu().numpy()
    gpu_prob=torch_pmf(torch.as_tensor(gpu_logits,device='cuda'),temperature).cpu().numpy()
model=model.cpu()
with torch.inference_mode():
    cpu_logits=model(*(torch.as_tensor(arrays[k]) for k in PUBLIC_KEYS)).numpy()
np_prob=numpy_pmf(np_logits,temperature)
class DoubleNumpy(NumpyJointScoreDistributionModel):
    def _linear(self,value,prefix):
        weight=self.weights[prefix+'.weight'].astype(np.float64)
        bias=self.weights[prefix+'.bias'].astype(np.float64)
        return np.einsum('...i,oi->...o',value.astype(np.float64),weight,optimize=False)+bias
double_logits=DoubleNumpy(root/'gpu_fit/selected_model.npz').forward(*(arrays[k] for k in PUBLIC_KEYS))
scoring=json.loads((root/'v4_score_config.json').read_text())
np_gain=expected_gain(np_prob,public['weight'],public['best'],scoring)
gpu_gain=expected_gain(gpu_prob,public['weight'],public['best'],scoring)
np_action,_=select(np_gain,public['mask'],public['fiber'],public['duration'],public['public_wait'])
gpu_action,_=select(gpu_gain,public['mask'],public['fiber'],public['duration'],public['public_wait'])
arch={}
for m,r in best_by_mode.items():
    worlds=r['checkpoint_metrics']['validation']['worlds']
    learned=[w['actual_rate'] for w in worlds];point=[w['point_rate'] for w in worlds]
    arch[m]=dict(epoch=r['epoch'],temperature=r['checkpoint_metrics']['calibration']['temperature'],
                 worldmean_actual_rate=float(np.mean(learned)),worldmean_original_point_rate=float(np.mean(point)),
                 paired_vs_original_point=bootstrap_pair(learned,point),world_rates=[{k:w[k] for k in ('seed','actual_rate','point_rate','delta_point')} for w in worlds])
full=[w['actual_rate'] for w in best_by_mode['fullhistory']['checkpoint_metrics']['validation']['worlds']]
current=[w['actual_rate'] for w in best_by_mode['current-public-only']['checkpoint_metrics']['validation']['worlds']]
result=dict(source_freeze_sha256=hashlib.sha256((root/'SOURCE_FREEZE.json').read_bytes()).hexdigest(),
            completed_checkpoints=24,descriptive_locked_choice=dict(mode=mode,epoch=record['epoch'],temperature=temperature),
            selection_driver_failed=True,no_selected_model_lock_written=not (root/'SELECTED_MODEL_LOCK.json').exists(),
            original_logit_gate=3e-5,logit_gate_preserved=True,
            public_fixture_states=8,public_valid_queries=int(public['mask'].sum()),
            numpy_gpu_logits_max_difference=float(np.max(abs(np_logits-gpu_logits))),
            numpy_cpu_logits_max_difference=float(np.max(abs(np_logits-cpu_logits))),
            cpu_gpu_logits_max_difference=float(np.max(abs(cpu_logits-gpu_logits))),
            double_numpy_gpu_logits_max_difference=float(np.max(abs(double_logits-gpu_logits))),
            logits_max_absolute=float(np.max(abs(gpu_logits))),
            numpy_gpu_logits_max_difference_valid=float(np.max(abs(np_logits-gpu_logits)[public['mask']])),
            numpy_gpu_pmf_max_difference=float(np.max(abs(np_prob-gpu_prob))),
            numpy_gpu_mean_max_difference=float(np.max(abs((np_prob*np.linspace(0,1,65)).sum((-2,-1))-(gpu_prob*np.linspace(0,1,65)).sum((-2,-1))))),
            numpy_gpu_expected_science_gain_max_difference=float(np.max(abs(np_gain-gpu_gain))),
            public_fixture_assignments_equal=np_action==gpu_action,
            input_max_absolute={k:float(np.max(abs(v))) for k,v in arrays.items()},
            architectures=arch,history_increment_vs_current=bootstrap_pair(full,current),test_world_count=0,
            scope='Retained failed-fit read-only diagnostic. Same prelocked selection describes completed checkpoints; no gate loosened, no fit rerun, no test generated or production adoption.')
(root/'PARITY_FAILURE_DIAGNOSTIC.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ['architectures']},indent=2),flush=True)
