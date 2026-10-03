"""Finite pointing pricing for a global interval-column master.

Input values[d, p, i] are nonnegative coverage-dual contributions, not science
summed across exposures. The caller integrates quality, constructs layer/REQ
incidences, and supplies full-exposure visibility. All programs share one field.
This solves fiber assignment exactly for each supplied pointing/duration/program
at zero instrument offset; it is not a bound over omitted continuous pointings.
No network, quality reconstruction, or production policy import is performed.
"""
from __future__ import annotations

import math
import numpy as np
from numba import cuda

DEG = math.pi / 180


def basis(centers):
    a, z = np.asarray(centers, dtype=float).T * DEG
    ca, sa, cz, sz = np.cos(a), np.sin(a), np.cos(z), np.sin(z)
    return np.ascontiguousarray(np.column_stack(
        (ca*cz, ca*sz, sa, -sa*cz, -sa*sz, ca, -sz, cz, np.zeros(len(a)))))


def altaz_vectors(altaz):
    a, z = np.asarray(altaz, dtype=float).T * DEG
    return np.ascontiguousarray(np.column_stack(
        (np.cos(a)*np.cos(z), np.cos(a)*np.sin(z), np.sin(a))))


def checked(vectors, centers, values, visible, glass, pitch, nfib):
    vectors, centers, values = [np.ascontiguousarray(a, dtype=np.float64)
                               for a in (vectors, centers, values)]
    visible = np.ascontiguousarray(visible, dtype=np.bool_)
    side = math.isqrt(nfib)
    if nfib < 1 or side*side != nfib or not 0 < glass <= pitch:
        raise ValueError('invalid fiber grid')
    if vectors.ndim != 2 or vectors.shape[1] != 3 or centers.ndim != 2 or centers.shape[1] != 2:
        raise ValueError('invalid pointing geometry')
    if values.ndim != 3 or min(values.shape[:2]) < 1 or values.shape[2] != len(vectors) or visible.shape != (values.shape[0], len(vectors)):
        raise ValueError('invalid value or full-exposure visibility tensor')
    if any(not np.all(np.isfinite(a)) for a in (vectors, centers, values)) or np.any(values < 0):
        raise ValueError('dual incidence contributions must be finite and nonnegative')
    return vectors, centers, values, visible, side


def fiber_indices(vectors, center, glass, pitch, side):
    b = basis(np.asarray(center).reshape(1, 2))[0]
    depth = vectors @ b[:3]
    dn, de = (vectors @ b[3:6])/np.maximum(depth, 1e-300)/DEG, (vectors @ b[6:9])/np.maximum(depth, 1e-300)/DEG
    # Clip before converting: back-facing projections can be extremely large.
    row = np.clip(np.floor(np.clip(dn/pitch+side/2, -1, side)), 0, side-1).astype(int)
    col = np.clip(np.floor(np.clip(de/pitch+side/2, -1, side)), 0, side-1).astype(int)
    inside = (depth > 0) & (np.abs(dn) <= side*pitch/2) & (np.abs(de) <= side*pitch/2)
    if glass < pitch:
        inside &= (np.abs(dn-(row-(side-1)/2)*pitch) <= glass/2) & (np.abs(de-(col-(side-1)/2)*pitch) <= glass/2)
    return np.where(inside, row*side+col, -1)


def price_cpu(vectors, centers, values, visible, *, glass, pitch, nfib):
    vectors, centers, values, visible, side = checked(vectors, centers, values, visible, glass, pitch, nfib)
    out = np.zeros((len(centers), *values.shape[:2]))
    for c, center in enumerate(centers):
        fibers = fiber_indices(vectors, center, glass, pitch, side)
        for d in range(values.shape[0]):
            usable = (fibers >= 0) & visible[d]
            for p in range(values.shape[1]):
                best = np.zeros(nfib)
                np.maximum.at(best, fibers[usable], values[d, p, usable])
                out[c, d, p] = best.sum()
    return out


@cuda.jit(cache=True)
def _fiber_max(vectors, bases, values, visible, side, nfib, glass, pitch, cells):
    pair = cuda.grid(1)
    nt = len(vectors)
    if pair >= len(bases)*nt:
        return
    c, i = pair//nt, pair % nt
    depth = 0.
    dn = 0.
    de = 0.
    for j in range(3):
        depth += vectors[i, j]*bases[c, j]
        dn += vectors[i, j]*bases[c, j+3]
        de += vectors[i, j]*bases[c, j+6]
    if depth <= 0:
        return
    dn, de = dn/depth/DEG, de/depth/DEG
    if abs(dn) > side*pitch/2 or abs(de) > side*pitch/2:
        return
    r = min(side-1, max(0, int(math.floor(dn/pitch+side/2))))
    k = min(side-1, max(0, int(math.floor(de/pitch+side/2))))
    if glass < pitch and (abs(dn-(r-(side-1)/2)*pitch) > glass/2 or abs(de-(k-(side-1)/2)*pitch) > glass/2):
        return
    f = r*side+k
    for d in range(values.shape[0]):
        if visible[d, i]:
            for p in range(values.shape[1]):
                cuda.atomic.max(cells, (c, d, p, f), values[d, p, i])


@cuda.jit(cache=True)
def _sum_fibers(cells, totals):
    flat = cuda.grid(1)
    programs = cells.shape[2]
    durations = cells.shape[1]
    if flat >= cells.shape[0]*durations*programs:
        return
    c, rest = flat//(durations*programs), flat % (durations*programs)
    d, p = rest//programs, rest % programs
    total = 0.
    for f in range(cells.shape[3]):
        total += cells[c, d, p, f]
    totals[c, d, p] = total


def price_cuda(vectors, centers, values, visible, *, glass, pitch, nfib, max_cell_bytes=256*1024**2):
    """Chunk centers; reuse target value tensors; copy only finite-column totals.

    32,768 pointings x 20 durations x 3 programs x 16 fibers uses 240 MiB.
    Chunking bounds the output workspace; target tensors add their own storage.
    CUDA simulator can verify the kernel without accessing a hardware device.
    """
    vectors, centers, values, visible, side = checked(vectors, centers, values, visible, glass, pitch, nfib)
    each = values.shape[0]*values.shape[1]*nfib*8
    if max_cell_bytes < each:
        raise ValueError('workspace cannot fit one pointing')
    chunk = max(1, int(max_cell_bytes//each))
    dv, dw, dm = [cuda.to_device(a) for a in (vectors, values, visible)]
    out = np.zeros((len(centers), *values.shape[:2]))
    for left in range(0, len(centers), chunk):
        right = min(len(centers), left+chunk)
        db = cuda.to_device(basis(centers[left:right]))
        cells = cuda.to_device(np.zeros((right-left, *values.shape[:2], nfib)))
        totals = cuda.device_array((right-left, *values.shape[:2]), dtype=np.float64)
        pairs = (right-left)*len(vectors)
        if pairs:
            _fiber_max[(pairs+255)//256, 256](dv, db, dw, dm, side, nfib, glass, pitch, cells)
        columns = (right-left)*values.shape[0]*values.shape[1]
        _sum_fibers[(columns+255)//256, 256](cells, totals)
        out[left:right] = totals.copy_to_host()
    return out


def recover_assignment(vectors, center, values, visible, *, glass, pitch, nfib):
    """For one selected duration/program, deterministic lowest-index tie break."""
    if np.asarray(values).ndim != 1:
        raise ValueError('select one duration and program first')
    vectors, centers, tensor, mask, side = checked(vectors, [center], np.asarray(values)[None, None, :], np.asarray(visible)[None, :], glass, pitch, nfib)
    fibers = fiber_indices(vectors, centers[0], glass, pitch, side)
    assignment = {}
    for f in range(nfib):
        candidates = np.flatnonzero((fibers == f) & mask[0] & (tensor[0, 0] > 0))
        if len(candidates):
            assignment[f] = int(candidates[np.argmax(tensor[0, 0, candidates])])
    return assignment
