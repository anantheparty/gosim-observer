"""Finite public-history boundary inventory, no altered-history feedback replay."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import hashlib
import json
from pathlib import Path
import sys
import time
OUT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(OUT/'package'))
import binding_agent as entry
from binding_model import PublicScoreLedger,BoundarySearch,terminal_certificate,prenight_certificate
from research.geometry import parse_utc


def probe(card):
    begin=time.perf_counter();initpath=OUT/f'public_inputs/{card}_initialize_public.json';hp=OUT/f'public_inputs/{card}_history.json'
    init=json.loads(initpath.read_text());history=json.loads(hp.read_text())['public_history']
    ledger=PublicScoreLedger(init,family_weather_ratio=3.);owner=None;rows=[];selected=set();all_tail_counts=0
    bulletin=forecast=None;requests={}
    nights=[(parse_utc(n['observing_start_utc']),parse_utc(n['observing_end_utc'])) for n in init['survey']['nights']]
    for step,h in enumerate(history):
        ledger.ingest(h)
        for msg in h.get('new_messages',[]):
            kind=msg.get('record_type')
            if kind=='bulletin':bulletin=msg
            elif kind=='forecast':forecast=msg
            elif kind=='observation_request':requests[msg['request_id']]=msg
        now=parse_utc(h['now_utc']);night=next(((a,b) for a,b in nights if a<=now<b),None)
        tail=night is not None and 0<(night[1]-now).total_seconds()<init['instrument']['exposure']['min_duration_seconds'] and h['action'].get('action')=='wait'
        gap=night is None and h['action'].get('action')=='wait'
        if tail:all_tail_counts+=1
        kind='tail' if tail else 'gap' if gap else None
        if kind is None or kind in selected:continue
        selected.add(kind)
        if owner is None:owner=entry.frozen.ExactCachedRequestPolicy(init)
        # This is a proposal inventory. C/E is the original public unconditional
        # prior, explicitly not a claimed reconstruction of latent prefix state.
        search=BoundarySearch(owner,ledger)
        snapshot={**h,'survey_end_utc':init['survey']['end_utc'],'latest_bulletin':bulletin,'latest_forecast':forecast,'wallclock':{'remaining_seconds':900},
                  'active_requests':[r for r in requests.values() if parse_utc(r['deadline_utc'])>now]}
        if tail:
            result=search.search(snapshot,terminal=True)
            candidate=result['chosen']['action'] if result['chosen'] else None
            certificate=terminal_certificate(init,snapshot,h['action'],candidate,ledger)
        else:
            result=search.search(snapshot,terminal=False,lead=2700,effective_seconds=900)
            certificate=prenight_certificate(snapshot,result['chosen'])
        rows.append({'step':step,'observe_rank':h['observe_action_index'],'kind':kind,'now_utc':h['now_utc'],'original_action':h['action'],
                     'certificate':certificate,'proposal':result,'certified_complete_targets':len(ledger.completed()),
                     'certificate_family_weather_ratio':3.,'certificate_family_maximum_raw_quality':ledger.family_max_raw_quality,
                     'belief':'unconditional public seasonal prior; no fake feedback state',
                     'runtime_action_change':bool(certificate['adopt']),'actual_score_evaluated':False,'prefix_steps_consumed':step+1})
    return {'card':card,'history_steps':len(history),'history_last_utc':history[-1]['now_utc'],'survey_end_utc':init['survey']['end_utc'],
            'all_short_wait_tails_in_supplied_prefix':all_tail_counts,'terminal_prefix_observed':any(r['now_utc']==init['survey']['end_utc'] for r in rows),
            'rows':rows,'seconds':time.perf_counter()-begin,'history_sha256':hashlib.sha256(hp.read_bytes()).hexdigest(),
            'initialize_sha256':hashlib.sha256(initpath.read_bytes()).hexdigest(),'actual_factor_columns_read':False,'teacher_labels_read':False}


if __name__=='__main__':
    results=[probe(card) for card in ['L1','L2','L3']]
    (OUT/'public_prefix_summary.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps([{'card':r['card'],'tail_count':r['all_short_wait_tails_in_supplied_prefix'],'rows':[{'kind':x['kind'],'step':x['step'],'reason':x['certificate']['reason'],'predicted_gain':x['proposal']['chosen']['predicted_science_gain'] if x['proposal']['chosen'] else None} for x in r['rows']],'seconds':r['seconds']} for r in results],indent=2))
