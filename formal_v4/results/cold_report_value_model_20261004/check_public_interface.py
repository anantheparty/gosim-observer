"""Public first entry parity and zero-time true/false causal interface."""
from pathlib import Path
import json,sys,copy,subprocess,os
ROOT=Path(__file__).resolve().parent;WORK=ROOT.parents[2]
sys.path.insert(0,str(ROOT/'candidate_package'))
from research import agent_request_exact_cache as exact_entry
from report_policy import make_policy_class
from research.geometry import parse_utc
initial=json.loads((WORK/'formal_v4/results/policy_iteration_20261004/L1_initialize_public.json').read_text())
real=exact_entry.ExactCachedRequestPolicy(initial)
class Fixture:
    def __init__(self,initial):
        self.initial=initial;self.planner=real.planner;self.slot_seconds=900;self.pending=None
        self.C=.234;self.E=.432;self.belief_clock={'anchor':'preserve'};self.low_efficiency=[1];self.efficiency_witnesses=[2]
        self.ledger=[{'valid':True}];self.false_since_correct=0;self.correct_reports=0;self.report_count=0;self.last_report=None;self.calls=0
    def _night(self,now):return next((i for i,(a,b) in enumerate(self.planner.nights) if a<=now<b),-1)
    def decide(self,s):
        self.calls+=1
        if (s.get('last_result') or {}).get('action')=='report':
            assert self.pending['action']=={'action':'report'}
            if s['last_result']['correct']:self.E=.95;self.correct_reports+=1;self.false_since_correct=0
            else:self.C=99
        action={'action':'observe','pointing':{'alt_deg':70.,'az_deg':90.},'duration_seconds':60,'program':'DARK','assignments':{'0':'V4T000001'}}
        self.pending={'action':copy.deepcopy(action),'start':parse_utc(s['now_utc']),'prior_C':self.C,'prior_E':self.E,'prediction':{},'notices':[]}
        return action
    def summary(self):return {'calls':self.calls}
def make():
    a=make_policy_class(Fixture)(initial);g=a.persistent_guard
    # Force decision scalar only; verify intervention semantics independently
    # of the statistical classifier's confidence on an artificial fixture.
    g.feature=lambda s:([0]*1382,.5,(0,0));g.model.posterior=lambda x:.8;g.dp.delta=lambda *args:2.
    s={'now_utc':initial['survey']['start_utc'],'observe_action_index':0,'new_messages':[],'last_result':None,'wallclock':{'remaining_seconds':900}}
    return a,s
a,s=make();assert a.decide(s)=={'action':'report'};fields=['C','E','belief_clock','low_efficiency','efficiency_witnesses','ledger','last_report']
before={k:copy.deepcopy(getattr(a,k)) for k in fields};pending=copy.deepcopy(a.persistent_guard.saved_pending)
ack={**s,'last_result':{'action':'report','correct':False,'repaired':False,'score_delta':0},'new_messages':[{'record_type':'report_result'}]}
out=a.decide(ack);assert out==pending['action'] and a.pending==pending and a.calls==1
assert all(getattr(a,k)==v for k,v in before.items()) and a.false_since_correct==1 and a.persistent_guard.false_count==1
a,s=make();a.decide(s);ack={**s,'last_result':{'action':'report','correct':True,'repaired':True,'score_delta':100},'new_messages':[{'record_type':'report_result'}]}
a.decide(ack);assert a.calls==2 and a.E==.95 and a.persistent_guard.correct==1 and a.correct_reports==1
a,s=make();a.persistent_guard.false_count=1;assert a.decide(s)=={'action':'report'}
a,s=make();a.persistent_guard.false_count=2;assert a.decide(s)['action']=='observe'
firstentry={};entry=ROOT/'firstentry';entry.mkdir(exist_ok=True)
for card in ['L1','L2']:
    source=WORK/f'formal_v4/results/request_terminal_adaptation_20261004/public_entry/{card}/public_input.jsonl'
    records={}
    for name,args,enabled in [('original',['-m','research.agent_request_exact_cache'],None),('disabled',['report_entry.py'],'0'),('dp',['report_entry.py'],'1'),('p90',['report_entry.py','--posterior-p90-control'],'1')]:
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':'0','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
        if enabled is not None:env['REQUEST_REPORT_VALUE_ENABLE']=enabled
        p=subprocess.run([sys.executable,'-u',*args],cwd=ROOT/'candidate_package',input=source.read_text(),text=True,capture_output=True,env=env,timeout=60)
        assert p.returncode==0 and 'Traceback' not in p.stderr,(name,p.stderr)
        (entry/f'{card}_{name}.stdout.jsonl').write_text(p.stdout);(entry/f'{card}_{name}.stderr.jsonl').write_text(p.stderr)
        records[name]=[json.loads(s) for s in p.stdout.splitlines()]
    assert all(records[name]==records['original'] for name in records)
    firstentry[card]=dict(responses=len(records['original']),equal_original_disabled_dp_p90=True,source=str(source),historical_clock_claim=False)
result=dict(passed=True,false_exact_action_and_pending=True,false_C_E_clock_ledger_preserved=True,true_normal_replan=True,
    quota1_usable_quota0_declined=True,firstentry=firstentry,public_only=True,score_claim=False)
(ROOT/'public_interface_checks.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
