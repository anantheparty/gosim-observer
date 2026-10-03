"""Small method-contract check; stub baseline, one already cached public request.

No full season, truth input, shared actor edits or network calls.
"""
import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
import csv
import json
import math
import sys
from datetime import timedelta
from pathlib import Path
import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
PACKAGE = ROOT / 'formal_v4/results/request_geometry_integration_20261004/geometry_package'
sys.path.insert(0, str(PACKAGE))
from research.request_geometry_planner import GeometryCachedRequestPlanner
from research.request_mask_dp import RequestColumn
from research.spatial_candidates import parse_utc

pub = ROOT / 'formal_v4/practice_cards/alpha/alpha'
cfg = json.loads((pub/'config/v4_scenario.json').read_text())
fiber = json.loads((pub/'config/v4_fiber_config.json').read_text())
nights = list(csv.DictReader((pub/'public/v4_night_calendar.csv').open()))
targets = list(csv.reader((pub/'public/targets.csv').open()))
side = math.isqrt(fiber['field']['n_fibers']); glass = math.sqrt(fiber['field']['fiber_area_deg2'])
initial = {'site':{**cfg['site'],'minimum_altitude_deg':cfg['minimum_altitude_deg']},
    'survey':{'start_utc':nights[0]['observing_start_utc'],'end_utc':nights[-1]['observing_end_utc'],'slot_seconds':900,'nights':nights},
    'instrument':{**fiber['field'],'grid_side':side,'glass_side_deg':round(glass,6),'pitch_deg':round(glass,6),
        'fov_side_deg':round(side*glass,6),'exposure':fiber['exposure']},
    'scoring':json.loads((pub/'config/v4_score_config.json').read_text()),'targets':{'columns':targets[0],'rows':targets[1:]}}
planner = GeometryCachedRequestPlanner(initial)
now = parse_utc(nights[0]['observing_start_utc']); deadline = now + timedelta(seconds=900)
request = {'request_id':'CONTRACT','target_ids':[planner.ids[0]],'minimum_completed':1,
    'completed_target_ids':[],'completion_factor_threshold':.5,'completion_reward':100,'deadline_utc':deadline.isoformat()}
planner._request_pools['CONTRACT'] = {'columns':[RequestColumn(now.timestamp()+120,now.timestamp()+240,1,0,None)],
    'idx':np.array([0]),'threshold':.5,'deadline':deadline,'scale':np.array([.55]),'band_scale':.55/.95}
calls = []
prediction = {planner.ids[0]:{'factor':.7,'index':0}}
def stub(snapshot,scores,factors,env,requests):
    calls.append({'tmax':planner.geometry_engine.tmax,'same_scores':scores is ledger,'same_factors':factors is factor,
        'same_requests':requests is active,'same_target_scale':env['target_quality_scale'] is target_scale})
    planner.geometry_engine.last_prediction = prediction
    planner.geometry_engine.stats = {'planning_seconds':.01,'contract_marker':True}
    return {'action':'observe','duration_seconds':min(900,planner.geometry_engine.tmax),'program':'DARK',
        'pointing':{'alt_deg':60.,'az_deg':90.},'assignments':{'0':planner.ids[0]}}
planner.geometry_engine.choose = stub
ledger,factor,target_scale = np.zeros(planner.n),np.zeros(planner.n),np.ones(planner.n)
active = [request]
action = planner.choose({'now_utc':now.isoformat(),'wallclock':{'remaining_seconds':900}},ledger,factor,
    {'quality_scale':.55,'program_band_quality_scale':.55/.95,'target_quality_scale':target_scale,'request_dp_mode':'deadline'},active)
assert [c['tmax'] for c in calls] == [3600,120]
assert all(all(c[k] for k in ['same_scores','same_factors','same_requests','same_target_scale']) for c in calls)
assert action['duration_seconds'] == 120
assert planner.tmax == planner.geometry_engine.tmax == 3600
assert planner.last_prediction == prediction and planner.last_prediction is not prediction
assert planner._request_counts['clipped_baselines'] == 1
assert planner.distributed_counts['forced_cpu_crops'] == 1
assert planner.distributed_counts['cpu_baselines'] == 2
result = {'passed':True,'calls':calls,'output_duration_seconds':action['duration_seconds'],
    'parent_tmax_after':planner.tmax,'child_tmax_after':planner.geometry_engine.tmax,
    'request_counts':planner._request_counts,'distributed_counts':planner.distributed_counts,
    'scope':'stub baseline plus one cached request; verifies actual boundary re-search, input identity and predictions; no score claim'}
(OUT/'root_composition_contract_check.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
