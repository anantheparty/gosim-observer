#!/usr/bin/env python3
"""All-pointing spatial support upper bound from a full-sphere RA/Dec cover.

This is independent of historical pointing columns. Local weather-conditional
quality upper edges and per-target raw-factor caps come from the complete graph.
"""
from pathlib import Path
import sys,json,math,time,hashlib
import numpy as np
from scipy.spatial import cKDTree
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'upstream/gosim-observer-examples/runner'))
from challenge.v4_runner import load_scenario
from challenge.v4_fiber_map import FiberGrid
OUT=BASE/'results/cold_probabilistic_model_20261003/spatial_support'
RESOURCE=BASE/'results/cold_probabilistic_model_20261003/resource_graph'


def covering(step=1.):
    ndec=math.ceil(180/step);nra=math.ceil(360/step)
    dd=180/ndec;da=360/nra
    dcent=-90+(np.arange(ndec)+.5)*dd
    acent=(np.arange(nra)+.5)*da
    dec=np.repeat(dcent,nra);ra=np.tile(acent,ndec)
    dec_r=np.radians(dec);ra_r=np.radians(ra)
    centers=np.column_stack([np.cos(dec_r)*np.cos(ra_r),np.cos(dec_r)*np.sin(ra_r),np.sin(dec_r)])
    # Distance is greatest at longitude edges and one of the latitude edges:
    # cos(separation) is a sinusoid with no interior minimum over each <=1deg
    # latitude interval around its own center. Pole endpoints are included.
    d0=np.radians(dcent);cornercos=[]
    for sign in (-1,1):
        edge=np.radians(dcent+sign*dd/2)
        cornercos.append(np.sin(d0)*np.sin(edge)+np.cos(d0)*np.cos(edge)*math.cos(math.radians(da/2)))
    radii=np.degrees(np.arccos(np.clip(np.minimum(*cornercos),-1,1)))
    radius=float(radii.max())+1e-7
    return centers,dict(latitude_cells=ndec,longitude_cells=nra,sphere_cells=len(centers),latitude_step_deg=dd,longitude_step_deg=da,maximum_cover_radius_deg=radius,cover_proof='Closed RA/Dec rectangles partition [-90,90]x[0,360], with longitude wrap and poles. Each rectangle uses its midpoint; angular distance maximum lies on longitude edges and a latitude endpoint, giving the computed corner radius. All continuous sphere centers are covered.')


def load_graph(card):
    path=RESOURCE/f'{card}_dual_certificate.npz'
    if path.exists():
        d=np.load(path)
        return dict(i=d['target_index'],k=d['slot_index'],v=d['edge_visible_900s_capacity'],r=d['edge_factor_per_900s_upper'],cap=d['slot_fiber_900s_capacity'],science=d['science_slope'],p=d['required_reward'],effective_p=d['effective_required_reward'],gmax=d['target_max_single_exposure_factor_upper'],threshold=float(d['required_threshold']))
    sys.path.insert(0,str(BASE/'research'))
    from cold_probabilistic_resource_graph import graph
    sc=load_scenario(BASE/f'upstream/gosim-observer-examples/local-cards/{card}/config/v4_scenario.json')
    return graph(sc)


def run(card,step=1.):
    started=time.time();sc=load_scenario(BASE/f'upstream/gosim-observer-examples/local-cards/{card}/config/v4_scenario.json');g=load_graph(card)
    centers,cover=covering(step)
    targets=np.array([[math.cos(math.radians(t['dec_deg']))*math.cos(math.radians(t['ra_deg'])),math.cos(math.radians(t['dec_deg']))*math.sin(math.radians(t['ra_deg'])),math.sin(math.radians(t['dec_deg']))] for t in sc.targets])
    field=sc.fiber_config['field'];fibers=int(field['n_fibers']);side=FiberGrid.from_config(sc.fiber_config).fov_side_deg
    corner=math.degrees(math.atan(math.sqrt(2)*math.radians(side/2)))+1e-7
    radius=corner+cover['maximum_cover_radius_deg']+1e-7
    chord=2*math.sin(math.radians(radius)/2)
    groups=cKDTree(targets).query_ball_point(centers,chord)
    active=np.array([j for j,inds in enumerate(groups) if inds],np.int32)
    maxcount=max(max(len(groups[j]) for j in active),fibers)
    neighbors=np.full((len(active),maxcount),len(targets),np.int32)
    for row,j in enumerate(active):neighbors[row,:len(groups[j])]=groups[j]
    maxrate=np.zeros(len(targets));np.maximum.at(maxrate,g['i'],g['r'])
    a=g['science'];gmax=g['gmax'];p=g['effective_p'];threshold=g['threshold']
    choices={'zero':np.zeros(len(a)),'science_slope':a.copy()}
    for price in (.03,.1,.25,.5):choices[f'normalized_price_{price}']=np.minimum(a,price/np.maximum(maxrate,1e-12))
    labels=list(choices);nus=np.array(list(choices.values()))
    z=np.vstack([np.zeros(len(a)),np.minimum(threshold,gmax),gmax])
    rewards=np.vstack([np.zeros(len(a)),a*np.minimum(threshold,gmax)+p,a*gmax+p])
    conjugates=np.array([np.sum(np.max(rewards-z*nu,axis=0),dtype=np.longdouble)-np.sum(g['p'],dtype=np.longdouble) for nu in nus],np.longdouble)
    totals=np.zeros(len(labels),np.longdouble);no_spatial=np.zeros(len(labels),np.longdouble)
    cuts=np.searchsorted(g['k'],np.arange(len(g['cap'])+1))
    slot_supports=[]
    # A fixed circle candidate matrix in equatorial coordinates covers every
    # time-dependent horizontal pointing; Earth rotation never changes targets'
    # pairwise sphere distances or the field's circumradius.
    for slot in range(len(g['cap'])):
        idx=g['i'][cuts[slot]:cuts[slot+1]];rate=g['r'][cuts[slot]:cuts[slot+1]]
        rates=np.zeros(len(a)+1);rates[idx]=rate
        seconds_units=g['cap'][slot]/fibers
        support=[];nospace=[]
        for j,nu in enumerate(nus):
            weighted=np.r_[nu,0.]*rates
            val=weighted[neighbors]
            top=np.partition(val,maxcount-fibers,axis=1)[:,maxcount-fibers:]
            # Longdouble sum and an outward epsilon on support avoid assigning
            # a lower support due only to floating-point summation.
            sums=np.sum(top,axis=1,dtype=np.longdouble)
            h=float(sums.max())*(1+1e-10)+1e-10
            plain=float(np.sum(np.partition(weighted[:-1],len(a)-fibers)[-fibers:],dtype=np.longdouble))
            totals[j]+=np.longdouble(seconds_units*h);no_spatial[j]+=np.longdouble(seconds_units*plain)
            support.append(h);nospace.append(plain)
        slot_supports.append({'resource_slot_index':slot,'support_upper':support,'top16_without_field':nospace})
        if slot%100==0:print(card,'slot',slot,'/',len(g['cap']),flush=True)
    bonus=sum(max(0.,float(q['completion_reward'])) for q in sc.observation_requests)+sum(e.event_type=='instrument_fault' for e in sc.events)*max(0.,float(sc.score_config['reporting']['correct_reward']))
    values={label:{'target_conjugate_minus_required_constant':float(conjugates[j]),'season_spatial_support':float(totals[j]),'season_top16_without_field_support':float(no_spatial[j]),'score_upper_before_padding':float(conjugates[j]+totals[j])+bonus,'score_upper_with_padding':float(conjugates[j]+totals[j])+bonus+1.} for j,label in enumerate(labels)}
    previous=json.loads((RESOURCE/f'{card}_summary.json').read_text())
    bestlabel=min(values,key=lambda k:values[k]['score_upper_with_padding']);best=values[bestlabel]['score_upper_with_padding']
    # Strengthen the target maximum SINGLE-exposure dose domain, without
    # changing spatial support. On equal 900s step-function slots, a length-
    # 3600s moving integral is piecewise linear in start time; a maximum is
    # attained at a slot edge. Thus four contiguous slot upper rates suffice.
    assert int(sc.fiber_config['exposure']['max_duration_seconds'])==3600
    assert all((z.end_utc-z.start_utc).total_seconds()==900 for z in sc.slots)
    slot_metadata=json.loads((RESOURCE/f'{card}_slot_prices.json').read_text())
    original=np.array([z['original_slot_index'] for z in slot_metadata],np.int32)
    rate_matrix=np.zeros((len(sc.slots),len(a)))
    rate_matrix[original[g['k']],g['i']]=g['r']
    window_cap=np.zeros(len(a));by_night={}
    for t,zs0 in enumerate(sc.slots):by_night.setdefault(zs0.slot_id.split('-S')[0],[]).append(t)
    for rows in by_night.values():
        q=rate_matrix[rows]
        if len(rows)<4:q=np.pad(q,((0,4-len(rows)),(0,0)))
        moving=q[:-3]+q[1:-2]+q[2:-1]+q[3:]
        window_cap=np.maximum(window_cap,moving.max(axis=0))
    window_cap=np.minimum(1.,window_cap*(1+1e-10)+1e-9)
    assert np.max(window_cap-gmax)<2e-8
    effective_p=np.where(window_cap>=threshold,g['p'],0.)
    capped_z=np.vstack([np.zeros(len(a)),np.minimum(threshold,window_cap),window_cap])
    capped_reward=np.vstack([np.zeros(len(a)),a*np.minimum(threshold,window_cap)+effective_p,a*window_cap+effective_p])
    contiguous_values={}
    for j,label in enumerate(labels):
        term=float(np.sum(np.max(capped_reward-capped_z*nus[j],axis=0),dtype=np.longdouble)-np.sum(g['p'],dtype=np.longdouble))
        contiguous_values[label]={'target_conjugate_minus_required_constant':term,'season_spatial_support':float(totals[j]),'score_upper_with_padding':term+float(totals[j])+bonus+1.}
    contiguous_best=min(contiguous_values,key=lambda z:contiguous_values[z]['score_upper_with_padding'])
    contiguous_upper=contiguous_values[contiguous_best]['score_upper_with_padding']
    report={'card':card,'status':'READY','full_sphere_cover':cover,'field_side_deg':side,'field_gnomonic_circumradius_deg':corner,'candidate_circle_radius_deg':radius,'nonempty_cover_cells':len(active),'padded_candidate_matrix_shape':list(neighbors.shape),'candidate_target_edges':sum(len(groups[j]) for j in active),'quality_source':'Complete local target-slot supremum graph, arbitrary repair efficiency upper, positive event multipliers, lunar<=1, continuous max-alt visibility envelope.','target_dual_candidates':labels,'dual_upper_values':values,'best_target_dual':bestlabel,'best_spatial_upper':best,'previous_complete_graph_upper':previous['total_upper'],'upper_tightening':previous['total_upper']-best,'contiguous_single_exposure_domain':{'duration_seconds':3600,'equal_slot_seconds':900,'window_slots':4,'bound_after_contiguous_domain':contiguous_upper,'best_target_dual':contiguous_best,'upper_tightening_from_previous':previous['total_upper']-contiguous_upper,'target_caps_sum_before':float(np.sum(gmax)),'target_caps_sum_after':float(np.sum(window_cap)),'additional_required_provably_impossible':int(np.sum((g['p']>0)&(window_cap<threshold)&(gmax>=threshold))),'dual_upper_values':contiguous_values,'attribute':'Any improvement here comes from continuous single-exposure time integration, not the tested spatial target-price refinement.'},'contains_latest_root_lower_bound':best>=dict(L1=6409.988920,L2=7006.280570)[card],'elapsed_seconds':time.time()-started,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'limitations':'Full continuous-pointing upper coverage. Circle cover is coarse and ignores individual fiber cells. Finite target-dual candidates, no optimality claim. Local truth weather conditional, not platform bound. No strategy replay or improvement.'}
    assert report['contains_latest_root_lower_bound']
    OUT.mkdir(parents=True,exist_ok=True)
    assert contiguous_upper>=dict(L1=6409.988920,L2=7006.280570)[card]
    np.savez_compressed(OUT/f'{card}_single_exposure_caps.npz',peak_slot_factor_cap=gmax,contiguous_four_slot_factor_cap=window_cap)
    (OUT/f'{card}_summary.json').write_text(json.dumps(report,indent=2)+'\n')
    (OUT/f'{card}_slot_supports.json').write_text(json.dumps({'target_dual_labels':labels,'slots':slot_supports},indent=2)+'\n')
    (OUT/f'{card}_proof.json').write_text(json.dumps({'proof':'An exposure-start hit target has gnomonic |x|,|y|<=side/2, hence angular center distance<=atan(sqrt(2)*side/2 in radians). Let c be the exposure-start actual_center converted to its fixed sidereally tracked RA/Dec center. Every initially hit target stays in this same spherical cap throughout the exposure by the official hit-at-start tracking rule. The actual_center is command plus offset; full-sphere coverage includes it without adding an offset radius. For every such arbitrary c, the complete sphere cover has a cell center b with angular(c,b)<=cover_radius. Spherical triangle inequality gives angular(target,b)<=field_radius+cover_radius. Thus the cell candidate list contains all true field targets. Their nonnegative weighted instantaneous dose sum is <=the cell top n_fibers weights using each target slot rate supremum. Maximum over all cells upper bounds every exposure-start actual pointing and every sidereally tracked initial-hit target set. Integrating this support over every full slot bounds the Lagrangian dose contribution for any real season. Target conjugates and required missing constants are identical to complete graph derivation; add request/report caps and zero upper Jain contribution.','coverage':'All 64,800 cells of full sphere considered; cells with no target have support exactly zero and may be omitted. Pole cells and longitude seam explicitly cover their closed rectangle boundaries.','group_query_numerics':'Spherical angular radius converted to Euclidean chord on unit vectors; three 1e-7 degree outward paddings cover circle/cover/query boundary rounding. Longdouble top16 sums, 1e-10 support outward padding, final 1 score tolerance. Numerical certificate, not interval arithmetic.','single_exposure_contiguous_cap_proof':'Per-target quality upper is a nonnegative step function constant on each 900s slot. A length<=3600s exposure within a night can be extended to length3600 in the relaxed night interval without reducing integrated dose. Its moving integral is piecewise linear between slot starts and starts shifted by3600; since3600 is four slots, maxima occur at slot edges and equal four contiguous slot upper rates. The integral uses raw dose only, not accumulated multiple exposures. A night shorter than3600 can be padded with zero upper rates. Target visibility constraints are relaxed by zero/nonzero slot rate envelopes, so the bound still contains every actual valid exposure. Added outward padding covers arithmetic.','no_old_columns':True},indent=2)+'\n')
    print(json.dumps(report),flush=True);return report

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    reports={c:run(c) for c in (sys.argv[1:] or ['L1','L2'])}
    (OUT/'summary.json').write_text(json.dumps(reports,indent=2)+'\n')
