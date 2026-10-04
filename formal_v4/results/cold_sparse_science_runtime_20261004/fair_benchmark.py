"""Same frozen L1/L2 inputs, alternating original and fused exact arithmetic.
Scalar historical-output ledger workloads do not reconstruct online beliefs.
"""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
import json,pickle,sys,time,resource,platform
from pathlib import Path
import numpy as np
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(OUT/'debias_package'))
from research import spatial_candidates as spatial,cpu_phase_candidates as phase
from debias_planner import DebiasedSpatialPlanner
from sparse_exact import install
old_fine=spatial.SpatialPlanner._evaluate;old_coarse=phase.coarse_numpy_local
install();new_fine=spatial.SpatialPlanner._evaluate;new_coarse=phase.coarse_numpy_local
initials,fixtures=pickle.load((OUT/'workload_fixtures.pkl').open('rb'))
rows=[]
for card,fraction,snapshot,scores,factors,env in fixtures:
 for name,cls in [('strong',phase.CPUPhaseSpatialPlanner),('debias',DebiasedSpatialPlanner)]:
  choose_env=dict(env,planning_budget_seconds=1e9,anchor_count=24) if name=='debias' else env
  p=cls(initials[card]);reference=None;samples={'original':[],'sparse':[]}
  for repeat in range(4):
   for mode in (['original','sparse'] if repeat%2==0 else ['sparse','original']):
    spatial.SpatialPlanner._evaluate=old_fine if mode=='original' else new_fine;phase.coarse_numpy_local=old_coarse if mode=='original' else new_coarse
    started=time.perf_counter();a=p.choose(snapshot,scores,factors,choose_env,[]);elapsed=time.perf_counter()-started
    if reference is None:reference=a
    assert a==reference,(card,fraction,name,mode)
    if repeat>0:samples[mode].append(elapsed)
  row={'card':card,'fraction':fraction,'name':name,'action_equal':True,'samples':samples,'original_seconds':float(np.median(samples['original'])),'sparse_seconds':float(np.median(samples['sparse']))}
  row['speedup']=row['original_seconds']/row['sparse_seconds'];rows.append(row);print(json.dumps(row),flush=True)
summary={}
for name in ('strong','debias'):
 r=[x for x in rows if x['name']==name];a=float(np.mean([x['original_seconds'] for x in r]));b=float(np.mean([x['sparse_seconds'] for x in r]));summary[name]={'n':len(r),'original_mean_seconds':a,'sparse_mean_seconds':b,'speedup':a/b,'saved_fraction':1-b/a}
result={'scope':__doc__,'rows':rows,'summary':summary,'runtime':{'python':sys.version,'numpy':np.__version__,'platform':platform.platform(),'maxrss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'threads':1},'all_actions_equal':True}
(OUT/('fair_benchmark_linux.json' if sys.platform=='linux' else 'fair_benchmark_mac.json')).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(summary))
