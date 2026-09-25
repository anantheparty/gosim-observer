#!/usr/bin/env python3
"""Experimental CUDA implementation of the certified integer projection DP.

This module changes only the execution of the projected time/mask recurrence.
It accepts the exact 16 arguments used by ``_conditional_bound`` and returns
integer cents.  The capacity prices, action graph, external envelopes, and
request accounting remain in the existing CPU certificate code.

Run ``NUMBA_ENABLE_CUDASIM=1 python3 gpu_projection_dp.py self-test`` without
a GPU.  The simulator is for correctness checks on small graphs, not timing.
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
from numba import cuda

import bounds_practice_projection as projection
import bounds_request_projection_k10 as full
from bounds_request_projection_ring import conditional_projected_dp_ring
from projection_ring_state_pruning import conditional_projected_dp_pruned


NEG_INF = -(10**15)
POINTS_PER_SLOT = projection.POINTS_PER_SLOT
WAIT_UNIT_CENTS = projection.WAIT_UNIT_CENTS
REQUIRED_MISS_CENTS = projection.REQUIRED_MISS_CENTS
THREADS_PER_BLOCK = 256


@cuda.jit
def _step_kernel(
    u_base, active_rows, state_count, horizon, all_bits,
    dp, terminal, allowed_mask, forced_mask,
    complete_ptr, complete_end, complete_tile, complete_reduced_cents,
    complete_tagged, partial_ptr, partial_end, actionable_mask,
    key_index, key_deadline_unit, earliest_terminal_unit, theta_cents,
):
    thread = cuda.grid(1)
    if thread >= active_rows * state_count:
        return
    lane = thread // state_count
    mask = thread - lane * state_count
    u = u_base + lane
    row = u % horizon
    allowed = allowed_mask[u]
    forced = forced_mask[u]
    if ((mask & (all_bits ^ allowed)) != 0
            or (mask & forced) != forced):
        dp[row, mask] = NEG_INF
        return

    best = terminal[mask] if u >= earliest_terminal_unit else NEG_INF
    boundary = ((u // POINTS_PER_SLOT) + 1) * POINTS_PER_SLOT
    wait_cost = (WAIT_UNIT_CENTS * (boundary - u)
                 if (actionable_mask[u] & (all_bits ^ mask)) != 0 else 0)
    future = dp[boundary % horizon, mask]
    if future > NEG_INF // 2:
        candidate = future - wait_cost
        if candidate > best:
            best = candidate

    for j in range(partial_ptr[u], partial_ptr[u + 1]):
        candidate = dp[partial_end[j] % horizon, mask]
        if candidate > best:
            best = candidate

    for j in range(complete_ptr[u], complete_ptr[u + 1]):
        tile = complete_tile[j]
        bit_index = key_index[tile]
        end_row = complete_end[j] % horizon
        if bit_index >= 0:
            bit = 1 << bit_index
            if (mask & bit) == 0:
                if u >= key_deadline_unit[bit_index]:
                    continue
                future = dp[end_row, mask | bit]
                if future <= NEG_INF // 2:
                    continue
                candidate = future + complete_reduced_cents[j]
            elif complete_tagged[j]:
                candidate = dp[end_row, mask]
            else:
                continue
        else:
            future = dp[end_row, mask]
            if future <= NEG_INF // 2:
                continue
            toll = 0 if complete_tagged[j] else theta_cents[tile]
            candidate = future - toll
        if candidate > best:
            best = candidate
    dp[row, mask] = best


def _prepare_masks(
    n: int, complete_ptr: np.ndarray, complete_end: np.ndarray,
    complete_tile: np.ndarray, partial_ptr: np.ndarray,
    partial_end: np.ndarray, key_index: np.ndarray,
    mandatory_key_mask: int, key_deadline_unit: np.ndarray, k: int,
) -> tuple[int, np.ndarray, np.ndarray, bool]:
    """Reproduce the CPU pruner's necessary conditions and check wave safety."""
    if n < 0 or not 0 <= k <= 20:
        raise ValueError("invalid time horizon or key count")
    if len(complete_ptr) != n + 1 or len(partial_ptr) != n + 1:
        raise ValueError("CSR pointers do not cover the time horizon")
    if len(key_deadline_unit) != k or mandatory_key_mask & ~((1 << k) - 1):
        raise ValueError("key deadline/mask mismatch")
    first_end = np.full(k, n + 1, dtype=np.int32)
    last_start = np.full(k, -1, dtype=np.int32)
    max_span = POINTS_PER_SLOT
    wave_safe = n % POINTS_PER_SLOT == 0
    for u in range(n):
        boundary = ((u // POINTS_PER_SLOT) + 1) * POINTS_PER_SLOT
        for j in range(int(complete_ptr[u]), int(complete_ptr[u + 1])):
            end = int(complete_end[j])
            span = end - u
            if span <= 0 or end > n:
                raise AssertionError("complete arc does not advance in time")
            max_span = max(max_span, span)
            wave_safe &= span >= POINTS_PER_SLOT // 2
            bit_index = int(key_index[int(complete_tile[j])])
            if bit_index >= 0 and u < int(key_deadline_unit[bit_index]):
                first_end[bit_index] = min(first_end[bit_index], end)
                last_start[bit_index] = u
        for j in range(int(partial_ptr[u]), int(partial_ptr[u + 1])):
            end = int(partial_end[j])
            span = end - u
            if span <= 0 or end > n:
                raise AssertionError("partial arc does not advance in time")
            max_span = max(max_span, span)
            wave_safe &= end >= boundary

    all_bits = (1 << k) - 1
    allowed = np.empty(n, dtype=np.int32)
    forced = np.empty(n, dtype=np.int32)
    for u in range(n):
        a = f = 0
        for bit_index in range(k):
            bit = 1 << bit_index
            if first_end[bit_index] <= u:
                a |= bit
            if mandatory_key_mask & bit and u > last_start[bit_index]:
                f |= bit
        allowed[u] = a & all_bits
        forced[u] = f & all_bits
    return max_span + 1, allowed, forced, wave_safe


def _terminal_values(k: int, required_key_mask: int,
                     mandatory_key_mask: int) -> np.ndarray:
    state_count = 1 << k
    masks = np.arange(state_count, dtype=np.int32)
    missing = required_key_mask & ~masks
    count = np.zeros(state_count, dtype=np.int8)
    for bit in range(k):
        count += ((missing & (1 << bit)) != 0).astype(np.int8)
    terminal = np.full(state_count, NEG_INF, dtype=np.int64)
    valid = (masks & mandatory_key_mask) == mandatory_key_mask
    terminal[valid] = -REQUIRED_MISS_CENTS * count[valid].astype(np.int64)
    return terminal


def conditional_projected_dp_cuda(
    n: int,
    complete_ptr: np.ndarray,
    complete_end: np.ndarray,
    complete_tile: np.ndarray,
    complete_reduced_cents: np.ndarray,
    complete_tagged: np.ndarray,
    partial_ptr: np.ndarray,
    partial_end: np.ndarray,
    actionable_mask: np.ndarray,
    key_index: np.ndarray,
    required_key_mask: int,
    mandatory_key_mask: int,
    key_deadline_unit: np.ndarray,
    earliest_terminal_unit: int,
    theta_cents: np.ndarray,
    k: int,
    *,
    launch_mode: str = "auto",
    threads_per_block: int = THREADS_PER_BLOCK,
) -> int:
    """Return the exact projected maximum in integer cents on a CUDA device.

    ``wave3`` batches three independent grid times per kernel. It is selected
    only after checking every complete arc has length >=3 and every partial
    arc reaches at least the next slot boundary; otherwise ``auto`` falls back
    to one time row per kernel. Kernel launches use the default stream, whose
    in-order execution is the barrier between successive reverse-time waves.
    """
    if not cuda.is_available():
        raise RuntimeError("CUDA unavailable; use NUMBA_ENABLE_CUDASIM=1 for self-test")
    if launch_mode not in ("auto", "serial", "wave3"):
        raise ValueError("launch_mode must be auto, serial, or wave3")
    if threads_per_block <= 0 or threads_per_block > 1024:
        raise ValueError("invalid CUDA block size")
    horizon, allowed, forced, wave_safe = _prepare_masks(
        n, complete_ptr, complete_end, complete_tile, partial_ptr,
        partial_end, key_index, mandatory_key_mask, key_deadline_unit, k,
    )
    if launch_mode == "wave3" and not wave_safe:
        raise ValueError("wave3 requires 6-cell slots, complete spans >=3, and boundary partial arcs")
    use_waves = wave_safe and launch_mode != "serial"
    if use_waves:
        # A later time in the same wave can read a future row whose original
        # ring index equals an earlier wave member's destination. Widen by
        # wave_width-1 so these concurrent writes cannot alias future reads.
        horizon += POINTS_PER_SLOT // 2 - 1
    state_count = 1 << k
    all_bits = state_count - 1
    terminal = _terminal_values(k, required_key_mask, mandatory_key_mask)
    dp = np.full((horizon, state_count), NEG_INF, dtype=np.int64)
    dp[n % horizon, :] = terminal

    d_dp = cuda.to_device(dp)
    d_terminal = cuda.to_device(terminal)
    d_allowed = cuda.to_device(allowed)
    d_forced = cuda.to_device(forced)
    d_complete_ptr = cuda.to_device(complete_ptr)
    d_complete_end = cuda.to_device(complete_end)
    d_complete_tile = cuda.to_device(complete_tile)
    d_complete_reduced = cuda.to_device(complete_reduced_cents)
    d_complete_tagged = cuda.to_device(complete_tagged)
    d_partial_ptr = cuda.to_device(partial_ptr)
    d_partial_end = cuda.to_device(partial_end)
    d_actionable = cuda.to_device(actionable_mask)
    d_key_index = cuda.to_device(key_index)
    d_key_deadline = cuda.to_device(key_deadline_unit)
    d_theta = cuda.to_device(theta_cents)

    def launch(u_base: int, active_rows: int) -> None:
        blocks = (active_rows * state_count + threads_per_block - 1) // threads_per_block
        _step_kernel[blocks, threads_per_block](
            u_base, active_rows, state_count, horizon, all_bits,
            d_dp, d_terminal, d_allowed, d_forced,
            d_complete_ptr, d_complete_end, d_complete_tile,
            d_complete_reduced, d_complete_tagged, d_partial_ptr,
            d_partial_end, d_actionable, d_key_index, d_key_deadline,
            earliest_terminal_unit, d_theta,
        )

    if use_waves:
        for slot_start in range(n - POINTS_PER_SLOT, -1, -POINTS_PER_SLOT):
            launch(slot_start + POINTS_PER_SLOT // 2, POINTS_PER_SLOT // 2)
            launch(slot_start, POINTS_PER_SLOT // 2)
    else:
        for u in range(n - 1, -1, -1):
            launch(u, 1)
    cuda.synchronize()
    return int(d_dp[0:1, 0:1].copy_to_host()[0, 0])


def _small_graph() -> tuple:
    """A deterministic request/deadline/revisit example for CUDASIM."""
    n, k, tile_count = 12, 3, 4
    per_start: list[list[tuple[int, int, int, bool]]] = [[] for _ in range(n)]
    for u in range(n):
        for tile in range(tile_count):
            span = (3, 4, 3, 6)[tile]
            if u + span <= n and (u + tile) % 4 != 0:
                per_start[u].append((u + span, tile, 13 - 2 * tile - (u % 3),
                                     (u + tile) % 3 == 0))
    complete_ptr = np.zeros(n + 1, dtype=np.int64)
    arcs = []
    for u in range(n):
        arcs.extend(per_start[u])
        complete_ptr[u + 1] = len(arcs)
    complete_end = np.array([arc[0] for arc in arcs], dtype=np.int32)
    complete_tile = np.array([arc[1] for arc in arcs], dtype=np.int16)
    reduced = np.array([arc[2] for arc in arcs], dtype=np.int64)
    tagged = np.array([arc[3] for arc in arcs], dtype=np.bool_)
    partial_ptr = np.zeros(n + 1, dtype=np.int64)
    partial_ptr[3:] += 1
    partial_ptr[9:] += 1
    partial_end = np.array([6, 12], dtype=np.int32)
    actionable = np.array([0b111 if u % 3 else 0b011 for u in range(n)],
                          dtype=np.uint16)
    key_index = np.array([0, 1, 2, -1], dtype=np.int8)
    deadlines = np.array([9, n, n], dtype=np.int32)
    theta = np.array([0, 0, 0, 5], dtype=np.int64)
    return (n, complete_ptr, complete_end, complete_tile, reduced, tagged,
            partial_ptr, partial_end, actionable, key_index, 0b101, 0b001,
            deadlines, 4, theta, k)


def _random_graph(seed: int) -> tuple:
    """Small DAGs with varied deadlines, tags, and weather interruptions."""
    rng = np.random.default_rng(seed)
    n, k, tile_count = 18, 4, 5
    complete_ptr = np.zeros(n + 1, dtype=np.int64)
    arcs: list[tuple[int, int, int, bool]] = []
    partial_ptr = np.zeros(n + 1, dtype=np.int64)
    partial_ends: list[int] = []
    actionable = np.zeros(n, dtype=np.uint16)
    for u in range(n):
        for tile in range(tile_count):
            span = int(rng.integers(3, 7))
            if u + span <= n and rng.random() < 0.43:
                arcs.append((u + span, tile, int(rng.integers(-9, 23)),
                             bool(rng.integers(0, 2))))
                if tile < k:
                    actionable[u] |= np.uint16(1 << tile)
        complete_ptr[u + 1] = len(arcs)
        boundary = ((u // POINTS_PER_SLOT) + 1) * POINTS_PER_SLOT
        if boundary <= n and rng.random() < 0.2:
            partial_ends.append(boundary)
        partial_ptr[u + 1] = len(partial_ends)
    required = int(rng.integers(0, 1 << k))
    mandatory = int(rng.integers(0, 1 << k))
    deadlines = np.array([int(rng.integers(6, n + 1)) for _ in range(k)],
                         dtype=np.int32)
    theta = np.array([0, 0, 0, 0, 7], dtype=np.int64)
    return (
        n, complete_ptr,
        np.array([arc[0] for arc in arcs], dtype=np.int32),
        np.array([arc[1] for arc in arcs], dtype=np.int16),
        np.array([arc[2] for arc in arcs], dtype=np.int64),
        np.array([arc[3] for arc in arcs], dtype=np.bool_),
        partial_ptr, np.array(partial_ends, dtype=np.int32),
        actionable, np.array([0, 1, 2, 3, -1], dtype=np.int8),
        required, mandatory, deadlines, 5, theta, k,
    )


def self_test() -> None:
    cases = [("fixed", _small_graph())]
    cases.extend((f"random_{seed}", _random_graph(seed)) for seed in range(6))
    for name, args in cases:
        expected = conditional_projected_dp_ring(*args)
        pruned = conditional_projected_dp_pruned(*args)
        if expected != pruned:
            raise AssertionError(f"{name} CPU ring/pruned differ: {expected}, {pruned}")
        results = {}
        for mode in ("serial", "wave3", "auto"):
            actual = conditional_projected_dp_cuda(*args, launch_mode=mode)
            if actual != expected:
                raise AssertionError(f"{name} CUDA {mode}: {actual} != {expected}")
            results[mode] = actual
        print(json.dumps({"test": name, "cpu_cents": expected,
                          "cuda_cents": results}, sort_keys=True), flush=True)
    args = list(_small_graph())
    altered_end = args[2].copy()
    altered_end[0] = 1
    args[2] = altered_end
    expected = conditional_projected_dp_ring(*args)
    actual = conditional_projected_dp_cuda(*args, launch_mode="auto")
    if actual != expected:
        raise AssertionError("auto mode failed to fall back to serial CUDA")
    try:
        conditional_projected_dp_cuda(*args, launch_mode="wave3")
    except ValueError:
        pass
    else:
        raise AssertionError("wave3 accepted a one-cell complete arc")
    print(json.dumps({"test": "serial_fallback", "cpu_cents": expected,
                      "cuda_cents": actual}, sort_keys=True), flush=True)


def verify_saved(k_values: list[int], launch_mode: str) -> None:
    from parallel_key_extension_scan import (
        CERT_EXPECTED_CENTS, COMPARE_FIELDS, K14_CERT, K15_CERT,
        certified_base, find_certified_case,
    )
    from projection_branch_merge import two_equivalent_branches

    base, cert16, _ = certified_base()
    data, audit = full._load_audited_data(full.PRICE_FILE)
    inputs = full._instance_inputs(data)
    certificates = {
        14: json.loads(K14_CERT.read_text()),
        15: json.loads(K15_CERT.read_text()),
        16: cert16,
    }
    for k in k_values:
        if k == 18:
            saved = json.loads((full.ROOT / "results/practice_k18_t45_t1_pilot.json").read_text())
            keys = tuple(saved["key_tiles"])
        elif k in certificates:
            keys = base[:k]
            saved = find_certified_case(certificates[k], keys)
        else:
            raise ValueError(f"no saved comparison case for K{k}")
        if len(keys) != k:
            raise AssertionError("saved key count differs")
        saved_price_sha = (saved["price_sha256"] if k == 18
                           else certificates[k]["certificates"]["price_sha256"])
        if saved_price_sha != audit["price_sha256"]:
            raise AssertionError(f"K{k} price hash differs from audited input")
        started = time.monotonic()
        if "T00004" in keys or "T00012" in keys:
            raise AssertionError("saved branch comparison expects equivalent DP inputs")
        rows, sharing = two_equivalent_branches(
            data, inputs, keys, 135,
            lambda *dp_args: conditional_projected_dp_cuda(
                *dp_args, launch_mode=launch_mode),
        )
        if not sharing["second_dp_reused"]:
            raise AssertionError("two branch DP invocations were not identical")
        for branch, actual in enumerate(rows):
            expected = saved["branches"][branch]
            if any(actual[field] != expected[field] for field in COMPARE_FIELDS):
                differences = {field: (actual[field], expected[field])
                               for field in COMPARE_FIELDS
                               if actual[field] != expected[field]}
                raise AssertionError(f"K{k} branch {branch} differs: {differences}")
            print(json.dumps({"k": k, "branch": branch,
                              "upper_cents": actual["conditional_upper_cents"],
                              "gpu_dp_seconds": actual["dp_wall_seconds"]}), flush=True)
        total = max(row["conditional_upper_cents"] for row in rows)
        expected_total = (saved["all_awarded_upper_cents"] if k == 18
                          else CERT_EXPECTED_CENTS[k])
        if total != expected_total:
            raise AssertionError(f"K{k} total {total} != {expected_total}")
        print(json.dumps({"k": k, "verified_total_cents": total,
                          "wall_seconds": time.monotonic() - started}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test", help="small integer graph versus both CPU DPs")
    check = sub.add_parser("verify", help="match saved public K14/K15/K16/K18 certificates")
    check.add_argument("--k", type=int, action="append", choices=(14, 15, 16, 18),
                       help="may be repeated; default: 14,15")
    check.add_argument("--launch-mode", choices=("auto", "serial", "wave3"),
                       default="auto")
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        verify_saved(args.k or [14, 15], args.launch_mode)


if __name__ == "__main__":
    main()
