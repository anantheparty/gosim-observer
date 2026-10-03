#!/usr/bin/env python3
"""Read-only audit of our own cloud_* participant-visible scoring artifacts.
Never loads practice truth. No estimate here is an official score improvement.
"""
from pathlib import Path
import csv,json,collections,math
BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'results/cold_probabilistic_model_20261003'
MULT={'DARK':1.2,'BRIGHT':1.12,'BACKUP':1.06}

def main():
    reports={}
    for card in ('alpha','beta','gamma','delta'):
        run=BASE/f'results/cloud_verified_portfolio_{card}_20261003'
        target={r['target_id']:r for r in csv.DictReader((BASE/f'practice_cards/{card}/{card}/public/targets.csv').open())}
        decisions={int(r['observe_index']):r for r in csv.DictReader((run/'decisions.csv').open()) if r['action']=='observe'}
        hits=list(csv.DictReader((run/'observations.csv').open()))
        valid=[r for r in hits if r['valid']=='true']
        pertarget=collections.defaultdict(list)
        for r in valid:pertarget[r['target_id']].append(r)
        uncertain=[];actualmissing=[]
        for tid,t in target.items():
            if t['required'].lower()!='true':continue
            rows=pertarget[tid];w=float(t['science_weight'])
            lower=max((max(0,float(r['score'])-.500001e-6)/w/max(MULT[decisions[int(r['observe_index'])]['program']],1.) for r in rows),default=0.)
            factor=max((float(r['factor']) for r in rows),default=0.)
            if factor>=.5 and lower<.5:
                uncertain.append({'target_id':tid,'actual_max_factor_from_own_output':factor,'online_factor_lower':lower,'max_score':max(float(r['score']) for r in rows),'exposures':len(rows)})
            if factor<.5:actualmissing.append(tid)
        messages=[json.loads(l) for l in (run/'messages.jsonl').read_text().splitlines() if l.strip()]
        requests={m['request_id']:m for m in messages if m['record_type']=='observation_request'}
        finalstatuses={m['request_id']:m for m in messages if m['record_type']=='observation_request_result'}
        probes=[]
        for reqid,status in finalstatuses.items():
            req=requests[reqid];threshold=float(req['completion_factor_threshold']);completed=set(status['completed_target_ids'])
            for tid in req['target_ids']:
                candidates=[]
                for r in pertarget[tid]:
                    d=decisions[int(r['observe_index'])]
                    if not(req['issued_at_utc']<=d['start_utc'] and d['end_utc']<=req['deadline_utc']):continue
                    norm=float(r['score'])/float(target[tid]['science_weight']);p=d['program']
                    candidates.append((r,d,norm,p))
                if tid not in completed:
                    for r,d,norm,p in candidates:
                        if norm>=threshold+1e-6:
                            assert float(r['prog_mult'])==MULT[p]
                            probes.append({'request_id':reqid,'target_id':tid,'observe_index':int(r['observe_index']),'proof':'not completed, but score/w>=threshold: declared program matched','program':p,'band_constraint':{'DARK':'B>=DARK_threshold','BRIGHT':'BRIGHT_threshold<=B<DARK_threshold','BACKUP':'B<BRIGHT_threshold'}[p],'score_over_weight':norm,'threshold':threshold})
                else:
                    possible=[q for q in candidates if q[2]>=threshold-1e-6]
                    if len(possible)==1:
                        r,d,norm,p=possible[0]
                        if norm<threshold*MULT[p]-1e-6:
                            assert float(r['prog_mult'])==1.
                            probes.append({'request_id':reqid,'target_id':tid,'observe_index':int(r['observe_index']),'proof':'only possible completing exposure, score/w<threshold*match: declared program mismatched','program':p,'band_constraint':{'DARK':'B<DARK_threshold','BRIGHT':'B<BRIGHT_threshold OR B>=DARK_threshold','BACKUP':'B>=BRIGHT_threshold'}[p],'score_over_weight':norm,'threshold':threshold})
        score=json.loads((run/'score_report.json').read_text())
        reports[card]={'run':str(run),'official_replay_total_of_existing_run':score['total'],'official_required_missing':score['counts']['required_missing'],'required_completed_but_uncertified_from_score_alone':len(uncertain),'uncertified_targets':uncertain,'request_status_digital_band_probes':probes,'probe_count':len(probes),'scope':'Our own public participant scoring outputs only. Existing run, read-only. Positive/negative request status inference can be online; actual factor/prog_mult are used only for post-run verification.'}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'cloud_factor_information_audit.json').write_text(json.dumps(reports,indent=2)+'\n')
    print(json.dumps({c:{k:r[k] for k in ('official_required_missing','required_completed_but_uncertified_from_score_alone','probe_count')} for c,r in reports.items()},indent=2))
if __name__=='__main__':main()
