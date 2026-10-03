"""Public request-window gate for time-supported terrain integration."""
import argparse
import json
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
import numpy as np

parser=argparse.ArgumentParser()
parser.add_argument('--initialize',required=True)
parser.add_argument('--history',required=True)
parser.add_argument('--runner',required=True)
parser.add_argument('--out',required=True)
args=parser.parse_args()
sys.path.insert(0,str(Path(args.initialize).resolve().parent))
from research.request_deadline_cpu import RequestCPUDeadlinePlanner
from research.request_mask_dp import solve_request_columns
from research.terrain_version_space import TerrainVersionSpace
from research.spatial_candidates import parse_utc
sys.path.insert(0,args.runner)
from challenge.v4_fiber_map import FiberGrid

payload=json.loads(Path(args.initialize).read_text())
history=Path(args.history)
request=dict(json.loads((history/'score_report.json').read_text())['observation_requests'][0])
now=parse_utc(request['issued_at_utc'])
records=[json.loads(line) for line in (history/'messages.jsonl').read_text().splitlines()]
public=[r for r in records if r.get('issued_at_utc') and parse_utc(r['issued_at_utc'])<=now]
bulletin=next(r for r in reversed(public) if r['record_type']=='bulletin')
forecast=next(r for r in reversed(public) if r['record_type']=='forecast')
directions=[n['direction'] for r in public for n in r.get('notices',[]) if n.get('event_kind')=='terrain_obstruction']
p=RequestCPUDeadlinePlanner(payload)
p.terrain_model=TerrainVersionSpace.reference_prior(directions,p.lat,p.lon)
snapshot={'now_utc':now.isoformat(),'latest_bulletin':bulletin,'latest_forecast':forecast}
env={'quality_scale':.55,'program_band_quality_scale':.55/.95,'duration_safety':1.1,
     'request_dp_future_field_mode':'published','request_dp_price_anchors':2,'request_dp_step_seconds':900}
begin=time.perf_counter()
info=p._build_pool(request,now,np.zeros(p.n),np.zeros(p.n),env,snapshot)
plan=solve_request_columns(info['columns'],target_count=len(info['idx']),quorum=request['minimum_completed'],
                          now=now.timestamp(),deadline=info['deadline'].timestamp())
assert plan.feasible,(len(info['columns']),plan)
first=info['columns'][plan.chosen_indices[0]]
moment=datetime.fromtimestamp(first.start,timezone.utc)
p._active_future_field=p._future_field(snapshot,env)
action=p._request_action(first.tag,moment,info,np.zeros(p.n),np.zeros(p.n),env,0)
assert action is not None
grid=FiberGrid(p.glass**2,p.pitch-p.glass,p.nfib)
for fid,tid in action['assignments'].items():
    i=p.index[tid]
    hit=grid.classify_target(float(p.ra[i]),float(p.dec[i]),moment,action['pointing']['alt_deg'],action['pointing']['az_deg'],p.lat,p.lon,0,0)
    assert hit.region=='glass' and hit.fiber_id==int(fid)
result={'request_id':request['request_id'],'columns':len(info['columns']),'quota':request['minimum_completed'],
        'final_mask_bits':plan.final_mask.bit_count(),'minimum_conditional_regret':plan.min_cost,
        'build_seconds':info['build_seconds'],'total_seconds':time.perf_counter()-begin,
        'first_action':action,'geometry_passed':True,'future_field':info['future_field']}
Path(args.out).write_text(json.dumps(result,indent=2))
print(json.dumps(result),flush=True)
