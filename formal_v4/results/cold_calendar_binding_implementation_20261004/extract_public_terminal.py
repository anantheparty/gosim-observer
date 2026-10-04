"""Whitelist the real L1/L2/L3 action/score prefixes; never decode factors.

CSV fields not in PUBLIC_OBSERVATION_FIELDS are opaque transport strings and
are immediately discarded. No float conversion, feature, output or actor input
is made from factor, quality, program-multiplier, fiber, or truth products.
Validity is derived only from participant-visible state_resync rank windows.
"""
import csv
import hashlib
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
PUBLIC_OBSERVATION_FIELDS=('observe_index','target_id','score')


def extract(card):
    source=ROOT/f'formal_v4/results/strategy_reassessment_actual_20261004/seasons/fault/{card}'
    actions=[json.loads(line) for line in (source/'actions.jsonl').open() if line.strip()]
    decisions=list(csv.DictReader((source/'decisions.csv').open()))
    last=decisions[-1]
    if actions[-1].get('action')!='wait':
        return {'card':card,'terminal_original_kind':actions[-1]['action'],'eligible':False,'reason':'original_terminal_action_is_not_wait'}
    now=last['start_utc'];end=last['end_utc']
    messages=[json.loads(line) for line in (source/'messages.jsonl').open() if line.strip()]
    messages=[m for m in messages if m.get('issued_at_utc','')<=now]
    invalid=set()
    for message in messages:
        if message.get('record_type')=='state_resync':
            w=message['invalidated_window'];invalid.update(range(int(w['action_index_start']),int(w['action_index_end_exclusive'])))
    count=max(int(r['observe_index']) for r in decisions if r['action']=='observe')+1
    public_scores=[]
    # Only the three columns that the protocol publishes are interpreted.
    with (source/'observations.csv').open(newline='') as handle:
        reader=csv.reader(handle);header=next(reader);positions=[header.index(k) for k in PUBLIC_OBSERVATION_FIELDS]
        for opaque_row in reader:
            selected=[opaque_row[j] for j in positions]
            row=dict(zip(PUBLIC_OBSERVATION_FIELDS,selected))
            if int(row['observe_index'])<count:
                public_scores.append({'observe_index':int(row['observe_index']),'target_id':row['target_id'],'score':float(row['score'])})
    best={}
    for row in public_scores:
        if row['observe_index'] not in invalid:
            best[row['target_id']]=max(best.get(row['target_id'],0.),row['score'])
    def latest(kind):
        rows=[m for m in messages if m.get('record_type')==kind];return rows[-1] if rows else None
    result={'card':card,'eligible':True,'now_utc':now,'survey_end_utc':end,'observe_action_index':count,
            'original_action':actions[-1],'best_scores_public':[{'target_id':t,'best_score':s} for t,s in sorted(best.items())],
            'public_invalidated_ranks':sorted(invalid),'latest_bulletin':latest('bulletin'),'latest_forecast':latest('forecast'),
            'full_public_score_prefix':public_scores,'future_truth_used':False,'private_columns_interpreted':[],
            'source_fault_zip_sha256':'bd461164340f4adf490ace91003d49f7205a6ea631f712e9767f3527ec9549ba',
            'provenance':{'source':str(source),'hashes':{name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in ['actions.jsonl','decisions.csv','messages.jsonl','observations.csv']}}}
    (OUT/f'public_inputs/{card}_current_fault_public_terminal.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    return {'card':card,'eligible':True,'now_utc':now,'end_utc':end,'observe_rank':count,'public_scores':len(public_scores),'invalid_rank_count':len(invalid)}


if __name__=='__main__':
    results=[extract(card) for card in ['L1','L2','L3']]
    (OUT/'public_terminal_extraction.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results,indent=2))
