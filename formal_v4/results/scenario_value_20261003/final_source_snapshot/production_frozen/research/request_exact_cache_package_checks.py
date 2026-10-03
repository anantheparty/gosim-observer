"""Frozen-package JSONL and actual-wrapper full-window equality gates."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile

FORMAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FORMAL))
sys.path.insert(0, str(FORMAL/'research'))
from pack_verified_portfolio import public_card
from request_exact_cache_checks import setup

SHA = lambda b: hashlib.sha256(b).hexdigest()
ZIP = Path('/Users/kamico/Downloads/observer_request_exact_cache.zip')
SOURCE = Path('/Users/kamico/Downloads/observer_request_phase_gpu.zip')
DEST = FORMAL/'results/request_exact_cache_candidate_20261003'
DEST.mkdir(exist_ok=True)

GUARD = '''import os,socket
marker=os.environ['EXACT_CACHE_GATE_MARKER']
def denied(*args,**kwargs):
    with open(marker,'a') as f:f.write('attempt\\n')
    raise AssertionError('network forbidden')
socket.socket.connect=denied
socket.socket.connect_ex=denied
socket.create_connection=denied
socket.getaddrinfo=denied
original=os._Environ.__getitem__
def no_credentials(self,key):
    if key in ('OPENAI_API_KEY','OPENAI_BASE_URL'):
        with open(marker,'a') as f:f.write('credential_read\\n')
        raise AssertionError('injected credential access forbidden')
    return original(self,key)
os._Environ.__getitem__=no_credentials
'''

FULL_GATE = '''import json,sys,time,hashlib
from dataclasses import asdict
from datetime import datetime,timezone
import numpy as np
from research import agent_request_exact_cache as wrapper
from research.request_remote_planner import RequestRemotePlanner
from research.request_mask_dp import solve_request_columns
from research.terrain_version_space import TerrainVersionSpace
from research.spatial_candidates import parse_utc
data=json.load(open(sys.argv[1]))
policy=wrapper.ExactCachedRequestPolicy(data['initial'])
assert type(policy.planner) is wrapper.ExactCachedRequestRemotePlanner
assert policy.remote is None
assert policy.planner.distributed_transport is None
env={**policy.config,**data['env']}
def clean(v):
    if isinstance(v,np.ndarray):return v.tolist()
    if isinstance(v,np.generic):return v.item()
    if hasattr(v,'isoformat'):return v.isoformat()
    if isinstance(v,dict):return {k:clean(x) for k,x in v.items() if k!='build_seconds'}
    if isinstance(v,(tuple,list)):return [clean(x) for x in v]
    return v
def canonical(info):
    converted=dict(info);converted['columns']=[asdict(x) for x in info['columns']]
    return json.dumps(clean(converted),sort_keys=True,separators=(',',':'),allow_nan=False)
out=[]
now=parse_utc(data['now'])
for planner in [RequestRemotePlanner(data['initial']),policy.planner]:
    planner.terrain_model=TerrainVersionSpace.reference_prior(data['directions'],planner.lat,planner.lon)
    s,f=planner._array(data['scores']),planner._array(data['factors'])
    t=time.perf_counter();pool=planner._build_pool(data['request'],now,s,f,env,data['snapshot']);seconds=time.perf_counter()-t
    plan=solve_request_columns(pool['columns'],target_count=len(pool['idx']),quorum=data['request']['minimum_completed'],now=now.timestamp(),deadline=pool['deadline'].timestamp())
    actions=[]
    for selected in plan.chosen_indices:
        col=pool['columns'][selected];moment=datetime.fromtimestamp(col.start,timezone.utc)
        planner._active_future_field=planner._future_field(data['snapshot'],env)
        actions.append(planner._request_action(col.tag,moment,pool,s,f,env,0))
        planner._active_future_field=None
    out.append({'pool':canonical(pool),'plan':clean(asdict(plan)),'actions':actions,'seconds':seconds,'columns':len(pool['columns'])})
assert out[0]['pool']==out[1]['pool']
assert out[0]['plan']==out[1]['plan']
assert out[0]['actions']==out[1]['actions']
assert policy.planner.distributed_counts['remote_baselines']==0
print(json.dumps({'gate':'actual-wrapper-complete-published-REQ','planner_class':type(policy.planner).__name__,'card':'delta','request_id':data['request']['request_id'],'columns':out[0]['columns'],'all_columns_bitwise_equal':True,'DP_bitwise_equal':True,'all_selected_actions_bitwise_equal':True,'selected_actions':len(out[0]['actions']),'pool_sha256':hashlib.sha256(out[0]['pool'].encode()).hexdigest(),'baseline_seconds':out[0]['seconds'],'cached_seconds':out[1]['seconds'],'remote_calls':0,'cache_stats':policy.planner.exact_cache_stats}))
'''


def main():
    with zipfile.ZipFile(ZIP) as z: contents={n:z.read(n) for n in z.namelist()}
    with zipfile.ZipFile(SOURCE) as z: old={n:z.read(n) for n in z.namelist()}
    assert SHA(SOURCE.read_bytes())=='bfcc8ed738229e961c2135415d44dbef27e78b5386c3bdfdabaee915904e91ec'
    preserved=[n for n in old if n not in ('observer.project.json','remote_runtime.json','build_manifest.json')]
    assert all(contents[n]==old[n] for n in preserved)
    manifest=json.loads(contents['build_manifest.json'])
    assert set(manifest)==set(contents)-{'build_manifest.json'}
    assert all(SHA(contents[n])==v for n,v in manifest.items())
    secret=(FORMAL/'runs/gpu_service/token').read_bytes().strip()
    assert secret and all(secret not in b for b in contents.values())
    assert not any('truth' in n or n.endswith(('model_gpu_adapter.py','gpu_planner_server.py')) for n in contents)
    sys.path.insert(0,'/tmp/gosim-generation-audit-20261003')
    from project_platform.package import read_project_zip,read_manifest,project_digest
    files=read_project_zip(ZIP.read_bytes()); read_manifest(files)
    fingerprint=project_digest(files)
    gates=[]
    with tempfile.TemporaryDirectory(prefix='gosim-request-exact-cache-gates-') as tmp:
        frozen=Path(tmp)/'frozen';frozen.mkdir()
        for n,b in contents.items():
            p=frozen/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
        deps=frozen/'.deps';deps.mkdir();(deps/'sitecustomize.py').write_text(GUARD)
        marker=Path(tmp)/'attempts.txt'
        for mode in ['missing','dummy']:
            for card in ['alpha','beta','gamma','delta']:
                initial,_=public_card(card)
                snapshot={'now_utc':initial['survey']['start_utc'],'wallclock':{'remaining_seconds':900},'active_requests':[],'last_result':None,'bulletin':{'notices':[]}}
                messages=[{'protocol_version':'participant-agent-protocol-v4','message_type':'initialize','payload':initial},
                          {'protocol_version':'participant-agent-protocol-v4','message_type':'decision_request','decision_sequence':1,'payload':snapshot},
                          {'protocol_version':'participant-agent-protocol-v4','message_type':'finish','payload':{}}]
                env=dict(os.environ);env['PYTHONPATH']=os.pathsep.join([str(deps),str(frozen)]);env['EXACT_CACHE_GATE_MARKER']=str(marker)
                for k in ['OPENAI_BASE_URL','OPENAI_API_KEY']:env.pop(k,None)
                if mode=='dummy':env.update(OPENAI_BASE_URL='https://example.invalid/v1',OPENAI_API_KEY='dummy-credential-forbidden-read')
                t=time.perf_counter()
                proc=subprocess.run([sys.executable,'-u','-m','research.agent_request_exact_cache'],cwd=frozen,env=env,input=('\n'.join(json.dumps(m) for m in messages)+'\n').encode(),capture_output=True,check=True,timeout=30)
                assert secret not in proc.stdout+proc.stderr and b'Traceback' not in proc.stderr
                responses=[json.loads(line) for line in proc.stdout.splitlines()]
                assert len(responses)==1 and responses[0]['message_type']=='decision_response' and responses[0]['decision_sequence']==1
                assert responses[0]['action']=='observe' and responses[0]['assignments']
                records=[json.loads(line) for line in proc.stderr.splitlines() if line.startswith(b'{')]
                check=next(r for r in records if r.get('remote_check')=='disabled')
                summary=next(r for r in records if 'request_exact_cache' in r)
                assert check['seconds']==0 and summary['remote_calls']==0 and summary['remote_seconds']==0
                assert summary['request_exact_cache_class']=='ExactCachedRequestRemotePlanner'
                assert summary['distributed_request']['cpu_baselines']==1
                assert not marker.exists()
                gates.append({'card':card,'injected_environment':mode,'strict_JSONL_initialize_choose_finish':True,'remote_check':check,'network_or_credential_attempts':0,'seconds':time.perf_counter()-t,'action_sha256':SHA(json.dumps(responses[0],sort_keys=True,separators=(',',':')).encode())})
        payload,hashes,req,now,scores,factors,directions,env,snapshot=setup('delta',1,True)
        inp=Path(tmp)/'input.json'
        inp.write_text(json.dumps({'initial':payload,'request':req,'now':now.isoformat(),'scores':scores,'factors':factors,'directions':directions,'env':env,'snapshot':snapshot}))
        proc=subprocess.run([sys.executable,'-u','-c',FULL_GATE,str(inp)],cwd=frozen,env={**os.environ,'PYTHONPATH':os.pathsep.join([str(deps),str(frozen)]),'EXACT_CACHE_GATE_MARKER':str(marker)},capture_output=True,check=True,timeout=90)
        assert not marker.exists() and secret not in proc.stdout+proc.stderr and b'Traceback' not in proc.stderr
        full=json.loads(proc.stdout)
        full['public_input_hashes']=hashes
    for card in ['alpha','beta','gamma','delta']:
        matches=[g for g in gates if g['card']==card]
        assert matches[0]['action_sha256']==matches[1]['action_sha256']
    result={'schema':'frozen-request-exact-cache-package-gates-v1','status':'READY_NOT_UPLOADED_OR_SCORED',
            'zip':{'file':str(ZIP),'sha256':SHA(ZIP.read_bytes()),'source_fingerprint':fingerprint,'bytes':ZIP.stat().st_size,'files':len(contents)},
            'frozen_source_zip_sha256':SHA(SOURCE.read_bytes()),'all_original_algorithms_and_policy_config_bytes_preserved':True,
            'preserved_files':preserved,'algorithm_parameters_changed':False,'private_runtime_token_matches':0,'hidden_or_server_files':0,
            'network_calls_or_injected_credential_reads':0,'JSONL_gates':gates,'full_window_actual_wrapper_gate':full,
            'all_cards_use_request_route':True,'score_measured':False,
            'scope':{'UI_operations':0,'submission_operations':0,'deployment_operations':0,'git_index_mutations':0},
            'source_sha256':{str(p.relative_to(FORMAL)):SHA(p.read_bytes()) for p in [FORMAL/'pack_request_exact_cache.py',FORMAL/'research/agent_request_exact_cache.py',FORMAL/'research/request_exact_cache.py',Path(__file__)]}}
    (DEST/'package_gates.json').write_text(json.dumps(result,indent=2)+'\n')
    (DEST/'exact_cache_provenance.json').write_bytes(contents['exact_cache_provenance.json'])
    print(json.dumps({'status':result['status'],'zip':result['zip'],'strict_JSONL_gates':len(gates),'full_REQ_columns':full['columns'],'selected_actions':full['selected_actions'],'network_or_credential_reads':0,'private_token_matches':0}))


if __name__=='__main__':main()
