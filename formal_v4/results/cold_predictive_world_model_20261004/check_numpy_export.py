from pathlib import Path
import json,time
import numpy as np
import torch
from torch import nn
from predictive_core import NumpyPredictor,score_token
ROOT=Path(__file__).resolve().parent
torch.set_num_threads(2)
def main():
    predictor=NumpyPredictor(ROOT/'joint_model.npz');weights=predictor.data
    model=nn.Sequential(nn.Linear(1306,128),nn.ReLU(),nn.Linear(128,128),nn.ReLU(),nn.Linear(128,196)).double().cuda()
    for k,j in enumerate([0,2,4]):
        with torch.no_grad():model[j].weight.copy_(torch.tensor(weights[f'weight{k}'],device='cuda'));model[j].bias.copy_(torch.tensor(weights[f'bias{k}'],device='cuda'))
    data=np.load(ROOT/'world_dataset.npz');x=data['train_x'][:128].astype(float)
    with torch.no_grad():native=model(torch.tensor(x,device='cuda')).cpu().numpy()
    exported=np.asarray([predictor.predict(r) for r in x]);error=float(np.max(np.abs(native-exported)))
    rng=np.random.default_rng(8941);scores=rng.uniform(0,1,16);weights0=rng.uniform(.3,1.7,16);flux=rng.uniform(.1,2,16);h=rng.uniform(.4,.8,16)
    order=rng.permutation(16)
    token=score_token(scores,weights0,flux,h,900,1,elapsed_slots=1,new_night=False,seasonal_c=.83,slot_fraction=.2)
    shuffled=score_token(scores[order],weights0[order],flux[order],h[order],900,1,elapsed_slots=1,new_night=False,seasonal_c=.83,slot_fraction=.2)
    permutation=float(np.max(np.abs(token-shuffled)))
    t=time.perf_counter()
    for row in x:predictor.predict(row)
    result={'max_abs_torch_float64_numpy_output_error':error,'permutation_token_max_error':permutation,
            'finite':bool(np.isfinite(exported).all()),'cpu_inference_ms_per_record':(time.perf_counter()-t)/len(x)*1000,
            'gate':error<1e-10 and permutation<1e-6,'device':torch.cuda.get_device_name()}
    (ROOT/'numpy_export_gate.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
