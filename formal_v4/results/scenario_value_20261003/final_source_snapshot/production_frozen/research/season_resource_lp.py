#!/usr/bin/env python3
"""Independent-fiber full-season resource relaxation, using public inputs only.

Outputs marginal science/raw-factor and night-time prices. This drops shared
pointings and allows target exposure accumulation. physical_ce bounds only a
specified constant-C/E science+required model. Sampled geometry/estimated factors
are a continuation surrogate, not a certified bound on hidden future weather.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

from global_lp_pilot import public_initialization
from spatial_candidates import SpatialPlanner, SIDEREAL_SPEED, local_sidereal, parse_utc

BASE=Path(__file__).resolve().parents[1]


def visible_seconds(planner,start,end):
    """Exact angular interval overlap at public minimum altitude, no margin."""
    limit=(math.sin(math.radians(planner.min_alt))-planner.sin_lat*planner.sin_dec)/np.maximum(1e-12,planner.cos_lat*planner.cos_dec)
    hmax=np.arccos(np.clip(limit,-1,1))*180/math.pi
    hmax[limit>=1]=0;hmax[limit<=-1]=180
    span=(end-start).total_seconds()*SIDEREAL_SPEED
    rise=(planner.ra-hmax-local_sidereal(start,planner.lon))%360
    overlap=np.maximum(0,np.minimum(span,rise+2*hmax)-rise)
    overlap+=np.maximum(0,np.minimum(span,rise-360+2*hmax))
    overlap[hmax>=180]=span
    return overlap/SIDEREAL_SPEED


def solve(initial,as_of=None,scores=None,factors=None,C=1.,E=.95,quality='physical_ce',factor_mode='upper',seconds=60.):
    started=time.perf_counter();p=SpatialPlanner(initial)
    now=parse_utc(as_of or initial['survey']['start_utc'])
    scores=np.zeros(p.n) if scores is None else p._array(scores)
    factors=np.zeros(p.n) if factors is None else p._array(factors)
    M=max(float(p.multipliers.max()),float(p.mismatch))
    mmin=min(float(p.multipliers.min()),float(p.mismatch))
    if factor_mode=='upper':
        baseline_factor=np.minimum(1,np.divide(scores,p.weight*mmin,out=np.ones(p.n),where=p.weight>0))
    else:baseline_factor=np.clip(factors,0,1)
    remaining=np.maximum(0,1-np.divide(scores,p.weight*M,out=np.ones(p.n),where=p.weight>0))
    required=np.flatnonzero(p.required & (baseline_factor < p.req_threshold))
    required_index=np.full(p.n,-1,dtype=int);required_index[required]=np.arange(len(required))
    req_already=int(np.count_nonzero(p.required & (baseline_factor >= p.req_threshold)))
    active_nights=[(k,max(a,now),b) for k,(a,b) in enumerate(p.nights) if b>now]
    ti=[];ni=[];upper=[];coeff=[];night_metadata=[]
    unit=900.
    best_H=np.ones(p.n) if quality=='physical_ce' else np.zeros(p.n)
    for q,(k,a,b) in enumerate(active_nights):
        visible=visible_seconds(p,a,b)
        useful=np.flatnonzero((visible>1e-9)&((remaining>1e-12)|(required_index>=0)))
        H=np.ones(p.n)
        if quality=='sampled_geom_max':
            H=np.zeros(p.n)
            for second in np.arange(0,(b-a).total_seconds()+1,900):
                moment=min(b,a+timedelta(seconds=float(second)))
                lst=local_sidereal(moment,p.lon);alt=p._altaz(lst)[0]
                sampled=p._public_quality(moment,lst,alt)*p.q0
                H=np.maximum(H,np.where(alt>=p.min_alt,sampled,0.))
            best_H=np.maximum(best_H,H)
        ti.extend(useful.tolist());ni.extend([q]*len(useful));upper.extend((visible[useful]/unit).tolist())
        coeff.extend((p.flux[useful]*float(C)*float(E)*H[useful]/p.f0t0*unit).tolist())
        night_metadata.append({'night_index':k,'start_utc':a.isoformat(),'end_utc':b.isoformat(),
            'seconds':(b-a).total_seconds(),'fiber_seconds':p.nfib*(b-a).total_seconds()})
    future_cap=np.minimum(1,p.flux*p.tmax*float(C)*float(E)*best_H/p.f0t0)
    # Retain the true single-exposure duration ceiling even though accumulation
    # is permitted in the resource constraints as a relaxation.
    remaining=np.maximum(0,future_cap-np.divide(scores,p.weight*M,out=np.ones(p.n),where=p.weight>0))
    req_upper=(future_cap[required]+1e-12 >= p.req_threshold).astype(float)
    ti=np.asarray(ti,dtype=int);ni=np.asarray(ni,dtype=int);upper=np.asarray(upper);coeff=np.asarray(coeff)
    nt=len(ti);nr=len(required);nn=len(active_nights);nv=nt+p.n+nr
    # science normalized-factor growth <= accumulated relaxed target exposure.
    rows=ti.tolist()+list(range(p.n));cols=list(range(nt))+list(range(nt,nt+p.n));data=(-coeff).tolist()+[1.]*p.n
    has_req=required_index[ti]>=0
    rows.extend((p.n+required_index[ti[has_req]]).tolist());cols.extend(np.flatnonzero(has_req).tolist());data.extend((-coeff[has_req]/p.req_threshold).tolist())
    rows.extend(range(p.n,p.n+nr));cols.extend(range(nt+p.n,nv));data.extend([1.]*nr)
    rows.extend((p.n+nr+ni).tolist());cols.extend(range(nt));data.extend([1.]*nt)
    A=coo_matrix((data,(rows,cols)),shape=(p.n+nr+nn,nv)).tocsr()
    rhs=np.r_[np.zeros(p.n),baseline_factor[required]/p.req_threshold,
              np.asarray([n['fiber_seconds']/unit for n in night_metadata])]
    objective=-np.r_[np.zeros(nt),p.weight*M,np.full(nr,p.req_penalty)]
    bounds=np.column_stack((np.zeros(nv),np.r_[upper,remaining,req_upper]))
    setup=time.perf_counter()-started;solver_started=time.perf_counter()
    lp=linprog(objective,A_ub=A,b_ub=rhs,bounds=bounds,method='highs',options={'time_limit':seconds})
    runtime=time.perf_counter()-solver_started
    if not lp.success:raise RuntimeError(f'resource LP failed {lp.status}: {lp.message}')
    alpha_raw=np.maximum(0,-lp.ineqlin.marginals[:p.n]);rho_raw=np.zeros(p.n)
    rho_raw[required]=np.maximum(0,-lp.ineqlin.marginals[p.n:p.n+nr]);beta=np.maximum(0,-lp.ineqlin.marginals[p.n+nr:])
    # At a zero lower bound HiGHS can choose nonunique coverage marginals above
    # the layer's entire reward. Reducing them to the reward preserves column
    # dual inequalities and avoids exporting that degeneracy as excessive value.
    alpha=np.minimum(alpha_raw,p.weight*M);rho=np.minimum(rho_raw,p.req_penalty)
    allocation=lp.x[:nt]*unit
    used=np.bincount(ni,weights=allocation,minlength=nn)
    growth=lp.x[nt:nt+p.n]*p.weight*M;relaxed_required=lp.x[nt+p.n:]
    avoided=(req_already+float(relaxed_required.sum()))*p.req_penalty
    result={'as_of':now.isoformat(),'C':C,'E':E,'quality_mode':quality,'factor_mode':factor_mode,
        'targets':p.n,'target_night_links':nt,'required_layers':nr,'active_nights':nn,'variables':nv,
        'constraints':A.shape[0],'nonzeros':int(A.nnz),'scipy_sparse_data_bytes':int(A.data.nbytes+A.indices.nbytes+A.indptr.nbytes),
        'science_current':float(scores.sum()),'science_relaxed_total':float(scores.sum()+growth.sum()),
        'required_avoided_penalty_relaxed':avoided,'required_constant_penalty':-float(p.required.sum()*p.req_penalty),
        'science_plus_required_relaxed_bound_or_surrogate':float(scores.sum()+growth.sum()+avoided-p.required.sum()*p.req_penalty),
        'science_physical_cap':float((p.weight*M).sum()),
        'frozen_single_exposure_science_ceiling':float(np.maximum(scores,p.weight*M*future_cap).sum()),
        'required_unreachable_in_frozen_single_exposure':int(np.count_nonzero(req_upper==0)),
        'science_layer_positive_price_count':int(np.count_nonzero(alpha>1e-9)),
        'required_layer_positive_price_count':int(np.count_nonzero(rho>1e-9)),
        'night_positive_price_count':int(np.count_nonzero(beta>1e-9)),
        'raw_science_marginals_above_reward_count':int(np.count_nonzero(alpha_raw>p.weight*M+1e-9)),
        'setup_seconds':setup,'solver_seconds':runtime,'total_seconds':time.perf_counter()-started,
        'bound_scope':'constant supplied C/E, public geometry, science+required numerical resource relaxation only' if quality=='physical_ce' and factor_mode=='upper' else 'frozen/expected continuation surrogate; not certified upper bound',
        'future_truth_used':False,'geometry_visibility_margin_deg':0,
        'relaxations':['independent target fibers without shared pointing/grid constraints','allow target exposure accumulation',
                       'science uses highest multiplier for all future exposures','fractional required threshold credit',
                       'uniformity/reports/requests/data_loss absent'],
        'numerical_optimality_only':True,'limits':['sampled_geom_max is not a rigorous continuous geometry upper bound',
            'supplied C/E is not an upper bound on unknown future weather/efficiency unless separately proved',
            'no exact rational solver certificate generated in this resource pilot']}
    prices={p.ids[i]:{'science_price_per_normalized_factor':float(alpha[i]),
            'raw_science_constraint_marginal':float(alpha_raw[i]),
            'science_price_per_score':float(alpha[i]/(p.weight[i]*M)) if p.weight[i]>0 else 0.,
            'required_price_per_threshold_fraction':float(rho[i]),
            'raw_required_constraint_marginal':float(rho_raw[i]),
            'required_price_per_raw_factor':float(rho[i]/p.req_threshold),
            'baseline_factor_used':float(baseline_factor[i]),'science_remaining_cap':float(remaining[i]*p.weight[i]*M)} for i in range(p.n)}
    nights=[{**n,'allocated_fiber_seconds':float(u),'utilization':float(u/n['fiber_seconds']),
             'shadow_price_per_fiber_second':float(v/unit)} for n,u,v in zip(night_metadata,used,beta)]
    return result,prices,nights


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--card',default='L1',choices=('L1','L2','L3','L4'))
    ap.add_argument('--as-of');ap.add_argument('--state',type=Path);ap.add_argument('--C',type=float,default=1.);ap.add_argument('--E',type=float,default=.95)
    ap.add_argument('--quality',choices=('physical_ce','sampled_geom_max'),default='physical_ce')
    ap.add_argument('--factor-mode',choices=('upper','estimated'),default='upper');ap.add_argument('--seconds',type=float,default=60.)
    ap.add_argument('--out',type=Path,default=BASE/'results/season_resource_L1_pilot');args=ap.parse_args()
    initial,hashes=public_initialization(BASE/'upstream/gosim-observer-examples/local-cards'/args.card)
    state=json.loads(args.state.read_text()) if args.state else {}
    result,prices,nights=solve(initial,args.as_of or state.get('now_utc'),state.get('scores'),state.get('factors'),args.C,args.E,args.quality,args.factor_mode,args.seconds)
    result['public_input_sha256']=hashes;result['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if args.state:result['public_state_sha256']=hashlib.sha256(args.state.read_bytes()).hexdigest()
    args.out.mkdir(parents=True,exist_ok=True)
    for name,value in [('result.json',result),('target_prices.json',prices),('night_prices.json',nights)]:
        (args.out/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
