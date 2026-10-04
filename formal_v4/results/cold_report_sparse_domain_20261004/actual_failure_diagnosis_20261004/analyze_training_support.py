"""Train/cal-only conditional support diagnostic; no new model or test use."""
import json,time
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;SOURCE=HERE.parent
import sys
sys.path.insert(0,str(SOURCE/'candidate_package'))
from report_core import ReportModel
data=np.load(SOURCE/'report_dataset.npz');model=ReportModel(SOURCE/'report_model.npz');actual=np.load(HERE/'actual_public_features.npz');result={}
for split in ['train','cal']:
    x=data[f'{split}_x'];y=data[f'{split}_y'];phase=data[f'{split}_phase'];p=model.posterior(x);out={}
    groups={'all':np.ones(len(x),bool),'negative_report_history':x[:,-36]<-.5,'negative_report_quake_first4nights':(x[:,-36]<-.5)&(x[:,-34]>0)&(x[:,-34]<=.2),
        'L3_second_attempt_coarse_state':(x[:,-36]<-.5)&(x[:,-35]==0)&(x[:,-34]>0)&(x[:,-34]<=.2)&(phase==3),
        'negative_report_next17h':(x[:,-36]<-.5)&(x[:,-37]>0)&(x[:,-37]<=17.3*4),
        'negative_report_next17h_quake_phase3':(x[:,-36]<-.5)&(x[:,-35]==0)&(x[:,-34]>0)&(x[:,-34]<=.2)&(phase==3)&(x[:,-37]<=17.3/8)}
    # Report age feature is age_clock_slots/32; 17.3h = 69.2slots/32.
    groups['negative_report_next17h']=(x[:,-36]<-.5)&(x[:,-37]>0)&(x[:,-37]<=17.3/8)
    for name,s in groups.items():
        out[name]=dict(records=int(s.sum()),worlds=int(len(set(data[f'{split}_world'][s]))),active_prevalence=float(y[s].mean()) if s.any() else None,mean_prediction=float(p[s].mean()) if s.any() else None,
            high_p_ge65_records=int((s&(p>=.65)).sum()),high_p_ge65_worlds=int(len(set(data[f'{split}_world'][s&(p>=.65)]))),high_p_ge65_actual=float(y[s&(p>=.65)].mean()) if (s&(p>=.65)).any() else None)
    result[split]=out
# Exact source-prior first-arrival probability after a public false report and
# zero prior correct reports. It is an innovation prior, not posterior bound.
WORK=SOURCE.parents[2];initial=json.loads((WORK/'formal_v4/results/policy_iteration_20261004/L3_initialize_public.json').read_text())
from datetime import datetime,timedelta
slots=[]
for n in initial['survey']['nights']:
    t=datetime.fromisoformat(n['observing_start_utc'].replace('Z','+00:00'))
    slots.extend([(t+timedelta(seconds=900*j)).timestamp() for j in range(int(n['slot_count']))])
events=[json.loads(s) for s in (WORK/'formal_v4/results/sparse_report_actual_20261004/seasons/sparse_report/L3/agent.log').read_text().splitlines() if s.startswith('{') and json.loads(s).get('event')=='sparse_calibrated_report']
k=[int(np.searchsorted(slots,datetime.fromisoformat(e['now_utc'].replace('Z','+00:00')).timestamp(),side='right')-1) for e in events];N=len(slots);jitter=np.arange(-200,201)
def survival(index):
    one=np.mean(int(N/2)+jitter>index)
    two=np.mean(int(N/3)+jitter>index)*np.mean(int(2*N/3)+jitter>index)
    return .25+.5*one+.25*two
h=(survival(k[0])-survival(k[1]))/survival(k[0]);p=events[1]['posterior'];bf=(p/(1-p))/(h/(1-h)) if h>0 else None
result['source_prior_innovation']=dict(public_L3_total_slots=N,slot_steps_between_false_and_second_attempt=k[1]-k[0],source_fault_count_prior=[.25,.5,.25],source_nominal_jitter='uniform integer -200..200',conditional_new_first_fault_prior=h,
    LR_required_to_reach_second_report_p=bf,limitation='Uses declared training count/jitter prior on public L3 calendar; no actual onset/date read. Weather likelihood and prior shifts can change posterior; this is not a universal upper bound.')
result['no_train_or_validation_claim']=True;result['no_test_read_or_model_tuning']=True
(HERE/'training_conditional_support.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
