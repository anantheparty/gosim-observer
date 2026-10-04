"""Three real initial public decisions: original, disabled, enabled entries."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[2]
KIT=ROOT/'formal_v4/upstream/gosim-observer-examples'
sys.path.insert(0,str(KIT/'runner'))
from challenge.v4_workflow import V4Workflow

def run(name):
    folder=BASE/'debias_parity'/name;folder.mkdir(parents=True,exist_ok=False)
    original=name=='original';project=BASE/('package' if original else 'debias_package')
    command=[sys.executable,'-u','-m','research.agent_request_exact_cache'] if original else [sys.executable,'-u','debias_entry.py']
    env={'PATH':os.environ['PATH'],'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1',
        'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
        'DEBIAS_ENABLED':'0' if name=='disabled' else '1'}
    workflow=V4Workflow(KIT/'local-cards/L1');records=[]
    with (folder/'agent.log').open('w') as log:
        p=subprocess.Popen(command,cwd=project,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,bufsize=1)
        def send(x):p.stdin.write(json.dumps(x,separators=(',',':'))+'\n');p.stdin.flush()
        def initialize(payload):send(workflow.initialize_message(payload))
        def decide(message,deadline):
            if message['decision_sequence']>3:
                return {'protocol_version':'participant-agent-protocol-v4','message_type':'decision_response',
                    'decision_sequence':message['decision_sequence'],'action':'finish'}
            send(message);response=json.loads(p.stdout.readline());records.append({'request':message,'response':response});return response
        result=workflow.run(decide,folder,initialize=initialize,wallclock_seconds=900)
        send({'protocol_version':'participant-agent-protocol-v4','message_type':'finish','payload':{}})
        p.stdin.close();p.wait(timeout=30)
    (folder/'public_three.json').write_text(json.dumps(records,indent=2)+'\n')
    return records

with ThreadPoolExecutor(max_workers=3) as e:
    data=dict(zip(('original','disabled','enabled'),e.map(run,('original','disabled','enabled'))))
def clean(records):
    return [{'request':{k:v for k,v in x['request']['payload'].items() if k!='wallclock'},'response':x['response']} for x in records]
result={'actual_official_public_three':True,'disabled_all_requests_responses_match':clean(data['original'])==clean(data['disabled']),
    'disabled_responses_match':[a['response']==b['response'] for a,b in zip(data['original'],data['disabled'])],
    'enabled_responses_match_original':[a['response']==b['response'] for a,b in zip(data['original'],data['enabled'])],
    'wallclock':'fresh measured clocks each branch; excluded for equality','scope':'normal initial prefix, no forced actor tape or stop machinery',
    'source_entry':'debias_entry.py default enabled, DEBIAS_ENABLED=0 exact hook bypass'}
(BASE/'debias_parity_result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
