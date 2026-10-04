"""Mechanical exact max-two-fault absorbing-state amendment; NN unchanged."""
import json,hashlib,time
import numpy as np
from report_core import ReportModel,build_dp
from pathlib import Path
ROOT=Path(__file__).resolve().parent
start=time.time();data=np.load(ROOT/'report_dataset.npz');model=ReportModel();probs=[model.posterior(data[f'train_{name}']) for name in ['x','xw','xr']]
dp=build_dp(*probs,data['train_y'],data['train_loss'],data['train_phase'],data['train_quake'],data['train_correct'],data['train_xw'],data['train_xr'])
np.savez_compressed(ROOT/'report_dp.npz',**dp)
out=dict(reason='exact max-two-fault prior: public correct_count2 implies F=0 and no future repair loss; loss0 and kernels to p0 preserve quake; no parameter selection or NN/cal change',
    original_dp_sha256=hashlib.sha256((ROOT/'report_dp_stage1_nonabsorbing.npz').read_bytes()).hexdigest(),fixed_dp_sha256=hashlib.sha256((ROOT/'report_dp.npz').read_bytes()).hexdigest(),
    frozen_model_sha256=hashlib.sha256((ROOT/'report_model.npz').read_bytes()).hexdigest(),test_unopened=True,seconds=time.time()-start)
(ROOT/'DP_CONTRACT_AMENDMENT.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
