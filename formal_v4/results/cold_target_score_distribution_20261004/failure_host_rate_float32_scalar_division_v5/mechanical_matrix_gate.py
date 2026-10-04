"""Four fresh-world finite action and distribution/geometry cache mechanical gates."""
import json,hashlib
from pathlib import Path
import numpy as np
from target_core import soft_label,expected_gain,first_gain
from finite_evaluator import evaluate_prob,finite_oracle
ROOT=Path(__file__).resolve().parent

def main():
    cfg=json.loads((ROOT/'v4_score_config.json').read_text());receipts=[];maxround=maxduplicate=maxmoment=0.;allrows=allchecks=0;effective_can_differ=0
    for seed in range(940911,940915):
        path=ROOT/'datasets/mechanical'/f'{seed}.npz'
        with np.load(path,allow_pickle=False) as z:data={k:z[k].copy() for k in z.files}
        r=json.loads(path.with_suffix('.json').read_text());assert r['pointstate_uncached_reference_checks']==r['past_observations'];assert r['max_official_factor_difference']<1e-9;assert r['max_original_public_H_cache_difference']<1e-10;assert r['pointstate_uncached_max_difference']<1e-9
        keep=data['mask'];err=float(np.max(abs(data['best'][keep].astype(float)-data['truebest'][keep].astype(float))));maxround=max(maxround,err);assert err<.75e-6 # both stored float32: include float32 ledger storage bound.
        assert np.isfinite(data['ht']).all() and np.isfinite(data['q']).all() and np.all(data['effective']<=data['F'])
        for s in range(128):
            previous={}
            for j in np.flatnonzero(keep[s]):
                key=(int(data['idx'][s,j]),float(data['duration'][s,j//32]))
                if key in previous:
                    old=previous[key];e=float(np.max(abs(data['q'][s,j]-data['q'][s,old])));maxduplicate=max(maxduplicate,e);assert e==0 and data['F'][s,j]==data['F'][s,old] and data['b'][s,j]==data['b'][s,old];effective_can_differ+=data['effective'][s,j]!=data['effective'][s,old]
                previous[key]=j
        # Prediction from physical projected labels is used only as an operator check, not fitted accuracy.
        actuals=[]
        for a in range(0,128,8):
            prob=soft_label(data['F'][a:a+8],data['b'][a:a+8]);weight=data['weight'][a:a+8];g0=expected_gain(prob,weight,np.zeros_like(weight),cfg);mu=first_gain(prob,weight,cfg);maxmoment=max(maxmoment,float(np.max(abs(g0-mu))));small={k:(v[a:a+8] if v.shape[0]==128 else v) for k,v in data.items()};ev=evaluate_prob(prob,small,cfg);actuals.extend(ev['actual_rate'])
        oracle=finite_oracle(data,cfg);assert np.all(oracle+1e-9>=actuals);allrows+=int(keep.sum());allchecks+=r['official_scalar_labels_checked'];receipts.append(r)
    out=dict(passed=True,worlds=receipts,future_rows=allrows,official_scalar_F_band_checks=allchecks,max_public_best_minus_truebest_float32_error=maxround,max_pointing_independent_query_duplicate_difference=maxduplicate,duplicate_fields_actual_effective_may_differ_cases=int(effective_can_differ),max_same_distribution_first_moment_difference=maxmoment,objective='Expected science/actualseconds before assignment; realized hosteffective gain/actualseconds; same original public wait/admissibility gate.',scope='Mechanical contracts and finite operator only; oracle-projected-label check is not trained accuracy, deployment or season gain.')
    (ROOT/'MECHANICAL_GATE_SUMMARY.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k!='worlds'}))
if __name__=='__main__':main()
