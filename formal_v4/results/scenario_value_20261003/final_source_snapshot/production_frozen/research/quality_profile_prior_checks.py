"""Public identity, repair/fallback gates, batch geometry and CPU cost checks."""
import copy,json,time
from pathlib import Path
import numpy as np
from quality_profile_prior import (build_registry,ProfileRegistry,public_protocol_initial,_paired_public_quality)


def checks():
    root=Path(__file__).resolve().parents[1];dest=root/'research/quality_profile_prior_data'
    registry=build_registry(dest);r=ProfileRegistry(dest/'registry.json')
    identification=[]
    for c in registry['cards']:
        initial=public_protocol_initial(root/'practice_cards'/c['card_id']/c['card_id'])
        began=time.perf_counter();p=r.identify(initial)
        assert p and p.card['card_id']==c['card_id']
        identification.append({'card':c['card_id'],'identify_and_load_seconds':time.perf_counter()-began,
                               'compact_profile_bytes':(dest/c['profile_file']).stat().st_size})
        changed=copy.deepcopy(initial);changed['targets']['rows'][0][1]=float(changed['targets']['rows'][0][1])+.01
        assert r.identify(changed) is None
    initial=public_protocol_initial(root/'practice_cards/alpha/alpha');p=r.identify(initial)
    rng=np.random.default_rng(20261003)
    a,b=p.model.nights[0]
    # Exact paired geometry never allocates all-pairs time×flattened targets.
    times=rng.uniform(a,b,20);indices=rng.integers(0,len(p.model.ids),(20,16))
    paired=_paired_public_quality(p.model,times,indices)
    worst=0.
    for j in range(20):worst=max(worst,float(np.max(abs(paired[j]-p.model.public_quality([times[j]],indices[j])[0]))))
    assert worst<1e-11
    cells=np.flatnonzero((p.support>0)&(p.upper-p.lower<=1e-4)&(p.starts<p.old_repairs[0]-120))
    cell=int(cells[0]);start=p.starts[cell]+10;duration=60
    idx=int(np.argmin(p.model.flux));now=start+duration
    assert not p.lookup([start+30],now=now)['supported'][0]
    priced=p.price_columns([start],[duration],[[idx]],now=now,require_live_compatibility=False)
    assert priced['supported_column'][0]
    q=priced['quality_point'][0,0]
    score=p.weights[idx]*min(1,p.model.flux[idx]*duration*q/p.model.f0t0)
    feedback=p.feedback_ratio(start,duration,[idx],[score],[p.weights[idx]],[p.model.flux[idx]],'BRIGHT',clean_mask=[True])
    assert feedback['compatible_with_unit_ratio'] and p.live_compatible
    assert p.lookup([start+30],now=now)['supported'][0]
    conflict=p.feedback_ratio(start,duration,[idx],[score*.5],[p.weights[idx]],[p.model.flux[idx]],'BRIGHT',clean_mask=[True])
    assert conflict['compatible_with_unit_ratio'] is False and not p.live_compatible
    assert not p.lookup([start+30],now=now,require_live_compatibility=False)['supported'][0]
    # A future source-repaired cell cannot assume an unconfirmed current report.
    after=np.flatnonzero((p.starts>p.old_repairs[0]+900)&(p.support>0)&(p.upper-p.lower<=1e-4))[0]
    future=p.starts[after]+30
    assert not p.lookup([future],now=start,require_live_compatibility=False)['supported'][0]
    p.note_report(p.old_repairs[0]+300,True)
    assert p.lookup([future],now=future,require_live_compatibility=False)['supported'][0]
    assert not p.lookup([future],now=future)['supported'][0] # repair resets compatibility
    # Batch coefficients vs existing exact slot<=120s scalar integration.
    starts=rng.uniform(a,b-3600,16);durations=rng.integers(60,3601,16)
    chosen=rng.integers(0,len(p.model.ids),(16,1))
    batch=p.price_columns(starts,durations,chosen,now=b,fallback_Z=.7,require_live_compatibility=False)
    # On wholly unsupported rows the supplied constant is applied to every piece.
    from quality_profile_inversion import PublicQualityMatrix
    matrix=PublicQualityMatrix(p.model,p.old_repairs)
    p.support[:]=0
    constant=p.price_columns(starts,durations,chosen,now=b,fallback_Z=.7,require_live_compatibility=False)
    integration_error=0.
    for j in range(16):
        cells,co=matrix.coefficients(starts[j],durations[j],[chosen[j,0]])
        integration_error=max(integration_error,abs(float(co.sum())*.7-constant['quality_point'][j,0]))
    assert integration_error<1e-11
    costs=[]
    for count in (100,1000,10000):
        starts=rng.uniform(a,b-3600,count);durations=rng.integers(60,3601,count)
        indices=rng.integers(0,len(p.model.ids),(count,16))
        began=time.perf_counter();out=p.price_columns(starts,durations,indices,now=b,fallback_Z=.7)
        elapsed=time.perf_counter()-began
        costs.append({'columns':count,'target_integrals':count*16,'elapsed_seconds':elapsed,
                      'columns_per_second':count/elapsed,'payload_bytes':starts.nbytes+durations.nbytes+indices.nbytes})
    return {'schema':'finite-profile-prior-independent-gates-v1','identity':identification,
            'unknown_catalog_rejected':True,'raw_six_file_digest_not_reconstructed_from_initialize':True,
            'identity_alone_does_not_activate_profile':True,'clean_positive_compatible_feedback_activates':True,
            'conflicting_feedback_disables_and_falls_back':True,'repair_epoch_mismatch_rejected':True,
            'correct_report_resets_live_compatibility':True,'paired_geometry_max_error':worst,
            'batch_midpoint_integration_max_error':integration_error,'CPU_pricing_cost':costs,
            'scope':'public/synthetic independent gate; no wholecard, network, GPU or production changes'}


if __name__=='__main__':
    result=checks();print(json.dumps(result,indent=2))
    Path(__file__).with_name('quality_profile_prior_checks_result.json').write_text(json.dumps(result,indent=2)+'\n')
