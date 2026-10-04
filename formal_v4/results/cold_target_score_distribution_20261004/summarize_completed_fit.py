"""Post-fit reporting only. Does not choose a new model or read test worlds."""
import hashlib
import json
from pathlib import Path
import numpy as np
from finite_evaluator import bootstrap_pair

root = Path(__file__).resolve().parent
fit = root / 'gpu_fit'
selection = json.loads((fit / 'SELECTION_RESULT.json').read_text())
receipt = json.loads((root / 'GPU_PROCESS_RECEIPT.json').read_text())
assert receipt['raw_process_exit_code'] == 0
summary = dict(selection=selection, raw_process_exit_code=0, architectures={})
for mode, chosen in selection['best_by_architecture'].items():
    record = json.loads((fit / mode / ('epoch_%02d_evaluation.json' % chosen['epoch'])).read_text())
    rows = record['validation']['worlds']
    learned = [r['actual_rate'] for r in rows]
    point = [r['point_rate'] for r in rows]
    assert len(list((fit / mode).glob('epoch_*.npz'))) == 12
    summary['architectures'][mode] = dict(
        epoch=chosen['epoch'], temperature=chosen['temperature'],
        worldmean_actual_rate=float(np.mean(learned)),
        worldmean_original_point_rate=float(np.mean(point)),
        paired_vs_original_point=bootstrap_pair(learned, point),
        worldmean_finite_oracle_rate=float(np.mean([r['finite_oracle_rate'] for r in rows])),
        worldmean_finite_oracle_regret=float(np.mean([r['finite_oracle_regret'] for r in rows])),
        world_rates=[{k:r[k] for k in ('seed','actual_rate','point_rate','delta_point','finite_oracle_regret')} for r in rows])
summary['test_world_count'] = len(list((root / 'datasets' / 'test').glob('*.npz')))
summary['source_freeze_sha256'] = hashlib.sha256((root / 'SOURCE_FREEZE.json').read_bytes()).hexdigest()
summary['decision'] = ('Eligible for one selected-model fresh finite test under the frozen lock'
                       if selection['validation_gate']['positive_launch_gate']
                       else 'Rejected at validation: test remains ungenerated; no production model adopted')
summary['scope'] = 'Finite additive science/actualseconds only; this does not estimate season score, REQ/Jain, or participant runtime performance'
(root / 'COMPLETED_FIT_SUMMARY.json').write_text(json.dumps(summary,indent=2) + '\n')
print(json.dumps({k:v for k,v in summary.items() if k!='selection'},indent=2))
