#!/usr/bin/env python3
"""Focused K16 high-bit semantics for the full and ring projected DPs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from bounds_request_projection_k10 import NEG_INF, conditional_projected_dp16
from bounds_request_projection_ring import conditional_projected_dp_ring


def solve(*, tagged_repeat: bool, deadline_unit: int,
          include_first: bool = True, required: bool = False,
          mandatory: bool = True, bit_index: int = 15) -> tuple[int, int]:
    n = 12
    if bit_index not in (15, 16, 17):
        raise ValueError("focused test only covers bit15/bit16/bit17")
    high_bit = 1 << bit_index
    mask_dtype = np.uint32 if bit_index >= 16 else np.uint16
    starts = [0, 3] if include_first else []
    complete_ptr = np.zeros(n + 1, dtype=np.int64)
    for u in starts:
        complete_ptr[u + 1] += 1
    np.cumsum(complete_ptr, out=complete_ptr)
    complete_end = np.array([3, 6] if include_first else [], dtype=np.int32)
    complete_tile = np.zeros(len(starts), dtype=np.int16)
    complete_reduced = np.array([100, 100] if include_first else [], dtype=np.int64)
    complete_tagged = np.array([False, tagged_repeat] if include_first else [], dtype=np.bool_)
    partial_ptr = np.zeros(n + 1, dtype=np.int64)
    partial_end = np.empty(0, dtype=np.int32)
    actionable_mask = np.zeros(n, dtype=mask_dtype)
    actionable_mask[0] = mask_dtype(high_bit)
    actionable_mask[3] = mask_dtype(1)
    key_index = np.array([bit_index, 0], dtype=np.int8)
    key_deadline_unit = np.full(bit_index + 1, n, dtype=np.int32)
    key_deadline_unit[bit_index] = deadline_unit
    theta = np.zeros(2, dtype=np.int64)
    kwargs = (
        n, complete_ptr, complete_end, complete_tile, complete_reduced,
        complete_tagged, partial_ptr, partial_end, actionable_mask,
        key_index, high_bit if required else 0,
        high_bit if mandatory else 0,
        key_deadline_unit, 9 if mandatory else 0, theta, bit_index + 1,
    )
    return conditional_projected_dp16(*kwargs), conditional_projected_dp_ring(*kwargs)


def main() -> None:
    high = np.uint16(32768)
    mask_rows = []
    for mask, expected in ((0, True), (32768, False), (65535, False)):
        got = bool(int(high) & (~mask))
        if got != expected:
            raise AssertionError(f"high actionable bit failed for mask {mask}")
        mask_rows.append({"mask": mask, "high_bit_actionable_and_unfinished": got})
    cases = {
        "first_and_tagged_revisit": (
            solve(tagged_repeat=True, deadline_unit=1), 100
        ),
        "untagged_revisit_disallowed": (
            solve(tagged_repeat=False, deadline_unit=1), 55
        ),
        "first_after_deadline_forbidden": (
            solve(tagged_repeat=True, deadline_unit=0), NEG_INF
        ),
        "required_high_bit_terminal_penalty": (
            solve(tagged_repeat=False, deadline_unit=0, include_first=False,
                  required=True, mandatory=False), -100000
        ),
    }
    tested = []
    for name, (pair, expected) in cases.items():
        if pair[0] != pair[1] or pair[0] != expected:
            raise AssertionError(f"{name}: full={pair[0]}, ring={pair[1]}, expected={expected}")
        tested.append({"case": name, "expected_cents": expected,
                       "full_cents": pair[0], "ring_cents": pair[1]})
    payload = {"scope": "focused synthetic 12-cell K16 DAG",
               "key_bit_index": 15, "high_bit": 32768,
               "mask_checks": mask_rows, "cases": tested}
    out = Path("results/projection_highbit_k16_test.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
