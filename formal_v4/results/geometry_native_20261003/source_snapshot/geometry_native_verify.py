#!/usr/bin/env python3
"""Reproducible exact-contract checks and end-to-end ctypes benchmarks.

Verification compares the original 24 exhaustive random cases, deliberate ties,
and every exported real sweep with the frozen Numba implementation. Benchmark
mode never imports Numba and checks the precomputed exports before timing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import resource
import statistics
import sys
import time

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from research import geometry_native as native


def exhaustive(x, y, value, pitch, glass, side, radius):
    half = glass / 2 - .008
    xe = np.unique(np.concatenate([[-radius, radius]] + [
        x - (c - (side - 1) / 2) * pitch + s * half for c in range(side) for s in (-1, 1)]))
    ye = np.unique(np.concatenate([[-radius, radius]] + [
        y - (c - (side - 1) / 2) * pitch + s * half for c in range(side) for s in (-1, 1)]))
    xe = xe[(xe >= -radius) & (xe <= radius)]
    ye = ye[(ye >= -radius) & (ye <= radius)]
    xx, yy = np.meshgrid((xe[1:] + xe[:-1]) / 2, (ye[1:] + ye[:-1]) / 2, indexing="ij")
    xx, yy = xx.ravel(), yy.ravel()
    col = np.floor((x[None, :] - xx[:, None]) / pitch + side / 2).astype(int)
    row = np.floor((y[None, :] - yy[:, None]) / pitch + side / 2).astype(int)
    ok = ((col >= 0) & (col < side) & (row >= 0) & (row < side) &
          (abs(x[None, :] - xx[:, None] - (col - (side - 1) / 2) * pitch) < half) &
          (abs(y[None, :] - yy[:, None] - (row - (side - 1) / 2) * pitch) < half))
    nf, qs = side * side, len(value)
    fiber = np.clip(row, 0, side - 1) * side + np.clip(col, 0, side - 1)
    cells = np.zeros((len(xx), qs, nf))
    offset = np.arange(len(xx))[:, None, None] * qs * nf + np.arange(qs)[None, :, None] * nf + fiber[:, None, :]
    np.maximum.at(cells.ravel(), offset.ravel(), np.where(ok[:, None, :], value[None, :, :], 0).ravel())
    return cells.sum(axis=2).max(axis=0), len(xx)


def assert_match(a, b, name):
    for index, field in enumerate(("x", "y", "value")):
        if not np.array_equal(a[index].view(np.uint64), b[index].view(np.uint64)):
            difference = float(np.max(np.abs(a[index] - b[index])))
            raise AssertionError((name, field, difference, a[index].tolist(), b[index].tolist()))
    if a[3] != b[3]:
        raise AssertionError((name, "visited", a[3], b[3]))


def random_cases():
    rng = np.random.default_rng(4771)
    for test in range(24):
        n, side, pitch = 6 + test % 13, 2 + test % 3, math.sqrt(.4)
        glass = pitch - (.03 if test % 2 else 0)
        radius = pitch * (.5 + (test % 4) * .35)
        x = rng.uniform(-pitch * side / 2 - radius, pitch * side / 2 + radius, n)
        y = rng.uniform(-pitch * side / 2 - radius, pitch * side / 2 + radius, n)
        value = rng.uniform(0., 3., (4, n))
        value[rng.random(value.shape) < .2] = 0
        yield str(test), (x, y, value, pitch, glass, side, radius, 2)


def tie_cases():
    pitch, side = math.sqrt(.4), 4
    coords = np.array([0., 0., pitch / 2, pitch / 2, -pitch / 2, -pitch / 2, pitch, -pitch])
    for keep in (1, 2, 3, 7):
        for mode in ("equal", "zero", "ulp", "negative"):
            values = np.ones((3, len(coords)))
            if mode == "zero": values[:] = 0
            elif mode == "ulp": values[1, ::2] = np.nextafter(1., 2.)
            elif mode == "negative": values[2] = -1
            yield f"{mode}_keep{keep}", (coords, coords[::-1], values, pitch, pitch, side, pitch, keep)
    yield "empty_targets", (np.empty(0), np.empty(0), np.empty((2, 0)), pitch, pitch, side, pitch, 3)
    yield "empty_queries", (coords, coords[::-1], np.empty((0, len(coords))), pitch, pitch, side, pitch, 2)
    yield "strided", (coords[::2], coords[::-2], np.ones((6, len(coords)))[::2, ::2], pitch, pitch, side, pitch, 2)


def frozen_cases(root):
    for path in sorted((root / "labels").glob("*/*.npz")):
        if path.name.startswith("."):
            continue
        card = path.parent.name
        config = json.loads((BASE / "upstream/gosim-observer-examples/local-cards" / card / "config/v4_fiber_config.json").read_text())
        field = config["field"]
        # initialize_payload publishes six-decimal dimensions, which are the
        # planner's actual input (v4_workflow.py, instrument payload).
        glass = round(math.sqrt(float(field["fiber_area_deg2"])), 6)
        pitch = round(math.sqrt(float(field["fiber_area_deg2"])) + float(field.get("gap_deg", 0)), 6)
        side = math.isqrt(int(field["n_fibers"]))
        with np.load(path) as data:
            args = (data["x"], data["y"], data["values"], pitch, glass, side, float(data["radius"]), data["bx"].shape[1])
            expected = (data["bx"], data["by"], data["bv"])
        yield path, args, expected


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe():
    native.load_library()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return dict(system=platform.platform(), machine=platform.machine(), python=sys.version,
                numpy=np.__version__, library=str(native._LIB_PATH), library_sha256=digest(native._LIB_PATH),
                source_sha256={name: digest(BASE / "research" / name) for name in
                               ("geometry_native.cpp", "geometry_native.py", "geometry_native_verify.py")},
                max_rss_bytes=rss * (1 if platform.system() == "Darwin" else 1024))


def verify(root, without_numba=False):
    corpus_path = BASE / "results/geometry_native_20261003/reference_contract_cases.npz"
    if without_numba:
        corpus = np.load(corpus_path)
        reference = None
    else:
        from research.candidate_geometry_sweep import weighted_sweep as reference
        corpus = {}
    def contract_inputs(index, generated):
        if reference is not None:
            return generated
        prefix = f"case{index}_"
        # NumPy uniform's last-bit arithmetic can differ between versions and
        # platforms. Reuse the exact original float64 inputs for ABI parity.
        pitch, glass, side, radius, keep = corpus[prefix + "parameters"]
        return (corpus[prefix + "x"], corpus[prefix + "y"], corpus[prefix + "values"],
                float(pitch), float(glass), int(side), float(radius), int(keep))
    def contract_reference(index, args):
        prefix = f"case{index}_"
        if reference is None:
            for field, actual in zip(("x", "y", "values"), args[:3]):
                assert np.array_equal(actual, corpus[prefix + field]), (index, "input", field)
            assert np.array_equal(np.asarray(args[3:]), corpus[prefix + "parameters"])
            return (corpus[prefix + "bx"], corpus[prefix + "by"], corpus[prefix + "bv"], int(corpus[prefix + "visited"]))
        result = reference(*args)
        corpus.update({prefix + field: value for field, value in zip(("x", "y", "values"), args[:3])})
        corpus.update({prefix + field: value for field, value in zip(("bx", "by", "bv", "visited"), result)})
        corpus[prefix + "parameters"] = np.asarray(args[3:])
        return result
    records, ties, real = [], [], []
    for index, (name, args) in enumerate(random_cases()):
        args = contract_inputs(index, args)
        expected, visited = exhaustive(*args[:-1])
        a, b = contract_reference(index, args), native.weighted_sweep(*args)
        assert_match(a, b, name)
        error = float(np.max(np.abs(b[2][:, 0] - expected)))
        assert error < 1e-10 and b[3] == visited, (name, error, visited, b[3])
        records.append(dict(test=name, targets=len(args[0]), side=args[5], cells=visited, max_exhaustive_error=error))
    for index, (name, args) in enumerate(tie_cases(), start=len(records)):
        args = contract_inputs(index, args)
        a, b = contract_reference(index, args), native.weighted_sweep(*args)
        assert_match(a, b, name)
        ties.append(dict(test=name, cells=b[3]))
    for index, (path, args, expected) in enumerate(frozen_cases(root)):
        b = native.weighted_sweep(*args)
        if reference is not None:
            assert_match(reference(*args), b, str(path))
        for field in range(3):
            assert np.array_equal(b[field].view(np.uint64), expected[field].view(np.uint64)), (str(path), "export", field)
        real.append(dict(path=str(path.relative_to(BASE)), sha256=digest(path), targets=len(args[0]),
                         queries=len(args[2]), cells=b[3], bit_identical=True))
        if index % 100 == 0: print(json.dumps(dict(event="verified_frozen", completed=index + 1)), flush=True)
    assert real, "No real frozen sweeps found"
    if reference is not None:
        corpus_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(corpus_path, **corpus)
    return dict(all_passed=True, exhaustive=records, deterministic_ties=ties, frozen=real,
                reference="precomputed Numba corpus plus frozen exports" if without_numba else "Numba direct plus frozen exports",
                reference_corpus_sha256=digest(corpus_path),
                summary=dict(exhaustive_tests=len(records), tie_tests=len(ties), frozen_tests=len(real),
                             compared_cells=sum(x["cells"] for x in records + ties + real),
                             max_exhaustive_error=max(x["max_exhaustive_error"] for x in records),
                             centers_values_visited_bit_identical=True), runtime=describe())


def benchmark(root, repeats, limit, compare_numba=False):
    # Sample each card across its entire trajectory, including first and last.
    all_cases = list(frozen_cases(root))
    cases = []
    for card in sorted({path.parent.name for path, _, _ in all_cases}):
        group = [case for case in all_cases if case[0].parent.name == card]
        selected = np.unique(np.rint(np.linspace(0, len(group) - 1, min(limit, len(group)))).astype(int))
        cases.extend(group[i] for i in selected)
    records = []
    first_call_seconds = None
    reference = None
    if compare_numba:
        from research.candidate_geometry_sweep import weighted_sweep as reference
    for path, args, expected in cases:
        begin = time.perf_counter()
        got = native.weighted_sweep(*args)
        if first_call_seconds is None:
            first_call_seconds = time.perf_counter() - begin
        for field in range(3): assert np.array_equal(got[field].view(np.uint64), expected[field].view(np.uint64)), (str(path), field)
        elapsed = []
        for _ in range(repeats):
            begin = time.perf_counter()
            native.weighted_sweep(*args)
            elapsed.append(time.perf_counter() - begin)
        record = dict(path=str(path.relative_to(BASE)), targets=len(args[0]), queries=len(args[2]),
                      cells=got[3], samples_seconds=elapsed, median_seconds=statistics.median(elapsed))
        if reference is not None:
            assert_match(reference(*args), got, str(path))
            reference_elapsed = []
            for _ in range(repeats):
                begin = time.perf_counter(); reference(*args); reference_elapsed.append(time.perf_counter() - begin)
            record["numba_samples_seconds"] = reference_elapsed
            record["numba_median_seconds"] = statistics.median(reference_elapsed)
            record["speedup_over_numba"] = record["numba_median_seconds"] / record["median_seconds"]
        records.append(record)
    medians = [row["median_seconds"] for row in records]
    return dict(all_export_checks_passed=True, includes="NumPy input validation/conversion, output allocation, ctypes and native kernel",
                repeats=repeats, records=records, summary=dict(cases=len(records), first_call_seconds=first_call_seconds,
                median_seconds=statistics.median(medians), p95_seconds=float(np.quantile(medians, .95)),
                max_seconds=max(medians), total_sample_seconds=sum(sum(row["samples_seconds"]) for row in records)),
                runtime=describe())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("verify", "benchmark"), default="verify")
    parser.add_argument("--reference-root", type=Path, default=BASE / "results/candidate_geometry_20261003")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--cases-per-card", type=int, default=12)
    parser.add_argument("--without-numba", action="store_true", help="Use the saved Numba corpus and frozen exports")
    parser.add_argument("--compare-numba", action="store_true", help="Benchmark the reference too (imports Numba)")
    args = parser.parse_args()
    result = verify(args.reference_root, args.without_numba) if args.mode == "verify" else benchmark(args.reference_root, args.repeats, args.cases_per_card, args.compare_numba)
    output = args.output or BASE / "results/geometry_native_20261003" / f"{args.mode}_{platform.system().lower()}_{platform.machine()}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(output=str(output), **result["summary"])), flush=True)


if __name__ == "__main__":
    main()
