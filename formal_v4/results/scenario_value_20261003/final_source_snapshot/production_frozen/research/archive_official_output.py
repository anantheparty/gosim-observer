"""Preserve downloaded official outputs and check their published hashes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

FILES = ('actions.jsonl', 'agent.log', 'decisions.csv', 'messages.jsonl',
         'observations.csv', 'score_report.json', 'workflow_result.json')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('zip', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--prior', type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(args.zip) as archive:
        contents = {}
        for filename in FILES:
            matches = [name for name in archive.namelist()
                       if name.rsplit('/', 1)[-1] == filename]
            if len(matches) != 1:
                raise ValueError(f'Expected exactly one {filename}')
            contents[filename] = archive.read(matches[0])
    secret_path = Path(__file__).resolve().parents[1] / 'runs/gpu_service/token'
    if secret_path.exists():
        secret = secret_path.read_bytes().strip()
        if secret and any(secret in data for data in contents.values()):
            raise ValueError('Private runtime credential matched; archive rejected')
    report = json.loads(contents['score_report.json'])
    workflow = json.loads(contents['workflow_result.json'])
    checks = {}
    for label, filename in [('decisions', 'decisions.csv'),
                            ('messages', 'messages.jsonl'),
                            ('observations', 'observations.csv')]:
        checks[label] = hashlib.sha256(contents[filename]).hexdigest() == report['sha256'][label]
    checks['workflow_report_equal'] = workflow['score_report'] == report
    if not all(checks.values()):
        raise ValueError(f'Official output hash check failed: {checks}')
    for filename, data in contents.items():
        path = args.out / filename
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'Existing archive differs: {path}')
    args.out.mkdir(parents=True, exist_ok=True)
    for filename, data in contents.items():
        path = args.out / filename
        path.write_bytes(data)
        path.chmod(0o644)
    manifest = {
        'schema': 'official-output-download-v1',
        'download_filename': args.zip.name,
        'download_sha256': hashlib.sha256(args.zip.read_bytes()).hexdigest(),
        'file_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()},
        'checks': checks, 'scenario': report['scenario'], 'total': report['total'],
        'components': report['components'], 'counts': report['counts'],
        'termination': report['termination'],
        'accounted_wallclock_seconds': workflow['accounted_wallclock_seconds'],
    }
    if args.prior:
        previous = json.loads((args.prior / 'score_report.json').read_bytes())
        previous_actions = (args.prior / 'actions.jsonl').read_bytes().splitlines()
        current_actions = contents['actions.jsonl'].splitlines()
        first = next((i for i, (a, b) in enumerate(zip(previous_actions, current_actions))
                      if json.loads(a) != json.loads(b)), None)
        if first is None and len(previous_actions) != len(current_actions):
            first = min(len(previous_actions), len(current_actions))
        manifest['comparison'] = {
            'prior_directory': args.prior.name, 'prior_total': previous['total'],
            'delta_total': report['total'] - previous['total'],
            'components_delta': {key: value - previous['components'][key]
                                 for key, value in report['components'].items()},
            'same_scenario_hash': report['sha256']['scenario'] == previous['sha256']['scenario'],
            'semantic_first_action_difference_zero_based': first,
            'prior_action_lines': len(previous_actions), 'current_action_lines': len(current_actions),
            'same_output_bytes': {name: (args.prior / name).read_bytes() == data
                                  for name, data in contents.items()},
        }
    (args.out / 'archive_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({key: manifest[key] for key in ('scenario', 'total', 'checks',
                     'termination', 'accounted_wallclock_seconds')}))
    if 'comparison' in manifest:
        print(json.dumps(manifest['comparison']))


if __name__ == '__main__':
    main()
