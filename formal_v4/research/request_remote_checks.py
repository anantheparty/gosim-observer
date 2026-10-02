"""Public stub/fallback/crop/ledger-budget gates for independent transport."""
import argparse
import json
import time
from datetime import timedelta
from pathlib import Path
import numpy as np

from .request_remote_planner import RequestRemotePlanner,DisabledRemoteFacade,PlannerBudgetFacade
from .request_mask_dp import RequestColumn
from .spatial_candidates import parse_utc

parser=argparse.ArgumentParser()
parser.add_argument('--initialize',required=True)
parser.add_argument('--out',required=True)
args=parser.parse_args()
payload=json.loads(Path(args.initialize).read_text())
snapshot={'now_utc':payload['survey']['nights'][0]['observing_start_utc'],
          'wallclock':{'remaining_seconds':900},'active_requests':[]}
env={'quality_scale':.55,'program_band_quality_scale':.55/.95,'duration_safety':1.1,
     'anchor_count':24,'cpu_phase_fixed_workload':True,'cpu_phase_top_count':4,
     'cpu_phase_local_target_count':50,'cpu_phase_boundary_target_count':24,'cpu_phase_exact_count':16,
     'request_dp_mode':'bypass','planning_budget_seconds':.22}


class StubBudget:
    def __init__(self):self.cpu=[];self.remote=[];self.allow_arguments=[]
    def allow(self,remaining,count):self.allow_arguments.append((remaining,count));return True
    def record_cpu(self,seconds):self.cpu.append(seconds)
    def record_remote(self,seconds):self.remote.append(seconds)
    def summary(self):return {'cpu_samples':len(self.cpu),'remote_samples':len(self.remote)}


class StubTransport:
    enabled=True
    def __init__(self,action,prediction):
        self.action=action;self.prediction=prediction;self.calls=0;self.seconds=0.
        self.rpc_calls=0;self.rpc_seconds=0.;self.fail=False;self.closed=False
    def choose(self,*args):
        self.calls+=1
        if self.fail:raise TimeoutError('public fixture failure')
        return {'action':self.action,'prediction':self.prediction,'stats':{'backend':'public-stub'}}
    def close(self):self.closed=True


p=RequestRemotePlanner(payload)
control=p.choose(snapshot,{},{},env,[])
assert control and control['action']=='observe'
transport=StubTransport(control,dict(p.last_prediction));budget=StubBudget()
p.attach_transport(transport,budget)
action=p.choose(snapshot,{},{},env,[])
assert action==control and p.last_prediction==transport.prediction
assert transport.calls==1 and budget.cpu==[] and len(budget.remote)==1
transport.fail=True
action=p.choose(snapshot,{},{},env,[])
assert action==control and len(budget.cpu)==1 and len(budget.remote)==2
assert p.distributed_counts['transport_failures']==1

# A reservation crossing the GPU baseline must use a cropped CPU baseline,
# while DP pool latency remains outside the empirical CPU p90 samples.
transport.fail=False
transport.action={**control,'duration_seconds':120}
now=parse_utc(snapshot['now_utc']);indices=np.arange(8)
request={'request_id':'PUBLIC_STUB_REQ','issued_at_utc':now.isoformat(),
         'deadline_utc':(now+timedelta(seconds=3600)).isoformat(),
         'target_ids':[p.ids[i] for i in indices],'completed_target_ids':[],
         'minimum_completed':6,'completion_reward':100.,'completion_factor_threshold':.5}
info={'columns':[RequestColumn(now.timestamp()+90,now.timestamp()+150,63,0.,{})],
      'idx':indices,'threshold':.5,'deadline':now+timedelta(seconds=3600),
      'scale':np.full(8,.55),'band_scale':.55/.95}
def pool(*args,**kwargs):time.sleep(.05);return info
p._build_pool=pool
started=time.perf_counter()
action=p.choose(snapshot,{},{},{**env,'request_dp_mode':'deadline'},[request])
elapsed=time.perf_counter()-started
assert action['action']=='observe' and action['duration_seconds']<=90
assert transport.calls==3 and len(budget.cpu)==2 and len(budget.remote)==3
assert p.tmax==p._distributed_normal_tmax and p.distributed_counts['forced_cpu_crops']==1
assert budget.cpu[-1]+.04<elapsed,(budget.cpu[-1],elapsed)
facade=DisabledRemoteFacade(transport)
assert not facade.enabled and facade.calls==transport.calls
facade.close();assert transport.closed
ledger_budget=PlannerBudgetFacade(budget);before=len(budget.cpu)
ledger_budget.record_cpu(10.);assert len(budget.cpu)==before

# Importing the independent entry binds the cached agent Policy correctly.
from . import agent_request_distributed as entry
import agent,policy
assert agent.Policy is policy.Policy is entry.DistributedRequestPolicy
candidate=policy.Policy(payload)
candidate.config['request_dp_mode']='bypass'
candidate.planner.attach_transport(transport,budget)
candidate.remote=DisabledRemoteFacade(transport)
candidate.remote_budget=PlannerBudgetFacade(budget)
transport.action=control;transport.closed=False
previous_calls=transport.calls;previous_cpu=len(budget.cpu)
response=candidate.decide(snapshot)
assert response==control and transport.calls==previous_calls+1
assert len(budget.cpu)==previous_cpu # original Policy record excludes full hook time
assert candidate.pending['prediction']==transport.prediction
candidate.summary();candidate.remote.close();assert transport.closed

result={'public_stub_passed':True,'fallback_passed':True,'reservation_crop_passed':True,
        'cpu_sample_excludes_dp_build':True,'single_remote_call_from_policy':True,
        'original_pending_prediction_preserved':True,'summary_close_facade_passed':True,
        'entry_policy_binding_passed':True,'crop_total_seconds':elapsed,
        'crop_cpu_baseline_seconds':budget.cpu[-1], 'counts':p.distributed_summary()}
Path(args.out).write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
