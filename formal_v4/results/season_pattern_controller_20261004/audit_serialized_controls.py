"""Independent saved-array audit of final common physical controls; no solver."""
import json,csv,hashlib
from pathlib import Path
from datetime import datetime
import numpy as np
ROOT=Path(__file__).resolve().parent;WORK=ROOT.parents[2]
p=ROOT/'time_dp_reuse'/'L2_night08';saved=np.load(ROOT/'time_dp'/'L2_night08'/'SHARED_PUBLIC_GRAPH.npz');g={k:saved[k] for k in saved.files};b=np.load(p/'CURRENT_PUBLIC_LEDGER.npz')['best_scores']
card=WORK/'formal_v4/upstream/gosim-observer-examples/local-cards/L2';rows=list(csv.DictReader((card/'public/targets.csv').open()));ids={r['target_id']:i for i,r in enumerate(rows)}
w=np.asarray([float(r['science_weight']) for r in rows]);pc=json.loads((card/'config/v4_score_config.json').read_text())['program'];mult=np.array([pc['multipliers'][q] for q in ('DARK','BRIGHT','BACKUP')]);mismatch=float(pc['mismatch_multiplier'])
now=datetime.fromisoformat(json.loads((p/'CURRENT_PUBLIC_SNAPSHOT.json').read_text())['now_utc'].replace('Z','+00:00')).timestamp();result=[]
for name in ['B','priced0','priced1']:
 c=json.loads((p/f'COMMON_CONTROL_{name}.json').read_text());first=np.asarray(c['first_ledger']);ledger=first.copy();schedule=c['future']['schedule'];last_end=now+int(c['first_action']['duration_seconds']);maxerror=0.
 touched=set(ids[t] for t in c['first_action']['assignments'].values());assert np.all(first>=b-1e-12)
 assert all(abs(first[i]-b[i])<1e-12 for i in range(len(b)) if i not in touched)
 for row in schedule:
  e=row['action'];f=g['af'][e];s=g['field_start'][f];d=g['ad'][e];pr=g['ap'][e];target=np.asarray(row['targets'],dtype=int);fiber=np.asarray(row['fibers'],dtype=int)
  assert row['start']>=last_end-1e-7;assert row['end']>row['start'];last_end=row['end'];assert len(set(fiber))==len(fiber) and len(set(target))==len(target)
  sl=slice(g['offset'][f],g['offset'][f+1]);lookup=dict(zip(g['target'][sl].tolist(),g['fiber'][sl].tolist()))
  assert all(lookup[int(i)]==int(fi) for i,fi in zip(target,fiber));assert np.all(g['eligible'][s,d,target])
  assert abs(row['start']-g['starts'][e])<1e-7 and abs(row['end']-g['ends'][e])<1e-7
  score=w[target]*g['factor'][s,d,target]*np.where(g['band'][s,d,target]==pr,mult[pr],mismatch)
  maxerror=max(maxerror,float(np.max(np.abs(score-row['scores']))));ledger[target]=np.maximum(ledger[target],score)
 assert maxerror<1e-10;assert np.max(np.abs(ledger-c['future']['ledger']))<1e-9
 increment=float((ledger-first).sum());assert abs(increment-c['future']['increment'])<1e-9
 result.append(dict(branch=name,schedule_exposures=len(schedule),score_maxerror=maxerror,physical_ledger_increment=increment,passed=True))
out=dict(scope='serialized final shared-path finite public controls; no LP/oracle rerun or official weather claim',passed=True,branches=result)
(ROOT/'SERIALIZED_CONTROLS_AUDIT.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
