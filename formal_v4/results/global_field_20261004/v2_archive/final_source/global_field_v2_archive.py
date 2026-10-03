"""Freeze the rejected v2 experiment and hash every artifact once."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE / 'results/global_field_20261004'
SOURCE = ROOT / 'v2'
DEST = ROOT / 'v2_archive'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

if __name__ == '__main__':
    if DEST.exists():
        raise RuntimeError('The v2 archive already exists; do not mutate it.')
    lock = json.loads((SOURCE / 'source_lock.json').read_text())
    observed = {str(p.relative_to(SOURCE / 'participant')): sha(p)
                for p in (SOURCE / 'participant').rglob('*') if p.is_file()}
    assert lock == observed, 'participant changed after lock'
    shutil.copytree(SOURCE, DEST)
    additional = DEST / 'final_source'
    additional.mkdir()
    for name in ('global_field_v2_DESIGN_ZH.md', 'global_field_full_result_report.py',
                 'global_field_v2_archive.py', 'global_field_v2_verify.py'):
        shutil.copy2(BASE / 'research' / name, additional / name)
    verification = DEST / 'verification'
    verification.mkdir()
    shutil.copy2(ROOT / 'v2_verify_actions.json', verification / 'v2_verify_actions.json')
    fixture_path = BASE / 'results/objective_graph_20261004'
    for name in ('prefix_L1_30.npz', 'prefix_L1_104.npz', 'prefix_L2_12.npz',
                 'prefix_L2_25.npz', 'prefix_L2_87.npz'):
        shutil.copy2(fixture_path / name, verification / name)
    files = {str(p.relative_to(DEST)): {'sha256': sha(p), 'bytes': p.stat().st_size}
             for p in sorted(DEST.rglob('*')) if p.is_file()}
    manifest = {
        'schema': 'global-field-v2-rejected-archive-v1',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'archive': str(DEST), 'decision': 'reject_v2_no_score_improvement',
        'immutable': True, 'file_count': len(files), 'files': files,
        'source_lock_sha256': sha(SOURCE / 'source_lock.json'),
        'cpp_sha256': sha(BASE / 'research/global_field_search_v2.cpp'),
        'participant_lock_rechecked': True,
        'offline_truth_fixtures_outside_participant': True,
        'scores': {'control_L1': 6289.992617, 'search_L1': 6246.329317,
                   'ready_native_L1': 6362.021539},
        'full_seasons': ['control_L1', 'search_L1', 'ready_native_L1'],
        'L2_not_launched': True,
        'pid': 554406,
        'start_utc': '2026-10-03T16:45:00.744447+00:00',
        'finish_utc_file_mtime': '2026-10-03T16:55:17.871082466+00:00',
        'resource_limits': {'cpus': 2, 'memory_bytes': 2147483648, 'wallclock_seconds': 900,
                            'network': False, 'readonly_root': True},
    }
    output = ROOT / 'v2_archive_manifest.json'
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'manifest': str(output), 'manifest_sha256': sha(output),
                      'file_count': len(files)}, indent=2))
