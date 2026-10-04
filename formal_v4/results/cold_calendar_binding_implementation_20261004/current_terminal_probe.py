"""Candidate and certificate on current fault-v1 PURE PUBLIC terminal prefixes."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import json
from pathlib import Path
import sys
import time
OUT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(OUT/'package'))
sys.path.insert(0,str(OUT/'official'))
import binding_agent as entry
from binding_model import PublicScoreLedger,BoundarySearch,terminal_certificate
from challenge import v4_runner as vr
from challenge import v4_scorer as vs
from challenge.v4_fiber_map import FiberGrid,min_altitude_during
from challenge.v4_workflow import V4Workflow
from datetime import timedelta


def probe(card):
    begin=time.perf_counter()
    init=json.loads((OUT/f'public_inputs/{card}_initialize_public.json').read_text())
    prefix=json.loads((OUT/f'public_inputs/{card}_current_fault_public_terminal.json').read_text())
    ledger=PublicScoreLedger(init,family_weather_ratio=3.)
    ledger.best={r['target_id']:r['best_score'] for r in prefix['best_scores_public']}
    owner=entry.frozen.ExactCachedRequestPolicy(init)
    snapshot={k:prefix[k] for k in ['now_utc','survey_end_utc','observe_action_index','latest_bulletin','latest_forecast']}
    snapshot.update(last_result={'action':'wait'},new_messages=[],active_requests=[],wallclock={'remaining_seconds':900.})
    result=BoundarySearch(owner,ledger).search(snapshot,terminal=True)
    candidate=result['chosen']['action'] if result['chosen'] else None
    cert=terminal_certificate(init,snapshot,prefix['original_action'],candidate,ledger)
    protocol_valid=False;nominal_hits={}
    if candidate:
        targets=[dict(zip(init['targets']['columns'],row)) for row in init['targets']['rows']]
        fiber=json.loads((OUT/'v4_fiber_config.json').read_text());now=vr._parse_utc(prefix['now_utc']);end=vr._parse_utc(prefix['survey_end_utc'])
        slot=vs.SlotTruth('N_PUBLIC-S001',end-timedelta(seconds=900),end,False,0.,0.,0.,0.)
        config={'schema_version':'v4-scenario-v1','name':'public_protocol_only','site':init['site'],'minimum_altitude_deg':init['site']['minimum_altitude_deg'],'products':{'footprint_csv':'synthetic_footprint.csv'},'stress':{'enabled':False}}
        sc=vr.Scenario(config,OUT,init['site'],fiber,init['scoring'],targets,[slot],[],[],[],[],[],slot.start_utc,end)
        envelope=dict(candidate,protocol_version='participant-agent-protocol-v4',message_type='decision_response',decision_sequence=1)
        normalized=V4Workflow.action_from_response(envelope,1)
        vr.normalize_action(normalized,sc,{t['target_id']:t for t in targets},now);protocol_valid=True
        grid=FiberGrid.from_config(fiber);target_map={t['target_id']:t for t in targets}
        for f,tid in candidate['assignments'].items():
            target=target_map[tid];hit=grid.classify_target(target['ra_deg'],target['dec_deg'],now,candidate['pointing']['alt_deg'],candidate['pointing']['az_deg'],init['site']['latitude_deg'],init['site']['longitude_deg'])
            nominal_hits[tid]={'same_fiber':hit.region=='glass' and hit.fiber_id==int(f),'minimum_altitude_deg':min_altitude_during(target['ra_deg'],target['dec_deg'],now,end,{'site':init['site']})}
        assert all(r['same_fiber'] and r['minimum_altitude_deg']>=init['site']['minimum_altitude_deg'] for r in nominal_hits.values())
    return {'card':card,'prefix_now_utc':prefix['now_utc'],'observe_rank':prefix['observe_action_index'],'original_action':prefix['original_action'],
            'proposal':result,'certificate':cert,'legal_new_action':bool(cert['adopt']),'actual_weather_scored':False,'actual_score_gain_known':False,
            'private_columns_interpreted':[],'belief':'original unconditional public seasonal C/E prior; actual fault-policy latent belief not reconstructed',
            'baseline_comparison':'current fault-v1 literal terminal wait, not full-season replacement of fault-v1',
            'original_terminal_report_guard':'would freeze the literal wait and release it after a report; no wait-to-observe conversion',
            'public_resync_invalidated_ranks':prefix['public_invalidated_ranks'],'maximum_weather_component_ratio':3.,
            'official_protocol_and_normalizer_valid':protocol_valid,'official_nominal_geometry':nominal_hits,'unknown_actual_pointing_offset_used':False,
            'analytical_airmass_lower':ledger.family_airmass_lower,'maximum_raw_quality_with_airmass':ledger.family_max_raw_quality,
            'seconds':time.perf_counter()-begin}


if __name__=='__main__':
    result=[probe(card) for card in ['L1','L3']]
    (OUT/'current_terminal_summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps([{'card':r['card'],'now':r['prefix_now_utc'],'adopt':r['certificate']['adopt'],'assigned':len(r['proposal']['chosen']['action']['assignments']) if r['proposal']['chosen'] else 0,
                       'predicted_gain':r['proposal']['chosen']['predicted_science_gain'] if r['proposal']['chosen'] else None,'seconds':r['seconds']} for r in result],indent=2))
