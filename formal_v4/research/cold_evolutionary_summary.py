#!/usr/bin/env python3
"""Collect paired native results and validate the complete terminal ledger."""
import json,hashlib
from pathlib import Path
import numpy as np
import cold_evolutionary_season as m

def main():
    summary={'scope':'finite local-truth oracle candidate experiment; one seed411 per mode/card','paired_budget_seconds':600,'concurrency':'eight simultaneous single CPU search processes, each600s elapsed budget','cards':{},'all_native_gates_pass':True}
    for card in m.SOURCES:
        s,sp,cols,initial,reports,expected=m.load_or_build(card,m.OUT/card/'prepare');engine=m.Season(s,cols,expected['components']['report_settlement'],np.random.default_rng(1));data={}
        for method in ['ga','local']:
            d=m.OUT/card/method;result=json.loads((d/'summary.json').read_text());native=result['native'];lookup={m.actionkey(c):i for i,c in enumerate(cols)};selected=[]
            for line in (d/'optimized_actions.jsonl').read_text().splitlines():
                a=json.loads(line);start=m.utc(a.pop('start_utc'));key=(int(start.timestamp()),int(start.timestamp())+a['duration_seconds'],json.dumps(a,sort_keys=True,separators=(',',':')))
                if key not in lookup:
                    # Original requested durations may be clipped at night end.
                    candidates=[i for i,c in enumerate(cols) if c['start']==key[0] and json.dumps(c['action'],sort_keys=True,separators=(',',':'))==key[2]]
                    if not candidates:raise RuntimeError('exported action is absent from column pool')
                    selected.append(candidates[0])
                else:selected.append(lookup[key])
            valid,loss=engine.valid(selected);invalid=set(selected)-set(valid);expected_invalid=sum(int(np.count_nonzero(cols[i]['ids']!=engine.n)) for i in invalid)
            trigger=m._data_loss_plan(s);straddlers=[] if trigger is None else [i for i in selected if cols[i]['start']<trigger.trigger_utc.timestamp()<cols[i]['end']]
            windows=[] if loss is None else [[loss['start'],loss['end_exclusive']]];native_windows=[x['window'] for x in native['invalidations']]
            obj=engine.objective(selected);components={'sum_best_scores':obj['science'],'required_penalty':-engine.penalty*obj['required_missing'],'uniformity_penalty':-obj['uniformity_penalty'],'report_settlement':obj['report_settlement'],'observation_request_reward':obj['request_reward']}
            errors={k:abs(float(v)-native['components'][k]) for k,v in components.items()};gate={'total_error':abs(obj['total']-native['total']),'component_errors':errors,'loss_windows_model':windows,'loss_windows_native':native_windows,'loss_windows_match':windows==native_windows,'expected_invalidated_observations':expected_invalid,'native_invalidated_observations':native['counts']['invalidated_observations'],'invalidated_count_match':expected_invalid==native['counts']['invalidated_observations'],'requests_completed_match':obj['requests_completed']==native['counts']['observation_requests_completed'],'required_missing_match':obj['required_missing']==native['counts']['required_missing'],'termination':native['termination'],'straddling_trigger_exposures':len(straddlers),'feasible_intervals':engine.legal(selected)}
            gate['passed']=gate['total_error']<1e-5 and max(errors.values())<1e-5 and all(gate[x] for x in ['loss_windows_match','invalidated_count_match','requests_completed_match','required_missing_match','feasible_intervals']) and native['termination']['reason']=='survey_complete';m.dump(d/'final_native_gate.json',gate)
            summary['all_native_gates_pass']&=gate['passed'];data[method]={'native_total':native['total'],'delta_vs_production':result['delta_vs_production'],'delta_vs_initial_strongest':result['delta_vs_initial_best'],'iterations':result['statistics']['iterations'],'elapsed_seconds':result['statistics']['elapsed_seconds'],'crossovers':result['statistics']['crossovers'],'gate':gate,'actions_path':str((d/'optimized_actions.jsonl').resolve()),'native_report_path':str((d/'optimized_native/score_report.json').resolve())}
        winner=max(data,key=lambda k:data[k]['native_total']);data['winner']=winner;data['ga_minus_local']=data['ga']['native_total']-data['local']['native_total'];summary['cards'][card]=data
    summary['conclusion']='Report per-card mixed outcomes; native GA vs local comparison includes lower GA throughput caused by population/crossover/diversity overhead. One seed and finite pool support no general statistical claim.';summary['source_sha256']=hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest();m.dump(m.OUT/'paired_summary.json',summary)
    print(json.dumps({'all_gates':summary['all_native_gates_pass'],'cards':{k:{x:v[x] for x in ['winner','ga_minus_local']} for k,v in summary['cards'].items()}}),flush=True)
if __name__=='__main__':main()
