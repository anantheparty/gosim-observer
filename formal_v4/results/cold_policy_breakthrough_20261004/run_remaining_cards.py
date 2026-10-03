#!/usr/bin/env python3
"""Plan, or explicitly execute, one locked L1/L2/L4 terminal-report season.

Reuse completed READY references and the frozen successful L3 verifier/lifecycle.
This tool launches no control run; the actor receives only the same frozen
package and dependencies.  No teacher target-label file is used.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
L3_HARNESS_SHA256='0990cc8c4d00dab936468d9d5d921c5cca6990a86cfa5f235b914696c1557002'
PACKAGE_LOCK_SHA256='9d488dda33db7448106d0b32fd25c7ab500e037ae9c3fd44e513fdd61ae7bc97'
OFFICIAL_SOURCE_LOCK_SHA256='eda4463d30fe79b7706b323d1024726fc0a379314f4497c47c7ec0005ecacd72'
CPUSETS={'L1':'20,21','L2':'22,23','L4':'16,17'}
REFERENCE_BINDINGS={'L1': {'reference_relative_path': 'protocol_gate_remaining/L1',
        'remote_reference': '/tmp/geometry_native_20261003/results/geometry_native_20261003/protocol_gate_remaining/L1',
        'files': {'actions.jsonl': '437747a91f601ed3ca8f401e1adc2bd98307310860b4bd854918b4fb6b3aa230',
                  'score_report.json': '4340dcc7243c8fe9b79891b78bf5a6dcfe57bc6fc278aec338082109093dda71',
                  'workflow_result.json': '50801d142cc0401be76f5876752e27543697baa9cfc5f0df5ba46cefc354bd90',
                  'decisions.csv': '752d0a0a7ae3dd2dcd473247fe565148c8fe622565e95629a786200ee9884d50',
                  'messages.jsonl': 'c4140a46ff05b2bb431408e693515dac3db2189b96932a8f876f0fbea0cec0dd',
                  'gate_result.json': 'e8852207f7d21217cac68609aad9c9ae536327c533c2d07eb40c1b25f2e1d636'},
        'total': 6362.021539,
        'components': {'observation_request_reward': 200.0,
                       'report_settlement': 100.0,
                       'required_penalty': -100.0,
                       'sum_best_scores': 6162.33341,
                       'uniformity_penalty': -0.311871},
        'parity_receipt_sha256': 'aefe9795dee297c846185551e2ff53a70398c2cbd41a4690acbbf046c7d834c8'},
 'L2': {'reference_relative_path': 'protocol_gate_retry/L2',
        'remote_reference': '/tmp/geometry_native_20261003/results/geometry_native_20261003/protocol_gate_retry/L2',
        'files': {'actions.jsonl': 'c4c37d1a588d8f8b088eb07fd0e054832b65a096ee57d7bd7b0792ce5189ba0c',
                  'score_report.json': 'dd1bbb338ca5aa617a6e0724cc07cd17d694df31f2fc6c87606b4b37ad224257',
                  'workflow_result.json': 'c7e8534e47dc89bb1cc8988638806c1be256983af4903e03d07df614daaffc1d',
                  'decisions.csv': 'd7396b690d9791ba8570bc891579c0f0823e8fa7b5b57a6dbe7d1cd8037683e0',
                  'messages.jsonl': '4ed744d3a21a8f8c7493c9f79c7fa83b4455cd1327f75767ef6b8e5865e0aaca',
                  'gate_result.json': '3a177a1dea6c470475a0a2de48340ac4085adb394280e26d64959706e2e8aa53'},
        'total': 6823.661561,
        'components': {'observation_request_reward': 200.0,
                       'report_settlement': 100.0,
                       'required_penalty': -150.0,
                       'sum_best_scores': 6674.649933,
                       'uniformity_penalty': -0.988373},
        'parity_receipt_sha256': 'b9d3558de11da719ea3843f4a3cdd8bd5082ce24a384092642f46c98462d9b99'},
 'L4': {'reference_relative_path': 'protocol_gate_retry/L4',
        'remote_reference': '/tmp/geometry_native_20261003/results/geometry_native_20261003/protocol_gate_retry/L4',
        'files': {'actions.jsonl': 'd95fe09f5232fc2cd52ecc93d3d519589c46b410b05c3de35fa55fa6318fcb01',
                  'score_report.json': '6f80597b9f42dd9d91ce86598a9659131a99bd918bb76abcb4eb04c7706be6ff',
                  'workflow_result.json': 'e4baf9169b0fa7be9415de5a979185e18d0bb2cd2a05a4cf73a5993ead761c1a',
                  'decisions.csv': 'ccfcd6a36878b3ec6553b0d512fc4806c66d66e533d67cf3df31b396643e6d15',
                  'messages.jsonl': '8d62f896b9b4685172716846c323a86566c98cb6e29f22a19c6d685bafa8e3b3',
                  'gate_result.json': '908e69bb9b128c040586aedfacbfa5dbd883b69db8c3cc9f41e7f913783fd7c9'},
        'total': 5974.281941,
        'components': {'observation_request_reward': 200.0,
                       'report_settlement': 100.0,
                       'required_penalty': -100.0,
                       'sum_best_scores': 5777.717412,
                       'uniformity_penalty': -3.435472},
        'parity_receipt_sha256': '2f90814551c814d9383623b4161848888d59ebc2120275c13c4deab013106f93'}}


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_frozen_harness(path):
    if digest(path)!=L3_HARNESS_SHA256:raise ValueError('Frozen successful L3 harness SHA differs')
    spec=importlib.util.spec_from_file_location('frozen_terminal_L3_harness',path)
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
    return base


def require(condition,message):
    if not condition:raise ValueError(message)


def review_reference(base,card,reference,parity_receipt,native_files):
    binding=REFERENCE_BINDINGS[card]
    for name,expected in binding['files'].items():base.checked_hash(reference/name,expected)
    gate=base.read_json(reference/'gate_result.json')
    score=base.read_json(reference/'score_report.json')
    flow=base.read_json(reference/'workflow_result.json')
    actions=base.read_jsonl(reference/'actions.jsonl')
    rows=base.read_csv(reference/'decisions.csv')
    # The historical gate has no schema and passed=false because its Mac/Phase
    # expected score differs from this completed Linux READY result.  Preserve
    # it verbatim and independently require real same-source protocol evidence.
    require('schema' not in gate and gate.get('passed') is False and gate.get('exact_score_match') is False,
            'Unexpected historical READY gate structure/status')
    require(gate.get('card')==card and gate.get('source_sha256')==native_files,
            'Original READY receipt does not bind the exact 20 native bytes')
    require(gate.get('exit_code')==0 and gate.get('termination')=='survey_complete'
            and gate.get('traceback_in_agent_log') is False
            and gate.get('participant_has_card_truth_mount') is False,
            'Original READY reference failed protocol or actor input separation')
    require(gate.get('container_image')==base.IMAGE,'Original READY image differs')
    agent_argv=__import__('shlex').split(gate['command'][gate['command'].index('--agent')+1])
    require(agent_argv[-4:]==['python3','-u','-m','research.agent_geometry_native']
            and agent_argv[agent_argv.index('--cpus')+1]=='2'
            and agent_argv[agent_argv.index('--memory')+1]=='2048m'
            and agent_argv[agent_argv.index('--network')+1]=='none'
            and agent_argv.count('--mount')==2
            and all('readonly' in agent_argv[i+1] for i,v in enumerate(agent_argv) if v=='--mount'),
            'Original READY receipt command differs from native 2CPU/2GiB isolated entry')
    require(score.get('scenario')==flow.get('scenario')=='v4-'+card.lower()
            and flow.get('schema_version')=='v4-workflow-result-v1'
            and score.get('schema_version')=='v4-score-report-v1'
            and flow.get('protocol_version')=='participant-agent-protocol-v4'
            and flow.get('termination_reason')=='survey_complete'
            and flow.get('ignored_in_flight_response') is False
            and flow.get('global_wallclock_seconds')==900
            and 0<=flow.get('accounted_wallclock_seconds',-1)<=900,
            'Reference official workflow is incomplete or over budget')
    require(flow.get('score_report')==score and score['total']==binding['total']==gate.get('observed_score')
            and score['components']==binding['components']==gate.get('components')
            and gate.get('counts')==score['counts'],'Original reference score/receipt inconsistent')
    require(flow.get('decision_requests')==len(actions)
            and flow.get('committed_action_count')==len(rows)==score['counts']['decisions']
            and sum(row['action']=='observe' for row in rows)==score['counts']['observe_actions'],
            'Reference action/decision count inconsistent')
    require(all(gate['output_sha256'].get(name)==binding['files'][name]
                for name in ['actions.jsonl','score_report.json','workflow_result.json','decisions.csv']),
            'Historical READY receipt output hashes differ')
    require(score['sha256']['decisions']==binding['files']['decisions.csv']
            and score['sha256']['messages']==binding['files']['messages.jsonl']
            and score['sha256']['observations']==gate['output_sha256']['observations.csv'],
            'Official score output hashes differ')
    # Only receipt, actions and official score are consulted in this directory;
    # no target/terminal label or observation-factor CSV is read.
    base.checked_hash(parity_receipt,binding['parity_receipt_sha256'])
    natural=base.read_json(parity_receipt)
    require(natural.get('phase')=='natural_control' and natural.get('case')=='control'
            and natural.get('card')==card and natural.get('rank')==64
            and natural.get('exit_code')==0 and natural.get('termination')=='survey_complete'
            and natural.get('traceback') is False and natural.get('participant_has_truth_mount') is False
            and natural.get('source_lock_sha256')==OFFICIAL_SOURCE_LOCK_SHA256
            and all(natural.get(key) is True for key in ['protocol_passed','ready_score_match',
                'ready_all_actions_match','ready_score_components_match','source_unchanged_after'])
            and natural.get('total')==score['total'] and natural.get('components')==score['components'],
            'Natural-control receipt lacks actual READY parity proof')
    for name in ['actions.jsonl','score_report.json']:
        base.checked_hash(parity_receipt.parent/name,binding['files'][name])
    return {'card':card,'complete_same_source_reference_valid':True,'original_gate_passed':gate['passed'],
            'original_exact_score_match':gate['exact_score_match'],'original_expected_score':gate['expected_score'],
            'actual_reference_total':score['total'],'actual_reference_components':score['components'],
            'original_READY_source_files':20,'native_actions':len(actions),'committed_decisions':len(rows),
            'observe_actions':score['counts']['observe_actions'],
            'accounted_seconds':flow['accounted_wallclock_seconds'],
            'cross_receipt_READY_actions_and_score_bytes_equal':True,
            'cross_receipt_sha256':binding['parity_receipt_sha256'],'labels_read':False}


def validate_options(args):
    require(args.card in CPUSETS,'Only L1/L2/L4 are supported; L3 is frozen')
    require(args.cpuset==CPUSETS[args.card],'This card freezes its suggested CPU pair at '+CPUSETS[args.card])
    require(args.enabled==1,'This packet is intervention-only; reuse the completed control')
    if args.container_name:
        require(re.fullmatch('[a-z0-9][a-z0-9_.-]{0,100}',args.container_name),'Invalid container name')


def freeze_inputs(base,args,check_out=True):
    validate_options(args)
    for key in ['project','dependencies','kit','reference','parity_receipt','official_source_lock','l3_harness','out']:
        value=Path(getattr(args,key)).resolve()
        require(not any(c in str(value) for c in [',','\n','\r']),'Unsafe input path')
        setattr(args,key,value)
    if check_out:require(not args.out.exists(),'Output directory exists; never overwrite prior results')
    for source in [args.project,args.dependencies,args.kit,args.reference,args.parity_receipt.parent]:
        require(args.out!=source and source not in args.out.parents and args.out not in source.parents,
                'Output must not overlap any locked input tree')
    base.checked_hash(Path(__file__),args.harness_sha256)
    base.checked_hash(args.l3_harness,L3_HARNESS_SHA256)
    base.checked_hash(args.official_source_lock,OFFICIAL_SOURCE_LOCK_SHA256)
    base.checked_hash(args.project/'terminal_report_package_lock.json',PACKAGE_LOCK_SHA256)
    package=base.read_json(args.project/'terminal_report_package_lock.json')
    actual=base.tree(args.project)
    require(actual=={**package['files'],'terminal_report_package_lock.json':PACKAGE_LOCK_SHA256}
            and len(actual)==22 and package.get('wrapper_sha256')==base.WRAPPER_SHA256
            and package.get('native_release_files')==20 and package.get('default_enabled') is False
            and package.get('runtime_entry')==['python3','-u','/workspace/wrapper.py']
            and package.get('runtime_base_root')=='/workspace'
            and package.get('minimum_wallclock_seconds')==10
            and package.get('observer_project_bytes_preserved') is True,
            'Frozen successful L3 package bytes/contract changed')
    official=base.read_json(args.official_source_lock)
    native=official['ready_release']
    require(official.get('schema')=='policy-iteration-source-lock-v1'
            and official.get('all_ready_files_byte_identical') is True and len(native)==20
            and all(actual.get(name)==expected for name,expected in native.items()),
            'Package differs from original 20 READY files')
    for name,expected in official['official'].items():base.checked_hash(args.kit/name,expected)
    review=review_reference(base,args.card,args.reference,args.parity_receipt,native)
    metadata=args.dependencies/'numpy-2.2.6.dist-info/METADATA'
    require(metadata.is_file() and '\nVersion: 2.2.6\n' in '\n'+metadata.read_text(),
            'Existing pinned NumPy2.2.6 dependency bytes required')
    args.reference_actions_sha256=REFERENCE_BINDINGS[args.card]['files']['actions.jsonl']
    return {'harness_sha256':args.harness_sha256,'frozen_L3_harness_sha256':L3_HARNESS_SHA256,
            'package_lock_sha256':PACKAGE_LOCK_SHA256,'official_source_lock_sha256':OFFICIAL_SOURCE_LOCK_SHA256,
            'package':actual,'dependencies':base.tree(args.dependencies),'official_runner':base.tree(args.kit/'runner'),
            'official_card_input_opaque_hashes':base.tree(args.kit/'local-cards'/args.card),
            'reference':{name:base.sha(args.reference/name) for name in REFERENCE_BINDINGS[args.card]['files']},
            'parity_receipt':{'gate_result.json':base.sha(args.parity_receipt),
                **{name:base.sha(args.parity_receipt.parent/name) for name in ['actions.jsonl','score_report.json']}},
            'reference_review':review}


def command(base,args,name,owner):
    runner,container=base.command(args,name,owner)
    runner[runner.index('--card')+1]=str(args.kit/'local-cards'/args.card)
    return runner,container


def verify_outputs(base,args,code,timed_out,state,cleanup,unchanged):
    records=[]
    for line in (args.out/'agent.log').read_text(errors='replace').splitlines():
        try:value=json.loads(line)
        except ValueError:continue
        if isinstance(value,dict) and isinstance(value.get('terminal_report'),dict):records.append(value)
    inserted=records[-1]['terminal_report'].get('inserted_reports') if records else None
    require(type(inserted) is int and inserted in [0,1],'Only zero or one terminal insertion is permitted')
    # For the zero-insertion branch use the unchanged L3 control identity gates,
    # then require the actual enabled=true summary and all public output bytes.
    proxy=copy.copy(args);proxy.enabled=inserted
    result=base.verify_outputs(proxy,code,timed_out,state,cleanup,unchanged)
    result.update(schema='terminal-report-official-remaining-card-gate-v1',card=args.card,enabled=True)
    gates=result['gates'];terminal=result['terminal_report']
    gates['configuration_matches']=terminal.get('enabled') is True
    gates['zero_or_one_terminal_report']=inserted in [0,1]
    score=base.read_json(args.out/'score_report.json');reference=base.read_json(args.reference/'score_report.json')
    gates['expected_card_scenario']=score.get('scenario')==reference.get('scenario')=='v4-'+args.card.lower()
    if inserted==0:
        gates.update(no_terminal_events=terminal.get('events')==[],
            all_decision_bytes_identical=base.sha(args.out/'decisions.csv')==REFERENCE_BINDINGS[args.card]['files']['decisions.csv'],
            all_public_message_bytes_identical=base.sha(args.out/'messages.jsonl')==REFERENCE_BINDINGS[args.card]['files']['messages.jsonl'],
            all_official_score_fields_identical=score==reference)
    else:
        # Correct/false, original actions/decision rows/messages, time/rank,
        # invalidations and public net-gain certificate use the frozen L3 gates.
        detail=result.get('action_intervention_audit')
        gates['full_insertion_audit_present']=detail is not None
    result['passed']=all(gates.values())
    result['actual_terminal_insertions']=inserted
    result['reference_gate_historical_passed']=False
    result['reference_has_natural_control_READY_parity_receipt']=True
    result['no_control_season_rerun']=True
    return result


def execute(base,args,before,runner,name,owner):
    require(base.inspect(name) is None,'Existing container name; refusing restart')
    args.out.mkdir(parents=True)
    lock={'schema':'terminal-report-remaining-card-run-lock-v1','card':args.card,'inputs':before,
          'command':runner,'image':base.IMAGE,'cpuset':args.cpuset,'cpus':2,'memory_mib':2048,
          'wallclock_seconds':900,'enabled':True,'container_name':name,'owner_label':owner,
          'explicit_entry':'/workspace/wrapper.py','actor_truth_mount':False,'control_seasons_launched':0}
    (args.out/'run_source_lock.json').write_text(json.dumps(lock,indent=2)+'\n')
    begin=time.monotonic();code=-1;timed_out=False;state=None;cleanup={}
    try:
        with (args.out/'driver.log').open('w') as handle:
            try:code=subprocess.run(runner,stdout=handle,stderr=subprocess.STDOUT,timeout=990).returncode
            except subprocess.TimeoutExpired:code=-9;timed_out=True
    finally:
        try:cleanup,state=base.cleanup_owned(name,owner)
        except Exception as exc:cleanup={'name':name,'removed':False,'error':type(exc).__name__+':'+str(exc)[:300]}
    try:
        after=freeze_inputs(base,args,check_out=False)
        (args.out/'after_source_lock.json').write_text(json.dumps(after,indent=2)+'\n')
        result=verify_outputs(base,args,code,timed_out,state,cleanup,after==before)
    except Exception as exc:
        result={'schema':'terminal-report-official-remaining-card-gate-v1','card':args.card,'enabled':True,
                'passed':False,'audit_error':type(exc).__name__+':'+str(exc)[:500],
                'runner_exit_code':code,'runner_timed_out':timed_out,'container_state':state,'cleanup':cleanup}
    result.update(host_seconds=time.monotonic()-begin,harness_sha256=args.harness_sha256,
                  package_lock_sha256=PACKAGE_LOCK_SHA256,run_source_lock_sha256=base.sha(args.out/'run_source_lock.json'))
    (args.out/'gate_result.json').write_text(json.dumps(result,indent=2)+'\n')
    compact={key:result.get(key) for key in ['schema','card','enabled','passed','actual_terminal_insertions','total',
        'actual_full_season_total_delta','termination','accounted_seconds','runner_exit_code','runner_timed_out','audit_error']}
    (args.out/'summary.json').write_text(json.dumps(compact,indent=2)+'\n')
    print(json.dumps(compact))
    return 0 if result['passed'] else 2


def self_check(base):
    checks={}
    for card,pair in CPUSETS.items():
        args=argparse.Namespace(card=card,cpuset=pair,enabled=1,container_name=None,
             project=Path('/synthetic/package'),dependencies=Path('/synthetic/deps'),kit=Path('/synthetic/kit'),out=Path('/synthetic/new/'+card))
        validate_options(args);runner,argv=command(base,args,'synthetic-'+card.lower(),'synthetic-owner')
        checks[card+'_correct_card']=runner[runner.index('--card')+1].endswith('/local-cards/'+card)
        checks[card+'_correct_cpu_pair']=argv[argv.index('--cpuset-cpus')+1]==pair
        checks[card+'_frozen_actor_entry']=argv[-3:]==['python3','-u','/workspace/wrapper.py']
        checks[card+'_only_two_readonly_mounts']=argv.count('--mount')==2 and sum('readonly' in v for v in argv)==2
        checks[card+'_pinned_resources']=base.IMAGE in argv and argv[argv.index('--memory')+1]=='2048m' and argv[argv.index('--cpus')+1]=='2' and runner[runner.index('--wallclock')+1]=='900'
        checks[card+'_network_none_no_auto_remove']=argv[argv.index('--network')+1]=='none' and '--rm' not in argv
        bad=copy.copy(args);bad.cpuset='18,19'
        try:validate_options(bad)
        except ValueError:checks[card+'_reject_shared_L3_pair']=True
        else:checks[card+'_reject_shared_L3_pair']=False
    ref=[{'action':'observe','duration_seconds':60},{'action':'wait','until_utc':'2042-01-01T01:00:00Z'}]
    identity,_=base.action_parity(ref,ref,0,{})
    checks['zero_insert_identity_gate']=all(identity.values())
    bad,_=base.action_parity([ref[0],{'action':'finish'}],ref,0,{})
    checks['zero_insert_mutation_rejected']=not all(bad.values())
    # The one-insertion verifier is the exact already-tested successful L3 one.
    f={'event':'terminal_report_frozen','now_utc':'2042-01-01T00:59:00Z','observe_action_index':17,
       'frozen_action':ref[-1],'frozen_action_hash':base.canonical(ref[-1])}
    terminal={'events':[f,{'event':'terminal_report_result','now_utc':f['now_utc'],'observe_action_index':17},
        {'event':'terminal_report_frozen_action_released','frozen_action_hash':f['frozen_action_hash'],'actor_belief_update_suppressed':True}]}
    good,_=base.action_parity([ref[0],{'action':'report'},ref[1]],ref,1,terminal)
    checks['one_insert_strict_frozen_L3_gate']=all(good.values())
    require(all(checks.values()),'Synthetic remaining-card guard check failed')
    return {'schema':'terminal-report-remaining-card-small-checks-v1','passed':True,'checks':checks,
            'checks_passed':len(checks),'docker_calls':0,'ssh_calls':0,'seasons_launched':0,'teacher_labels_read':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--card',choices=tuple(CPUSETS))
    for name in ['project','dependencies','kit','reference','parity-receipt','official-source-lock','out']:
        parser.add_argument('--'+name,type=Path)
    parser.add_argument('--l3-harness',type=Path,default=HERE/'run_protocol.py')
    parser.add_argument('--harness-sha256')
    parser.add_argument('--cpuset')
    parser.add_argument('--container-name')
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--self-check',action='store_true')
    parser.add_argument('--review-reference-root',type=Path)
    parser.add_argument('--parity-root',type=Path)
    args=parser.parse_args()
    base=load_frozen_harness(args.l3_harness)
    if args.self_check:
        print(json.dumps(self_check(base)));return 0
    if args.review_reference_root:
        require(args.parity_root is not None,'--parity-root required for reference-only review')
        native=base.read_json(HERE/'NATIVE_READY_SOURCE_LOCK.json')['source_files']
        result={card:review_reference(base,card,args.review_reference_root/binding['reference_relative_path'],
            args.parity_root/card/'rank_0064/control/gate_result.json',native) for card,binding in REFERENCE_BINDINGS.items()}
        print(json.dumps({'schema':'terminal-report-remaining-card-reference-review-v1','cards':result,
            'docker_calls':0,'ssh_calls':0,'seasons_launched':0,'teacher_labels_read':False}));return 0
    required=['card','project','dependencies','kit','reference','parity_receipt','official_source_lock','out','harness_sha256']
    missing=[key for key in required if getattr(args,key) is None]
    if missing:parser.error('Required: '+', '.join('--'+key.replace('_','-') for key in missing))
    args.cpuset=args.cpuset or CPUSETS[args.card]
    args.enabled=1
    before=freeze_inputs(base,args)
    owner=hashlib.sha256(json.dumps({'card':args.card,'out':str(args.out),'cpuset':args.cpuset,'inputs':before},sort_keys=True).encode()).hexdigest()
    name=args.container_name or 'terminal-'+args.card.lower()+'-'+owner[:12]
    runner,container=command(base,args,name,owner)
    if not args.execute:
        print(json.dumps({'schema':'terminal-report-remaining-card-command-plan-v1','card':args.card,
            'execute':False,'command':runner,'container':container,'inputs':before,
            'actor_truth_mount':False,'control_seasons_launched':0,'seasons_launched':0}));return 0
    return execute(base,args,before,runner,name,owner)


if __name__=='__main__':raise SystemExit(main())
