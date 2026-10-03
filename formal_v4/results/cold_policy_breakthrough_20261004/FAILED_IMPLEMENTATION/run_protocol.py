#!/usr/bin/env python3
"""Prepare/explicitly execute one locked official L3 terminal-report replay."""
from __future__ import annotations
import argparse
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

IMAGE='python@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016'
OWNER_LABEL='terminal_report_replay.owner'
WRAPPER_SHA256='297bec972e2611e1f1f6a4b4aa06f8cb363667e8c9712bd1eebd6f76b58c0278'
COMPONENTS={'sum_best_scores','required_penalty','uniformity_penalty','report_settlement','observation_request_reward'}
REFERENCE_FILES=('actions.jsonl','score_report.json','workflow_result.json','decisions.csv','messages.jsonl')


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def canonical(action):return hashlib.sha256(json.dumps(action,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def read_json(path):return json.loads(Path(path).read_text())
def read_jsonl(path):return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
def read_csv(path):
    with Path(path).open(newline='') as handle:return list(csv.DictReader(handle))


def tree(root):
    root=Path(root)
    if not root.is_dir():raise ValueError('Locked directory missing: '+str(root))
    files={}
    for p in sorted(root.rglob('*')):
        if '__pycache__' in p.parts:continue
        if p.is_symlink():raise ValueError('Locked symlink refused: '+str(p))
        if p.is_file():files[str(p.relative_to(root))]=sha(p)
    if not files:raise ValueError('Empty locked directory: '+str(root))
    return files


def checked_hash(path,expected):
    if not re.fullmatch('[0-9a-f]{64}',expected or '') or sha(path)!=expected:
        raise ValueError('Reviewed SHA256 mismatch: '+str(path))


def validate_options(args):
    if args.cpuset!='18,19':raise ValueError('This packet freezes cpuset at 18,19')
    if args.enabled not in (0,1):raise ValueError('Enabled must be 0 or 1')
    if args.container_name and not re.fullmatch('[a-z0-9][a-z0-9_.-]{0,100}',args.container_name):
        raise ValueError('Invalid container name')


def freeze_inputs(args):
    validate_options(args)
    for key in ('project','dependencies','kit','reference','teacher_source_lock','reference_gate','out'):
        value=getattr(args,key).resolve()
        if any(c in str(value) for c in (',','\n','\r')):raise ValueError('Unsafe mount/input path')
        setattr(args,key,value)
    if args.out.exists():raise ValueError('Output directory must not already exist')
    for source in (args.project,args.dependencies,args.kit,args.reference):
        if args.out==source or source in args.out.parents or args.out in source.parents:
            raise ValueError('Output must not overlap any locked input tree')
    checked_hash(Path(__file__).resolve(),args.harness_sha256)
    checked_hash(args.teacher_source_lock,args.teacher_source_lock_sha256)
    checked_hash(args.reference_gate,args.reference_gate_sha256)
    package_path=args.project/'terminal_report_package_lock.json'
    checked_hash(package_path,args.package_lock_sha256)
    package=read_json(package_path)
    if (package.get('schema')!='terminal-report-overlay-package-lock-v1'
        or package.get('native_release_files')!=20 or package.get('wrapper_sha256')!=WRAPPER_SHA256
        or package.get('runtime_entry')!=['python3','-u','/workspace/wrapper.py']
        or package.get('runtime_base_root')!='/workspace' or package.get('default_enabled') is not False
        or package.get('minimum_wallclock_seconds')!=10
        or package.get('observer_project_bytes_preserved') is not True
        or package.get('deployment_calibrated') is not False or package.get('cloud_deployment_authorized') is not False):
        raise ValueError('Package contract differs from reviewed terminal candidate')
    actual=tree(args.project)
    if actual!={**package['files'],'terminal_report_package_lock.json':args.package_lock_sha256}:
        raise ValueError('Package inventory/bytes changed')
    checked_hash(args.project/'wrapper.py',WRAPPER_SHA256)
    teacher=read_json(args.teacher_source_lock)
    if teacher.get('schema')!='policy-iteration-source-lock-v1' or teacher.get('all_ready_files_byte_identical') is not True:
        raise ValueError('Expected reviewed native READY source lock')
    if len(teacher['ready_release'])!=20 or any(actual.get(n)!=v for n,v in teacher['ready_release'].items()):
        raise ValueError('Package changed a native READY byte')
    for name,expected in teacher['official'].items():checked_hash(args.kit/name,expected)
    checked_hash(args.reference/'actions.jsonl',args.reference_actions_sha256)
    checked_hash(args.reference/'score_report.json',args.reference_score_sha256)
    gate=read_json(args.reference_gate)
    if (gate.get('schema')!='student-policy-official-L3-gate-v1' or gate.get('passed') is not True
        or gate.get('mode')!='control' or gate.get('selector')!='native_control'
        or not all(gate.get('reference_parity',{}).get(k) is True for k in ('actions_sha256_match','total_match','components_match'))
        or gate.get('output_sha256',{}).get('actions.jsonl')!=args.reference_actions_sha256
        or gate.get('output_sha256',{}).get('score_report.json')!=args.reference_score_sha256):
        raise ValueError('Reference lacks reviewed complete native-control parity evidence')
    score=read_json(args.reference/'score_report.json')
    flow=read_json(args.reference/'workflow_result.json')
    if score.get('components')!=gate.get('components') or score.get('total')!=gate.get('total'):
        raise ValueError('Reference score differs from complete control gate')
    if flow.get('termination_reason')!='survey_complete':raise ValueError('Reference season is incomplete')
    metadata=args.dependencies/'numpy-2.2.6.dist-info/METADATA'
    if not metadata.is_file() or '\nVersion: 2.2.6\n' not in '\n'+metadata.read_text():
        raise ValueError('Existing NumPy 2.2.6 dependency bytes required')
    return {'harness_sha256':args.harness_sha256,'teacher_source_lock_sha256':args.teacher_source_lock_sha256,
            'package_lock_sha256':args.package_lock_sha256,'reference_gate_sha256':args.reference_gate_sha256,
            'package':actual,'dependencies':tree(args.dependencies),'official_runner':tree(args.kit/'runner'),
            'official_L3_input_opaque_hashes':tree(args.kit/'local-cards/L3'),
            'reference':{n:sha(args.reference/n) for n in REFERENCE_FILES}}


def command(args,name,owner):
    env={'PYTHONPATH':'/deps','PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1',
         'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','GEOMETRY_NATIVE_PLANNER':'sweep',
         'TERMINAL_REPORT_BASE_ROOT':'/workspace','TERMINAL_REPORT_ENABLE':str(args.enabled),
         'TERMINAL_REPORT_MIN_WALLCLOCK':'10'}
    container=['docker','run','--pull=never','--interactive','--user','1000:1000',
        '--name',name,'--label',OWNER_LABEL+'='+owner,'--cpus','2','--cpuset-cpus',args.cpuset,
        '--memory','2048m','--memory-swap','2048m','--pids-limit','128','--cap-drop=ALL',
        '--security-opt=no-new-privileges','--ulimit','nofile=512:512','--ulimit','fsize=268435456:268435456',
        '--read-only','--tmpfs','/tmp:rw,nosuid,size=256m','--network','none','--log-driver','none',
        '--mount',f'type=bind,src={args.project},dst=/workspace,readonly',
        '--mount',f'type=bind,src={args.dependencies},dst=/deps,readonly','--workdir','/workspace']
    for k,v in env.items():container+=['--env',k+'='+v]
    container += [IMAGE,'python3','-u','/workspace/wrapper.py']
    runner=[sys.executable,str(args.kit/'runner/run_local.py'),'--card',str(args.kit/'local-cards/L3'),
            '--agent',shlex.join(container),'--agent-cwd',str(args.project),'--wallclock','900',
            '--out',str(args.out),'--quiet']
    return runner,container


def inspect(name):
    result=subprocess.run(['docker','container','inspect',name],capture_output=True,text=True,timeout=15)
    if result.returncode:
        if 'No such' in result.stderr:return None
        raise RuntimeError('Container inspection failed: '+result.stderr[:300])
    return json.loads(result.stdout)[0]


def cleanup_owned(name,owner):
    data=inspect(name)
    result={'name':name,'existed':data is not None,'removed':False,'owner_match':False}
    if data is None:return result,None
    result['owner_match']=data.get('Config',{}).get('Labels',{}).get(OWNER_LABEL)==owner
    result['container_id']=data.get('Id')
    state=data.get('State',{})
    if not result['owner_match']:
        result['error']='Owner label differs; container not removed'
        return result,state
    removed=subprocess.run(['docker','rm','--force',data['Id']],capture_output=True,text=True,timeout=30)
    result['removed']=removed.returncode==0
    result['exists_after_cleanup']=inspect(name) is not None
    if removed.returncode:result['error']=removed.stderr[:300]
    return result,state


def after_inputs(args):
    return {'harness_sha256':sha(Path(__file__).resolve()),'teacher_source_lock_sha256':sha(args.teacher_source_lock),
            'package_lock_sha256':sha(args.project/'terminal_report_package_lock.json'),
            'reference_gate_sha256':sha(args.reference_gate),'package':tree(args.project),
            'dependencies':tree(args.dependencies),'official_runner':tree(args.kit/'runner'),
            'official_L3_input_opaque_hashes':tree(args.kit/'local-cards/L3'),
            'reference':{n:sha(args.reference/n) for n in REFERENCE_FILES}}


def action_parity(actions,reference,enabled,terminal):
    if not enabled:
        return {'all_actions_equal_reference':actions==reference},None
    gates={'exactly_one_extra_action':len(actions)==len(reference)+1}
    pos=next((i for i,(a,b) in enumerate(zip(actions,reference)) if a!=b),None)
    if pos is None and len(actions)>len(reference):pos=len(reference)
    events=terminal.get('events',[])
    frozen=[r for r in events if r.get('event')=='terminal_report_frozen']
    released=[r for r in events if r.get('event')=='terminal_report_frozen_action_released']
    received=[r for r in events if r.get('event')=='terminal_report_result']
    gates.update(one_frozen_event=len(frozen)==1,one_released_event=len(released)==1,one_report_result_event=len(received)==1)
    if pos is None or pos>=len(reference) or len(frozen)!=1 or len(released)!=1 or len(received)!=1:
        gates['insertion_and_frozen_context_verified']=False
        return gates,None
    f,r,y=frozen[0],released[0],received[0]
    tail=actions[:pos]+actions[pos+1:]
    digest=lambda seq:hashlib.sha256(''.join(json.dumps(a,sort_keys=True,separators=(',',':'))+'\n' for a in seq).encode()).hexdigest()
    predecessor=canonical(actions[pos-1]) if pos else None
    reference_predecessor=canonical(reference[pos-1]) if pos else None
    gates.update(inserted_action_is_only_report=actions[pos]=={'action':'report'},
        all_actions_after_removing_that_report_equal_reference=tail==reference,
        report_immediately_precedes_final_reference_action=pos==len(reference)-1,
        entire_prefix_digest_matches_reference=digest(actions[:pos])==digest(reference[:pos]),
        predecessor_action_hash_matches_reference=predecessor==reference_predecessor,
        frozen_final_action_hash_matches_reference=f.get('frozen_action_hash')==canonical(reference[pos]),
        frozen_final_action_is_reference_and_actual=f.get('frozen_action')==reference[pos]==actions[pos+1],
        released_hash_matches_frozen=r.get('frozen_action_hash')==f.get('frozen_action_hash'),
        actor_report_belief_ingestion_suppressed=r.get('actor_belief_update_suppressed') is True,
        report_public_time_and_rank_unchanged=y.get('now_utc')==f.get('now_utc') and y.get('observe_action_index')==f.get('observe_action_index'))
    detail={'inserted_report_action_position':pos,'prefix_sha256':digest(actions[:pos]),
            'reference_prefix_sha256':digest(reference[:pos]),'predecessor_action_sha256':predecessor,
            'reference_predecessor_action_sha256':reference_predecessor,'frozen':f,'released':r,'report_result':y}
    return gates,detail


def verify_outputs(args,code,timed_out,state,cleanup,unchanged):
    flow=read_json(args.out/'workflow_result.json')
    score=read_json(args.out/'score_report.json')
    reference_score=read_json(args.reference/'score_report.json')
    actions=read_jsonl(args.out/'actions.jsonl');reference_actions=read_jsonl(args.reference/'actions.jsonl')
    log=(args.out/'agent.log').read_text(errors='replace')
    json_records=[]
    for line in log.splitlines():
        try:value=json.loads(line)
        except ValueError:continue
        if isinstance(value,dict):json_records.append(value)
    summaries=[r for r in json_records if isinstance(r.get('terminal_report'),dict)]
    summary=summaries[-1] if summaries else {}
    terminal=summary.get('terminal_report',{})
    components=score.get('components',{})
    finite=lambda x:isinstance(x,(int,float)) and math.isfinite(x)
    accounted=flow.get('accounted_wallclock_seconds')
    state=state or {}
    gates={'runner_exit_zero':code==0 and not timed_out,
        'container_exit_zero':state.get('Status')=='exited' and state.get('ExitCode')==0 and not state.get('OOMKilled') and not state.get('Error'),
        'owned_container_cleaned':cleanup.get('owner_match') is True and cleanup.get('removed') is True and cleanup.get('exists_after_cleanup') is False,
        'complete_official_protocol':flow.get('termination_reason')=='survey_complete' and flow.get('protocol_version')=='participant-agent-protocol-v4' and flow.get('ignored_in_flight_response') is False,
        'resource_budget':finite(accounted) and 0<=accounted<=900 and flow.get('global_wallclock_seconds')==900,
        'source_and_inputs_unchanged':unchanged,'no_traceback':'Traceback' not in log,'one_full_terminal_summary':len(summaries)==1,
        'configuration_matches':terminal.get('enabled') is bool(args.enabled),
        'actor_never_reads_truth_or_teacher':terminal.get('reads_truth') is False and terminal.get('reads_teacher_labels') is False,
        'finite_official_score':finite(score.get('total')) and set(components)==COMPONENTS and all(finite(v) for v in components.values()),
        'decision_bookkeeping':flow.get('decision_requests')==len(actions)==summary.get('decisions',-100)+terminal.get('inserted_reports',-200)}
    parity,detail=action_parity(actions,reference_actions,args.enabled,terminal)
    gates.update(parity)
    delta={k:float(Decimal(str(components[k]))-Decimal(str(reference_score['components'][k]))) for k in COMPONENTS} if set(components)==COMPONENTS else {}
    total_delta=float(Decimal(str(score['total']))-Decimal(str(reference_score['total']))) if finite(score.get('total')) else None
    if not args.enabled:
        gates.update(no_inserted_report=terminal.get('inserted_reports')==0,
                     all_action_bytes_identical=sha(args.out/'actions.jsonl')==args.reference_actions_sha256,
                     native_total_identical=score.get('total')==reference_score.get('total'),
                     native_components_identical=components==reference_score.get('components'))
    else:
        gates['exactly_one_terminal_report']=terminal.get('inserted_reports')==1
        log_events=[r for r in json_records if str(r.get('event','')).startswith('terminal_report_')]
        gates['terminal_events_match_full_summary']=log_events==terminal.get('events')
        if detail:
            f,y=detail['frozen'],detail['report_result']
            rows=read_csv(args.out/'decisions.csv');old_rows=read_csv(args.reference/'decisions.csv')
            i=next((i for i,(a,b) in enumerate(zip(rows,old_rows)) if a['action']!=b['action']),None)
            filtered=rows[:i]+rows[i+1:] if i is not None else []
            normalized=lambda rs:[{k:v for k,v in row.items() if k!='decision_id'} for row in rs]
            gates.update(one_extra_decision_row=len(rows)==len(old_rows)+1,
                all_original_decision_fields_equal=normalized(filtered)==normalized(old_rows),
                report_row_zero_duration=i is not None and rows[i]['action']=='report' and rows[i]['duration_seconds']=='0' and rows[i]['start_utc']==rows[i]['end_utc']==f['now_utc'],
                final_observe_rank_unchanged=score.get('counts',{}).get('observe_actions')==reference_score.get('counts',{}).get('observe_actions'),
                old_data_loss_invalidation_plan_unchanged=score.get('invalidations')==reference_score.get('invalidations'),
                public_gate_was_safe=f.get('free_reports_remaining',0)>0 and f.get('conditional_correct_gain_lower',-1)>=0 and f.get('wallclock_remaining',-1)>=10)
            messages=read_jsonl(args.out/'messages.jsonl');old_messages=read_jsonl(args.reference/'messages.jsonl')
            new_report_results=[m for m in messages if m.get('record_type')=='report_result' and m.get('issued_at_utc')==f['now_utc']]
            remaining_messages=[m for m in messages if not(m.get('record_type')=='report_result' and m.get('issued_at_utc')==f['now_utc'])]
            result=new_report_results[0] if len(new_report_results)==1 else {}
            gates.update(one_new_official_report_result=len(new_report_results)==1,
                other_public_messages_unchanged=remaining_messages==old_messages,
                official_and_actor_report_results_agree=result.get('correct')==y.get('correct')==terminal.get('terminal_correct') and result.get('score_delta')==y.get('score_delta')==terminal.get('terminal_score_delta'),
                report_component_matches_official_result=delta.get('report_settlement')==result.get('score_delta'),
                required_and_request_rewards_non_decreasing=delta.get('required_penalty',-1)>=-1e-6 and delta.get('observation_request_reward',-1)>=-1e-6)
            if result.get('correct') is True:
                gates.update(correct_repair_reward_positive=result.get('repaired') is True and result.get('score_delta',0)>0,
                    same_frozen_exposure_science_non_decreasing=delta.get('sum_best_scores',-1)>=-1e-6,
                    actual_total_meets_public_lower_bound=total_delta is not None and total_delta+2e-6>=f['conditional_correct_gain_lower'])
            else:
                gates.update(free_false_result_zero=result.get('correct') is False and result.get('score_delta')==0,
                             false_frozen_tail_total_and_components_identical=total_delta==0 and components==reference_score.get('components'))
    return {'schema':'terminal-report-official-L3-gate-v1','card':'L3','enabled':bool(args.enabled),
        'passed':all(gates.values()),'gates':gates,'total':score.get('total'),'components':components,
        'reference_total':reference_score.get('total'),'actual_full_season_total_delta':total_delta,'component_delta':delta,
        'uses_micro_packet_estimate_as_expected_score':False,'termination':flow.get('termination_reason'),
        'accounted_seconds':accounted,'agent_seconds':flow.get('agent_wallclock_seconds'),
        'runner_exit_code':code,'runner_timed_out':timed_out,'container_state':state,'cleanup':cleanup,
        'terminal_report':terminal,'participant_summary':summary,'action_intervention_audit':detail,
        'participant_truth_mount':False,'participant_input_mounts':['readonly package','readonly dependencies'],
        'output_sha256':{n:sha(args.out/n) for n in ('actions.jsonl','score_report.json','workflow_result.json','agent.log','decisions.csv','messages.jsonl')},
        'deployment_calibrated':False,'cloud_deployment_authorized':False}


def execute(args,before,runner,name,owner):
    if inspect(name) is not None:raise ValueError('Existing container name; refusing restart')
    args.out.mkdir(parents=True)
    lock={'schema':'terminal-report-official-L3-run-lock-v1','inputs':before,'command':runner,'image':IMAGE,
          'cpuset':args.cpuset,'cpus':2,'memory_mib':2048,'wallclock_seconds':900,'enabled':bool(args.enabled),
          'container_name':name,'owner_label':owner,'explicit_entry':'/workspace/wrapper.py',
          'actor_truth_mount':False,'reference_is_completed_student_native_control':True}
    (args.out/'run_source_lock.json').write_text(json.dumps(lock,indent=2)+'\n')
    begin=time.monotonic();code=-1;timed_out=False;state=None;cleanup={}
    try:
        with (args.out/'driver.log').open('w') as handle:
            try:code=subprocess.run(runner,stdout=handle,stderr=subprocess.STDOUT,timeout=990).returncode
            except subprocess.TimeoutExpired:code=-9;timed_out=True
    finally:
        try:cleanup,state=cleanup_owned(name,owner)
        except Exception as exc:cleanup={'name':name,'removed':False,'error':type(exc).__name__+':'+str(exc)[:300]}
    try:
        after=after_inputs(args)
        (args.out/'after_source_lock.json').write_text(json.dumps(after,indent=2)+'\n')
        result=verify_outputs(args,code,timed_out,state,cleanup,after==before)
    except Exception as exc:
        result={'schema':'terminal-report-official-L3-gate-v1','card':'L3','enabled':bool(args.enabled),'passed':False,
                'audit_error':type(exc).__name__+':'+str(exc)[:500],'runner_exit_code':code,'runner_timed_out':timed_out,
                'container_state':state,'cleanup':cleanup}
    result.update(host_seconds=time.monotonic()-begin,harness_sha256=args.harness_sha256,
                  package_lock_sha256=args.package_lock_sha256,run_source_lock_sha256=sha(args.out/'run_source_lock.json'))
    (args.out/'gate_result.json').write_text(json.dumps(result,indent=2)+'\n')
    compact={k:result.get(k) for k in ('schema','enabled','passed','total','actual_full_season_total_delta',
             'termination','accounted_seconds','runner_exit_code','runner_timed_out','audit_error')}
    (args.out/'summary.json').write_text(json.dumps(compact,indent=2)+'\n')
    print(json.dumps(compact))
    return 0 if result['passed'] else 2


def self_check():
    args=argparse.Namespace(cpuset='18,19',enabled=0,container_name=None,project=Path('/synthetic/package'),
                            dependencies=Path('/synthetic/deps'),kit=Path('/synthetic/kit'),out=Path('/synthetic/out'))
    validate_options(args)
    runner,argv=command(args,'synthetic-terminal-l3','fabricated-owner')
    checks={'explicit_wrapper_entry':argv[-3:]==['python3','-u','/workspace/wrapper.py'],
        'fixed_image':IMAGE in argv,'fixed_cpu_pair':argv[argv.index('--cpuset-cpus')+1]=='18,19',
        'two_cpus':argv[argv.index('--cpus')+1]=='2','memory_2gib':argv[argv.index('--memory')+1]=='2048m',
        'host_official_wallclock_900':runner[runner.index('--wallclock')+1]=='900',
        'network_none':argv[argv.index('--network')+1]=='none','retains_exit_evidence':'--rm' not in argv,
        'only_two_readonly_actor_mounts':argv.count('--mount')==2 and sum('readonly' in item for item in argv)==2,
        'actor_has_no_kit_reference_or_output_mount':not any('dst=/kit' in item or 'dst=/reference' in item or 'dst=/capture' in item for item in argv),
        'default_enabled_zero':'TERMINAL_REPORT_ENABLE=0' in argv,'correct_runtime_base_root':'TERMINAL_REPORT_BASE_ROOT=/workspace' in argv,
        'fixed_trigger_wallclock':'TERMINAL_REPORT_MIN_WALLCLOCK=10' in argv}
    args.enabled=1;validate_options(args);_,enabled=command(args,'synthetic-terminal-l3','fabricated-owner')
    checks['explicit_enabled_one']='TERMINAL_REPORT_ENABLE=1' in enabled
    for value in ('18,18','16,17','18,19,20'):
        args.cpuset=value
        try:validate_options(args)
        except ValueError:checks['reject_cpuset_'+value]=True
        else:checks['reject_cpuset_'+value]=False
    ref=[{'action':'observe','duration_seconds':60},{'action':'wait','until_utc':'2042-01-01T01:00:00Z'}]
    frozen={'event':'terminal_report_frozen','frozen_action':ref[-1],'frozen_action_hash':canonical(ref[-1]),
            'now_utc':'2042-01-01T00:59:00Z','observe_action_index':123}
    terminal={'events':[frozen,{'event':'terminal_report_result','now_utc':frozen['now_utc'],'observe_action_index':123,'correct':False},
                {'event':'terminal_report_frozen_action_released','frozen_action_hash':frozen['frozen_action_hash'],'actor_belief_update_suppressed':True}]}
    candidate=[ref[0],{'action':'report'},ref[1]]
    parity,detail=action_parity(candidate,ref,1,terminal)
    checks['synthetic_single_report_strict_action_parity']=all(parity.values()) and detail['predecessor_action_sha256']==canonical(ref[0])
    bad=[ref[0],{'action':'report'},{'action':'finish'}]
    parity,_=action_parity(bad,ref,1,terminal)
    checks['mutated_tail_rejected']=not all(parity.values())
    control,_=action_parity(ref,ref,0,{})
    checks['control_action_parity']=all(control.values())
    assert all(checks.values()),checks
    print(json.dumps({'schema':'terminal-report-harness-synthetic-check-v1','passed':True,'checks':checks,
                      'checks_passed':len(checks),'docker_calls':0,'seasons_launched':0,'teacher_labels_read':0}))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('project','dependencies','kit','reference','teacher-source-lock','reference-gate','out'):
        ap.add_argument('--'+name,type=Path)
    for name in ('harness-sha256','package-lock-sha256','teacher-source-lock-sha256','reference-actions-sha256','reference-score-sha256','reference-gate-sha256'):
        ap.add_argument('--'+name)
    ap.add_argument('--enabled',type=int,choices=(0,1),default=0)
    ap.add_argument('--cpuset',default='18,19')
    ap.add_argument('--container-name')
    ap.add_argument('--execute',action='store_true',help='Launch exactly one L3 season; omitted means a command plan only')
    ap.add_argument('--self-check',action='store_true',help='Small synthetic argv/action checks; zero Docker/season calls')
    args=ap.parse_args()
    if args.self_check:self_check();return 0
    required=('project','dependencies','kit','reference','teacher_source_lock','reference_gate','out','harness_sha256',
              'package_lock_sha256','teacher_source_lock_sha256','reference_actions_sha256','reference_score_sha256','reference_gate_sha256')
    missing=[n for n in required if getattr(args,n) is None]
    if missing:ap.error('Required: '+', '.join('--'+n.replace('_','-') for n in missing))
    before=freeze_inputs(args)
    owner=hashlib.sha256(json.dumps({'out':str(args.out),'inputs':before,'enabled':args.enabled},sort_keys=True).encode()).hexdigest()
    name=args.container_name or 'terminal-l3-'+str(args.enabled)+'-'+owner[:12]
    runner,container=command(args,name,owner)
    if not args.execute:
        print(json.dumps({'schema':'terminal-report-L3-command-plan-v1','execute':False,'command':runner,'container':container,
             'harness_sha256':args.harness_sha256,'package_lock_sha256':args.package_lock_sha256,
             'enabled':bool(args.enabled),'actor_truth_mount':False,'seasons_launched':0}))
        return 0
    return execute(args,before,runner,name,owner)


if __name__=='__main__':raise SystemExit(main())
