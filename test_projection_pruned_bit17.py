#!/usr/bin/env python3
"""Check K18 bit17 on the full matrix, ring, and safely pruned ring."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from bounds_request_projection_k10 import NEG_INF, conditional_projected_dp16
from bounds_request_projection_ring import conditional_projected_dp_ring
from projection_ring_state_pruning import conditional_projected_dp_pruned


def case(*, tagged_repeat: bool, deadline_unit: int,
         include_first: bool = True, required: bool = False,
         mandatory: bool = True) -> tuple:
    n, bit_index = 12, 17
    starts = [0, 3] if include_first else []
    complete_ptr = np.zeros(n + 1, dtype=np.int64)
    for u in starts:
        complete_ptr[u + 1] += 1
    np.cumsum(complete_ptr, out=complete_ptr)
    actionable_mask = np.zeros(n, dtype=np.uint32)
    actionable_mask[0] = np.uint32(1 << bit_index)
    actionable_mask[3] = np.uint32(1)
    key_deadline_unit = np.full(bit_index + 1, n, dtype=np.int32)
    key_deadline_unit[bit_index] = deadline_unit
    return (
        n, complete_ptr,
        np.array([3, 6] if include_first else [], dtype=np.int32),
        np.zeros(len(starts), dtype=np.int16),
        np.array([100, 100] if include_first else [], dtype=np.int64),
        np.array([False, tagged_repeat] if include_first else [], dtype=np.bool_),
        np.zeros(n + 1, dtype=np.int64), np.empty(0, dtype=np.int32),
        actionable_mask, np.array([bit_index, 0], dtype=np.int8),
        (1 << bit_index) if required else 0,
        (1 << bit_index) if mandatory else 0,
        key_deadline_unit, 9 if mandatory else 0,
        np.zeros(2, dtype=np.int64), bit_index + 1,
    )


def main() -> None:
    rows = []
    for name, kwargs, expected in (
        ("tagged_revisit", dict(tagged_repeat=True, deadline_unit=1), 100),
        ("untagged_revisit", dict(tagged_repeat=False, deadline_unit=1), 55),
        ("first_after_deadline", dict(tagged_repeat=True, deadline_unit=0), NEG_INF),
        ("required_miss", dict(tagged_repeat=False, deadline_unit=0,
                               include_first=False, required=True, mandatory=False),
         -100000),
    ):
        args = case(**kwargs)
        values = [conditional_projected_dp16(*args),
                  conditional_projected_dp_ring(*args),
                  conditional_projected_dp_pruned(*args)]
        if values != [expected] * 3:
            raise AssertionError((name, values, expected))
        rows.append({"case": name, "full_cents": values[0],
                     "ring_cents": values[1], "pruned_ring_cents": values[2]})
    payload = {"key_count": 18, "actionable_dtype": "uint32", "rows": rows}
    out = Path("results/projection_pruned_bit17_k18_test.json")
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"cases": len(rows), "all_equal": True}))


if __name__ == "__main__":
    main()
