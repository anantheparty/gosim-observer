"""Finite public-start required opportunity audit using own interval profiles.

No hidden input, network or accelerator. Bounds are conditional on the stated
reference geometry domain and retained effective-efficiency repair trajectory.
Absence of a sampled opportunity is never a continuous infeasibility proof.
"""
from __future__ import annotations
import csv,hashlib,json,os,time
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import numpy as np
from quality_profile_inversion import PublicQualityMatrix,ReferenceClearFilter
from required_opportunity_model import RequiredOpportunityModel,public_initial,parse,stamp


def audit(root):
    began=time.perf_counter();out={'scope':'finite public starts; conditional reference-domain and original repair path',
          'hidden_inputs_read':False,'negative_sampling_not_infeasibility_proof':True,'cards':{}}
    for card in ('alpha','beta','gamma','delta'):
        directory=root/'formal_v4/results'/f'cloud_cd2_{card}_20261003'
        model=RequiredOpportunityModel(public_initial(root/'formal_v4/practice_cards'/card/card))
        observations=list(csv.DictReader((directory/'observations.csv').open()))
        maxima={}
        for row in observations:
            if row['valid']=='true':maxima[row['target_id']]=max(maxima.get(row['target_id'],0),float(row['factor']))
        missing=[tid for tid in model.ids if maxima.get(tid,0)<model.threshold]
        report=json.loads((directory/'score_report.json').read_text())
        assert len(missing)==report['counts']['required_missing']
        messages=[json.loads(line) for line in (directory/'messages.jsonl').read_text().splitlines()]
        profile_path=root/'formal_v4/research'/f'quality_profile_{card}_result.npz'
        profile=np.load(profile_path)
        meta=json.loads(profile_path.with_suffix('.json').read_text())
        matrix=PublicQualityMatrix(model,[parse(s).timestamp() for s in meta['repair_timestamps_utc']])
        assert np.allclose(matrix.starts,profile['cell_start']) and np.allclose(matrix.ends,profile['cell_end'])
        clean=ReferenceClearFilter(model,messages)
        lower,upper,support=profile['lower'],profile['upper'],profile['support']
        narrow=(support>0)&(upper-lower<=1e-4)
        gap_path=root/'formal_v4/research'/f'quality_profile_{card}_cross_run_result.json'
        gaps=[(parse(a).timestamp(),parse(b).timestamp()) for a,b in json.loads(gap_path.read_text())['repair_gap_utc']]
        records=[]
        for tid in missing:
            i=model.index[tid];best_lower=best_clean_lower=best_upper=best_supported_upper=0.
            strongest=None;strongest_narrow=None;counts=dict(candidates=0,all_supported=0,all_narrow=0,
                                                         clean_certified=0,conditional_quota=0)
            coupons=[]
            for night,(anchor,end) in enumerate(model.nights):
                for left,right in model.windows(i,night):
                    a,b=np.ceil(left),np.floor(right)
                    if b-a<model.tmin:continue
                    starts=np.unique(np.r_[a,b-model.tmax,b-model.tmin,
                        np.arange(anchor,end,900),profile['cell_start'][(profile['cell_start']>=a)&(profile['cell_start']<=b-model.tmin)]])
                    starts=np.unique(np.ceil(starts[(starts>=a)&(starts<=b-model.tmin)]))
                    for start in starts:
                        duration=int(min(model.tmax,b-start))
                        if duration<model.tmin:continue
                        cells,coef=matrix.coefficients(start,duration,[i]);coef=coef[0]
                        lo=min(1.,float(model.flux[i]*duration/model.f0t0*np.dot(coef,lower[cells])))
                        hi=min(1.,float(model.flux[i]*duration/model.f0t0*np.dot(coef,upper[cells])))
                        all_supported=bool(np.all(support[cells]>0));all_narrow=bool(np.all(narrow[cells]))
                        counts['candidates']+=1;counts['all_supported']+=all_supported;counts['all_narrow']+=all_narrow
                        best_lower=max(best_lower,lo);best_upper=max(best_upper,hi)
                        if all_supported:best_supported_upper=max(best_supported_upper,hi)
                        if lo<model.threshold:continue
                        is_clean=clean.clear(i,matrix.overlaps(start,duration))
                        counts['clean_certified']+=is_clean
                        if not is_clean:continue
                        counts['conditional_quota']+=1;best_clean_lower=max(best_clean_lower,lo)
                        cross_safe=not any(start<b_gap and start+duration>a_gap for a_gap,b_gap in gaps)
                        witness={'start_utc':stamp(start),'duration_seconds':duration,'factor_lower':lo,
                                 'factor_upper':hi,'all_cells_supported':all_supported,'all_cells_narrow':all_narrow,
                                 'clear_under_reference_domain':True,'outside_known_two_run_repair_gap':cross_safe,
                                 'site_normalized_quality_lower':float(np.dot(coef,lower[cells])),
                                 'supported_seconds_fraction':float(np.dot(coef,support[cells]>0)/max(np.sum(coef),1e-300)),
                                 'cell_indices':cells.tolist()}
                        if strongest is None or lo>strongest['factor_lower']:strongest=witness
                        if all_narrow and cross_safe and (strongest_narrow is None or lo>strongest_narrow['factor_lower']):strongest_narrow=witness
                        coupons.append(witness)
            category=('narrow_supported_conditional_witness' if strongest_narrow else
                      'interval_conditional_witness' if strongest else
                      'optimistic_supported_only' if best_supported_upper>=model.threshold else
                      'unsupported_or_unsampled_opportunity')
            records.append({'target_id':tid,'flux':float(model.flux[i]),'old_max_valid_factor':maxima.get(tid,0),
                'category':category,'counts':counts,'best_no_direction_factor_lower':best_lower,
                'best_clear_factor_lower':best_clean_lower,'best_optimistic_factor_upper':best_upper,
                'best_all_supported_optimistic_upper':best_supported_upper,
                'conditional_clear_witness':strongest,'narrow_cross_safe_witness':strongest_narrow,
                'top_conditional_coupons':sorted(coupons,key=lambda x:x['factor_lower'],reverse=True)[:4]})
        categories={c:sum(r['category']==c for r in records) for c in sorted(set(r['category'] for r in records))}
        out['cards'][card]={'old_official_missing':len(missing),'profile_sha256':hashlib.sha256(profile_path.read_bytes()).hexdigest(),
                           'repair_times':meta['repair_timestamps_utc'],'known_two_run_repair_gaps':[[stamp(a),stamp(b)] for a,b in gaps],
                           'categories':categories,'targets':records}
        print(json.dumps({'card':card,'categories':categories,'elapsed_seconds':time.perf_counter()-began}),flush=True)
    out['elapsed_seconds']=time.perf_counter()-began
    return out


if __name__=='__main__':
    root=Path(__file__).resolve().parents[2]
    result=audit(root)
    path=root/'formal_v4/results/required_quality_interval_20261003/audit.json'
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,indent=2))
