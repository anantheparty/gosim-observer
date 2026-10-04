"""Observational support audit on already published original strong histories.

No policy planning replay, interventions or recovered runtime clock claim.
"""
from pathlib import Path
import importlib.util,sys,json
ROOT=Path(__file__).resolve().parent;WORK=ROOT.parents[2]
sys.path.insert(0,str(ROOT/'candidate_package'))
from research import agent_request_exact_cache as exact_entry
from report_policy import make_policy_class
from report_core import ReportModel,ReportDP
spec=importlib.util.spec_from_file_location('public_projection',WORK/'formal_v4/results/request_terminal_adaptation_20261004/check_adaptation.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
out={}
for card,reference in [('L1','request_geometry_integration_20261004'),('L2','request_geometry_integration_20261004'),('L3','request_terminal_pair_20261004')]:
    m.REFERENCE=WORK/f'formal_v4/results/{reference}/seasons/control'
    initial,snapshots,actions,metadata=m.reconstruct(card);actor=make_policy_class(exact_entry.ExactCachedRequestPolicy)(initial);g=actor.persistent_guard;g.model=ReportModel();g.dp=ReportDP()
    predictions=[];first=None
    for s,a in zip(snapshots,actions):
        s.pop('wallclock',None);s.pop('active_requests',None);g.ingest(s)
        f=g.feature(s,a) if a['action']=='observe' else None
        if a['action']=='observe' and f is not None and g.false_count<2 and g.correct<2:
            x,progress,nuisance=f;p=float(g.model.posterior(x));delta=g.dp.delta(p,2-g.false_count,int(8*progress),nuisance,progress,1.)
            row=dict(now_utc=s['now_utc'],rank=s['observe_action_index'],p=p,delta=delta,quota=2-g.false_count,nuisance=nuisance)
            predictions.append(row)
            if first is None and p>0 and delta>0:first=row
        g.sent(s,a)
    out[card]=dict(supported_sensor_records=g.supported,query_support_records=len(predictions),first_would_qualify=first,rejected=g.rejected,
        max_p=max([x['p'] for x in predictions],default=None),history_mode='original public score/notice/forecast observational audit; report outcomes not counterfactually synthesized; runtimeclock omitted',
        original_reports=g.correct+g.false_count,public_prediction_rows=predictions)
(ROOT/'public_support_audit.json').write_text(json.dumps(out,indent=2));print(json.dumps({k:{x:v for x,v in r.items() if x!='public_prediction_rows'} for k,r in out.items()}))
