"""After-run host diagnostics. Private columns never become actor features."""
from pathlib import Path
from collections import defaultdict
import csv
import hashlib
import json
import statistics

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[2]

def read(path):
    return list(csv.DictReader(path.open()))

def ah(action):
    return hashlib.sha256(json.dumps(action,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def ledger(rows):
    scores={};factors={};quality={};duration={}
    for x in rows:
        if x['valid']!='true':continue
        i=x['target_id'];s=float(x['score']);g=float(x['factor'])
        factors[i]=max(factors.get(i,0.),g)
        if s>scores.get(i,-1.):scores[i]=s;quality[i]=float(x['quality'])
    return scores,factors,quality

all_results=[]
for card in ('L1','L2'):
    folder=BASE/(card+'_night8');plan=json.loads((folder/'plan.json').read_text());cut=plan['cut_rank']
    targets={t['target_id']:t for t in read(ROOT/'formal_v4/upstream/gosim-observer-examples/local-cards'/card/'public/targets.csv')}
    past=[json.loads(x) for x in (folder/'prefix_public_actions.jsonl').read_text().splitlines()]
    source=ROOT/'formal_v4/results/request_geometry_integration_20261004/seasons/control'/card
    historical=[json.loads(x) for x in (source/'actions.jsonl').read_text().splitlines()]
    rank=0;historical_cut=None
    for j,x in enumerate(historical):
        if rank>=cut and x['action']=='observe':historical_cut=j;break
        rank+=x['action']=='observe'
    control_report=json.loads((folder/'control/score_report.json').read_text())
    for mode in ('control','surplus','debias'):
        run=folder/mode;rows=read(run/'observations.csv');decisions=read(run/'decisions.csv')
        prefix=[x for x in rows if int(x['observe_index'])<cut]
        before,beforef,_=ledger(prefix);after,afterf,quality=ledger(rows)
        traces=[json.loads(x) for x in (run/'participant_public_trace.jsonl').read_text().splitlines()]
        action_rows=[x for x in traces if x['action']['action']=='observe']
        acts=[json.loads(x) for x in (run/'actions.jsonl').read_text().splitlines()]
        report=json.loads((run/'score_report.json').read_text())
        class_rows=[]
        for c in sorted({x['target_class'] for x in targets.values()}):
            ids=[i for i,t in targets.items() if t['target_class']==c]
            gained=sum(after.get(i,0.)-before.get(i,0.) for i in ids)
            new_sat=sum(beforef.get(i,0.)<1.-1e-6 and afterf.get(i,0.)>=1.-1e-6 for i in ids)
            new_complete=sum(beforef.get(i,0.)<.5 and afterf.get(i,0.)>=.5 for i in ids)
            class_rows.append({'class':c,'science_increment':gained,'new_saturated':new_sat,'new_factor_half':new_complete,
                'new_covered':sum(i not in before and i in after for i in ids)})
        now=action_rows[0]['snapshot']['now_utc'];first=action_rows[0]['action'];firstrows=[x for x in rows if int(x['observe_index'])==cut]
        first_actual_gain=sum(max(0.,float(x['score'])-before.get(x['target_id'],0.)) for x in firstrows)
        time=sum(float(x['duration_seconds']) for x in decisions if x['action']=='observe' and int(x['observe_index'])>=cut)
        prefix_hash=hashlib.sha256(json.dumps(prefix,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        result={'card':card,'mode':mode,'total':report['total'],'delta_vs_control':report['total']-control_report['total'],
            'component_deltas':{k:v-control_report['components'][k] for k,v in report['components'].items()},
            'initial_public_scores':action_rows[0]['public_score_sum'],'initial_prefix_score':sum(before.values()),
            'prefix_official_rows_sha256':prefix_hash,'past_actions_match':all(ah(a)==ah(b) for a,b in zip(past,acts[:len(past)])),
            'first_mode':action_rows[0]['mode'],'first_now':now,'first_rank':action_rows[0]['snapshot']['observe_action_index'],
            'first_price':action_rows[0]['price'],'first_action':first,'first_action_matches_historical':ah(first)==ah(historical[historical_cut]),
            'first_actual_science_gain':first_actual_gain,'first_actual_science_rate':first_actual_gain/first['duration_seconds'],
            'night_science_increment':sum(after.values())-sum(before.values()),'night_observe_seconds':time,
            'night_realized_science_per_observe_second':(sum(after.values())-sum(before.values()))/time,
            'night_observes':len(action_rows),'duration_median':statistics.median(x['action']['duration_seconds'] for x in action_rows),
            'duration_mean':time/len(action_rows),'changed_local_controls':sum(x.get('baseline_action') is not None and ah(x['action'])!=ah(x['baseline_action']) for x in action_rows),
            'price_range':[min(x['price'] for x in action_rows),max(x['price'] for x in action_rows)],
            'class_rows':class_rows,'traceback':'Traceback' in (run/'agent.log').read_text(),
            'termination':report['termination']['reason']}
        all_results.append(result)
summary={'all_actor_modes_correct':all(x['mode']==x['first_mode'] for x in all_results),
    'all_past_actions_equal':all(x['past_actions_match'] for x in all_results),
    'public_score_sums_match':all(abs(x['initial_public_scores']-x['initial_prefix_score'])<1e-6 for x in all_results),
    'all_same_prefix_per_card':all(len({x['prefix_official_rows_sha256'] for x in all_results if x['card']==c})==1 for c in ('L1','L2')),
    'no_traceback':not any(x['traceback'] for x in all_results),
    'all_reached_short_stop':all(x['termination']=='agent_finished' for x in all_results),'results':all_results,
    'decision':'Surplus rejected: both short paired branches lose science and one required. No lambda tuning or full paired seasons. Debias has mixed results; no stable gain criterion met.'}
(BASE/'analysis_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='results'},indent=2))
for x in all_results:print(x['card'],x['mode'],x['delta_vs_control'],x['night_science_increment'],x['first_actual_science_rate'],x['night_realized_science_per_observe_second'],x['class_rows'])
