"""Public-bound counterexamples and conditional alpha multi-run W label merge.

Only published scorer/own outputs. No engine, hidden input, generator, network.
Cross-run pooling is explicitly conditional on the same W realization.
"""
from __future__ import annotations
import csv,hashlib,json,os,sys,time
from collections import defaultdict
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix,vstack
from program_band_interval_audit import labels,propagate
from quality_profile_inversion import all_target_model,PublicQualityMatrix
from required_opportunity_model import parse,stamp

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def lines(p):return [json.loads(s) for s in Path(p).read_text().splitlines() if s]

def merged_constraints(model,matrix,directories):
    rr=[];cc=[];vv=[];low=[];high=[];coverage=[];disjunctions=0
    for directory in directories:
        decisions={int(d['observe_index']):d for d in csv.DictReader((directory/'decisions.csv').open()) if d['action']=='observe'}
        grouped=defaultdict(list)
        for hit in csv.DictReader((directory/'observations.csv').open()):grouped[int(hit['observe_index'])].append(hit)
        counts=0
        for oi,hits in grouped.items():
            d=decisions[oi];cells,coef=matrix.coefficients(parse(d['start_utc']).timestamp(),int(d['duration_seconds']),[model.index[h['target_id']] for h in hits])
            for j,hit in enumerate(hits):
                lo,hi,meaning,strict=labels(d['program'],float(hit['prog_mult']))
                if lo is None:disjunctions+=1;continue
                row=len(low);low.append(max(0.,lo-1e-9));high.append(hi+1e-9);counts+=1
                for c,v in zip(cells,coef[j]):
                    if v>0:rr.append(row);cc.append(int(c));vv.append(float(v))
        coverage.append({'source':directory.name,'convex_rows':counts})
    return np.array(rr),np.array(cc),np.array(vv),np.array(low),np.array(high),coverage,disjunctions

def compare(first,second):
    def read(directory):
        ds={r['observe_index']:r for r in csv.DictReader((directory/'decisions.csv').open()) if r['action']=='observe'}
        obs={(ds[r['observe_index']]['start_utc'],ds[r['observe_index']]['end_utc'],r['target_id']):r
             for r in csv.DictReader((directory/'observations.csv').open())}
        actions=[r for r in lines(directory/'actions.jsonl') if r['action']=='observe']
        messages=lines(directory/'messages.jsonl')
        weather={(m['record_type'],m['issued_at_utc'],m.get('slot_id')):m for m in messages if m['record_type'] in ('bulletin','forecast')}
        repairs=[m['issued_at_utc'] for m in messages if m['record_type']=='report_result' and m.get('repaired')]
        return ds,obs,actions,weather,repairs
    ds1,obs1,a1,w1,r1=read(first);ds2,obs2,a2,w2,r2=read(second)
    prefix=0
    for i,(a,b) in enumerate(zip(a1,a2)):
        if a!=b or (ds1[str(i)]['start_utc'],ds1[str(i)]['end_utc'])!=(ds2[str(i)]['start_utc'],ds2[str(i)]['end_utc']):break
        prefix+=1
    common=obs1.keys()&obs2.keys();matched_program=0;different_multiplier=[];quality_delta=[]
    gap_quality=[];after_repairs=0
    gap=(min(r1[0],r2[0]),max(r1[0],r2[0])) if len(r1)==len(r2)==1 else None
    for key in common:
        a,b=obs1[key],obs2[key];d1=ds1[a['observe_index']];d2=ds2[b['observe_index']]
        if d1['program']==d2['program']:
            matched_program+=1
            if a['prog_mult']!=b['prog_mult']:different_multiplier.append({'key':key,'first':a['prog_mult'],'second':b['prog_mult']})
        quality_delta.append(abs(float(a['quality'])-float(b['quality'])))
        if gap and key[0]>=gap[0] and key[1]<=gap[1]:gap_quality.append(abs(float(a['quality'])-float(b['quality'])))
        if gap and key[0]>=gap[1]:after_repairs+=1
    wc=w1.keys()&w2.keys()
    return {'first':first.name,'second':second.name,'identical_timed_observe_action_prefix':prefix,
            'identical_target_start_end_rows':len(common),'paired_same_declared_program_rows':matched_program,
            'paired_same_program_different_multiplier_rows':len(different_multiplier),'differences':different_multiplier[:20],
            'paired_quality_max_absolute_difference':max(quality_delta,default=None),
            'paired_rows_within_repair_disagreement_gap':len(gap_quality),'paired_quality_max_difference_in_repair_gap':max(gap_quality,default=None),
            'paired_rows_after_both_repairs':after_repairs,
            'shared_bulletin_forecast_records':len(wc),'changed_shared_public_weather_records':sum(w1[k]!=w2[k] for k in wc),
            'first_repairs':r1,'second_repairs':r2,'scenario_hash_equal':load(first/'score_report.json')['sha256']['scenario']==load(second/'score_report.json')['sha256']['scenario'],
            'scope':'finite identical integrals/labels and public-message consistency; does not prove unseen weather truth equal'}

def synthetic_counterexamples(model,matrix):
    from challenge.v4_scorer import SlotTruth,WeatherTruth
    a,b=model.nights[0];start=parse(stamp(a+30));end=parse(stamp(a+330));site=model.initial['site']
    def trial(W,E):
        slot=SlotTruth('synthetic',parse(stamp(a)),parse(stamp(b)),True,1./W,1.,1.,E)
        weather=WeatherTruth([slot],None)
        band=weather.band_quality(start,end,model.score,lambda t:60.,lambda t:1.)
        return {'W':W,'E':E,'B':band,'clean_q_same_geometry':band*E,'seeing':1./W,
                'synthetic_slot_inputs_not_hidden_data':True}
    x,y=trial(1.,1e-3),trial(1e9,1e-12)
    assert abs(x['clean_q_same_geometry']-y['clean_q_same_geometry'])<1e-12
    assert y['E']>0 and y['B']>1e8
    return {'same_Z_different_W_and_E':[x,y],
            'universal_E_positive_floor_follows_from_public_scorer':False,
            'universal_W_upper_follows_from_public_scorer':False,
            'qualification':'Counterexamples are accepted by the scorer primitives; not claims about task-generator support.'}

def main(root):
    began=time.perf_counter();base=root/'formal_v4/practice_cards/alpha/alpha'
    model=all_target_model(base);matrix=PublicQualityMatrix(model,[])
    res=root/'formal_v4/results';directories=[res/n for n in ('cloud_cd2_alpha_20261003','cloud_phase_gpu_alpha_20261003',
          'cloud_request_gpu_alpha_20261003','cloud_verified_portfolio_alpha_20261003') if (res/n/'observations.csv').exists()]
    phase=res/'cloud_phase_gpu_alpha_20261003';portfolio=res/'cloud_verified_portfolio_alpha_20261003'
    comparisons=[compare(phase,d) for d in directories if d!=phase]
    portfolio_pair_checks=[compare(res/f'cloud_phase_gpu_{c}_20261003',res/f'cloud_verified_portfolio_{c}_20261003')
                           for c in ('alpha','beta','gamma') if (res/f'cloud_verified_portfolio_{c}_20261003/score_report.json').exists()]
    row,col,value,lo,hi,coverage,disjunctions=merged_constraints(model,matrix,directories)
    low,high,iterations,consistent=propagate(row,col,value,lo,hi,len(matrix.cells));assert consistent
    A=coo_matrix((value,(row,col)),shape=(len(lo),len(matrix.cells))).tocsr();ur=np.flatnonzero(np.isfinite(hi));lr=np.flatnonzero(lo>0)
    result=linprog(np.zeros(len(matrix.cells)),A_ub=vstack((A[ur],-A[lr])),b_ub=np.r_[hi[ur],-lo[lr]],bounds=list(zip(low,high)),method='highs')
    assert result.success,result.message
    upper_support=np.bincount(col[np.isfinite(hi[row])],minlength=len(matrix.cells));assert np.array_equal(~np.isfinite(high),upper_support==0)
    original=np.load(res/'program_band_interval_20261003/alpha/band_W_outer_intervals.npz')
    pool=load(res/'best_incumbent_alpha_master_20261003/column_pool.json');bounds=[];finite_count=0;excluded=0;total_reduction=0.
    columns=model.initial['targets']['columns'];weight_col=columns.index('science_weight')
    for c in pool:
        if c['kind']=='historical':continue
        tids=list(c['entries']);cells,coef=matrix.coefficients(c['start'],c['end']-c['start'],[model.index[t] for t in tids])
        for j,tid in enumerate(tids):
            uncertain=np.any((coef[j]>0)&~np.isfinite(high[cells]));upper=None if uncertain else float(coef[j]@high[cells])
            dark_possible=upper is None or upper>=.65-1e-8;finite_count+=upper is not None;excluded+=not dark_possible
            weight=float(model.initial['targets']['rows'][model.index[tid]][weight_col]);e=c['entries'][tid]
            refined=weight*e['factor_upper']*(1.2 if dark_possible else 1.);reduction=max(0.,e['score_upper']-refined);total_reduction+=reduction
            bounds.append({'start':c['start'],'end':c['end'],'target_id':tid,'B_upper_under_shared_W_assumption':upper,
                           'DARK_possible':dark_possible,'score_upper_reduction':reduction})
    out=res/'public_W_bounds_merge_20261003';out.mkdir(exist_ok=True)
    np.savez_compressed(out/'conditional_shared_alpha_W.npz',cell_start=matrix.starts,cell_end=matrix.ends,lower=low,upper=high,
                        row=row,col=col,coefficient=value,row_lower=lo,row_upper=hi,finite_upper_constraint_support=upper_support)
    (out/'alpha_coupon_bounds.json').write_text(json.dumps(bounds,indent=2)+'\n')
    summary={'card':'alpha','cross_run_W_pool_is_conditional':True,'repair_cuts_used':False,'rows':len(lo),'coverage':coverage,
             'omitted_exact_BRIGHT_mismatch_disjunctions':disjunctions,'conditional_joint_convex_LP_feasible':True,
             'finite_upper_cells_before':int(np.isfinite(original['upper']).sum()),'finite_upper_cells_merged':int(np.isfinite(high).sum()),
             'unbounded_ray_cells_merged':int((upper_support==0).sum()),'interval_iterations':iterations,
             'own_run_finite_consistency':comparisons,'new_portfolio_pair_checks':portfolio_pair_checks,
             'coupon_target_rows':len(bounds),'coupon_finite_B_upper_rows':int(finite_count),
             'coupon_DARK_excluded_rows':int(excluded),'sum_per_column_score_upper_reduction_under_shared_W':total_reduction,
             'not_a_schedule_or_competition_score_change':True,'synthetic_counterexamples':synthetic_counterexamples(model,matrix),
             'hidden_inputs_read':False,'generator_read':False,'source_sha256':sha(__file__),
             'own_output_input_sha256':{str(p.relative_to(root)):sha(p) for d in directories for p in [d/n for n in ('observations.csv','decisions.csv','messages.jsonl','actions.jsonl','score_report.json')]},
             'public_bound_sources_sha256':{str(p.relative_to(root)):sha(p) for p in [
                 root/'formal_v4/upstream/gosim-observer-examples/docs/participant-guide.zh.md',
                 root/'formal_v4/upstream/gosim-observer-examples/runner/challenge/v4_scorer.py',
                 root/'formal_v4/upstream/gosim-observer-examples/runner/challenge/v4_config_check.py']},
             'elapsed_seconds':time.perf_counter()-began}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))

if __name__=='__main__':
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'formal_v4/upstream/gosim-observer-examples/runner'));main(root)
