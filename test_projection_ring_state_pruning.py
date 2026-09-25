#!/usr/bin/env python3
"""Random small time-DAG parity checks for safe key-mask pruning."""

from __future__ import annotations

import numpy as np

from bounds_request_projection_ring import conditional_projected_dp_ring
from projection_ring_state_pruning import conditional_projected_dp_pruned


def case(seed: int) -> tuple:
    rng = np.random.default_rng(seed)
    n = int(rng.integers(2, 7)) * 6
    k = int(rng.integers(1, 6))
    tile_count = k + 2
    ends: list[int] = []
    tiles: list[int] = []
    reduced: list[int] = []
    tagged: list[bool] = []
    complete_ptr = [0]
    partial_ends: list[int] = []
    partial_ptr = [0]
    for u in range(n):
        for _ in range(int(rng.integers(0, 5))):
            ends.append(int(rng.integers(u + 1, min(n, u + 9) + 1)))
            tiles.append(int(rng.integers(tile_count)))
            reduced.append(int(rng.integers(-40, 301)))
            tagged.append(bool(rng.integers(2)))
        complete_ptr.append(len(ends))
        for _ in range(int(rng.integers(0, 3))):
            partial_ends.append(int(rng.integers(u + 1, min(n, u + 9) + 1)))
        partial_ptr.append(len(partial_ends))
    required = int(rng.integers(1 << k))
    mandatory = int(rng.integers(1 << k))
    return (
        n, np.array(complete_ptr, dtype=np.int32), np.array(ends, dtype=np.int32),
        np.array(tiles, dtype=np.int8), np.array(reduced, dtype=np.int64),
        np.array(tagged, dtype=np.bool_), np.array(partial_ptr, dtype=np.int32),
        np.array(partial_ends, dtype=np.int32),
        rng.integers(0, 1 << k, size=n, dtype=np.uint16),
        np.array(list(range(k)) + [-1, -1], dtype=np.int8),
        required, mandatory,
        rng.integers(0, n + 1, size=k, dtype=np.int32),
        int(rng.integers(n + 1)),
        rng.integers(0, 30, size=tile_count, dtype=np.int64), k,
    )


if __name__ == "__main__":
    for seed in range(200):
        args = case(seed)
        old = conditional_projected_dp_ring(*args)
        new = conditional_projected_dp_pruned(*args)
        if old != new:
            raise AssertionError((seed, old, new))
    print("200 random small time-DAG root values matched exactly")
