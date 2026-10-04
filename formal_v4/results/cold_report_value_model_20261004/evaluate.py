"""One frozen validation selection, then one independent-world test evaluation."""
from __future__ import annotations
import json,sys,time,hashlib
from pathlib import Path
import numpy as np
from report_world import trajectory
from report_core import ReportModel,ReportDP
ROOT=Path(__file__).resolve().parent

def run(split,offset,count,names,selected=None):
    model=ReportModel();dp=ReportDP();rows=[]
    def make(name):
        if name=='none':return lambda *a:False
        if name=='oracle':return 'oracle'
        def policy(x,q,phase,nuisance,j,total):
            p=float(model.posterior(x))
            if name=='p90_free':return q>0 and p>.9
            if name=='myopic':return p>0 if q else p>.6
            if name=='dp_free':return q>0 and dp.report(p,q,phase,nuisance,j,total)
            return dp.report(p,q,phase,nuisance,j,total)
        return policy
    started=time.time()
    for k in range(count):
        scores={}
        for name in names:
            _,res=trajectory(offset+k,policy=make(name),collect=False);scores[name]=res
        rows.append(scores)
        print(json.dumps(dict(split=split,k=k,seed=offset+k,scores={name:round(r['score'],4) for name,r in scores.items()},seconds=time.time()-started)),flush=True)
    summary={}
    for name in names:
        gains=np.asarray([row[name]['score']-row['none']['score'] for row in rows]);regrets=np.asarray([row['oracle']['score']-row[name]['score'] for row in rows])
        summary[name]=dict(score_mean=float(np.mean([r[name]['score'] for r in rows])),gain_over_none=float(gains.mean()),
            gain_standard_error=float(gains.std(ddof=1)/np.sqrt(count)),decision_regret=float(regrets.mean()),
            science_mean=float(np.mean([r[name]['science'] for r in rows])),report_mean=float(np.mean([r[name]['report'] for r in rows])),
            correct_mean=float(np.mean([r[name]['correct'] for r in rows])),false_mean=float(np.mean([r[name]['false'] for r in rows])),
            wins_over_none=int((gains>1e-6).sum()),losses_over_none=int((gains<-1e-6).sum()))
    out=dict(split=split,seeds=[offset,offset+count-1],worlds=count,seconds=time.time()-started,summary=summary,raw=rows,
        limitation='Official generated weather and repair semantics; finite protected random sensor trajectories, best-only score, no production season score or REQ/Jain/data-loss claim',selected=selected)
    (ROOT/f'{split}_evaluation.json').write_text(json.dumps(out,indent=2));return out

def main():
    mode=sys.argv[1] if len(sys.argv)>1 else 'val'
    if mode=='val':
        out=run('val',750016,16,['none','oracle','p90_free','myopic','dp','dp_free'])
        selected=max(['dp','dp_free'],key=lambda n:out['summary'][n]['score_mean'])
        lock=dict(selected=selected,rule='higher frozen independent validation mean score of dp vs same-DP free-only; no parameter sweep',
            model_sha256=hashlib.sha256((ROOT/'report_model.npz').read_bytes()).hexdigest(),dp_sha256=hashlib.sha256((ROOT/'report_dp.npz').read_bytes()).hexdigest(),
            test_seed_first=760000,test_seed_last=760031,test_unopened=True)
        (ROOT/'selection_lock.json').write_text(json.dumps(lock,indent=2));print(json.dumps(lock),flush=True)
    elif mode=='test':
        lock=json.loads((ROOT/'selection_lock.json').read_text());assert lock['test_unopened']
        for name in ['model','dp']:assert hashlib.sha256((ROOT/f'report_{name}.npz').read_bytes()).hexdigest()==lock[f'{name}_sha256']
        offset=lock['test_seed_first'];count=lock['test_seed_last']-offset+1
        out=run(lock.get('test_output_prefix','test'),offset,count,['none','oracle','p90_free',lock['selected']],selected=lock['selected'])
        lock['test_unopened']=False;lock['test_once_complete']=True;(ROOT/'selection_lock.json').write_text(json.dumps(lock,indent=2));print(json.dumps(out['summary']),flush=True)
    elif mode=='val_v2':
        out=run('val_v2',750016,16,['none','oracle','p90_free','dp_free'],selected='dp_free')
        print(json.dumps(out['summary']),flush=True)
    else:raise ValueError(mode)
if __name__=='__main__':main()
