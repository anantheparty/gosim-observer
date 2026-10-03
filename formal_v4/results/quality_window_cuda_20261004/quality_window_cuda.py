"""CUDA backend for the frozen finite public-score quality-window prototype.

This is a backend comparison, not a deployed actor, official score improvement,
or an upper bound on the original partially observed scheduling problem. It
consumes outcome models supplied by the reference experiment; it derives no
outcomes from future truth. Float64 arithmetic and the reference's strict
``option > current + 1e-10`` rule are preserved. Max over actions is outside the
expectation over latent outcomes. Observable-score grouping is performed with
NumPy's exact reference rounding before any GPU transfer.
"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import time

import numpy as np


@dataclass
class OutcomeModel:
    normalized_score: np.ndarray  # [W,A,S,N]
    raw_factor: np.ndarray  # [W,A,S,N]
    probabilities: np.ndarray  # [W,S]
    durations: np.ndarray  # [W,A]
    weights: np.ndarray  # [N]
    required_bonus: np.ndarray  # [N]
    threshold: float = .5

    def validate(self):
        c, g = self.normalized_score, self.raw_factor
        if c.shape != g.shape or c.ndim != 4:
            raise ValueError("outcomes must be equal [W,A,S,N] arrays")
        w, a, s, n = c.shape
        if self.probabilities.shape != (w, s) or self.durations.shape != (w, a):
            raise ValueError("probability/duration shape mismatch")
        if self.weights.shape != (n,) or self.required_bonus.shape != (n,):
            raise ValueError("target shape mismatch")
        if np.any(c < 0) or np.any(g < 0) or np.any(g > 1) or np.any(self.weights <= 0):
            raise ValueError("invalid modeled outcome")
        if not np.allclose(self.probabilities.sum(1), 1) or np.any(self.probabilities < 0):
            raise ValueError("probabilities must be nonnegative and sum to one")
        if a > 255:
            raise ValueError("uint8 policy supports at most 255 non-skip actions")


def observable_posteriors(model, window, action):
    """Match NumPy score rounding and publicly grouped threshold posterior."""
    score = np.round(model.normalized_score[window, action] * model.weights, 6)
    hit = model.raw_factor[window, action] >= model.threshold
    probability = model.probabilities[window, :, None]
    tau = np.empty_like(score)
    for r in range(len(probability)):
        same = score == score[r:r+1]
        denom = (same * probability).sum(0)
        tau[r] = np.divide((same * hit * probability).sum(0), denom,
                           out=np.zeros_like(denom), where=denom > 0)
    return score / model.weights, tau


def _torch():
    # Lazy import lets the source and CLI help be inspected without a CUDA env.
    import torch
    return torch


def _coordinates(values, bins, step):
    torch = _torch()
    x = torch.clamp(values / step, 0, bins-1)
    lo = torch.floor(x).to(torch.int64)
    hi = torch.clamp(lo+1, max=bins-1)
    return lo, hi, x-lo


def _transition(value, score, tau, bg, pg):
    torch = _torch()
    n, b, p = value.shape
    next_b = torch.maximum(score[:, None], bg[None, :])
    bl, bh, bw = _coordinates(next_b, b, 1.2/(b-1))
    next_p = pg[None, :] + (1-pg[None, :]) * tau[:, None]
    pl, ph, pw = _coordinates(next_p, p, 1/(p-1))
    # Index into each target's own state array, never into another target.
    flat = value.reshape(n, b*p)
    v00 = torch.gather(flat, 1, (bl[:, :, None]*p+pl[:, None, :]).reshape(n, -1)).reshape(n, b, p)
    v01 = torch.gather(flat, 1, (bl[:, :, None]*p+ph[:, None, :]).reshape(n, -1)).reshape(n, b, p)
    v10 = torch.gather(flat, 1, (bh[:, :, None]*p+pl[:, None, :]).reshape(n, -1)).reshape(n, b, p)
    v11 = torch.gather(flat, 1, (bh[:, :, None]*p+ph[:, None, :]).reshape(n, -1)).reshape(n, b, p)
    low = v00 * (1-pw[:, None, :]) + v01 * pw[:, None, :]
    high = v10 * (1-pw[:, None, :]) + v11 * pw[:, None, :]
    return low * (1-bw[:, :, None]) + high * bw[:, :, None]


def _prepared_observations(model, device):
    torch = _torch()
    score = np.empty_like(model.normalized_score, dtype=np.float64)
    tau = np.empty_like(score)
    w, a = score.shape[:2]
    for k in range(w):
        for j in range(a):
            score[k, j], tau[k, j] = observable_posteriors(model, k, j)
    return torch.as_tensor(score, dtype=torch.float64, device=device), torch.as_tensor(tau, dtype=torch.float64, device=device)


def solve(model, prices, *, score_bins=13, probability_bins=5,
          keep_suffix=False, keep_policy=True, device="cuda", progress=None,
          _prepared=None):
    """Rolling float64 Bellman sweep with the reference return schema.

    value and policy are NumPy arrays. The private _cuda cache retains tensors
    for expected_demand so the stored policy need not cross the device twice.
    Only two Bellman value slabs are retained when keep_suffix is false.
    """
    torch = _torch()
    model.validate()
    w, a, s, n = model.normalized_score.shape
    prices = np.asarray(prices, dtype=float)
    if prices.shape != (w,) or np.any(prices < 0):
        raise ValueError("prices must be a nonnegative window vector")
    if score_bins < 2 or probability_bins < 2:
        raise ValueError("each interpolation grid needs at least two bins")
    if torch.device(device).type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    bg_np = np.linspace(0, 1.2, score_bins)
    pg_np = np.linspace(0, 1, probability_bins)
    terminal = (model.weights[:, None, None]*bg_np[None, :, None] +
                model.required_bonus[:, None, None]*pg_np[None, None, :])
    terminal = np.broadcast_to(terminal, (n, score_bins, probability_bins)).copy()
    bg = torch.as_tensor(bg_np, dtype=torch.float64, device=device)
    pg = torch.as_tensor(pg_np, dtype=torch.float64, device=device)
    value = torch.as_tensor(terminal, dtype=torch.float64, device=device)
    score, tau = _prepared_observations(model, device) if _prepared is None else _prepared
    if tuple(score.shape) != tuple(model.normalized_score.shape) or score.device != torch.device(device):
        # torch.device('cuda') has no explicit ordinal while CUDA tensors do.
        if tuple(score.shape) != tuple(model.normalized_score.shape) or score.device.type != torch.device(device).type:
            raise ValueError("prepared observations do not match model/device")
    policy = torch.zeros((w, n, score_bins, probability_bins), dtype=torch.uint8, device=device) if keep_policy else None
    suffix = np.empty((w+1, n, score_bins, probability_bins), dtype=np.float32) if keep_suffix else None
    if suffix is not None:
        suffix[w] = terminal
    with torch.inference_mode():
        for k in range(w-1, -1, -1):
            nxt, current = value, value.clone()
            choices = torch.zeros_like(current, dtype=torch.uint8)
            for j in range(a):
                option = torch.zeros_like(current)
                for r in range(s):
                    if model.probabilities[k, r] > 0:
                        option += float(model.probabilities[k, r]) * _transition(nxt, score[k, j, r], tau[k, j, r], bg, pg)
                option -= float(prices[k] * model.durations[k, j])
                better = option > current + 1e-10
                current = torch.where(better, option, current)
                choices = torch.where(better, j+1, choices)
            value = current
            if policy is not None:
                policy[k] = choices
            if suffix is not None:
                suffix[k] = value.cpu().numpy()
            if progress is not None:
                progress(k, w)
    return dict(value=value.cpu().numpy(), policy=None if policy is None else policy.cpu().numpy(),
                suffix=suffix, score_grid=bg_np, probability_grid=pg_np,
                _cuda=dict(policy=policy, score=score, tau=tau, bg=bg, pg=pg,
                           device=str(device)))


def expected_demand(model, solved, *, normalized_best=None, completed_probability=None,
                    device="cuda", progress=None, mass_cutoff=1e-15):
    """Forward occupancy using the reference cutoff and bilinear projection.

    Float64 scatter-add can differ from NumPy add.at in summation order. The
    numerical gate reports that error independently from exact policy equality.
    """
    torch = _torch()
    if solved["policy"] is None:
        raise ValueError("demand requires stored policy")
    w, a, s, n = model.normalized_score.shape
    cache = solved.get("_cuda")
    if cache is None or cache["device"] != str(device):
        score, tau = _prepared_observations(model, device)
        cache = dict(policy=torch.as_tensor(solved["policy"], device=device), score=score, tau=tau,
                     bg=torch.as_tensor(solved["score_grid"], dtype=torch.float64, device=device),
                     pg=torch.as_tensor(solved["probability_grid"], dtype=torch.float64, device=device))
    policy, score, tau, bg, pg = [cache[k] for k in ("policy", "score", "tau", "bg", "pg")]
    b, p = len(bg), len(pg)
    bstep = float(solved["score_grid"][-1])/(b-1)
    pstep = float(solved["probability_grid"][-1])/(p-1)
    mass = torch.zeros((n, b, p), dtype=torch.float64, device=device)
    best = np.zeros(n) if normalized_best is None else np.asarray(normalized_best, dtype=float)
    complete = np.zeros(n) if completed_probability is None else np.asarray(completed_probability, dtype=float)
    if best.shape != (n,) or complete.shape != (n,):
        raise ValueError("initial public state must be target vectors")
    rows = torch.arange(n, device=device)
    bl, bh, bw = _coordinates(torch.as_tensor(best, dtype=torch.float64, device=device), b, bstep)
    pl, ph, pw = _coordinates(torch.as_tensor(complete, dtype=torch.float64, device=device), p, pstep)
    for bx, wx in ((bl, 1-bw), (bh, bw)):
        for px, wy in ((pl, 1-pw), (ph, pw)):
            mass.reshape(-1).scatter_add_(0, (rows*b+bx)*p+px, wx*wy)
    demand = torch.zeros(w, dtype=torch.float64, device=device)
    with torch.inference_mode():
        for k in range(w):
            rows, bi, pi = torch.nonzero(mass > mass_cutoff, as_tuple=True)
            prob = mass[rows, bi, pi]
            action = policy[k, rows, bi, pi]
            output = torch.zeros_like(mass)
            skip = action == 0
            outflat = output.reshape(-1)
            outflat.scatter_add_(0, (rows[skip]*b+bi[skip])*p+pi[skip], prob[skip])
            for j in range(a):
                take = action == j+1
                # No host-side any()/item() is needed for empty action fibers.
                rn, bn, pn, mn = rows[take], bi[take], pi[take], prob[take]
                if rn.numel() == 0:
                    continue
                demand[k] += mn.sum() * float(model.durations[k, j])
                for r in range(s):
                    if model.probabilities[k, r] <= 0:
                        continue
                    bl, bh, bw = _coordinates(torch.maximum(bg[bn], score[k, j, r, rn]), b, bstep)
                    pl, ph, pw = _coordinates(pg[pn]+(1-pg[pn])*tau[k, j, r, rn], p, pstep)
                    mr = mn * float(model.probabilities[k, r])
                    for bx, wx in ((bl, 1-bw), (bh, bw)):
                        for px, wy in ((pl, 1-pw), (ph, pw)):
                            outflat.scatter_add_(0, (rn*b+bx)*p+px, mr*wx*wy)
            mass = output
            if progress is not None:
                progress(k, w)
    return demand.cpu().numpy()


def query(value, normalized_best, completed_probability, score_grid, probability_grid):
    """Use the same NumPy bilinear public-state query as the reference."""
    def coords(values, grid):
        x = np.clip(values/(grid[-1]/(len(grid)-1)), 0, len(grid)-1)
        lo = np.floor(x).astype(np.int32)
        return lo, np.minimum(lo+1, len(grid)-1), x-lo
    rows = np.arange(len(normalized_best))
    bl, bh, bw = coords(np.asarray(normalized_best), score_grid)
    pl, ph, pw = coords(np.asarray(completed_probability), probability_grid)
    return ((value[rows, bl, pl]*(1-pw)+value[rows, bl, ph]*pw)*(1-bw) +
            (value[rows, bh, pl]*(1-pw)+value[rows, bh, ph]*pw)*bw)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _array_sha256(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def _rss():
    if sys.platform == "win32":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        data = Counters()
        data.cb = ctypes.sizeof(data)
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        memory_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        memory_info.restype = wintypes.BOOL
        ok = memory_info(kernel.GetCurrentProcess(), ctypes.byref(data), data.cb)
        return {"rss_bytes": int(data.WorkingSetSize), "peak_rss_bytes": int(data.PeakWorkingSetSize)} if ok else {"rss_unavailable": True}
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"peak_rss_bytes": int(peak if sys.platform == "darwin" else peak*1024)}


class NvidiaTelemetry:
    def __init__(self, path=None):
        default = shutil.which("nvidia-smi")
        if default is None and sys.platform == "win32":
            default = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/nvidia-smi.exe")
        self.path = path or default
        self.samples = []
        self.stage = "idle"
        self.process = None
        self.thread = None
        self.error = None

    def start(self):
        if self.path is None:
            self.error = "nvidia-smi unavailable"
            return
        try:
            self.process = subprocess.Popen([self.path, "--query-gpu=timestamp,power.draw,memory.used,utilization.gpu,power.limit", "--format=csv,noheader,nounits", "-lms", "500"],
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.thread = threading.Thread(target=self._read, daemon=True)
            self.thread.start()
        except OSError as error:
            self.error = str(error)

    def _read(self):
        for line in self.process.stdout:
            fields = [x.strip() for x in line.strip().split(",")]
            if len(fields) == 5:
                try:
                    self.samples.append(dict(stage=self.stage, timestamp=fields[0], power_w=float(fields[1]),
                                             memory_mib=float(fields[2]), utilization_percent=float(fields[3]), power_limit_w=float(fields[4])))
                except ValueError:
                    self.error = line.strip()

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.thread.join(timeout=5)

    def summary(self, stage):
        rows = [x for x in self.samples if x["stage"] == stage]
        return dict(samples=len(rows), max_power_w=max((x["power_w"] for x in rows), default=None),
                    mean_power_w=float(np.mean([x["power_w"] for x in rows])) if rows else None,
                    max_memory_mib=max((x["memory_mib"] for x in rows), default=None),
                    max_utilization_percent=max((x["utilization_percent"] for x in rows), default=None))


def _load_reference(path, expected_sha):
    actual = _sha256(path)
    if actual != expected_sha:
        raise ValueError(f"reference SHA256 mismatch: {actual}")
    spec = importlib.util.spec_from_file_location("frozen_window_control_reference", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_model(path):
    with np.load(path, allow_pickle=False) as data:
        keys = ("normalized_score", "raw_factor", "probabilities", "durations", "weights", "required_bonus")
        model = OutcomeModel(**{key: np.asarray(data[key], dtype=np.float64) for key in keys},
                             threshold=float(data["threshold"]) if "threshold" in data else .5)
        prices = np.asarray(data["prices"], dtype=np.float64) if "prices" in data else np.zeros(model.normalized_score.shape[0])
        extras = {key: np.asarray(data[key]) for key in ("capacity", "normalized_best", "completed_probability") if key in data}
    model.validate()
    return model, prices, extras


def _subset(model, indices):
    # The gate keeps all windows/actions/outcomes and the frozen fixture indices.
    return OutcomeModel(model.normalized_score[..., indices], model.raw_factor[..., indices], model.probabilities,
                        model.durations, model.weights[indices], model.required_bonus[indices], model.threshold)


def _progress(label):
    previous = time.perf_counter()

    def report(k, w):
        nonlocal previous
        now = time.perf_counter()
        if now-previous > 15 or k in (0, w-1):
            print(json.dumps(dict(progress=label, window=k, windows=w, elapsed_seconds=now-previous)), flush=True)
            previous = now
    return report


def _price_search(model, capacity, zero_solved, *, normalized_best=None,
                  completed_probability=None, max_bisections=32, max_kelley=32):
    """Uniform bisection then box-constrained Kelley cuts for this finite model.

    The interval/cutting-plane gaps are numerical diagnostics for this fixed
    interpolation problem. They are not certificates for the original task.
    Price oracles use positive-mass occupancy without the parity cutoff, and
    cuts include a recorded numerical slack. Ref tie tolerance is retained.
    """
    import scipy
    from scipy.optimize import linprog
    torch = _torch()
    w, a, s, n = model.normalized_score.shape
    capacity = np.asarray(capacity, dtype=float)
    if capacity.shape != (w,) or np.any(capacity < 0) or np.any(model.required_bonus < 0) or np.any(model.durations <= 0):
        raise ValueError("price box requires C>=0, bonus>=0, durations>0")
    best0 = np.zeros(n) if normalized_best is None else np.asarray(normalized_best, dtype=float)
    complete0 = np.zeros(n) if completed_probability is None else np.asarray(completed_probability, dtype=float)
    initial = dict(normalized_best=best0, completed_probability=complete0)
    rmax = float(np.max(1.2*model.weights+model.required_bonus))
    upper = rmax/model.durations.min(axis=1)
    uniform_upper = float(upper.max())
    prepared = _prepared_observations(model, "cuda")
    zero_solved["_cuda"] = dict(policy=torch.as_tensor(zero_solved["policy"], device="cuda"),
                               score=prepared[0], tau=prepared[1], device="cuda",
                               bg=torch.as_tensor(zero_solved["score_grid"], dtype=torch.float64, device="cuda"),
                               pg=torch.as_tensor(zero_solved["probability_grid"], dtype=torch.float64, device="cuda"))
    started = time.perf_counter()
    zero_demand = expected_demand(model, zero_solved, mass_cutoff=0, **initial)
    fzero = float(query(zero_solved["value"], best0, complete0, zero_solved["score_grid"], zero_solved["probability_grid"]).sum())
    zero = dict(label="zero", prices=np.zeros(w).tolist(), finite_F=fzero,
                demand=zero_demand.tolist(), total_demand=float(zero_demand.sum()),
                gradient=(capacity-zero_demand).tolist(), seconds=time.perf_counter()-started)
    logs = [zero]
    incumbent = zero
    del zero_solved["_cuda"]
    scale = max(1., abs(fzero))
    tie_epsilon = n*w*1e-10
    cut_slack = scale*1e-8
    uniform_tolerance = max(1e-6*scale, 1e-3)
    kelley_tolerance = max(1e-5*scale, 1e-3)

    def oracle(prices, label):
        nonlocal incumbent
        started = time.perf_counter()
        solved = solve(model, prices, score_bins=len(zero_solved["score_grid"]),
                       probability_bins=len(zero_solved["probability_grid"]), _prepared=prepared)
        demand = expected_demand(model, solved, mass_cutoff=0, **initial)
        f = float(query(solved["value"], best0, complete0, solved["score_grid"], solved["probability_grid"]).sum()+prices@capacity)
        row = dict(label=label, prices=prices.tolist(), finite_F=f, demand=demand.tolist(),
                   total_demand=float(demand.sum()), gradient=(capacity-demand).tolist(),
                   seconds=time.perf_counter()-started)
        logs.append(row)
        if f < incumbent["finite_F"]:
            incumbent = row
        print(json.dumps(dict(price_oracle=label, finite_F=f, total_demand=row["total_demand"],
                              total_capacity=float(capacity.sum()), seconds=row["seconds"])), flush=True)
        return row

    lower_mu, upper_mu = 0., uniform_upper
    low, high = zero, oracle(np.full(w, upper_mu), "uniform_high")
    if high["total_demand"] > 1e-8:
        raise AssertionError("safe upper price did not produce skip-only demand")
    bisection_count = 0
    if zero["total_demand"] > capacity.sum():
        for iteration in range(min(max_bisections, 32)):
            if (upper_mu-lower_mu)*capacity.sum() <= uniform_tolerance:
                break
            mu = (lower_mu+upper_mu)/2
            row = oracle(np.full(w, mu), f"uniform_bisect_{iteration}")
            bisection_count += 1
            if row["total_demand"] > capacity.sum():
                lower_mu, low = mu, row
            else:
                upper_mu, high = mu, row
    else:
        lower_mu = upper_mu = 0.
        low = high = zero
    uniform_rows = list(logs)
    uniform_best = min(uniform_rows, key=lambda row: row["finite_F"])
    uniform = dict(iterations=bisection_count, bracket=[lower_mu, upper_mu],
                   numerical_gap_limit=float((upper_mu-lower_mu)*capacity.sum()),
                   tolerance=uniform_tolerance, best=uniform_best, lower_endpoint=low,
                   upper_endpoint=high, per_window_feasibility_claim=False)

    # Retain all uniform-ray affine policy cuts. Scale μ to [0,1]^W and theta
    # by F(0), which avoids unnecessary coefficient disparities in the LP.
    cuts = list(logs)
    lp_logs = []
    numerical_lower = None
    for iteration in range(min(max_kelley, 32)):
        aub, bub = [], []
        for row in cuts:
            g = np.asarray(row["gradient"])
            mu = np.asarray(row["prices"])
            aub.append(np.r_[g*upper/scale, -1.])
            bub.append((g@mu-row["finite_F"]+cut_slack)/scale)
        lp = linprog(np.r_[np.zeros(w), 1.], A_ub=np.asarray(aub), b_ub=np.asarray(bub),
                     bounds=[(0., 1.)]*w+[(None, None)], method="highs")
        if not lp.success:
            raise RuntimeError(f"Kelley HiGHS LP failed: {lp.message}")
        numerical_lower = float(lp.fun*scale)
        numerical_upper = incumbent["finite_F"]+tie_epsilon+cut_slack
        gap = max(0., numerical_upper-numerical_lower)
        item = dict(iteration=iteration, cuts=len(cuts), numerical_lower=numerical_lower,
                    numerical_upper=numerical_upper, numerical_gap=gap, lp_status=int(lp.status),
                    lp_iterations=int(lp.nit))
        lp_logs.append(item)
        print(json.dumps(dict(kelley_lp=item)), flush=True)
        if gap <= kelley_tolerance:
            break
        mu = np.clip(lp.x[:w], 0, 1)*upper
        row = oracle(mu, f"kelley_{iteration}")
        cuts.append(row)
    return dict(scipy=scipy.__version__, safe_price_box=upper.tolist(), safe_uniform_upper=uniform_upper,
                theoretical_tie_policy_epsilon=tie_epsilon, numerical_cut_slack=cut_slack,
                occupancy_mass_cutoff=0, uniform=uniform,
                kelley=dict(max_oracles=32, oracle_calls=sum(row["label"].startswith("kelley_") for row in logs),
                            lp_iterations=lp_logs, best=incumbent, tolerance=kelley_tolerance,
                            last_numerical_lower=numerical_lower,
                            last_numerical_gap=incumbent["finite_F"]+tie_epsilon+cut_slack-numerical_lower),
                oracle_calls=len(logs)-1, logs=logs, original_problem_certificate_claim=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--reference-sha256", required=True)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--score-bins", type=int, default=25)
    parser.add_argument("--probability-bins", type=int, default=9)
    parser.add_argument("--gate-targets", type=int, default=128)
    parser.add_argument("--gate-fixture", required=True)
    parser.add_argument("--gate-sha256", required=True)
    parser.add_argument("--nvidia-smi")
    parser.add_argument("--price-only-from-full", help="Completed frozen mu0 benchmark directory")
    parser.add_argument("--isolated-python-deps", help="New isolated SciPy --target directory")
    args = parser.parse_args()
    if _sha256(args.model) != args.model_sha256:
        raise ValueError("model SHA256 mismatch")
    if _sha256(args.gate_fixture) != args.gate_sha256:
        raise ValueError("gate fixture SHA256 mismatch")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    reference = _load_reference(args.reference, args.reference_sha256)
    model, prices, extras = _load_model(args.model)
    torch = _torch()
    if not torch.cuda.is_available():
        raise RuntimeError("This benchmark requires an actual CUDA device")
    telemetry = NvidiaTelemetry(args.nvidia_smi)
    telemetry.start()
    record = dict(kind="finite_public_quality_window_backend", official_score_claim=False,
                  original_problem_upper_bound_claim=False, hidden_inputs_read=False,
                  reference_sha256=args.reference_sha256, model_sha256=args.model_sha256,
                  gate_fixture_sha256=args.gate_sha256,
                  backend_sha256=_sha256(__file__), model_shape=list(model.normalized_score.shape),
                  grids=dict(score_bins=args.score_bins, probability_bins=args.probability_bins),
                  process_id=os.getpid(), working_directory=str(Path.cwd()),
                  environment=dict(python=sys.version, platform=platform.platform(), torch=torch.__version__,
                                   cuda=torch.version.cuda, device=torch.cuda.get_device_name(0)),
                  model_npz_keys=sorted([*OutcomeModel.__dataclass_fields__, *extras, "prices"]),
                  reference_tie_tolerance=1e-10, arithmetic="float64", policy_dtype="uint8", suffix_dtype="float32")
    print(json.dumps(dict(process_id=os.getpid(), backend_sha256=record["backend_sha256"],
                          model_sha256=args.model_sha256, output=str(out))), flush=True)
    if args.price_only_from_full:
        base = Path(args.price_only_from_full)
        baseline = json.loads((base/"result.json").read_text(encoding="utf-8"))
        if baseline.get("status") != "complete" or not baseline["gate"]["passed"] or baseline["model_sha256"] != args.model_sha256 or baseline["reference_sha256"] != args.reference_sha256:
            raise ValueError("price search requires a completed frozen baseline gate")
        if "capacity" not in extras:
            raise ValueError("price search requires model capacity")
        if args.isolated_python_deps:
            sys.path.insert(0, str(Path(args.isolated_python_deps)))
        with np.load(base/"full_arrays.npz", allow_pickle=False) as data:
            zero_solved = {key: np.asarray(data[key]) for key in ("value", "policy", "score_grid", "probability_grid")}
            if np.any(data["prices"] != 0):
                raise ValueError("price baseline must use mu=0")
        telemetry.stage = "price_oracle"
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        try:
            initial = {key: extras[key] for key in ("normalized_best", "completed_probability") if key in extras}
            result = _price_search(model, extras["capacity"], zero_solved, **initial)
            record["status"] = "complete"
            record["baseline_backend_sha256"] = baseline["backend_sha256"]
            record["baseline_gate"] = baseline["gate"]
            record["prices"] = result
            record["elapsed_seconds"] = time.perf_counter()-started
            record["cuda_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
            record["cuda_peak_reserved_bytes"] = torch.cuda.max_memory_reserved()
            record["rss"] = _rss()
            record["telemetry"] = telemetry.summary("price_oracle")
            np.savez_compressed(out/"price_arrays.npz", uniform_prices=result["uniform"]["best"]["prices"],
                                uniform_demand=result["uniform"]["best"]["demand"],
                                kelley_prices=result["kelley"]["best"]["prices"],
                                kelley_demand=result["kelley"]["best"]["demand"], capacity=extras["capacity"])
        except Exception as error:
            record["status"] = "failed"
            record["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            telemetry.stop()
            record["telemetry_error"] = telemetry.error
            record["telemetry_samples"] = len(telemetry.samples)
            (out/"nvidia_telemetry.json").write_text(json.dumps(telemetry.samples, indent=2), encoding="utf-8")
            (out/"result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(dict(status=record["status"], price_oracles=record["prices"]["oracle_calls"],
                              best_finite_F=record["prices"]["kelley"]["best"]["finite_F"])), flush=True)
        return
    try:
        with np.load(args.gate_fixture, allow_pickle=False) as fixture:
            frozen_gate = {key: np.asarray(fixture[key]) for key in fixture.files}
        gate_model = _subset(model, frozen_gate["indices"])
        gate_prices = frozen_gate["prices"]
        gate_initial = {key: frozen_gate[key] for key in ("normalized_best", "completed_probability")}
        telemetry.stage = "cpu_gate"
        started = time.perf_counter()
        cpu = reference.solve(gate_model, gate_prices, score_bins=args.score_bins,
                              probability_bins=args.probability_bins, keep_suffix=True)
        cpu_demand = reference.expected_demand(gate_model, cpu, **gate_initial)
        cpu_seconds = time.perf_counter()-started
        telemetry.stage = "cuda_gate"
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        gpu = solve(gate_model, gate_prices, score_bins=args.score_bins,
                    probability_bins=args.probability_bins, keep_suffix=True)
        gpu_demand = expected_demand(gate_model, gpu, **gate_initial)
        torch.cuda.synchronize()
        gpu_seconds = time.perf_counter()-started
        value_error = float(np.max(np.abs(cpu["value"]-gpu["value"])))
        demand_error = float(np.max(np.abs(cpu_demand-gpu_demand)))
        suffix_error = float(np.max(np.abs(cpu["suffix"]-gpu["suffix"])))
        policy_diff = int(np.count_nonzero(cpu["policy"] != gpu["policy"]))
        frozen_cpu_match = (np.array_equal(cpu["value"], frozen_gate["value"]) and
                            np.array_equal(cpu["policy"], frozen_gate["policy"]) and
                            np.array_equal(cpu_demand, frozen_gate["demand"]))
        frozen_cpu_tolerant = (np.allclose(cpu["value"], frozen_gate["value"], rtol=0, atol=1e-9) and
                              np.array_equal(cpu["policy"], frozen_gate["policy"]) and
                              np.allclose(cpu_demand, frozen_gate["demand"], rtol=1e-11, atol=1e-8))
        gate_pass = frozen_cpu_tolerant and policy_diff == 0 and value_error <= 1e-9 and suffix_error <= 1e-6 and np.allclose(cpu_demand, gpu_demand, rtol=1e-11, atol=1e-8)
        record["gate"] = dict(passed=bool(gate_pass), shape=list(gate_model.normalized_score.shape),
                              cpu_seconds=cpu_seconds, cuda_seconds=gpu_seconds, max_abs_value_error=value_error,
                              max_abs_suffix_error=suffix_error, policy_differences=policy_diff,
                              max_abs_demand_error=demand_error, cpu_demand=cpu_demand.tolist(), cuda_demand=gpu_demand.tolist(),
                              frozen_cpu_fixture_exact_match=bool(frozen_cpu_match), initial_public_state_nonzero=True,
                              frozen_cpu_fixture_tolerant_match=bool(frozen_cpu_tolerant),
                              cuda_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                              cuda_peak_reserved_bytes=torch.cuda.max_memory_reserved(), rss=_rss(), telemetry=telemetry.summary("cuda_gate"))
        print(json.dumps(dict(gate=record["gate"])), flush=True)
        np.savez_compressed(out/"gate_arrays.npz", cpu_value=cpu["value"], cuda_value=gpu["value"],
                            cpu_policy=cpu["policy"], cuda_policy=gpu["policy"], cpu_demand=cpu_demand, cuda_demand=gpu_demand)
        del cpu, gpu, cpu_demand, gpu_demand, gate_model
        torch.cuda.empty_cache()
        if not gate_pass:
            raise AssertionError("CPU/CUDA finite-model consistency gate failed")
        telemetry.stage = "cuda_full_solve"
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        full = solve(model, prices, score_bins=args.score_bins, probability_bins=args.probability_bins,
                     progress=_progress("cuda_full_backward"))
        torch.cuda.synchronize()
        solve_seconds = time.perf_counter()-started
        solve_peak_allocated = torch.cuda.max_memory_allocated()
        telemetry.stage = "cuda_full_demand"
        started = time.perf_counter()
        full_initial = {key: extras[key] for key in ("normalized_best", "completed_probability") if key in extras}
        demand = expected_demand(model, full, progress=_progress("cuda_full_forward"), **full_initial)
        torch.cuda.synchronize()
        demand_seconds = time.perf_counter()-started
        best = extras.get("normalized_best", np.zeros(len(model.weights)))
        complete = extras.get("completed_probability", np.zeros(len(model.weights)))
        initial_value_sum = float(query(full["value"], best, complete, full["score_grid"], full["probability_grid"]).sum())
        record["full"] = dict(solve_seconds=solve_seconds, demand_seconds=demand_seconds,
                              total_seconds=solve_seconds+demand_seconds, value_initial_sum=initial_value_sum,
                              total_demand=float(demand.sum()), demand=demand.tolist(), prices=prices.tolist(),
                              cuda_solve_peak_allocated_bytes=solve_peak_allocated,
                              cuda_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                              cuda_peak_reserved_bytes=torch.cuda.max_memory_reserved(), rss=_rss(),
                              value_sha256=_array_sha256(full["value"]), policy_sha256=_array_sha256(full["policy"]),
                              telemetry_solve=telemetry.summary("cuda_full_solve"), telemetry_demand=telemetry.summary("cuda_full_demand"))
        if "capacity" in extras:
            record["full"]["finite_model_dual_value"] = float(initial_value_sum+prices@extras["capacity"])
            record["full"]["total_capacity"] = float(extras["capacity"].sum())
        telemetry.stage = "save"
        np.savez_compressed(out/"full_arrays.npz", value=full["value"], policy=full["policy"],
                            demand=demand, prices=prices, score_grid=full["score_grid"], probability_grid=full["probability_grid"])
        record["status"] = "complete"
    except Exception as error:
        record["status"] = "failed"
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        telemetry.stop()
        record["telemetry_error"] = telemetry.error
        record["telemetry_samples"] = len(telemetry.samples)
        (out/"nvidia_telemetry.json").write_text(json.dumps(telemetry.samples, indent=2), encoding="utf-8")
        (out/"result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(dict(status=record["status"], full=record.get("full"))), flush=True)


if __name__ == "__main__":
    main()
