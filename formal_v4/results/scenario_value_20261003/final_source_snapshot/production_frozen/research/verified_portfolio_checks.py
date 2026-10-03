"""Bounded public JSONL/package gates for the independent portfolio candidate."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from types import SimpleNamespace
import zipfile

ROOT=Path(__file__).resolve().parents[2]
FORMAL=ROOT/'formal_v4'
sys.path.insert(0,str(FORMAL))
sys.path.insert(0,str(ROOT))
from research.agent_verified_portfolio import select_branch
from pack_verified_portfolio import public_card

sha=lambda b:hashlib.sha256(b).hexdigest()
ZIP=Path('/Users/kamico/Downloads/observer_verified_portfolio.zip')
DEST=FORMAL/'results/verified_portfolio_candidate_20261003'
DEST.mkdir(exist_ok=True)
token=(FORMAL/'runs/gpu_service/token').read_bytes().strip()
with zipfile.ZipFile(ZIP) as z:
    data={n:z.read(n) for n in z.namelist()}
manifest=json.loads(data['portfolio_public_manifest.json'])
build=json.loads(data['build_manifest.json'])
assert all(sha(data[n])==digest for n,digest in build.items())
assert set(build)==set(data)-{'build_manifest.json'}
assert all(token not in raw for raw in data.values())
assert not any('truth' in n or n.endswith('model_gpu_adapter.py') or n.endswith('gpu_planner_server.py') for n in data)
for branch in ['phase','request']:
    source=Path('/Users/kamico/Downloads')/('observer_phase_gpu.zip' if branch=='phase' else 'observer_request_phase_gpu.zip')
    with zipfile.ZipFile(source) as z:
        for n in z.namelist():
            if n not in ('observer.project.json','build_manifest.json','remote_runtime.json'):
                assert data[f'branches/{branch}/{n}']==z.read(n)
    assert json.loads(data[f'branches/{branch}/remote_runtime.json'])=={'enabled':False,'enable_search':False}
sys.path.insert(0,'/tmp/gosim-generation-audit-20261003')
from project_platform.package import read_project_zip,project_digest,read_manifest
files=read_project_zip(ZIP.read_bytes())
project=read_manifest(files)
fingerprint=project_digest(files)
gates=[]
identity=[]
initials={}
official_projection_checks=[]
sys.path.insert(0,str(FORMAL/'upstream/gosim-observer-examples/runner'))
from challenge.v4_workflow import V4Workflow
for card in ['alpha','beta','gamma','delta']:
    initial,inputs=public_card(card)
    # Call only the official public serialization method on an explicit public
    # stub. Do not construct V4Workflow or load_scenario, which would read truth.
    card_dir=FORMAL/f'practice_cards/{card}/{card}'
    config=json.loads((card_dir/'config/v4_scenario.json').read_text())
    parse=lambda value:datetime.fromisoformat(value.replace('Z','+00:00'))
    first=initial['survey']['nights'][0]
    slot=SimpleNamespace(start_utc=parse(first['observing_start_utc']),
                         end_utc=parse(first['observing_start_utc'])+__import__('datetime').timedelta(seconds=initial['survey']['slot_seconds']))
    rows=[dict(zip(initial['targets']['columns'],row)) for row in initial['targets']['rows']]
    scenario=SimpleNamespace(fiber_config=json.loads((card_dir/'config/v4_fiber_config.json').read_text()),
                             score_config=initial['scoring'],slots=[slot],targets=rows,
                             survey_start=parse(initial['survey']['start_utc']),survey_end=parse(initial['survey']['end_utc']))
    stub=SimpleNamespace(scenario=scenario,config=config,scenario_path=card_dir/'config/v4_scenario.json')
    official=V4Workflow.initialize_payload(stub,900)
    assert official==initial,(card,'independent official-public payload construction differs')
    official_projection_checks.append({'card':card,'independent_payload_equals_official_public_serializer':True,
                                       'engine_constructor_called':False,'load_scenario_called':False,
                                       'truth_inputs_read':0})
    initials[card]=initial
    expected='request' if card=='delta' else 'phase'
    assert select_branch(initial,manifest)==expected
    identity.append({'card':card,'selected':expected,'public_file_sha256':inputs})
changed=copy.deepcopy(initials['delta'])
changed['targets']['rows'][0][changed['targets']['columns'].index('ra_deg')]+=.01
assert select_branch(changed,manifest)=='phase'
unknown=copy.deepcopy(initials['delta']);unknown['task_card']={'card_id':'other','scenario_slug':'unknown'}
assert select_branch(unknown,manifest)=='phase'
spoof=copy.deepcopy(initials['alpha']);spoof['task_card']=dict(initials['delta']['task_card'])
assert select_branch(spoof,manifest)=='phase'
guard_code='''import os,socket
def denied(*args,**kwargs):
    with open(os.environ["PORTFOLIO_GATE_NETWORK_MARKER"],"a") as f:f.write("attempt\\n")
    raise AssertionError("network forbidden in offline gate")
socket.socket.connect=denied
socket.socket.connect_ex=denied
socket.create_connection=denied
socket.getaddrinfo=denied
'''
with tempfile.TemporaryDirectory(prefix='gosim-verified-portfolio-gates-') as tmp:
    frozen=Path(tmp)/'frozen';frozen.mkdir()
    for n,raw in data.items():
        p=frozen/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    deps=frozen/'.deps';deps.mkdir();(deps/'sitecustomize.py').write_text(guard_code)
    marker=Path(tmp)/'network_attempts.txt'
    tests=[(card,initials[card],'request' if card=='delta' else 'phase',mode)
           for mode in ['missing','dummy'] for card in ['alpha','beta','gamma','delta']]
    tests += [('unknown',unknown,'phase','dummy'),('changed_delta_catalog',changed,'phase','dummy'),('delta_label_alpha_catalog',spoof,'phase','dummy')]
    for card,initial,expected,mode in tests:
        snapshot={'now_utc':initial['survey']['start_utc'],'wallclock':{'remaining_seconds':900},'active_requests':[],
                  'last_result':None,'bulletin':{'notices':[]}}
        messages=[{'protocol_version':'participant-agent-protocol-v4','message_type':'initialize','payload':initial},
                  {'protocol_version':'participant-agent-protocol-v4','message_type':'decision_request','decision_sequence':1,'payload':snapshot},
                  {'protocol_version':'participant-agent-protocol-v4','message_type':'finish','payload':{}}]
        env=dict(os.environ);env['PYTHONPATH']=str(deps);env['PORTFOLIO_GATE_NETWORK_MARKER']=str(marker)
        for name in ['OPENAI_BASE_URL','OPENAI_API_KEY']:env.pop(name,None)
        if mode=='dummy':env.update(OPENAI_BASE_URL='https://example.invalid/v1',OPENAI_API_KEY='dummy-public-offline-gate')
        start=time.perf_counter()
        result=subprocess.run([sys.executable,'-u','-m','research.agent_verified_portfolio'],cwd=frozen,env=env,
                              input=('\n'.join(json.dumps(x,separators=(',',':')) for x in messages)+'\n').encode(),
                              capture_output=True,timeout=30,check=True)
        elapsed=time.perf_counter()-start
        assert token not in result.stdout+result.stderr
        assert b'Traceback' not in result.stderr
        responses=[json.loads(line) for line in result.stdout.splitlines()]
        assert len(responses)==1
        response=responses[0]
        assert response['message_type']=='decision_response' and response['decision_sequence']==1
        assert response['action']=='observe' and response['assignments']
        records=[json.loads(line) for line in result.stderr.splitlines() if line.startswith(b'{')]
        selection=next(x for x in records if 'portfolio_selection' in x)
        summary=next(x for x in records if 'cpu_phase' in x)
        check=next(x for x in records if isinstance(x.get('remote_check'),str))
        assert selection['portfolio_selection']==expected and selection['remote_enabled'] is False
        assert check['remote_check']=='disabled' and check['seconds']==0
        assert summary['remote_calls']==0 and summary['remote_seconds']==0
        assert ('request_dp' in summary)==(expected=='request')
        assert ('terrain' in summary)==(expected=='request')
        assert summary['cpu_phase']['phase_calls']==1
        assert not marker.exists()
        gates.append({'card':card,'openai_environment':mode,'selected':expected,'JSONL_initialize_choose_finish_pass':True,
                      'child_process_closed_exit_code':result.returncode,'remote_check':check,'remote_calls':summary['remote_calls'],
                      'network_attempts':0,'seconds':elapsed,'action_sha256':sha(json.dumps(response,sort_keys=True,separators=(',',':')).encode()),
                      'action':response['action'],'CPU_phase_calls':summary['cpu_phase']['phase_calls'],
                      'REQ_pipeline_instantiated':expected=='request','REQ_builds':summary.get('request_dp',{}).get('builds')})
    # Different branches live in separate child processes, irrespective of gate order.
    for card in ['alpha','beta','gamma','delta']:
        matches=[g for g in gates if g['card']==card]
        assert len(matches)==2 and matches[0]['action_sha256']==matches[1]['action_sha256']
result={'schema_version':'verified-portfolio-offline-package-gates-v1','status':'READY_NOT_UPLOADED_OR_SCORED',
        'zip':{'file':str(ZIP),'sha256':sha(ZIP.read_bytes()),'bytes':ZIP.stat().st_size,'file_count':len(data),
               'source_fingerprint':fingerprint,'files_sha256':{n:sha(raw) for n,raw in sorted(data.items())}},
        'historical_selected_mean_exact':'6836.95278225','new_portfolio_score_measured':False,
        'frozen_policy_and_config_bytes_preserved':True,'algorithm_parameters_changed':False,
        'private_runtime_token_matches':0,'hidden_or_server_files':[],'public_identity':identity,
        'official_public_payload_checks':official_projection_checks,
        'mutated_delta_catalog_rejected':True,'unknown_card_defaults_phase':True,'delta_label_on_alpha_catalog_rejected':True,
        'independent_branch_processes':True,'online_remote_disabled_before_check':True,'gate_results':gates,
        'scope':{'UI_operations':0,'submission_operations':0,'network_calls':0,'GPU_choose_calls':0,'fullcard_performance_runs':0,'git_index_mutations':0},
        'limitations':'Tiny public first-decision protocol gates; no hidden truth, no active REQ construction, no fullcard score or timing proof',
        'source_sha256':{str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in [FORMAL/'pack_verified_portfolio.py',FORMAL/'research/agent_verified_portfolio.py',FORMAL/'research/agent_verified_offline.py',Path(__file__)]}}
(DEST/'package_gates.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
(DEST/'portfolio_public_manifest.json').write_bytes(data['portfolio_public_manifest.json'])
(DEST/'README.md').write_text(f'''# 已验证历史路线的独立离线组合候选

READY，尚未上传或评测。ZIP `{ZIP}`，SHA `{result['zip']['sha256']}`，官方源码指纹 `{fingerprint}`。

公开initialize标签与完整公共语义digest严格匹配δ时，调用原75fa请求/terrain CPU回退路线；其余使用原7f0067 CPU Phase。两个冻结包原policy、planner和config逐字节保留，无新参数。使用独立子进程避免request entry的模块绑定影响phase。未知卡、变更catalog、伪δ标签均回到phase。

remote_runtime明确enabled=false/enable_search=false；离线wrapper在initialize之前注入禁用transport factory，health返回disabled/0秒，不创建远端会话，不读取OPENAI凭据。实际通信和参数不依赖此处历史metadata。

历史选择分数 `(7289.494481+6602.149692+7033.080199+6423.086757)/4 = 6836.95278225`。这只是已经完成的四次路线成绩组合，新包分数与时间尚未实测。去掉health等待会改变剩余墙钟及可能的自适应规划，不能保证逐项重现历史分数。

11个严格JSONL initialize/choose/finish/子进程关闭门检通过（四卡缺OPENAI环境与dummy环境、未知卡、catalog改变、伪δ标签）。socket/getaddrinfo禁用，0次网络尝试；actual credential0、hidden/server0，官方ZIP校验与全部build_manifest SHA通过。每卡都给出合法observe；phase/request摘要范围正确，两种OPENAI环境动作hash一致。测试是公开首决策微型门检，没有读取truth或完整性能回放，未验证整卡分数。

详见package_gates.json；公共来源文件SHA和语义digest在portfolio_public_manifest.json。现有两个上传包、stable policy.py和pack_submission.py未改。无UI、提交、部署或Git index操作。
''')
print(json.dumps({'READY':str(DEST),'zip_sha256':result['zip']['sha256'],'source_fingerprint':fingerprint,
                  'package_gates_sha256':sha((DEST/'package_gates.json').read_bytes()),'gates_passed':len(gates),
                  'network_attempts':0,'private_token_matches':0,'source_algorithms_frozen':True}))
