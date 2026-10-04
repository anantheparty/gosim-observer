"""Only old declared cal/val, no test/model/threshold selection."""
import json,time,sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;SOURCE=HERE.parent
sys.path.insert(0,str(SOURCE))
from sparse_world import trajectory,designs
from report_core import ReportModel,ReportDP,state_index
old=ReportDP(SOURCE/'report_dp.npz');new=np.load(HERE/'diagnostic_free_only_dp.npz');model=ReportModel(SOURCE/'report_model.npz');data=np.load(SOURCE/'report_dataset.npz');out={};started=time.time()
def progress_at(seed,j):
    pub=designs()[['L1','L2'][seed%2]];now=pub['actions'][j]['start'];return sum(max(0.,min(now,n.observing_end_utc.timestamp())-n.observing_start_utc.timestamp()) for n in pub['nights'] if now>n.observing_start_utc.timestamp())/sum(n.night_seconds for n in pub['nights'])
for split,start in [('cal',830000),('val',840000)]:
    x=data[f'{split}_x'];p=model.posterior(x);s=state_index(p,data[f'{split}_quake'],data[f'{split}_correct']);phase=data[f'{split}_phase'];i=np.minimum(1023,((phase+.5)*128).astype(int));shadow={}
    for q in [1,2]:
        a=old.data['value'][i,q,s]-old.data['value'][i,q-1,s];b=new['value'][i,q,s]-new['value'][i,q-1,s]
        shadow[f'quota{q}_minus_quota{q-1}']=dict(original_paid_continuation_mean=float(a.mean()),constrained_free_continuation_mean=float(b.mean()),original_quantiles=np.quantile(a,[0,.5,.9,1]).tolist(),free_quantiles=np.quantile(b,[0,.5,.9,1]).tolist())
    worlds=[]
    for seed in range(start,start+8):
        scores={}
        for mode in ['original_free_actor','constrained_free_Bellman']:
            def policy(x,q,j,total,nuisance):
                if q<=0 or nuisance[1]>=2:return False
                p=float(model.posterior(x));progress=progress_at(seed,j)
                if mode=='original_free_actor':return old.report(p,q,0,nuisance,progress,1.)
                ii=min(1023,max(0,int(1024*progress)));ss=int(state_index(p,*nuisance));return p>0 and bool(new['report_allowed'][ii,q,ss]) and new['delta'][ii,q,ss]>0
            _,result=trajectory(seed,policy=policy);scores[mode]=result
        worlds.append(scores)
    out[split]=dict(shadow_price_state_projection='phase midpoint in identical original vs constrained lookup; samples at old fixed cal/val histories',quota_shadow=shadow,
        fixed_design_mean_scores={mode:float(np.mean([r[mode]['score'] for r in worlds])) for mode in ['original_free_actor','constrained_free_Bellman']},
        paired_constrained_minus_original=float(np.mean([r['constrained_free_Bellman']['score']-r['original_free_actor']['score'] for r in worlds])),raw=worlds)
    print(json.dumps(dict(split=split,means=out[split]['fixed_design_mean_scores'],quota_shadow=shadow)),flush=True)
out['limitations']='Diagnostic q0 action-set consistency only, same model/calibration/prior/K/L; not current faultv1 controller value; no test read, no threshold/model selection, not production candidate.';out['seconds']=time.time()-started
(HERE/'cal_val_free_diagnostic.json').write_text(json.dumps(out,indent=2))
