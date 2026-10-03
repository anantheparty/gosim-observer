"""Audit the locked public-constraint protocol pair against the READY native."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/band_identification_20261004/stage2'
REF=ROOT/'results/geometry_native_20261003/protocol_gate_retry/L2'
def read(p):return json.loads(p.read_text())
def rows(p):return [json.loads(s) for s in p.read_text().splitlines() if s.strip()]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    if not (OUT/'protocol_summary.json').exists():
        print('Protocol summary not complete.');return
    summary=read(OUT/'protocol_summary.json');by={r['mode']:r for r in summary}
    ctrl=OUT/'protocol/control/L2';variant=OUT/'protocol/constraint/L2'
    reference_actions=rows(REF/'actions.jsonl');control_actions=rows(ctrl/'actions.jsonl');variant_actions=rows(variant/'actions.jsonl')
    prefix=0
    for a,b in zip(control_actions,variant_actions):
        if a!=b:break
        prefix+=1
    lock=read(OUT/'source_lock.json');part=OUT/'participant'
    source_unchanged={str(p.relative_to(part)):sha(p) for p in part.rglob('*') if p.is_file()}==lock['files']
    reference=read(REF/'score_report.json');control=read(ctrl/'score_report.json');changed=read(variant/'score_report.json')
    checks=dict(control_actions_match_READY=control_actions==reference_actions,
                control_score_match_READY=Decimal(str(control['total']))==Decimal('6823.661561'),
                source_lock_unchanged=source_unchanged,
                both_protocol_complete=all(r['protocol_passed'] for r in summary),
                both_under_900_seconds=all(r['accounted_seconds']<900 for r in summary),
                no_traceback=not any(r['traceback'] for r in summary),
                no_participant_truth_mount=all(not r['participant_has_truth_mount'] for r in summary))
    delta=lambda a,b:float(Decimal(str(a))-Decimal(str(b)))
    gain=delta(changed['total'],control['total'])
    result=dict(checks=checks,all_gates_passed=all(checks.values()),control_total=control['total'],constraint_total=changed['total'],
                total_delta=gain,component_deltas={k:delta(changed['components'][k],v) for k,v in control['components'].items()},
                control_counts=control['counts'],constraint_counts=changed['counts'],
                common_prefix_action_count=prefix,common_prefix_observe_count=sum(a['action']=='observe' for a in control_actions[:prefix]),
                first_control_difference=control_actions[prefix] if prefix<len(control_actions) else None,
                first_constraint_difference=variant_actions[prefix] if prefix<len(variant_actions) else None,
                control_constraint_events=by['control']['public_constraint_logs'],
                constraint_constraint_events=by['constraint']['public_constraint_logs'],
                controlled_score_scope='complete supplied local L2 season under pinned Linux protocol',
                source_lock_sha256=sha(OUT/'source_lock.json'),
                decision='promising_L2_only_requires_heldout_validation' if all(checks.values()) and gain>0 else 'reject_no_parameter_rescue',
                output_sha256={f'{mode}/{name}':sha(OUT/'protocol'/mode/'L2'/name) for mode in ('control','constraint')
                               for name in ('actions.jsonl','decisions.csv','observations.csv','score_report.json','workflow_result.json','agent.log','gate_result.json')})
    (OUT/'pair_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
