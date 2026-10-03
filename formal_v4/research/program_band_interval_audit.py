"""Independent band-quality W constraints from our own public prog_mult labels.

W has public slot cells without repair cuts, unlike effective-quality Z=E*W.
No hidden data, generator bounds, finite weather cap, production or network.
BRIGHT mismatch is recorded as a disjunction, excluded from the convex outer LP.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,os,sys,time
from collections import Counter,defaultdict
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from quality_profile_inversion import all_target_model,PublicQualityMatrix
from required_opportunity_model import parse,stamp


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def labels(program,multiplier,dark=.65,bright=.4):
    expected={'DARK':1.2,'BRIGHT':1.12,'BACKUP':1.06}
    if abs(multiplier-expected[program])<1e-10:
        if program=='DARK':return dark,np.inf,'DARK matched',False
        if program=='BRIGHT':return bright,dark,'BRIGHT matched; upper strict',True
        return 0.,bright,'BACKUP matched; upper strict',True
    assert abs(multiplier-1.)<1e-10,'unknown multiplier'
    if program=='DARK':return 0.,dark,'DARK mismatch; upper strict',True
    if program=='BACKUP':return bright,np.inf,'BACKUP mismatch',False
    return None,None,'BRIGHT mismatch; B<bright OR B>=dark',True


def propagate(row,col,value,lo,hi,n,iterations=300):
    low=np.zeros(n);high=np.full(n,np.inf)
    for it in range(iterations):
        finite=np.isfinite(high);h=np.where(finite,high,0.)
        rowlow=np.bincount(row,weights=value*low[col],minlength=len(lo))
        rowhigh=np.bincount(row,weights=value*h[col],minlength=len(lo))
        rowinf=np.bincount(row,weights=(~finite[col]).astype(int),minlength=len(lo))
        canlow=np.where(rowinf[row]-(~finite[col]).astype(int)==0,
                        (lo[row]-rowhigh[row]+value*h[col])/value,-np.inf)
        canhigh=(hi[row]-rowlow[row]+value*low[col])/value
        newlow,newhigh=low.copy(),high.copy()
        np.maximum.at(newlow,col,canlow);np.minimum.at(newhigh,col,canhigh)
        if np.any(newlow>newhigh+1e-8):return newlow,newhigh,it+1,False
        finite_same=np.array_equal(np.isfinite(newhigh),finite)
        change=max(float(np.max(np.abs(newlow-low))),float(np.max(np.abs(newhigh[finite]-high[finite]))) if finite.any() else 0.)
        low,high=newlow,newhigh
        if finite_same and change<1e-12:break
    return low,high,it+1,True


def official_oracle(model,matrix):
    from challenge.v4_scorer import SlotTruth,WeatherTruth,lunar_quality_factor
    from challenge.v4_fiber_map import radec_to_altaz
    site={'latitude_deg':model.latitude,'longitude_deg':model.longitude}
    # Synthetic, explicitly chosen W. No engine or scenario truth construction.
    values=np.linspace(.15,.9,len(matrix.cells));slots=[]
    for j,(_,_,a,b) in enumerate(matrix.cells):
        slots.append(SlotTruth(str(j),parse(stamp(a)),parse(stamp(b)),True,1.,float(values[j]),1.,.07))
    weather=WeatherTruth(slots,None);error=[]
    for night in range(min(3,len(model.nights))):
        a,b=model.nights[night]
        for shift,duration in ((17,83),(853,163),(1766,1103)):
            start=a+shift;end=start+duration
            if end>b:continue
            ids=np.flatnonzero((model._alt([start],np.arange(len(model.ids)))[0]>=model.minimum_altitude+1)
                               &(model._alt([end],np.arange(len(model.ids)))[0]>=model.minimum_altitude+1))[:2]
            assert len(ids)==2
            cells,coef=matrix.coefficients(start,duration,ids);predicted=coef@values[cells]
            for k,i in enumerate(ids):
                actual=weather.band_quality(parse(stamp(start)),parse(stamp(end)),model.score,
                    lambda moment,i=i:radec_to_altaz(model.ra[i],model.dec[i],moment,model.latitude,model.longitude)[0],
                    lambda moment,i=i:lunar_quality_factor(model.ra[i],model.dec[i],moment,site,model.score))
                error.append(abs(actual-float(predicted[k])))
    assert max(error)<1e-8, max(error)
    return {'synthetic_official_band_quality_checks':len(error),'max_error':max(error),'instrument_efficiency':.07,
            'interpretation':'Changing E does not enter the W band matrix; synthetic chosen slot values only.'}


def run_card(root,card,kind,out):
    began=time.perf_counter();base=root/'formal_v4/practice_cards'/card/card
    directory=root/'formal_v4/results'/f'cloud_{kind}_gpu_{card}_20261003'
    model=all_target_model(base);matrix=PublicQualityMatrix(model,[])
    decisions={int(d['observe_index']):d for d in csv.DictReader((directory/'decisions.csv').open()) if d['action']=='observe'}
    groups=defaultdict(list);all_rows=[]
    for hit in csv.DictReader((directory/'observations.csv').open()):groups[int(hit['observe_index'])].append(hit);all_rows.append(hit)
    rr=[];cc=[];vv=[];lo=[];hi=[];metadata=[];disjunctions=[];counts=Counter()
    for observe,hits in groups.items():
        d=decisions[observe];start=parse(d['start_utc']).timestamp();duration=int(d['duration_seconds'])
        cells,coef=matrix.coefficients(start,duration,[model.index[h['target_id']] for h in hits])
        for j,hit in enumerate(hits):
            lower,upper,meaning,strict=labels(d['program'],float(hit['prog_mult']))
            counts[meaning]+=1
            tag={'observe_index':observe,'target_id':hit['target_id'],'program':d['program'],
                 'prog_mult':float(hit['prog_mult']),'upper_strict':strict,'meaning':meaning,
                 'start_utc':d['start_utc'],'end_utc':d['end_utc'],'valid_ledger':hit['valid']=='true',
                 'cells':cells.tolist(),'coefficients':coef[j].tolist()}
            if lower is None:disjunctions.append(tag);continue
            # Closed outer inequalities retain every strict original label.
            row=len(lo);lo.append(max(0.,lower-1e-9));hi.append(upper+1e-9)
            metadata.append(tag)
            for cell,value in zip(cells,coef[j]):
                if value>0:rr.append(row);cc.append(int(cell));vv.append(float(value))
    row,col,value=np.array(rr),np.array(cc),np.array(vv);lo,hi=np.array(lo),np.array(hi)
    A=coo_matrix((value,(row,col)),shape=(len(lo),len(matrix.cells))).tocsr()
    low,high,iterations,consistent=propagate(row,col,value,lo,hi,len(matrix.cells))
    assert consistent
    upper_rows=np.flatnonzero(np.isfinite(hi));lower_rows=np.flatnonzero(lo>0)
    upper_support=np.bincount(col[np.isfinite(hi[row])],minlength=len(matrix.cells))
    # A cell missing from every finite-upper row has an unbounded positive ray.
    # Finite-upper rows have positive coefficients and W>=0, so they would by
    # themselves give a finite upper bound to each cell they touch.
    assert np.array_equal(~np.isfinite(high),upper_support==0)
    from scipy.sparse import vstack
    result=linprog(np.zeros(len(matrix.cells)),A_ub=vstack([A[upper_rows],-A[lower_rows]]),
                   b_ub=np.r_[hi[upper_rows],-lo[lower_rows]],bounds=list(zip(low,high)),method='highs')
    assert result.success,result.message
    predicted=A@result.x
    constraint_error=max(float(np.max(np.maximum(lo-predicted,0))),float(np.max(np.maximum(predicted[np.isfinite(hi)]-hi[np.isfinite(hi)],0))))
    assert constraint_error<1e-7
    directory_out=out/card;directory_out.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(directory_out/'band_W_outer_intervals.npz',cell_start=matrix.starts,cell_end=matrix.ends,
                        lower=low,upper=high,row=row,col=col,coefficient=value,row_lower=lo,row_upper=hi,
                        one_convex_feasible_point=result.x,finite_upper_constraint_support=upper_support)
    (directory_out/'label_metadata.json').write_text(json.dumps({'convex_rows':metadata,'omitted_exact_disjunctions':disjunctions},separators=(',',':'))+'\n')
    summary={'card':card,'source_run':str(directory.relative_to(root)),'W_definition':'transparency * sky_quality / seeing; 0 for closed slots',
             'repair_cuts_used':False,'E_in_band_matrix':False,'finite_W_cap_assumed':False,'slot_cells':len(matrix.cells),
             'raw_prog_mult_labels':len(all_rows),'convex_constraint_rows':len(lo),'label_counts':dict(counts),
             'convex_rows_from_invalidated_data':sum(not m['valid_ledger'] for m in metadata),
             'raw_label_rows_from_zero_quality':sum(float(r['quality'])==0 for r in all_rows),
             'positive_lower_cells':int((low>1e-8).sum()),'finite_upper_cells':int(np.isfinite(high).sum()),
             'unbounded_upper_cells':int((~np.isfinite(high)).sum()),'propagation_iterations':iterations,
             'exact_label_unbounded_ray_cells':int((upper_support==0).sum()),
             'convex_LP_feasible':True,'convex_LP_max_constraint_violation':constraint_error,
             'convex_point_not_certified_for_omitted_disjunctions':True,'strict_upper_relaxed_to_closed_for_outer_bounds':True,
             'official_band_quality_oracle':official_oracle(model,matrix),'hidden_inputs_read':False,
             'source_sha256':sha(__file__),'elapsed_seconds':time.perf_counter()-began}
    if card=='alpha':
        pool_path=root/'formal_v4/results/best_incumbent_alpha_master_20261003/column_pool.json'
        pool=load(pool_path);candidate_results=[];nexcluded=0;total_reduction=0.;finite_band=0;new_targets=0
        for c in pool:
            if c['kind']=='historical':continue
            tids=list(c['entries']);cells,coef=matrix.coefficients(c['start'],c['end']-c['start'],[model.index[t] for t in tids])
            band_low=coef@low[cells]
            band_high=np.sum(np.where(coef>0,coef*np.where(np.isfinite(high[cells]),high[cells],0),0),axis=1)
            unknown=np.any((coef>0)&(~np.isfinite(high[cells]))[None,:],axis=1);band_high[unknown]=np.inf
            possible_dark=band_high>=.65-1e-8
            refined={};reduction=0.
            for j,tid in enumerate(tids):
                e=c['entries'][tid];mult=1.2 if possible_dark[j] else 1.
                upper=float(model.initial['targets']['rows'][model.index[tid]][model.initial['targets']['columns'].index('science_weight')])*e['factor_upper']*mult
                change=e['score_upper']-upper;assert change>=-1e-8
                reduction+=max(0.,change);nexcluded+=not possible_dark[j];finite_band+=np.isfinite(band_high[j]);new_targets+=1
                ray_cells=cells[(coef[j]>0)&(upper_support[cells]==0)]
                refined[tid]={'band_lower':float(band_low[j]),'band_upper':float(band_high[j]) if np.isfinite(band_high[j]) else None,
                              'positive_unbounded_ray_cell_indices':ray_cells.tolist(),
                              'DARK_possible_outer':bool(possible_dark[j]),'old_score_upper':e['score_upper'],'new_fixed_DARK_score_upper':upper}
            total_reduction+=reduction;candidate_results.append({'start':c['start'],'end':c['end'],'anchor_required':c['anchor_required'],
                                                               'upper_sum_reduction':reduction,'target_bounds':refined})
        (directory_out/'alpha_coupon_band_bounds.json').write_text(json.dumps(candidate_results,indent=2)+'\n')
        summary['alpha_coupon_audit']={'conditional_coupon_columns':len(candidate_results),'assigned_target_rows':new_targets,
                                      'finite_band_upper_rows':int(finite_band),'DARK_excluded_rows':int(nexcluded),
                                      'sum_per_column_science_upper_reduction':total_reduction,
                                      'all_assigned_rows_have_exact_label_positive_unbounded_ray':bool(finite_band==0),
                                      'not_a_schedule_or_competition_score_gain':True,'column_pool_sha256':sha(pool_path)}
    (directory_out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False),flush=True);return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cards',nargs='+',default=['alpha','beta','gamma','delta']);args=p.parse_args()
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'formal_v4/upstream/gosim-observer-examples/runner'))
    out=root/'formal_v4/results/program_band_interval_20261003'
    summaries=[run_card(root,c,'request' if c=='delta' else 'phase',out) for c in args.cards]
    (out/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
