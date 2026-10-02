# Global finite-column pricing kernel

`research/interval_column_pricing.py` prices a finite set of pointings, durations,
and shared programs for the global interval-column model. Its input
`values[duration, program, target]` is the sum of that target's science-layer,
required, and REQ coverage dual prices when the exposure reaches their thresholds.
The caller supplies full-exposure visibility and applies the time-arc dual cost.
The kernel maximizes the value in each glass and sums the glasses; it does not
divide by exposure time or sum a target's science repeatedly across exposures.

This fiber assignment is exact for the supplied geometry at zero instrument
offset: each target lands on at most one glass. Recovering assignments on CPU
retains a deterministic lowest-index tie break. Program uncertainty and quality
intervals are caller inputs, and omitted continuous pointings remain unbounded.
This is not a full problem optimum certificate or an evaluated new policy.

CUDA workspace is chunked. A 32,768-pointing, 20-duration, 3-program, 16-fiber
block needs 240 MiB for fiber maxima; only 15 MiB of column totals returns to the
host. Target tensors add storage. No RPC or model API is involved in this module.

Gate: `NUMBA_ENABLE_CUDASIM=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3
formal_v4/research/interval_column_pricing_checks.py`.

The independent oracle uses the official `FiberGrid.tangent_offsets` and
`classify_offset`, then enumerates each glass's candidate targets. Tests cover
azimuth wraparound, front/back projections, positive/zero glass gaps, differing
duration visibility, differing shared programs, and two-pointing chunk assembly.
All 72 finite columns and 72 recovered assignments pass. CUDA simulator max
error is zero; NumPy reduction error is at most 5.69e-14. Simulator wall time
was 0.129 seconds and is **not a hardware GPU performance measurement**.

The current cloud evaluation's GPU service and uploaded source are unchanged.
Hardware benchmarking and connection to global dual-column generation remain.
