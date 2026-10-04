from pathlib import Path
import importlib.util,sys,json,copy,subprocess,os,hashlib,time
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(HERE/'candidate_package'))
from research import agent_request_exact_cache as exact_entry
from persistent_fault_guard import PersistentFaultGuard
spec=importlib.util.spec_from_file_location('public_projection_source',ROOT/'formal_v4/results/request_terminal_adaptation_20261004/check_adaptation.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def write(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n')
reports={}
for card,base in [('L1','request_geometry_integration_20261004'),('L2','request_geometry_integration_20261004'),('L3','request_terminal_pair_20261004')]:
 m.REFERENCE=ROOT/f'formal_v4/results/{base}/seasons/control'
 initial,snapshots,actions,metadata=m.reconstruct(card)
 # Reconstruct only public observations. Remove every proxy runtime field;
 # no actor planning is replayed on this reconstructed historical trace.
 for s in snapshots:s.pop('wallclock',None);s.pop('active_requests',None)
 actor=exact_entry.ExactCachedRequestPolicy(initial)
 guard=PersistentFaultGuard(actor)
 first=None;qualified=[];sampled=[]
 for s,a in zip(snapshots,actions):
  guard.ingest(s)
  if a['action']=='observe':
   f=guard.evidence(s)
   if f['qualified']:
    q={'now_utc':s['now_utc'],'observe_action_index':s['observe_action_index'],'features':f}
    qualified.append(q)
    if first is None and int(guard.reporting['false_report_free_allowance'])-guard.false_count>guard.cfg['free_quota_reserve']:first=q
  guard.sent(s,a)
  if guard.rows and (not sampled or sampled[-1]['rank']!=guard.rows[-1]['rank']):sampled.append(dict(guard.rows[-1]))
 write(HERE/(card+'_public_product_rows.json'),sampled)
 reports[card]={'first_qualified_public_diagnostic':first,'qualified_count':len(qualified),'observations_with_clean_product':len(sampled),
                'original_report_public_results':[x for x in m.read_jsonl(m.REFERENCE/card/'messages.jsonl') if x['record_type']=='report_result'],
                'history_mode':'observational features only; no planning replay or simulated diagnostic outcomes',
                'wallclock':'not recoverable and deleted; actual candidate requires live wallclock',
                'metadata':{k:v for k,v in metadata.items() if k not in ('substituted_fields','recoverable_fields')}}
 write(HERE/(card+'_public_qualifications.json'),qualified)
write(HERE/'public_trajectory_audit.json',reports)
# Equal input first-entry fixture verifies exact class binding. Its explicitly
# supplied wallclock is a test input, not a recovered historical clock.
entry=HERE/'firstentry';entry.mkdir(exist_ok=True)
for card in ('L1','L2'):
 source=ROOT/f'formal_v4/results/request_terminal_adaptation_20261004/public_entry/{card}/public_input.jsonl'
 protocol=source.read_text();allactions={}
 for variant,args,enable in [('control',['-m','research.agent_request_exact_cache'],None),('disabled',['wrapper.py'],'0'),('enabled',['wrapper.py'],'1')]:
  package='control_package' if variant=='control' else 'candidate_package'
  env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':'0','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
  if enable is not None:env['REQUEST_PERSISTENT_FAULT_ENABLE']=enable
  p=subprocess.run([sys.executable,'-u',*args],cwd=HERE/package,input=protocol,text=True,capture_output=True,env=env,timeout=60)
  assert p.returncode==0 and 'Traceback' not in p.stderr,(variant,p.stderr)
  (entry/f'{card}_{variant}.stdout.jsonl').write_text(p.stdout);(entry/f'{card}_{variant}.stderr.jsonl').write_text(p.stderr)
  allactions[variant]=[json.loads(x) for x in p.stdout.splitlines()]
 assert allactions['control']==allactions['disabled']==allactions['enabled']
 reports[card]['firstentry_equal_input_fixture']={'responses':len(allactions['control']),'exact_equal':True,'source':str(source),'historical_wallclock_claim':False}
write(HERE/'public_trajectory_audit.json',reports)
print(json.dumps({k:{'first':v['first_qualified_public_diagnostic'],'clean_exposures':v['observations_with_clean_product']} for k,v in reports.items()},indent=2))
