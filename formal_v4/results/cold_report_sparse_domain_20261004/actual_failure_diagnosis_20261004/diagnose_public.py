"""Read-only frozen model and already happened public feedback; no truth labels."""
from pathlib import Path
import sys,json,importlib.util,hashlib,collections,time
import numpy as np
HERE=Path(__file__).resolve().parent;SOURCE=HERE.parent;WORK=SOURCE.parents[2]
sys.path.insert(0,str(SOURCE/'candidate_package'))
from report_policy import make_policy_class
from report_core import ReportModel,ReportDP,state_index,NP
from research.agent_request_exact_cache import ExactCachedRequestPolicy
spec=importlib.util.spec_from_file_location('public_projection',WORK/'formal_v4/results/request_terminal_adaptation_20261004/check_adaptation.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
ACTUAL=WORK/'formal_v4/results/sparse_report_actual_20261004/seasons/sparse_report'
def logs(path):return [json.loads(s) for s in path.read_text().splitlines() if s.startswith('{')]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
rows={};features={};started=time.time()
for card in ['L1','L2','L3']:
    m.REFERENCE=ACTUAL;initial,snapshots,actions,meta=m.reconstruct(card)
    actor=make_policy_class(ExactCachedRequestPolicy)(initial);g=actor.persistent_guard;g.model=ReportModel(SOURCE/'report_model.npz');g.dp=ReportDP(SOURCE/'report_dp.npz')
    events=[r for r in logs(ACTUAL/card/'agent.log') if r.get('event')=='sparse_calibrated_report'];ranks={r['observe_action_index'] for r in events};selected=[];qualified=[];public_rows=[];previous=None
    for action_index,(snapshot,action) in enumerate(zip(snapshots,actions)):
        g.ingest(snapshot);rank=snapshot['observe_action_index'];ev=g.evidence(snapshot)
        if ev['qualified']:qualified.append(dict(rank=rank,free=2-g.false_count,quota_eligible=(2-g.false_count)>1,features=ev))
        pending=action if action['action']=='observe' else next((a for a in actions[action_index+1:] if a['action']=='observe'),None)
        # First report uses field az of its exact cached subsequent action.
        f=g.feature(snapshot,pending) if pending is not None else None
        if f is not None and (rank in ranks or (card=='L3' and 765<=rank<=772) or (card=='L3' and rank==961)):
            x,progress,nuisance=f;dp=g.dp.data;p=float(g.model.posterior(x));i=min(1023,int(1024*progress));s=int(state_index(p,*nuisance));ph=min(7,int(8*i/1024));q=max(0,2-g.false_count);pg=float(dp['pgrid'][s%NP]);V=dp['value'];K=dp['kernels']
            waitfuture=float(K[ph,0,s]@V[i+1,q]);truefuture=float(K[ph,1,s]@V[i+1,2]);falsefuture=float(K[ph,2,s]@V[i+1,max(0,q-1)]);loss=float(dp['loss'][ph,s]);delta=float(dp['delta'][i,q,s])
            noinfo=x.copy();noinfo[-37]=3.;noinfo[-36]=0.;noinfo[-33]=0.
            row=dict(rank=rank,action=action['action'],public_false_count=g.false_count,p=p,p_without_last_report_public_scalars=float(g.model.posterior(noinfo)),progress=progress,nuisance=nuisance,quota=q,pgrid=pg,report_age_clock_slots=float(x[-37]*32),quake_age_nights=float(x[-34]*20),
                v1_qualified=ev['qualified'],v1_quota_eligible=q>1,report_minus_wait=delta,dp_decomposition=dict(immediate_correct_reward=100*pg,immediate_wait_loss=loss,wait_future=waitfuture,correct_future=truefuture,false_future=falsefuture,report_future_mixture=pg*truefuture+(1-pg)*falsefuture),
                public_recent_ratios=[{k:r[k] for k in ['rank','night','slot','ratio_lo','ratio_hi','earthquake_notice']} for r in list(g.rows)[-5:]])
            selected.append(row);features[f'{card}_rank{rank}_{action["action"]}']=np.asarray(x,np.float32)
        g.sent(snapshot,action)
    entries=logs(ACTUAL/card/'agent.log');summary=next(r for r in reversed(entries) if 'persistent_fault_control' in r)
    controller=summary['persistent_fault_control'];actual_reports=[{k:r[k] for k in ['observe_action_index','posterior','report_minus_wait','quota','progress','nuisance']} for r in events]
    actual_results=[{k:r[k] for k in ['correct','repaired','score_delta']} for r in m.read_jsonl(ACTUAL/card/'messages.jsonl') if r['record_type']=='report_result']
    rows[card]=dict(actual_reports=actual_reports,public_report_results=actual_results,final_false_count=controller['false_reports_since_correct'],correct_reports=controller['correct_reports'],NN_queries=controller['sparse_report']['queries'],NN_seconds=controller['sparse_report']['seconds'],selected_public_states=selected,
        v1_qualified_states=qualified,first_blocked_v1_qualified=next((r for r in qualified if not r['quota_eligible']),None),
        public_source_sha256=meta['sources'],original_private_fields_read=False)
np.savez_compressed(HERE/'actual_public_features.npz',**features)
# L3 science actions should equal no-repair control after removing only new reports.
control=WORK/'formal_v4/results/request_terminal_pair_20261004/seasons/control/L3'
new=[r for r in m.read_jsonl(ACTUAL/'L3'/'actions.jsonl') if r['action']!='report'];old=[r for r in m.read_jsonl(control/'actions.jsonl') if r['action']!='report']
diff=next((j for j,(a,b) in enumerate(zip(new,old)) if a!=b),None)
rows['L3_action_parity']=dict(new_without_reports=len(new),control_without_reports=len(old),exact_equal=new==old,first_difference=diff)
baseline=WORK/'formal_v4/results/strategy_reassessment_actual_20261004/seasons/fault/L3';v1actions=m.read_jsonl(baseline/'actions.jsonl');first_report=next(j for j,a in enumerate(v1actions) if a['action']=='report')
prefix=v1actions[:first_report];rows['L3_action_parity']['v1_pre_correct_report_prefix_equal_control']=prefix==old[:len(prefix)]
rows['L3_action_parity']['v1_pre_report_prefix_actions']=len(prefix)
out=dict(public_only=True,actual_private_fault_dates_read=False,L4_read=False,frozen_model_or_policy_changed=False,seconds=time.time()-started,cards=rows)
(HERE/'public_causal_diagnosis.json').write_text(json.dumps(out,indent=2));print(json.dumps({k:dict(reports=v['actual_reports'],results=v['public_report_results'],first_blocked_v1_rank=(v['first_blocked_v1_qualified'] or {}).get('rank'),NN_seconds=v['NN_seconds']) for k,v in rows.items() if k!='L3_action_parity'}));print(json.dumps(rows['L3_action_parity']))
