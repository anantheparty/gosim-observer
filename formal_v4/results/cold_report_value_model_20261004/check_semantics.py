"""Small exact Bellman tree and official coupled repair/state contract checks."""
from __future__ import annotations
import json,sys,itertools,math,hashlib
from datetime import datetime,timezone,timedelta
from pathlib import Path
import numpy as np
from report_core import ReportDP,NP,NST
from report_world import World
from challenge.v4_scorer import WeatherTruth,SlotTruth,ScoreEvent,score_target_exposure,program_band,program_multiplier,_normalized_airmass
ROOT=Path(__file__).resolve().parent

def terminal(p,q):return max(0.,100*p-(150 if q==0 else 0)*(1-p))

def exact_tree(p,q,h,ell):
    # Enumerate report-now/no-report, and every public terminal outcome rule.
    vals=[]
    for initial_report in [False,True]:
        best=-math.inf
        outcomes=['correct','false'] if initial_report else ['wait']
        for choices in itertools.product([False,True],repeat=len(outcomes)):
            value=0.
            for f0 in [0,1]:
                pr0=p if f0 else 1-p
                outcome=('correct' if f0 else 'false') if initial_report else 'wait'
                qt=(2 if f0 else max(0,q-1)) if initial_report else q
                first=(100 if f0 else (-150 if q==0 else 0)) if initial_report else -ell*f0
                # A repaired existing event is still active: no new event is
                # drawn on the correct branch in this two-epoch micro-world.
                for new in [0,1]:
                    prnew=(h if new else 1-h) if not f0 else float(new==0)
                    ft=int((f0 and not initial_report) or (not f0 and new))
                    do=choices[outcomes.index(outcome)]
                    last=(100 if ft else (-150 if qt==0 else 0)) if do else 0.
                    value+=pr0*prnew*(first+last)
            best=max(best,value)
        vals.append(best)
    return vals

trees=0;maxerr=0.
for p,q,h,ell in itertools.product([0.,.005,.1,.35,.6,.9,1.],[0,1,2],[0.,.2],[0.,4.,30.]):
    expected=[-p*ell+terminal(p+(1-p)*h,q),p*100+(1-p)*(-150*(q==0)+terminal(h,max(0,q-1)))]
    got=exact_tree(p,q,h,ell);maxerr=max(maxerr,max(abs(a-b) for a,b in zip(expected,got)));trees+=1
assert maxerr<1e-10

dp=ReportDP().data;K=dp['kernels'];V=dp['value'];D=dp['delta']
assert np.all(np.isfinite(K)) and np.all(np.isfinite(V)) and np.all(np.isfinite(D))
assert np.max(np.abs(K.sum(-1)-1))<1e-12 and K.min()>=0
maxbad=0.
for ph,kind,s in itertools.product(range(8),range(3),range(NST)):
    count=s//(3*NP);wanted=min(2,count+(kind==1));bad=np.arange(NST)//(3*NP)!=wanted
    maxbad=max(maxbad,float(K[ph,kind,s,bad].sum()))
assert maxbad<1e-12
pp=np.tile(dp['pgrid'],9);pp[6*NP:]=0.
bellerr=0.
for i,q in itertools.product([0,127,512,1023],range(3)):
    ph=min(7,int(8*i/1024));wait=-dp['loss'][ph]+K[ph,0]@V[i+1,q]
    report=pp*(100+K[ph,1]@V[i+1,2])+(1-pp)*(-150*(q==0)+K[ph,2]@V[i+1,max(0,q-1)])
    bellerr=max(bellerr,float(np.max(np.abs(D[i,q]-(report-wait)))))
assert bellerr<1e-10

cfg=json.loads((ROOT.parent/'cold_predictive_world_model_20261004/official/challenge/reference/v4/v4_score_config.json').read_text());cfg.pop('lunar_model')
world=World(740000);slots=[]
for i,s in enumerate(world.slots):
    slots.append(SlotTruth(s.slot_id,s.timestamp_utc,s.end_utc,world.cc[i]>0,1.,float(world.cc[i])*.68,1.,float(world.eff[i])))
faults=[ScoreEvent(f.event_id,'instrument_fault',f.actual_start_utc,f.actual_end_utc,'ALL',None,None,None,None,1.,1.,1.,f.instrument_efficiency_multiplier) for f in world.faults]
weather=WeatherTruth(slots,faults);a=next(a for a in world.actions if world.active(a['start'],set()) is not None and world.cc[a['slot']]>0)
start=datetime.fromtimestamp(a['start'],timezone.utc);end=datetime.fromtimestamp(a['end'],timezone.utc)
f=weather.active_fault(start);modified=dict(a);modified['h']=np.full(len(a['ids']),_normalized_airmass(85.)**(-cfg['airmass_exponent']))
raw,c,z=world.score(modified,set());repaired,c1,z1=world.score(modified,{f.event_id})
segments=list(weather.segments(start,end));band=weather.band_quality(start,end,cfg,lambda t:85.)
mult=program_multiplier(['DARK','BRIGHT','BACKUP'][a['program']],program_band(band,cfg),cfg)
errors=[]
for repair,expected in [(False,raw),(True,repaired)]:
    if repair:assert weather.report_fault(start,cfg)==100. and weather.false_reports_since_correct==0
    for j,tid in enumerate(a['ids']):
        target=dict(target_id=str(tid),feature_flux=float(world.flux[tid]),science_weight=float(world.w[tid]))
        score=score_target_exposure(target,segments,[],weather,int(a['duration']),mult,cfg,start,lambda t:(85.,0.)).score
        errors.append(abs(round(score,6)-expected[j]))
assert max(errors)<1e-10 and weather.repair_fault(start) is False
assert weather.report_fault(start,cfg)==0. and weather.false_reports_since_correct==1
assert weather.report_fault(start,cfg)==0. and weather.false_reports_since_correct==2
assert weather.report_fault(start,cfg)==-150. and weather.false_reports_since_correct==3
assert weather._apply_fault(slots[a['slot']],start)>slots[a['slot']].instrument_efficiency
result=dict(passed=True,exhaustive_two_epoch_trees=trees,max_tree_error=maxerr,all_transition_rows=8*3*NST,
    public_count_violation_mass=maxbad,kernel_row_error=float(np.max(np.abs(K.sum(-1)-1))),bellman_recompute_error=bellerr,
    quota_route='wait same q; correct2; false max(q-1,0); paid penalty only q0; never implicit reset',
    official_shared_future_score_cases=len(errors),official_score_error=max(errors),official_correct_reset_and_repeat_false=True,
    model_sha256=hashlib.sha256((ROOT/'report_model.npz').read_bytes()).hexdigest(),dp_sha256=hashlib.sha256((ROOT/'report_dp.npz').read_bytes()).hexdigest(),test_read=False)
(ROOT/'semantics_checks.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
