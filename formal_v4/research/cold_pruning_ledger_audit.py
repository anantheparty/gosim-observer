#!/usr/bin/env python3
"""Exact ledger compression by future-loss survival signatures; local output audit."""
from pathlib import Path
import sys, csv, json, math, hashlib, time
from datetime import datetime

HERE=Path(__file__).resolve().parents[1]
UPSTREAM=HERE/'upstream/gosim-observer-examples'
sys.path.insert(0,str(UPSTREAM/'runner'))
from challenge.v4_runner import load_scenario,_data_loss_plan
from challenge.v4_scorer import BestLedger,observation_request_status

def utc(x):return datetime.fromisoformat(x.replace('Z','+00:00'))

def compress(rows,requests,signature):
    groups={}
    for i,row in enumerate(rows):
        groups.setdefault((row['target_id'],signature(row['action_index'])),[]).append(i)
    retained=set()
    for indices in groups.values():
        retained.add(max(indices,key=lambda i:rows[i]['score']))
        retained.add(max(indices,key=lambda i:rows[i]['factor']))
        for request in requests:
            eligible=[i for i in indices if request['issued_at_utc']<=rows[i]['start'] and rows[i]['end']<=request['deadline_utc']]
            if eligible:retained.add(max(eligible,key=lambda i:rows[i]['factor']))
    return [rows[i] for i in sorted(retained)],len(groups)

def ledger(rows,first=None,last=None):
    l=BestLedger()
    for r in rows:l.record(r['action_index'],r['target_id'],r['factor'],r['score'],r['start'],r['end'])
    if first is not None:l.invalidate_window(first,last,'test_loss')
    return l

def status(l,requests):
    return {'best':l.best(),'factors':l.max_factors(),
            'requests':[observation_request_status(r,l) for r in requests]}

def toy_negative():
    # Best score has factor below .5; another lower score crosses required threshold.
    base=utc('2026-01-01T00:00:00Z')
    from datetime import timedelta
    req={'request_id':'toy','issued_at_utc':base,'deadline_utc':base+timedelta(seconds=120),
         'target_ids':['t'],'completion_factor_threshold':.5,'minimum_completed':1,'completion_reward':100.}
    rows=[{'action_index':0,'target_id':'t','factor':.49,'score':.588,'start':base,'end':base+timedelta(seconds=60)},
          {'action_index':1,'target_id':'t','factor':.51,'score':.51,'start':base+timedelta(seconds=180),'end':base+timedelta(seconds=240)}]
    l=ledger(rows); naive=ledger(rows[:1])
    assert l.best()==naive.best()
    assert l.max_factors()!=naive.max_factors()
    assert not observation_request_status(req,l)['completed']
    after=ledger(rows,0,1);naive_after=ledger(rows[:1],0,1)
    assert after.best() and not naive_after.best()
    # Extra coverage can decrease Jain: equal [1/2,1/2] -> [1,1/2].
    return {'best_score_factor':l.best()['t'][0],'independent_max_factor':l.max_factors()['t'],
            'request_completed':False,'score_after_loss':after.best()['t'][1],
            'best_only_score_after_loss':0.,'jain_before':1.,'jain_after_extra_coverage':.9}

def run(card,path,out):
    begun=time.perf_counter()
    scenario=load_scenario(UPSTREAM/'local-cards'/card/'config/v4_scenario.json')
    decisions={int(r['observe_index']):r for r in csv.DictReader((path/'decisions.csv').open()) if r['action']=='observe'}
    rows=[]
    for r in csv.DictReader((path/'observations.csv').open()):
        ai=int(r['observe_index']);d=decisions[ai]
        rows.append({'action_index':ai,'target_id':r['target_id'],'factor':float(r['factor']),'score':float(r['score']),
                     'start':utc(d['start_utc']),'end':utc(d['end_utc'])})
    plan=_data_loss_plan(scenario)
    if plan is None:
        candidate_ns=[0];signature=lambda ai:(True,)
    else:
        resync=next(json.loads(x) for x in (path/'messages.jsonl').read_text().splitlines() if json.loads(x).get('record_type')=='state_resync')
        actual_n=resync['invalidated_window']['action_count_at_trigger']
        prefix_n=int(.8*actual_n)
        rows=[r for r in rows if r['action_index']<prefix_n]
        candidate_ns=list(range(prefix_n,actual_n+65))
        signature=lambda ai:tuple(not(math.floor(plan.window_start_fraction*n)<=ai<math.floor(plan.window_end_fraction*n)) for n in candidate_ns)
    compressed,groups=compress(rows,scenario.observation_requests,signature)
    checked=0
    for n in candidate_ns:
        window=(None,None) if plan is None else (math.floor(plan.window_start_fraction*n),math.floor(plan.window_end_fraction*n))
        full=ledger(rows,*window);small=ledger(compressed,*window)
        assert status(full,scenario.observation_requests)==status(small,scenario.observation_requests)
        checked+=1
    result={'card':card,'scope':'Exact maxima and REQ-window maxima for a fixed raw history and enumerated possible frozen observe counts at one future loss; observation actions themselves are preserved.',
            'raw_entries':len(rows),'compressed_entries':len(compressed),'survival_target_groups':groups,
            'candidate_trigger_n_min':min(candidate_ns),'candidate_trigger_n_max':max(candidate_ns),
            'frozen_trigger_n_cases_checked':checked,'mismatches':0,'seconds':time.perf_counter()-begun,
            'input_sha256':{str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [path/'observations.csv',path/'decisions.csv',path/'messages.jsonl']}}
    print(json.dumps(result),flush=True)
    return result

def main():
    out=HERE/'results/cold_pruning_proofs_20261003';out.mkdir(parents=True,exist_ok=True)
    cases=[('L1',HERE/'results/gpu_direct_20261003/L1'),('L3',HERE/'results/gpu_phase_followup_20261003/phase/L3'),
           ('L4',HERE/'results/gpu_phase_followup_20261003/phase/L4')]
    result={'negative_examples':toy_negative(),'cases':[run(card,path,out) for card,path in cases]}
    (out/'ledger_compression.json').write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':main()
