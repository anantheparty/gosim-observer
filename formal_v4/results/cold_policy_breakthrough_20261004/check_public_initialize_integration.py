#!/usr/bin/env python3
"""Actual READY/wrapper JSONL initialization plus two captured public feedbacks.

This is a three-decision prefix integration check, never a simulator run.  It
reads the fixed public initialize and only the first three public_history rows
of an existing natural-control capture.  No truth or target-label file is read.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
NATIVE=ROOT/'formal_v4/runs/geometry_native_20261003/release'
KIT=ROOT/'formal_v4/upstream/gosim-observer-examples'
INITIAL=ROOT/'formal_v4/results/policy_iteration_20261004/L3_initialize_public.json'
CAPTURE=ROOT/'formal_v4/results/policy_iteration_20261004/natural_control/L3/rank_0064/control/public_capture/capture.json'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
    os.environ.setdefault('OMP_NUM_THREADS','1')
    os.environ.setdefault('MKL_NUM_THREADS','1')
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(KIT/'runner'))
    # Only official static protocol constructors are invoked.  No workflow or
    # Scenario is constructed, and no scenario/config/truth file is opened.
    from challenge.v4_workflow import V4Workflow as Workflow
    import numpy as np
    initial=json.loads(INITIAL.read_text())
    assert initial['schema_version']=='v4-initialize-v1'
    targets=initial['targets']
    assert list(targets)==['columns','rows']
    assert targets['columns']==['target_id','ra_deg','dec_deg','target_class',
                               'feature_flux','science_weight','required']
    assert len(targets['rows'])==8700
    assert all(len(row)==len(targets['columns']) for row in targets['rows'])
    # Select the public_history member; do not use capture prediction/state or
    # any counterfactual utility member for actor inputs or action comparisons.
    history=json.loads(CAPTURE.read_text())['public_history'][:3]
    assert [r['observe_action_index'] for r in history]==[0,1,2]
    assert history[0]['last_result'] is None
    assert [r['last_result']['observe_index'] for r in history[1:]]==[0,1]
    latest_bulletin=latest_forecast=None
    scores={}
    snapshots=[]
    messages=[Workflow.initialize_message(initial)]
    for sequence,row in enumerate(history,1):
        result=row['last_result']
        if result:
            assert result['action']=='observe'
            assert all(set(hit)=={'target_id','score'} for hit in result['hits'])
            for hit in result['hits']:
                scores[hit['target_id']]=max(scores.get(hit['target_id'],0),hit['score'])
        for message in row['new_messages']:
            if message['record_type']=='bulletin':latest_bulletin=message
            elif message['record_type']=='forecast':latest_forecast=message
            else:raise AssertionError('First public prefix unexpectedly contains a request/resync')
        snapshot={
            'now_utc':row['now_utc'],'survey_end_utc':initial['survey']['end_utc'],
            'observe_action_index':row['observe_action_index'],
            'running_total':round(sum(scores.values()),6),
            'latest_bulletin':copy.deepcopy(latest_bulletin),
            'latest_forecast':copy.deepcopy(latest_forecast),'active_requests':[],
            'new_messages':copy.deepcopy(row['new_messages']),
            'last_result':copy.deepcopy(result),
        }
        request=Workflow.request_message(sequence,snapshot,0.,900.)
        snapshots.append(request['payload'])
        messages.append(request)
    messages.append({'protocol_version':'participant-agent-protocol-v4','message_type':'finish',
                     'payload':{'schema_version':'v4-finish-v1','termination_reason':'prefix_integration_check',
                                'decisions':3,'observe_actions':3}})
    output=HERE/'public_initialize_integration'
    output.mkdir(exist_ok=False)
    protocol=''.join(json.dumps(m,separators=(',',':'))+'\n' for m in messages)
    (output/'public_input.jsonl').write_text(protocol)
    env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
         'PYTHONHASHSEED':'0','PYTHONDONTWRITEBYTECODE':'1','GEOMETRY_NATIVE_PLANNER':'sweep',
         'TERMINAL_REPORT_BASE_ROOT':str(NATIVE),'TERMINAL_REPORT_MIN_WALLCLOCK':'10'}
    env.pop('PYTHONPATH',None)
    variants={}
    for name,command,enabled in [
        ('native',[sys.executable,'-u','-m','research.agent_geometry_native'],None),
        ('enabled0',[sys.executable,'-u',str(HERE/'terminal_report_agent.py')],0),
        ('enabled1',[sys.executable,'-u',str(HERE/'terminal_report_agent.py')],1),
    ]:
        current=env.copy()
        if enabled is not None:current['TERMINAL_REPORT_ENABLE']=str(enabled)
        else:current.pop('TERMINAL_REPORT_ENABLE',None)
        start=time.monotonic()
        run=subprocess.run(command,input=protocol,text=True,capture_output=True,
                           cwd=NATIVE,env=current,timeout=60)
        (output/(name+'.stdout.jsonl')).write_text(run.stdout)
        (output/(name+'.stderr.jsonl')).write_text(run.stderr)
        assert run.returncode==0,(name,run.returncode,run.stderr)
        assert 'Traceback' not in run.stderr,(name,run.stderr)
        responses=[json.loads(line) for line in run.stdout.splitlines() if line.strip()]
        assert len(responses)==3,'Initialize must not emit an ACK/response'
        assert [r['decision_sequence'] for r in responses]==[1,2,3]
        actions=[Workflow.action_from_response(r,seq) for seq,r in enumerate(responses,1)]
        assert all(action['action']=='observe' for action in actions)
        summaries=[json.loads(line) for line in run.stderr.splitlines() if line.startswith('{')]
        assert len(summaries)==1
        summary=summaries[0]
        assert summary['decisions']==3 and summary['exposures']==2
        if enabled is not None:
            guard=summary.pop('terminal_report')
            assert guard['enabled']==bool(enabled)
            assert guard['inserted_reports']==0 and guard['events']==[]
            assert guard['reads_truth'] is False and guard['reads_teacher_labels'] is False
            assert guard['gate_checks']==({'not_terminal':3} if enabled else {})
        variants[name]={'returncode':run.returncode,'elapsed_seconds':time.monotonic()-start,
                        'actions':actions,'summary':summary,'responses':responses}
    baseline=variants['native']
    for name in ['enabled0','enabled1']:
        assert variants[name]['actions']==baseline['actions'],name+' differs from unchanged READY'
        assert variants[name]['responses']==baseline['responses'],name+' JSONL differs from READY'
        for key in baseline['summary']:
            if key not in ('planning_seconds','remote_budget'):
                assert variants[name]['summary'][key]==baseline['summary'][key],(name,key)
    spec=importlib.util.spec_from_file_location('terminal_report_guard_check',HERE/'terminal_report_agent.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    guard=module.TerminalReportGuard(initial,enabled=True)
    assert len(guard.catalog)==len(targets['rows'])
    for snapshot,row in zip(snapshots,history):
        guard.ingest(snapshot)
        guard.sent(snapshot,row['action'])
    assert sorted(guard.entries)==[0,1]
    assert [len(guard.entries[rank]) for rank in [0,1]]==[14,13]
    native_manifest=json.loads((NATIVE/'build_manifest.json').read_text())
    native_files={str(p.relative_to(NATIVE)):sha(p) for p in sorted(NATIVE.rglob('*'))
                  if p.is_file() and '__pycache__' not in p.parts}
    assert native_files=={**native_manifest,'build_manifest.json':sha(NATIVE/'build_manifest.json')}
    result={
        'schema':'terminal-report-real-public-initialize-prefix-integration-v1','passed':True,
        'decisions_per_variant':3,'captured_public_feedbacks':2,'native_files_unchanged':20,
        'targets_contract':{'format':'columns/rows','columns':targets['columns'],'rows':8700},
        'inputs':{str(INITIAL.relative_to(ROOT)):sha(INITIAL),str(CAPTURE.relative_to(ROOT)):sha(CAPTURE)},
        'sources':{str(path.relative_to(ROOT)):sha(path) for path in [
            HERE/'terminal_report_agent.py',Path(__file__),KIT/'runner/challenge/v4_workflow.py',
            KIT/'runner/challenge/v4_runner.py',NATIVE/'research/spatial_candidates.py',
            NATIVE/'agent.py',NATIVE/'research/agent_geometry_native.py']},
        'first_action_and_two_feedback_actions_equal_READY':True,
        'all_JSONL_responses_equal_READY':True,'initialize_ack_emitted':False,
        'guard_feedback_ranks':[0,1],'guard_feedback_hit_counts':[14,13],
        'captured_actions_equal_local_READY':[row['action']==action for row,action in zip(history,baseline['actions'])],
        'variants':{name:{key:value for key,value in v.items() if key!='responses'} for name,v in variants.items()},
        'platform':platform.platform(),'python':sys.version,'numpy_version':np.__version__,
        'snapshot_reconstruction':{
            'verbatim_capture_fields':['now_utc','observe_action_index','last_result','new_messages'],
            'public_derived_fields':['survey_end_utc from initialize','latest bulletin/forecast from prior messages',
                                     'running_total from six-decimal public max-score ledger','empty active_requests before any published request'],
            'official_static_envelope_constructors':True,'identical_test_wallclock_seconds':900,
            'limitations':['Captured public_history omits full snapshots; reconstructed unused public fields and fixed clock are documented.',
                           'Captured feedback is from the fixed original public trajectory, not a fresh environment response.',
                           'Local Darwin/NumPy prefix parity does not certify Linux NumPy2.2.6 full-season parity.'],
        },
        'reads_truth':False,'reads_teacher_labels':False,'seasons_launched':0,'ssh_calls':0,'docker_calls':0,
    }
    (HERE/'public_initialize_integration.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({key:result[key] for key in ['schema','passed','decisions_per_variant',
        'first_action_and_two_feedback_actions_equal_READY','captured_actions_equal_local_READY','numpy_version','seasons_launched']}))


if __name__=='__main__':main()
