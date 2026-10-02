"""Independent three-call startup timing using public initialization only."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--agent-root',required=True)
parser.add_argument('--initialize',required=True)
parser.add_argument('--empty-cache-dir')
args=parser.parse_args()
if args.empty_cache_dir:
    cache=Path(args.empty_cache_dir)
    if cache.exists():raise ValueError('empty JIT-cache probe requires a new directory')
    cache.mkdir(parents=True)
    os.environ['NUMBA_CACHE_DIR']=str(cache)
begin=time.perf_counter()
sys.path.insert(0,args.agent_root)
from research.gpu_phase_candidates import PhaseGPUSpatialPlanner
imported=time.perf_counter()
payload=json.loads(Path(args.initialize).read_text())
planner=PhaseGPUSpatialPlanner(payload)
initialized=time.perf_counter()
env={'quality_scale':.55,'program_band_quality_scale':.55/.95,
     'gpu_anchor_count':1024,'gpu_max_candidates':32768,'gpu_refine_count':64,
     'gpu_fixed_workload':True,'gpu_exact_candidate_count':256,'gpu_refinement_steps':32,
     'gpu_emergency_seconds':3.,'gpu_phase_top_count':16,
     'gpu_phase_local_target_count':24,'gpu_phase_exact_count':64,
     'gpu_phase_emergency_seconds':3.}
calls=[]
for _ in range(3):
    start=time.perf_counter()
    action=planner.choose({'now_utc':payload['survey']['nights'][0]['observing_start_utc']},{},{},env,[])
    calls.append({'seconds':time.perf_counter()-start,'duration_seconds':action['duration_seconds'],
                  'assignments':len(action['assignments']),'stats':planner.stats})
print(json.dumps({'cache_mode':'new empty cache directory' if args.empty_cache_dir else 'existing module cache',
                  'import_seconds':imported-begin,'initialize_seconds':initialized-imported,
                  'first_initialize_choose_seconds':calls[0]['seconds']+initialized-imported,
                  'process_to_first_action_seconds':initialized-begin+calls[0]['seconds'],
                  'calls':calls},indent=2))
