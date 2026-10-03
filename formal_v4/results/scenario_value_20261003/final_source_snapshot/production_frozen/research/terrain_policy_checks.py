"""Protocol pending/actual duration and shared future-field cross checks."""
import csv,json,sys
from pathlib import Path
from types import SimpleNamespace
from datetime import timedelta
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research.terrain_policy import install_terrain_policy,temporary_weather_scale
from research.request_future_field import PublishedFutureField
from research.required_opportunity_model import public_initial
from research.spatial_candidates import parse_utc


def checks():
    public=Path(__file__).resolve().parents[1]/'practice_cards/delta/delta'
    initial=public_initial(public)
    col={c:i for i,c in enumerate(initial['targets']['columns'])};rows=initial['targets']['rows']
    ids=[r[col['target_id']] for r in rows]
    planner=SimpleNamespace(init=initial,index=dict(zip(ids,range(len(ids)))),n=len(ids),
          lat=initial['site']['latitude_deg'],lon=initial['site']['longitude_deg'],
          ra=np.array([float(r[col['ra_deg']]) for r in rows]),dec=np.array([float(r[col['dec_deg']]) for r in rows]))
    class Base:
        def __init__(self,initial):
            self.planner=planner;self.config={};self.pending=None;self.terrain=set();self.notices=[];self.blocked_spots=[]
        def _ingest_result(self,snapshot):self.pending=None
        def _messages(self,snapshot):
            self.notices=snapshot['latest_bulletin']['notices']
            self.terrain.update(n['direction'] for n in self.notices if n['event_kind']=='terrain_obstruction')
        def summary(self):return {}
    old=Base._ingest_result
    Candidate=install_terrain_policy(Base);policy=Candidate(initial)
    assert Base._ingest_result is old
    now=parse_utc(initial['survey']['nights'][0]['observing_start_utc'])
    bulletin={'initial':True,'record_type':'bulletin','issued_at_utc':now.isoformat(),
            'notices':[{'event_kind':'terrain_obstruction','direction':d} for d in ['NE','E','NW']]+
                      [{'event_kind':'cloud','direction':'SE'}]}
    snapshot={'now_utc':now.isoformat(),'latest_bulletin':bulletin,'new_messages':[bulletin]}
    policy._messages(snapshot)
    assert policy.planner.terrain_model is policy.terrain_model
    field=PublishedFutureField(planner,snapshot,policy.terrain_model,weather_scenario=temporary_weather_scale,
                               empirical_blocks=policy.blocked_spots)
    assert np.allclose(field.raw_scale_at(now),policy._target_scale(now))
    # Actual duration is shorter than requested and arrives without duration field.
    starts=[];durations=[]
    original=policy.terrain_model.observe_positive
    def capture(ra,dec,start,duration,score):
        starts.append(start);durations.append(duration)
        return original(ra,dec,start,duration,score)
    policy.terrain_model.observe_positive=capture
    policy.pending={'start':now,'action':{'action':'observe','duration_seconds':3600}}
    response={'now_utc':(now+timedelta(seconds=60)).isoformat(),'last_result':{'action':'observe','observe_index':1,
               'hits':[{'target_id':ids[0],'score':.1},{'target_id':ids[1],'score':0}]}}
    policy._ingest_result(response)
    assert durations==[60.] and starts==[now] and policy.pending is None
    policy._ingest_result(response)
    assert len(durations)==1 and policy.terrain_feedback_exposures==1
    return {'schema':'terrain-policy-hook-checks-v1','stable_class_unmodified':True,
            'online_and_future_field_same_geometry_scale':True,'planner_shares_same_object':True,
            'pending_captured_before_clear':True,'actual_duration_seconds':durations[0],
            'repeated_feedback_idempotent':True,'zero_no_hard_update':True,
            'scope':'public delta catalog/calendar and synthetic protocol feedback only'}


if __name__=='__main__':
    result=checks();print(json.dumps(result,indent=2))
    Path(__file__).with_name('terrain_policy_checks_result.json').write_text(json.dumps(result,indent=2)+'\n')
