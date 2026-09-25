#!/usr/bin/env python3
"""Independent small-DAG audit of the 17-key uint32 projection transition.

The two compiled implementations have different time storage layouts.  A
third, reachable-state Python recursion checks their shared transition rules.
All three receive exactly the same uint32 actionability array, including bit
16, while the DP state remains a nonnegative Python/Numba integer.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from numba import njit

import bounds_practice_projection as projection
from bounds_request_projection_k10 import NEG_INF, conditional_projected_dp16
from bounds_request_projection_ring import conditional_projected_dp_ring


K = 17
HIGH = 1 << 16
N = 12


@njit(cache=True)
def _compiled_unfinished(actionable: np.ndarray, mask: int) -> bool:
    """Probe the exact mixed unsigned/signed expression used in both DPs."""
    return bool(actionable[0] & (~mask))


def _pack(
    arcs: list[tuple[int, int, int, int, bool]],
    partials: list[tuple[int, int]],
    active: dict[int, int],
    *,
    required: int = 0,
    mandatory: int = 0,
    deadlines: dict[int, int] | None = None,
    earliest_terminal: int = N,
    theta_nonkey: tuple[int, int] = (0, 0),
) -> tuple:
    arcs = sorted(arcs, key=lambda arc: arc[0])
    partials = sorted(partials)
    complete_ptr = np.zeros(N + 1, dtype=np.int64)
    partial_ptr = np.zeros(N + 1, dtype=np.int64)
    for u, end, *_ in arcs:
        assert 0 <= u < end <= N
        complete_ptr[u + 1] += 1
    for u, end in partials:
        assert 0 <= u < end <= N
        partial_ptr[u + 1] += 1
    np.cumsum(complete_ptr, out=complete_ptr)
    np.cumsum(partial_ptr, out=partial_ptr)
    actionable = np.zeros(N, dtype=np.uint32)
    for u, mask in active.items():
        actionable[u] = np.uint32(mask)
    key_index = np.array(list(range(K)) + [-1, -1], dtype=np.int8)
    key_deadline = np.full(K, N, dtype=np.int32)
    for bit, deadline in (deadlines or {}).items():
        key_deadline[bit] = deadline
    theta = np.zeros(K + 2, dtype=np.int64)
    theta[-2:] = theta_nonkey
    return (
        N,
        complete_ptr,
        np.array([arc[1] for arc in arcs], dtype=np.int32),
        np.array([arc[2] for arc in arcs], dtype=np.int16),
        np.array([arc[3] for arc in arcs], dtype=np.int64),
        np.array([arc[4] for arc in arcs], dtype=np.bool_),
        partial_ptr,
        np.array([end for _, end in partials], dtype=np.int32),
        actionable,
        key_index,
        required,
        mandatory,
        key_deadline,
        earliest_terminal,
        theta,
        K,
    )


def _reference(args: tuple) -> int:
    (
        n, complete_ptr, complete_end, complete_tile, complete_reduced,
        complete_tagged, partial_ptr, partial_end, actionable, key_index,
        required, mandatory, deadline, earliest_terminal, theta, k,
    ) = args
    assert k == K and actionable.dtype == np.uint32

    @lru_cache(maxsize=None)
    def value(u: int, visited: int) -> int:
        missing = mandatory & ~visited
        terminal = NEG_INF if missing else -projection.REQUIRED_MISS_CENTS * (
            required & ~visited
        ).bit_count()
        if u == n:
            return terminal
        best = terminal if u >= earliest_terminal else NEG_INF
        boundary = ((u // projection.POINTS_PER_SLOT) + 1) * projection.POINTS_PER_SLOT
        assert boundary <= n
        waiting = projection.WAIT_UNIT_CENTS * (boundary - u) if (
            int(actionable[u]) & ~visited
        ) else 0
        wait_future = value(boundary, visited)
        if wait_future > NEG_INF // 2:
            best = max(best, wait_future - waiting)
        for j in range(partial_ptr[u], partial_ptr[u + 1]):
            best = max(best, value(int(partial_end[j]), visited))
        for j in range(complete_ptr[u], complete_ptr[u + 1]):
            tile = int(complete_tile[j])
            bit = int(key_index[tile])
            if bit >= 0:
                flag = 1 << bit
                if visited & flag:
                    if complete_tagged[j]:
                        best = max(best, value(int(complete_end[j]), visited))
                elif u < deadline[bit]:
                    first_future = value(int(complete_end[j]), visited | flag)
                    if first_future > NEG_INF // 2:
                        best = max(best, first_future + int(complete_reduced[j]))
            else:
                toll = 0 if complete_tagged[j] else int(theta[tile])
                nonkey_future = value(int(complete_end[j]), visited)
                if nonkey_future > NEG_INF // 2:
                    best = max(best, nonkey_future - toll)
        return best

    return value(0, 0)


def _check(name: str, args: tuple, expected: int | None = None) -> None:
    reference = _reference(args)
    full = conditional_projected_dp16(*args)
    ring = conditional_projected_dp_ring(*args)
    if expected is not None and reference != expected:
        raise AssertionError(f"{name}: reference {reference}, expected {expected}")
    if full != reference or ring != reference:
        raise AssertionError(
            f"{name}: reference {reference}, full {full}, ring {ring}"
        )


def main() -> None:
    probe = np.array([HIGH], dtype=np.uint32)
    for visited, expected in (
        (0, True), (1 << 15, True), (HIGH, False), ((1 << K) - 1, False),
    ):
        actual = _compiled_unfinished(probe, visited)
        if actual != expected:
            raise AssertionError(
                f"uint32/actionability bit 16: visited={visited}, got={actual}"
            )

    _check(
        "unfinished high bit charges wait",
        _pack([], [], {0: HIGH}, earliest_terminal=N),
        -90,
    )
    first = [(0, 3, 16, 100, False)]
    repeat = (3, 6, 16, 100, True)
    low_alternative = (3, 6, 0, -1000, False)
    common = dict(
        active={0: HIGH, 3: 1 | HIGH}, mandatory=HIGH,
        deadlines={16: 1}, earliest_terminal=9,
    )
    _check(
        "first high-bit success then tagged revisit",
        _pack(first + [repeat, low_alternative], [], **common), 100,
    )
    _check(
        "untagged high-bit revisit forbidden",
        _pack(first + [(3, 6, 16, 100, False), low_alternative], [], **common),
        55,
    )
    _check(
        "high-bit first visit after deadline infeasible",
        _pack([(3, 6, 16, 100, False)], [], {3: HIGH}, mandatory=HIGH,
              deadlines={16: 3}, earliest_terminal=9),
        NEG_INF,
    )
    _check(
        "high-bit required miss penalty",
        _pack([], [], {}, required=HIGH, earliest_terminal=0),
        -projection.REQUIRED_MISS_CENTS,
    )
    _check(
        "partial-weather edge bypasses wait",
        _pack([], [(0, 3)], {0: HIGH}, earliest_terminal=N), 0,
    )

    rng = np.random.default_rng(20260925)
    for case in range(12):
        arcs = []
        partials = []
        active = {}
        for u in range(N):
            for _ in range(int(rng.integers(0, 4))):
                end = int(rng.integers(u + 1, min(N, u + 5) + 1))
                tile = int(rng.choice([0, 15, 16, 17, 18]))
                arcs.append((u, end, tile, int(rng.integers(-60, 160)),
                             bool(rng.integers(0, 2))))
                if tile < K:
                    active[u] = active.get(u, 0) | (1 << tile)
            if rng.random() < 0.2:
                partials.append((u, int(rng.integers(u + 1, min(N, u + 5) + 1))))
        mandatory = HIGH if case % 2 else 0
        if case % 4 == 0:
            mandatory |= 1 << 15
        required = HIGH | (1 << 15 if case % 3 == 0 else 0)
        args = _pack(
            arcs, partials, active, mandatory=mandatory, required=required,
            deadlines={16: (3, 7, 12)[case % 3], 15: (2, 8, 12)[case % 3]},
            earliest_terminal=(0, 6, 12)[case % 3],
            theta_nonkey=(int(rng.integers(0, 15)), int(rng.integers(0, 15))),
        )
        _check(f"seed 20260925 random case {case}", args)
    print("K17 uint32 actionability: 6 deterministic and 12 randomized tiny-DAG cases passed")


if __name__ == "__main__":
    main()
