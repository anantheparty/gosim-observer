"""Independent official geometry oracle and CUDA-simulator pricing gate.

Run with NUMBA_ENABLE_CUDASIM=1; no device, network, or hidden truth is accessed.
The oracle enumerates all choices per glass using the official classifier.
"""
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
import numpy as np
from interval_column_pricing import altaz_vectors, price_cpu, price_cuda, recover_assignment


def main():
    if os.environ.get('NUMBA_ENABLE_CUDASIM') != '1':
        raise RuntimeError('gate requires CUDA simulator; hardware is reserved for the live evaluation')
    began = time.perf_counter()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root/'upstream/gosim-observer-examples/runner'))
    from challenge.v4_fiber_map import FiberGrid
    rng = np.random.default_rng(261003)
    centers = np.array([[55., 359.9], [55., 1.], [80., 270.], [35., 140.]])
    targets = np.array([[55.+da, (359.9+dz) % 360] for da, dz in rng.uniform(-5, 5, (18, 2))])
    targets = np.vstack((targets, [[80., 270.], [35., 140.], [10., 180.], [55., 359.9]]))
    vectors = altaz_vectors(targets)
    values = rng.uniform(0, 100, (3, 3, len(targets)))
    # Different durations and programs must retain different target winners.
    values[0, 0, :2] = [17., 31.]
    visible = rng.random((3, len(targets))) > .2
    visible[1, :2] = False
    rows = []
    for gap in (.15, 0.):
        grid = FiberGrid(1., gap, 16)
        reference = np.zeros((len(centers), 3, 3))
        official_fibers = []
        for c, center in enumerate(centers):
            fibers = []
            for target in targets:
                offset = grid.tangent_offsets(*target, *center)
                fiber, region = (None, 'outside') if offset is None else grid.classify_offset(*offset)
                fibers.append(fiber if region == 'glass' else -1)
            official_fibers.append(fibers)
            for d in range(3):
                for p in range(3):
                    for f in range(16):
                        reference[c, d, p] += max([0.] + [float(values[d, p, i]) for i, fiber in enumerate(fibers) if fiber == f and visible[d, i]])
        kwargs = {'glass': 1., 'pitch': 1.+gap, 'nfib': 16}
        cpu = price_cpu(vectors, centers, values, visible, **kwargs)
        # Deliberately force two-pointing chunks to test assembly and workspace.
        gpu = price_cuda(vectors, centers, values, visible, max_cell_bytes=2*3*3*16*8, **kwargs)
        np.testing.assert_allclose(cpu, reference, rtol=1e-14, atol=1e-12)
        np.testing.assert_allclose(gpu, reference, rtol=1e-14, atol=1e-12)
        restored = 0
        for c, center in enumerate(centers):
            for d in range(3):
                for p in range(3):
                    a = recover_assignment(vectors, center, values[d, p], visible[d], **kwargs)
                    assert len(set(a.values())) == len(a)
                    assert all(official_fibers[c][i] == f and visible[d, i] for f, i in a.items())
                    np.testing.assert_allclose(sum(values[d, p, i] for i in a.values()), reference[c, d, p], rtol=1e-14, atol=1e-12)
                    restored += 1
        rows.append({'gap': gap, 'finite_columns': int(reference.size), 'cpu_max_error': float(np.max(np.abs(cpu-reference))), 'cuda_simulator_max_error': float(np.max(np.abs(gpu-reference))), 'official_assignment_gates': restored})
    result = {'schema': 'global-finite-column-pricing-gate-v1', 'hardware_gpu_used': False,
              'production_or_service_modified': False, 'hidden_inputs_read': False,
              'finite_grid_only_not_continuous_global_certificate': True,
              'oracle': 'official FiberGrid tangent_offsets and classify_offset, independent per-fiber enumeration',
              'rows': rows, 'seconds': time.perf_counter()-began}
    destination = root/'results/interval_column_pricing_20261003'
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'checks.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
