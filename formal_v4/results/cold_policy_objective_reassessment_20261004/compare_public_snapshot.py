"""Replay only public feedback of the frozen trace up to a strict trigger.

No scorer call, label, future truth, or speculative continuation is executed.
The prefix follows recorded actions; the final control/candidate normal decide
is the only planning call. This is a public-state candidate comparison.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import sys,csv,json,copy,time,hashlib,argparse
from pathlib import Path
from collections import defaultdict
from datetime import timedelta
import numpy as np

OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(OUT/'candidate_package'))
import public_open_recovery_entry as entry
from research.geometry import parse_utc,format_utc,local_sidereal_deg
from research.feedback_model import seasonal_quality
from research.request_remote_planner import PlannerBudgetFacade,DisabledRemoteFacade

def copy_facade(self,memo):
    other=object.__new__(type(self));memo[id(self)]=other
    other.__dict__.update(copy.deepcopy(self.__dict__,memo));return other

# Replay-only cloning support; no production file is edited.
PlannerBudgetFacade.__deepcopy__=copy_facade
DisabledRemoteFacade.__deepcopy__=copy_facade

def rows(p):return list(csv.DictReader(p.open()))
def dump(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def main(card,rank):
    initial_path=ROOT/f'formal_v4/results/policy_iteration_20261004/{card}_initialize_public.json'
    initial=json.loads(initial_path.read_text())
    source=ROOT/(f'formal_v4/results/sparse_fault_actual_20261004/seasons/fault_fast/{card}' if card in ['L1','L2'] else 'formal_v4/results/strategy_reassessment_actual_20261004/seasons/fault/L3')
    decisions=rows(source/'decisions.csv');actions=[json.loads(s) for s in (source/'actions.jsonl').read_text().splitlines()]
    # Official wait_until can produce many CSV slot rows for one actor action.
    # Only observe actions require exact alignment; waits do not change a ledger.
    observed_actions=iter(a for a in actions if a['action']=='observe')
    aligned=[]
    for d in decisions:
        if d['action']=='observe':
            a=next(observed_actions)
            assert a['duration_seconds']==int(d['duration_seconds'])
            assert len(a['assignments'])==int(d['assigned_count'])
        elif d['action']=='report':a={'action':'report'}
        else:a={'action':'wait','until_utc':d['end_utc']}
        aligned.append(a)
    hit_by_rank=defaultdict(list)
    for r in rows(source/'observations.csv'):
        hit_by_rank[int(r['observe_index'])].append(dict(target_id=r['target_id'],score=float(r['score'])))
    messages=sorted([json.loads(s) for s in (source/'messages.jsonl').read_text().splitlines()],key=lambda m:m['issued_at_utc'])
    actor=entry.wrapper.agent.Policy(initial);actor.public_open_recovery_enabled=False
    p=actor.planner;seen=[];pi=0;previous=None;index=0
    def snapshot(now,result):
        nonlocal pi
        new=[]
        while pi<len(messages) and parse_utc(messages[pi]['issued_at_utc'])<=now:
            new.append(messages[pi]);seen.append(messages[pi]);pi+=1
        bulletin=next((m for m in reversed(seen) if m.get('record_type')=='bulletin'),None)
        forecast=next((m for m in reversed(seen) if m.get('record_type')=='forecast'),None)
        requests={}
        for m in seen:
            if m.get('record_type')=='observation_request':requests[m['request_id']]=copy.deepcopy(m)
            elif m.get('record_type')=='observation_request_result':
                if m['request_id'] in requests:requests[m['request_id']].update(m)
        active=[m for m in requests.values() if parse_utc(m['issued_at_utc'])<=now<parse_utc(m['deadline_utc'])]
        return dict(now_utc=format_utc(now),observe_action_index=index,last_result=result,new_messages=new,
                    latest_bulletin=bulletin,latest_forecast=forecast,active_requests=active,
                    wallclock=dict(remaining_seconds=900.))
    start=time.perf_counter();prefix=[]
    for action,d in zip(aligned,decisions):
        now=parse_utc(d['start_utc']);s=snapshot(now,previous)
        actor.persistent_guard.ingest(s)
        actor._ingest_result(s);actor._messages(s)
        night=actor._night(now)
        if night>=0:actor.last_night=night
        if action['action']=='observe':
            seasonal,_=seasonal_quality(now.timetuple().tm_yday,p.q0)
            C,E=actor.belief_clock.prior(actor.C,actor.E,now,seasonal)
            alt,az,_,_=p._altaz(local_sidereal_deg(now,p.lon))
            prediction={t:dict(alt_deg=float(alt[p.index[t]]),az_deg=float(az[p.index[t]])) for t in action['assignments'].values()}
            actor.pending=dict(action=copy.deepcopy(action),start=now,prediction=prediction,
                               notices=copy.deepcopy(actor.notices),prior_C=C,prior_E=E)
            rr=int(d['observe_index']);assert rr==index
            previous=dict(action='observe',observe_index=rr,assigned_count=len(action['assignments']),hit_count=len(hit_by_rank[rr]),hits=hit_by_rank[rr])
            index+=1
        elif action['action']=='report':
            actor.pending=dict(action={'action':'report'})
            future=next(m for m in messages if m.get('record_type')=='report_result' and m['issued_at_utc']==d['end_utc'])
            previous={**future,'action':'report'}
        else:
            actor.pending=None
            # Frozen closure branch consumes its one-shot flag before a wait.
            actor.last_closed=False
            previous=dict(action=action['action'])
        actor.persistent_guard.sent(s,action)
        prefix.append(dict(now_utc=s['now_utc'],action=action,last_result=s['last_result'],new_messages=s['new_messages']))
        if action['action']=='observe' and rr==rank:
            s=snapshot(parse_utc(d['end_utc']),previous)
            break
    else:raise ValueError('Trigger not found')
    prefix_seconds=time.perf_counter()-start
    control=copy.deepcopy(actor);candidate=copy.deepcopy(actor)
    candidate.public_open_recovery_enabled=True
    t=time.perf_counter();control_action=control.decide(copy.deepcopy(s));control_seconds=time.perf_counter()-t
    t=time.perf_counter();candidate_action=candidate.decide(copy.deepcopy(s));candidate_seconds=time.perf_counter()-t
    expected_wait=dict(action='wait',until_utc=format_utc(p.nights[actor._night(parse_utc(s['now_utc']))][0]+timedelta(seconds=(int((parse_utc(s['now_utc'])-p.nights[actor._night(parse_utc(s['now_utc']))][0]).total_seconds()//actor.slot_seconds)+1)*actor.slot_seconds)))
    assert control_action==expected_wait
    event=getattr(candidate,'public_open_recovery_events',[])[-1:]
    prediction=candidate.pending.get('prediction',{}) if candidate.pending else {}
    science=0.;assigned_public_best={}
    for tid,pr in prediction.items():
        i=p.index[tid]
        pc=initial['scoring']['program']
        mult=pc['multipliers'][candidate_action['program']] if candidate_action['program']==pr['predicted_band'] else pc['mismatch_multiplier']
        assigned_public_best[tid]=float(candidate.scores[i])
        science+=max(0.,float(p.weight[i])*float(pr['factor'])*mult-float(candidate.scores[i]))
    # No truth values appear in this output. The original planner's prediction
    # fields are documented separately; they are not realized science.
    result=dict(card=card,rank=rank,snapshot=s,control_action=control_action,candidate_action=candidate_action,
                prefix_feedback_seconds=prefix_seconds,control_decide_seconds=control_seconds,candidate_decide_seconds=candidate_seconds,
                recovery_events=event,prediction=prediction,assigned_public_best=assigned_public_best,public_point_predicted_science_gain=science,
                public_point_predicted_science_rate=science/candidate_action['duration_seconds'] if candidate_action['action']=='observe' else 0.,
                source_initializer_sha256=hashlib.sha256(initial_path.read_bytes()).hexdigest(),
                scope='one normal planning call from public reconstructed prefix; no official future scoring or full season',
                actor_base_best_science=float(actor.scores.sum()),prefix_decisions=len(prefix),public_future_truth_reads=0)
    dump(OUT/f'{card}_R{rank}_PUBLIC_SNAPSHOT_COMPARISON.json',result)
    dump(OUT/f'{card}_R{rank}_PUBLIC_PREFIX.json',dict(initial=initial,prefix=prefix,current_snapshot=s))
    print(json.dumps({k:v for k,v in result.items() if k not in ['snapshot','prediction']},indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--card',choices=['L1','L2','L3'],default='L3');ap.add_argument('--rank',type=int,default=56);a=ap.parse_args();main(a.card,a.rank)
