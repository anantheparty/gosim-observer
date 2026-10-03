"""Prepare an isolated v2 participant and public-state cost/geometry checks."""
from pathlib import Path
import argparse,hashlib,json,shutil,sys,time
import numpy as np

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'results/global_field_20261004/v2'
SOURCE=BASE/'results/global_field_20261004/v1_archive/source_snapshot/participant'
OFFICIAL=BASE/'upstream/gosim-observer-examples'
FROZEN_FILES=('policy.py','policy_config.json','research/geometry.py','research/feedback_model.py',
    'research/spatial_candidates.py','research/belief_clock.py','research/efficiency_bounds.py','research/remote_budget.py',
    'research/pointing_calibration.py','research/cpu_phase_candidates.py','research/global_field_planner.py')

def prepare():
    project=OUT/'participant';project.mkdir(parents=True,exist_ok=True)
    for name in FROZEN_FILES:
        dst=project/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(SOURCE/name,dst)
    for name in ['global_field_planner_v2.py','global_field_agent_v2.py']:
        shutil.copyfile(BASE/'research'/name,project/'research'/name)
    for p in OUT.glob('global_field_search_v2_*'):
        if p.suffix in ['.dylib','.so']:shutil.copyfile(p,project/'research'/p.name)
    return project

def micro(card):
    project=prepare();sys.path.insert(0,str(project));sys.path.insert(1,str(OFFICIAL))
    from runner.challenge.v4_workflow import V4Workflow
    from runner.challenge.v4_fiber_map import FiberGrid
    from research.global_field_planner_v2 import GlobalFieldPlannerV2
    from research.spatial_candidates import parse_utc
    initial=V4Workflow(OFFICIAL/'local-cards'/card).initialize_payload(900);p=GlobalFieldPlannerV2(initial)
    snap=dict(now_utc=initial['survey']['nights'][0]['observing_start_utc'],observe_action_index=0,new_messages=[],active_requests=[])
    record={}
    def hook(s,frame,useful,upper,data,cfg,out,stats,baseline):
        record.update(stats=p.stats,baseline_action=baseline,native_result=out.tolist(),native_stats=stats.tolist())
        np.savez_compressed(OUT/f'micro_{card}.npz',data=data,cfg=cfg,out=out,stats=stats)
    p.export_hook=hook
    started=time.perf_counter();action=p.choose(snap,{}, {},dict(quality_scale=.55,program_band_quality_scale=.55/.95),[])
    elapsed=time.perf_counter()-started
    grid=FiberGrid(.4,0.,16);lookup={r[0]:r for r in initial['targets']['rows']}
    for f,t in action['assignments'].items():
        r=lookup[t];found=grid.classify_target(r[1],r[2],parse_utc(snap['now_utc']),action['pointing']['alt_deg'],action['pointing']['az_deg'],p.lat,p.lon)
        assert found.region=='glass' and found.fiber_id==int(f),(t,f,found)
    record.update(card=card,seconds=elapsed,action=action,official_geometry_valid=True,summary=p.global_summary)
    (OUT/f'micro_{card}.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--card',choices=['L1','L2','L3','L4'],default='L1')
    a=ap.parse_args();OUT.mkdir(parents=True,exist_ok=True);micro(a.card)
