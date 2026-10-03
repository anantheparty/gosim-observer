"""Streaming v2 executable-native participant; v1 archive is immutable."""
import json,os,sys,traceback
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import policy
from research.cpu_phase_candidates import CPUPhaseSpatialPlanner
from research.global_field_planner_v2 import GlobalFieldPlannerV2

MODE=os.environ.get('GLOBAL_FIELD_MODE','search')
class Control(CPUPhaseSpatialPlanner):
    def choose(self,s,scores,factors,env=None,requests=None):
        e=dict(env or {});e['cpu_phase_fixed_workload']=True;e['anchor_count']=24
        return super().choose(s,scores,factors,e,requests)
policy.SpatialPlanner=Control if MODE=='control' else GlobalFieldPlannerV2

def summary(p):
    result=dict(mode=MODE,version=2,nodes=256,policy=p.summary(),phase=p.planner.cpu_phase_summary)
    if MODE!='control':result['global']=p.planner.global_summary
    return result

def main():
    p=None;calls=0
    for line in sys.stdin:
        if not line.strip():continue
        m=json.loads(line);kind=m.get('message_type')
        if kind=='initialize':
            p=policy.Policy(m['payload'])
            if p.remote is not None:raise RuntimeError('unexpected remote dependency')
        elif kind=='decision_request':
            calls+=1
            try:action=p.decide(m['payload'])
            except Exception:
                traceback.print_exc(file=sys.stderr);action=dict(action='wait',duration_seconds=900)
            if calls%100==0:
                print(json.dumps(dict(event='progress',calls=calls,now=m['payload']['now_utc'],observe=m['payload']['observe_action_index'],
                                     **summary(p)),separators=(',',':')),file=sys.stderr,flush=True)
            print(json.dumps(dict(protocol_version='participant-agent-protocol-v4',message_type='decision_response',decision_sequence=m['decision_sequence'],
                                 **action),separators=(',',':'),allow_nan=False),flush=True)
        elif kind=='finish':
            if p:print(json.dumps(summary(p),separators=(',',':')),file=sys.stderr,flush=True)
            break
if __name__=='__main__':main()
