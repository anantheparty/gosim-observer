"""Remaining frozen RequestCache terminal checks, reusing the completed L3 runner."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    for key in ('experiment', 'kit', 'dependencies'):
        parser.add_argument('--' + key, required=True, type=Path)
    args = parser.parse_args()
    for key in ('experiment', 'kit', 'dependencies'):
        setattr(args, key, getattr(args, key).resolve())
    harness = args.experiment / 'run_request_terminal_pair.py'
    spec = importlib.util.spec_from_file_location('frozen_l3_runner', harness)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args.lock = json.loads((args.experiment / 'source_lock.json').read_text())
    work = [('terminal', 'L1'), ('terminal', 'L2'), ('control', 'L4'), ('terminal', 'L4')]
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(module.run, args, variant, card, slot) for slot, (variant, card) in enumerate(work)]
        for future in as_completed(futures):
            results.append(future.result())
            summary = {'schema': 'actual-request-terminal-remaining-comparison-v1', 'expected': 4, 'completed': len(results), 'results': results, 'historical_control_L1_L2': 'request_geometry_integration_20261004/seasons/control'}
            (args.experiment / 'remaining_progress.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
