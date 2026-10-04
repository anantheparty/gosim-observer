import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
import json,time,copy,sys
from pathlib import Path
import numpy as np
from public_states import states,OUT
from research.spatial_candidates import parse_utc,local_sidereal,PROGRAMS,SIDEREAL_SPEED
from jain_assignment import Option,exact_select,linear_select,settle,gradient,jain


def candidate_options(actor,snapshot,env,action,scale=1.):
    p=actor.planner;now=parse_utc(snapshot['now_utc']);d=action['duration_seconds']
    alt,az,hour,vectors=p._altaz(local_sidereal(now,p.lon))
    up=np.where(p.hmax>=180,1e9,(p.hmax-hour)/SIDEREAL_SPEED)-1
    center=(action['pointing']['alt_deg']+env.get('pointing_offset_alt_deg',0),
            (action['pointing']['az_deg']+env.get('pointing_offset_az_deg',0))%360)
    # The official glass region lies within this conservative spherical cap.
    # Screen the opposite hemisphere before gnomonic division to avoid casts
    # from NaNs in the unchanged package's vector classifier.
    a,z=np.radians(center);cv=np.asarray([np.cos(a)*np.cos(z),np.cos(a)*np.sin(z),np.sin(a)])
    pool=np.flatnonzero((vectors@cv>=np.cos(np.radians(p.fov)))&(alt>=p.min_alt+.04)&(up>=d))
    fid,valid,_=p._classify(vectors[pool],*center)
    idx=pool[valid];fiber=np.full(p.n,-1,int);fiber[idx]=fid[valid]
    h=p._public_quality(now,local_sidereal(now,p.lon),alt)
    k=p.flux*h*env['quality_scale']*np.asarray(env['target_quality_scale'])*scale/p.f0t0
    raw=np.minimum(1.,k*d);robust=np.minimum(1.,k*d/max(1.,env['duration_safety']))
    bands=np.where(h*env['program_band_quality_scale']*scale>=p.dark_threshold,0,
                   np.where(h*env['program_band_quality_scale']*scale>=p.bright_threshold,1,2))
    prog=PROGRAMS.index(action['program']);mult=np.where(bands==prog,p.multipliers[prog],p.mismatch)
    science=np.maximum(0.,p.weight*raw*mult-actor.scores)
    completed=actor.factor_lower>=p.uniform_threshold
    new=~completed&(robust+1e-10>=p.uniform_threshold)
    required=p.required&(actor.factor_lower<p.req_threshold)&(robust+1e-10>=p.req_threshold)
    options=[Option(int(i),int(fiber[i]),float(science[i]+p.req_penalty*required[i]),
                    int(p.ra_bands[i]) if new[i] else -1) for i in idx]
    counts=np.bincount(p.ra_bands,weights=completed,minlength=len(p.band_sizes)).astype(int)
    upper=np.minimum(1.,(actor.scores+.500001e-6)/(p.weight*min(float(p.multipliers.min()),p.mismatch)))
    upper=np.maximum(upper,actor.factor_lower)
    ambiguous=(actor.factor_lower<p.uniform_threshold)&(upper>=p.uniform_threshold)
    return options,counts,science,required,new,idx,ambiguous


def inspect(actor,snapshot,env,meta):
    start=time.perf_counter();p=actor.planner
    if snapshot['active_requests']:return {**meta,'status':'excluded_active_request'}
    action=p.choose(snapshot,actor.scores,actor.factor_lower,env,[])
    if action is None or action['action']!='observe':return {**meta,'status':'no_observe'}
    rows=[]
    for scale in (.9,1.,1.1):
        options,counts,science,required,new,idx,ambiguous=candidate_options(actor,snapshot,env,action,scale)
        exact=exact_select(options,counts,p.band_sizes,p.uniform_weight)
        if exact is None:
            rows.append({'scale':scale,'status':'excluded_more_than_two_newcompletion_bands'});continue
        linear=linear_select(options,counts,p.band_sizes,p.uniform_weight)
        lookup={o.target:o for o in options}
        original=[lookup[p.index[t]] for t in action['assignments'].values() if p.index[t] in lookup]
        selected=exact['chosen'];assign={str(o.fiber):p.ids[o.target] for o in selected}
        changes=[{'fiber':str(f),'before':action['assignments'].get(str(f)), 'after':assign.get(str(f))}
                 for f in range(p.nfib) if action['assignments'].get(str(f))!=assign.get(str(f))]
        rows.append({'scale':scale,'status':'solved','options':len(options),'active_bands':exact['active_bands'],
            'peak_states':exact['peak_states'],'linear_value':settle(linear,counts,p.band_sizes,p.uniform_weight),
            'strong_assignment_value':settle(original,counts,p.band_sizes,p.uniform_weight), 'exact_value':exact['value'],
            'exact_minus_strong':exact['value']-settle(original,counts,p.band_sizes,p.uniform_weight),
            'exact_minus_matched_linear':exact['value']-settle(linear,counts,p.band_sizes,p.uniform_weight),
            'chosen':[o.target for o in selected],'linear_chosen':[o.target for o in linear],
            'science_delta':float(sum(science[o.target] for o in selected)-sum(science[o.target] for o in original)),
            'required_delta':int(sum(required[o.target] for o in selected)-sum(required[o.target] for o in original)),
            'completion_delta':int(sum(new[o.target] for o in selected)-sum(new[o.target] for o in original)),
            'global_ambiguous_completion_count':int(ambiguous.sum()),'local_ambiguous_completion_count':int(ambiguous[idx].sum()),
            'band_sizes':p.band_sizes.tolist(),'band_completed_lower':counts.tolist(),
            'action_changes':changes,'candidate':{**action,'assignments':assign}})
    valid=[r for r in rows if r.get('status')=='solved']
    stable=(len(valid)==3 and all(r['exact_minus_strong']>1e-8 and r['action_changes'] for r in valid)
            and all(r['chosen']==valid[0]['chosen'] for r in valid))
    # Isolated curvature must beat matched linear selector, not just a weighted
    # production selector that also uses urgency/progress-scale heuristics.
    curvature=(len(valid)==3 and all(r['exact_minus_matched_linear']>1e-8 for r in valid))
    return {**meta,'status':'solved','baseline':action,'rows':rows,'stable_same_assignment_three_scales':stable,
            'strict_curvature_three_scales':curvature,'seconds':time.perf_counter()-start}


def main():
    start=time.perf_counter();results=[]
    for card in ('L1','L2'):
        present=set()
        for actor,snapshot,env,meta in states(card,[7,17,27,37]):
            present.add(meta['night_index'])
            r=inspect(actor,snapshot,env,meta);results.append(r)
            (OUT/f'{card}_night{meta["night_index"]}.json').write_text(json.dumps(r,indent=2)+'\n')
            print(json.dumps({'card':card,'night':meta['night_index'],'status':r['status'],
                'stable':r.get('stable_same_assignment_three_scales'),'curvature':r.get('strict_curvature_three_scales'),
                'gains':[v.get('exact_minus_strong') for v in r.get('rows',[])], 'seconds':r.get('seconds')}),flush=True)
        for n in [7,17,27,37]:
            if n not in present:results.append({'card':card,'night_index':n,'status':'unavailable_predeclared_state'})
    summary={'scope':'reconstructed public strong states; fixed current field/duration/program; frozen conditional-Q and lower-bound completion surrogate; no actualfull or future truth',
        'states':results,'seconds':time.perf_counter()-start,
        'stable_candidates':sum(r.get('stable_same_assignment_three_scales',False) for r in results),
        'strict_curvature':sum(r.get('strict_curvature_three_scales',False) for r in results)}
    (OUT/'public_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
if __name__=='__main__':main()
