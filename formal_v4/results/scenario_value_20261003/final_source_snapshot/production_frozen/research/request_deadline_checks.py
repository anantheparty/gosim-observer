"""Public L1 history gate for subset geometry, full-window DP and legal actions."""
import argparse
import csv
import json
import sys
import time
from pathlib import Path
import numpy as np

parser=argparse.ArgumentParser()
parser.add_argument('initialize_json')
parser.add_argument('history_dir')
parser.add_argument('official_runner')
parser.add_argument('--out',default='request_deadline_check.json')
args=parser.parse_args()
sys.path.insert(0,str(Path(args.official_runner)))
from challenge.v4_fiber_map import FiberGrid
from research.request_deadline_planner import RequestDPPlanner
from research.request_mask_dp import solve_request_columns
from research.spatial_candidates import parse_utc,local_sidereal

payload=json.loads(Path(args.initialize_json).read_text())
p=RequestDPPlanner(payload)
history=Path(args.history_dir)
req=dict(json.loads((history/'score_report.json').read_text())['observation_requests'][0])
req['completed_target_ids']=[];req['completed_count']=0
now=parse_utc(req['issued_at_utc'])
decisions={r['observe_index']:r for r in csv.DictReader((history/'decisions.csv').open()) if r['action']=='observe'}
scores,factors={},{}
for observation in csv.DictReader((history/'observations.csv').open()):
    if observation['valid']=='true' and parse_utc(decisions[observation['observe_index']]['end_utc'])<=now:
        tid=observation['target_id'];scores[tid]=max(scores.get(tid,0),float(observation['score']));factors[tid]=max(factors.get(tid,0),float(observation['factor']))
env={'quality_scale':.55,'program_band_quality_scale':.55/.95,'duration_safety':1.1,
     'gpu_anchor_count':1024,'gpu_max_candidates':32768,'gpu_refine_count':64,'gpu_fixed_workload':True,
     'gpu_exact_candidate_count':256,'gpu_refinement_steps':32,'gpu_emergency_seconds':3.0,
     'request_dp_step_seconds':900,'request_dp_price_anchors':2}
errors=[]
idx=np.arange(0,p.n,max(1,p.n//100))
for date in (payload['survey']['nights'][0]['observing_start_utc'],req['issued_at_utc'],req['deadline_utc']):
    moment=parse_utc(date);lst=local_sidereal(moment,p.lon);alt,*_=p._altaz(lst)
    errors.append(float(np.max(np.abs(p._subset_public_quality(moment,idx)-p._public_quality(moment,lst,alt)[idx]))))
assert max(errors)<1e-12
start=time.perf_counter();info=p._build_pool(req,now,p._array(scores),p._array(factors),env)
build_seconds=time.perf_counter()-start
plan=solve_request_columns(info['columns'],target_count=len(info['idx']),quorum=req['minimum_completed'],
                          now=now.timestamp(),deadline=info['deadline'].timestamp())
assert plan.feasible and plan.final_mask.bit_count()>=req['minimum_completed']
first=info['columns'][plan.chosen_indices[0]]
moment=parse_utc(__import__('datetime').datetime.fromtimestamp(first.start,__import__('datetime').timezone.utc))
action=p._request_action(first.tag,moment,info,p._array(scores),p._array(factors),env,0)
assert action is not None
grid=FiberGrid(p.glass**2,p.pitch-p.glass,p.nfib)
for fid,tid in action['assignments'].items():
    i=p.index[tid]
    hit=grid.classify_target(float(p.ra[i]),float(p.dec[i]),moment,action['pointing']['alt_deg'],action['pointing']['az_deg'],p.lat,p.lon,0,0)
    assert hit.region=='glass' and hit.fiber_id==int(fid),hit
result={'request_id':req['request_id'],'issued_at_utc':req['issued_at_utc'],'deadline_utc':req['deadline_utc'],
        'public_quality_max_error':max(errors),'build_seconds':build_seconds,'columns':len(info['columns']),
        'dp_min_cost':plan.min_cost,'dp_final_mask':plan.final_mask,'dp_quota':req['minimum_completed'],
        'selected_columns':len(plan.chosen_indices),'first_start':first.start,'first_action':action,
        'planned_masks':[info['columns'][i].completion_mask for i in plan.chosen_indices],
        'planned_intervals':[(info['columns'][i].start,info['columns'][i].end) for i in plan.chosen_indices],
        'official_geometry_passed':True,'opportunity_model':'frozen same-duration scientific regret, no cumulative science credit'}
Path(args.out).write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
