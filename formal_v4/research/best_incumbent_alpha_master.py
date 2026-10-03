"""Fresh alpha finite master from the best own legal Phase result.

Pure solver helpers are reused, never card_master/capture or module mutation.
Old quality intervals are only conditional, and must pass a new-run measured
integral gate before any old coupon is admitted. No hidden data or network.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,os,sys,time
from collections import defaultdict
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import numpy as np
from best_incumbent_rebase_audit import audit
from quality_profile_inversion import (all_target_model,PublicQualityMatrix,ReferenceClearFilter,cross_validate_profile)
from required_opportunity_model import parse,stamp
from request_remote_owned_gate import initial_public
from spatial_candidates import SpatialPlanner,local_sidereal,SIDEREAL_SPEED,_shift_altaz
from season_science_required_master import solve_master,settle
from season_column_dual_audit import lp_duals,reduced_cost


def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def json_read(p):return json.loads(Path(p).read_text())
def lines(p):return [json.loads(s) for s in Path(p).read_text().splitlines() if s]


def build(root,out,with_coupons=True):
    began=time.perf_counter();card=root/'formal_v4/practice_cards/alpha/alpha'
    directory=root/'formal_v4/results/cloud_phase_gpu_alpha_20261003'
    old=root/'formal_v4/results/cloud_cd2_alpha_20261003'
    source=json_read(directory/'score_report.json');messages=lines(directory/'messages.jsonl')
    assert not any(m['record_type']=='state_resync' for m in messages)
    initial,public_sources=initial_public(card);model=all_target_model(card)
    model.actual_required=[r['target_id'] for r in csv.DictReader((card/'public/targets.csv').open()) if r['required'].lower()=='true']
    planner=SpatialPlanner(initial)
    decisions=[d for d in csv.DictReader((directory/'decisions.csv').open())]
    observes=[d for d in decisions if d['action']=='observe']
    actions=[a for a in lines(directory/'actions.jsonl') if a['action']=='observe']
    hits=defaultdict(list)
    for r in csv.DictReader((directory/'observations.csv').open()):hits[int(r['observe_index'])].append(r)
    assert len(observes)==len(actions)==1184
    report_times=[parse(d['start_utc']).timestamp() for d in decisions if d['action']=='report']
    repairs=[parse(m['issued_at_utc']).timestamp() for m in messages if m['record_type']=='report_result' and m.get('correct') and m.get('repaired')]
    assert repairs==report_times
    requests=[m for m in messages if m['record_type']=='observation_request']
    columns=[]
    for j,(d,action) in enumerate(zip(observes,actions)):
        assert int(d['observe_index'])==j
        entries={e['target_id']:{'score_lower':float(e['score']),'score_upper':float(e['score'])+0.0000005,
                                'factor_lower':float(e['factor']),'factor_upper':min(1.,float(e['factor'])+0.0000005),
                                'score_csv':float(e['score']),'factor_csv':float(e['factor'])}
                 for e in hits[j] if e['valid']=='true'}
        columns.append({'kind':'historical','old_observe_index':j,'start':parse(d['start_utc']).timestamp(),
                        'end':parse(d['end_utc']).timestamp(),'action':action,'entries':entries})
    historical_count=len(columns)
    baseline=settle(columns,list(range(historical_count)),model,requests,source['components']['report_settlement'])
    reconstructed,_=audit(root,'alpha','phase')
    assert abs(baseline['total_conditional_conservative']-reconstructed['reconstructed_total_csv'])<1e-8
    out.mkdir(parents=True,exist_ok=True)
    profile_path=root/'formal_v4/research/quality_profile_alpha_result.npz'
    profile_meta=root/'formal_v4/research/quality_profile_alpha_result.json'
    validation=cross_validate_profile(card,profile_path,old,directory) if with_coupons else {'scope':'historical-only; profile not used'}
    (out/'profile_cross_validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    stats={'enabled':with_coupons,'new_columns':0,'official_fiber_checks':0,'official_whole_visibility_checks':0,
           'candidate_rejected_repair_gap':0,'candidate_rejected_unsupported_cell':0,
           'no_hidden_weather_offset_certificate':True,'quality_gate_required':True}
    profile_accepted=(with_coupons and validation.get('validated_positive_quality_rows',0)>0
                      and validation.get('outside_previous_conditional_interval_rows',1)==0
                      and not validation.get('repair_history_length_mismatch',False))
    stats['prior_conditional_profile_measured_gate_passed']=profile_accepted
    if profile_accepted:
        from challenge.v4_fiber_map import FiberGrid,min_altitude_during
        old_profile=np.load(profile_path);meta=json_read(profile_meta)
        old_matrix=PublicQualityMatrix(model,[parse(t).timestamp() for t in meta['repair_timestamps_utc']])
        matrix=PublicQualityMatrix(model,repairs)
        assert np.array_equal(old_profile['cell_start'],old_matrix.starts)
        assert np.array_equal(old_profile['cell_end'],old_matrix.ends)
        gaps=[(parse(a).timestamp(),parse(b).timestamp()) for a,b in validation['repair_gap_utc']]
        low=np.full(len(matrix.cells),np.nan);high=low.copy();support=np.zeros(len(matrix.cells),dtype=np.int32)
        # Entire new cells touching the repair disagreement are rejected. Outside
        # them a new cell must be wholly contained in one old supported cell.
        for j,(a,b) in enumerate(zip(matrix.starts,matrix.ends)):
            if any(a<d and b>c for c,d in gaps):continue
            k=int(np.searchsorted(old_matrix.starts,(a+b)/2,side='right')-1)
            if k<0 or a<old_matrix.starts[k]-1e-7 or b>old_matrix.ends[k]+1e-7:continue
            if old_profile['support'][k]<=0 or old_profile['upper'][k]-old_profile['lower'][k]>1e-4:continue
            low[j]=old_profile['lower'][k];high[j]=old_profile['upper'][k];support[j]=old_profile['support'][k]
        np.savez_compressed(out/'conditional_profile_new_repair_cells.npz',cell_start=matrix.starts,cell_end=matrix.ends,
                            lower=low,upper=high,support=support)
        stats['mapped_narrow_supported_new_cells']=int((support>0).sum())
        clear=ReferenceClearFilter(model,messages);grid=FiberGrid(planner.glass**2,planner.pitch-planner.glass,planner.nfib)
        coupon_path=root/'formal_v4/results/required_quality_interval_20261003/audit.json'
        stats['coupon_source_sha256']=digest(coupon_path);seen=set()
        for target in json_read(coupon_path)['cards']['alpha']['targets']:
            anchor=model.index[target['target_id']]
            for witness in target['top_conditional_coupons']:
                start=parse(witness['start_utc']).timestamp();duration=int(witness['duration_seconds']);end=start+duration
                if any(start<d and end>c for c,d in gaps):stats['candidate_rejected_repair_gap']+=1;continue
                if any(start<t<end for t in report_times):continue
                # The fresh repair partition is used for all new coefficients.
                cells,_=matrix.coefficients(start,duration,[anchor])
                if np.any(support[cells]<=0):stats['candidate_rejected_unsupported_cell']+=1;continue
                now=parse(stamp(start));alt,az,hour,vectors=planner._altaz(local_sidereal(now,planner.lon))
                up=np.where(planner.hmax>=180,1e9,(planner.hmax-hour)/SIDEREAL_SPEED)
                for row in range(planner.side):
                    for col in range(planner.side):
                        center=_shift_altaz(alt[anchor],az[anchor],-(row-(planner.side-1)/2)*planner.pitch,-(col-(planner.side-1)/2)*planner.pitch)
                        fiber,valid,margin=planner._classify(vectors,*center)
                        pool=np.flatnonzero(valid&(alt>=planner.min_alt+.04)&(up>=duration)&(margin>.03))
                        if anchor not in pool:continue
                        cells,coef=matrix.coefficients(start,duration,pool)
                        assert np.all(support[cells]>0)
                        qlo=coef@low[cells];qhi=coef@high[cells]
                        glo=np.minimum(1.,planner.flux[pool]*duration/planner.f0t0*qlo)
                        ghi=np.minimum(1.,planner.flux[pool]*duration/planner.f0t0*qhi)
                        overlaps=matrix.overlaps(start,duration)
                        good=np.array([clear.clear(int(i),overlaps) for i in pool]);eligible=np.flatnonzero(good)
                        assignment={};entries={};selected_margins=[]
                        for fid in np.unique(fiber[pool[eligible]]):
                            candidates=eligible[fiber[pool[eligible]]==fid];is_anchor=candidates[pool[candidates]==anchor]
                            if len(is_anchor):j=int(is_anchor[0])
                            else:
                                value=planner.weight[pool[candidates]]*glo[candidates]*np.where(qlo[candidates]>=planner.dark_threshold,1.2,1.)
                                j=int(candidates[np.argmax(value)])
                            i=int(pool[j]);tid=model.ids[i]
                            hit=grid.classify_target(model.ra[i],model.dec[i],now,*center,planner.lat,planner.lon)
                            assert hit.region=='glass' and hit.fiber_id==int(fid)
                            minimum=min_altitude_during(model.ra[i],model.dec[i],now,parse(stamp(end)),{'site':initial['site']})
                            if minimum<planner.min_alt-1e-8:continue
                            stats['official_fiber_checks']+=1;stats['official_whole_visibility_checks']+=1
                            assignment[str(int(fid))]=tid;selected_margins.append(float(margin[i]))
                            entries[tid]={'factor_lower':float(glo[j]),'factor_upper':float(ghi[j]),
                                          'score_lower':float(planner.weight[i]*glo[j]*(1.2 if qlo[j]>=planner.dark_threshold else 1.)),
                                          'score_upper':float(planner.weight[i]*ghi[j]*1.2)}
                        if target['target_id'] not in entries or entries[target['target_id']]['factor_lower']<.5:continue
                        key=(start,end,tuple(sorted(assignment.items())))
                        if key in seen:continue
                        seen.add(key)
                        columns.append({'kind':'latest-best-conditional-coupon','start':start,'end':end,'entries':entries,
                                        'action':{'action':'observe','pointing':{'alt_deg':center[0],'az_deg':center[1]},
                                                  'duration_seconds':duration,'assignments':assignment,'program':'DARK'},
                                        'anchor_required':target['target_id'],'minimum_assigned_fiber_margin_deg':min(selected_margins),
                                        'pointing_offset_assumption':'zero actual offset; >.03deg glass margin; conditional reference geometry',
                                        'quality_scope':'old narrow interval passed latest measured q gate; not complete hidden-weather truth certificate'})
        stats['new_columns']=len(columns)-historical_count
    (out/'column_pool.json').write_text(json.dumps(columns,separators=(',',':'))+'\n')
    solution,dual,dual_stats=lp_duals(columns,model,requests,[])
    prices=[reduced_cost(c,dual,requests)[0] for c in columns]
    nonbasic=[j for j in range(len(columns)) if solution.x[j]<1e-9]
    dual_stats.update(existing_columns=len(columns),existing_nonbasic=len(nonbasic),
                      existing_nonbasic_max_reduced_profit=max((prices[j] for j in nonbasic),default=0.),
                      existing_unfixed_max_reduced_profit=max(prices))
    assert dual_stats['max_stationarity_residual']<1e-7
    assert dual_stats['dual_primal_objective_residual']<1e-7
    assert dual_stats['existing_nonbasic_max_reduced_profit']<1e-7
    mip,mip_stats=solve_master(columns,model,requests,[],'lower',90)
    proposed=[j for j in range(len(columns)) if mip.x is not None and mip.x[j]>.5] if mip.x is not None else list(range(historical_count))
    proposed_settlement=settle(columns,proposed,model,requests,source['components']['report_settlement'])
    bound=reconstructed['total_error_bound_including_official_rounding']
    incumbent_kept=proposed_settlement['total_conditional_conservative']<=baseline['total_conditional_conservative']+2*bound
    selected=list(range(historical_count)) if incumbent_kept else proposed
    ordered=sorted(selected,key=lambda j:columns[j]['start'])
    assert all(columns[a]['end']<=columns[b]['start'] for a,b in zip(ordered,ordered[1:]))
    summary={'card':'alpha','baseline_source':str(directory.relative_to(root)),'baseline_official_total':source['total'],
             'baseline_reconstructed':baseline,'baseline_rounding_error_bound':bound,'historical_columns':historical_count,
             'conditional_new_column_gate':stats,'profile_cross_validation_sha256':digest(out/'profile_cross_validation.json'),
             'finite_optimistic_lp_upper_without_uniformity':-solution.fun-50*len(model.actual_required)+source['components']['report_settlement'],
             'dual_audit':dual_stats,'mip_status':int(mip.status),'mip_gap':getattr(mip,'mip_gap',None),'mip_stats':mip_stats,
             'proposed_settlement_with_actual_Jain':proposed_settlement,'proposed_new_column_indices':[j-historical_count for j in proposed if j>=historical_count],
             'incumbent_kept':incumbent_kept,'retained_settlement':settle(columns,selected,model,requests,source['components']['report_settlement']),
             'fixed_report_times_utc':[stamp(t) for t in report_times], 'fixed_successful_repair_times_utc':[stamp(t) for t in repairs],
             'uniformity_in_MIP_objective':False,'uniformity_recomputed_after_MIP':True,'new_official_replay_performed':False,
             'hidden_inputs_read':False,'global_upper_bound_available':False,'conditional_program_lower_assumption':'clean reference geometry, effective E<=1; DARK band if lower effective quality>=dark threshold, otherwise mismatch multiplier=1',
             'public_sources_sha256':public_sources,'profile_sha256':digest(profile_path), 'source_sha256':digest(__file__),
             'column_pool_sha256':digest(out/'column_pool.json'),'elapsed_seconds':time.perf_counter()-began}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    exported={'card':'alpha','target_order':model.ids,'rho':[dual['rho'].get(tid,0.) for tid in model.ids],
              'required_nu':[dual['nu'].get(tid,0.) for tid in model.ids],
              'request_eta':[[dual['eta'].get((r,tid),0.) for tid in model.ids] for r in range(len(requests))],
              'requests':requests,'time_nodes':sorted(dual['potential']),
              'time_potential':[dual['potential'][t] for t in sorted(dual['potential'])],
              'time_arc_cost_definition':'potential[end] - potential[start]; fresh scipy equality marginals for this pool',
              'fixed_column_indices':[],'baseline_source':str(directory.relative_to(root)),
              'column_pool_sha256':digest(out/'column_pool.json'), 'hypothesis':'latest-alpha optimistic finite pool; conditional new columns, original new-best report/E history; no hidden offset guarantee',
              'admissibility':{'fixed_report_times':report_times,'new_column_must_not_straddle_report':True,
                              'pricing_endpoints_must_be_existing_time_nodes':True,'repair_disagreement_gap_utc':validation.get('repair_gap_utc',[]),
                              'conditional_mapped_profile':'conditional_profile_new_repair_cells.npz' if profile_accepted else None}}
    (out/'pricing_duals.json').write_text(json.dumps(exported,indent=2)+'\n')
    schedule=[{'start_utc':stamp(columns[j]['start']),'end_utc':stamp(columns[j]['end']),'kind':columns[j]['kind'],'action':columns[j]['action']} for j in ordered]
    schedule += [{'start_utc':stamp(t),'end_utc':stamp(t),'kind':'fixed-report','action':{'action':'report'}} for t in report_times]
    (out/'retained_schedule.json').write_text(json.dumps(sorted(schedule,key=lambda s:(s['start_utc'],s['kind'])),indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--historical-only',action='store_true');parser.add_argument('--out',type=Path)
    args=parser.parse_args();root=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root/'formal_v4/upstream/gosim-observer-examples/runner'))
    build(root,args.out or root/'formal_v4/results/best_incumbent_alpha_master_20261003',not args.historical_only)
