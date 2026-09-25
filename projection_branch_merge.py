#!/usr/bin/env python3
"""Reuse an exact projected DP value when RQ0004 branches have identical inputs.

Both branches still recalculate non-key residuals independently.  The second
branch's DP is reused only after every scalar input and every branch-dependent
array has been compared with the first branch, and graph arrays have identical
objects.  If a future key set includes an RQ0004 choice tile, this assertion
will fail instead of silently reusing the value.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np

import bounds_request_projection_k10 as full


_BRANCH_ARRAY_ARGUMENTS = (8, 9, 12, 14)
_BRANCH_SCALAR_ARGUMENTS = (0, 10, 11, 13, 15)
_GRAPH_ARGUMENTS = (1, 2, 3, 4, 5, 6, 7)


def two_equivalent_branches(
    data: dict, inputs: dict, keys: tuple[str, ...], theta_cents: int,
    dp_function: Callable,
) -> tuple[list[dict], dict]:
    first_args: tuple | None = None
    first_value: int | None = None

    def compute_and_capture(*args):
        nonlocal first_args, first_value
        first_args = args
        first_value = int(dp_function(*args))
        return first_value

    first = full._conditional_bound(
        data, inputs, keys, theta_cents, 0,
        dp_function=compute_and_capture,
    )
    if not first["feasible_relaxation"] or first_args is None or first_value is None:
        raise AssertionError("first RQ0004 branch is not a valid projection")
    compared = False

    def compare_and_reuse(*args):
        nonlocal compared
        assert first_args is not None and first_value is not None
        for index in _GRAPH_ARGUMENTS:
            if args[index] is not first_args[index]:
                raise AssertionError(f"projection graph argument {index} changed")
        for index in _BRANCH_SCALAR_ARGUMENTS:
            if args[index] != first_args[index]:
                raise AssertionError(f"projection scalar argument {index} changed")
        for index in _BRANCH_ARRAY_ARGUMENTS:
            if not np.array_equal(args[index], first_args[index]):
                raise AssertionError(f"projection array argument {index} changed")
        compared = True
        return first_value

    started = time.monotonic()
    second = full._conditional_bound(
        data, inputs, keys, theta_cents, 1,
        dp_function=compare_and_reuse,
    )
    if not second["feasible_relaxation"] or not compared:
        raise AssertionError("second branch was not fully compared")
    if first["dp_cents"] != second["dp_cents"]:
        raise AssertionError("shared DP value changed")
    if first["request_cents"] != second["request_cents"]:
        raise AssertionError("all-awarded request reward changed")
    if first["theta_constant_cents"] != second["theta_constant_cents"]:
        raise AssertionError("theta constant changed")
    audit = {
        "graph_argument_identity_checks": list(_GRAPH_ARGUMENTS),
        "equal_array_argument_checks": list(_BRANCH_ARRAY_ARGUMENTS),
        "equal_scalar_argument_checks": list(_BRANCH_SCALAR_ARGUMENTS),
        "first_dp_cents": first_value,
        "second_dp_reused": True,
        "second_branch_external_difference_cents": (
            second["external_cents"] - first["external_cents"]
        ),
        "second_branch_wall_seconds": time.monotonic() - started,
    }
    return [first, second], audit
