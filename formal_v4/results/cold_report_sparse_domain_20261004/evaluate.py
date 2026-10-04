"""One fixed free-DP validation, then one frozen sparse-world test."""
import json,sys,time,hashlib
from pathlib import Path
import numpy as np
from sparse_world import ROOT,trajectory,designs
from report_core import ReportModel,ReportDP,nuisance_from_features
def run(split,offset,count):
    model=ReportModel();dp=ReportDP();rows=[];names=['none','oracle','p90_free','dp_free'];started=time.time()
    def policy(name,seed):
        if name=='none':return lambda *a:False
        if name=='oracle':return 'oracle'
        def act(x,q,j,total,nuisance):
            p=float(model.posterior(x))
            if name=='p90_free':return q>0 and p>.9
            public=designs()[['L1','L2'][seed%2]];now=public['actions'][j]['start']
            elapsed=sum(max(0.,min(now,n.observing_end_utc.timestamp())-n.observing_start_utc.timestamp()) for n in public['nights'] if now>n.observing_start_utc.timestamp())
            progress=elapsed/sum(n.night_seconds for n in public['nights'])
            return q>0 and dp.report(p,q,min(7,int(progress*8)),nuisance,progress,1.)
        return act
    for k in range(count):
        world={}
        for name in names:
            _,summary=trajectory(offset+k,policy=policy(name,offset+k));world[name]=summary
        rows.append(world);print(json.dumps(dict(split=split,seed=offset+k,scores={n:r['score'] for n,r in world.items()},seconds=time.time()-started)),flush=True)
    summary={}
    for name in names:
        gain=np.asarray([r[name]['score']-r['none']['score'] for r in rows]);regret=np.asarray([r['oracle']['score']-r[name]['score'] for r in rows])
        summary[name]=dict(score_mean=float(np.mean([r[name]['score'] for r in rows])),gain_over_none=float(gain.mean()),gain_standard_error=float(gain.std(ddof=1)/np.sqrt(count)),
            decision_regret=float(regret.mean()),science_mean=float(np.mean([r[name]['science'] for r in rows])),report_mean=float(np.mean([r[name]['report'] for r in rows])),
            correct_mean=float(np.mean([r[name]['correct'] for r in rows])),false_mean=float(np.mean([r[name]['false'] for r in rows])),wins_over_none=int((gain>1e-6).sum()),losses_over_none=int((gain<-1e-6).sum()))
    diff=np.asarray([r['dp_free']['score']-r['p90_free']['score'] for r in rows])
    out=dict(split=split,seeds=[offset,offset+count-1],seconds=time.time()-started,summary=summary,paired_dp_minus_p90=dict(mean=float(diff.mean()),standard_error=float(diff.std(ddof=1)/np.sqrt(count)),wins=int((diff>1e-6).sum()),losses=int((diff<-1e-6).sum())),raw=rows,
        limitations='fixed public actions, independent weather and independent official offset; best-only science and report; not strong counterfactual replanning, no data-loss/REQ/Jain production score')
    (ROOT/f'{split}_evaluation.json').write_text(json.dumps(out,indent=2));print(json.dumps(summary),flush=True);return out
if __name__=='__main__':
    mode=sys.argv[1] if len(sys.argv)>1 else 'val'
    if mode=='val':
        run('val',840000,8)
        lock=dict(selected='dp_free',rule='predeclared free-only; validation is no sweep',model_sha256=hashlib.sha256((ROOT/'report_model.npz').read_bytes()).hexdigest(),dp_sha256=hashlib.sha256((ROOT/'report_dp.npz').read_bytes()).hexdigest(),test_seed_first=850000,test_seed_last=850015,test_unopened=True)
        (ROOT/'selection_lock.json').write_text(json.dumps(lock,indent=2))
    elif mode=='test':
        lock=json.loads((ROOT/'SOURCE_LOCK.json').read_text());assert not (ROOT/'test_evaluation.json').exists()
        for n,h in lock['sha256'].items():assert hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h,n
        run('test',850000,16)
    else:raise ValueError(mode)
