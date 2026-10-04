"""Create a review lock and a future matched-run plan; launches no runs."""
from __future__ import annotations
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
KIT = ROOT/'formal_v4/upstream/gosim-observer-examples'
REPORT = ROOT/'formal_v4/research/request_terminal_adaptation_20261004.md'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def main():
    preservation = json.loads((HERE/'package_preservation.json').read_text())
    assert tree(HERE/'control_package') == preservation['control']
    assert tree(HERE/'full_wrapper_package') == preservation['full_wrapper']
    assert json.loads((HERE/'public_checks.json').read_text())['passed'] is True
    assert json.loads((HERE/'official_short_checks.json').read_text())['passed'] is True
    old = ROOT/'formal_v4/results/cold_policy_breakthrough_20261004/terminal_report_agent.py'
    (HERE/'terminal_report_derivation.diff').write_text(''.join(difflib.unified_diff(
        old.read_text().splitlines(True), (HERE/'terminal_report_agent.py').read_text().splitlines(True),
        fromfile='reviewed_native_terminal_report_agent.py', tofile='request_terminal_report_agent.py')))
    plan = {
        'schema': 'request-terminal-future-matched-L3-plan-v1', 'card': 'L3',
        'status': 'prepared_only_not_started', 'owner': 'root must explicitly run this next step',
        'variants': {
            'control': {'package': str(HERE/'control_package'),
                        'entry': ['python3', '-u', '-m', 'research.agent_request_exact_cache']},
            'intervention': {'package': str(HERE/'full_wrapper_package'),
                             'entry': ['python3', '-u', 'wrapper.py'],
                             'environment': {'REQUEST_TERMINAL_REPORT_ENABLE': '1',
                                             'REQUEST_TERMINAL_REPORT_MIN_WALLCLOCK': '10'}}},
        'resources_each': {'cpus': 2, 'memory_mib': 2048, 'global_wallclock_seconds': 900,
                           'network': 'none', 'participant_mounts': ['readonly locked package',
                                                                   'readonly numpy==2.2.6 dependencies'],
                           'truth_mount': False},
        'container_image': 'python@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016',
        'runner': str(KIT/'runner/run_local.py'),
        'required_preflight': ['verify this source lock and both package ZIP hashes',
                              'same official L3 card/runner/scorer/dependencies/container image',
                              'disjoint two-core pinning per variant and simultaneous start',
                              'fresh output directories; preserve raw failures and timeout outcomes'],
        'required_result_gates': [
            'both complete survey_complete within 900s; no ignored response/OOM/traceback',
            'source trees remain locked before/after; store every output hash',
            'control is this 29-member RequestCache package, not a native-policy old score',
            'full wrapper emits at most one extra report, immediately before control final action',
            'after deleting only that inserted report all action objects equal matched control',
            'all original decision fields except sequential decision_id equal after deletion',
            'UTC/rank unchanged across report; final observe rank and loss plan equal',
            'public false quota/consecutive limit/Jain/remaining budget gate satisfied',
            'report outcome agrees between public report_result and actor summary',
            'false outcome has score_delta=0 and every score component/total equal',
            'correct outcome reward positive; required/request contributions do not decrease',
            'actual Jain change respects public bound and total delta meets conditional lower bound',
            'if zero insertions report gate reason and treat fitness gain as unmeasured/unavailable'],
        'no_native_score_or_FOUR_CARD_ACTUAL_RESULT_used_as_RequestCache_evidence': True,
        'no_L4_read_or_run_planned': True,
        'adoption_rule': 'Only a passed matched actual L3 can establish this RequestCache gain; do not assume +100.'}
    (HERE/'MATCHED_L3_PLAN.json').write_text(json.dumps(plan, indent=2, sort_keys=True)+'\n')
    official = [KIT/'runner/challenge'/name for name in
                ('v4_runner.py', 'v4_scorer.py', 'v4_workflow.py', 'v4_config_check.py', 'v4_fiber_map.py')]
    official.append(KIT/'python/agent_core/protocol.py')
    lock = {'schema': 'request-terminal-review-source-lock-v1',
            'frozen_utc': datetime.now(timezone.utc).isoformat(),
            'baseline_zip_sha256': preservation['baseline_zip_sha256'],
            'original_control_source_tree': preservation['baseline_members'],
            'control': tree(HERE/'control_package'), 'full_wrapper': tree(HERE/'full_wrapper_package'),
            'package_zip_sha256': {name: sha(HERE/name) for name in
                                   ('control_package.zip', 'full_wrapper_package.zip')},
            'upstream_terminal_wrapper_sha256': sha(old),
            'official_sources': {str(p.relative_to(ROOT)): sha(p) for p in official},
            'report_sha256': sha(REPORT),
            'public_entry_input_sha256': {card: sha(HERE/'public_entry'/card/'public_input.jsonl')
                                         for card in ('L1', 'L2')},
            'actual_score_delta_measured': False, 'whole_seasons_launched': 0,
            'participant_weather_truth_reads': False,
            'review_artifact_sha256': {name: value for name, value in tree(HERE).items()
                                       if name != 'source_lock.json'}}
    (HERE/'source_lock.json').write_text(json.dumps(lock, indent=2, sort_keys=True)+'\n')
    print(json.dumps({'frozen': True, 'source_lock_sha256': sha(HERE/'source_lock.json'),
                      'full_wrapper_zip_sha256': sha(HERE/'full_wrapper_package.zip')}))


if __name__ == '__main__':
    main()
