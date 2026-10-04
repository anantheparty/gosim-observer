"""Freeze public geometry plus scalar historical output ledger workload fixtures."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
import csv,json,math,sys,pickle
from pathlib import Path
import numpy as np
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(OUT/'strong_package'))
from research.spatial_candidates import SpatialPlanner
config=json.loads((OUT/'strong_package/policy_config.json').read_text())
initials={};fixtures=[]
for card in ('L1','L2'):
 p=ROOT/f'formal_v4/upstream/gosim-observer-examples/local-cards/{card}'
 cfg=json.loads((p/'config/v4_scenario.json').read_text());fiber=json.loads((p/'config/v4_fiber_config.json').read_text());score=json.loads((p/'config/v4_score_config.json').read_text())
 targets=list(csv.reader((p/'public/targets.csv').open()));nights=list(csv.DictReader((p/'public/v4_night_calendar.csv').open()))
 side=math.isqrt(fiber['field']['n_fibers']);glass=math.sqrt(fiber['field']['fiber_area_deg2']);pitch=glass+fiber['field']['gap_deg']
 initial={'site':{**cfg['site'],'minimum_altitude_deg':cfg['minimum_altitude_deg']},'survey':{'start_utc':nights[0]['observing_start_utc'],'end_utc':nights[-1]['observing_end_utc'],'slot_seconds':900,'nights':nights},'instrument':{**fiber['field'],'grid_side':side,'glass_side_deg':round(glass,6),'pitch_deg':round(pitch,6),'fov_side_deg':round(side*pitch,6),'exposure':fiber['exposure']},'scoring':score,'targets':{'columns':targets[0],'rows':targets[1:]},'limits':{'global_wallclock_seconds':900}}
 initials[card]=initial;planner=SpatialPlanner(initial)
 run=ROOT/f'formal_v4/results/request_geometry_integration_20261004/seasons/control/{card}'
 decisions=[r for r in csv.DictReader((run/'decisions.csv').open()) if r['action']=='observe'];observations=list(csv.DictReader((run/'observations.csv').open()))
 for fraction in (0,.2,.4,.6,.8,.98):
  record=decisions[round(fraction*(len(decisions)-1))];scores=np.zeros(planner.n);factors=np.zeros(planner.n)
  for o in observations:
   if int(o['observe_index'])>=int(record['observe_index']):break
   i=planner.index[o['target_id']];scores[i]=max(scores[i],float(o['score']));factors[i]=max(factors[i],float(o['factor']))
  env={**config,'quality_scale':.55,'program_band_quality_scale':.55/.95,'use_bulletin_directional_prior':False,'target_quality_scale':np.ones(planner.n)}
  snapshot={'now_utc':record['start_utc'],'wallclock':{'remaining_seconds':900}}
  fixtures.append((card,fraction,snapshot,scores,factors,env))
with (OUT/'workload_fixtures.pkl').open('wb') as f:pickle.dump((initials,fixtures),f,protocol=4)
