"""Actual initial official snapshots and responses; host stops after five decisions."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess,os,sys,json,time,hashlib
OUT=Path(__file__).resolve().parent
KIT=Path('/tmp/geometry_native_20261003/upstream/gosim-observer-examples')
sys.path.insert(0,str(KIT/'runner'))
from challenge.v4_workflow import V4Workflow
IMAGE='python@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016'
DEPS='/tmp/geometry_native_20261003/.deps'

def run(case):
 variant,card,mode=case;folder=OUT/'short_protocol'/variant/card/mode;folder.mkdir(parents=True,exist_ok=False)
 package=OUT/(variant+'_package')
 entry=['sparse_entry.py'] if mode=='sparse' else (['-m','research.agent_request_exact_cache'] if variant=='strong' else ['wrapper.py' if variant=='fault' else 'debias_entry.py'])
 command=['docker','run','--rm','-i','--cpus','2','--cpuset-cpus','16,17','--memory','2048m','--memory-swap','2048m','--network','none','--read-only','--user','1000:1000','--tmpfs','/tmp:rw,nosuid,size=256m','--mount',f'type=bind,src={package},dst=/workspace,readonly','--mount',f'type=bind,src={DEPS},dst=/deps,readonly','--workdir','/workspace','--env','PYTHONPATH=/deps','--env','PYTHONDONTWRITEBYTECODE=1','--env','OPENBLAS_NUM_THREADS=1','--env','OMP_NUM_THREADS=1','--env','MKL_NUM_THREADS=1',IMAGE,'python3','-u',*entry]
 workflow=V4Workflow(KIT/'local-cards'/card);records=[];started=time.perf_counter()
 with (folder/'agent.log').open('w') as log:
  p=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,bufsize=1)
  def send(x):p.stdin.write(json.dumps(x,separators=(',',':'))+'\n');p.stdin.flush()
  def initialize(payload):send(workflow.initialize_message(payload))
  def decide(message,deadline):
   if message['decision_sequence']>5:return {'protocol_version':'participant-agent-protocol-v4','message_type':'decision_response','decision_sequence':message['decision_sequence'],'action':'finish'}
   send(message);response=json.loads(p.stdout.readline());records.append({'request':message,'response':response});return response
  result=workflow.run(decide,folder,initialize=initialize,wallclock_seconds=900)
  send({'protocol_version':'participant-agent-protocol-v4','message_type':'finish','payload':{}});p.stdin.close();p.wait(timeout=30)
 (folder/'public_five.json').write_text(json.dumps(records,indent=2)+'\n')
 return {'variant':variant,'card':card,'mode':mode,'records':records,'wall_seconds':time.perf_counter()-started,'returncode':p.returncode,'workflow':result}
results=[]
# Sequential to preserve the same two physical CPUs without competition.
for v in ('strong','fault','debias'):
 for c in ('L1','L2'):
  a=run((v,c,'original'));b=run((v,c,'sparse'))
  def clean(r):return [{'request':{k:v for k,v in x['request']['payload'].items() if k!='wallclock'},'response':x['response']} for x in r['records']]
  passed=clean(a)==clean(b);assert passed,(v,c)
  row={'variant':v,'card':c,'official_same_public_requests_responses':passed,'responses':5,'original_wall_seconds':a['wall_seconds'],'sparse_wall_seconds':b['wall_seconds'],'original_returncode':a['returncode'],'sparse_returncode':b['returncode']}
  results.append(row);print(json.dumps(row),flush=True)
(OUT/'short_protocol_result.json').write_text(json.dumps({'scope':__doc__,'results':results,'all_passed':True},indent=2)+'\n')
