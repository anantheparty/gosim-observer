"""Mechanical public-state transition repair. Model stays frozen; no test read."""
import json,shutil,hashlib,time
from pathlib import Path
import numpy as np
from report_core import ReportModel,build_dp,NP
ROOT=Path(__file__).resolve().parent;start=time.time()
for name in ['report_dp.npz','selection_lock.json']:
    shutil.copyfile(ROOT/name,ROOT/(Path(name).stem+'_v1'+Path(name).suffix))
model=ReportModel();data=np.load(ROOT/'report_dataset.npz');probs=[]
for name in ['x','xw','xr']:
    X=data['train_'+name];p=[]
    for j in range(0,len(X),4096):p.append(model.posterior(X[j:j+4096]))
    probs.append(np.concatenate(p))
dp=build_dp(*probs,data['train_y'],data['train_loss'],data['train_phase'],data['train_quake'],data['train_correct'],data['train_xw'],data['train_xr'])
np.savez_compressed(ROOT/'report_dp.npz',**dp)
lock=json.loads((ROOT/'selection_lock_v1.json').read_text());lock.update(test_seed_first=770000,test_seed_last=770031,test_unopened=True,test_once_complete=False,
    dp_sha256=hashlib.sha256((ROOT/'report_dp.npz').read_bytes()).hexdigest(),selected='dp_free',
    rule='dp_free remains selected from original validation; mechanical deterministic public-count repair; no threshold/model retuning',
    prior_test=dict(seeds=[760000,760031],file='test_evaluation.json',qualification='implementation-defective v1 DP; retained; not used for v2 choices'),
    test_output_prefix='test_v2')
(ROOT/'selection_lock.json').write_text(json.dumps(lock,indent=2))
result=dict(public_count_invariant=True,model_sha256=lock['model_sha256'],new_dp_sha256=lock['dp_sha256'],
    seconds=time.time()-start,max_positive_delta=float(dp['delta'].max()),old_bug='Global fallback could decrease public correct_count and create fictitious repeated repair rewards',
    test_read=False,new_test_locked_seeds=[770000,770031])
(ROOT/'dp_count_repair.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
