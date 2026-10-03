#!/usr/bin/env python3
"""Build an isolated CPU-only participant tree from the locked research source."""
import hashlib
import json
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parents[1]
FROZEN = BASE / 'runs/cold_neural_value_20261003/production_frozen'
DEST = BASE / 'results/required_allocation_20261003/participant'


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    names = ['agent.py', 'policy.py', 'policy_config.json',
             'research/cpu_phase_candidates.py', 'research/spatial_candidates.py',
             'research/feedback_model.py', 'research/belief_clock.py',
             'research/efficiency_bounds.py', 'research/remote_budget.py',
             'research/geometry.py', 'research/pointing_calibration.py']
    for name in names:
        target = DEST / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FROZEN / name, target)
    for name in ['required_allocation_calendar.py', 'agent_required_allocation.py']:
        shutil.copy2(BASE / 'research' / name, DEST / 'research' / name)
    (DEST / 'research/__init__.py').write_text('')
    (DEST / 'requirements.txt').write_text('numpy==2.2.6\n')
    manifest = {str(p.relative_to(DEST)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(DEST.rglob('*')) if p.is_file()}
    (DEST.parent / 'participant_manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(dict(directory=str(DEST), files=len(manifest), no_truth_or_rpc_files=True)))


if __name__ == '__main__':
    main()
