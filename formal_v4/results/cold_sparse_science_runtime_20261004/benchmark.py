"""Same-input exact kernel benchmarks on L1/L2 public geometry.
Reconstructed scalar ledgers from historic output are workload fixtures only,
not exact online belief replay; no hidden forecast or world supplied to actor.
"""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import csv, json, math, sys, time, cProfile, pstats, io
import numpy as np
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
sys.path.insert(0,str(OUT/'package'))
from research import spatial_candidates as spatial, cpu_phase_candidates as phase
from debias_planner import DebiasedSpatialPlanner
import sparse_exact
base_evaluate=spatial.SpatialPlanner._evaluate
base_coarse=phase.coarse_numpy_local
sparse_exact.install()
fast_evaluate=spatial.SpatialPlanner._evaluate
fast_coarse=phase.coarse_numpy_local
config=json.loads((OUT/'package/policy_config.json').read_text())

def initial(card):
 p=ROOT/f'formal_v4/upstream/gosim-observer-examples/local-cards/{card}'
 cfg=json.loads((p/'config/v4_scenario.json').read_text()); fiber=json.loads((p/'config/v4_fiber_config.json').read_text()); score=json.loads((p/'config/v4_score_config.json').read_text())
 targets=list(csv.reader((p/'public/targets.csv').open()));nights=list(csv.DictReader((p/'public/v4_night_calendar.csv').open()))
 side=math.isqrt(fiber['field']['n_fibers']);glass=math.sqrt(fiber['field']['fiber_area_deg2']);pitch=glass+fiber['field']['gap_deg']
 return {'site':{**cfg['site'],'minimum_altitude_deg':cfg['minimum_altitude_deg']},'survey':{'start_utc':nights[0]['observing_start_utc'],'end_utc':nights[-1]['observing_end_utc'],'slot_seconds':900,'nights':nights},'instrument':{**fiber['field'],'grid_side':side,'glass_side_deg':round(glass,6),'pitch_deg':round(pitch,6),'fov_side_deg':round(side*pitch,6),'exposure':fiber['exposure']},'scoring':score,'targets':{'columns':targets[0],'rows':targets[1:]},'limits':{'global_wallclock_seconds':900}}

def compare_candidate(a,b):
 if a is None or b is None:return a is b
 return a[:4]==b[:4] and np.array_equal(a[4],b[4]) and np.array_equal(a[5],b[5])
rows=[]; fine_total=0; coarse_total=0
for card in ('L1','L2'):
 init=initial(card);p=phase.CPUPhaseSpatialPlanner(init);d=DebiasedSpatialPlanner(init)
 run=ROOT/f'formal_v4/results/request_geometry_integration_20261004/seasons/control/{card}'
 decisions=[r for r in csv.DictReader((run/'decisions.csv').open()) if r['action']=='observe']
 observations=list(csv.DictReader((run/'observations.csv').open()))
 for fraction in (0,.2,.4,.6,.8,.98):
  record=decisions[round(fraction*(len(decisions)-1))];scores=np.zeros(p.n);factors=np.zeros(p.n)
  for o in observations:
   if int(o['observe_index'])>=int(record['observe_index']):break
   i=p.index[o['target_id']];scores[i]=max(scores[i],float(o['score']));factors[i]=max(factors[i],float(o['factor']))
  env={**config,'quality_scale':.55,'program_band_quality_scale':.55/.95,'use_bulletin_directional_prior':False,'target_quality_scale':np.ones(p.n)}
  snapshot={'now_utc':record['start_utc'],'wallclock':{'remaining_seconds':900}}
  for name,planner in [('strong',p),('debias',d)]:
   calls=[];groups=[]
   def record_fine(self,center,pool,*frame):
    a=base_evaluate(self,center,pool,*frame);calls.append((center,pool.copy(),frame,a));return a
   def record_coarse(*args,**kwargs):
    a=base_coarse(*args,**kwargs);groups.append((args,kwargs,a));return a
   spatial.SpatialPlanner._evaluate=record_fine;phase.coarse_numpy_local=record_coarse
   prof=cProfile.Profile();prof.enable();started=time.perf_counter();a=planner.choose(snapshot,scores,factors,env,[]);old_seconds=time.perf_counter()-started;prof.disable()
   old_stats=dict(planner.stats)
   spatial.SpatialPlanner._evaluate=fast_evaluate;phase.coarse_numpy_local=fast_coarse
   started=time.perf_counter();b=planner.choose(snapshot,scores,factors,env,[]);fast_seconds=time.perf_counter()-started
   assert a==b,(card,fraction,name,a,b)
   fine_start=time.perf_counter()
   for center,pool,frame,candidate in calls:
    v=fast_evaluate(planner,center,pool,*frame);assert compare_candidate(candidate,v),(card,fraction,name,'fine',candidate,v)
   fine_seconds=time.perf_counter()-fine_start;fine_total+=len(calls)
   coarse_start=time.perf_counter()
   for args,kwargs,candidate in groups:
    v=fast_coarse(*args,**kwargs);assert np.array_equal(candidate,v),(card,fraction,name,'coarse',np.max(np.abs(candidate-v)))
   coarse_seconds=time.perf_counter()-coarse_start;coarse_total+=sum(len(g[2]) for g in groups)
   fair={"original":[],"sparse":[]}
   for repeat in range(3):
    for mode in (('original','sparse') if repeat%2==0 else ('sparse','original')):
     spatial.SpatialPlanner._evaluate=base_evaluate if mode=='original' else fast_evaluate
     phase.coarse_numpy_local=base_coarse if mode=='original' else fast_coarse
     start=time.perf_counter();action=planner.choose(snapshot,scores,factors,env,[]);fair[mode].append(time.perf_counter()-start)
     assert action==a
   spatial.SpatialPlanner._evaluate=fast_evaluate;phase.coarse_numpy_local=fast_coarse
   buf=io.StringIO();pstats.Stats(prof,stream=buf).sort_stats('cumulative').print_stats(18)
   (OUT/f'profile_{card}_{fraction}_{name}.txt').write_text(buf.getvalue())
   row={'card':card,'fraction':fraction,'name':name,'baseline_seconds_profiled':old_seconds,'fast_seconds':fast_seconds,'action_equal':a==b,'fine_candidates':len(calls),'fine_equal':True,'fine_fast_seconds':fine_seconds,'coarse_candidates':sum(len(g[2]) for g in groups),'coarse_bitwise_equal':True,'coarse_fast_seconds':coarse_seconds,'fair_seconds':fair,'fair_original_median':float(np.median(fair['original'])),'fair_sparse_median':float(np.median(fair['sparse'])),'base_stats':old_stats,'fast_stats':dict(planner.stats)}
   rows.append(row);print(json.dumps({k:v for k,v in row.items() if k not in ('base_stats','fast_stats')}),flush=True)
result={'scope':__doc__,'rows':rows,'fine_candidates':fine_total,'coarse_candidates':coarse_total,'all_actions_equal':True,'all_fine_values_and_actions_exact':True,'all_coarse_values_bitwise_equal':True,'numpy':np.__version__}
(OUT/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n')
