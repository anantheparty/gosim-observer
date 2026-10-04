from pathlib import Path
import json,sys,copy,subprocess,os,importlib.util
from datetime import timedelta
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.dont_write_bytecode=True;sys.path.insert(0,str(HERE/'candidate_v2_package'))
from research import agent_request_exact_cache as exact_entry
from adaptive_fault_guard import AdaptiveFaultGuard
from research.geometry import format_utc
initial=json.loads((ROOT/'formal_v4/results/policy_iteration_20261004/L1_initialize_public.json').read_text())
actor=exact_entry.ExactCachedRequestPolicy(initial)
g=AdaptiveFaultGuard(actor);g.false_count=1;g.negative_utc=format_utc(actor.planner.nights[0][0]);g.negative_level=.5

def row(night,slot,ratio):
 start=actor.planner.nights[night][0]+timedelta(seconds=900*slot)
 return {'rank':night*32+slot,'night':night,'slot':slot,'start_utc':format_utc(start),'now_utc':format_utc(start+timedelta(seconds=300)),
         'ratio_lo':ratio*.9,'ratio_hi':ratio,'hits':5,'field_sector':slot%4,'program':'DARK','earthquake_notice':True}
for n in (1,2):
 for slot in range(4):g.rows.append(row(n,slot,.5))
g.learn_background();assert g.background is not None
for n in (3,4):
 for slot in range(4):g.rows.append(row(n,slot,.5))
s={'now_utc':format_utc(actor.planner.nights[4][0]+timedelta(seconds=3600)),'observe_action_index':132,'wallclock':{'remaining_seconds':900},'latest_bulletin':{'notices':[{'event_kind':'earthquake','direction':'ALL'}]}}
assert not g.new_change(s)['qualified']
for n in (5,6):
 for slot in range(4):g.rows.append(row(n,slot,.225))
s['now_utc']=format_utc(actor.planner.nights[6][0]+timedelta(seconds=3600));s['observe_action_index']=196
f=g.new_change(s);assert f['qualified'] and f['fault_posterior_model']>.99
with (HERE/'firstentry/L1_control.stdout.jsonl').open() as h:a=json.loads(h.readline())
a={k:v for k,v in a.items() if k not in ('protocol_version','message_type','decision_sequence')}
actor.pending={'action':a,'prediction':{t:{'factor':.3,'predicted_band':'DARK'} for t in a['assignments'].values()}}
value=g.quota_value(s,a,f['fault_posterior_model']);assert value['diagnostic_net_value_model']>0
assert g.propose(s,a)['action']=='report' and g.inserted==1
# Same conditional experiment with tiny recovery and a very high quota option
# price must reject the last diagnostic despite qualified product evidence.
g2=AdaptiveFaultGuard(actor);g2.false_count=1;g2.negative_utc=g.negative_utc;g2.background=g.background;g2.rows=copy.deepcopy(g.rows)
g2.quota_value=lambda *args:{'diagnostic_net_value_model':-1.}
assert g2.propose(s,a)==a and g2.inserted==0
result={'passed':True,'synthetic_mechanism_only':True,'checks':['false-report background learned from eight stable public slots over two nights','same background level rejected','additional 50% persistent drop posterior qualifies','final free quota used only after positive explicit net value','negative net value rejects diagnostic'],'example_value_model':value,'posterior_is_uncalibrated':True}
# Actual package entry against the exact same explicit public-prefix fixture.
for card in ('L1','L2'):
 protocol=(ROOT/f'formal_v4/results/request_terminal_adaptation_20261004/public_entry/{card}/public_input.jsonl').read_text()
 env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':'0','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
 for mode in ('0','1'):
  run=subprocess.run([sys.executable,'-u','wrapper.py'],cwd=HERE/'candidate_v2_package',input=protocol,text=True,capture_output=True,env={**env,'REQUEST_PERSISTENT_FAULT_ENABLE':mode},timeout=60)
  assert run.returncode==0 and 'Traceback' not in run.stderr
  (HERE/'firstentry'/f'{card}_v2_enable_{mode}.stdout.jsonl').write_text(run.stdout);(HERE/'firstentry'/f'{card}_v2_enable_{mode}.stderr.jsonl').write_text(run.stderr)
  ref=[json.loads(x) for x in (HERE/'firstentry'/f'{card}_control.stdout.jsonl').read_text().splitlines()]
  assert [json.loads(x) for x in run.stdout.splitlines()]==ref
result['public_firstentry_equal']=True
(HERE/'v2_mechanism_checks.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
