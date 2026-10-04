"""All pre-test gates, hashes and one fixed candidate."""
import hashlib,json,datetime
from pathlib import Path
import numpy as np
from report_core import ReportModel
ROOT=Path(__file__).resolve().parent
checks={k:json.loads((ROOT/f'{k}.json').read_text()) for k in ['pilot_operator_checks','semantics_checks','public_adapter_checks','public_interface_checks']}
assert all(v['passed'] for v in checks.values())
training=json.loads((ROOT/'training_result.json').read_text())
assert training['gate_float32_gpu_numpy_max_logit_error']<1e-4
for split in ['cal','val']:
    m=training[split];p=m['prevalence'];baseline=-p*np.log(p)-(1-p)*np.log(1-p)
    assert m['nll']<baseline and m['brier']<p*(1-p)
model=ReportModel();data=np.load(ROOT/'report_dataset.npz');states=0
for name in ['cal_x','val_x']:
    x=data[name];p=model.posterior(x);assert np.isfinite(p).all() and np.all((0<=p)&(p<=1))
    exact=x.copy();exact[:,-35]=1.;assert np.max(model.posterior(exact))==0.
    exact=x.copy();exact[:,-33]=1.;assert np.max(model.posterior(exact))==0.
    states+=len(p)
files=['report_model.npz','report_dp.npz','report_core.py','report_policy.py','report_support.py','sensor_core.py','report_entry.py','public_design.py','sparse_world.py','build_dataset.py','train.py','evaluate.py','candidate_package.zip','posterior_p90_control_package.zip','public_design_cache.pkl','report_dataset.npz','SAMPLING_LOCK.json','DP_CONTRACT_AMENDMENT.json']
out=dict(created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),trial='sparse newdomain fixed free DP with byte-frozen faultv1 fallback',
    all_gates_passed=True,finite_public_posterior_states=states,exact_report_timestamp_and_post_two_correct_prior=True,
    test_seeds=[850000,850015],test_unopened=True,test_use='one independent fixed-design decision-regret evaluation; no threshold/source/model selection after result',
    model_sha256=hashlib.sha256((ROOT/'report_model.npz').read_bytes()).hexdigest(),dp_sha256=hashlib.sha256((ROOT/'report_dp.npz').read_bytes()).hexdigest(),
    sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files},checks=checks,
    metric_diagnostic='epochs14/15 preselection calNLL reported Infinity because float32 clip1-1e-8 rounded1; logits/output finite, selectedepoch3 and final float64 cal/val NLL finite. Raw logs retained; no model re-fit.')
(ROOT/'SOURCE_LOCK.json').write_text(json.dumps(out,indent=2));print(json.dumps({k:v for k,v in out.items() if k not in ['checks','sha256']},indent=2))
