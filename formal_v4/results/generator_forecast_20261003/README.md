# Generator research: completed, 2026-10-03

## Decisions

Do not adopt either tested controller. The hierarchical weather clock loses on fixed bypass24 heldout tests. The free-coupon diagnostic gains slightly on bypass24 but loses on the strong CPUPhase baseline. Native geometry combination was cancelled after the negative strong gate. Production files and Git index were not changed by this agent.

## Weather derivation and negative clock

Official generator revision `e01939d060f304c2a7cf04d9b3e46009b564fc23`, SHA256 `b4675ead09e8cf333c12841ac051786c523394d4fb3cfb0b52397ad75dcc753a`, was read alongside official contracts/workflow/runner/scorer and authorized public/local L1–L4 material. Weather has a night latent AR state, slot deviations reset from it at each night, slot-constant fields and independent slot efficiency jitter. V4 forecasts exactly project real events onto coarse touched nights; rain/storm labels do not prove `force_close` or numerical quality.

The causal two-state log-C model used public score feedback only at runtime. L1 trained parameters, L2 selected, L3/L4 held out. Fixed bypass24 deltas: L3 **-28.938401**, L4 **-73.902698**, mean **-51.420550**. A large positive timed-search L4 delta changed sign on locked repetition. See `derivation.json`, `prediction_results.json`, `summary.json`, and `fixed24_*`.

## Locked coupon experiment

Direct reports take zero simulated time, have no observe index and do not directly change exposure N. False reports alone consume free coupons; correct reports repair the active fault and restore allowance. Spending both coupons early blocked a later correct report on L1. L1 chose retaining one coupon for the existing stronger witness rule. The `.68` threshold, at least three informative fits, loss `<.5`, 7200-second evidence and 86400-second cooldown were fixed; no L3/L4 tuning was performed.

| Configuration/card | Baseline | Diagnostic reserve | Delta |
|---|---:|---:|---:|
| Bypass24 train L1 | 6096.185388 | 6132.248607 | +36.063219 |
| Bypass24 validation L2 | 6530.003371 | 6539.317975 | +9.314604 |
| Bypass24 heldout L3 | 5769.301279 | 5778.265887 | +8.964608 |
| Bypass24 heldout L4 | 5920.398486 | 5926.834160 | +6.435674 |
| **Strong phase24 L3** | **5910.930583** | **5909.315457** | **-1.615126** |
| **Strong phase24 L4** | **6095.293215** | **5912.328130** | **-182.965085** |

Strong heldout mean is **-92.290106**. Both arms use the same frozen source and fixed phase work: 24 anchors, four seeds, 50 local ranking targets, 24 boundary targets, 16 exact probes, BLAS/OMP/MKL threads 1. Each run executes 944–992 phase calls and 15104–15872 exact evaluations. All four official protocol runs completed in 247–261 seconds. Strong L4 baseline reproduces the prior score, every component/count and decision SHA256 exactly.

All added public-card diagnostics were false with zero direct settlement. The existing policy handles a false result by resetting C to seasonal quality and E to `.95`; this concrete interaction changes later estimates and exposure trajectories. Strong L4 loses 84.162233 science and adds two missing required targets (-100), partly offset by Jain. Zero direct report cost does not prove nonnegative season effect. No threshold was tuned after seeing the strong negatives.

## Mechanism checks

Real frozen-policy checks cover configured allowance 0–4, exhaustion, correct replenishment, stale/weak evidence and cooldown. An official-runner synthetic quake+fault overlap with real score fits correctly reports after three exposures, giving **+100.060943** versus the old quake-blocking policy. This validates the repair path, not production score improvement. Every completed public report is audited for nonnegative settlement, no overspend, zero time and blank observe index in `diagnostic/summary.json` and `diagnostic/strong_phase24_summary.json`.

Solver features are ordinary public constants, geometry, program, notices, score-only hits and report results. Local truth is labels/evaluation only. No LLM, GPU, external hidden access or website action.

## Stable artifacts

`final_manifest.json` records final status, source hashes, lock/config, elapsed times and the concrete reset mechanism. `final_source_hashes.json` records all final owned sources. `source_snapshot/` contains their frozen copies. `READY.json` is complete. `final_archive_manifest.json` lists exact final stable archive files/SHA256; incomplete interrupted outputs are retained locally but excluded, apart from their small start log.

The earlier 210-file `completed_archive_manifest.json`, `COMPLETED_README.md`, `COMPLETED_READY.json` and all its files remain byte-identical. Its contents describe the earlier completed weather/bypass stage; final strong-stage interpretation is here. Initial all-coupon development source is reconstructed byte-for-byte and SHA-verified against its original manifest in `diagnostic/development_source/`.
