"""Independent serialized-schedule check, without matching/oracle imports."""
import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
def stamp(s):return datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
def run(output):
    receipt=json.loads((HERE/'INPUT_RECEIPT.json').read_text())
    inputs={k:REPO/v['path'] for k,v in receipt['inputs'].items()}
    with np.load(inputs['graph'],allow_pickle=False) as z:a={k:z[k] for k in z.files}
    with inputs['catalogue'].open() as h:rows=list(csv.DictReader(h))
    weight=np.asarray([float(r['science_weight']) for r in rows]);cfg=json.loads(inputs['scoring'].read_text())['program']
    mult=np.asarray([cfg['multipliers'][p] for p in ('DARK','BRIGHT','BACKUP')]);mismatch=cfg['mismatch_multiplier']
    pool=json.loads((output/'COMMON_PATH_POOL.json').read_text());pool_valid=0
    for path in pool:
        assert all(a['starts'][v]>=a['ends'][u]-1e-7 for u,v in zip(path,path[1:]));pool_valid+=1
    now=stamp(json.loads(inputs['snapshot'].read_text())['now_utc']);checks=[]
    with np.load(inputs['ledger'],allow_pickle=False) as z:original=z['best_scores']
    for name in ('B','priced0','priced1'):
        d=json.loads((output/f'BEST_{name}.json').read_text());saved=json.loads(inputs['first_'+name].read_text())
        b=np.asarray(d['first_ledger']);assert np.array_equal(b,saved['first_ledger']) and d['first_action']==saved['first_action']
        c=d['future'];path=c['path'];blocked=now+d['first_action']['duration_seconds']
        assert any([e for e in p if a['starts'][e]>=blocked-1e-7]==path for p in pool)
        assert [r['action'] for r in c['schedule']]==path
        ledger=b.copy();previous=blocked;seen=set();max_score_error=0.;assignments=0;empty=0
        for row in c['schedule']:
            e=row['action'];start=a['starts'][e];end=a['ends'][e]
            assert row['start']==start and row['end']==end and start>=previous-1e-7;previous=end
            f=int(a['af'][e]);s=int(a['field_start'][f]);di=int(a['ad'][e]);pr=int(a['ap'][e]);lo,hi=a['offset'][f:f+2]
            fibers=row['fibers'];targets=row['targets'];assert len(set(fibers))==len(fibers)
            empty+=not bool(targets)
            for i,fiber,score in zip(targets,fibers,row['scores']):
                assert i not in seen and a['eligible'][s,di,i];seen.add(i)
                hits=(a['target'][lo:hi]==i)&(a['fiber'][lo:hi]==fiber);assert int(hits.sum())==1
                expected=weight[i]*a['factor'][s,di,i]*(mult[pr] if a['band'][s,di,i]==pr else mismatch)
                max_score_error=max(max_score_error,abs(expected-score));ledger[i]=max(ledger[i],score);assignments+=1
        ledger_error=float(np.max(np.abs(ledger-np.asarray(c['ledger']))));gain=float((ledger-original).sum())
        assert max_score_error<1e-10 and ledger_error<1e-10 and abs(gain-d['joint'])<1e-8
        checks.append(dict(branch=name,joint=gain,exposures=len(path),assignments=assignments,empty_exposures=empty,
            score_error=max_score_error,ledger_error=ledger_error,nonoverlap=True,fibers=True,eligibility=True,
            target_winner_unique=True,full_path_in_common_pool=True,first_prefix_identical=True))
    audit=dict(status='passed',independent_of_matching_and_oracle=True,all_common_time_paths_verified=pool_valid,branches=checks)
    (output/'INDEPENDENT_SCHEDULE_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n');return audit

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();print(json.dumps(run(a.run_dir)))
