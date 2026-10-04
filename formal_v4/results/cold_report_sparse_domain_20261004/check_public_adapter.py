"""Host/public actor feature parity without actor access to world truth."""
import sys,json,time,copy
from datetime import datetime,timezone
import numpy as np
from sparse_world import ROOT,World,PublicState
BASE=ROOT.parent/'cold_report_value_model_20261004'/'candidate_package';sys.path.insert(0,str(BASE));sys.path.insert(0,str(ROOT))
from research.agent_request_exact_cache import ExactCachedRequestPolicy
from report_policy import make_policy_class
from research.geometry import format_utc
started=time.time();features=0;maxerr=0.;herror=0.;hbit=True;zeros=0;allzero=0;reportcases=0
for seed in [810000,810001]:
    world=World(seed);actor=make_policy_class(ExactCachedRequestPolicy)(world.design['initial']);guard=actor.persistent_guard;public=PublicState(world)
    repaired=set();last=None;previous=world.geometry[0]['start']-1
    for j,a in enumerate(world.geometry):
        now=datetime.fromtimestamp(a['start'],timezone.utc);slot=int(a['slots'][0]);messages=[m for m in world.bulletins+world.forecasts if previous<datetime.fromisoformat(m['issued_at_utc'].replace('Z','+00:00')).timestamp()<=a['start']]
        forecast=next((f for f in reversed(world.forecasts) if datetime.fromisoformat(f['issued_at_utc'].replace('Z','+00:00')).timestamp()<=a['start']),{})
        snapshot=dict(now_utc=format_utc(now),observe_action_index=j,last_result=last,new_messages=messages,latest_bulletin=world.bulletins[slot],latest_forecast=forecast)
        guard.ingest(snapshot)
        action=dict(action='observe',duration_seconds=a['duration'],program=['DARK','BRIGHT','BACKUP'][a['program']],pointing=dict(alt_deg=a['pointing'][0],az_deg=a['pointing'][1]),assignments=dict(zip([str(f) for f in a['fibers']],a['target_ids'])))
        x=public.feature(world,j);f=guard.feature(snapshot,action)
        if x is not None and f is not None:
            error=float(np.max(np.abs(x-f[0])));maxerr=max(maxerr,error);features+=1
            if error>2e-6:raise AssertionError((seed,j,error,np.argmax(np.abs(x-f[0])),public.quake_start,guard.quake_start,a['night'],now,world.geometry[j-1]['night'],snapshot['latest_bulletin'],guard.last))
        elif x is not None and f is None:
            assert (a['start']-public.history[-1][1]>8*3600 or any((a['start']-r[1])/900>192 for r in public.history))
        # Report followed by the exact same physical action; later observations
        # are scored in the repaired same world. Every report feature is public.
        fault=world.active(a['start'],repaired)
        if j%177==0 or (fault is not None and reportcases<4):
            correct=fault is not None;guard.sent(snapshot,{'action':'report'});public.report(a['start'],correct)
            ack=dict(snapshot,last_result=dict(action='report',correct=correct,score_delta=100. if correct else 0.),new_messages=[dict(record_type='report_result',correct=correct)])
            guard.ingest(ack)
            if correct:repaired.add(fault.event_id)
            xx=public.feature(world,j);ff=guard.feature(ack,action)
            if xx is not None and ff is not None:assert np.max(np.abs(xx-ff[0]))<2e-6
            reportcases+=1
        guard.sent(snapshot,action);scores=world.score(j,repaired)[0];public.ingest(world,j,scores)
        zeros+=int((scores==0).sum());allzero+=int(len(scores)>=3 and np.all(scores==0))
        if j%100==0 and len(scores):
            idx=np.asarray([actor.planner.index[s] for s in a['target_ids']]);memo=actor._geometric_H(now,a['duration'],idx)
            raw=ExactCachedRequestPolicy._geometric_H(actor,now,a['duration'],idx)
            hbit=hbit and np.array_equal(memo,raw);herror=max(herror,float(np.max(np.abs(memo-a['h_public']))))
        last=dict(action='observe',observe_index=j,hits=[dict(target_id=s,score=float(v)) for s,v in zip(a['target_ids'],scores)],hit_count=len(scores),assigned_count=16);previous=a['start']
assert features>100 and maxerr<2e-6 and herror<1e-12 and hbit and allzero>0
out=dict(passed=True,public_features_compared=features,max_feature_absolute_error=maxerr,public_geometry_host_error=herror,memoized_H_bit_equal_original=hbit,zero_scores_retained=zeros,allzero_feedback_tokens=allzero,public_report_result_cases=reportcases,seconds=time.time()-started,actor_receives_only='public now, notices/forecast, actual-hit ids and scores, report result; never hidden offset/actual center/factor/quality/valid')
(ROOT/'public_adapter_checks.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
