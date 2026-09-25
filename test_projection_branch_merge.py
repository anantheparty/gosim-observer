#!/usr/bin/env python3
"""Check exact RQ0004 branch-DP reuse against independent evaluations."""

from __future__ import annotations

import json
from pathlib import Path

import bounds_request_projection_k10 as full
from bounds_request_projection_ring import conditional_projected_dp_ring
from projection_branch_merge import two_equivalent_branches


K14 = full.BASE_KEYS + ("T00048", "T00032", "T00016", "T00010", "T00047", "T00011")
FIELDS = (
    "conditional_upper_cents", "external_cents", "request_cents",
    "theta_constant_cents", "dp_cents", "required_key_mask",
    "mandatory_key_mask", "key_deadline_unit", "rq0004_tile",
)


def main() -> None:
    data, certs = full._load_audited_data(full.PRICE_FILE)
    inputs = full._instance_inputs(data)
    checks = []
    for keys, saved_path in (
        (full.BASE_KEYS, Path("results/practice_projection_ring_k8.json")),
        (K14, Path("results/practice_projection_ring_k14.json")),
    ):
        rows, audit = two_equivalent_branches(
            data, inputs, keys, 135, conditional_projected_dp_ring,
        )
        saved = json.loads(saved_path.read_text())
        for i in range(2):
            expected = saved["results"][i]["ring"]
            if {field: rows[i][field] for field in FIELDS} != {
                field: expected[field] for field in FIELDS
            }:
                raise AssertionError(f"K={len(keys)} branch {i} differs")
        checks.append({
            "key_count": len(keys),
            "saved_certificate": str(saved_path),
            "branches_upper_cents": [r["conditional_upper_cents"] for r in rows],
            "reuse_audit": audit,
        })
    payload = {
        "scope": "public dev-reference all-17 RQ0004 branch projection",
        "price_sha256": certs["price_sha256"],
        "checks": checks,
    }
    out = Path("results/practice_projection_branch_merge_audit.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"checks": len(checks),
                      "bounds": [r["branches_upper_cents"] for r in checks]}))


if __name__ == "__main__":
    main()
