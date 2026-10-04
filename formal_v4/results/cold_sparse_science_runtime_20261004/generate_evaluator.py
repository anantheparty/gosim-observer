"""Exact fibre block maxima; all geometry and score arithmetic stay in NumPy."""
from __future__ import annotations
import numpy as np
from research.cpu_phase_candidates import _basis
from research.spatial_candidates import DEG
from sparse_native import fine_tables, fine_cells, max_cells

def coarse_block_local(planner, centers, pool, frame, durations, batch_size=256):
    vectors, up, k, scores, factors, multiplier, missing, rr, rt, rd, ub, urgency, _, safety, focus = frame
    rates = np.zeros(len(centers))
    if not len(pool): return rates
    weights, kp = planner.weight[pool], k[pool]
    # These expressions are exactly the original expressions, calculated once
    # for each duration rather than once for each geometric batch.
    tables = []
    for duration in durations:
        raw = np.minimum(1., duration * kp)
        robust = np.minimum(1., duration * kp / safety)
        terminal = missing[pool] * (robust + 1e-10 >= planner.req_threshold) * planner.req_penalty
        terminal += ((factors[pool] < planner.uniform_threshold) * (robust + 1e-10 >= planner.uniform_threshold) * ub[pool])
        terminal += ((rr[pool] > 0) * (robust + 1e-10 >= rt[pool]) * (duration <= rd[pool]) * rr[pool])
        eligible = None
        if focus is not None:
            membership, reward, left, threshold, deadline = focus
            eligible = membership[pool] & (robust + 1e-10 >= threshold) & (duration <= deadline)
            terminal -= eligible * (reward / left)
        science = np.maximum(0., weights[None, :] * raw[None, :] * multiplier[:, pool] - scores[pool][None, :])
        value = (science + terminal[None, :]) * urgency[pool][None, :]
        tables.append((duration, value, eligible, duration <= up[pool]))
    for start in range(0, len(centers), batch_size):
        stop = min(start + batch_size, len(centers))
        center, north, east = _basis(centers[start:stop])
        pv = vectors[pool]
        depth = np.einsum('ij,kj->ki', pv, center)
        dn = np.einsum('ij,kj->ki', pv, north) / np.maximum(depth, 1e-12) / DEG
        de = np.einsum('ij,kj->ki', pv, east) / np.maximum(depth, 1e-12) / DEG
        row = np.clip(np.floor(dn / planner.pitch + planner.side / 2).astype(np.int32), 0, planner.side - 1)
        col = np.clip(np.floor(de / planner.pitch + planner.side / 2).astype(np.int32), 0, planner.side - 1)
        cn, ce = (row - (planner.side - 1) / 2) * planner.pitch, (col - (planner.side - 1) / 2) * planner.pitch
        margin = planner.glass / 2 - np.maximum(np.abs(dn - cn), np.abs(de - ce))
        valid = ((depth > 0) & (np.abs(dn) <= planner.fov / 2) & (np.abs(de) <= planner.fov / 2) & (margin >= .008))
        fibers = row * planner.side + col
        count = stop-start
        batch_rates = np.zeros(count)
        for duration, value, eligible, target_allowed in tables:
            cells, eligible_cells = max_cells(fibers,valid,value,target_allowed,eligible,planner.nfib)
            total = cells.sum(axis=2)
            if eligible is not None:
                regrets = cells - eligible_cells
                ordered = np.sort(regrets, axis=2)[:, :, :min(left, planner.nfib)]
                possible = (left <= planner.nfib) & (np.sum(np.isfinite(regrets), axis=2) >= left)
                full = np.where(possible, total + reward - ordered.sum(axis=2), -np.inf)
                partial = total + np.maximum(0., reward / left - ordered).sum(axis=2)
                total = np.where(possible, np.maximum(total, full), partial)
            batch_rates = np.maximum(batch_rates, total.max(axis=1) / duration)
        rates[start:stop] = batch_rates
    return rates


def install():
    from research import spatial_candidates as spatial
    from research import cpu_phase_candidates as phase
    import inspect
    # Preserve the full original function, including duration sampling/tie and
    # selected-target order, replacing only the two pure max scatter operators.
    source = inspect.getsource(spatial.SpatialPlanner._evaluate)
    source = '\n'.join(line[4:] if line.startswith('    ') else line for line in source.splitlines())
    begin = source.index('    t = durations[:, None]')
    end = source.index('    total = best_cell.sum(axis=2)',begin)
    replacement = """    t = durations[:, None]
    if focus_request is not None:
        membership, focus_reward, focus_left, focus_threshold, focus_deadline = focus_request
    best_cell, eligible_cell, winner, eligible_winner = fine_cells(self, idx, fiber, durations,
        (up, k, scores, factors, multiplier, req_missing, request_reward, request_threshold,
         request_deadline, uniform_bonus, urgency, safety, focus_request))
    focus_eligible = focus_request
"""
    source = source[:begin]+replacement+source[end:]
    begin = source.index('        eligible_values = np.where(')
    end = source.index('        focus_costs = best_cell - eligible_cell',begin)
    source = source[:begin]+source[end:]
    begin = source.index('    for f in range(self.nfib):')
    end = source.index('    return float(rates[d, p])',begin)
    selection = """    forced = np.asarray([f in force_fibers for f in range(self.nfib)], dtype=bool)
    chosen = np.where(forced, eligible_winner[d, p], winner[d, p])
    keep = (chosen >= 0) & ((best_cell[d, p] > 0) | forced)
    selected = chosen[keep]
    fibers = np.flatnonzero(keep)
"""
    source = source[:begin]+selection+source[end:]
    global EVALUATOR_SOURCE
    EVALUATOR_SOURCE = source
    space = dict(vars(spatial), fine_cells=fine_cells)
    exec(compile(source, '<exact-fibre-blocks>', 'exec'), space)
    spatial.SpatialPlanner._evaluate = space['_evaluate']
    phase.coarse_numpy_local = coarse_block_local
