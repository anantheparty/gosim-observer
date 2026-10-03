"""Independent executable-action checks for global_field_search_v2.

This is an offline verification harness. Prefix raw factors are test fixtures,
never participant inference inputs. The reference uses the official projection,
an untruncated integer-duration event family, and quota dynamic programming.
Small cases also enumerate every legal integer second and every assignment.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timedelta, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform
import sys
import time

import numpy as np

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "results/global_field_20261004"
OFFICIAL = BASE / "upstream/gosim-observer-examples"
PREFIX = BASE / "results/objective_graph_20261004"
sys.path.insert(0, str(OFFICIAL))
from runner.challenge.v4_fiber_map import (  # noqa: E402
    FiberGrid, altaz_to_radec, min_altitude_during, validate_action,
)
from runner.challenge.v4_workflow import V4Workflow  # noqa: E402

EPS = 1e-10


def full_durations(data, cfg):
    """Endpoints of every frozen-utility interval, without a 72-item cap.

    Integer bisection finds the actual threshold hit under robust+EPS, rather
    than trusting a rounded real-valued threshold. Negative bonuses require
    the last second before a hit as well as the first second after it.
    """
    low, high = map(int, cfg[3:5])
    ds = {low, high}

    def neighbors(x):
        if math.isfinite(float(x)):
            v = math.floor(float(x))
            ds.update((v - 1, v, v + 1, v + 2))

    for row in data:
        k, up = row[2:4]
        neighbors(up)
        if k <= 0:
            continue
        neighbors(1 / k)
        thresholds = []
        if row[8]:
            thresholds.append(cfg[6])
        if row[5] < cfg[8]:
            thresholds.append(cfg[8])
        if row[9] > 0:
            thresholds.append(row[10])
            neighbors(row[11])
        if cfg[12] > 0 and row[17]:
            thresholds.append(cfg[14])
            neighbors(cfg[15])
        for threshold in thresholds:
            def hit(d):
                return min(1., d * k / cfg[5]) + EPS >= threshold
            if not hit(high):
                continue
            lo, hi = low, high
            while lo < hi:
                mid = (lo + hi) // 2
                if hit(mid):
                    hi = mid
                else:
                    lo = mid + 1
            ds.update((lo - 1, lo, lo + 1))
    return np.asarray(sorted(d for d in ds if low <= d <= high), dtype=int)


def classify(data, cfg, altitude, azimuth):
    """Official vector projection with the policy's .008-degree margin."""
    side, pitch, glass = int(cfg[0]), cfg[1], cfg[2]
    grid = FiberGrid(glass * glass, max(0., pitch - glass), side * side)
    fibers = np.full(len(data), -1, dtype=int)
    for i, row in enumerate(data):
        offset = grid.tangent_offsets(row[0], row[1], altitude, azimuth)
        if offset is None:
            continue
        f, region = grid.classify_offset(*offset)
        if region != "glass":
            continue
        cn, ce = grid.fiber_center_offset(f)
        margin = glass / 2 - max(abs(offset[0] - cn), abs(offset[1] - ce))
        if margin >= .008:
            fibers[i] = f
    return fibers


def value_matrix(data, cfg, durations):
    d = np.asarray(durations, dtype=float)[:, None]
    raw = np.minimum(1., d * data[:, 2])
    robust = np.minimum(1., d * data[:, 2] / cfg[5])
    terminal = np.zeros_like(raw)
    terminal += ((data[:, 8] > 0) & (robust + EPS >= cfg[6])) * cfg[7]
    terminal += ((data[:, 5] < cfg[8]) & (robust + EPS >= cfg[8])) * data[:, 12]
    terminal += ((data[:, 9] > 0) & (robust + EPS >= data[:, 10]) &
                 (d <= data[:, 11])) * data[:, 9]
    eligible = np.zeros_like(raw, dtype=bool)
    if cfg[12] > 0:
        eligible = ((data[:, 17] > 0) & (robust + EPS >= cfg[14]) &
                    (d <= cfg[15]) & (d <= data[:, 3]))
        terminal -= eligible * (cfg[13] / cfg[12])
    science = np.maximum(0., data[:, 6][None, None, :] * raw[:, None, :] *
                         data[:, 14:17].T[None, :, :] - data[:, 4][None, None, :])
    values = (science + terminal[:, None, :]) * data[:, 7][None, None, :]
    values = np.where((d <= data[:, 3])[:, None, :], values, -np.inf)
    return values, eligible


def totals_dp(values, eligible, fibers, cfg):
    """Maximize the frozen single-focus utility by eligible-count DP.

    This intentionally preserves the frozen policy's rule: when completion
    is possible, choose baseline or completion; otherwise price partial quota.
    It does not reuse the native regret-sort calculation.
    """
    nf, left = int(cfg[0]) ** 2, int(cfg[12])
    base = np.zeros(values.shape[:2])
    if left <= 0:
        for f in range(nf):
            ids = np.flatnonzero(fibers == f)
            if len(ids):
                base += np.maximum(0., values[:, :, ids].max(axis=2))
        return base
    quota = min(left, nf)
    dp = np.full((*values.shape[:2], quota + 1), -np.inf)
    dp[:, :, 0] = 0.
    count_available = np.zeros(values.shape[0], dtype=int)
    for f in range(nf):
        ids = np.flatnonzero(fibers == f)
        if not len(ids):
            continue
        v, e = values[:, :, ids], eligible[:, None, ids]
        plain = np.maximum(0., np.where(~e, v, -np.inf).max(axis=2))
        focus = np.where(e, v, -np.inf).max(axis=2)
        base += np.maximum(0., v.max(axis=2))
        count_available += np.isfinite(focus[:, 0])
        nxt = dp + plain[:, :, None]
        for q in range(quota + 1):
            nq = min(quota, q + 1)
            nxt[:, :, nq] = np.maximum(nxt[:, :, nq], dp[:, :, q] + focus)
        dp = nxt
    can_complete = (left <= nf) & (count_available >= left)
    completion = np.maximum(base, dp[:, :, quota] + cfg[13])
    credit = np.arange(quota + 1) * cfg[13] / left
    partial = (dp + credit).max(axis=2)
    return np.where(can_complete[:, None], completion, partial)


def optimum(data, cfg, altitude, azimuth, durations=None):
    fibers = classify(data, cfg, altitude, azimuth)
    durations = full_durations(data[fibers >= 0], cfg) if durations is None else np.asarray(durations)
    values, eligible = value_matrix(data, cfg, durations)
    totals = totals_dp(values, eligible, fibers, cfg)
    rates = totals / durations[:, None]
    max_rate = float(rates.max())
    tied = rates >= max_rate - EPS * max(1., max_rate)
    flat = int(np.argmax(np.where(tied, totals, -np.inf)))
    di, program = divmod(flat, 3)
    return dict(rate=float(rates[di, program]), max_rate=max_rate,
                total=float(totals[di, program]), duration=int(durations[di]),
                program=program, family_size=len(durations))


def action_utility(data, cfg, altitude, azimuth, duration, program, assignment):
    fibers = classify(data, cfg, altitude, azimuth)
    values, eligible = value_matrix(data, cfg, [duration])
    occupied, count, total = set(), 0, 0.
    for f, i in enumerate(assignment):
        if i < 0:
            continue
        assert i < len(data) and i not in occupied, (f, i, len(data))
        occupied.add(i)
        assert fibers[i] == f, (f, i, fibers[i])
        assert duration <= data[i, 3], (i, duration, data[i, 3])
        total += float(values[0, program, i])
        count += bool(eligible[0, i])
    left = int(cfg[12])
    if left:
        available = len(set(fibers[eligible[0] & (fibers >= 0)]))
        can_complete = left <= int(cfg[0]) ** 2 and available >= left
        total += cfg[13] if can_complete and count >= left else (
            cfg[13] / left * min(left, count) if not can_complete else 0.)
    return total


def brute_assignments(data, cfg, altitude, azimuth, duration, program):
    fibers = classify(data, cfg, altitude, azimuth)
    choices = [[-1] + np.flatnonzero((fibers == f) & (duration <= data[:, 3])).tolist()
               for f in range(int(cfg[0]) ** 2)]
    count = math.prod(map(len, choices))
    assert count <= 200000, count
    return max(action_utility(data, cfg, altitude, azimuth, duration, program, a)
               for a in itertools.product(*choices))


def conservative_upper(data, cfg):
    """Verification-only safe per-target upper; deliberately loose."""
    gain = np.maximum(0., data[:, 6] * data[:, 14:17].max(axis=1) - data[:, 4])
    gain += (data[:, 8] > 0) * max(0., cfg[7])
    gain += (data[:, 5] < cfg[8]) * np.maximum(0., data[:, 12])
    gain += np.maximum(0., data[:, 9])
    if cfg[12] > 0:
        gain += (data[:, 17] > 0) * max(0., cfg[13] / cfg[12])
    return gain * np.maximum(1., data[:, 7]) / cfg[3] + 1e-9


def config(tmax=3600, nodes=96, offset=(0., 0.)):
    return np.asarray([4, math.sqrt(.4), math.sqrt(.4), 60, tmax, 1.1,
                       .5, 50., .5, 0., nodes, 1, 0, 0., .5, 1800.,
                       70., 74., *offset], dtype=float)


def target_at(alt, az, north=0., east=0.):
    a, z = map(math.radians, (alt, az))
    v = np.asarray([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])
    n = np.asarray([-math.sin(a) * math.cos(z), -math.sin(a) * math.sin(z), math.cos(a)])
    e = np.asarray([-math.sin(z), math.cos(z), 0.])
    t = v + math.radians(north) * n + math.radians(east) * e
    t /= np.linalg.norm(t)
    return math.degrees(math.asin(t[2])), math.degrees(math.atan2(t[1], t[0])) % 360


def random_case(rng, trial):
    tmax = int(rng.integers(60, 3601)) if trial % 3 else [60, 61, 66, 120][trial % 4]
    cfg = config(tmax, offset=(float(rng.uniform(-.3, .3)), float(rng.uniform(-1, 1))))
    n = int(rng.integers(8, 25))
    data = np.zeros((n, 18))
    az = 359.9 if trial % 2 else 10.
    for i in range(n):
        f = int(rng.integers(16)); row, col = divmod(f, 4)
        data[i, :2] = target_at(72., az, (row - 1.5) * cfg[1] + rng.uniform(-.15, .15),
                              (col - 1.5) * cfg[1] + rng.uniform(-.15, .15))
    data[:, 2] = np.exp(rng.uniform(math.log(.00015), math.log(.025), n))
    data[:, 3] = rng.choice([59.999, 60., 60.001, tmax - .001, tmax, tmax + .001, 3600.], n)
    data[:, 4] = rng.uniform(0., 8., n)
    data[:, 5] = rng.choice([0., .49, .5, 1.], n)
    data[:, 6] = rng.uniform(1., 12., n)
    data[:, 7] = rng.uniform(1., 2., n)
    data[:, 8] = rng.random(n) < .3
    data[:, 9] = rng.choice([0., 5., 20.], n)
    data[:, 10] = rng.choice([.3, .5, .9], n)
    data[:, 11] = rng.choice([59.9, 60., 66., tmax, 3600.], n)
    data[:, 12] = rng.uniform(-12., 5., n)
    data[:, 14:17] = 1.
    for i, p in enumerate(rng.integers(0, 3, n)):
        data[i, 14 + p] = [1.2, 1.12, 1.06][p]
    if trial % 2:
        cfg[12:16] = [rng.choice([1, 2, 5, 16, 17]), 60., rng.choice([.3, .5, .9]),
                      rng.choice([60., 66., tmax, 1800.])]
        data[:, 17] = rng.random(n) < .6
    data[:, 13] = conservative_upper(data, cfg)
    return np.ascontiguousarray(data), cfg, (72., az)


def load_library(path):
    lib = ctypes.CDLL(str(path))
    arr = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
    lib.global_field_search_v2.argtypes = [ctypes.c_int, arr, arr, arr, arr]
    lib.global_field_search_v2.restype = ctypes.c_int
    lib.global_field_point_action_v2.argtypes = [ctypes.c_int, arr, arr, ctypes.c_double, ctypes.c_double, arr]
    lib.global_field_point_action_v2.restype = ctypes.c_double
    lib.global_field_bound_v2.argtypes = [ctypes.c_int, arr, arr, arr]
    lib.global_field_bound_v2.restype = ctypes.c_double
    lib.global_field_mask_v2.argtypes = [ctypes.c_double] * 6 + [ctypes.c_int, ctypes.c_double, ctypes.c_double]
    lib.global_field_mask_v2.restype = ctypes.c_uint
    return lib


def native_search(lib, data, cfg):
    out, stats = np.full(22, np.nan), np.zeros(8)
    started = time.perf_counter()
    count = lib.global_field_search_v2(len(data), np.ascontiguousarray(data), np.ascontiguousarray(cfg), out, stats)
    return count, out, stats, time.perf_counter() - started


def verify_native_action(data, cfg, out, initial=None, now=None, indices=None):
    rate, alt, az, duration, program, total = out[:6]
    assert math.isfinite(rate) and rate > cfg[9] + EPS, (rate, cfg[9])
    assert duration == int(duration) and int(cfg[3]) <= duration <= int(cfg[4]), out[:6]
    assert program == int(program) and 0 <= program <= 2, program
    assert 0 <= alt <= 90 and 0 <= az < 360, (alt, az)
    ca, cz = round(alt - cfg[18], 7), round((az - cfg[19]) % 360, 7) % 360
    assert 0 <= ca <= 90
    assert abs((ca + cfg[18]) - alt) <= 5e-12, (ca, cfg[18], alt)
    assert abs(((cz + cfg[19] - az + 180) % 360) - 180) <= 5e-12
    assignment = out[6:6 + int(cfg[0]) ** 2]
    assert np.all(assignment == np.rint(assignment))
    assignment = assignment.astype(int)
    actual = action_utility(data, cfg, alt, az, int(duration), int(program), assignment)
    assert math.isclose(actual, total, rel_tol=2e-10, abs_tol=2e-9), (actual, total)
    assert math.isclose(actual / duration, rate, rel_tol=2e-10, abs_tol=2e-10), (actual / duration, rate)
    ref = optimum(data, cfg, alt, az)
    assert rate >= ref["max_rate"] - 3e-10 * max(1., ref["max_rate"]), (out[:6], ref)
    assert total >= ref["total"] - 3e-8 * max(1., abs(ref["total"])), (out[:6], ref)
    if initial is not None:
        geometry = official_action_check(initial, now, indices, data, cfg, ca, cz, int(duration), assignment)
    else:
        geometry = 0
    return dict(rate=float(rate), total=float(total), duration=int(duration), program=int(program),
                assigned=int(np.count_nonzero(assignment >= 0)), family_size=ref["family_size"],
                official_targets=geometry)


def official_action_check(initial, now, indices, data, cfg, ca, cz, duration, assignment):
    card_cfg = dict(field=dict(fiber_area_deg2=.4, gap_deg=0., n_fibers=16),
                    exposure=dict(min_duration_seconds=60, max_duration_seconds=3600))
    grid = FiberGrid.from_config(card_cfg)
    names = initial["targets"]["columns"]
    col = {name: i for i, name in enumerate(names)}
    rows = initial["targets"]["rows"]
    site = initial["site"]
    count, assignments = 0, {}
    for f, i in enumerate(assignment):
        if i < 0:
            continue
        row = rows[int(indices[i])]
        assignments[str(f)] = row[col["target_id"]]
        c = grid.classify_target(float(row[col["ra_deg"]]), float(row[col["dec_deg"]]), now,
                                 ca, cz, site["latitude_deg"], site["longitude_deg"], cfg[18], cfg[19])
        assert c.region == "glass" and c.fiber_id == f, (f, i, c)
        minimum = min_altitude_during(float(row[col["ra_deg"]]), float(row[col["dec_deg"]]),
                                     now, now + timedelta(seconds=duration), dict(site=site))
        assert minimum + 1e-8 >= site["minimum_altitude_deg"], (i, duration, minimum)
        count += 1
    validate_action(dict(action="observe", pointing=dict(alt_deg=ca, az_deg=cz),
                         duration_seconds=duration, assignments=assignments), card_cfg)
    return count


def prefix_case(path, nodes=96):
    _, card, rank = path.stem.split("_")
    initial = V4Workflow(OFFICIAL / "local-cards" / card).initialize_payload(900)
    names = initial["targets"]["columns"]
    weight_col = names.index("science_weight")
    weights = np.asarray([row[weight_col] for row in initial["targets"]["rows"]], dtype=float)
    records = json.loads((PREFIX / "zenith_prefix_probe.json").read_text())["records"]
    record = next(r for r in records if r["card"] == card and r["rank"] == int(rank))
    now = datetime.fromisoformat(record["now_utc"].replace("Z", "+00:00"))
    with np.load(path) as z:
        alt = np.degrees(np.arcsin(np.clip(z["vectors"][:, 2], -1, 1)))
        az = np.degrees(np.arctan2(z["vectors"][:, 1], z["vectors"][:, 0])) % 360
        cfg = config(int(z["seconds"]), nodes)
        instrument = initial["instrument"]
        cfg[:3] = [instrument["grid_side"], instrument["pitch_deg"], instrument["glass_side_deg"]]
        cfg[5] = z["safety"]
        cfg[16:18] = [max(0., initial["site"]["minimum_altitude_deg"] - 2.), 90.]
        data = np.column_stack((alt, az, z["k"], z["up"], z["scores"], z["factors"], weights,
                                z["urg"], z["missing"], z["rr"], z["rt"], z["rd"], z["ub"],
                                np.zeros(len(alt)), z["mult"].T, np.zeros(len(alt))))
        indices = np.flatnonzero((alt >= initial["site"]["minimum_altitude_deg"] + .04) &
                                 (z["up"] >= cfg[3]))
        data = np.ascontiguousarray(data[indices])
        data[:, 13] = conservative_upper(data, cfg)
    return data, cfg, initial, now, indices


def reference_checks(trials):
    rng = np.random.default_rng(2601004)
    largest = 0
    for trial in range(trials):
        data, cfg, center = random_case(rng, trial)
        events = optimum(data, cfg, *center)
        all_seconds = optimum(data, cfg, *center, durations=np.arange(int(cfg[3]), int(cfg[4]) + 1))
        assert math.isclose(events["max_rate"], all_seconds["max_rate"], rel_tol=1e-10, abs_tol=1e-10), (trial, events, all_seconds)
        assert math.isclose(events["total"], all_seconds["total"], rel_tol=1e-9, abs_tol=1e-8), (trial, events, all_seconds)
        largest = max(largest, events["family_size"])
    # Exhaust all assignments for focus complete, incomplete, and unavailable.
    assignment_cases = 0
    cfg = config(300)
    for left in (0, 1, 2, 3, 5, 17):
        cfg[12:16] = [left, 30., .5, 220.]
        data = np.zeros((6, 18))
        for i in range(6):
            f = i // 2; r, c = divmod(f, 4)
            data[i, :2] = target_at(72., 10., (r - 1.5) * cfg[1], (c - 1.5) * cfg[1])
        data[:, 2] = [.002, .004, .003, .005, .001, .008]
        data[:, 3] = [3600, 3600, 100, 3600, 3600, 200]
        data[:, 4] = [0, 1, 0, 2, 0, 2]
        data[:, 5:8] = [0., 8., 1.]
        data[:, 9:12] = [10., .5, 220.]
        data[:, 12] = -3.
        data[:, 14:17] = [1.2, 1.12, 1.06]
        data[:, 17] = [1, 0, 1, 0, 1, 0]
        fibers = classify(data, cfg, 72., 10.)
        for duration in (60, 100, 167, 200, 220, 221, 300):
            values, eligible = value_matrix(data, cfg, [duration])
            dp = totals_dp(values, eligible, fibers, cfg)[0]
            for program in range(3):
                brute = brute_assignments(data, cfg, 72., 10., duration, program)
                assert abs(dp[program] - brute) <= 1e-9, (left, duration, program, dp, brute)
                assignment_cases += 1
    # Negative uniformity step: 499 must beat both 500 and saturation.
    cfg = config(1000); cfg[5] = 1.
    data = np.zeros((1, 18)); data[0, :2] = target_at(72., 10., -.5 * cfg[1], -.5 * cfg[1])
    data[0, 2:8] = [.001, 3600., .5, 0., 2., 1.]
    data[0, 12] = -1.; data[0, 14:17] = 1.
    negative = optimum(data, cfg, 72., 10.)
    assert negative["duration"] == 499, negative
    cfg[4] = 150; data[0, 4] = 0.; data[0, 5] = 1.; data[0, 12] = 0.
    plateau = optimum(data, cfg, 72., 10.)
    assert plateau["duration"] == 150, plateau
    return dict(random_full_integer_cases=trials, assignment_enumerations=assignment_cases,
                largest_untruncated_family=largest, negative_uniform=negative, plateau=plateau)


def rank87_regression(lib=None):
    path = PREFIX / "prefix_L2_87.npz"
    data, cfg, initial, now, indices = prefix_case(path)
    center = (90., 9.298989660871635)
    ref = optimum(data, cfg, *center)
    oldpath = OUT / "global_field_search_darwin_arm64.dylib"
    if platform.system() != "Darwin":
        oldpath = OUT / "global_field_search_linux_x86_64.so"
    old = ctypes.CDLL(str(oldpath))
    arr = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
    old.global_field_point_rate.argtypes = [ctypes.c_int, arr, arr, ctypes.c_double, ctypes.c_double]
    old.global_field_point_rate.restype = ctypes.c_double
    old_rate = old.global_field_point_rate(len(data), data, cfg[:18].copy(), *center)
    assert old_rate > ref["max_rate"] + .15, (old_rate, ref)
    # Deliberately expose the old illegal family to localize the false rate.
    illegal_ds = np.unique(np.r_[full_durations(data, cfg), [300, 600, 900, 1200, 1800, 2400, 3600]])
    illegal = optimum(data, cfg, *center, durations=illegal_ds)
    assert math.isclose(old_rate, illegal["max_rate"], rel_tol=1e-9, abs_tol=1e-9), (old_rate, illegal)
    assert illegal["duration"] > cfg[4]
    result = dict(fixture=str(path), fixture_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  offline_factor_truth=True, seconds_remaining=int(cfg[4]), center=center,
                  old_native_rate=old_rate, legal_full_family=ref, illegal_old_duration=illegal["duration"],
                  false_rate_gap=old_rate - ref["rate"])
    if lib is not None:
        point = np.full(22, np.nan)
        value = lib.global_field_point_action_v2(len(data), data, cfg, *center, point)
        rounded_ref = optimum(data, cfg, point[1], point[2], durations=np.arange(60, 67))
        assert math.isclose(value, rounded_ref["rate"], rel_tol=2e-10, abs_tol=2e-10)
        result["v2_same_center"] = verify_native_action(data, cfg, point, initial, now, indices)
        count, out, stats, seconds = native_search(lib, data, cfg)
        assert count == 1, (count, stats)
        result["v2"] = verify_native_action(data, cfg, out, initial, now, indices)
        result["v2"].update(stats=stats.tolist(), native_seconds=seconds)
    return result


def native_directed_checks(lib):
    def run(name, data, cfg, center, expected_duration=None):
        data[:, 13] = conservative_upper(data, cfg)
        data = np.ascontiguousarray(data)
        point = np.full(22, np.nan)
        rate = lib.global_field_point_action_v2(len(data), data, cfg, *center, point)
        assert rate > EPS, (name, point)
        record = verify_native_action(data, cfg, point)
        exhaustive = optimum(data, cfg, point[1], point[2], durations=np.arange(60, int(cfg[4]) + 1))
        assert math.isclose(rate, exhaustive["rate"], rel_tol=2e-10, abs_tol=2e-10), (name, point, exhaustive)
        if expected_duration is not None:
            assert record["duration"] == expected_duration, (name, record)
        return dict(name=name, **record)

    cfg = config(1000); cfg[5] = 1.
    data = np.zeros((1, 18)); data[0, :2] = target_at(72., 10., -.5 * cfg[1], -.5 * cfg[1])
    data[0, 2:8] = [.001, 3600., .5, 0., 2., 1.]
    data[0, 12] = -1.; data[0, 14:17] = 1.
    results = [run("negative_uniform_predecessor", data.copy(), cfg.copy(), (72., 10.), 499)]
    cfg[4] = 150; data[0, 4] = 0.; data[0, 5] = 1.; data[0, 12] = 0.
    results.append(run("plateau_largest_total", data.copy(), cfg.copy(), (72., 10.), 150))

    cfg = config(500); cfg[5] = 1.; cfg[12:16] = [2, 60., .05, 500.]
    data = np.zeros((2, 18))
    for i in range(2):
        data[i, :2] = target_at(72., 10., -.5 * cfg[1], (i - 1.5) * cfg[1])
    data[:, 2:8] = [[.001, 101., 0., 1., 100., 1.], [.001, 100., 0., 1., 1., 4.]]
    data[:, 14:17] = 1.; data[:, 17] = 1.
    results.append(run("focus_up_successor_completion_to_partial", data.copy(), cfg.copy(), (72., 10.), 101))

    # Threshold equality under EPS can hit one integer second before naive ceil.
    cfg = config(3600); cfg[5] = 1.
    data = np.zeros((1, 18)); data[0, :2] = target_at(72., 10., -.5 * cfg[1], -.5 * cfg[1])
    data[0, 2:8] = [(.5 - .5 * EPS) / 100, 3600., 0., 1., 1., 1.]
    data[0, 8] = 1.; data[0, 14:17] = 1.
    results.append(run("epsilon_threshold_first_second", data.copy(), cfg.copy(), (72., 10.), 100))

    # Command azimuth rounding to 360 must wrap to zero before sending.
    cfg = config(150, offset=(.1, .2))
    actual_center = (72.123456749, .199999999)
    data = np.zeros((1, 18)); data[0, :2] = target_at(*actual_center, -.5 * cfg[1], -.5 * cfg[1])
    data[0, 2:8] = [.001, 3600., 0., 1., 2., 1.]; data[0, 14:17] = 1.
    results.append(run("command_az_wrap_and_alt_round", data.copy(), cfg.copy(), actual_center, 150))
    for program in range(3):
        cfg = config(150)
        data = np.zeros((1, 18)); data[0, :2] = target_at(72., 10., -.5 * cfg[1], -.5 * cfg[1])
        data[0, 2:8] = [.001, 3600., 0., 1., 2., 1.]
        data[0, 14:17] = 1.; data[0, 14 + program] = [1.2, 1.12, 1.06][program]
        record = run("program_" + str(program), data.copy(), cfg.copy(), (72., 10.), 150)
        assert record["program"] == program, record
        results.append(record)
    # Invalid command, invalid actual altitude, and no target surviving tmin.
    rejected = 0
    for center, offset, up in [((.1, 10.), (.2, 0.), 3600.),
                               ((90.2, 10.), (.3, 0.), 3600.),
                               ((72., 10.), (0., 0.), 59.999)]:
        cfg = config(60, offset=offset)
        data[0, 3] = up
        point = np.full(22, np.nan)
        rate = lib.global_field_point_action_v2(len(data), np.ascontiguousarray(data), cfg, *center, point)
        assert rate == 0., (center, offset, up, point)
        rejected += 1
    results.append(dict(name="invalid_command_actual_altitude_and_up", rejected=rejected))
    return results


def native_checks(lib, trials):
    rng = np.random.default_rng(2601004)
    records = []
    for trial in range(trials):
        data, cfg, center = random_case(rng, trial)
        point = np.full(22, np.nan)
        point_rate = lib.global_field_point_action_v2(len(data), data, cfg, *center, point)
        # The point API applies command rounding just like the search.
        pa = round(center[0] - cfg[18], 7) + cfg[18]
        pz = (round((center[1] - cfg[19]) % 360, 7) + cfg[19]) % 360
        reference = optimum(data, cfg, pa, pz, durations=np.arange(60, int(cfg[4]) + 1))
        assert math.isclose(point_rate, reference["rate"], rel_tol=2e-9, abs_tol=3e-10), (trial, point, reference)
        if point_rate > EPS:
            verify_native_action(data, cfg, point)
        count, out, stats, seconds = native_search(lib, data, cfg)
        assert count in (0, 1), (trial, count)
        if count:
            record = verify_native_action(data, cfg, out)
            record.update(trial=trial, tmax=int(cfg[4]), focus_left=int(cfg[12]), stats=stats.tolist(), seconds=seconds)
            records.append(record)
        # An impossibly high incumbent must preserve the existing action.
        high = cfg.copy(); high[9] = 1e6
        n, _, s, _ = native_search(lib, data, high)
        assert n == 0 and s[5] == 0, (trial, n, s)
    prefix_records = []
    for path in sorted(PREFIX.glob("prefix_*.npz")):
        data, cfg, initial, now, indices = prefix_case(path)
        count, out, stats, seconds = native_search(lib, data, cfg)
        assert count == 1, (path, count, stats)
        record = verify_native_action(data, cfg, out, initial, now, indices)
        record.update(fixture=path.name, stats=stats.tolist(), seconds=seconds)
        prefix_records.append(record)
    return dict(random_native_trials=trials, returned_actions=len(records), records=records,
                real_prefix_actions=prefix_records)


def native_geometry_checks(lib, boxes=400):
    rng = np.random.default_rng(2610004)
    hits = 0
    for trial in range(boxes):
        target = (float(rng.uniform(0., 90.)), float(rng.uniform(0., 360.)))
        width = float(rng.uniform(.001, 4.))
        al, ah = max(0., target[0] - width), min(90., target[0] + width)
        zl, zh = target[1] - 2 * width, target[1] + 2 * width
        cfg = config()
        mask = lib.global_field_mask_v2(*target, al, ah, zl, zh, 4, cfg[1], cfg[2])
        data = np.zeros((1, 18)); data[0, :2] = target
        for _ in range(20):
            center = (float(rng.uniform(al, ah)), float(rng.uniform(zl, zh)))
            f = classify(data, cfg, *center)[0]
            if f >= 0:
                assert mask & (1 << int(f)), (target, [al, ah, zl, zh], center, f, mask)
                hits += 1
        # Compare independently evaluated interior rates with the entire bound,
        # including the new spherical-cap target rejection in bound().
        if trial < 60:
            sample, cfg, center = random_case(rng, trial)
            box = np.asarray([70., 74., center[1] - 4., center[1] + 4.])
            bound = lib.global_field_bound_v2(len(sample), sample, cfg, box)
            for _ in range(8):
                a, z = rng.uniform(box[0], box[1]), rng.uniform(box[2], box[3])
                actual = optimum(sample, cfg, a, z)["max_rate"]
                assert bound + 2e-9 >= actual, (trial, box, bound, actual)
    return dict(official_projection_boxes=boxes, sampled_points=20 * boxes,
                interior_glass_hits=hits, mask_violations=0, bound_point_checks=480,
                bound_violations=0)


def official_altitude_samples():
    checked = 0
    nearest_margin = math.inf
    for path in sorted(PREFIX.glob("prefix_*.npz")):
        data, cfg, initial, now, indices = prefix_case(path)
        names = initial["targets"]["columns"]
        rc, dc = names.index("ra_deg"), names.index("dec_deg")
        rows, site = initial["targets"]["rows"], initial["site"]
        # Include the nearest up boundaries, plus broadly spaced public rows.
        choices = np.unique(np.r_[np.argsort(data[:, 3])[:100],
                                   np.linspace(0, len(data) - 1, 100, dtype=int)])
        for i in choices:
            row = rows[int(indices[i])]
            for duration in {60, int(min(cfg[4], math.floor(data[i, 3])))}:
                minimum = min_altitude_during(float(row[rc]), float(row[dc]), now,
                                             now + timedelta(seconds=duration), dict(site=site))
                margin = minimum - site["minimum_altitude_deg"]
                assert margin >= -1e-8, (path.name, int(indices[i]), duration, data[i, 3], minimum)
                nearest_margin = min(nearest_margin, margin)
                checked += 1
    return dict(real_prefix_altitude_samples=checked, altitude_violations=0,
                nearest_official_limit_margin_deg=nearest_margin)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path)
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--reference-only", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    result = dict(reference=reference_checks(args.trials))
    lib = None
    if not args.reference_only:
        suffix = "darwin_arm64.dylib" if platform.system() == "Darwin" else "linux_x86_64.so"
        path = args.library or OUT / "v2" / ("global_field_search_v2_" + suffix)
        lib = load_library(path)
        result["library"] = str(path)
        result["library_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        result["native"] = native_checks(lib, args.trials)
        result["directed"] = native_directed_checks(lib)
        result["geometry"] = native_geometry_checks(lib)
        result["altitude"] = official_altitude_samples()
    result["rank87"] = rank87_regression(lib)
    result.update(offline_verification=True, participant_future_truth=False,
                  scope="frozen public utility and executable actions; no season score claim")
    sources = [Path(__file__), BASE / "research/global_field_search_v2.cpp",
               OFFICIAL / "runner/challenge/v4_fiber_map.py",
               OFFICIAL / "runner/challenge/v4_runner.py",
               OFFICIAL / "runner/challenge/v4_scorer.py"]
    result["source_sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sources if p.exists()}
    target = OUT / ("v2_verify_reference.json" if args.reference_only else "v2_verify_actions.json")
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(output=str(target), reference=result["reference"], rank87=result["rank87"],
                          native=None if lib is None else dict(random_native_trials=args.trials,
                          returned_actions=result["native"]["returned_actions"],
                          real_prefix_actions=result["native"]["real_prefix_actions"])), indent=2), flush=True)


if __name__ == "__main__":
    main()
