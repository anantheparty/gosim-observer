#!/usr/bin/env python3
"""Focused K17 bit16 semantics after widening actionable masks to uint32."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from bounds_request_projection_k10 import NEG_INF
from test_projection_high_bit import solve


def main() -> None:
    high = np.uint32(65536)
    masks = []
    for mask, expected in ((0, True), (65536, False), (131071, False)):
        actual = bool(int(high) & (~mask))
        if actual != expected:
            raise AssertionError(f"bit16 wait predicate failed for mask {mask}")
        masks.append({"mask": mask, "bit16_actionable_and_unfinished": actual})
    definitions = (
        ("first_and_tagged_revisit", {"tagged_repeat": True, "deadline_unit": 1}, 100),
        ("untagged_revisit_disallowed", {"tagged_repeat": False, "deadline_unit": 1}, 55),
        ("first_after_deadline_forbidden", {"tagged_repeat": True, "deadline_unit": 0}, NEG_INF),
        ("required_bit16_terminal_penalty", {
            "tagged_repeat": False, "deadline_unit": 0,
            "include_first": False, "required": True, "mandatory": False,
        }, -100000),
    )
    cases = []
    for name, kwargs, expected in definitions:
        matrix, ring = solve(bit_index=16, **kwargs)
        if matrix != expected or ring != expected:
            raise AssertionError(f"{name}: full={matrix}, ring={ring}, expected={expected}")
        cases.append({"case": name, "expected_cents": expected,
                      "full_cents": matrix, "ring_cents": ring})
    payload = {"scope": "focused synthetic 12-cell K17 DAG",
               "actionable_mask_dtype": "uint32", "key_bit_index": 16,
               "high_bit": 65536, "mask_checks": masks, "cases": cases}
    out = Path("results/projection_bit16_k17_test.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
