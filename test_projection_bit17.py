#!/usr/bin/env python3
"""Focused K18 bit17 equivalence of full and ring projected DPs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from bounds_request_projection_k10 import NEG_INF
from test_projection_high_bit import solve


def main() -> None:
    high = 1 << 17
    probe = np.uint32(high)
    checks = []
    for visited, expected in ((0, True), (1 << 16, True),
                              (high, False), ((1 << 18) - 1, False)):
        actual = bool(probe & np.uint32(~visited & ((1 << 32) - 1)))
        if actual != expected:
            raise AssertionError(f"bit17 actionable mismatch at visited={visited}")
        checks.append({"visited_mask": visited, "unfinished": actual})
    cases = []
    for name, kwargs, expected in (
        ("first_then_tagged_revisit", dict(tagged_repeat=True, deadline_unit=1), 100),
        ("untagged_revisit_forbidden", dict(tagged_repeat=False, deadline_unit=1), 55),
        ("first_after_deadline_forbidden", dict(tagged_repeat=True, deadline_unit=0), NEG_INF),
        ("required_miss_terminal_penalty", dict(tagged_repeat=False, deadline_unit=0,
                                                include_first=False, required=True,
                                                mandatory=False), -100000),
    ):
        matrix, ring = solve(bit_index=17, **kwargs)
        if matrix != expected or ring != expected:
            raise AssertionError(f"{name}: full={matrix}, ring={ring}, expected={expected}")
        cases.append({"case": name, "full_cents": matrix, "ring_cents": ring})
    payload = {"key_bit_index": 17, "high_bit": high,
               "actionable_mask_dtype": "uint32", "mask_checks": checks,
               "cases": cases}
    out = Path("results/projection_bit17_k18_test.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"cases": len(cases), "all_equal": True}, sort_keys=True))


if __name__ == "__main__":
    main()
