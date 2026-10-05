# Formal v4 observer research

**Current final version (online mean 33494.59):** see [`pleiades/README_ZH.md`](pleiades/README_ZH.md).
The agent in `pleiades/agent/` is byte-identical to the submitted package `o4e_c17w5`. The rest of this
file describes the team's earlier exact-optimization line (`agent.py` / `policy.py` in this directory).

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
| L1 | 4345.449534 | 6096.185388 |
| L2 | 4062.915709 | 6534.787015 |
| L3 | 4113.401043 | 5633.730701 |
| L4 | 3334.339522 | 5869.556485 |

All current runs completed the survey within the 900-second budget and incurred
zero report penalties. All four current runs use the frozen
`cpu_calendar_witness_20261003` source manifest; their mean is 6033.564897.
Earlier source snapshots remain in `results/` for comparison. These are local engine scores,
not platform scores. The official engine is verified against its release hashes.

`research/benchmark_suite.py` freezes the source before a run. Raw output and
runtime credentials live under ignored `runs/`; compact reports live in `results/`.
The official L1–L4 truth is included only to reproduce the local evaluator.

The first complete external HTTPS/GPU L1 replay scored 6011.251392 in 898.64
seconds. A direct PRO6000 L1 replay of the older calibrated policy scored
6348.155319 in 383.618 seconds. These use the same older policy snapshot;
they are not a controlled comparison against the newer CPU table above.
The optional remote-call allocator now reserves local completion time and
uses measured complete network round trips rather than GPU kernel time.
Its deadline forecast is empirical, not a hard runtime bound. The platform
public check and first complete practice evaluation both failed CD2 DNS
resolution and used the CPU fallback; online GPU access is not established.
An independent CD2 HTTPS relay reduced measured warm full-decision round trips
from .8711s to .4916s. Four complete local replays scored 6365.337882,
6780.821386, 5679.216893 and 6038.977937 (mean 6216.0885245), in 354–448s
per card. These are local L1–L4 results; network measurements and deployment
boundaries are in `research/REMOTE_COMPUTE_ZH.md`.

The separately downloaded alpha–delta ZIPs on 2026-10-03 contained six public
configuration/catalog/calendar files each. They did not contain weather, events
or forecast products; local exact replay of those cloud cards is therefore not
available from these archives.

## First platform practice evaluation

The private project `Observer Search CD2` completed all four platform cards on
2026-10-03 JST. One evaluation batch was used; the UI showed four daily attempts
remaining after completion. No remarks or design materials were added.

| Platform card | Total | Required missing | Requests | Accounted seconds |
|---|---:|---:|---:|---:|
| alpha | 7094.664204 | 3 | 1/2 | 230.894 |
| beta | 6333.107019 | 9 | 1/2 | 254.541 |
| gamma | 6547.568316 | 3 | 1/2 | 317.276 |
| delta | 4818.222318 | 19 | 1/2 | 276.141 |
| Mean | 6198.39046425 | | | |

Every card reported `survey_complete`, +100 report settlement and zero remote
calls. The first request failed on every card, while the second succeeded.
Gamma and delta included retrospective data invalidation. Full official
outputs, original download hashes and normalized archive hashes are in
`results/cloud_cd2_{alpha,beta,gamma,delta}_20261003/`; the batch summary is in
`results/cloud_cd2_practice_20261003/`. These are different datasets from L1–L4.

A subsequent free public check used literal-IP TCP with verified hostname TLS.
It failed immediately with `OSError errno=101` (network unreachable), not DNS;
the quota remained four. See `research/IP_TRANSPORT_ZH.md`. The platform's
current runtime cannot reach this external GPU route.

## Latest platform evaluation (2026-10-03 JST)

`Observer Verified Portfolio` completed the four practice cards with a displayed
exact mean **6714.98391975**, improving on the previous complete batch mean of
6532.68247925 by 182.30144050. The card scores are 7279.188726, 6571.727518,
6585.932678 and 6423.086757. All four completed the survey. Official downloads
are archived under `results/cloud_verified_portfolio_{card}_20261003/`; all
published output hashes and nested workflow reports match. These measured scores differ from the historical componentwise mean
6836.95278225; that arithmetic value was never a new-package measurement.

The Request cache package completed a scored four-card evaluation started at
20:10 JST, with measured mean **6735.09250250** (+20.10858275 over the Portfolio).
Alpha/beta reached the 900-second deadline; gamma/delta completed. Alpha and beta
retain the complete original Request action prefixes and continue further;
delta's actions/decisions/messages/observations/score_report are byte-identical.
Gamma differs from action index 101; its cause has not been established. All
four published output-hash checks passed. This package uses zero remote calls.
The platform shows a practice daily limit of eight; six evaluations remain.
See `results/cloud_request_cache_batch_20261003/`. No remarks or design materials
were supplied.

The latest mathematical records cover a 1376-column incumbent-based alpha
master, full optimal-face dual stabilization, and actual GPU column pricing.
They have not established a global optimum or an additional measured score.
See their result READMEs for assumptions and finite-model coverage.

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
`PUBLIC_SEED_AUDIT_ZH.md` records the positive control and the explicitly
bounded public-seed candidate search.

The public generator isolates random streams with SHA-256. Catalogue observations
do not directly reveal the weather stream; no master-seed recovery has been
demonstrated.

## Private source backup

https://github.com/anantheparty/gosim-observer

Upstream attribution and licensing are recorded in `ATTRIBUTION.md`.
