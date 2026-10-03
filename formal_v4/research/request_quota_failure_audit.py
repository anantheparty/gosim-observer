"""Own-output REQ forensic audit and delta rank-preserving conditional exchange.

No hidden products or scenario engine. New one-for-one columns are predictions,
not official observations. Original report/time/count/rank are unchanged.
"""
from __future__ import annotations
import csv,hashlib,json,os,sys,time
from collections import defaultdict
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
import numpy as np
from quality_profile_inversion import all_target_model,PublicQualityMatrix,ReferenceClearFilter
from request_remote_owned_gate import initial_public
from required_opportunity_model import parse,stamp
from spatial_candidates import SpatialPlanner,local_sidereal,_shift_altaz

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def lines(p):return [json.loads(l) for l in Path(p).read_text().splitlines() if l]
def csvrows(p):return list(csv.DictReader(Path(p).open()))

def request_audit(directory):
    ds={int(d['observe_index']):d for d in csvrows(directory/'decisions.csv') if d['action']=='observe'}
    acts=[a for a in lines(directory/'actions.jsonl') if a['action']=='observe'];obs=csvrows(directory/'observations.csv')
    messages=lines(directory/'messages.jsonl');rq=[m for m in messages if m['record_type']=='observation_request']
    statuses=[]
    for r in rq:
        targets=[];raw_completed=[];valid_completed=[]
        for tid in r['target_ids']:
            hit=[h for h in obs if h['target_id']==tid and r['issued_at_utc']<=ds[int(h['observe_index'])]['start_utc'] and ds[int(h['observe_index'])]['end_utc']<=r['deadline_utc']]
            valid=[h for h in hit if h['valid']=='true'];maxraw=max((float(h['factor']) for h in hit),default=0.);maxvalid=max((float(h['factor']) for h in valid),default=0.)
            assigned=[j for j,a in enumerate(acts) if tid in a['assignments'].values() and r['issued_at_utc']<=ds[j]['start_utc'] and ds[j]['end_utc']<=r['deadline_utc']]
            if maxraw>=r['completion_factor_threshold']:raw_completed.append(tid)
            if maxvalid>=r['completion_factor_threshold']:valid_completed.append(tid)
            reason=('completed_final' if maxvalid>=r['completion_factor_threshold'] else 'qualified_hit_invalidated_later' if maxraw>=r['completion_factor_threshold'] else 'actual_hits_below_factor_threshold' if hit else 'no_assignments_inside_full_request_window' if not assigned else 'assigned_but_no_geometric_hit_row; offset/glass/visibility not separated')
            targets.append({'target_id':tid,'max_raw_factor_whole_window':maxraw,'max_final_valid_factor_whole_window':maxvalid,
                            'assigned_whole_window_indices':assigned,'failure_evidence':reason,'hit_rows':hit})
        official=next(s for s in load(directory/'score_report.json')['observation_requests'] if s['request_id']==r['request_id'])
        assert valid_completed==official['completed_target_ids']
        statuses.append({'request':r,'raw_before_invalidation_completed':raw_completed,'final_valid_completed':valid_completed,
                         'raw_quorum_met':len(raw_completed)>=r['minimum_completed'],'final_quorum_met':len(valid_completed)>=r['minimum_completed'],
                         'official_reward':official['reward'],'targets':targets})
    return {'run':directory.name,'requests':statuses,'resync_messages':[{k:v for k,v in m.items() if k in ('record_type','issued_at_utc','trigger_event_id','invalidated_window')} for m in messages if m['record_type']=='state_resync'],
            'input_sha256':{n:sha(directory/n) for n in ('observations.csv','decisions.csv','messages.jsonl','actions.jsonl','score_report.json')}}

def search(root,out,anchor_targets=None,stem='delta_one_for_one'):
    from challenge.v4_fiber_map import FiberGrid,min_altitude_during
    began=time.perf_counter();directory=root/'formal_v4/results/cloud_request_gpu_delta_20261003';card=root/'formal_v4/practice_cards/delta/delta'
    initial,_=initial_public(card);model=all_target_model(card);planner=SpatialPlanner(initial);grid=FiberGrid(planner.glass**2,planner.pitch-planner.glass,planner.nfib)
    ds=[d for d in csvrows(directory/'decisions.csv') if d['action']=='observe'];acts=[a for a in lines(directory/'actions.jsonl') if a['action']=='observe']
    messages=lines(directory/'messages.jsonl');requests=[m for m in messages if m['record_type']=='observation_request'];rq=requests[0]
    observations=csvrows(directory/'observations.csv');groups=defaultdict(list)
    for h in observations:groups[int(h['observe_index'])].append(h)
    profile_path=root/'formal_v4/research/quality_profile_delta_result.npz';profile=np.load(profile_path);meta=load(profile_path.with_suffix('.json'))
    validation=load(out/'delta_profile_cross_validation.json');assert validation['outside_previous_conditional_interval_rows']==0 and validation['validated_positive_quality_rows']>0
    matrix=PublicQualityMatrix(model,[parse(t).timestamp() for t in meta['repair_timestamps_utc']]);clear=ReferenceClearFilter(model,messages)
    assert np.array_equal(profile['cell_start'],matrix.starts)
    targetids=rq['target_ids'];reqpos={tid:k for k,tid in enumerate(targetids)}
    required=np.asarray(planner.required,dtype=bool);n=len(model.ids);band=(model.ra//10).astype(int);band_total=np.bincount(band);activebands=band_total>0
    # Contributions are indexed by original observe rank, including original final validity.
    valid_contributions=[(int(h['observe_index']),model.index[h['target_id']],float(h['score']),float(h['factor'])) for h in observations if h['valid']=='true']
    def settle(changes):
        score=np.zeros(n);factor=np.zeros(n);rqfactor=np.zeros(len(targetids))
        for j,i,s,g in valid_contributions:
            if j in changes:continue
            score[i]=max(score[i],s);factor[i]=max(factor[i],g)
            tid=model.ids[i]
            if tid in reqpos and rq['issued_at_utc']<=ds[j]['start_utc'] and ds[j]['end_utc']<=rq['deadline_utc']:rqfactor[reqpos[tid]]=max(rqfactor[reqpos[tid]],g)
        for j,c in changes.items():
            for tid,e in c['entries'].items():
                i=model.index[tid];score[i]=max(score[i],e['score_lower']);factor[i]=max(factor[i],e['factor_lower'])
                if tid in reqpos:rqfactor[reqpos[tid]]=max(rqfactor[reqpos[tid]],e['factor_lower'])
        ratios=np.bincount(band,weights=(factor>=.5),minlength=len(band_total))[activebands]/band_total[activebands]
        jain=sum(ratios)**2/(len(ratios)*sum(ratios**2));uniform=200*(1-jain);missing=int((required&(factor<.5)).sum());reward=100 if (rqfactor>=.5).sum()>=6 else 0
        # Other request + report remain unchanged, outside the changed first window.
        total=float(score.sum())-50*missing-uniform+reward+200
        return {'conditional_total':total,'science':float(score.sum()),'required_missing':missing,'uniformity_penalty':uniform,
                'REQ1_completed':[targetids[k] for k in np.flatnonzero(rqfactor>=.5)],'REQ1_reward':reward},score,factor
    baseline,B,F=settle({});assert abs(baseline['conditional_total']-load(directory/'score_report.json')['total'])<.005
    missing=(list(anchor_targets) if anchor_targets is not None else [t for t in targetids if t not in baseline['REQ1_completed']]);stats=defaultdict(int);candidates=[]
    for j,(d,a) in enumerate(zip(ds,acts)):
        if not(rq['issued_at_utc']<=d['start_utc'] and d['end_utc']<=rq['deadline_utc']):continue
        stats['window_originals']+=1
        if d['valid']!='true':stats['invalid_rank_originals_rejected']+=1;continue
        duration=int(d['duration_seconds']);start=parse(d['start_utc']);end=parse(d['end_utc']);cells,coef=matrix.coefficients(start.timestamp(),duration,np.arange(n))
        if np.any(profile['support'][cells]<=0) or np.any(profile['upper'][cells]-profile['lower'][cells]>1e-4):stats['unsupported_originals_rejected']+=1;continue
        stats['supported_originals']+=1
        with np.errstate(divide='ignore',over='ignore',invalid='ignore'):
            qlo=coef@profile['lower'][cells];qhi=coef@profile['upper'][cells]
        assert np.all(np.isfinite(coef)) and np.all(np.isfinite(qlo)) and np.all(np.isfinite(qhi))
        assert np.all(qlo>=0) and np.all(qhi+1e-12>=qlo)
        glo=np.minimum(1,planner.flux*duration/planner.f0t0*qlo);ghi=np.minimum(1,planner.flux*duration/planner.f0t0*qhi)
        slo=planner.weight*glo*np.where(qlo>=planner.dark_threshold,1.2,1.);shi=planner.weight*ghi*1.2
        outside,Bo,Fo=settle({j:{'entries':{}}});alt,az,hour,vectors=planner._altaz(local_sidereal(start,planner.lon));overlaps=matrix.overlaps(start.timestamp(),duration)
        clean_cache={};visibility_cache={}
        def eligible(i):
            if i not in clean_cache:clean_cache[i]=clear.clear(i,overlaps)
            if i not in visibility_cache:visibility_cache[i]=min_altitude_during(model.ra[i],model.dec[i],start,end,{'site':initial['site']})>=planner.min_alt
            return clean_cache[i] and visibility_cache[i]
        utility=np.maximum(0,slo-Bo)+50*required*(Fo<.5)*(glo>=.5)
        # Resource quota is treated as a hard anchor, not fractionally rewarded.
        for tid in missing:
            anchor=model.index[tid]
            if glo[anchor]<.5 or not eligible(anchor):continue
            stats['eligible_anchor_time_pairs']+=1
            for row in range(planner.side):
                for col in range(planner.side):
                    center=_shift_altaz(alt[anchor],az[anchor],-(row-(planner.side-1)/2)*planner.pitch,-(col-(planner.side-1)/2)*planner.pitch)
                    with np.errstate(invalid='ignore'):
                        fibers,on_glass,margin=planner._classify(vectors,*center)
                    pool=np.flatnonzero(on_glass&np.isfinite(margin)&(margin>.03)&(alt>=planner.min_alt))
                    if anchor not in pool:continue
                    assignment={};entries={};selectedmargin=[]
                    for fid in np.unique(fibers[pool]):
                        choices=pool[fibers[pool]==fid];choices=np.array([i for i in choices if eligible(int(i))],dtype=int)
                        if not len(choices):continue
                        i=int(anchor) if anchor in choices else int(choices[np.argmax(utility[choices])])
                        if i!=anchor and utility[i]<=1e-12:continue
                        hit=grid.classify_target(model.ra[i],model.dec[i],start,*center,planner.lat,planner.lon);assert hit.region=='glass' and hit.fiber_id==int(fid)
                        stats['official_geometry_checks']+=1;selectedmargin.append(float(margin[i]));t=model.ids[i];assignment[str(int(fid))]=t
                        entries[t]={'factor_lower':float(glo[i]),'factor_upper':float(ghi[i]),'score_lower':float(slo[i]),'score_upper':float(shi[i])}
                    if tid not in entries:continue
                    action={'action':'observe','pointing':{'alt_deg':float(center[0]),'az_deg':float(center[1])},'duration_seconds':duration,'program':'DARK','assignments':assignment}
                    candidate={'original_observe_index':j,'anchor':tid,'start_utc':d['start_utc'],'end_utc':d['end_utc'],'action':action,'entries':entries,'minimum_margin_deg':min(selectedmargin)}
                    score,_,_=settle({j:candidate});candidate['single_without_REQ1_gain_change']=score['conditional_total']-baseline['conditional_total'];candidates.append(candidate)
    # Bounded finite family: keep top20 for each missing target by exact single replacement settlement.
    kept=[]
    for tid in missing:kept.extend(sorted([c for c in candidates if c['anchor']==tid],key=lambda c:c['single_without_REQ1_gain_change'],reverse=True)[:20])
    best=None;pair_checks=0
    for aidx,a in enumerate(kept):
        for b in kept[aidx+1:]:
            if a['original_observe_index']==b['original_observe_index']:continue
            changes={a['original_observe_index']:a,b['original_observe_index']:b};value,_,_=settle(changes);pair_checks+=1
            if value['REQ1_reward']!=100:continue
            if best is None or value['conditional_total']>best['settlement']['conditional_total']:best={'changes':list(changes.values()),'settlement':value,'conditional_total_difference':value['conditional_total']-baseline['conditional_total']}
    summary={'baseline':baseline,'source_run':directory.name,'original_rows_and_ranks_preserved':True,'report_times_preserved':True,
             'candidate_statistics':dict(stats),'conditional_columns_generated':len(candidates),'bounded_columns_retained':len(kept),'pairs_checked':pair_checks,
             'best_pair':best,'hypotheses':'old interval profile independently passed current measured q gate; supported narrow cells; reference directional-clear geometry; zero pointing offset with >.03 margin; E<=1 for DARK lower; no hidden-weather certificate',
             'fixed_loss_rank_window':[150,169],'future_trigger_observe_count_preserved':603,'new_official_score':False,'hidden_inputs_read':False,
             'elapsed_seconds':time.perf_counter()-began,'source_sha256':sha(__file__),'profile_sha256':sha(profile_path)}
    (out/f'{stem}_columns.json').write_text(json.dumps(candidates,separators=(',',':'))+'\n')
    (out/f'{stem}_summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--anchors',nargs='*');ap.add_argument('--stem',default='delta_one_for_one');args=ap.parse_args()
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'formal_v4/upstream/gosim-observer-examples/runner'))
    out=root/'formal_v4/results/request_quota_failure_20261003';out.mkdir(exist_ok=True)
    directories=sorted((root/'formal_v4/results').glob('cloud*delta_20261003'))
    audits=[request_audit(d) for d in directories if (d/'score_report.json').exists()]
    (out/'delta_official_request_forensics.json').write_text(json.dumps(audits,indent=2)+'\n');search(root,out,args.anchors,args.stem)
