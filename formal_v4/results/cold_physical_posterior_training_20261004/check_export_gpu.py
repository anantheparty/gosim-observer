"""Read-only actual CUDA vs NumPy parameter export and healthy support fixtures."""
from pathlib import Path
import json,hashlib
import numpy as np
import torch
ROOT=Path(__file__).resolve().parent
def main():
    assert torch.cuda.is_available();z=np.load(ROOT/'physical_model.npz');data=np.load(ROOT/'fit_data.npz');x=data['cal_x'];chosen=np.unique(np.r_[np.arange(128),np.flatnonzero(x[:,8*322+9]>.5)]);x=x[chosen]
    h=torch.tensor((x-z['mean'])/z['std'],dtype=torch.float32,device='cuda')
    for k in range(3):
        h=h@torch.tensor(z[f'w{k}'],dtype=torch.float32,device='cuda').T+torch.tensor(z[f'b{k}'],dtype=torch.float32,device='cuda')
        if k<2:h=h.relu()
    h=h/float(z['temperature']);health=torch.tensor(z['healthy'],device='cuda');same=torch.tensor(x[:,8*322+9]>.5,device='cuda');h=h.masked_fill(same[:,None]&~health[None,:],-1e6);p=h.softmax(-1).cpu().numpy()
    np.savez(ROOT/'export_fixture.npz',x=x,gpu_probabilities=p)
    result=dict(gpu=torch.cuda.get_device_name(),queries=len(x),same_timestamp_report=int(same.sum()),first_fault_forbidden_probability_max=float(p[(x[:,8*322+9]>.5)][:,~z['healthy'].astype(bool)].max()),model_sha256=hashlib.sha256((ROOT/'physical_model.npz').read_bytes()).hexdigest(),float32_cuda_evaluation=True,training=False)
    (ROOT/'export_cuda_result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
