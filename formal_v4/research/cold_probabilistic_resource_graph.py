#!/usr/bin/env python3
"""Complete target/slot generalized-flow relaxation of continuous v4 seasons.

All visible target/slot edges are built, independent of incumbent columns.
Local truth is used only for a LOCAL clairvoyant upper bound. No practice-card
truth is read. At arbitrary nonnegative multipliers the Lagrangian expression
is an upper bound; minimization improves it but is not needed for validity.
"""
from __future__ import annotations
import sys,json,math,time,hashlib
from pathlib import Path
import numpy as np
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'upstream/gosim-observer-examples/runner'))
from challenge.v4_runner import load_scenario
from challenge.tile_geometry_simulator import _local_sidereal_deg
from challenge.v4_scorer import DIRECTIONAL_MULTIPLIER_TYPES
OUT=BASE/'results/cold_probabilistic_model_20261003/resource_graph'

def airmass(h):
    z=90-h
    raw=1/(np.cos(np.radians(z))+.50572*(96.07995-z)**(-1.6364))
    norm=1/(1+.50572*96.07995**(-1.6364))
    return raw/norm


def graph(sc):
    n=len(sc.targets);ra=np.array([t['ra_deg'] for t in sc.targets]);dec=np.radians([t['dec_deg'] for t in sc.targets])
    phi=math.radians(sc.site['latitude_deg']);aa=math.sin(phi)*np.sin(dec);bb=math.cos(phi)*np.cos(dec)
    uu=(math.sin(math.radians(sc.minimum_altitude_deg))-aa)/bb
    hlim=np.degrees(np.arccos(np.clip(uu,-1,1)))
    possible=uu<=1+1e-12
    fiber=int(sc.fiber_config['field']['n_fibers']);cfg=sc.score_config
    f=np.array([t['feature_flux'] for t in sc.targets]);weight=np.array([t['science_weight'] for t in sc.targets])
    required=np.array([t['required'] for t in sc.targets])
    mult=max(float(cfg['program']['mismatch_multiplier']),*[float(v) for v in cfg['program']['multipliers'].values()])
    science=mult*weight;p=np.where(required,float(cfg['required']['penalty_per_missing']),0.)
    threshold=float(cfg['required']['observed_factor_threshold'])
    if not 0<threshold<=1:raise ValueError('positive completion threshold <=1 required')
    if min(science.min(),p.min(),float(cfg['uniformity']['weight']))<0:raise ValueError('nonnegative local rewards/penalties required')
    if float(cfg['reporting']['false_penalty'])>0:raise ValueError('positive false-report reward needs a different report bound')
    if float(cfg['airmass_exponent'])<0:raise ValueError('negative airmass exponent')
    lunar=cfg['lunar_model']
    if not (0<=lunar['maximum_penalty']<1 and lunar['altitude_exponent']>0 and lunar['angular_decay_scale_deg']>0):raise ValueError('invalid lunar bound')
    if f.min()<0 or weight.min()<0:raise ValueError('negative target properties')
    for slot in sc.slots:
        if min(slot.instrument_efficiency,slot.transparency,slot.sky_quality)<0:raise ValueError('negative weather')
    ii=[];kk=[];vv=[];rr=[];slotmap=[];slotmeta=[]
    for original,slot in enumerate(sc.slots):
        if not slot.is_observable:continue
        # Repaired fault efficiency is min(1,raw/fault_multiplier); the
        # unrepaired raw value can exceed 1. This bound covers both exactly.
        eff_upper=float(slot.instrument_efficiency)
        for fault in sc.events:
            if fault.event_type=='instrument_fault' and fault.overlaps(slot.start_utc,slot.end_utc) and fault.instrument_efficiency_multiplier>0:
                eff_upper=max(eff_upper,min(1.,slot.instrument_efficiency/fault.instrument_efficiency_multiplier))
        if slot.seeing_arcsec<=0:raise ValueError('nonpositive local seeing')
        w=eff_upper*slot.transparency*slot.sky_quality/slot.seeing_arcsec/float(cfg['q0'])
        directional_upper=1.
        for e in sc.events:
            if e.event_type in DIRECTIONAL_MULTIPLIER_TYPES and e.overlaps(slot.start_utc,slot.end_utc):
                if e.seeing_multiplier<=0:raise ValueError('nonpositive event seeing multiplier')
                directional_upper*=max(1.,e.instrument_efficiency_multiplier*e.transparency_multiplier*e.sky_quality_multiplier/e.seeing_multiplier)
        w*=directional_upper
        if w<=0:continue
        seconds=(slot.end_utc-slot.start_utc).total_seconds()
        drift=360.98564736629*seconds/86400
        h0=(_local_sidereal_deg(slot.start_utc,sc.site['longitude_deg'])-ra+180)%360-180
        visible=np.zeros(n);maxcos=np.full(n,-1.)
        for turn in (-1,0,1):
            left=np.maximum(h0,-hlim+turn*360);right=np.minimum(h0+drift,hlim+turn*360)
            length=np.maximum(0.,right-left)
            visible+=length/drift
            c=np.maximum(np.cos(np.radians(left)),np.cos(np.radians(right)))
            c=np.where((left<=turn*360)&(right>=turn*360),1.,c)
            maxcos=np.maximum(maxcos,np.where(length>0,c,-1.))
        # Outward padding covers floating point seam/visibility calculation.
        visible=np.minimum(1.,visible+1e-7)
        # Whole-slot visibility envelope: include every target whose continuous
        # maximum altitude can reach the limit; give it the whole slot.
        fullcos=np.maximum(np.cos(np.radians(h0)),np.cos(np.radians(h0+drift)))
        for turn in (-1,0,1):
            fullcos=np.where((h0<=turn*360)&(h0+drift>=turn*360),1.,fullcos)
        allmaxalt=np.degrees(np.arcsin(np.clip(aa+bb*fullcos,-1,1)))
        select=np.flatnonzero(allmaxalt>=sc.minimum_altitude_deg-1e-7)
        if not len(select):continue
        maxalt=allmaxalt[select]
        maxalt=np.minimum(90.,maxalt+1e-8)
        quality_upper=w/airmass(maxalt)**float(cfg['airmass_exponent']) # lunar<=1
        rate=f[select]*900*quality_upper/(float(cfg['flux_zero_point'])*float(cfg['exposure_zero_point_seconds']))
        rate=np.maximum(0.,rate)*(1+1e-10)
        j=len(slotmap);slotmap.append(original)
        ii.append(select.astype(np.int32));kk.append(np.full(len(select),j,np.int32));vv.append(np.full(len(select),seconds/900));rr.append(rate)
        slotmeta.append({'original_slot_index':original,'slot_id':slot.slot_id,'night_id':slot.slot_id.split('-S')[0],'start_utc':slot.start_utc.isoformat(),'end_utc':slot.end_utc.isoformat(),'capacity_fiber_900s_units':fiber*seconds/900,'raw_instrument_efficiency':slot.instrument_efficiency,'efficiency_upper':eff_upper,'directional_positive_multiplier_upper':directional_upper,'site_weather_quality_upper':w})
    i=np.concatenate(ii);k=np.concatenate(kk);v=np.concatenate(vv);r=np.concatenate(rr)
    cap=np.array([s['capacity_fiber_900s_units'] for s in slotmeta])
    maxrate=np.zeros(n);np.maximum.at(maxrate,i,r)
    maxduration=float(sc.fiber_config['exposure']['max_duration_seconds'])
    gmax=np.minimum(1.,maxrate*maxduration/900)
    effective_p=np.where(gmax>=threshold,p,0.)
    return dict(i=i,k=k,v=v,r=r,cap=cap,science=science,p=p,effective_p=effective_p,gmax=gmax,threshold=threshold,slots=slotmeta)


def solve(g,maxiter=8):
    i,k,v,r=g['i'],g['k'],g['v'],g['r'];cap=g['cap'];a,p=g['science'],g['effective_p'];threshold=g['threshold'];n=len(a);ns=len(cap)
    zmax=g['gmax'];zmid=np.minimum(threshold,zmax)
    zs=np.vstack([np.zeros(n),zmid,zmax]);rewards=np.vstack([np.zeros(n),a*zmid+p,a*zmax+p])
    # Exact convex coordinate minimization by monotone subgradient bisection.
    # All iterates are valid certificates; retain the best including zero dual.
    def exact(nu,lam):
        conjugate=np.max(rewards.astype(np.longdouble)-zs.astype(np.longdouble)*nu.astype(np.longdouble),axis=0)
        edge=np.maximum(np.longdouble(0),nu[i].astype(np.longdouble)*r.astype(np.longdouble)-lam[k].astype(np.longdouble))*v.astype(np.longdouble)
        terms={'target_reward_conjugates':float(conjugate.sum(dtype=np.longdouble)),'fiber_time_capacity_prices':float(np.sum(cap.astype(np.longdouble)*lam.astype(np.longdouble),dtype=np.longdouble)),'edge_upper_capacity_corrections':float(edge.sum(dtype=np.longdouble)),'required_missing_constant':-float(g['p'].sum(dtype=np.longdouble))}
        return sum(terms.values()),terms
    nu=np.zeros(n);lam=np.zeros(ns);best,terms=exact(nu,lam);bestnu=nu.copy();bestlam=lam.copy();trajectory=[best]
    # A positive price seed avoids the zero/zero coordinate plateau.
    lam=np.full(ns,.25);upper=a+p/threshold
    for iteration in range(maxiter):
        lo=np.zeros(n);hi=upper.copy()
        for _ in range(25):
            mid=(lo+hi)/2
            active=mid[i]*r>lam[k]
            dose=np.bincount(i,weights=v*r*active,minlength=n)
            wanted=np.where(mid<a,zmax,np.where((p>0)&(mid<a+p/threshold),zmid,0.))
            increase=dose<wanted
            lo=np.where(increase,mid,lo);hi=np.where(increase,hi,mid)
        nu=(lo+hi)/2
        q=nu[i]*r;lo=np.zeros(ns);hi=np.full(ns,float(q.max()))
        for _ in range(25):
            mid=(lo+hi)/2
            allocated=np.bincount(k,weights=v*(q>mid[k]),minlength=ns)
            increase=allocated>cap
            lo=np.where(increase,mid,lo);hi=np.where(increase,hi,mid)
        lam=(lo+hi)/2
        value,current=exact(nu,lam);trajectory.append(value)
        if value<best:best=value;terms=current;bestnu=nu.copy();bestlam=lam.copy()
        print('dual iteration',iteration,'upper science+required',value,flush=True)
    nu,lam=bestnu,bestlam
    pad=max(1.,abs(best)*1e-8)
    return nu,lam,dict(dual_terms=terms,science_required_upper_before_padding=best,numerical_upward_padding=pad,science_required_upper=best+pad,optimizer_success=True,optimizer_status='Best of finite exact coordinate updates and zero dual; no optimum claim',optimizer_iterations=maxiter,objective_calls=maxiter+1,dual_trajectory=trajectory,dual_nonnegative_violation=float(max(0.,-min(nu.min(),lam.min()))),scope='Valid complete-edge dual at any nonnegative multipliers; optimization convergence is not required for bound validity.')


def main():
    reports={};OUT.mkdir(parents=True,exist_ok=True)
    for card in sys.argv[1:] or ('L1','L2'):
        began=time.time();sc=load_scenario(BASE/f'upstream/gosim-observer-examples/local-cards/{card}/config/v4_scenario.json')
        g=graph(sc);print(card,'edges',len(g['i']),'targets',len(g['science']),'slots',len(g['cap']),flush=True)
        nu,lam,rep=solve(g)
        reqcap=sum(max(0.,float(q['completion_reward'])) for q in sc.observation_requests)
        reportcap=sum(e.event_type=='instrument_fault' for e in sc.events)*max(0.,float(sc.score_config['reporting']['correct_reward']))
        rep.update(card=card,targets=len(sc.targets),complete_visible_target_slot_edges=len(g['i']),open_positive_weather_slots=len(g['cap']),program_max_multiplier=max(float(sc.score_config['program']['mismatch_multiplier']),*[float(z) for z in sc.score_config['program']['multipliers'].values()]),required_count=sum(t['required'] for t in sc.targets),raw_local_efficiency_max=max(s.instrument_efficiency for s in sc.slots),request_reward_upper=reqcap,report_settlement_upper=reportcap,uniformity_contribution_upper=0.,total_upper=rep['science_required_upper']+reqcap+reportcap,elapsed_seconds=time.time()-began)
        baseline=BASE/f'results/reference_{card}/score_report.json'
        if baseline.exists():
            br=json.loads(baseline.read_text());rep['existing_reference_score']=br['total'];rep['upper_minus_existing_reference']=rep['total_upper']-br['total'];rep['contains_existing_reference']=rep['total_upper']+1e-6>=br['total'];rep['existing_reference_termination']=br.get('termination')
            assert rep['contains_existing_reference']
        rep['strong_existing_local_baseline']=dict(L1=6348.155319,L2=6534.787015).get(card)
        if rep['strong_existing_local_baseline'] is not None:
            rep['contains_strong_existing_local_baseline']=rep['total_upper']>=rep['strong_existing_local_baseline']
            assert rep['contains_strong_existing_local_baseline']
        rep['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        np.savez_compressed(OUT/f'{card}_dual_certificate.npz',target_index=g['i'],slot_index=g['k'],edge_visible_900s_capacity=g['v'],edge_factor_per_900s_upper=g['r'],slot_fiber_900s_capacity=g['cap'],science_slope=g['science'],required_reward=g['p'],required_threshold=g['threshold'],target_max_single_exposure_factor_upper=g['gmax'],effective_required_reward=g['effective_p'],target_nu=nu,slot_lambda=lam)
        (OUT/f'{card}_slot_prices.json').write_text(json.dumps([{**s,'lambda_score_per_fiber_900s':float(lam[j]),'telescope_shadow_score_per_second':float(lam[j]*sc.fiber_config['field']['n_fibers']/900)} for j,s in enumerate(g['slots'])],indent=2)+'\n')
        (OUT/f'{card}_target_prices.json').write_text(json.dumps([{'target_id':t['target_id'],'nu_score_per_factor':float(nu[j]),'required':t['required']} for j,t in enumerate(sc.targets)],indent=2)+'\n')
        (OUT/f'{card}_summary.json').write_text(json.dumps(rep,indent=2)+'\n');reports[card]=rep;print(json.dumps(rep),flush=True)
    proof={
      'model':'Complete target-slot generalized-flow relaxation; no incumbent exposure columns. Target dose may accumulate across continuous exposures/night boundaries. Spatial field co-location, program choice, data loss, terrain and directional closures are relaxed.',
      'embedding':'For every arbitrary valid real exposure, assign each scored target its exposure seconds in each overlapped weather slot as service x_i,k. A valid target remains >= minimum altitude throughout, so total service in each slot is <= its whole-slot visibility envelope (the target is included if any continuous slot moment reaches the altitude limit). At every time there are <=n_fibers assigned targets, hence sum_i x_i,k<=n_fibers*slot_seconds. Across overlapping real exposures no time overlap is possible. Original maximum raw factor <= min(sum of relaxed effective dose across all exposures,1); original best science <= global program multiplier * weight * this accumulated capped dose.',
      'physical_upper':'The local actual slot weather is read explicitly. Efficiency upper=max(raw, min(1,raw/fault_mult)) only when a local fault overlaps that slot; otherwise use raw. This covers unrepaired/repaired states while retaining earthquake degradation, without assuming raw efficiency<=1. Each potentially enhancing directional coefficient overlapping the slot multiplies the upper by max(1,eff_mult*transp_mult*sky_mult/seeing_mult). Lunar factor<=1 and airmass is bounded using exact maximum target altitude over its visible slot intervals. Site closures retained; target closures relaxed.',
      'target_reward':'R_i(z)=M*weight_i*z+P_i*min(z/threshold,1), z in [0,gmax_i], where gmax_i<=1 bounds every single maximum-duration exposure using the target\'s full-season maximum dose rate. If gmax_i<threshold the required reward is identically zero, minus constant sum_required P_i. Since 1{z>=threshold}<=min(z/threshold,1), R is a concave envelope of required reward and keeps the missing penalty constant. Science uses accumulated dose only as a proved optimistic relaxation of per-target maximum exposure score.',
      'dual':'For any nu_i>=0,lambda_k>=0, U=sum_i max_{z in {0,min(threshold,gmax_i),gmax_i}}[R_i(z)-nu_i*z]+sum_k lambda_k*C_k+sum_(i,k) V_i,k*max(nu_i*r_i,k-lambda_k,0)-sum_i P_i. This follows by maximizing the Lagrangian independently over target completion and each edge service 0<=x_i,k<=V_i,k. Every produced nonnegative pair is a valid upper certificate; heterogeneous gains r_i,k make it a generalized-flow/convex LP rather than ordinary network flow.',
      'settlement_upper':'Add every positive request completion reward and one positive correct-report reward per local instrument_fault event. Local false penalty is nonpositive, so false reports cannot improve this cap. Ignore nonpositive Jain penalty: its contribution upper is zero. Data loss only removes valid observations, so ignoring it is optimistic.',
      'numerics':'Geometry and edge rates receive outward padding; exact nonsmooth dual is summed in numpy.longdouble. Final score bound receives >=1 score upward tolerance. Certificates contain complete edge arrays and nonnegative multipliers; independent recomputation checks the value without optimizer assumptions. This is a numerical upper certificate with stated tolerances, not a formal interval-arithmetic proof.',
      'limitations':'LOCAL clairvoyant weather upper bound, not a platform alpha-delta or weather-prior bound. Removing spatial co-location, Moon and indivisible best-exposure signal weakens it. A bound enclosing a reference replay is only a sanity check; validity derives from arbitrary-exposure embedding and dual inequality.',
      'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (OUT/'proof_and_scope.json').write_text(json.dumps(proof,indent=2)+'\n')
    (OUT/'summary.json').write_text(json.dumps(reports,indent=2)+'\n')
if __name__=='__main__':main()
