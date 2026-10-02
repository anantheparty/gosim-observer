# Formal v4 observer research

The executable entry point is `agent.py`. It consumes the sequential v4 protocol
and retains an exposure ledger, conservative completion bounds, weather belief,
public requests and fixed-pointing calibration. Future evaluator input is not
read by the participant program.

## Solver

- Vectorized multi-start pointing search with independent per-fiber assignment.
- Joint program and exposure-duration optimization at score breakpoints.
- Exact single-request quota assignment for a fixed pointing and duration.
- Optional authenticated external CUDA search, followed by CPU refinement.
- Local fallback after bounded remote failures.

The fixed-field assignment and quota subproblems are exact under the frozen
quality model. Spatial enumeration, future quality, and season scheduling are
approximations; no global optimum has been established.

## Reproducible local evidence

| Local card | Official numerical reference | Current CPU run |
|---|---:|---:|
| L1 | 4345.449534 | 5834.604991 |
| L2 | 4062.915709 | 6618.021215 |
| L3 | 4113.401043 | 5737.082167 |
| L4 | 3334.339522 | 5334.175064 |

All current runs completed the survey within the 900-second budget and incurred
zero report penalties. L1 precedes the calibration snapshot used for L2–L4;
those three cards have a frozen source manifest. These are local engine scores,
not platform scores. The official engine is verified against its release hashes.

`research/benchmark_suite.py` freezes the source before a run. Raw output and
runtime credentials live under ignored `runs/`; compact reports live in `results/`.
The official L1–L4 truth is included only to reproduce the local evaluator.

The separately downloaded alpha–delta ZIPs on 2026-10-03 contained six public
configuration/catalog/calendar files each. They did not contain weather, events
or forecast products; local exact replay of those cloud cards is therefore not
available from these archives.

## Run and package

```sh
.venv-solver/bin/python formal_v4/research/benchmark_suite.py --label trial --cards L1 L2
.venv-solver/bin/python formal_v4/pack_submission.py --out formal_v4/runs/observer.zip
```

The submission packer uses an explicit file whitelist. It excludes official card
truth, the verification engine, logs, Git history, and server source. A separately
supplied private runtime configuration can enable the accelerator. The default
program runs locally.

## Research records

See `research/SPATIAL_OPTIMIZER_ZH.md`, `GENERATION_MODEL_ZH.md`,
`POINTING_CALIBRATION_ZH.md`, `EFFICIENCY_AND_CLOCK_ZH.md`, and
`GPU_SPATIAL_BACKEND_ZH.md` for assumptions, proofs and measurements.

The public generator isolates random streams with SHA-256. Catalogue observations
do not directly reveal the weather stream; no master-seed recovery has been
demonstrated.

## Private source backup

https://github.com/anantheparty/gosim-observer

Upstream attribution and licensing are recorded in `ATTRIBUTION.md`.
